"""
Graph pattern detectors for anti-money laundering typologies.

Detects:
1. fan_out / fan_in: multi-scale (2h, 12h, 48h), >= 4 counterparties, amount CV < 0.8.
2. reconvergence (smurfing_fan_out_fan_in): fan-out branches meeting at a common destination within <= 3 hops.
3. time-respecting cycles (round_tripping): DFS along increasing timestamps, length 3-6, retention >= 0.5.
4. mule chains (mule_chain): >= 3 consecutive mule-like nodes (pass_through >= 0.75, hold < 12h).

Recall-oriented candidate generation. Zero label leakage: uses ONLY graph structure,
timestamps, amounts, and account types (never reads tx.kind or ground truth).
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Dict, List, Optional, Set, Tuple
import numpy as np

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import SIM_NAIVE_THRESHOLD, WINDOW_HOURS
from app.detect.window import SlidingWindow

# ---------------------------------------------------------------------------
# Detector Parameters Table (Tuned for high recall on candidate generation)
# ---------------------------------------------------------------------------
DETECTOR_PARAMS = {
    "scales_hours": [2.0, 12.0, 48.0],
    "fan_min_counterparties": 4,
    "fan_min_amount": 100_000.0,
    "fan_max_cv": 0.8,
    "candidate_min_flow": 15_000.0,
    "cycle_min_edge_amount": 5_000.0,
    "cycle_max_path_span_hours": 24.0,
    "hub_max_counterparties": 18,
    "mule_max_pass_through": 1.35,
    "reconvergence_max_hops": 3,
    "cycle_min_len": 3,
    "cycle_max_len": 6,
    "cycle_min_retention": 0.5,
    "cycle_max_start_nodes": 100,
    "cycle_max_edge_expansions": 5000,
    "mule_min_pass_through": 0.75,
    "mule_max_hold_hours": 12.0,
    "chain_min_length": 3,
}


@dataclass
class PatternInstance:
    pattern_type: str  # fan_out, fan_in, smurfing_fan_out_fan_in, round_tripping, mule_chain
    accounts: Set[str]
    core_accounts: Set[str]
    tx_ids: Set[str]
    start_ts: datetime
    end_ts: datetime
    total_amount: float
    meta: dict = field(default_factory=dict)


# Global tracking flag for cycle search budget
cycle_cap_hit: bool = False


def _calc_cv(amounts: List[float]) -> float:
    """Calculate Coefficient of Variation (std / mean)."""
    if len(amounts) <= 1:
        return 0.0
    arr = np.array(amounts, dtype=float)
    mean_val = float(np.mean(arr))
    if mean_val <= 0.0:
        return 0.0
    return float(np.std(arr) / mean_val)


# ---------------------------------------------------------------------------
# 1. Fan-Out and Fan-In Detectors (Multi-scale)
# ---------------------------------------------------------------------------
def detect_fan_out_fan_in(
    window: SlidingWindow,
    now: datetime,
) -> Tuple[List[PatternInstance], List[PatternInstance]]:
    """Detect fan-out and fan-in instances across 2h, 12h, 48h scales."""
    scales = DETECTOR_PARAMS["scales_hours"]
    min_cp = DETECTOR_PARAMS["fan_min_counterparties"]
    min_amt = DETECTOR_PARAMS["fan_min_amount"]
    max_cv = DETECTOR_PARAMS["fan_max_cv"]

    fan_outs: List[PatternInstance] = []
    fan_ins: List[PatternInstance] = []

    # --- Check Fan-Out for eligible nodes ---
    hub_max_cp = DETECTOR_PARAMS.get("hub_max_counterparties", 18)
    for node, targets in window.out_adj.items():
        if len(targets) < min_cp or len(targets) >= hub_max_cp or window.node_out_total.get(node, 0.0) < min_amt:
            continue

        out_edges = window.out_edges(node)
        for scale in scales:
            cutoff = now - timedelta(hours=scale)
            scale_txs = []
            cp_totals = defaultdict(float)

            for v, e_data in out_edges:
                for t in e_data["tx_list"]:
                    if t.ts >= cutoff:
                        scale_txs.append(t)
                        cp_totals[v] += t.amount

            if len(cp_totals) >= min_cp:
                total_amt = sum(cp_totals.values())
                if total_amt >= min_amt:
                    cv = _calc_cv(list(cp_totals.values()))
                    if cv < max_cv:
                        tx_ids = {t.tx_id for t in scale_txs}
                        start_ts = min(t.ts for t in scale_txs)
                        end_ts = max(t.ts for t in scale_txs)
                        recipients = set(cp_totals.keys())
                        fan_outs.append(
                            PatternInstance(
                                pattern_type="fan_out",
                                accounts={node} | recipients,
                                core_accounts={node},
                                tx_ids=tx_ids,
                                start_ts=start_ts,
                                end_ts=end_ts,
                                total_amount=round(total_amt, 2),
                                meta={"scale_hours": scale, "cv": round(cv, 4), "counterparties_count": len(recipients)},
                            )
                        )
                        break

    # --- Check Fan-In for eligible nodes ---
    for node, sources in window.in_adj.items():
        if len(sources) < min_cp or len(sources) >= hub_max_cp or window.node_in_total.get(node, 0.0) < min_amt:
            continue

        in_edges = window.in_edges(node)
        for scale in scales:
            cutoff = now - timedelta(hours=scale)
            scale_txs = []
            cp_totals = defaultdict(float)

            for u, e_data in in_edges:
                for t in e_data["tx_list"]:
                    if t.ts >= cutoff:
                        scale_txs.append(t)
                        cp_totals[u] += t.amount

            if len(cp_totals) >= min_cp:
                total_amt = sum(cp_totals.values())
                if total_amt >= min_amt:
                    cv = _calc_cv(list(cp_totals.values()))
                    if cv < max_cv:
                        tx_ids = {t.tx_id for t in scale_txs}
                        start_ts = min(t.ts for t in scale_txs)
                        end_ts = max(t.ts for t in scale_txs)
                        payers = set(cp_totals.keys())
                        fan_ins.append(
                            PatternInstance(
                                pattern_type="fan_in",
                                accounts={node} | payers,
                                core_accounts={node},
                                tx_ids=tx_ids,
                                start_ts=start_ts,
                                end_ts=end_ts,
                                total_amount=round(total_amt, 2),
                                meta={"scale_hours": scale, "cv": round(cv, 4), "counterparties_count": len(payers)},
                            )
                        )
                        break

    return fan_outs, fan_ins


# ---------------------------------------------------------------------------
# 2. Reconvergence Detector (smurfing_fan_out_fan_in)
# ---------------------------------------------------------------------------
def detect_reconvergence(
    window: SlidingWindow,
    fan_outs: List[PatternInstance],
) -> List[PatternInstance]:
    """
    Follow out-edges up to 3 hops from fan-out sources in time-respecting order.
    Emits smurfing_fan_out_fan_in instances when >= 2 branches reach a common destination.
    """
    reconvergence_instances: List[PatternInstance] = []
    min_flow = DETECTOR_PARAMS.get("candidate_min_flow", 15_000.0)

    for fo in fan_outs:
        source = list(fo.core_accounts)[0]
        # destination -> list of (branch_mule, intermediate_nodes, path_txs)
        reconverged_paths = defaultdict(list)

        # Hop 1: Out-edges from source (branches M_i)
        for mule, e1 in window.out_edges(source):
            if not e1["tx_list"] or e1["total"] < min_flow:
                continue
            t1 = next((t for t in e1["tx_list"] if t.amount >= min_flow), e1["tx_list"][0])

            # Hop 2: out-edges from mule -> n2
            for n2, e2 in window.out_edges(mule):
                if n2 == source or n2 == mule or e2["total"] < min_flow:
                    continue
                t2 = next((t for t in e2["tx_list"] if t.ts >= t1.ts and t.amount >= min_flow), None)
                if t2:
                    reconverged_paths[n2].append((mule, [mule], [t1, t2]))

                    # Hop 3: out-edges from n2 -> n3
                    for n3, e3 in window.out_edges(n2):
                        if n3 in (source, mule, n2) or e3["total"] < min_flow:
                            continue
                        t3 = next((t for t in e3["tx_list"] if t.ts >= t2.ts and t.amount >= min_flow), None)
                        if t3:
                            reconverged_paths[n3].append((mule, [mule, n2], [t1, t2, t3]))

        # Create an instance for each valid destination reached by >= 2 distinct branches
        for dest, paths in reconverged_paths.items():
            if dest == source:
                continue
            mule_branches = {mule for mule, _, _ in paths}
            if len(mule_branches) >= 2:
                dest_txs = []
                dest_core = {source, dest}
                dest_all = {source, dest}
                for mule, inters, p_txs in paths:
                    dest_core.add(mule)
                    dest_all.add(mule)
                    for n in inters:
                        dest_core.add(n)
                        dest_all.add(n)
                    for t in p_txs:
                        dest_txs.append(t)
                        dest_all.add(t.src)
                        dest_all.add(t.dst)

                unique_txs = list({t.tx_id: t for t in dest_txs}.values())
                unique_txs.sort(key=lambda t: t.ts)
                total_amt = sum(t.amount for t in unique_txs)

                reconvergence_instances.append(
                    PatternInstance(
                        pattern_type="smurfing_fan_out_fan_in",
                        accounts=dest_all,
                        core_accounts=dest_core,
                        tx_ids={t.tx_id for t in unique_txs},
                        start_ts=unique_txs[0].ts,
                        end_ts=unique_txs[-1].ts,
                        total_amount=round(total_amt, 2),
                        meta={
                            "source": source,
                            "destination": dest,
                            "branches_count": len(mule_branches),
                        },
                    )
                )

    return reconvergence_instances

    return reconvergence_instances


# ---------------------------------------------------------------------------
# 3. Time-Respecting Cycles Detector (round_tripping)
# ---------------------------------------------------------------------------
def detect_cycles(
    window: SlidingWindow,
) -> Tuple[List[PatternInstance], bool]:
    """
    Time-respecting DFS for cycles of length 3-6 with cycle retention >= 0.5.
    Pruned to strongly connected components (size 3-50) with edge aggregate >= cycle_min_edge_amount,
    requiring path time span <= 24h and nodes with both inflow and outflow.
    """
    import networkx as nx

    min_len = DETECTOR_PARAMS["cycle_min_len"]
    max_len = DETECTOR_PARAMS["cycle_max_len"]
    min_ret = DETECTOR_PARAMS["cycle_min_retention"]
    max_expansions = DETECTOR_PARAMS["cycle_max_edge_expansions"]
    min_edge_amt = DETECTOR_PARAMS.get("cycle_min_edge_amount", 5000.0)
    max_path_span_sec = DETECTOR_PARAMS.get("cycle_max_path_span_hours", 24.0) * 3600.0

    # 1. Build filtered DiGraph with edges having total amount >= cycle_min_edge_amount
    G = nx.DiGraph()
    for (u, v), e_data in window.edges.items():
        if e_data.total >= min_edge_amt:
            G.add_edge(u, v)

    # 2. Restrict to SCCs of size 3 to 50
    valid_sccs = [scc for scc in nx.strongly_connected_components(G) if 3 <= len(scc) <= 50]

    seen_canonical_cycles = set()
    cycle_instances: List[PatternInstance] = []
    expansions = 0
    cap_hit = False

    for scc in valid_sccs:
        if expansions >= max_expansions:
            cap_hit = True
            break

        # Start only from nodes with both inflow and outflow in SCC and in window
        start_candidates = [
            n for n in sorted(scc)
            if G.in_degree(n) >= 1 and G.out_degree(n) >= 1
            and window.node_in_total.get(n, 0.0) >= min_edge_amt
            and window.node_out_total.get(n, 0.0) >= min_edge_amt
        ]

        for start_node in start_candidates:
            if expansions >= max_expansions:
                cap_hit = True
                break

            # DFS stack: (current_node, path_nodes, path_txs, last_ts, first_ts, first_amt)
            stack = [(start_node, [start_node], [], None, None, None)]

            while stack:
                curr, path, p_txs, last_ts, first_ts, first_amt = stack.pop()
                expansions += 1
                if expansions >= max_expansions:
                    cap_hit = True
                    break

                out_edges = window.out_edges(curr)
                for next_node, e_data in out_edges:
                    # Edge must be inside SCC and survive edge amount filter
                    if next_node not in scc or e_data["total"] < min_edge_amt:
                        continue

                    # Check for cycle completion
                    if next_node == start_node and len(path) >= min_len:
                        for t in e_data["tx_list"]:
                            if t.amount < min_edge_amt and e_data["total"] < min_edge_amt:
                                continue
                            if last_ts is None or t.ts >= last_ts:
                                cur_first = first_ts if first_ts is not None else t.ts
                                if (t.ts - cur_first).total_seconds() > max_path_span_sec:
                                    continue

                                final_txs = p_txs + [t]
                                returned_amt = t.amount
                                init_amt = first_amt if first_amt is not None else final_txs[0].amount
                                retention = (returned_amt / init_amt) if init_amt > 0 else 0.0

                                if retention >= min_ret:
                                    cycle_tuple = tuple(path)
                                    min_rot = min(cycle_tuple[i:] + cycle_tuple[:i] for i in range(len(cycle_tuple)))
                                    if min_rot not in seen_canonical_cycles:
                                        seen_canonical_cycles.add(min_rot)
                                        final_txs.sort(key=lambda x: x.ts)
                                        cycle_instances.append(
                                            PatternInstance(
                                                pattern_type="round_tripping",
                                                accounts=set(path),
                                                core_accounts=set(path),
                                                tx_ids={x.tx_id for x in final_txs},
                                                start_ts=final_txs[0].ts,
                                                end_ts=final_txs[-1].ts,
                                                total_amount=round(sum(x.amount for x in final_txs), 2),
                                                meta={
                                                    "cycle_length": len(path),
                                                    "retention": round(retention, 4),
                                                    "cycle_path": list(min_rot),
                                                },
                                            )
                                        )
                                        break
                        continue

                    # Continue DFS if length allows
                    if len(path) < max_len and next_node not in path:
                        for t in e_data["tx_list"]:
                            if t.amount < min_edge_amt and e_data["total"] < min_edge_amt:
                                continue
                            if last_ts is None or t.ts >= last_ts:
                                cur_first = first_ts if first_ts is not None else t.ts
                                if (t.ts - cur_first).total_seconds() <= max_path_span_sec:
                                    stack.append((
                                        next_node,
                                        path + [next_node],
                                        p_txs + [t],
                                        t.ts,
                                        cur_first,
                                        first_amt if first_amt is not None else t.amount,
                                    ))
                                    break  # Expand earliest valid edge tx

    return cycle_instances, cap_hit


# ---------------------------------------------------------------------------
# 4. Mule Chain Detector (mule_chain)
# ---------------------------------------------------------------------------
def detect_mule_chains(
    window: SlidingWindow,
) -> List[PatternInstance]:
    """
    Detects chains of >= 3 consecutive mule-like nodes (pass_through >= 0.75, median_hold < 12h)
    connected by time-ordered edges.
    """
    min_pt = DETECTOR_PARAMS["mule_min_pass_through"]
    max_pt = DETECTOR_PARAMS.get("mule_max_pass_through", 1.35)
    max_hold_sec = DETECTOR_PARAMS["mule_max_hold_hours"] * 3600.0
    min_len = DETECTOR_PARAMS["chain_min_length"]
    min_flow = DETECTOR_PARAMS.get("candidate_min_flow", 15_000.0)
    hub_cutoff = DETECTOR_PARAMS.get("hub_max_counterparties", 18)

    active_nodes = window.active_nodes()
    hubs = {
        u for u in active_nodes
        if len(window.out_adj.get(u, set()) | window.in_adj.get(u, set())) >= hub_cutoff
    }

    mule_like_nodes = set()
    node_stats_cache = {}

    for n in active_nodes:
        if n in hubs or window.node_in_total.get(n, 0.0) < min_flow or window.node_out_total.get(n, 0.0) < min_flow:
            continue
        stats = window.node_stats(n)
        node_stats_cache[n] = stats
        if min_pt <= stats["pass_through"] <= max_pt and stats["median_hold"] is not None and stats["median_hold"] < max_hold_sec:
            mule_like_nodes.add(n)

    chain_instances: List[PatternInstance] = []
    seen_chains = set()
    chain_tx_map = {}
    expansions = 0
    max_chain_expansions = 2000

    for start_node in mule_like_nodes:
        if expansions >= max_chain_expansions:
            break
        stack = [(start_node, [start_node], [], None)]

        while stack:
            curr, path, p_txs, last_ts = stack.pop()
            expansions += 1
            if expansions >= max_chain_expansions:
                break

            if len(path) >= min_len:
                chain_tuple = tuple(path)
                seen_chains.add(chain_tuple)
                chain_tx_map[chain_tuple] = p_txs

            if len(path) < 6 and expansions < max_chain_expansions:
                for next_node, e_data in window.out_edges(curr):
                    if next_node in mule_like_nodes and next_node not in path and e_data["total"] >= min_flow:
                        t_valid = next((t for t in e_data["tx_list"] if (last_ts is None or t.ts >= last_ts) and t.amount >= min_flow), None)
                        if t_valid:
                            stack.append((
                                next_node,
                                path + [next_node],
                                p_txs + [t_valid],
                                t_valid.ts,
                            ))

    # Keep only maximal chains
    sorted_chains = sorted(seen_chains, key=lambda c: len(c), reverse=True)
    maximal_chains = []
    for c in sorted_chains:
        if not any(set(c).issubset(set(p)) for p in maximal_chains):
            maximal_chains.append(c)

    for path_tuple in maximal_chains:
        path = list(path_tuple)
        p_txs_sorted = sorted(chain_tx_map[path_tuple], key=lambda t: t.ts)
        chain_instances.append(
            PatternInstance(
                pattern_type="mule_chain",
                accounts=set(path),
                core_accounts=set(path),
                tx_ids={t.tx_id for t in p_txs_sorted},
                start_ts=p_txs_sorted[0].ts,
                end_ts=p_txs_sorted[-1].ts,
                total_amount=round(sum(t.amount for t in p_txs_sorted), 2),
                meta={
                    "chain_length": len(path),
                    "chain_path": path,
                    "mean_pass_through": round(float(np.mean([node_stats_cache[n]["pass_through"] for n in path])), 4),
                },
            )
        )

    return chain_instances


# ---------------------------------------------------------------------------
# Main Detection Entry Point
# ---------------------------------------------------------------------------
def detect(
    window: SlidingWindow,
    now: datetime,
) -> List[PatternInstance]:
    """
    Main detection entry point.
    Dispatches to fan-out, fan-in, reconvergence, cycles, and mule chains.
    Uses ONLY observable attributes (src, dst, amount, ts).
    """
    global cycle_cap_hit

    # 1. Fan-out and fan-in
    fan_outs, fan_ins = detect_fan_out_fan_in(window, now)

    # 2. Reconvergence
    reconvergence = detect_reconvergence(window, fan_outs)

    # 3. Cycles
    cycles, cap_hit = detect_cycles(window)
    cycle_cap_hit = cap_hit

    # 4. Mule chains
    chains = detect_mule_chains(window)

    all_instances = fan_outs + fan_ins + reconvergence + cycles + chains
    return all_instances
