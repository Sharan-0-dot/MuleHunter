"""
ClusterTracker: Assigns stable cluster IDs (C-0001, C-0002...) across detection ticks
by account-set Jaccard similarity >= 0.5.
Tracks first_seen, last_seen, best risk so far, features, and the peak account set.
Turns repeated window snapshot detections of the same network into a single tracked entity.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set
from app.detect.clusters import Cluster


@dataclass
class TrackedCluster:
    cluster_id: str
    first_seen: datetime
    last_seen: datetime
    best_risk: float
    peak_accounts: Set[str]
    current_accounts: Set[str]
    typology: str
    pattern_types: Set[str]
    total_amount: float
    start_ts: datetime
    end_ts: datetime
    features: dict = field(default_factory=dict)
    pattern_instances: List = field(default_factory=list)
    peak_cluster: Optional[Cluster] = None
    tick_count: int = 1

    @property
    def accounts(self) -> Set[str]:
        return self.peak_accounts


class ClusterTracker:
    """
    Maintains continuity of detected clusters across temporal window ticks.
    """

    def __init__(self, jaccard_threshold: float = 0.5):
        self.jaccard_threshold = jaccard_threshold
        self.tracks: Dict[str, TrackedCluster] = {}
        self.next_id: int = 1

    def update(self, clusters: List[Cluster], current_ts: datetime, risk_fn=None) -> List[TrackedCluster]:
        """
        Match incoming clusters to existing tracks by account-set Jaccard similarity >= threshold.
        Updates matched tracks and registers new tracks with stable C-xxxx IDs.
        Returns the list of active tracked clusters for this tick.
        """
        active_this_tick: List[TrackedCluster] = []
        unmatched_clusters = list(clusters)

        # Match greedily by highest Jaccard similarity
        while unmatched_clusters:
            best_match: Optional[TrackedCluster] = None
            best_sim = 0.0
            best_c_idx = -1

            for c_idx, c in enumerate(unmatched_clusters):
                for cid, trk in self.tracks.items():
                    union_sz = len(c.accounts | trk.current_accounts)
                    if union_sz == 0:
                        continue
                    sim = len(c.accounts & trk.current_accounts) / union_sz
                    if sim > best_sim and sim >= self.jaccard_threshold:
                        best_sim = sim
                        best_match = trk
                        best_c_idx = c_idx

            if best_match is not None and best_c_idx >= 0:
                c = unmatched_clusters.pop(best_c_idx)
                best_match.last_seen = current_ts
                best_match.current_accounts = set(c.accounts)
                if len(c.accounts) >= len(best_match.peak_accounts):
                    best_match.peak_accounts = set(c.accounts)
                    best_match.peak_cluster = c
                    best_match.features = dict(c.features)
                    best_match.pattern_instances = list(c.pattern_instances)

                risk = risk_fn(c.features) if risk_fn else c.features.get("risk_score", 0.0)
                best_match.best_risk = max(best_match.best_risk, risk)
                best_match.typology = c.typology
                best_match.total_amount = max(best_match.total_amount, c.total_amount)
                best_match.start_ts = min(best_match.start_ts, c.start_ts)
                best_match.end_ts = max(best_match.end_ts, c.end_ts)
                best_match.pattern_types.update(p.pattern_type for p in c.pattern_instances)
                best_match.tick_count += 1
                active_this_tick.append(best_match)
            else:
                break

        # Remaining unmatched clusters become new tracks with stable C-xxxx IDs
        for c in unmatched_clusters:
            cid = f"C-{self.next_id:04d}"
            self.next_id += 1
            risk = risk_fn(c.features) if risk_fn else c.features.get("risk_score", 0.0)
            trk = TrackedCluster(
                cluster_id=cid,
                first_seen=current_ts,
                last_seen=current_ts,
                best_risk=risk,
                peak_accounts=set(c.accounts),
                current_accounts=set(c.accounts),
                typology=c.typology,
                pattern_types={p.pattern_type for p in c.pattern_instances},
                total_amount=c.total_amount,
                start_ts=c.start_ts,
                end_ts=c.end_ts,
                features=dict(c.features),
                pattern_instances=list(c.pattern_instances),
                peak_cluster=c,
                tick_count=1,
            )
            self.tracks[cid] = trk
            active_this_tick.append(trk)

        return active_this_tick

    def all_tracks(self) -> List[TrackedCluster]:
        return list(self.tracks.values())
