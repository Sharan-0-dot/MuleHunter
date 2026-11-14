"""
Sliding-window temporal graph accumulator for streaming transaction analysis.

Maintains:
- Exact per-(u, v) edge aggregates (total, count, first_ts, last_ts, tx list).
- Per-node inflow and outflow lists (ts, amount, counterparty, tx_id).
- Exact eviction: aggregates drop to zero and empty edges are removed immediately.
- Fast adjacency queries: out_edges(u), in_edges(v).
- Node statistics: in_amount, out_amount, pass_through, median_hold, distinct counterparties.
"""

from bisect import bisect_left
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path
import sys

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import numpy as np

from app.sim.generator import Transaction


@dataclass
class EdgeAggregate:
    src: str
    dst: str
    total: float
    count: int
    first_ts: datetime
    last_ts: datetime
    tx_list: List[Transaction]


class SlidingWindow:
    """
    Sliding window temporal graph maintaining exact edge and node state over window_hours.
    """

    def __init__(self, window_hours: float = 48.0):
        self.window_hours = float(window_hours)
        self.window_delta = timedelta(hours=self.window_hours)
        self.current_time: Optional[datetime] = None

        # Queue of active transactions in window in insertion/timestamp order
        self.tx_queue: deque[Transaction] = deque()

        # (u, v) -> EdgeAggregate
        self.edges: Dict[Tuple[str, str], EdgeAggregate] = {}

        # Adjacency sets
        self.out_adj: Dict[str, Set[str]] = defaultdict(set)
        self.in_adj: Dict[str, Set[str]] = defaultdict(set)

        # Node transaction records: (ts, amount, counterparty, tx_id)
        self.inflows: Dict[str, List[Tuple[datetime, float, str, str]]] = defaultdict(list)
        self.outflows: Dict[str, List[Tuple[datetime, float, str, str]]] = defaultdict(list)

        # Node totals
        self.node_in_total: Dict[str, float] = defaultdict(float)
        self.node_out_total: Dict[str, float] = defaultdict(float)

    def add(self, tx: Transaction):
        """Add a transaction to the window and evict expired transactions."""
        if self.current_time is None or tx.ts > self.current_time:
            self.current_time = tx.ts

        self.tx_queue.append(tx)

        # Update edge (u, v)
        key = (tx.src, tx.dst)
        if key not in self.edges:
            self.edges[key] = EdgeAggregate(
                src=tx.src,
                dst=tx.dst,
                total=round(tx.amount, 2),
                count=1,
                first_ts=tx.ts,
                last_ts=tx.ts,
                tx_list=[tx],
            )
            self.out_adj[tx.src].add(tx.dst)
            self.in_adj[tx.dst].add(tx.src)
        else:
            edge = self.edges[key]
            edge.total = round(edge.total + tx.amount, 2)
            edge.count += 1
            if tx.ts < edge.first_ts:
                edge.first_ts = tx.ts
            if tx.ts > edge.last_ts:
                edge.last_ts = tx.ts
            edge.tx_list.append(tx)

        # Update node inflows and outflows
        self.inflows[tx.dst].append((tx.ts, tx.amount, tx.src, tx.tx_id))
        self.outflows[tx.src].append((tx.ts, tx.amount, tx.dst, tx.tx_id))
        self.node_in_total[tx.dst] = round(self.node_in_total[tx.dst] + tx.amount, 2)
        self.node_out_total[tx.src] = round(self.node_out_total[tx.src] + tx.amount, 2)

        # Evict transactions that fell out of window
        cutoff = self.current_time - self.window_delta
        self._evict(cutoff)

    def advance(self, now: datetime):
        """Advance current time without adding a transaction, evicting expired items."""
        if self.current_time is None or now > self.current_time:
            self.current_time = now
        cutoff = self.current_time - self.window_delta
        self._evict(cutoff)

    def _evict(self, cutoff: datetime):
        """Evict transactions with timestamp strictly earlier than cutoff."""
        while self.tx_queue and self.tx_queue[0].ts < cutoff:
            old_tx = self.tx_queue.popleft()
            key = (old_tx.src, old_tx.dst)

            # 1. Update edge
            edge = self.edges.get(key)
            if edge:
                edge.count -= 1
                edge.total = round(edge.total - old_tx.amount, 2)
                # Remove from tx_list (it is at the front since transactions are ordered)
                if edge.tx_list and edge.tx_list[0].tx_id == old_tx.tx_id:
                    edge.tx_list.pop(0)
                else:
                    edge.tx_list = [t for t in edge.tx_list if t.tx_id != old_tx.tx_id]

                if edge.count <= 0 or not edge.tx_list:
                    del self.edges[key]
                    self.out_adj[old_tx.src].discard(old_tx.dst)
                    if not self.out_adj[old_tx.src]:
                        del self.out_adj[old_tx.src]

                    self.in_adj[old_tx.dst].discard(old_tx.src)
                    if not self.in_adj[old_tx.dst]:
                        del self.in_adj[old_tx.dst]
                else:
                    edge.first_ts = edge.tx_list[0].ts
                    edge.last_ts = edge.tx_list[-1].ts

            # 2. Update node inflow
            dst_in = self.inflows.get(old_tx.dst)
            if dst_in:
                if dst_in[0][3] == old_tx.tx_id:
                    dst_in.pop(0)
                else:
                    self.inflows[old_tx.dst] = [r for r in dst_in if r[3] != old_tx.tx_id]
                self.node_in_total[old_tx.dst] = round(max(0.0, self.node_in_total[old_tx.dst] - old_tx.amount), 2)
                if not self.inflows[old_tx.dst]:
                    del self.inflows[old_tx.dst]
                    if old_tx.dst in self.node_in_total:
                        del self.node_in_total[old_tx.dst]

            # 3. Update node outflow
            src_out = self.outflows.get(old_tx.src)
            if src_out:
                if src_out[0][3] == old_tx.tx_id:
                    src_out.pop(0)
                else:
                    self.outflows[old_tx.src] = [r for r in src_out if r[3] != old_tx.tx_id]
                self.node_out_total[old_tx.src] = round(max(0.0, self.node_out_total[old_tx.src] - old_tx.amount), 2)
                if not self.outflows[old_tx.src]:
                    del self.outflows[old_tx.src]
                    if old_tx.src in self.node_out_total:
                        del self.node_out_total[old_tx.src]

    def out_edges(self, u: str) -> List[Tuple[str, dict]]:
        """Return list of (v, edge_dict) for outgoing edges from u."""
        res = []
        for v in sorted(self.out_adj.get(u, set())):
            edge = self.edges.get((u, v))
            if edge:
                res.append((v, {
                    "total": edge.total,
                    "count": edge.count,
                    "first_ts": edge.first_ts,
                    "last_ts": edge.last_ts,
                    "tx_list": edge.tx_list,
                }))
        return res

    def in_edges(self, v: str) -> List[Tuple[str, dict]]:
        """Return list of (u, edge_dict) for incoming edges into v."""
        res = []
        for u in sorted(self.in_adj.get(v, set())):
            edge = self.edges.get((u, v))
            if edge:
                res.append((u, {
                    "total": edge.total,
                    "count": edge.count,
                    "first_ts": edge.first_ts,
                    "last_ts": edge.last_ts,
                    "tx_list": edge.tx_list,
                }))
        return res

    def node_stats(self, n: str) -> dict:
        """
        Return summary statistics for node n:
        - in_amount, out_amount, pass_through (out/in)
        - median_hold: median time (in seconds) between an inflow and the next outflow
        - distinct in and out counterparties
        """
        in_amt = round(self.node_in_total.get(n, 0.0), 2)
        out_amt = round(self.node_out_total.get(n, 0.0), 2)
        pass_through = round(out_amt / in_amt, 4) if in_amt > 0.0 else 0.0

        in_recs = self.inflows.get(n, [])
        out_recs = self.outflows.get(n, [])

        distinct_in = set(r[2] for r in in_recs)
        distinct_out = set(r[2] for r in out_recs)

        # Median hold calculation:
        # For each inflow, find earliest outflow occurring at or after inflow timestamp
        median_hold = None
        if in_recs and out_recs:
            out_times = [r[0] for r in out_recs]
            holds = []
            for r in in_recs:
                t_in = r[0]
                idx = bisect_left(out_times, t_in)
                if idx < len(out_times):
                    hold_sec = (out_times[idx] - t_in).total_seconds()
                    holds.append(hold_sec)
            if holds:
                median_hold = float(np.median(holds))

        return {
            "in_amount": in_amt,
            "out_amount": out_amt,
            "pass_through": pass_through,
            "median_hold": median_hold,
            "distinct_in": distinct_in,
            "distinct_out": distinct_out,
            "in_degree": len(distinct_in),
            "out_degree": len(distinct_out),
        }

    def active_nodes(self) -> Set[str]:
        """Return all nodes with at least one active edge in the window."""
        nodes = set(self.out_adj.keys()) | set(self.in_adj.keys())
        return nodes


