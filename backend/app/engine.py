"""
Mule Hunter — Real-Time Streaming, Detection & Alerting Engine.

Owns:
  - Simulated clock with speed multiplier (1x-20x)
  - Streaming transaction generation + attack injector
  - SlidingWindow(48h) temporal graph
  - Detection pipeline & ClusterTracker
  - Calibrated XGBoost model inference & urgency band mapping
  - Spoken summary generation, LLM polish & TTS WAV synthesis
  - Strict push order: DB persist -> Audio verify -> /ws/pi push & /ws/dashboard broadcast
  - Escalation timer monitoring Pi voice/joystick acks
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

from app.config import (
    SHARED_SECRET,
    LISTEN_SECONDS,
    SIM_SPEED,
    DETECT_TICK_SIM_MINUTES,
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
    generate_accounts_pool,
    generate_dataset,
    _generate_legit_traffic,
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
        self.tracker: ClusterTracker = ClusterTracker(jaccard_threshold=0.50)
        self.last_detection_sim_time: datetime = self.base_sim_time
        self.detection_interval_sec: float = DETECT_TICK_SIM_MINUTES * 60.0
        self.tick_lock = asyncio.Lock()

        # 4. Attack queue & isolated dev ground-truth
        self.pending_attack_txs: List[Transaction] = []
        self.server_ground_truth: Dict[str, dict] = {}
        self.attack_counter: int = 1

        # 5. Alerting & tracking
        self.alert_counter: int = get_max_alert_id() + 1
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

    def warmup(self):
        """Generates WARMUP_SIM_HOURS of legit traffic in batch to prime graph window."""
        print(f"[ENGINE] Warming up window with {WARMUP_SIM_HOURS:.1f} hours of legit traffic...")
        init_db()
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
        print(f"[ENGINE] Warmup complete. Prime window contains {len(txs):,} transactions across {len(self.window.active_nodes())} nodes.")

    async def start(self, speed: Optional[float] = None):
        """Starts live simulation stream."""
        if speed is not None:
            self.sim_speed = max(1.0, min(20.0, float(speed)))
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
        """Resets engine state to fresh warmup."""
        await self.stop()
        self.window = SlidingWindow(window_hours=WINDOW_HOURS)
        self.tracker = ClusterTracker(jaccard_threshold=0.50)
        self.pending_attack_txs.clear()
        self.server_ground_truth.clear()
        self.frozen_accounts.clear()
        self.prevented_inr = 0.0
        self.tx_processed_count = 0
        self.alerts_count = 0
        clear_db()
        self.alert_counter = 1
        self.cluster_alert_levels.clear()
        self.cluster_alert_versions.clear()
        self.unacked_alerts.clear()
        self.tick_runtimes_ms.clear()
        self.warmup()
        print("[ENGINE] Simulation reset to initial state.")

    def launch_attack(self, attack_type: str, difficulty: int) -> dict:
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

        print(f"[ENGINE] Injected {atk_type} (diff {diff}) ring {ring_id} starting at {self.sim_time.isoformat()}.")
        return {
            "ok": True,
            "ring_id": ring_id,
            "type": atk_type,
            "difficulty": diff,
            "start_ts": self.sim_time.isoformat(),
        }

    async def _run_loop(self):
        """Continuous wall-clock loop advancing simulated stream every ~500 ms."""
        legit_rng = np.random.default_rng(seed=999)

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

                # 1. Generate legit transactions for this step
                new_txs: List[Transaction] = []
                legit_step_txs = _generate_legit_traffic(
                    rng=legit_rng,
                    accounts=self.accounts,
                    start_ts=self.sim_time,
                    duration_hours=dt_sim_sec / 3600.0,
                )
                new_txs.extend(legit_step_txs)

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

                # 5. Check if it's time for a detection tick
                time_since_detect = (self.sim_time - self.last_detection_sim_time).total_seconds()
                if time_since_detect >= self.detection_interval_sec:
                    if not self.tick_lock.locked():
                        self.last_detection_sim_time = self.sim_time
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

            # Heavy detection run in executor to keep event loop responsive
            def _detect_and_cluster():
                instances = detect(self.window, self.sim_time)
                clusters = build_clusters(instances, self.window, self.accounts_dict)
                return clusters

            clusters = await loop.run_in_executor(None, _detect_and_cluster)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self.tick_runtimes_ms.append(dt_ms)

            # Update temporal cluster tracker with calibrated risk scoring
            active_tracks = self.tracker.update(clusters, self.sim_time, risk_fn=predict_risk)

            # Evaluate each active tracked cluster
            for trk in active_tracks:
                score = trk.best_risk
                level = risk_level(score)

                # Check if cluster should trigger an alert (reaches >= ALERT_MIN or moves UP a band)
                if level in ("green", "yellow", "red"):
                    prev_level = self.cluster_alert_levels.get(trk.cluster_id)
                    prev_rank = BAND_RANKS.get(prev_level, 0)
                    new_rank = BAND_RANKS.get(level, 0)

                    if prev_level is None or new_rank > prev_rank:
                        # New alert or upward escalation
                        await self._process_alert(trk, score, level)
                    else:
                        # Material change without band jump: broadcast cluster_updated
                        await self._broadcast_dashboard({
                            "type": "cluster_updated",
                            "cluster_id": trk.cluster_id,
                            "risk": round(score, 4),
                            "accounts_count": len(trk.accounts),
                            "total_amount": round(trk.total_amount, 2),
                        })

    async def _process_alert(self, cluster_obj, risk_score: float, level: str):
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
        for p in cluster_obj.pattern_instances:
            if p.pattern_type in ("fan_out", "smurfing_fan_out_fan_in"):
                source = next(iter(p.core_accounts), None)
            if p.pattern_type in ("fan_in", "smurfing_fan_out_fan_in"):
                destination = p.meta.get("reconvergence_dst") or next(iter(p.core_accounts), None)

        # 1. Generate template summary
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

        # 2. LLM polish in worker thread (non-blocking)
        loop = asyncio.get_running_loop()
        final_summary, summary_source, llm_latency_ms = await loop.run_in_executor(
            None, polish_summary, template_text
        )

        # 3. TTS WAV synthesis in worker thread
        audio_path, wav_url, tts_fallback = await loop.run_in_executor(
            None,
            generate_audio,
            cluster_id,
            final_summary,
            level,
            version,
        )

        # 4. Strict check: verify wav file exists on disk
        if not audio_path.exists() or audio_path.stat().st_size < 1000:
            print(f"[ALERT WARNING] Audio {audio_path} not found; creating fallback.")
            sample_file = backend_dir / "static" / "audio" / f"{level.lower()}.wav"
            import shutil
            shutil.copyfile(sample_file, audio_path)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Master 8.2 alert contract
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

        # 5. Step 1: Persist cluster + alert + window txs to SQLite
        window_txs = []
        for u in cluster_obj.accounts:
            for _, e in self.window.out_edges(u):
                window_txs.extend(e["tx_list"])

        save_cluster_and_alert(
            alert_dict=alert_dict,
            cluster_obj=cluster_obj,
            summary_text=final_summary,
            summary_source=summary_source,
            audio_path=str(audio_path),
            llm_latency_ms=llm_latency_ms,
            tts_fallback=tts_fallback,
            window_txs=window_txs,
        )

        # 6. Step 2: Push to /ws/pi
        pi_payload = dict(alert_dict)
        pi_payload["type"] = "alert"
        await self._broadcast_pi(pi_payload)

        # Record in unacked_alerts for escalation monitoring
        self.unacked_alerts[alert_id] = {
            "pushed_at": time.perf_counter(),
            "escalated": False,
        }

        # 7. Step 3: Broadcast cluster_alert to /ws/dashboard
        dashboard_payload = dict(alert_dict)
        dashboard_payload["type"] = "cluster_alert"
        dashboard_payload["summary"] = final_summary
        dashboard_payload["accounts"] = list(cluster_obj.accounts)
        dashboard_payload["features"] = cluster_obj.features
        await self._broadcast_dashboard(dashboard_payload)

        print(f"[ALERT PUSHED] {level.upper()} alert {alert_id} for {cluster_id} (risk {risk_score:.2f}, {summary_source}) -> Pi & Dashboard")

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

    def handle_pi_ack(self, alert_id: str, event: str, ts: str):
        """Handles acknowledgement from Pi, stores in DB, cancels escalation, and forwards to dashboard."""
        record_pi_ack(alert_id, event, ts)
        if alert_id in self.unacked_alerts:
            # If ack was an explain or played, clear from escalation watch
            if event in ("explain_voice", "explain_joystick", "played", "received"):
                self.unacked_alerts.pop(alert_id, None)

        # Broadcast pi_ack on dashboard
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
        cluster = None
        focus_nodes = set()
        if cluster_id:
            c_detail = get_cluster_detail(cluster_id)
            if c_detail:
                focus_nodes = set(c_detail["accounts"])

        # 1-hop neighbours from window
        neighbour_nodes = set()
        for u in focus_nodes:
            neighbour_nodes.update(self.window.out_adj.get(u, set()))
            neighbour_nodes.update(self.window.in_adj.get(u, set()))

        highlighted_nodes = focus_nodes | neighbour_nodes
        all_active = list(self.window.active_nodes())

        # Sample background nodes capped at 300
        background_sample = [n for n in all_active if n not in highlighted_nodes]
        if len(background_sample) > 300:
            rng = np.random.default_rng(42)
            background_sample = list(rng.choice(background_sample, size=300, replace=False))

        included_nodes = highlighted_nodes | set(background_sample)

        # Node objects
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

        # Links objects internal to included_nodes
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

        # Cluster lookup
        c_id = None
        risk = 0.1
        for tid, t in self.tracker.tracks.items():
            if account_id in t.current_accounts or account_id in t.peak_accounts:
                c_id = tid
                risk = t.best_risk
                break

        # Recent transactions from window and historical DB
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


# Singleton engine instance
engine = Engine()
