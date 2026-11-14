"""
Baseline AML rules and ablations for comparison against graph + XGBoost pipeline.

1. baseline_fixed: Flags transactions with amount >= SIM_NAIVE_THRESHOLD (default INR 50,000).
2. baseline_tuned: Threshold T tuned on training data (10k - 150k in 5k steps) to maximize F1.
3. rules_only: Ablation evaluating candidate generation without machine learning filtering.
"""

from pathlib import Path
import json
import sys
from typing import Dict, List, Optional, Set, Tuple

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import SIM_NAIVE_THRESHOLD
from app.sim.generator import Transaction

THRESHOLD_FILE = backend_dir / "models" / "baseline_threshold.json"


def baseline_fixed(transactions: List[Transaction]) -> Set[str]:
    """
    Naive baseline: any transaction >= SIM_NAIVE_THRESHOLD is flagged;
    returns all account IDs involved in flagged transactions.
    """
    flagged_accounts = set()
    for tx in transactions:
        if tx.amount >= SIM_NAIVE_THRESHOLD:
            flagged_accounts.add(tx.src)
            flagged_accounts.add(tx.dst)
    return flagged_accounts


def get_tuned_threshold() -> float:
    """
    Loads optimal threshold T tuned on training data, or falls back to SIM_NAIVE_THRESHOLD.
    """
    if THRESHOLD_FILE.exists():
        try:
            with open(THRESHOLD_FILE, "r") as f:
                data = json.load(f)
                return float(data.get("tuned_threshold", SIM_NAIVE_THRESHOLD))
        except Exception:
            pass
    return float(SIM_NAIVE_THRESHOLD)


def baseline_tuned(transactions: List[Transaction], threshold: Optional[float] = None) -> Set[str]:
    """
    Tuned baseline: any transaction >= threshold is flagged.
    """
    if threshold is None:
        threshold = get_tuned_threshold()

    flagged_accounts = set()
    for tx in transactions:
        if tx.amount >= threshold:
            flagged_accounts.add(tx.src)
            flagged_accounts.add(tx.dst)
    return flagged_accounts


def rules_only(clusters: list) -> Set[str]:
    """
    Rules-only ablation: flags all accounts present in any detected cluster
    without XGBoost probability filtering.
    """
    flagged = set()
    for c in clusters:
        flagged.update(c.accounts)
    return flagged


def tune_threshold_on_runs(
    runs_data: List[Tuple[List[Transaction], Set[str]]],
    min_t: float = 10_000.0,
    max_t: float = 150_000.0,
    step_t: float = 5_000.0,
) -> float:
    """
    Grid search for threshold T in [min_t, max_t] with step step_t
    to maximize mean account-level F1 on training runs.
    Saves best threshold to backend/models/baseline_threshold.json.
    """
    best_t = SIM_NAIVE_THRESHOLD
    best_f1 = -1.0
    best_precision = 0.0
    best_recall = 0.0

    thresholds = [min_t + i * step_t for i in range(int((max_t - min_t) / step_t) + 1)]

    for t in thresholds:
        f1_scores = []
        for txs, ground_truth_accounts in runs_data:
            if not ground_truth_accounts:
                continue
            pred_accs = set()
            for tx in txs:
                if tx.amount >= t:
                    pred_accs.add(tx.src)
                    pred_accs.add(tx.dst)

            tp = len(pred_accs & ground_truth_accounts)
            prec = tp / len(pred_accs) if pred_accs else 0.0
            rec = tp / len(ground_truth_accounts) if ground_truth_accounts else 0.0
            f1 = (2.0 * prec * rec) / (prec + rec) if (prec + rec) > 0.0 else 0.0
            f1_scores.append(f1)

        mean_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0
        if mean_f1 > best_f1:
            best_f1 = mean_f1
            best_t = t

    THRESHOLD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(THRESHOLD_FILE, "w") as f:
        json.dump(
            {
                "tuned_threshold": best_t,
                "mean_train_f1": round(best_f1, 4),
            },
            f,
            indent=2,
        )

    print(f"Optimal baseline threshold T = INR {best_t:,.2f} (Train F1 = {best_f1:.4f})")
    return best_t
