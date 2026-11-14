import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from datetime import datetime, timezone, timedelta
import numpy as np
from app.sim.generator import TransactionStream, generate_accounts_pool, generate_dataset
from app.detect.window import SlidingWindow
from app.detect.patterns import detect
from app.detect.clusters import build_clusters
from app.detect.tracker import ClusterTracker
from app.detect.model import predict_risk, risk_level
from app.config import ALERT_MIN

def run_simulation(
    seed=50,
    sim_hours=48.0,
    warmup_hours=48.0,
    tick_minutes=15,
    use_overlap=True,
    confirm_ticks=2,
    retain_ticks=4,
):
    accounts = generate_accounts_pool()
    accounts_dict = {a.account_id: a for a in accounts}
    base_time = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)
    
    # Warmup
    window = SlidingWindow(window_hours=48.0)
    warmup_txs, _ = generate_dataset(
        seed=seed,
        duration_hours=warmup_hours,
        attacks=None,
        start_ts=base_time,
    )
    for t in warmup_txs:
        window.add(t)
    sim_time = base_time + timedelta(hours=warmup_hours)
    window.advance(sim_time)
    
    # Stream
    stream = TransactionStream(seed=seed + 100, start_ts=sim_time)
    if use_overlap:
        tracker = ClusterTracker(overlap_threshold=0.5, max_disappeared_ticks=retain_ticks, confirm_ticks=confirm_ticks)
    else:
        # Legacy Jaccard without retention
        tracker = ClusterTracker(overlap_threshold=0.5, max_disappeared_ticks=0, confirm_ticks=confirm_ticks)
        tracker.overlap_threshold = 0.5  # will use jaccard if we test that
    
    dt_sec = tick_minutes * 60.0
    n_ticks = int((sim_hours * 3600.0) // dt_sec)
    
    alerts_fired = 0
    all_scores = []
    cluster_ids_seen = set()
    alerted_clusters = set()
    
    for tick in range(n_ticks):
        # 1. Advance stream
        txs = stream.advance(dt_sec)
        for t in txs:
            window.add(t)
        sim_time += timedelta(seconds=dt_sec)
        window.advance(sim_time)
        
        # 2. Detect
        instances = detect(window, sim_time)
        clusters = build_clusters(instances, window, accounts_dict)
        
        # 3. Track
        active = tracker.update(clusters, sim_time, risk_fn=predict_risk)
        for trk in active:
            cluster_ids_seen.add(trk.cluster_id)
            score = trk.last_risk
            all_scores.append(score)
            
            # Alert check
            if score >= ALERT_MIN:
                if trk.consecutive_alert_ticks >= confirm_ticks and trk.cluster_id not in alerted_clusters:
                    alerted_clusters.add(trk.cluster_id)
                    alerts_fired += 1
                    
    false_alerts_per_day = alerts_fired / (sim_hours / 24.0)
    new_cids_per_hour = len(cluster_ids_seen) / sim_hours
    
    return {
        "false_alerts": alerts_fired,
        "false_alerts_per_day": false_alerts_per_day,
        "new_cids_per_hour": new_cids_per_hour,
        "total_cids": len(cluster_ids_seen),
        "scores": all_scores,
    }

if __name__ == "__main__":
    print("Testing Seed 50 (48 sim-hours legit-only):")
    
    # Factor 1: Tick Cadence (15 min vs 60 min)
    res_15m = run_simulation(tick_minutes=15)
    print(f"1. Cadence 15m (default): {res_15m['false_alerts_per_day']:.2f} alerts/day | {res_15m['new_cids_per_hour']:.2f} new CIDs/hr")
    
    res_60m = run_simulation(tick_minutes=60)
    print(f"   Cadence 60m:           {res_60m['false_alerts_per_day']:.2f} alerts/day | {res_60m['new_cids_per_hour']:.2f} new CIDs/hr")
    
    # Factor 2: Warmup Length (24h vs 48h)
    res_24h_warm = run_simulation(warmup_hours=24.0)
    print(f"2. Warmup 24h:            {res_24h_warm['false_alerts_per_day']:.2f} alerts/day | {res_24h_warm['new_cids_per_hour']:.2f} new CIDs/hr")
    print(f"   Warmup 48h (default):  {res_15m['false_alerts_per_day']:.2f} alerts/day | {res_15m['new_cids_per_hour']:.2f} new CIDs/hr")
    
    # Factor 3: Confirmation ticks (1 vs 2)
    res_conf1 = run_simulation(confirm_ticks=1)
    print(f"3. Confirm ticks = 1:     {res_conf1['false_alerts_per_day']:.2f} alerts/day | {res_conf1['new_cids_per_hour']:.2f} new CIDs/hr")
    print(f"   Confirm ticks = 2:     {res_15m['false_alerts_per_day']:.2f} alerts/day | {res_15m['new_cids_per_hour']:.2f} new CIDs/hr")
    
    # Factor 4: Calibrator saturation analysis
    scores = np.array(res_15m['scores'])
    print("\nScore distribution on legit-only run (15m):")
    print(f"Count: {len(scores)}, Min: {scores.min():.4f}, Max: {scores.max():.4f}, Mean: {scores.mean():.4f}")
    print(f"Scores >= 0.40: {(scores >= 0.40).sum()} ({(scores >= 0.40).mean()*100:.2f}%)")
    deciles = np.percentile(scores, np.arange(0, 101, 10))
    print(f"Deciles (p0-p100): {[round(x, 4) for x in deciles]}")
