import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.engine import engine
from app.db import list_clusters, get_cluster_detail

print("=== TESTING STEP 2 SIZING ON ROUND_TRIP DIFF 2 ===")
for label, amt in [("3 lakh", 300_000), ("10 lakh", 1_000_000), ("25 lakh", 2_500_000)]:
    res = engine.run_headless(
        sim_hours=10.0,
        attacks=[{"type": "round_trip", "difficulty": 2, "offset_hours": 1.0, "total_amount_inr": amt}],
        reset_first=True,
        seed=50,
    )
    clusters = list_clusters()
    if clusters:
        c = clusters[0]
        c_detail = get_cluster_detail(c["cluster_id"])
        print(f"{label} ({amt:,} INR): Cluster {c['cluster_id']}, total_amount={c_detail['features'].get('total_amount', 0):,.0f}, risk_score={c['risk_score']:.4f}, level={c['level'].upper()}, risk_components={c_detail.get('risk_components')}")
    else:
        print(f"{label}: MISSED")
