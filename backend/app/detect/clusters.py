"""
Cluster builder and feature extractor.

Groups PatternInstances using Union-Find with strict anti-giant-component rules:
- Merge two instances only if they share >= 2 accounts, OR share exactly 1 account
  that is a core account in BOTH.
Assigns cluster typology:
- smurfing_fan_out_fan_in, round_tripping, mule_chain, fan_out, fan_in, hybrid.
Extracts rich cluster-level features for XGBoost scoring in M3.
"""

from collections import defaultdict
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

from app.config import SIM_NAIVE_THRESHOLD
from app.detect.patterns import PatternInstance, _calc_cv
from app.detect.window import SlidingWindow


@dataclass
class Cluster:
    cluster_id: str
    accounts: Set[str]
    core_accounts: Set[str]
    tx_ids: Set[str]
    pattern_instances: List[PatternInstance]
    typology: str
    start_ts: datetime
    end_ts: datetime
    total_amount: float
    features: dict = field(default_factory=dict)


class DSU:
    """Disjoint Set Union with path compression and union by rank."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int):
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x != root_y:
            if self.rank[root_x] < self.rank[root_y]:
                self.parent[root_x] = root_y
            elif self.rank[root_x] > self.rank[root_y]:
                self.parent[root_y] = root_x
            else:
                self.parent[root_y] = root_x
                self.rank[root_x] += 1


def build_clusters(
    instances: List[PatternInstance],
    window: SlidingWindow,
    accounts_dict: Optional[dict] = None,
) -> List[Cluster]:
    """
    Build clusters from pattern instances using strict Union-Find:
    Merge only if sharing >= 2 accounts OR sharing 1 account that is core in both.
    Indexed by accounts for high performance.
    """
    if not instances:
        return []

    n = len(instances)
    dsu = DSU(n)

    from app.detect.patterns import DETECTOR_PARAMS
    hub_cutoff = DETECTOR_PARAMS.get("hub_max_counterparties", 18)
    hubs = {
        u for u in window.active_nodes()
        if len(window.out_adj.get(u, set()) | window.in_adj.get(u, set())) >= hub_cutoff
    }

    # Inverted index: non-hub account -> list of instance indices
    acc_to_insts = defaultdict(list)
    for i, inst in enumerate(instances):
        for acc in (inst.accounts - hubs):
            acc_to_insts[acc].append(i)

    # Check only pairs sharing at least one non-hub account
    pairs_to_check = set()
    for acc, idx_list in acc_to_insts.items():
        if len(idx_list) > 1:
            for a in range(len(idx_list)):
                for b in range(a + 1, min(len(idx_list), a + 50)):
                    i, j = idx_list[a], idx_list[b]
                    if i != j:
                        pairs_to_check.add((min(i, j), max(i, j)))

    for i, j in pairs_to_check:
        p1 = instances[i]
        p2 = instances[j]
        sh_core = (p1.core_accounts & p2.core_accounts) - hubs
        if len(sh_core) >= 1:
            dsu.union(i, j)

    # Group instances by root
    groups = defaultdict(list)
    for i in range(n):
        root = dsu.find(i)
        groups[root].append(instances[i])

    clusters: List[Cluster] = []
    c_idx = 1

    for root, p_list in groups.items():
        all_accounts = set()
        core_accounts = set()
        all_tx_ids = set()

        for p in p_list:
            all_accounts.update(p.accounts)
            core_accounts.update(p.core_accounts)
            all_tx_ids.update(p.tx_ids)

        start_ts = min(p.start_ts for p in p_list)
        end_ts = max(p.end_ts for p in p_list)

        # -------------------------------------------------------------------
        # Typology Assignment Precedence Rule:
        # - cycle AND reconvergence both present, and cycle shares >= 1 account
        #   with reconvergence core -> hybrid
        # - cycle present -> round_tripping
        # - reconvergence present -> smurfing_fan_out_fan_in
        #   (chain patterns inside reconvergence do NOT make it hybrid or mule_chain)
        # - chain present -> mule_chain
        # - fan_out only / fan_in only -> fan_out / fan_in
        # -------------------------------------------------------------------
        has_reconv = any(p.pattern_type == "smurfing_fan_out_fan_in" for p in p_list)
        has_cycle = any(p.pattern_type == "round_tripping" for p in p_list)
        has_chain = any(p.pattern_type == "mule_chain" for p in p_list)
        has_fo = any(p.pattern_type == "fan_out" for p in p_list)
        has_fi = any(p.pattern_type == "fan_in" for p in p_list)

        cycle_shares_reconv = False
        if has_cycle and has_reconv:
            cycle_accs = set().union(*(p.accounts for p in p_list if p.pattern_type == "round_tripping"))
            reconv_cores = set().union(*(p.core_accounts for p in p_list if p.pattern_type == "smurfing_fan_out_fan_in"))
            if bool(cycle_accs & reconv_cores):
                cycle_shares_reconv = True

        if cycle_shares_reconv:
            typology = "hybrid"
        elif has_cycle:
            typology = "round_tripping"
        elif has_reconv:
            typology = "smurfing_fan_out_fan_in"
        elif has_chain:
            typology = "mule_chain"
        elif has_fo and not has_fi:
            typology = "fan_out"
        elif has_fi and not has_fo:
            typology = "fan_in"
        else:
            typology = "fan_out" if has_fo else (p_list[0].pattern_type)

        total_amt = round(sum(p.total_amount for p in p_list), 2)

        cluster = Cluster(
            cluster_id=f"C-{c_idx:04d}",
            accounts=all_accounts,
            core_accounts=core_accounts,
            tx_ids=all_tx_ids,
            pattern_instances=p_list,
            typology=typology,
            start_ts=start_ts,
            end_ts=end_ts,
            total_amount=total_amt,
        )

        cluster.features = cluster_features(cluster, window, accounts_dict)
        clusters.append(cluster)
        c_idx += 1

    return clusters


def cluster_features(
    cluster: Cluster,
    window: SlidingWindow,
    accounts_dict: Optional[dict] = None,
) -> dict:
    """
    Extract cluster-level feature dictionary for XGBoost training and evaluation.
    Fast adjacency-bounded edge traversal.
    """
    V = cluster.accounts
    n_acc = len(V)
    span_sec = max(0.0, (cluster.end_ts - cluster.start_ts).total_seconds())

    # Density: directed density |E| / (|V| * (|V|-1))
    internal_edges = 0
    tx_amounts = []
    near_thresh_count = 0
    thresh_80 = 0.8 * SIM_NAIVE_THRESHOLD

    # Efficiently iterate only over edges internal to V
    for u in V:
        for v in window.out_adj.get(u, ()):
            if v in V:
                edge = window.edges.get((u, v))
                if edge:
                    internal_edges += 1
                    for t in edge.tx_list:
                        if t.tx_id in cluster.tx_ids:
                            tx_amounts.append(t.amount)
                            if thresh_80 <= t.amount <= SIM_NAIVE_THRESHOLD:
                                near_thresh_count += 1

    density = (internal_edges / (n_acc * (n_acc - 1))) if n_acc > 1 else 0.0

    # Node stats (pass-through, hold)
    pts = []
    holds = []
    for node in V:
        stats = window.node_stats(node)
        pts.append(stats["pass_through"])
        if stats["median_hold"] is not None:
            holds.append(stats["median_hold"])

    max_pt = float(max(pts)) if pts else 0.0
    mean_pt = float(np.mean(pts)) if pts else 0.0
    med_hold = float(np.median(holds)) if holds else 0.0

    amount_cv = _calc_cv(tx_amounts) if tx_amounts else 0.0
    ratio_near_thresh = (near_thresh_count / len(tx_amounts)) if tx_amounts else 0.0

    has_fo = int(any(p.pattern_type == "fan_out" for p in cluster.pattern_instances))
    has_fi = int(any(p.pattern_type == "fan_in" for p in cluster.pattern_instances))
    has_cyc = int(any(p.pattern_type == "round_tripping" for p in cluster.pattern_instances))
    has_chn = int(any(p.pattern_type == "mule_chain" for p in cluster.pattern_instances))
    has_rec = int(any(p.pattern_type == "smurfing_fan_out_fan_in" for p in cluster.pattern_instances))

    cycle_lens = [p.meta.get("cycle_length", 0) for p in cluster.pattern_instances if p.pattern_type == "round_tripping"]
    cycle_len = max(cycle_lens) if cycle_lens else 0

    retentions = [p.meta.get("retention", 0.0) for p in cluster.pattern_instances if p.pattern_type == "round_tripping"]
    retention = max(retentions) if retentions else 0.0

    # Merchant / Business share
    if accounts_dict:
        merch_biz_count = sum(1 for a in V if accounts_dict.get(a) and accounts_dict[a].account_type in ("merchant", "business"))
    else:
        merch_biz_count = 0
        for acc in V:
            try:
                num = int(acc.split("-")[1])
                if num > 1400:
                    merch_biz_count += 1
            except Exception:
                pass
    merch_biz_share = (merch_biz_count / n_acc) if n_acc > 0 else 0.0

    return {
        "n_accounts": n_acc,
        "total_amount": cluster.total_amount,
        "time_span": round(span_sec, 2),
        "density": round(density, 4),
        "max_pass_through": round(max_pt, 4),
        "mean_pass_through": round(mean_pt, 4),
        "median_hold": round(med_hold, 2),
        "amount_cv": round(amount_cv, 4),
        "has_fan_out": has_fo,
        "has_fan_in": has_fi,
        "has_cycle": has_cyc,
        "has_chain": has_chn,
        "has_reconvergence": has_rec,
        "cycle_length": cycle_len,
        "retention": round(retention, 4),
        "ratio_near_threshold": round(ratio_near_thresh, 4),
        "merchant_business_share": round(merch_biz_share, 4),
    }
