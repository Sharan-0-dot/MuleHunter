"""
Verification suite for Milestone M1 (Simulator) with Step 0 fixes.

Runs against seeds and prints real numbers:
1. Accounts by type.
2. For a 24-sim-hour legit-only dataset: total tx, tx per hour, count by kind,
   amount percentiles (p50, p90, p99, max), and hard-negative false-positive pool (>= SIM_NAIVE_THRESHOLD).
3. For EACH attack type x difficulty 1-5: number of ring tx, number of ring accounts,
   total amount, max single tx amount, % of ring tx at or above the threshold,
   time span from first to last ring tx, and number of legit tx mixed into ring accounts.
4. Volume Preservation Table: Mean total amount by attack x difficulty over seeds 1-5.
5. Automatic sanity assertions (PASS/FAIL):
   - same seed gives identical output
   - ground-truth accounts are all real accounts
   - (a) Connectivity: every GT account appears in at least one ring tx and ring is weakly connected
   - (d) No label leakage: kind uses normal vocabulary only (no 'ring_hop'); tx_ids assigned after sort
   - (e) % of ring tx above threshold non-increasing and exactly 0% at difficulty 5
   - time span increases with difficulty
   - no tx has src == dst
   - no negative amounts
   - timestamps are sorted
"""

from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Configure stdout for utf-8 if supported
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import networkx as nx
import numpy as np
import pandas as pd

from app.config import SIM_NAIVE_THRESHOLD
from app.sim.generator import (
    generate_accounts_pool,
    generate_dataset,
    Account,
    Transaction,
    DatasetGroundTruth,
)
from app.sim.attacks import inject_attack


