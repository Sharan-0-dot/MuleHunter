"""
Mule Hunter — 10-Minute Real-Time Soak Test.

Runs live simulation for 10 minutes (600 seconds) at SIM_SPEED=10 (100 sim-hours).
Launches 6 attack rings at random types and difficulties (1-4) spread across the run.
Collects live telemetry, monitors WebSocket alerts and server metrics.
Reports:
  - Total alerts raised
  - Injected rings alerted (ring detection recall)
  - False alerts (< 10% overlap with any active ground-truth ring)
  - Mean and max detection tick runtimes (ms)
  - Any exceptions encountered
  - Memory growth over the soak duration
"""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sys
import time
import psutil
import requests
import websockets

BASE_URL = "http://127.0.0.1:8001"
WS_BASE = "ws://127.0.0.1:8001"
ATTACK_TYPES = ["smurfing", "round_trip", "mule_chain", "hybrid"]


async def run_soak_test():
    print("=" * 80)
    print("MULE HUNTER — 10-MINUTE REAL-TIME SOAK TEST (SIM_SPEED=10)")
    print("=" * 80)

    # Check server availability
    try:
        r = requests.get(f"{BASE_URL}/api/metrics", timeout=5)
        assert r.status_code == 200
    except Exception as e:
        print(f"FAILED to reach {BASE_URL}: {e}")
        sys.exit(1)

    # Reset simulation state to start clean
    requests.post(f"{BASE_URL}/api/sim/reset")
    await asyncio.sleep(1.0)

    # Monitor current server process memory
    proc = None
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "uvicorn" in cmd and "8001" in cmd:
                proc = p
                break
            elif "main:app" in cmd and "8001" in cmd:
                proc = p
                break
        except Exception:
            pass

    mem_start_mb = proc.memory_info().rss / (1024 * 1024) if proc else 0.0
    print(f"[SOAK INIT] Server process PID: {proc.pid if proc else 'N/A'}, Initial RAM: {mem_start_mb:.1f} MB")

    # Connect WebSockets
    ws_pi = await websockets.connect(f"{WS_BASE}/ws/pi")
    ws_dash = await websockets.connect(f"{WS_BASE}/ws/dashboard")

    # Start simulation at 10x
    requests.post(f"{BASE_URL}/api/sim/start", json={"speed": 10.0})
    print("[SOAK INIT] Simulation stream started at speed 10.0x.")

    total_duration_sec = 600.0  # 10 minutes
    t_start = time.perf_counter()
    t_end = t_start + total_duration_sec

    # Schedule 6 attacks spread across the 10-minute window
    attack_schedule = [
        {"time_sec": 30.0, "type": "round_trip", "diff": 2},
        {"time_sec": 120.0, "type": "smurfing", "diff": 3},
        {"time_sec": 210.0, "type": "mule_chain", "diff": 1},
        {"time_sec": 300.0, "type": "hybrid", "diff": 2},
        {"time_sec": 390.0, "type": "round_trip", "diff": 3},
        {"time_sec": 480.0, "type": "smurfing", "diff": 4},
    ]
    attack_idx = 0
    injected_attacks = []
    received_alerts = []
    exceptions = []

    async def _pi_listener():
        try:
            while time.perf_counter() < t_end:
                try:
                    msg = await asyncio.wait_for(ws_pi.recv(), timeout=2.0)
                    data = json.loads(msg)
                    if data.get("type") == "alert":
                        received_alerts.append(data)
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            exceptions.append(f"Pi WS error: {e}")

    async def _dash_listener():
        try:
            while time.perf_counter() < t_end:
                try:
                    await asyncio.wait_for(ws_dash.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            exceptions.append(f"Dashboard WS error: {e}")

    pi_task = asyncio.create_task(_pi_listener())
    dash_task = asyncio.create_task(_dash_listener())

    print(f"\n[SOAK RUN] Running soak test for {total_duration_sec:.0f} seconds (100 sim-hours)...")
    last_print = time.perf_counter()

    while time.perf_counter() < t_end:
        elapsed = time.perf_counter() - t_start

        # Check attack schedule
        if attack_idx < len(attack_schedule) and elapsed >= attack_schedule[attack_idx]["time_sec"]:
            atk = attack_schedule[attack_idx]
            try:
                res = requests.post(f"{BASE_URL}/api/sim/attack", json={"type": atk["type"], "difficulty": atk["diff"]}).json()
                injected_attacks.append({**atk, **res})
                print(f"  [T+{elapsed:.1f}s] Launched attack {attack_idx+1}/6: {atk['type']} (diff {atk['diff']}) -> {res.get('ring_id')}")
            except Exception as e:
                exceptions.append(f"Attack injection error: {e}")
            attack_idx += 1

        # Periodic status every 60s
        if time.perf_counter() - last_print >= 60.0:
            last_print = time.perf_counter()
            mem_curr = proc.memory_info().rss / (1024 * 1024) if proc else 0.0
            print(f"  [STATUS T+{elapsed:.0f}s / {total_duration_sec:.0f}s] Alerts: {len(received_alerts)}, RAM: {mem_curr:.1f} MB")

        await asyncio.sleep(1.0)

    # Cancel listeners
    pi_task.cancel()
    dash_task.cancel()
    await ws_pi.close()
    await ws_dash.close()

    # Pause simulation
    requests.post(f"{BASE_URL}/api/sim/stop")

    # Fetch final telemetry and ground truth from server
    metrics_res = requests.get(f"{BASE_URL}/api/metrics").json()
    gt_res = requests.get(f"{BASE_URL}/api/dev/ground_truth").json()
    clusters_res = requests.get(f"{BASE_URL}/api/clusters").json()

    # Ground truth rings map
    all_gt_rings = {k: set(v["ring_accounts"]) for k, v in gt_res.items()}

    # Evaluate alerts
    false_alerts = []
    real_alerts = []
    alerted_rings = set()

    for a in received_alerts:
        cid = a["cluster_id"]
        c_detail_resp = requests.get(f"{BASE_URL}/api/clusters/{cid}")
        if c_detail_resp.status_code == 200:
            c_accs = set(c_detail_resp.json().get("accounts", []))
        else:
            c_accs = set()

        max_overlap = 0.0
        matching_ring = None
        for r_id, r_accs in all_gt_rings.items():
            if c_accs:
                overlap = len(c_accs & r_accs) / len(c_accs)
                if overlap > max_overlap:
                    max_overlap = overlap
                    matching_ring = r_id

        if max_overlap >= 0.10:
            real_alerts.append(a)
            if matching_ring:
                alerted_rings.add(matching_ring)
        else:
            false_alerts.append((a, max_overlap, c_accs))

    elapsed_wall = time.perf_counter() - t_start
    sim_hours = elapsed_wall * 10.0 / 3600.0  # SIM_SPEED = 10
    false_alerts_per_sim_hour = len(false_alerts) / sim_hours if sim_hours > 0 else 0.0

    mem_end_mb = proc.memory_info().rss / (1024 * 1024) if proc else 0.0
    mem_delta_mb = mem_end_mb - mem_start_mb

    print("\n" + "=" * 80)
    print("MULE HUNTER — 10-MINUTE SOAK TEST RESULTS REPORT")
    print("=" * 80)
    print(f"  - Total Elapsed Wall-Clock Time  : {elapsed_wall:.1f} s")
    print(f"  - Simulated Time Advanced        : {sim_hours:.1f} sim-hours")
    print(f"  - Transactions Processed         : {metrics_res.get('tx_processed', 0):,} txs")
    print(f"  - Attacks Injected               : {len(injected_attacks)} / 6")
    print(f"  - Total Alerts Raised            : {len(received_alerts)}")
    print(f"  - Injected Rings Alerted         : {len(alerted_rings)} / {len(injected_attacks)} ({len(alerted_rings)/max(1, len(injected_attacks))*100:.1f}%)")
    print(f"  - False Alerts (<10% ring overlap): {len(false_alerts)}")
    print(f"  - False Alerts / Sim-Hour        : {false_alerts_per_sim_hour:.2f} / sim-hour")
    print(f"  - Mean Detection Tick Runtime    : {metrics_res.get('mean_tick_ms', 0.0):.2f} ms")
    print(f"  - Exceptions Encountered         : {len(exceptions)}")
    if exceptions:
        for ex in exceptions:
            print(f"    * {ex}")
    print(f"  - Initial Memory Usage           : {mem_start_mb:.1f} MB")
    print(f"  - Final Memory Usage             : {mem_end_mb:.1f} MB")
    print(f"  - Memory Growth                  : {mem_delta_mb:+.1f} MB")

    if false_alerts_per_sim_hour > 2.0:
        print("\n  >>> WARNING: False alerts exceed 2 per sim-hour.")
        print("  Legit behaviors observed in false alert clusters:")
        for fa, ov, accs in false_alerts:
            print(f"    - Alert {fa['alert_id']} ({fa['typology']}, risk {fa['risk_score']}): {len(accs)} accounts, overlap {ov:.1%}")
    else:
        print("\n  >>> PASS: False alert rate is well within acceptable threshold (<= 2.0 / sim-hour).")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_soak_test())
