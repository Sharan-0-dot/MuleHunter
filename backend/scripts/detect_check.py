"""
Mule Hunter — M2 Detector & Clustering Verification Suite
Step A Quality Fixes & Sanity Gates (G1 - G6).
Evaluates seeds 1-3 (strictly reserving 100-104 for M3 evaluation, and 50-54 for validation).
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import time

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import numpy as np

from app.config import SIM_NAIVE_THRESHOLD, WINDOW_HOURS
from app.sim.generator import generate_accounts_pool, generate_dataset, Transaction
from app.sim.attacks import inject_attack
from app.detect.window import SlidingWindow, test_sliding_window_oracle
import app.detect.patterns as patterns_module
from app.detect.patterns import detect, PatternInstance, DETECTOR_PARAMS
from app.detect.clusters import build_clusters, cluster_features, Cluster
from app.detect.tracker import ClusterTracker


def run_toy_graphs_test() -> bool:
    """Test detection of hand-built toy graphs."""
    base_t = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Hand-built 4-Cycle: A -> B -> C -> D -> A
    win_cycle = SlidingWindow(window_hours=48.0)
    cycle_txs = [
        Transaction("T1", base_t + timedelta(hours=1), "A", "B", 100000.0, "p2p"),
        Transaction("T2", base_t + timedelta(hours=2), "B", "C", 98000.0, "p2p"),
        Transaction("T3", base_t + timedelta(hours=3), "C", "D", 96000.0, "p2p"),
        Transaction("T4", base_t + timedelta(hours=4), "D", "A", 95000.0, "p2p"),
    ]
    for t in cycle_txs:
        win_cycle.add(t)
    inst_cycle = detect(win_cycle, base_t + timedelta(hours=5))
    clust_cycle = build_clusters(inst_cycle, win_cycle)
    cycle_detected = any(c.typology == "round_tripping" for c in clust_cycle)

    # 2. Hand-built 5-Node Mule Chain: N1 -> N2 -> N3 -> N4 -> N5
    win_chain = SlidingWindow(window_hours=48.0)
    chain_txs = [
        Transaction("TC1", base_t + timedelta(hours=1), "N1", "N2", 100000.0, "p2p"),
        Transaction("TC2", base_t + timedelta(hours=2), "N2", "N3", 98000.0, "p2p"),
        Transaction("TC3", base_t + timedelta(hours=3), "N3", "N4", 96000.0, "p2p"),
        Transaction("TC4", base_t + timedelta(hours=4), "N4", "N5", 94000.0, "p2p"),
    ]
    for t in chain_txs:
        win_chain.add(t)
    inst_chain = detect(win_chain, base_t + timedelta(hours=5))
    clust_chain = build_clusters(inst_chain, win_chain)
    chain_detected = any(c.typology == "mule_chain" for c in clust_chain)

    # 3. Hand-built Fan-Out with Reconvergence: S -> M1, M2, M3, M4 -> D
    win_rec = SlidingWindow(window_hours=48.0)
    rec_txs = [
        # Fan-out: S -> M1..M4 (total 120k > 100k, 4 counterparties, CV < 0.8)
        Transaction("TR1", base_t + timedelta(hours=1), "S", "M1", 30000.0, "p2p"),
        Transaction("TR2", base_t + timedelta(hours=1, minutes=5), "S", "M2", 30000.0, "p2p"),
        Transaction("TR3", base_t + timedelta(hours=1, minutes=10), "S", "M3", 30000.0, "p2p"),
        Transaction("TR4", base_t + timedelta(hours=1, minutes=15), "S", "M4", 30000.0, "p2p"),
        # Reconvergence: M1..M4 -> D
        Transaction("TR5", base_t + timedelta(hours=2), "M1", "D", 29000.0, "p2p"),
        Transaction("TR6", base_t + timedelta(hours=2, minutes=5), "M2", "D", 29000.0, "p2p"),
        Transaction("TR7", base_t + timedelta(hours=2, minutes=10), "M3", "D", 29000.0, "p2p"),
        Transaction("TR8", base_t + timedelta(hours=2, minutes=15), "M4", "D", 29000.0, "p2p"),
    ]
    for t in rec_txs:
        win_rec.add(t)
    inst_rec = detect(win_rec, base_t + timedelta(hours=3))
    clust_rec = build_clusters(inst_rec, win_rec)
    rec_detected = any(c.typology == "smurfing_fan_out_fan_in" for c in clust_rec)

    return cycle_detected and chain_detected and rec_detected


def run_checks():
    print("=" * 80)
    print("MULE HUNTER — M2 DETECTOR & CLUSTERING VERIFICATION SUITE (STEP A QUALITY FIXES)")
    print("=" * 80)
    print(f"WINDOW_HOURS = {WINDOW_HOURS} hours, SIM_NAIVE_THRESHOLD = INR {SIM_NAIVE_THRESHOLD:,.2f}")
    seeds = [1, 2, 3]

    tick_runtimes_ms = []
    cycle_cap_hit_count = 0
    total_ticks = 0
    all_cluster_sizes = []
    large_clusters = []

    # Typology confusion tracking
    known_typologies = ["smurfing_fan_out_fan_in", "round_tripping", "mule_chain", "hybrid", "fan_out", "fan_in", "none"]
    type_name_map = {
        "smurfing": "smurfing_fan_out_fan_in",
        "round_trip": "round_tripping",
        "mule_chain": "mule_chain",
        "hybrid": "hybrid",
    }
    confusion_matrix = {t: Counter() for t in ["smurfing", "round_trip", "mule_chain", "hybrid"]}
    typology_correct_d13 = 0
    typology_total_d13 = 0

    # Gate G4 tracking: diff 1-3 non-stealth
    g4_found_count = 0
    g4_total_runs = 0
    g4_coverages = []
    g4_purities = []

    # Diagnostic tracking for misses
    miss_diagnostics = []
    miss_categories = Counter()

    # -----------------------------------------------------------------------
    # 1. Attack Matrix: 4 Non-Stealth Typologies x Difficulty 1-5 across Seeds 1-3
    # -----------------------------------------------------------------------
    print("\n[SECTION 1] Attack Detection Matrix (Seeds 1, 2, 3)")
    base_types = ["smurfing", "round_trip", "mule_chain", "hybrid"]
    base_ts = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)
    accounts = generate_accounts_pool()
    accounts_dict = {a.account_id: a for a in accounts}

    for atk_type in base_types:
        print(f"\n--- Typology: {atk_type.upper()} ---")
        header = f"{'Diff':<5} | {'Found (Any)':<12} | {'Found (Final)':<13} | {'Avg Cov':<9} | {'Avg Purity':<11} | {'Typology Acc':<13} | {'Top Typology':<24}"
        print(header)
        print("-" * len(header))

        for diff in range(1, 6):
            found_any_count = 0
            found_final_count = 0
            cov_list = []
            purity_list = []
            size_list = []
            typologies_fired = []
            typology_match_count = 0

            for s in seeds:
                rng = np.random.default_rng(seed=100 * s + diff)
                atk_start = base_ts + timedelta(hours=24)
                ring_txs, gt = inject_attack(
                    attack_type=atk_type,
                    rng=rng,
                    accounts=accounts,
                    start_ts=atk_start,
                    difficulty=diff,
                    ring_id=f"RING-{s}-{diff}",
                )

                # Generate background legit traffic for 96 hours
                legit_txs, _ = generate_dataset(
                    seed=s,
                    difficulty=1,
                    duration_hours=96.0,
                    attacks=None,
                    start_ts=base_ts,
                )

                all_stream = sorted(legit_txs + ring_txs, key=lambda t: t.ts)
                window = SlidingWindow(window_hours=WINDOW_HOURS)
                stream_idx = 0
                n_txs = len(all_stream)

                best_match_cluster = None
                best_match_cov = 0.0
                best_match_purity = 0.0
                final_tick_found = False

                final_ring_tx_time = max(t.ts for t in gt.metadata["ring_txs"])
                final_sim_hr = int((final_ring_tx_time - base_ts).total_seconds() / 3600.0) + 1
                sim_hr_end = min(96, max(final_sim_hr + 2, int((gt.end_ts - base_ts).total_seconds() / 3600.0) + 6))

                ring_patterns_observed = set()
                overlapping_clusters_seen = []

                for sim_hr in range(24, sim_hr_end + 1):
                    curr_sim_time = base_ts + timedelta(hours=sim_hr)

                    while stream_idx < n_txs and all_stream[stream_idx].ts <= curr_sim_time:
                        window.add(all_stream[stream_idx])
                        stream_idx += 1

                    window.advance(curr_sim_time)

                    t0 = time.perf_counter()
                    instances = detect(window, curr_sim_time)
                    clusters = build_clusters(instances, window, accounts_dict)
                    dt_ms = (time.perf_counter() - t0) * 1000.0

                    tick_runtimes_ms.append(dt_ms)
                    total_ticks += 1
                    if patterns_module.cycle_cap_hit:
                        cycle_cap_hit_count += 1

                    for p in instances:
                        if p.accounts & gt.ring_accounts:
                            ring_patterns_observed.add(p.pattern_type)

                    is_final_tick = (sim_hr == final_sim_hr)

                    for c in clusters:
                        sz = len(c.accounts)
                        all_cluster_sizes.append(sz)
                        if sz > 60:
                            large_clusters.append((c.cluster_id, sz, c.typology, curr_sim_time))

                        overlap = len(c.accounts & gt.ring_accounts)
                        if overlap > 0:
                            overlapping_clusters_seen.append((c, overlap))
                            purity = overlap / sz
                            cov = overlap / len(gt.ring_accounts)

                            if purity >= 0.5 and cov > best_match_cov:
                                best_match_cov = cov
                                best_match_purity = purity
                                best_match_cluster = c

                            if is_final_tick and purity >= 0.5 and cov >= 0.5:
                                final_tick_found = True

                expected_typology = type_name_map[atk_type]

                if best_match_cluster is not None and best_match_cov >= 0.5:
                    found_any_count += 1
                    cov_list.append(best_match_cov)
                    purity_list.append(best_match_purity)
                    size_list.append(len(best_match_cluster.accounts))
                    typologies_fired.append(best_match_cluster.typology)
                    confusion_matrix[atk_type][best_match_cluster.typology] += 1

                    if best_match_cluster.typology == expected_typology:
                        typology_match_count += 1
                        if diff <= 3:
                            typology_correct_d13 += 1
                    if diff <= 3:
                        typology_total_d13 += 1
                else:
                    confusion_matrix[atk_type]["none"] += 1
                    if diff <= 3:
                        typology_total_d13 += 1

                if final_tick_found:
                    found_final_count += 1

                # Gate G4 tracking
                if diff <= 3:
                    g4_total_runs += 1
                    if best_match_cluster is not None and best_match_cov >= 0.5:
                        g4_found_count += 1
                        g4_coverages.append(best_match_cov)
                        g4_purities.append(best_match_purity)
                    else:
                        g4_coverages.append(0.0)
                        g4_purities.append(0.0)

                # Miss diagnostic: check if ring missed or coverage < 80%
                if best_match_cluster is None or best_match_cov < 0.80:
                    # Diagnose root-cause
                    # (a) Ring evicted from window?
                    first_ring_tx_ts = min(t.ts for t in gt.metadata["ring_txs"])
                    last_ring_tx_ts = max(t.ts for t in gt.metadata["ring_txs"])
                    ring_span_hours = (last_ring_tx_ts - first_ring_tx_ts).total_seconds() / 3600.0

                    if ring_span_hours > WINDOW_HOURS:
                        cat = "(a) ring evicted from the window"
                    elif not ring_patterns_observed:
                        cat = "(b) no candidate generated"
                    elif any(c.accounts & gt.ring_accounts and (len(c.accounts & gt.ring_accounts) / len(c.accounts) < 0.5) for c, _ in overlapping_clusters_seen):
                        cat = "(c) merged into a giant/impure cluster (purity < 50%)"
                    elif len(overlapping_clusters_seen) > 1 and max(ov for _, ov in overlapping_clusters_seen) / len(gt.ring_accounts) < 0.8:
                        cat = "(d) fragmented across several clusters"
                    else:
                        cat = "(b) no candidate generated"

                    miss_categories[cat] += 1
                    pats_str = ", ".join(sorted(ring_patterns_observed)) if ring_patterns_observed else "none"
                    miss_diagnostics.append(
                        f"  - {atk_type} (d={diff}, seed={s}): {cat} [cov={best_match_cov*100:.1f}%, patterns_on_ring: {pats_str}]"
                    )

            avg_cov = f"{np.mean(cov_list)*100:>5.1f}%" if cov_list else "  0.0%"
            avg_purity = f"{np.mean(purity_list)*100:>5.1f}%" if purity_list else "  0.0%"
            top_type = Counter(typologies_fired).most_common(1)[0][0] if typologies_fired else "none"

            print(
                f"{diff:<5} | {found_any_count}/3         | {found_final_count}/3           | {avg_cov:<9} | {avg_purity:<11} | {typology_match_count}/3          | {top_type:<24}",
                flush=True,
            )

    # -----------------------------------------------------------------------
    # 1B. Separate Scenario: STEALTH (Always Diff 5 base attack structured)
    # -----------------------------------------------------------------------
    print("\n--- Scenario: STEALTH (Difficulty 5 Structured Below SIM_NAIVE_THRESHOLD) ---")
    header = f"{'Seed':<5} | {'Found (Any)':<12} | {'Found (Final)':<13} | {'Coverage':<9} | {'Purity':<11} | {'Cluster Size':<13} | {'Base Type':<16} | {'Detected Typology'}"
    print(header)
    print("-" * len(header))

    stealth_covs = []
    stealth_purities = []
    stealth_found_any = 0
    stealth_found_final = 0

    for s in seeds:
        rng = np.random.default_rng(seed=999 * s + 5)
        atk_start = base_ts + timedelta(hours=24)
        ring_txs, gt = inject_attack(
            attack_type="stealth",
            rng=rng,
            accounts=accounts,
            start_ts=atk_start,
            difficulty=5,
            ring_id=f"RING-STEALTH-{s}",
        )
        base_typology = gt.metadata.get("base_type", "smurfing")

        legit_txs, _ = generate_dataset(
            seed=s,
            difficulty=1,
            duration_hours=96.0,
            attacks=None,
            start_ts=base_ts,
        )

        all_stream = sorted(legit_txs + ring_txs, key=lambda t: t.ts)
        window = SlidingWindow(window_hours=WINDOW_HOURS)
        stream_idx = 0
        n_txs = len(all_stream)

        best_match_cluster = None
        best_match_cov = 0.0
        best_match_purity = 0.0
        final_tick_found = False

        final_ring_tx_time = max(t.ts for t in gt.metadata["ring_txs"])
        final_sim_hr = int((final_ring_tx_time - base_ts).total_seconds() / 3600.0) + 1
        sim_hr_end = min(96, max(final_sim_hr + 2, int((gt.end_ts - base_ts).total_seconds() / 3600.0) + 6))

        for sim_hr in range(24, sim_hr_end + 1):
            curr_sim_time = base_ts + timedelta(hours=sim_hr)

            while stream_idx < n_txs and all_stream[stream_idx].ts <= curr_sim_time:
                window.add(all_stream[stream_idx])
                stream_idx += 1

            window.advance(curr_sim_time)

            t0 = time.perf_counter()
            instances = detect(window, curr_sim_time)
            clusters = build_clusters(instances, window, accounts_dict)
            dt_ms = (time.perf_counter() - t0) * 1000.0

            tick_runtimes_ms.append(dt_ms)
            total_ticks += 1
            if patterns_module.cycle_cap_hit:
                cycle_cap_hit_count += 1

            is_final_tick = (sim_hr == final_sim_hr)

            for c in clusters:
                sz = len(c.accounts)
                all_cluster_sizes.append(sz)
                if sz > 60:
                    large_clusters.append((c.cluster_id, sz, c.typology, curr_sim_time))

                overlap = len(c.accounts & gt.ring_accounts)
                if overlap > 0:
                    purity = overlap / sz
                    cov = overlap / len(gt.ring_accounts)

                    if purity >= 0.5 and cov > best_match_cov:
                        best_match_cov = cov
                        best_match_purity = purity
                        best_match_cluster = c

                    if is_final_tick and purity >= 0.5 and cov >= 0.5:
                        final_tick_found = True

        if best_match_cluster is not None and best_match_cov >= 0.5:
            stealth_found_any += 1
            stealth_covs.append(best_match_cov)
            stealth_purities.append(best_match_purity)
            detected_typ = best_match_cluster.typology
            cl_sz = len(best_match_cluster.accounts)
        else:
            detected_typ = "none"
            cl_sz = 0

        if final_tick_found:
            stealth_found_final += 1

        print(
            f"{s:<5} | {'YES' if best_match_cluster else 'NO':<12} | {'YES' if final_tick_found else 'NO':<13} | {best_match_cov*100:>5.1f}%   | {best_match_purity*100:>5.1f}%    | {cl_sz:<13} | {base_typology:<16} | {detected_typ}",
            flush=True,
        )

    # -----------------------------------------------------------------------
    # Typology Confusion Matrix
    # -----------------------------------------------------------------------
    print("\n[SECTION 1C] Typology Confusion Matrix (Diff 1-5 across Seeds 1-3)")
    conf_types = ["smurfing_fan_out_fan_in", "round_tripping", "mule_chain", "hybrid", "fan_out", "fan_in", "none"]
    conf_header = f"{'Ground Truth Ring':<24} | " + " | ".join(f"{t[:10]:>10}" for t in conf_types)
    print(conf_header)
    print("-" * len(conf_header))
    for atk_type in base_types:
        row_counts = [confusion_matrix[atk_type][t] for t in conf_types]
        row_str = " | ".join(f"{c:>10}" for c in row_counts)
        print(f"{type_name_map[atk_type]:<24} | {row_str}")

    # -----------------------------------------------------------------------
    # Miss Diagnostic Report (A6)
    # -----------------------------------------------------------------------
    print("\n[SECTION 1D] Miss & Sub-80% Coverage Diagnostic Report (A6)")
    print(f"Total Diagnosed Runs: {len(miss_diagnostics)}")
    print("Summary Count by Root-Cause Category:")
    for cat, cnt in miss_categories.most_common():
        print(f"  {cat:<50} : {cnt}")
    print("\nDetailed Miss Diagnostics (First 15):")
    for d in miss_diagnostics[:15]:
        print(d)

    # -----------------------------------------------------------------------
    # 2. Legit-Only Runs & ClusterTracker (A7, G3)
    # -----------------------------------------------------------------------
    print("\n[SECTION 2] Legit-Only Runs with ClusterTracker (96h, Seeds 1, 2, 3)")
    legit_all_cluster_sizes = []
    legit_tracked_daily_counts = []
    legit_tracked_pattern_breakdown = Counter()

    for s in seeds:
        legit_txs, _ = generate_dataset(
            seed=s,
            difficulty=1,
            duration_hours=96.0,
            attacks=None,
            start_ts=base_ts,
        )
        window = SlidingWindow(window_hours=WINDOW_HOURS)
        tracker = ClusterTracker(jaccard_threshold=0.5)
        stream_idx = 0
        n_txs = len(legit_txs)

        for sim_hr in range(1, 97):
            curr_sim_time = base_ts + timedelta(hours=sim_hr)
            while stream_idx < n_txs and legit_txs[stream_idx].ts <= curr_sim_time:
                window.add(legit_txs[stream_idx])
                stream_idx += 1
            window.advance(curr_sim_time)

            t0 = time.perf_counter()
            instances = detect(window, curr_sim_time)
            clusters = build_clusters(instances, window, accounts_dict)
            dt_ms = (time.perf_counter() - t0) * 1000.0

            tick_runtimes_ms.append(dt_ms)
            total_ticks += 1
            if patterns_module.cycle_cap_hit:
                cycle_cap_hit_count += 1

            for c in clusters:
                sz = len(c.accounts)
                legit_all_cluster_sizes.append(sz)

            # Update ClusterTracker
            tracker.update(clusters, curr_sim_time)

        # 96 hours = 4 sim-days
        total_unique_tracks = len(tracker.all_tracks())
        daily_unique = total_unique_tracks / 4.0
        legit_tracked_daily_counts.append(daily_unique)
        for trk in tracker.all_tracks():
            legit_tracked_pattern_breakdown[trk.typology] += 1

    legit_p99 = np.percentile(legit_all_cluster_sizes, 99) if legit_all_cluster_sizes else 0.0
    legit_max = np.max(legit_all_cluster_sizes) if legit_all_cluster_sizes else 0
    mean_unique_daily = np.mean(legit_tracked_daily_counts) if legit_tracked_daily_counts else 0.0

    print(f"Legit-Only Candidate Cluster Size Percentiles (Snapshot Level):")
    print(f"  - p50 (Median) : {np.percentile(legit_all_cluster_sizes, 50):.1f} accounts")
    print(f"  - p90          : {np.percentile(legit_all_cluster_sizes, 90):.1f} accounts")
    print(f"  - p99          : {legit_p99:.1f} accounts (Gate G3 target: <= 40)")
    print(f"  - Max          : {legit_max} accounts (Gate G3 target: <= 80)")
    print(f"\nUnique Tracked Candidate Clusters / Legit Sim-Day: {mean_unique_daily:.1f}")
    print("Unique Tracked Candidate Clusters Breakdown by Detected Typology:")
    for typ, cnt in legit_tracked_pattern_breakdown.most_common():
        print(f"  - {typ:<24} : {cnt}")

    # -----------------------------------------------------------------------
    # 3. Runtime per Tick & Cycle Cap Budget (A3, G2)
    # -----------------------------------------------------------------------
    print("\n[SECTION 3] Runtime per Tick & Cycle Cap Budget (Gate G2)")
    mean_ms = float(np.mean(tick_runtimes_ms))
    max_ms = float(np.max(tick_runtimes_ms))
    p95_ms = float(np.percentile(tick_runtimes_ms, 95))
    cap_pct = (cycle_cap_hit_count / total_ticks * 100) if total_ticks > 0 else 0.0

    print(f"Total Detection Ticks Evaluated : {total_ticks:,}")
    print(f"Mean Runtime per Tick           : {mean_ms:>6.2f} ms (Gate G2 target: < 500 ms)")
    print(f"p95 Runtime per Tick            : {p95_ms:>6.2f} ms")
    print(f"Max Runtime per Tick            : {max_ms:>6.2f} ms")
    print(f"Cycle Budget Cap Hit Frequency  : {cycle_cap_hit_count} / {total_ticks} ({cap_pct:.2f}%) (Gate G2 target: < 5%)")

    # -----------------------------------------------------------------------
    # 4. Ring Span Verification across seeds 1-5 (A2, G1)
    # -----------------------------------------------------------------------
    print("\n[SECTION 4] Ring Span vs Window Assertion (Gate G1)")
    max_allowed_span = 0.75 * WINDOW_HOURS
    g1_ok = True
    max_observed_span = 0.0

    for atk in ["smurfing", "round_trip", "mule_chain", "hybrid", "stealth"]:
        for d in range(1, 6):
            for s in range(1, 6):
                rng = np.random.default_rng(100 * s + d)
                _, gt_tmp = inject_attack(atk, rng, accounts, base_ts, difficulty=d)
                span_h = (gt_tmp.end_ts - gt_tmp.start_ts).total_seconds() / 3600.0
                if span_h > max_observed_span:
                    max_observed_span = span_h
                if span_h > max_allowed_span:
                    g1_ok = False
                    print(f"  [VIOLATION] {atk} d{d} s{s} span={span_h:.2f}h > {max_allowed_span:.2f}h")

    print(f"Max Observed Ring Span across seeds 1-5: {max_observed_span:.2f} hours (Limit: <= {max_allowed_span:.2f} hours)")

    # -----------------------------------------------------------------------
    # 5. Step A Quality Gates (G1 - G6)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP A SANITY GATES (G1 - G6) VERIFICATION")
    print("=" * 80)
    all_gates_pass = True

    # Gate G1: ring span <= 0.75*WINDOW_HOURS everywhere
    if g1_ok:
        print("  [PASS] G1: Ring span <= 0.75 * WINDOW_HOURS (36.0h) for all types and difficulties, seeds 1-5.")
    else:
        print("  [FAIL] G1: Ring span exceeded 0.75 * WINDOW_HOURS!")
        all_gates_pass = False

    # Gate G2: cycle cap hit < 5% of ticks, mean tick < 500 ms
    g2_ok = (cap_pct < 5.0) and (mean_ms < 500.0)
    if g2_ok:
        print(f"  [PASS] G2: Cycle cap hit rate = {cap_pct:.2f}% (< 5%), mean tick = {mean_ms:.2f} ms (< 500 ms).")
    else:
        print(f"  [FAIL] G2: Cycle search performance target violated (cap_hit={cap_pct:.2f}%, mean_tick={mean_ms:.2f}ms)!")
        all_gates_pass = False

    # Gate G3: legit-only p99 cluster size <= 40, max <= 80
    g3_ok = (legit_p99 <= 40.0) and (legit_max <= 80)
    if g3_ok:
        print(f"  [PASS] G3: Legit-only p99 cluster size = {legit_p99:.1f} (<= 40), max = {legit_max} (<= 80).")
    else:
        print(f"  [FAIL] G3: Legit-only cluster size target violated (p99={legit_p99:.1f}, max={legit_max})!")
        all_gates_pass = False

    # Gate G4: diff 1-3 non-stealth: found 3/3, mean coverage >= 85%, mean purity >= 70%
    mean_g4_cov = np.mean(g4_coverages) if g4_coverages else 0.0
    mean_g4_purity = np.mean(g4_purities) if g4_purities else 0.0
    g4_all_found = (g4_found_count == g4_total_runs)
    g4_ok = g4_all_found and (mean_g4_cov >= 0.85) and (mean_g4_purity >= 0.70)
    if g4_ok:
        print(f"  [PASS] G4: Diff 1-3 found = {g4_found_count}/{g4_total_runs} (100%), mean coverage = {mean_g4_cov*100:.1f}% (>= 85%), mean purity = {mean_g4_purity*100:.1f}% (>= 70%).")
    else:
        print(f"  [FAIL] G4: Diff 1-3 targets missed (found={g4_found_count}/{g4_total_runs}, mean_cov={mean_g4_cov*100:.1f}%, mean_purity={mean_g4_purity*100:.1f}%)!")
        all_gates_pass = False

    # Gate G5: diff 1-3 typology accuracy >= 80% overall
    overall_typology_acc = (typology_correct_d13 / typology_total_d13) if typology_total_d13 > 0 else 0.0
    g5_ok = (overall_typology_acc >= 0.80)
    if g5_ok:
        print(f"  [PASS] G5: Diff 1-3 overall typology accuracy = {overall_typology_acc*100:.1f}% ({typology_correct_d13}/{typology_total_d13}) (>= 80%).")
    else:
        print(f"  [FAIL] G5: Diff 1-3 typology accuracy = {overall_typology_acc*100:.1f}% (< 80%)!")
        all_gates_pass = False

    # Gate G6: leakage guard and window oracle pass
    oracle_ok = test_sliding_window_oracle()
    toy_ok = run_toy_graphs_test()

    test_ds, _ = generate_dataset(seed=1, difficulty=2, duration_hours=48.0, attacks=["round_trip"])
    w1 = SlidingWindow(48.0)
    for t in test_ds:
        w1.add(t)
    clust1 = build_clusters(detect(w1, base_ts + timedelta(hours=48)), w1)

    w2 = SlidingWindow(48.0)
    for t in test_ds:
        w2.add(Transaction(t.tx_id, t.ts, t.src, t.dst, t.amount, "MASKED"))
    clust2 = build_clusters(detect(w2, base_ts + timedelta(hours=48)), w2)

    leakage_ok = (
        len(clust1) == len(clust2) and
        all(c1.typology == c2.typology and c1.accounts == c2.accounts for c1, c2 in zip(clust1, clust2))
    )

    g6_ok = oracle_ok and toy_ok and leakage_ok
    if g6_ok:
        print("  [PASS] G6: Window oracle test, toy graphs test, and Leakage Guard (masked kind) all pass.")
    else:
        print(f"  [FAIL] G6: Oracle ({oracle_ok}), Toy ({toy_ok}), or Leakage Guard ({leakage_ok}) failed!")
        all_gates_pass = False

    print("=" * 80)
    if all_gates_pass:
        print(">>> ALL STEP A GATES (G1 - G6) PASSED SUCCESSFULLY! PROCEED TO STEP B. <<<")
    else:
        print(">>> ONE OR MORE STEP A GATES FAILED! STOPPING AS PER GATE RULE. <<<")
    print("=" * 80)

    return all_gates_pass


if __name__ == "__main__":
    success = run_checks()
    sys.exit(0 if success else 1)
