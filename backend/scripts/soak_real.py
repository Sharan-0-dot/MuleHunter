"""
Mule Hunter — Soak Test via Headless Replay Mode.

Runs 48 sim-hours headless replay (same window, detect, clusters, model, tracker, alerting)
with 6 injected attack rings (all 4 non-stealth + 2 stealth, diff 1-4) spread across the run.
"""

import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.engine import engine

def main():
    print("=" * 80)
    print("MULE HUNTER — 48 SIM-HOUR HEADLESS SOAK REPLAY")
    print("=" * 80)

    # 6 attack rings: all 4 non-stealth + 2 stealth, diff 1-4, spread across 48h
    attacks = [
        {"type": "round_trip", "difficulty": 2, "offset_hours": 6.0, "total_amount_inr": 300_000},
        {"type": "smurfing", "difficulty": 3, "offset_hours": 13.0, "total_amount_inr": 1_000_000},
        {"type": "mule_chain", "difficulty": 1, "offset_hours": 20.0, "total_amount_inr": 420_000},
        {"type": "hybrid", "difficulty": 4, "offset_hours": 27.0, "total_amount_inr": 2_500_000},
        {"type": "stealth", "difficulty": 5, "offset_hours": 34.0},
        {"type": "stealth", "difficulty": 5, "offset_hours": 41.0},
    ]

    res = engine.run_headless(sim_hours=48.0, attacks=attacks, reset_first=True, seed=50)

    print("\n" + "=" * 80)
    print("MULE HUNTER — HEADLESS SOAK REPLAY RESULTS")
    print("=" * 80)
    print(f"  - Simulated Hours Advanced       : {res['sim_hours']:.1f} sim-hours")
    print(f"  - Wall-Clock Execution Time      : {res['wall_clock_sec']:.2f} s")
    print(f"  - Total Alerts Raised            : {res['total_alerts']}")
    print(f"  - True Alerts (Ring Matched)     : {res['true_alerts']}")
    print(f"  - False Alerts (Legit Only)      : {res['false_alerts']}")
    print(f"  - False Alerts / Sim-Hour        : {res['false_alerts_per_sim_hour']:.3f} (GATE G1 limit <= 2.0)")
    print(f"  - Rings Alerted                  : {res['rings_alerted']} / {res['rings_scheduled']} (GATE G1 limit >= 5)")
    print(f"  - Alerts By Band                 : {res['alerts_by_band']}")
    print(f"  - Mean Detection Tick Runtime    : {res['mean_detection_tick_ms']:.2f} ms")
    print(f"  - Mean Time to Alert             : {res['mean_time_to_alert_min']:.1f} sim-min")
    print("\nRings Detail:")
    for r in res["rings_detail"]:
        status = "ALERTED" if r["alerted"] else "MISSED"
        t_str = f"in {r['time_to_alert_min']:.1f} sim-min" if r["time_to_alert_min"] is not None else ""
        print(f"  - {r['ring_id']}: {status} {t_str}")

    print("=" * 80)
    if res['false_alerts_per_sim_hour'] <= 2.0 and res['rings_alerted'] >= 5:
        print(">>> GATE G1 PASSED: false alerts <= 2/hr and >= 5/6 rings alerted! <<<")
    else:
        print(">>> GATE G1 FAILED <<<")

if __name__ == "__main__":
    main()