def run_checks(seeds_to_test=(1, 2, 3)):
    print("=" * 80)
    print("MULE HUNTER — M1 SIMULATOR VERIFICATION SUITE (WITH STEP 0 FIXES)")
    print("=" * 80)
    print(f"SIM_NAIVE_THRESHOLD = INR {SIM_NAIVE_THRESHOLD:,.2f}")

    # -----------------------------------------------------------------------
    # 1. Accounts by type
    # -----------------------------------------------------------------------
    print("\n[SECTION 1] Accounts Pool Summary")
    accounts = generate_accounts_pool()
    acc_counts = Counter(a.account_type for a in accounts)
    total_acc = len(accounts)
    print(f"Total Accounts: {total_acc:,}")
    for acc_type, count in sorted(acc_counts.items()):
        pct = (count / total_acc) * 100
        print(f"  - {acc_type:<12}: {count:>5} ({pct:>5.1f}%)")

    # -----------------------------------------------------------------------
    # 2. 24-sim-hour Legit-Only Dataset
    # -----------------------------------------------------------------------
    print(f"\n[SECTION 2] 24-Sim-Hour Legit-Only Dataset (Seed={seeds_to_test[0]})")
    t0 = time.perf_counter()
    legit_txs, legit_gt = generate_dataset(
        seed=seeds_to_test[0],
        difficulty=1,
        duration_hours=24.0,
        attacks=None,
    )
    t_elapsed = time.perf_counter() - t0
    total_tx = len(legit_txs)
    tx_per_hour = total_tx / 24.0

    print(f"Generation Time : {t_elapsed:.3f} seconds (vectorized batch)")
    print(f"Total Tx        : {total_tx:,}")
    print(f"Tx / Hour       : {tx_per_hour:.1f}")

    kind_counts = Counter(tx.kind for tx in legit_txs)
    print("Transaction Breakdown by Kind:")
    for kind, count in sorted(kind_counts.items()):
        pct = (count / total_tx) * 100
        print(f"  - {kind:<18}: {count:>5} ({pct:>5.1f}%)")

    amounts = np.array([tx.amount for tx in legit_txs])
    p50 = float(np.percentile(amounts, 50))
    p90 = float(np.percentile(amounts, 90))
    p99 = float(np.percentile(amounts, 99))
    max_amt = float(np.max(amounts))
    print("Amount Percentiles (INR):")
    print(f"  - p50 (Median)   : INR {p50:>10,.2f}")
    print(f"  - p90            : INR {p90:>10,.2f}")
    print(f"  - p99            : INR {p99:>10,.2f}")
    print(f"  - Max            : INR {max_amt:>10,.2f}")

    hard_negatives = [tx for tx in legit_txs if tx.amount >= SIM_NAIVE_THRESHOLD]
    hard_neg_kinds = Counter(tx.kind for tx in hard_negatives)
    print(f"Hard-Negative False Positive Pool (>= INR {SIM_NAIVE_THRESHOLD:,.0f}):")
    print(f"  - Total Count    : {len(hard_negatives)} ({len(hard_negatives)/total_tx*100:.2f}% of legit traffic)")
    for kind, count in sorted(hard_neg_kinds.items()):
        print(f"    * {kind:<16}: {count}")

    # -----------------------------------------------------------------------
    # 3. Each Attack Type x Difficulty 1-5 (Evaluated on Seed 1)
    # -----------------------------------------------------------------------
    print(f"\n[SECTION 3] Attack Matrices (Attack Type x Difficulty 1-5, Seed={seeds_to_test[0]})")
    attack_types = ["smurfing", "round_trip", "mule_chain", "hybrid", "stealth"]
    base_ts = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)

    attack_results = {}

    for atk_type in attack_types:
        print(f"\n--- Attack: {atk_type.upper()} ---")
        header = (
            f"{'Diff':<5} | {'Ring Tx':<8} | {'Ring Acc':<9} | {'Total Amt (INR)':<16} | "
            f"{'Max Tx (INR)':<13} | {'% >= Thresh':<12} | {'Time Span':<12} | {'Mixed Legit':<11}"
        )
        print(header)
        print("-" * len(header))

        for diff in range(1, 6):
            rng = np.random.default_rng(seed=10 * seeds_to_test[0] + diff)
            txs, gt = inject_attack(
                attack_type=atk_type,
                rng=rng,
                accounts=accounts,
                start_ts=base_ts,
                difficulty=diff,
                ring_id=f"RING-{diff}",
            )

            ring_txs = [t for t in gt.metadata["ring_txs"]]
            mixed_txs = [t for t in txs if t not in ring_txs]
            n_ring_tx = len(ring_txs)
            n_ring_acc = len(gt.ring_accounts)
            total_amt = sum(t.amount for t in ring_txs)
            max_tx_amt = max(t.amount for t in ring_txs) if ring_txs else 0.0

            above_thresh = [t for t in ring_txs if t.amount >= SIM_NAIVE_THRESHOLD]
            pct_above = (len(above_thresh) / n_ring_tx * 100) if n_ring_tx > 0 else 0.0

            span_sec = (gt.end_ts - gt.start_ts).total_seconds()
            span_hrs = span_sec / 3600.0

            # Weak connectivity check
            G = nx.Graph()
            for t in ring_txs:
                G.add_edge(t.src, t.dst)
            is_connected = (set(G.nodes) == gt.ring_accounts) and nx.is_connected(G)

            attack_results[(atk_type, diff)] = {
                "n_ring_tx": n_ring_tx,
                "n_ring_acc": n_ring_acc,
                "total_amt": total_amt,
                "max_tx_amt": max_tx_amt,
                "pct_above": pct_above,
                "span_sec": span_sec,
                "span_hrs": span_hrs,
                "mixed_count": len(mixed_txs),
                "ring_accounts": gt.ring_accounts,
                "is_connected": is_connected,
                "ring_txs": ring_txs,
            }

            print(
                f"{diff:<5} | {n_ring_tx:<8} | {n_ring_acc:<9} | INR {total_amt:>10,.2f} | "
                f"INR {max_tx_amt:>7,.2f} | {pct_above:>10.1f}% | {span_hrs:>8.2f} hrs | {len(mixed_txs):>11}"
            )

    # -----------------------------------------------------------------------
    # 4. Volume Preservation: Mean total amount by attack x diff over seeds 1-5
    # -----------------------------------------------------------------------
    print("\n[SECTION 4] Volume Preservation Table: Mean Total Amount (INR) over Seeds 1-5")
    header_vol = f"{'Attack Typology':<15} | " + " | ".join(f"Diff {d} (INR)" for d in range(1, 6))
    print(header_vol)
    print("-" * len(header_vol))

    for atk_type in attack_types:
        row_means = []
        for diff in range(1, 6):
            seed_totals = []
            for s in range(1, 6):
                rng = np.random.default_rng(seed=100 * s + diff)
                _, gt = inject_attack(
                    attack_type=atk_type,
                    rng=rng,
                    accounts=accounts,
                    start_ts=base_ts,
                    difficulty=diff,
                    ring_id=f"RING-{s}-{diff}",
                )
                seed_totals.append(gt.total_amount)
            mean_val = float(np.mean(seed_totals))
            row_means.append(f"INR {mean_val:>10,.0f}")
        print(f"{atk_type:<15} | " + " | ".join(row_means))

    # -----------------------------------------------------------------------
    # 5. Automatic Sanity Assertions
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("[SECTION 5] Automatic Sanity Assertions")
    print("=" * 80)
    all_passed = True

    # 1. Same seed gives identical output
    ds_a, _ = generate_dataset(seed=seeds_to_test[0], difficulty=3, duration_hours=6.0, attacks=["smurfing", "mule_chain"])
    ds_b, _ = generate_dataset(seed=seeds_to_test[0], difficulty=3, duration_hours=6.0, attacks=["smurfing", "mule_chain"])
    is_identical = len(ds_a) == len(ds_b) and all(
        a.tx_id == b.tx_id and a.ts == b.ts and a.src == b.src and a.dst == b.dst and
        a.amount == b.amount and a.kind == b.kind
        for a, b in zip(ds_a, ds_b)
    )
    if is_identical:
        print("  [PASS] 1. Same seed gives 100% bitwise identical output.")
    else:
        print("  [FAIL] 1. Same seed produced differing output!")
        all_passed = False

    # 2. Ground-truth accounts are all real accounts
    real_account_ids = set(a.account_id for a in accounts)
    all_real = all(res["ring_accounts"].issubset(real_account_ids) for res in attack_results.values())
    if all_real:
        print("  [PASS] 2. Ground-truth accounts are all real accounts in the pool.")
    else:
        print("  [FAIL] 2. Found unknown accounts in ground truth!")
        all_passed = False

    # (a) Connectivity: every GT account appears in >= 1 ring tx, and ring is weakly connected
    all_connected = True
    for (atk_type, diff), res in attack_results.items():
        if not res["is_connected"]:
            print(f"       Failed connectivity for {atk_type} d{diff}!")
            all_connected = False
    if all_connected:
        print("  [PASS] 3 (a). Connectivity: Every GT account appears in >= 1 ring tx, and ring is weakly connected.")
    else:
        print("  [FAIL] 3 (a). Connectivity violated!")
        all_passed = False

    # (d) No label leakage: normal kind vocabulary only, no 'ring_hop', sequential tx_ids
    allowed_kinds = {"p2p", "merchant_payment", "payroll", "rent", "large_purchase"}
    no_leakage_kinds = all(t.kind in allowed_kinds for t in ds_a)
    has_ring_hop = any(t.kind == "ring_hop" for t in ds_a)
    tx_ids_ordered = [t.tx_id for t in ds_a] == [f"TX-{i:08d}" for i in range(1, len(ds_a) + 1)]

    if no_leakage_kinds and not has_ring_hop and tx_ids_ordered:
        print("  [PASS] 4 (d). No label leakage: Real vocabulary only (no 'ring_hop'); tx_ids assigned sequentially.")
    else:
        print(f"  [FAIL] 4 (d). Label leakage detected! (has_ring_hop={has_ring_hop}, tx_ids_ordered={tx_ids_ordered})")
        all_passed = False

    # (e) % of ring tx above threshold non-increasing with difficulty and exactly 0% at difficulty 5
    pct_valid = True
    for atk_type in attack_types:
        pcts = [attack_results[(atk_type, d)]["pct_above"] for d in range(1, 6)]
        non_increasing = all(pcts[i] >= pcts[i + 1] for i in range(4))
        zero_at_d5 = (pcts[4] == 0.0)
        if not (non_increasing and zero_at_d5):
            print(f"       Failed % threshold for {atk_type}: {pcts}")
            pct_valid = False
    if pct_valid:
        print("  [PASS] 5 (e). % above threshold is non-increasing and exactly 0% at difficulty 5.")
    else:
        print("  [FAIL] 5 (e). % above threshold failed monotonicity or is non-zero at difficulty 5!")
        all_passed = False

    # Time span strictly increases with difficulty
    span_valid = True
    for atk_type in attack_types:
        if atk_type == "stealth":
            continue  # Stealth always runs at difficulty 5
        spans = [attack_results[(atk_type, d)]["span_sec"] for d in range(1, 6)]
        if not all(spans[i] < spans[i + 1] for i in range(4)):
            print(f"       Failed time span for {atk_type}: {spans}")
            span_valid = False
    if span_valid:
        print("  [PASS] 6. Time span strictly increases with difficulty.")
    else:
        print("  [FAIL] 6. Time span did not increase strictly with difficulty!")
        all_passed = False

    # No tx has src == dst
    no_self = all(tx.src != tx.dst for tx in ds_a)
    if no_self:
        print("  [PASS] 7. No transaction has src == dst.")
    else:
        print("  [FAIL] 7. Found transaction with src == dst!")
        all_passed = False

    # No negative amounts
    no_neg = all(tx.amount > 0.0 for tx in ds_a)
    if no_neg:
        print("  [PASS] 8. No negative or zero transaction amounts.")
    else:
        print("  [FAIL] 8. Found negative or zero amounts!")
        all_passed = False

    # Timestamps are sorted
    ts_sorted = all(ds_a[i].ts <= ds_a[i + 1].ts for i in range(len(ds_a) - 1))
    if ts_sorted:
        print("  [PASS] 9. All transactions are strictly sorted by timestamp.")
    else:
        print("  [FAIL] 9. Transactions not sorted by timestamp!")
        all_passed = False

    print("\n" + "=" * 80)
    if all_passed:
        print("ALL STEP 0 ASSERTIONS PASSED SUCCESSFULLY (PASS)!")
    else:
        print("SOME STEP 0 ASSERTIONS FAILED (FAIL)!")
    print("=" * 80)

    return all_passed


if __name__ == "__main__":
    success = run_checks(seeds_to_test=(1, 2, 3))
    sys.exit(0 if success else 1)
