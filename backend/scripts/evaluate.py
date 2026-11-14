"""
Mule Hunter — Comprehensive Evaluation Suite.

Evaluates account-level precision/recall/F1, ring detected recall, detection latency,
prevented INR, and false alerts across risk bands:
  1. baseline_fixed (SIM_NAIVE_THRESHOLD >= 50k INR)
  2. baseline_tuned (optimal T grid-searched on training data)
  3. rules_only (candidate clusters ablation without ML filtering)
  4. rules_plus_xgboost (calibrated XGBoost model risk >= ALERT_MIN 0.40)

Supports:
  --split val  : Seeds 50-54, difficulties 1-3 (default) or 1-5 + stealth (--full)
  --split test : Seeds 100-104, difficulties 1-5 (REQUIRES --confirm-final)
Outputs metrics table to stdout and persists to metrics.json or metrics_val_full.json.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
import os
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
    WINDOW_HOURS,
    SIM_NAIVE_THRESHOLD,
    ALERT_MIN,
    GREEN_MAX,
    YELLOW_MAX,
)
from app.sim.generator import generate_accounts_pool, generate_dataset
from app.sim.attacks import inject_attack
from app.detect.window import SlidingWindow
from app.detect.patterns import detect
from app.detect.clusters import build_clusters
from app.detect.model import predict_risk, risk_level
from app.detect.baseline import baseline_fixed, baseline_tuned, rules_only, get_tuned_threshold

METRICS_PATH = backend_dir / "data" / "metrics.json"
METRICS_VAL_FULL_PATH = backend_dir / "data" / "metrics_val_full.json"


def _evaluate_single_run(
    seed: int,
    attack_type: Optional[str],
    difficulty: int,
    tuned_threshold: float,
    duration_hours: float = 96.0,
    tick_hours: float = 2.0,
) -> dict:
    """
    Evaluates one 96h stream run across baselines, rules-only, and rules+XGBoost.
    """
    base_ts = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)
    accounts = generate_accounts_pool()
    accounts_dict = {a.account_id: a for a in accounts}

    gt_ring_accounts: Set[str] = set()
    final_ring_tx_ts: Optional[datetime] = None
    ring_tx_map: Dict[str, float] = {}

    if attack_type is not None:
        rng = np.random.default_rng(seed=100 * seed + difficulty)
        atk_start = base_ts + timedelta(hours=24)
        ring_txs, gt = inject_attack(
            attack_type=attack_type,
            rng=rng,
            accounts=accounts,
            start_ts=atk_start,
            difficulty=difficulty,
            ring_id=f"RING-{seed}-{difficulty}",
        )
        legit_txs, _ = generate_dataset(
            seed=seed,
            difficulty=1,
            duration_hours=duration_hours,
            attacks=None,
            start_ts=base_ts,
        )
        all_stream = sorted(legit_txs + ring_txs, key=lambda t: t.ts)
        gt_ring_accounts = set(gt.ring_accounts)
        ring_tx_list = gt.metadata.get("ring_txs", ring_txs)
        final_ring_tx_ts = max(t.ts for t in ring_tx_list)
        ring_tx_map = {t.tx_id: t.amount for t in ring_tx_list}
        ring_deadline = gt.end_ts + timedelta(hours=6)
    else:
        all_stream, _ = generate_dataset(
            seed=seed,
            difficulty=1,
            duration_hours=duration_hours,
            attacks=None,
            start_ts=base_ts,
        )
        ring_deadline = base_ts + timedelta(hours=duration_hours)

    # 1. Baseline predictions (over full run)
    fixed_flagged = baseline_fixed(all_stream)
    tuned_flagged = baseline_tuned(all_stream, threshold=tuned_threshold)

    # Check baseline ring detection (>= 50% ring accounts flagged before deadline)
    fixed_ring_detected = False
    tuned_ring_detected = False
    if gt_ring_accounts:
        fixed_before = set()
        tuned_before = set()
        for t in all_stream:
            if t.ts <= ring_deadline:
                if t.amount >= SIM_NAIVE_THRESHOLD:
                    fixed_before.add(t.src)
                    fixed_before.add(t.dst)
                if t.amount >= tuned_threshold:
                    tuned_before.add(t.src)
                    tuned_before.add(t.dst)
        fixed_ring_detected = (len(fixed_before & gt_ring_accounts) / len(gt_ring_accounts)) >= 0.50
        tuned_ring_detected = (len(tuned_before & gt_ring_accounts) / len(gt_ring_accounts)) >= 0.50

    # 2. Graph + Detector streaming simulation
    window = SlidingWindow(window_hours=WINDOW_HOURS)
    stream_idx = 0
    n_txs = len(all_stream)

    rules_only_flagged: Set[str] = set()
    xgb_flagged: Set[str] = set()

    rules_only_ring_detected = False
    xgb_ring_detected = False
    first_xgb_alert_ts: Optional[datetime] = None
    first_xgb_red_ts: Optional[datetime] = None
    frozen_accounts: Set[str] = set()
    prevented_inr = 0.0

    alerts_by_band = {"green": 0, "yellow": 0, "red": 0}
    ring_cluster_scores: List[float] = []
    legit_cluster_scores: List[float] = []

    num_ticks = int(duration_hours / tick_hours)
    for tick_i in range(1, num_ticks + 1):
        curr_sim_time = base_ts + timedelta(hours=tick_i * tick_hours)

        while stream_idx < n_txs and all_stream[stream_idx].ts <= curr_sim_time:
            tx = all_stream[stream_idx]
            # Track blocked INR if account was already frozen
            if (tx.src in frozen_accounts or tx.dst in frozen_accounts) and tx.tx_id in ring_tx_map:
                prevented_inr += tx.amount
            window.add(tx)
            stream_idx += 1

        window.advance(curr_sim_time)

        instances = detect(window, curr_sim_time)
        clusters = build_clusters(instances, window, accounts_dict)

        for c in clusters:
            rules_only_flagged.update(c.accounts)

            # Check rules_only ring detection
            if gt_ring_accounts and curr_sim_time <= ring_deadline:
                inter = len(c.accounts & gt_ring_accounts)
                if (inter / len(gt_ring_accounts)) >= 0.50:
                    rules_only_ring_detected = True

            # Model inference
            score = predict_risk(c.features)
            level = risk_level(score)

            # Record score decile data
            if gt_ring_accounts:
                inter = len(c.accounts & gt_ring_accounts)
                if (inter / len(c.accounts)) >= 0.50 or (inter / len(gt_ring_accounts)) >= 0.50:
                    ring_cluster_scores.append(score)
                elif inter == 0:
                    legit_cluster_scores.append(score)
            else:
                legit_cluster_scores.append(score)

            # Alert triggered if risk >= ALERT_MIN (level in green, yellow, red)
            if level in ("green", "yellow", "red"):
                alerts_by_band[level] += 1
                xgb_flagged.update(c.accounts)

                if first_xgb_alert_ts is None and gt_ring_accounts:
                    inter = len(c.accounts & gt_ring_accounts)
                    if (inter / len(gt_ring_accounts)) >= 0.50 or (inter / len(c.accounts)) >= 0.50:
                        first_xgb_alert_ts = curr_sim_time

                # Freeze on red
                if level == "red":
                    frozen_accounts.update(c.accounts)
                    if first_xgb_red_ts is None and gt_ring_accounts:
                        inter = len(c.accounts & gt_ring_accounts)
                        if (inter / len(gt_ring_accounts)) >= 0.50 or (inter / len(c.accounts)) >= 0.50:
                            first_xgb_red_ts = curr_sim_time

                if gt_ring_accounts and curr_sim_time <= ring_deadline:
                    inter = len(c.accounts & gt_ring_accounts)
                    if (inter / len(gt_ring_accounts)) >= 0.50 or (inter / len(c.accounts)) >= 0.50:
                        xgb_ring_detected = True

    # Latency calculation
    latency_sec = None
    ref_ts = first_xgb_alert_ts or first_xgb_red_ts
    if ref_ts is not None and final_ring_tx_ts is not None:
        latency_sec = (ref_ts - final_ring_tx_ts).total_seconds()

    return {
        "seed": seed,
        "attack_type": attack_type,
        "difficulty": difficulty,
        "is_legit": (attack_type is None),
        "gt_ring_accounts": gt_ring_accounts,
        "fixed_flagged": fixed_flagged,
        "tuned_flagged": tuned_flagged,
        "rules_only_flagged": rules_only_flagged,
        "xgb_flagged": xgb_flagged,
        "fixed_ring_detected": fixed_ring_detected,
        "tuned_ring_detected": tuned_ring_detected,
        "rules_only_ring_detected": rules_only_ring_detected,
        "xgb_ring_detected": xgb_ring_detected,
        "latency_sec": latency_sec,
        "prevented_inr": prevented_inr,
        "alerts_by_band": alerts_by_band,
        "ring_cluster_scores": ring_cluster_scores,
        "legit_cluster_scores": legit_cluster_scores,
    }


def compute_aggregate_metrics(results: List[dict], split_name: str) -> dict:
    models = ["baseline_fixed", "baseline_tuned", "rules_only", "rules_plus_xgboost"]
    flag_key_map = {
        "baseline_fixed": "fixed_flagged",
        "baseline_tuned": "tuned_flagged",
        "rules_only": "rules_only_flagged",
        "rules_plus_xgboost": "xgb_flagged",
    }
    ring_det_map = {
        "baseline_fixed": "fixed_ring_detected",
        "baseline_tuned": "tuned_ring_detected",
        "rules_only": "rules_only_ring_detected",
        "rules_plus_xgboost": "xgb_ring_detected",
    }

    # 1. Overall account-level metrics
    account_level = {}
    for m in models:
        key = flag_key_map[m]
        tp = sum(len(r[key] & r["gt_ring_accounts"]) for r in results)
        fp = sum(len(r[key] - r["gt_ring_accounts"]) for r in results)
        fn = sum(len(r["gt_ring_accounts"] - r[key]) for r in results if not r["is_legit"])

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2.0 * prec * rec) / (prec + rec) if (prec + rec) > 0.0 else 0.0

        account_level[m] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
        }

    # 2. Account-level metrics by difficulty (non-stealth)
    by_difficulty = {}
    for diff in range(1, 6):
        d_str = str(diff)
        d_runs = [r for r in results if not r["is_legit"] and r["attack_type"] != "stealth" and r["difficulty"] == diff]
        if not d_runs:
            continue
        by_difficulty[d_str] = {}
        for m in models:
            key = flag_key_map[m]
            tp = sum(len(r[key] & r["gt_ring_accounts"]) for r in d_runs)
            fp = sum(len(r[key] - r["gt_ring_accounts"]) for r in d_runs)
            fn = sum(len(r["gt_ring_accounts"] - r[key]) for r in d_runs)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2.0 * prec * rec) / (prec + rec) if (prec + rec) > 0.0 else 0.0
            by_difficulty[d_str][m] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
            }

    # 3. Stealth scenario metrics separately
    stealth_runs = [r for r in results if r["attack_type"] == "stealth"]
    stealth_metrics = {}
    if stealth_runs:
        for m in models:
            key = flag_key_map[m]
            tp = sum(len(r[key] & r["gt_ring_accounts"]) for r in stealth_runs)
            fp = sum(len(r[key] - r["gt_ring_accounts"]) for r in stealth_runs)
            fn = sum(len(r["gt_ring_accounts"] - r[key]) for r in stealth_runs)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2.0 * prec * rec) / (prec + rec) if (prec + rec) > 0.0 else 0.0
            det = sum(1 for r in stealth_runs if r[ring_det_map[m]])
            stealth_metrics[m] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "ring_recall": round(det / len(stealth_runs), 4),
            }

    # 4. Ring detected recall
    attack_runs = [r for r in results if not r["is_legit"]]
    n_attacks = len(attack_runs)
    ring_recall = {}
    for m in models:
        key = ring_det_map[m]
        detected = sum(1 for r in attack_runs if r[key])
        ring_recall[m] = round(detected / n_attacks, 4) if n_attacks > 0 else 0.0

    # 5. Latency
    latencies = [r["latency_sec"] for r in attack_runs if r["latency_sec"] is not None]
    if latencies:
        mean_lat = round(float(np.mean(latencies)), 1)
        med_lat = round(float(np.median(latencies)), 1)
    else:
        mean_lat, med_lat = 0.0, 0.0

    # 6. Prevented INR
    total_prevented = round(sum(r["prevented_inr"] for r in attack_runs), 2)

    # 7. False alerts per legit sim-day split by band
    legit_runs = [r for r in results if r["is_legit"]]
    total_legit_sim_days = len(legit_runs) * 4.0  # 96h = 4 days
    false_alerts = {"green": 0, "yellow": 0, "red": 0, "total_ge_040": 0}
    for r in legit_runs:
        for b in ("green", "yellow", "red"):
            false_alerts[b] += r["alerts_by_band"][b]
            false_alerts["total_ge_040"] += r["alerts_by_band"][b]

    false_alerts_per_day = {
        b: round(false_alerts[b] / total_legit_sim_days, 2) if total_legit_sim_days > 0 else 0.0
        for b in ("green", "yellow", "red", "total_ge_040")
    }

    # 8. Score deciles (10% to 100%)
    all_ring_scores = []
    all_legit_scores = []
    for r in results:
        all_ring_scores.extend(r["ring_cluster_scores"])
        all_legit_scores.extend(r["legit_cluster_scores"])

    deciles = list(range(10, 101, 10))
    ring_deciles = {}
    legit_deciles = {}
    if all_ring_scores:
        for p in deciles:
            ring_deciles[f"p{p}"] = round(float(np.percentile(all_ring_scores, p)), 4)
    if all_legit_scores:
        for p in deciles:
            legit_deciles[f"p{p}"] = round(float(np.percentile(all_legit_scores, p)), 4)

    return {
        "split": split_name,
        "account_level": account_level,
        "by_difficulty": by_difficulty,
        "stealth": stealth_metrics,
        "ring_recall": ring_recall,
        "latency_sec": {"mean": mean_lat, "median": med_lat},
        "prevented_inr": total_prevented,
        "false_alerts_per_day": false_alerts_per_day,
        "score_deciles": {
            "true_ring_clusters": ring_deciles,
            "legit_clusters": legit_deciles,
            "n_ring_clusters": len(all_ring_scores),
            "n_legit_clusters": len(all_legit_scores),
        },
    }


def print_full_evaluation_report(metrics: dict):
    print("\n" + "=" * 80)
    print(f"MULE HUNTER — FULL EVALUATION REPORT (SPLIT: {metrics['split'].upper()})")
    print(f"Config Risk Bands: ALERT_MIN={ALERT_MIN}, GREEN_MAX={GREEN_MAX}, YELLOW_MAX={YELLOW_MAX}")
    print("=" * 80)

    print("\n[1] Account-Level Precision / Recall / F1 by Difficulty (1-5):")
    hdr = f"{'Diff':<6} | {'Model':<20} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10}"
    print(hdr)
    print("-" * len(hdr))
    for d, m_dict in sorted(metrics["by_difficulty"].items()):
        for m, name in [
            ("baseline_fixed", "Baseline (Fixed 50k)"),
            ("baseline_tuned", "Baseline (Tuned T)"),
            ("rules_plus_xgboost", "Rules + XGBoost (Ours)"),
        ]:
            if m in m_dict:
                p = m_dict[m]["precision"]
                r = m_dict[m]["recall"]
                f1 = m_dict[m]["f1"]
                print(f"L{d:<4} | {name:<20} | {p:<10.1%} | {r:<10.1%} | {f1:<10.4f}")
        print("-" * len(hdr))

    if metrics.get("stealth"):
        print("\n[2] Stealth Attack Scenario Performance (Difficulty 5 Structured Below 50k):")
        s_hdr = f"{'Model':<22} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10} | {'Ring Recall':<12}"
        print(s_hdr)
        print("-" * len(s_hdr))
        for m, name in [
            ("baseline_fixed", "Baseline (Fixed 50k)"),
            ("baseline_tuned", "Baseline (Tuned T)"),
            ("rules_only", "Rules Only (No ML)"),
            ("rules_plus_xgboost", "Rules + XGBoost (Ours)"),
        ]:
            if m in metrics["stealth"]:
                p = metrics["stealth"][m]["precision"]
                r = metrics["stealth"][m]["recall"]
                f1 = metrics["stealth"][m]["f1"]
                rr = metrics["stealth"][m]["ring_recall"]
                print(f"{name:<22} | {p:<10.1%} | {r:<10.1%} | {f1:<10.4f} | {rr:<12.1%}")

    print("\n[3] False Alerts per Legit Sim-Day (Split by Risk Band):")
    fa = metrics["false_alerts_per_day"]
    print(f"  - Green Alerts (0.40 <= risk < 0.65) : {fa.get('green', 0.0):.2f} / day")
    print(f"  - Yellow Alerts (0.65 <= risk < 0.85): {fa.get('yellow', 0.0):.2f} / day")
    print(f"  - Red Alerts (risk >= 0.85)         : {fa.get('red', 0.0):.2f} / day")
    print(f"  - Total False Alerts (risk >= 0.40)  : {fa.get('total_ge_040', 0.0):.2f} / day")

    print("\n[4] Calibrated Risk-Score Deciles (True-Ring vs Legit Clusters):")
    dec_hdr = f"{'Percentile':<12} | {'True-Ring Clusters':<20} | {'Legit Clusters':<20}"
    print(dec_hdr)
    print("-" * len(dec_hdr))
    ring_dec = metrics["score_deciles"]["true_ring_clusters"]
    legit_dec = metrics["score_deciles"]["legit_clusters"]
    for p in range(10, 101, 10):
        k = f"p{p}"
        r_val = ring_dec.get(k, 0.0)
        l_val = legit_dec.get(k, 0.0)
        print(f"{k:<12} | {r_val:<20.4f} | {l_val:<20.4f}")

    print("\n[5] Red Band Reachability Assessment (>= 0.85):")
    p90_ring = ring_dec.get("p90", 0.0)
    p100_ring = ring_dec.get("p100", 0.0)
    print(f"  - True Ring Clusters p90 risk: {p90_ring:.4f}, max risk: {p100_ring:.4f}")
    if p100_ring < 0.85:
        print("  >>> OBSERVATION: True ring clusters rarely/never reach >= 0.85 under current isotonic calibration.")
    else:
        print(f"  >>> OBSERVATION: True ring clusters reach >= 0.85 starting at percentile ~{next((p for p in range(10, 101, 10) if ring_dec.get(f'p{p}', 0.0) >= 0.85), 'N/A')}.")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Evaluate AML Detection Models")
    parser.add_argument("--split", choices=["val", "test"], required=True, help="Evaluation split: 'val' or 'test'")
    parser.add_argument("--confirm-final", action="store_true", help="Confirmation flag required to execute test split")
    parser.add_argument("--full", action="store_true", help="Run full evaluation grid across diff 1-5 + stealth")
    args = parser.parse_args()

    if args.split == "test" and not args.confirm_final:
        print("ERROR: Test split is strictly held-out. You must provide '--confirm-final' to run on test seeds.")
        sys.exit(1)

    if args.split == "val":
        seeds = list(range(50, 55))  # Seeds 50-54
        diffs = [1, 2, 3, 4, 5] if args.full else [1, 2, 3]
    else:
        seeds = list(range(100, 105))  # Seeds 100-104
        diffs = [1, 2, 3, 4, 5]

    tuned_t = get_tuned_threshold()
    attack_types = ["smurfing", "round_trip", "mule_chain", "hybrid"]

    runs = []
    # 5 legit runs
    for s in seeds:
        runs.append((s, None, 1))

    # Attack runs
    for s in seeds:
        for d in diffs:
            for atk in attack_types:
                runs.append((s, atk, d))

    # Stealth scenario if full
    if args.full:
        for s in seeds:
            runs.append((s, "stealth", 5))

    print(f"Evaluating {len(runs)} simulation runs on split '{args.split}' (Seeds {min(seeds)}-{max(seeds)}, full={args.full})...")
    t0 = time.perf_counter()

    results = []
    workers = max(1, min(16, (os.cpu_count() or 2) - 1))

    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_evaluate_single_run, s, atk, d, tuned_t): (s, atk, d)
            for (s, atk, d) in runs
        }
        done = 0
        for future in as_completed(future_map):
            done += 1
            if done % 20 == 0 or done == len(runs):
                print(f"  Progress: {done}/{len(runs)} runs evaluated ({done/len(runs)*100:.1f}%)")
            results.append(future.result())

    dt = time.perf_counter() - t0
    print(f"Evaluation finished in {dt:.2f}s.")

    metrics = compute_aggregate_metrics(results, args.split)
    print_full_evaluation_report(metrics)

    out_path = METRICS_VAL_FULL_PATH if args.full else METRICS_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Saved evaluation metrics to: {out_path}")


if __name__ == "__main__":
    main()
