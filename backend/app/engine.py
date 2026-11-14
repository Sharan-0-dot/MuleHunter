"""
Mule Hunter - Real-Time Streaming, Detection & Alerting Engine.

Owns:
  - Simulated clock with speed multiplier (1x-20x)
  - Streaming transaction generation drawing from generate_dataset code path
  - SlidingWindow(48h) temporal graph
  - Detection pipeline & ClusterTracker (overlap coefficient >= 0.5, 4-tick grace)
  - Calibrated XGBoost model inference & composite severity score:
      risk_score = 0.5*p + 0.5*exposure, exposure = min(1, total_amount_inr / 2,500,000)
  - Spoken summary generation, LLM polish & TTS WAV synthesis
  - Strict push order: DB persist -> Audio verify -> /ws/pi push & /ws/dashboard broadcast
  - Escalation timer monitoring Pi voice/joystick acks
  - Headless replay mode for instant high-speed evaluation (48h in seconds)
  - Zero label leakage: server-side ground truth registry kept isolated for dev/testing only
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional, Set, Tuple
import numpy as np

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import app.config as cfg
from app.config import (
    SHARED_SECRET,
    LISTEN_SECONDS,
    SIM_SPEED,
    DETECT_TICK_SIM_MINUTES,
    DETECT_TICK_WALL_SECONDS,
    LLM_TIMEOUT_SECONDS,
    WARMUP_SIM_HOURS,
    WINDOW_HOURS,
    ALERT_MIN,
    GREEN_MAX,
    YELLOW_MAX,
    get_public_base_url,
)
from app.sim.generator import (
    Account,
    Transaction,
    TransactionStream,
    generate_accounts_pool,
    generate_dataset,
)
from app.sim.attacks import inject_attack
from app.detect.window import SlidingWindow
from app.detect.patterns import detect
from app.detect.clusters import build_clusters
from app.detect.tracker import ClusterTracker, TrackedCluster
from app.detect.model import predict_risk, risk_level
from app.summary.templates import generate_template_summary
from app.summary.llm import polish_summary
from app.summary.tts import generate_audio
from app.db import (
    init_db,
    save_cluster_and_alert,
    record_pi_ack,
    get_account_historical_txs,
    list_clusters,
    get_cluster_detail,
    get_max_alert_id,
    clear_db,
)

BAND_RANKS = {"green": 1, "yellow": 2, "red": 3}


class Engine:
    def __init__(self):
        # 1. Accounts pool & account type index
        self.accounts: List[Account] = generate_accounts_pool()
        self.accounts_dict: Dict[str, Account] = {a.account_id: a for a in self.accounts}

        # 2. Simulated clock & state
        self.base_sim_time: datetime = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)
        self.sim_time: datetime = self.base_sim_time
        self.sim_speed: float = SIM_SPEED
        self.is_running: bool = False
        self.last_wall_time: Optional[float] = None

        # 3. Sliding window & detection
        self.window: SlidingWindow = SlidingWindow(window_hours=WINDOW_HOURS)
        self.tracker: ClusterTracker = ClusterTracker(
            overlap_threshold=0.50,
            max_disappeared_ticks=4,
            confirm_ticks=2,
        )
        self.last_detection_sim_time: datetime = self.base_sim_time
        self.detection_interval_sec: float = DETECT_TICK_SIM_MINUTES * 60.0
        self.tick_lock = asyncio.Lock()

        # 4. Traffic stream & attack queue
        self.stream: Optional[TransactionStream] = None
        self.pending_attack_txs: List[Transaction] = []
        self.server_ground_truth: Dict[str, dict] = {}
        self.attack_counter: int = 1

        # 5. Alerting & tracking
        # Clean startup: start alert counters fresh from 1
        self.alert_counter: int = 1
        self.cluster_alert_levels: Dict[str, str] = {}
        self.cluster_alert_versions: Dict[str, int] = {}
        self.unacked_alerts: Dict[str, dict] = {}  # alert_id -> {"pushed_at": wall_time, "escalated": bool}

        # 6. Defense actions & counters
        self.frozen_accounts: Set[str] = set()
        self.prevented_inr: float = 0.0
        self.tx_processed_count: int = 0
        self.alerts_count: int = 0
        self.tick_runtimes_ms: List[float] = []

        # 7. WebSockets connections
        self.dashboard_websockets: Set = set()
        self.pi_websockets: Set = set()
        self.auth_websockets: Dict[str, object] = {}  # challenge_id -> websocket
        self.pending_challenges: Dict[str, datetime] = {}

        # 8. Background loop task
        self.loop_task: Optional[asyncio.Task] = None
        self.detect_tick_wall_seconds: float = DETECT_TICK_WALL_SECONDS
        self.last_detection_wall_time: float = time.perf_counter()
        self.last_pi_ack: Optional[dict] = None

    def warmup(self):
        """Generates WARMUP_SIM_HOURS of legit traffic in batch to prime graph window."""
        print(f"[ENGINE] Warming up window with {WARMUP_SIM_HOURS:.1f} hours of legit traffic...")
        init_db()
        clear_db()
        self.alert_counter = 1
        self.alerts_count = 0
        self.tx_processed_count = 0
        self.window = SlidingWindow(window_hours=WINDOW_HOURS)
        self.tracker = ClusterTracker(
            overlap_threshold=0.50,
            max_disappeared_ticks=4,
            confirm_ticks=2,
        )

        txs, _ = generate_dataset(
            seed=42,
            difficulty=1,
            duration_hours=WARMUP_SIM_HOURS,
            attacks=None,
            start_ts=self.base_sim_time,
        )
        for t in txs:
            self.window.add(t)
            self.tx_processed_count += 1

        self.sim_time = self.base_sim_time + timedelta(hours=WARMUP_SIM_HOURS)
        self.window.advance(self.sim_time)
        self.last_detection_sim_time = self.sim_time

        # Initialize streaming generator linked to the exact same dataset generator
        self.stream = TransactionStream(seed=999, start_ts=self.sim_time)
        print(f"[ENGINE] Warmup complete. Prime window contains {len(txs):,} transactions across {len(self.window.active_nodes())} nodes.")

    async def start(self, speed: Optional[float] = None):
        """Starts live simulation stream."""
        if speed is not None:
            self.sim_speed = max(1.0, min(20.0, float(speed)))
        if self.stream is None:
            self.warmup()
        self.is_running = True
        self.last_wall_time = time.perf_counter()
        if self.loop_task is None or self.loop_task.done():
            self.loop_task = asyncio.create_task(self._run_loop())
        print(f"[ENGINE] Simulation started at speed {self.sim_speed:.1f}x.")

    async def stop(self):
        """Pauses live simulation stream."""
        self.is_running = False
        print("[ENGINE] Simulation paused.")

    async def reset(self):
        """Resets engine state to fresh warmup and clears DB."""
        await self.stop()
        clear_db()
        self.alert_counter = 1
        self.alerts_count = 0
        self.attack_counter = 1
        self.pending_attack_txs.clear()
        self.server_ground_truth.clear()
        self.frozen_accounts.clear()
        self.prevented_inr = 0.0
        self.cluster_alert_levels.clear()
        self.cluster_alert_versions.clear()
        self.unacked_alerts.clear()
        self.tick_runtimes_ms.clear()
        self.warmup()
        print("[ENGINE] Simulation reset to initial state.")

    def launch_attack(
        self,
        attack_type: str,
        difficulty: int,
        total_amount_inr: Optional[int] = None,
    ) -> dict:
        """Injects an attack ring starting at the current sim time."""
        atk_type = attack_type.lower().strip()
        diff = max(1, min(5, int(difficulty)))
        ring_id = f"RING-{self.attack_counter:04d}"
        rng = np.random.default_rng(seed=1000 + self.attack_counter)

        ring_txs, gt = inject_attack(
            attack_type=atk_type,
            rng=rng,
            accounts=self.accounts,
            start_ts=self.sim_time + timedelta(seconds=10),
            difficulty=diff,
            ring_id=ring_id,
            total_amount_inr=total_amount_inr,
        )

        # Queue transactions sorted by timestamp
        self.pending_attack_txs.extend(ring_txs)
        self.pending_attack_txs.sort(key=lambda t: t.ts)

        # Server-side isolated ground truth registry
        self.server_ground_truth[ring_id] = {
            "ring_id": ring_id,
            "attack_type": atk_type,
            "difficulty": diff,
            "ring_accounts": gt.ring_accounts,
            "total_amount": gt.total_amount,
            "start_ts": gt.start_ts,
            "end_ts": gt.end_ts,
            "tx_ids": {t.tx_id for t in ring_txs},
        }
        self.attack_counter += 1

        amt_str = f" ({total_amount_inr:,} INR)" if total_amount_inr else ""
        print(f"[ENGINE] Injected {atk_type} (diff {diff}{amt_str}) ring {ring_id} starting at {self.sim_time.isoformat()}.")
        return {
            "ok": True,
            "ring_id": ring_id,
            "type": atk_type,
            "difficulty": diff,
            "total_amount_inr": total_amount_inr,
            "start_ts": self.sim_time.isoformat(),
        }

    async def _run_loop(self):
        """Continuous wall-clock loop advancing simulated stream every ~500 ms."""
        while True:
            try:
                if not self.is_running:
                    await asyncio.sleep(0.5)
                    self.last_wall_time = time.perf_counter()
                    continue

                now_wall = time.perf_counter()
                dt_wall = now_wall - (self.last_wall_time or now_wall)
                self.last_wall_time = now_wall

                # Advance sim time
                dt_sim_sec = dt_wall * self.sim_speed
                new_sim_time = self.sim_time + timedelta(seconds=dt_sim_sec)

                # 1. Pull legit transactions from TransactionStream (same logic as generate_dataset)
                if self.stream is None:
                    self.stream = TransactionStream(seed=999, start_ts=self.sim_time)
                new_txs: List[Transaction] = self.stream.advance(dt_sim_sec)

                # 2. Pull scheduled attack transactions whose timestamp <= new_sim_time
                ready_attacks = []
                remaining_attacks = []
                for t in self.pending_attack_txs:
                    if t.ts <= new_sim_time:
                        ready_attacks.append(t)
                    else:
                        remaining_attacks.append(t)
                self.pending_attack_txs = remaining_attacks
                new_txs.extend(ready_attacks)
                new_txs.sort(key=lambda t: t.ts)

                # 3. Apply freeze defense filter & populate window
                accepted_txs: List[Transaction] = []
                for t in new_txs:
                    if t.src in self.frozen_accounts:
                        # Transaction blocked
                        self.prevented_inr += t.amount
                        continue
                    accepted_txs.append(t)
                    self.window.add(t)
                    self.tx_processed_count += 1

                self.sim_time = new_sim_time
                self.window.advance(self.sim_time)

                # 4. Broadcast tx_batch to /ws/dashboard
                if accepted_txs and self.dashboard_websockets:
                    batch_payload = [
                        {
                            "tx_id": t.tx_id,
                            "ts": t.ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "src": t.src,
                            "dst": t.dst,
                            "amount": round(t.amount, 2),
                        }
                        for t in accepted_txs[:50]
                    ]
                    await self._broadcast_dashboard({"type": "tx_batch", "txs": batch_payload})

                # 5. Check if it's time for a wall-clock detection tick (every DETECT_TICK_WALL_SECONDS)
                time_since_detect_wall = now_wall - self.last_detection_wall_time
                if time_since_detect_wall >= self.detect_tick_wall_seconds:
                    if not self.tick_lock.locked():
                        self.last_detection_wall_time = now_wall
                        asyncio.create_task(self._run_detection_tick())

                # 6. Check unacked Pi alerts for escalation
                await self._check_escalations()

                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"[ENGINE ERROR] in stream loop: {e}")
                await asyncio.sleep(1.0)

    async def _run_detection_tick(self):
        """Runs heavy graph pattern detection, clustering, XGBoost scoring & alert pipeline."""
        async with self.tick_lock:
            t0 = time.perf_counter()
            loop = asyncio.get_running_loop()

            def _detect_and_cluster():
                instances = detect(self.window, self.sim_time)
                clusters = build_clusters(instances, self.window, self.accounts_dict)
                return clusters

            clusters = await loop.run_in_executor(None, _detect_and_cluster)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self.tick_runtimes_ms.append(dt_ms)

            # Update temporal cluster tracker with calibrated risk scoring
            active_tracks = self.tracker.update(clusters, self.sim_time, risk_fn=predict_risk)

            # Evaluate each active tracked cluster using composite severity scoring
            for trk in active_tracks:
                p = trk.last_risk  # Model calibrated probability

                # Severity score: risk_score = 0.5*p + 0.5*exposure
                exposure = min(1.0, trk.total_amount / 2_500_000.0)
                risk_score = 0.5 * p + 0.5 * exposure

                # Map composite risk to urgency level
                level = risk_level(risk_score)
                # Any confirmed alert is at least green
                if p >= ALERT_MIN and level == "green" and risk_score < ALERT_MIN:
                    level = "green"

                # Alert trigger: model probability p >= ALERT_MIN (0.40)
                if p >= ALERT_MIN:
                    prev_level = trk.alerted_level
                    prev_rank = BAND_RANKS.get(prev_level, 0)
                    new_rank = BAND_RANKS.get(level, 0)

                    # First alert: requires confirm_ticks consecutive wall ticks at p >= ALERT_MIN
                    if prev_level is None:
                        if trk.consecutive_alert_ticks >= self.tracker.confirm_ticks:
                            trk.alerted_level = level
                            await self._process_alert(trk, risk_score, level, prob=p, exposure=exposure)
                    # Re-alert only on upward band jump (e.g. green -> yellow -> red)
                    elif new_rank > prev_rank:
                        trk.alerted_level = level
                        await self._process_alert(trk, risk_score, level, prob=p, exposure=exposure)
                    else:
                        # Material change without band jump: broadcast cluster_updated
                        await self._broadcast_dashboard({
                            "type": "cluster_updated",
                            "cluster_id": trk.cluster_id,
                            "risk": round(risk_score, 4),
                            "accounts_count": len(trk.accounts),
                            "total_amount": round(trk.total_amount, 2),
                        })

    async def _process_alert(
        self,
        cluster_obj: TrackedCluster,
        risk_score: float,
        level: str,
        prob: float,
        exposure: float,
        headless: bool = False,
    ) -> dict:
        """Executes the strict alert pipeline: DB -> Audio verify -> WS pushes."""
        cluster_id = cluster_obj.cluster_id
        alert_id = f"A-{self.alert_counter:04d}"
        self.alert_counter += 1
        self.alerts_count += 1

        version = self.cluster_alert_versions.get(cluster_id, 0) + 1
        self.cluster_alert_versions[cluster_id] = version
        self.cluster_alert_levels[cluster_id] = level

        span_sec = max(60.0, (cluster_obj.end_ts - cluster_obj.start_ts).total_seconds())

        # Determine source and destination if discernible
        source = None
        destination = None
        for p_inst in cluster_obj.pattern_instances:
            if p_inst.pattern_type in ("fan_out", "smurfing_fan_out_fan_in"):
                source = next(iter(p_inst.core_accounts), None)
            if p_inst.pattern_type in ("fan_in", "smurfing_fan_out_fan_in"):
                destination = p_inst.meta.get("reconvergence_dst") or next(iter(p_inst.core_accounts), None)

        # 1. Generate template summary (speaks composite risk as percent)
        template_text = generate_template_summary(
            level=level,
            accounts_count=len(cluster_obj.accounts),
            total_amount=cluster_obj.total_amount,
            span_seconds=span_sec,
            typology=cluster_obj.typology,
            risk_score=risk_score,
            source=source,
            destination=destination,
        )

        audio_path = backend_dir / "static" / "audio" / f"{cluster_id}_v{version}.wav"
        wav_url = f"{get_public_base_url()}/static/audio/{cluster_id}_v{version}.wav"
        summary_source = "template"
        llm_status = "disabled" if not cfg.LLM_ENABLED else ("no_key" if not cfg.OPENROUTER_API_KEY else "ok")
        llm_latency_ms = None
        tts_fallback = True

        if not headless:
            loop = asyncio.get_running_loop()
            facts = {
                "accounts_count": len(cluster_obj.accounts),
                "total_amount": cluster_obj.total_amount,
                "risk_pct": int(round(risk_score * 100)),
            }
            try:
                polish_future = loop.run_in_executor(None, polish_summary, template_text, facts)
                final_summary, summary_source, llm_status, llm_latency_ms = await asyncio.wait_for(
                    polish_future, timeout=cfg.LLM_TIMEOUT_SECONDS + 0.5
                )
            except asyncio.TimeoutError:
                final_summary = template_text
                summary_source = "template"
                llm_status = "timeout"
                llm_latency_ms = cfg.LLM_TIMEOUT_SECONDS * 1000.0
            except Exception as e:
                final_summary = template_text
                summary_source = "template"
                llm_status = f"exception:{type(e).__name__}"

            # 3. TTS WAV synthesis in worker thread from FINAL text
            audio_path, wav_url, tts_fallback = await loop.run_in_executor(
                None,
                generate_audio,
                cluster_id,
                final_summary,
                level,
                version,
            )
        else:
            final_summary = template_text
            # Ensure audio file exists for headless contract compliance
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            if not audio_path.exists():
                fallback_src = backend_dir / "static" / "audio" / f"{level.lower()}.wav"
                if fallback_src.exists():
                    import shutil
                    shutil.copyfile(fallback_src, audio_path)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Master 8.2 alert contract: risk_score is the composite severity
        alert_dict = {
            "alert_id": alert_id,
            "cluster_id": cluster_id,
            "level": level,
            "risk_score": round(risk_score, 4),
            "typology": cluster_obj.typology,
            "accounts_count": len(cluster_obj.accounts),
            "total_amount_inr": int(round(cluster_obj.total_amount)),
            "wav_url": wav_url,
            "listen_seconds": LISTEN_SECONDS,
            "created_at": now_iso,
        }

        # Step 1: Persist cluster + alert + window txs to SQLite
        window_txs = []
        for u in cluster_obj.accounts:
            for _, e in self.window.out_edges(u):
                window_txs.extend(e["tx_list"])

        # Attach risk components into features
        cluster_obj.features["probability"] = round(prob, 4)
        cluster_obj.features["exposure"] = round(exposure, 4)

        save_cluster_and_alert(
            alert_dict=alert_dict,
            cluster_obj=cluster_obj,
            summary_text=final_summary,
            summary_source=summary_source,
            audio_path=str(audio_path),
            llm_latency_ms=llm_latency_ms,
            tts_fallback=tts_fallback,
            window_txs=window_txs,
            llm_status=llm_status,
        )

        # Audit: log alert_created event
        from app.audit import append_audit
        append_audit("alert_created", {
            "alert_id": alert_id,
            "cluster_id": cluster_id,
            "level": level,
            "risk_score": round(risk_score, 4),
            "accounts_count": len(cluster_obj.accounts),
            "total_amount_inr": int(round(cluster_obj.total_amount)),
            "created_at": now_iso,
        })

        if not headless:
            # Step 2: Push to /ws/pi
            pi_payload = dict(alert_dict)
            pi_payload["type"] = "alert"
            await self._broadcast_pi(pi_payload)

            self.unacked_alerts[alert_id] = {
                "pushed_at": time.perf_counter(),
                "escalated": False,
            }

            # Step 3: Broadcast cluster_alert to /ws/dashboard
            dashboard_payload = dict(alert_dict)
            dashboard_payload["type"] = "cluster_alert"
            dashboard_payload["summary"] = final_summary
            dashboard_payload["summary_source"] = summary_source
            dashboard_payload["llm_status"] = llm_status
            dashboard_payload["llm_latency_ms"] = llm_latency_ms
            dashboard_payload["accounts"] = list(cluster_obj.accounts)
            dashboard_payload["features"] = cluster_obj.features
            dashboard_payload["risk_components"] = {
                "probability": round(prob, 4),
                "exposure": round(exposure, 4),
            }
            await self._broadcast_dashboard(dashboard_payload)
            print(f"[ALERT PUSHED] {level.upper()} alert {alert_id} for {cluster_id} (risk {risk_score:.2f}, {summary_source}) -> Pi & Dashboard")

        return alert_dict

    def run_headless(
        self,
        sim_hours: float,
        attacks: Optional[List[dict]] = None,
        reset_first: bool = True,
        seed: int = 50,
    ) -> dict:
        """
        Headless replay mode: Advances the SAME engine code (window, detect, clusters,
        model, tracker, alerting) with no wall-clock sleeping and no WebSockets.
        Runs 48 sim-hours in seconds.
        """
        if reset_first:
            clear_db()
            self.alert_counter = 1
            self.alerts_count = 0
            self.attack_counter = 1
            self.pending_attack_txs.clear()
            self.server_ground_truth.clear()
            self.frozen_accounts.clear()
            self.prevented_inr = 0.0
            self.cluster_alert_levels.clear()
            self.cluster_alert_versions.clear()
            self.unacked_alerts.clear()
            self.tick_runtimes_ms.clear()
            self.warmup()

        # In headless, stream uses specified seed
        self.stream = TransactionStream(seed=seed, start_ts=self.sim_time)

        # Pre-schedule any specified attacks
        scheduled_attacks = []
        if attacks:
            for atk in attacks:
                atk_type = atk.get("type", "round_trip")
                diff = atk.get("difficulty", 2)
                offset_hrs = atk.get("offset_hours", 2.0)
                tot_amt = atk.get("total_amount_inr", None)
                atk_start = self.sim_time + timedelta(hours=offset_hrs)
                ring_id = f"RING-{self.attack_counter:04d}"
                rng = np.random.default_rng(seed=2000 + self.attack_counter)
                ring_txs, gt = inject_attack(
                    attack_type=atk_type,
                    rng=rng,
                    accounts=self.accounts,
                    start_ts=atk_start,
                    difficulty=diff,
                    ring_id=ring_id,
                    total_amount_inr=tot_amt,
                )
                self.server_ground_truth[ring_id] = {
                    "ring_id": ring_id,
                    "attack_type": atk_type,
                    "difficulty": diff,
                    "ring_accounts": gt.ring_accounts,
                    "total_amount": gt.total_amount,
                    "start_ts": gt.start_ts,
                    "end_ts": gt.end_ts,
                    "tx_ids": {t.tx_id for t in ring_txs},
                }
                self.attack_counter += 1
                scheduled_attacks.append({
                    "ring_id": ring_id,
                    "start_ts": gt.start_ts,
                    "accounts": gt.ring_accounts,
                    "txs": ring_txs,
                    "alerted": False,
                    "time_to_alert_min": None,
                })

        tick_sec = self.detection_interval_sec
        total_sec = sim_hours * 3600.0
        n_ticks = int(total_sec // tick_sec)

        alerts_recorded = []
        ring_detection_times = {}

        t0_wall = time.perf_counter()

        for tick in range(n_ticks):
            step_target_time = self.sim_time + timedelta(seconds=tick_sec)

            # 1. Pull legit transactions for this tick interval
            new_txs: List[Transaction] = self.stream.advance(tick_sec)

            # 2. Inject scheduled attack transactions falling in this interval
            for atk in scheduled_attacks:
                for t in atk["txs"]:
                    if self.sim_time < t.ts <= step_target_time:
                        new_txs.append(t)

            new_txs.sort(key=lambda t: t.ts)

            # 3. Apply freeze defense filter & populate window
            for t in new_txs:
                if t.src in self.frozen_accounts:
                    self.prevented_inr += t.amount
                    continue
                self.window.add(t)
                self.tx_processed_count += 1

            self.sim_time = step_target_time
            self.window.advance(self.sim_time)

            # 4. Heavy graph pattern detection, clustering & scoring
            tick_t0 = time.perf_counter()
            instances = detect(self.window, self.sim_time)
            clusters = build_clusters(instances, self.window, self.accounts_dict)
            self.tick_runtimes_ms.append((time.perf_counter() - tick_t0) * 1000.0)

            # 5. Tracker update
            active_tracks = self.tracker.update(clusters, self.sim_time, risk_fn=predict_risk)

            # 6. Alert hygiene & composite severity scoring
            for trk in active_tracks:
                p = trk.last_risk
                exposure = min(1.0, trk.total_amount / 2_500_000.0)
                risk_score = 0.5 * p + 0.5 * exposure
                level = risk_level(risk_score)

                if p >= ALERT_MIN:
                    prev_level = trk.alerted_level
                    prev_rank = BAND_RANKS.get(prev_level, 0)
                    new_rank = BAND_RANKS.get(level, 0)

                    should_alert = False
                    if prev_level is None:
                        if trk.consecutive_alert_ticks >= self.tracker.confirm_ticks:
                            should_alert = True
                    elif new_rank > prev_rank:
                        should_alert = True

                    if should_alert:
                        trk.alerted_level = level
                        # Run alert processing synchronously in headless mode
                        alert_data = asyncio.run(
                            self._process_alert(trk, risk_score, level, prob=p, exposure=exposure, headless=True)
                        )
                        alerts_recorded.append({
                            **alert_data,
                            "sim_time": self.sim_time,
                            "accounts": set(trk.accounts),
                        })

                        # Check if this alert matched any scheduled attack ring
                        for atk in scheduled_attacks:
                            if not atk["alerted"]:
                                if len(trk.accounts & atk["accounts"]) >= 2:
                                    atk["alerted"] = True
                                    elapsed_min = (self.sim_time - atk["start_ts"]).total_seconds() / 60.0
                                    atk["time_to_alert_min"] = max(0.0, elapsed_min)

        total_wall_sec = time.perf_counter() - t0_wall

        # Categorize alerts: true alerts vs false alerts
        true_alerts = []
        false_alerts = []
        all_ring_accounts = set().union(*[atk["accounts"] for atk in scheduled_attacks]) if scheduled_attacks else set()

        for a in alerts_recorded:
            if a["accounts"] & all_ring_accounts:
                true_alerts.append(a)
            else:
                false_alerts.append(a)

        alerts_by_band = {"green": 0, "yellow": 0, "red": 0}
        for a in alerts_recorded:
            alerts_by_band[a["level"]] = alerts_by_band.get(a["level"], 0) + 1

        rings_alerted = sum(1 for atk in scheduled_attacks if atk["alerted"])
        alert_times = [atk["time_to_alert_min"] for atk in scheduled_attacks if atk["alerted"] and atk["time_to_alert_min"] is not None]

        return {
            "sim_hours": sim_hours,
            "wall_clock_sec": round(total_wall_sec, 2),
            "total_alerts": len(alerts_recorded),
            "true_alerts": len(true_alerts),
            "false_alerts": len(false_alerts),
            "false_alerts_per_sim_hour": round(len(false_alerts) / sim_hours, 3),
            "false_alerts_per_sim_day": round(len(false_alerts) / (sim_hours / 24.0), 3),
            "alerts_by_band": alerts_by_band,
            "rings_scheduled": len(scheduled_attacks),
            "rings_alerted": rings_alerted,
            "mean_detection_tick_ms": round(float(np.mean(self.tick_runtimes_ms)), 2) if self.tick_runtimes_ms else 0.0,
            "mean_time_to_alert_min": round(float(np.mean(alert_times)), 1) if alert_times else 0.0,
            "rings_detail": [
                {
                    "ring_id": atk["ring_id"],
                    "alerted": atk["alerted"],
                    "time_to_alert_min": atk["time_to_alert_min"],
                }
                for atk in scheduled_attacks
            ],
        }

    async def _check_escalations(self):
        """Sends escalate event to Pi if no voice/joystick ack within listen_seconds + 5s."""
        now_wall = time.perf_counter()
        timeout_threshold = LISTEN_SECONDS + 5.0
        for alert_id, info in list(self.unacked_alerts.items()):
            if not info["escalated"] and (now_wall - info["pushed_at"]) > timeout_threshold:
                info["escalated"] = True
                escalate_msg = {"type": "escalate", "alert_id": alert_id}
                await self._broadcast_pi(escalate_msg)
                print(f"[ESCALATION] Sent escalate for {alert_id} to Pi (no ack within {timeout_threshold}s).")
                # Audit: log escalate event
                from app.audit import append_audit
                append_audit("escalate", {"alert_id": alert_id, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})

    def handle_pi_ack(self, alert_id: str, event: str, ts: str):
        self.last_pi_ack = {"event": event, "alert_id": alert_id, "time": ts}
        """Handles acknowledgement from Pi, stores in DB, cancels escalation, and forwards to dashboard."""
        record_pi_ack(alert_id, event, ts)
        if alert_id in self.unacked_alerts:
            if event in ("explain_voice", "explain_joystick", "played", "received"):
                self.unacked_alerts.pop(alert_id, None)

        # Audit: log pi_ack event
        from app.audit import append_audit
        append_audit("pi_ack", {"alert_id": alert_id, "event": event, "ts": ts})

        asyncio.create_task(self._broadcast_dashboard({
            "type": "pi_ack",
            "alert_id": alert_id,
            "event": event,
            "ts": ts,
        }))

    async def _broadcast_dashboard(self, msg: dict):
        dead = set()
        for ws in self.dashboard_websockets:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                dead.add(ws)
        self.dashboard_websockets -= dead

    async def _broadcast_pi(self, msg: dict):
        dead = set()
        for ws in self.pi_websockets:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                dead.add(ws)
        self.pi_websockets -= dead

    def get_focused_graph(self, cluster_id: Optional[str] = None, hops: int = 1) -> dict:
        """
        Builds focused subgraph per master 8.5:
          cluster accounts + 1-hop neighbours + capped sample (<= 300) background nodes dimmed.
        """
        focus_nodes = set()
        if cluster_id:
            c_detail = get_cluster_detail(cluster_id)
            if c_detail:
                focus_nodes = set(c_detail["accounts"])

        neighbour_nodes = set()
        for u in focus_nodes:
            neighbour_nodes.update(self.window.out_adj.get(u, set()))
            neighbour_nodes.update(self.window.in_adj.get(u, set()))

        highlighted_nodes = focus_nodes | neighbour_nodes
        all_active = list(self.window.active_nodes())

        background_sample = [n for n in all_active if n not in highlighted_nodes]
        if len(background_sample) > 300:
            rng = np.random.default_rng(42)
            background_sample = list(rng.choice(background_sample, size=300, replace=False))

        included_nodes = highlighted_nodes | set(background_sample)

        nodes_list = []
        for n in included_nodes:
            stats = self.window.node_stats(n)
            acc = self.accounts_dict.get(n)
            acc_type = acc.account_type if acc else "individual"
            c_id = cluster_id if n in focus_nodes else None
            is_dimmed = (n not in highlighted_nodes) if focus_nodes else False

            nodes_list.append({
                "id": n,
                "type": acc_type,
                "risk": 0.85 if n in focus_nodes else 0.1,
                "cluster_id": c_id,
                "in_amount": round(stats["in_amount"], 2),
                "out_amount": round(stats["out_amount"], 2),
                "frozen": (n in self.frozen_accounts),
                "dimmed": is_dimmed,
            })

        links_list = []
        for u in included_nodes:
            for v, e_data in self.window.out_edges(u):
                if v in included_nodes:
                    links_list.append({
                        "source": u,
                        "target": v,
                        "amount": round(e_data["total"], 2),
                        "count": e_data["count"],
                        "last_ts": e_data["last_ts"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    })

        return {"nodes": nodes_list, "links": links_list}

    def get_account_detail(self, account_id: str) -> Optional[dict]:
        """Returns account detail matching master 8.6 shape."""
        acc = self.accounts_dict.get(account_id)
        if not acc and account_id not in self.window.active_nodes():
            return None

        stats = self.window.node_stats(account_id)
        in_amt = round(stats["in_amount"], 2)
        out_amt = round(stats["out_amount"], 2)
        retention = round(abs(out_amt - in_amt) / in_amt, 2) if in_amt > 0 else 0.0

        c_id = None
        risk = 0.1
        for tid, t in self.tracker.tracks.items():
            if account_id in t.current_accounts or account_id in t.peak_accounts:
                c_id = tid
                risk = t.best_risk
                break

        recent_txs = []
        for _, e_data in self.window.out_edges(account_id):
            for t in e_data["tx_list"][-5:]:
                recent_txs.append({"from": t.src, "to": t.dst, "amount": t.amount, "ts": t.ts.strftime("%Y-%m-%dT%H:%M:%SZ")})
        for _, e_data in self.window.in_edges(account_id):
            for t in e_data["tx_list"][-5:]:
                recent_txs.append({"from": t.src, "to": t.dst, "amount": t.amount, "ts": t.ts.strftime("%Y-%m-%dT%H:%M:%SZ")})

        if not recent_txs:
            recent_txs = get_account_historical_txs(account_id)

        recent_txs.sort(key=lambda t: t["ts"], reverse=True)

        return {
            "account_id": account_id,
            "type": acc.account_type if acc else "individual",
            "cluster_id": c_id,
            "risk": round(risk, 2),
            "in_amount": in_amt,
            "out_amount": out_amt,
            "retention_ratio": retention,
            "in_degree": stats["in_degree"],
            "out_degree": stats["out_degree"],
            "median_hold_seconds": int(stats["median_hold"]) if stats["median_hold"] is not None else 0,
            "frozen": (account_id in self.frozen_accounts),
            "recent_tx": recent_txs[:10],
        }

    async def freeze_cluster(self, cluster_id: str, officer: dict) -> dict:
        """
        Freeze all accounts in a cluster:
        - Marks accounts frozen (engine drops their future transactions)
        - Tracks prevented_inr from remaining pending attack txs
        - Sends {"type":"clear","alert_id":...} to /ws/pi
        - Broadcasts {"type":"frozen",...} to /ws/dashboard
        - Logs freeze event to audit chain
        """
        from app.db import get_cluster_detail
        from app.audit import append_audit

        c = get_cluster_detail(cluster_id)
        if not c:
            return {"ok": False, "error": f"Cluster {cluster_id} not found"}

        accounts = set(c.get("accounts", []))
        self.frozen_accounts.update(accounts)

        # Drop any pending attack transactions from frozen accounts and count prevented INR
        prevented = 0.0
        still_pending = []
        for t in self.pending_attack_txs:
            if t.src in self.frozen_accounts:
                prevented += t.amount
                self.prevented_inr += t.amount
            else:
                still_pending.append(t)
        self.pending_attack_txs = still_pending

        # Find the latest alert_id for this cluster
        alerts = c.get("alerts", [])
        latest_alert_id = alerts[-1]["alert_id"] if alerts else None

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Push clear to Pi
        if latest_alert_id:
            await self._broadcast_pi({"type": "clear", "alert_id": latest_alert_id})

        # Broadcast frozen event to dashboard
        frozen_payload = {
            "type": "frozen",
            "cluster_id": cluster_id,
            "officer": officer.get("name", officer.get("id", "unknown")),
            "accounts": list(accounts),
            "prevented_inr": round(prevented, 2),
            "ts": now_iso,
        }
        await self._broadcast_dashboard(frozen_payload)

        # Audit log freeze event
        append_audit("freeze", {
            "cluster_id": cluster_id,
            "officer_id": officer.get("id", ""),
            "officer_name": officer.get("name", ""),
            "accounts": sorted(accounts),
            "prevented_inr": round(prevented, 2),
            "ts": now_iso,
        })

        print(f"[FREEZE] Cluster {cluster_id} frozen by {officer.get('name')} - {len(accounts)} accounts, INR {prevented:,.2f} prevented")
        return {
            "ok": True,
            "cluster_id": cluster_id,
            "accounts_frozen": len(accounts),
            "prevented_inr": round(prevented, 2),
        }


# Singleton engine instance
engine = Engine()
