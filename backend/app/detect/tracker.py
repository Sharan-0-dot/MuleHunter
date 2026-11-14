"""
ClusterTracker: Assigns stable cluster IDs (C-0001, C-0002...) across detection ticks
by account-set overlap coefficient (|A and B| / min(|A|,|B|) >= 0.5).
Retains disappeared clusters for up to 4 ticks to prevent track fragmentation.
Tracks consecutive alert ticks (>= ALERT_MIN) for alert hygiene confirmation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set
from app.detect.clusters import Cluster
from app.config import ALERT_MIN


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
    # Alert hygiene & tracking continuity
    consecutive_alert_ticks: int = 0
    ticks_disappeared: int = 0
    alerted_level: Optional[str] = None
    last_risk: float = 0.0

    @property
    def accounts(self) -> Set[str]:
        return self.peak_accounts


class ClusterTracker:
    """
    Maintains continuity of detected clusters across temporal window ticks
    using overlap coefficient matching and disappeared-tick retention.
    """

    def __init__(
        self,
        overlap_threshold: float = 0.5,
        max_disappeared_ticks: int = 4,
        confirm_ticks: int = 2,
    ):
        self.overlap_threshold = overlap_threshold
        self.max_disappeared_ticks = max_disappeared_ticks
        self.confirm_ticks = confirm_ticks
        self.tracks: Dict[str, TrackedCluster] = {}
        self.retired_tracks: Dict[str, TrackedCluster] = {}
        self.next_id: int = 1

    def update(self, clusters: List[Cluster], current_ts: datetime, risk_fn=None) -> List[TrackedCluster]:
        """
        Match incoming clusters to existing tracks by account-set overlap coefficient >= threshold.
        Returns the list of active tracked clusters present in this tick.
        """
        active_this_tick: List[TrackedCluster] = []
        matched_track_ids: Set[str] = set()
        unmatched_clusters = list(clusters)

        # 1. Match greedily by highest Overlap Coefficient: |A & B| / min(|A|, |B|)
        while unmatched_clusters:
            best_match: Optional[TrackedCluster] = None
            best_sim = 0.0
            best_c_idx = -1

            for c_idx, c in enumerate(unmatched_clusters):
                for cid, trk in self.tracks.items():
                    if cid in matched_track_ids:
                        continue
                    # Compare against both current and peak accounts for robustness
                    acc_sets = [trk.current_accounts, trk.peak_accounts]
                    for ref_accs in acc_sets:
                        min_sz = min(len(c.accounts), len(ref_accs))
                        if min_sz == 0:
                            continue
                        overlap = len(c.accounts & ref_accs) / min_sz
                        if overlap > best_sim and overlap >= self.overlap_threshold:
                            best_sim = overlap
                            best_match = trk
                            best_c_idx = c_idx

            if best_match is not None and best_c_idx >= 0:
                c = unmatched_clusters.pop(best_c_idx)
                matched_track_ids.add(best_match.cluster_id)
                best_match.last_seen = current_ts
                best_match.ticks_disappeared = 0
                best_match.current_accounts = set(c.accounts)

                if len(c.accounts) >= len(best_match.peak_accounts):
                    best_match.peak_accounts = set(c.accounts)
                    best_match.peak_cluster = c
                    best_match.features = dict(c.features)
                    best_match.pattern_instances = list(c.pattern_instances)

                risk = risk_fn(c.features) if risk_fn else c.features.get("risk_score", 0.0)
                best_match.last_risk = risk
                best_match.best_risk = max(best_match.best_risk, risk)

                if risk >= ALERT_MIN:
                    best_match.consecutive_alert_ticks += 1
                else:
                    best_match.consecutive_alert_ticks = 0

                best_match.typology = c.typology
                best_match.total_amount = max(best_match.total_amount, c.total_amount)
                best_match.start_ts = min(best_match.start_ts, c.start_ts)
                best_match.end_ts = max(best_match.end_ts, c.end_ts)
                best_match.pattern_types.update(p.pattern_type for p in c.pattern_instances)
                best_match.tick_count += 1
                active_this_tick.append(best_match)
            else:
                break

        # 2. Update disappeared count for unmatched existing tracks
        to_retire = []
        for cid, trk in self.tracks.items():
            if cid not in matched_track_ids:
                trk.ticks_disappeared += 1
                trk.consecutive_alert_ticks = 0
                if trk.ticks_disappeared > self.max_disappeared_ticks:
                    to_retire.append(cid)

        for cid in to_retire:
            self.retired_tracks[cid] = self.tracks.pop(cid)

        # 3. Remaining unmatched incoming clusters become new tracks
        for c in unmatched_clusters:
            cid = f"C-{self.next_id:04d}"
            self.next_id += 1
            risk = risk_fn(c.features) if risk_fn else c.features.get("risk_score", 0.0)
            initial_alert_ticks = 1 if risk >= ALERT_MIN else 0
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
                consecutive_alert_ticks=initial_alert_ticks,
                ticks_disappeared=0,
                alerted_level=None,
                last_risk=risk,
            )
            self.tracks[cid] = trk
            active_this_tick.append(trk)

        return active_this_tick

    def all_tracks(self) -> List[TrackedCluster]:
        return list(self.tracks.values())

    def all_tracks(self) -> List[TrackedCluster]:
        return list(self.tracks.values())