# ---------------------------------------------------------------------------
# Unit Test: Exact Oracle Comparison
# ---------------------------------------------------------------------------
def test_sliding_window_oracle():
    """
    Unit test comparing SlidingWindow state against from-scratch recomputation
    after every transaction addition and time advancement.
    """
    rng = np.random.default_rng(12345)
    accounts = [f"ACC-{i:04d}" for i in range(1, 21)]
    start_time = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)

    window_hours = 12.0
    window = SlidingWindow(window_hours=window_hours)
    all_txs: List[Transaction] = []

    curr_ts = start_time
    for i in range(1, 201):
        # Step forward 5 to 30 minutes
        delta_sec = float(rng.uniform(300, 1800))
        curr_ts += timedelta(seconds=delta_sec)
        src, dst = rng.choice(accounts, size=2, replace=False).tolist()
        amt = float(np.round(rng.uniform(100.0, 50000.0), 2))
        tx = Transaction(
            tx_id=f"TX-{i:08d}",
            ts=curr_ts,
            src=src,
            dst=dst,
            amount=amt,
            kind="p2p",
        )
        all_txs.append(tx)
        window.add(tx)

        # Oracle comparison at this step
        cutoff = curr_ts - timedelta(hours=window_hours)
        expected_txs = [t for t in all_txs if cutoff <= t.ts <= curr_ts]

        # 1. Compare total active transactions
        assert len(window.tx_queue) == len(expected_txs), f"Queue len mismatch: {len(window.tx_queue)} vs {len(expected_txs)}"

        # 2. Compare edge aggregates
        expected_edges = defaultdict(list)
        for t in expected_txs:
            expected_edges[(t.src, t.dst)].append(t)

        assert len(window.edges) == len(expected_edges), f"Edge count mismatch: {len(window.edges)} vs {len(expected_edges)}"

        for key, exp_list in expected_edges.items():
            edge = window.edges.get(key)
            assert edge is not None, f"Missing edge {key}"
            assert edge.count == len(exp_list)
            assert abs(edge.total - round(sum(t.amount for t in exp_list), 2)) < 0.01
            assert edge.first_ts == exp_list[0].ts
            assert edge.last_ts == exp_list[-1].ts

        # 3. Compare node stats for all active nodes
        for node in set(accounts):
            stats = window.node_stats(node)
            exp_in = sum(t.amount for t in expected_txs if t.dst == node)
            exp_out = sum(t.amount for t in expected_txs if t.src == node)
            assert abs(stats["in_amount"] - round(exp_in, 2)) < 0.01, f"In amount mismatch for {node}"
            assert abs(stats["out_amount"] - round(exp_out, 2)) < 0.01, f"Out amount mismatch for {node}"

    # Advance time far into the future: everything must evict completely
    future_time = curr_ts + timedelta(hours=window_hours + 1.0)
    window.advance(future_time)
    assert len(window.tx_queue) == 0, "Window queue not empty after full advance"
    assert len(window.edges) == 0, "Edges not empty after full advance"
    assert len(window.out_adj) == 0, "Out adj not empty after full advance"
    assert len(window.in_adj) == 0, "In adj not empty after full advance"
    assert len(window.inflows) == 0, "Inflows not empty after full advance"
    assert len(window.outflows) == 0, "Outflows not empty after full advance"
    return True


if __name__ == "__main__":
    passed = test_sliding_window_oracle()
    print("SlidingWindow Oracle Unit Test: PASS!" if passed else "SlidingWindow Oracle Unit Test: FAIL!")
