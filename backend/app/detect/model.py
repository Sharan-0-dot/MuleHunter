"""
XGBoost risk scoring model with Isotonic Probability Calibration.

Outputs a calibrated risk score in [0.0, 1.0] and maps to urgency bands:
  green:  risk < 0.40
  yellow: 0.40 <= risk < 0.70
  red:    risk >= 0.70
"""

from pathlib import Path
import sys
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import joblib
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import ALERT_MIN, GREEN_MAX, YELLOW_MAX

MODEL_PATH = backend_dir / "models" / "model.json"
CALIBRATOR_PATH = backend_dir / "models" / "calibrator.joblib"

# Exact list of cluster features used by the model
FEATURE_NAMES = [
    "n_accounts",
    "total_amount",
    "time_span",
    "density",
    "max_pass_through",
    "mean_pass_through",
    "median_hold",
    "amount_cv",
    "has_fan_out",
    "has_fan_in",
    "has_cycle",
    "has_chain",
    "has_reconvergence",
    "cycle_length",
    "retention",
    "ratio_near_threshold",
    "merchant_business_share",
]

# Cached model and calibrator instances for fast inference
_CACHED_MODEL: Optional[xgb.XGBClassifier] = None
_CACHED_CALIBRATOR: Optional[IsotonicRegression] = None


def get_model() -> Optional[xgb.XGBClassifier]:
    """Loads and caches XGBoost model from backend/models/model.json."""
    global _CACHED_MODEL
    if _CACHED_MODEL is not None:
        return _CACHED_MODEL

    if MODEL_PATH.exists():
        clf = xgb.XGBClassifier()
        clf.load_model(str(MODEL_PATH))
        _CACHED_MODEL = clf
        return _CACHED_MODEL
    return None


def get_calibrator() -> Optional[IsotonicRegression]:
    """Loads and caches IsotonicRegression calibrator from backend/models/calibrator.joblib."""
    global _CACHED_CALIBRATOR
    if _CACHED_CALIBRATOR is not None:
        return _CACHED_CALIBRATOR

    if CALIBRATOR_PATH.exists():
        _CACHED_CALIBRATOR = joblib.load(str(CALIBRATOR_PATH))
        return _CACHED_CALIBRATOR
    return None


def predict_risk(cluster_features: dict) -> float:
    """
    Predicts calibrated risk_score in [0.0, 1.0] from cluster features.
    If model/calibrator is not found on disk, falls back to a heuristic risk score.
    """
    model = get_model()
    calibrator = get_calibrator()

    if model is None:
        # Fallback heuristic: high retention cycle or reconvergence => high risk
        score = 0.2
        if cluster_features.get("has_reconvergence") or cluster_features.get("has_cycle"):
            score = 0.8
        elif cluster_features.get("has_chain"):
            score = 0.6
        return float(np.clip(score, 0.0, 1.0))

    # Form feature array strictly respecting FEATURE_NAMES order
    row = [float(cluster_features.get(f, 0.0)) for f in FEATURE_NAMES]
    X = np.array([row])

    # Raw predicted probability
    raw_prob = float(model.predict_proba(X)[0, 1])

    # Calibrate probability if calibrator exists
    if calibrator is not None:
        cal_prob = float(calibrator.predict([raw_prob])[0])
        return float(np.clip(cal_prob, 0.0, 1.0))

    return float(np.clip(raw_prob, 0.0, 1.0))


def risk_level(risk_score: float) -> str:
    """
    Maps continuous risk_score in [0.0, 1.0] to master 8.1 risk band:
      none:   < ALERT_MIN (0.40) -> no alert
      green:  ALERT_MIN <= risk < GREEN_MAX (0.40 - 0.65)
      yellow: GREEN_MAX <= risk < YELLOW_MAX (0.65 - 0.85)
      red:    >= YELLOW_MAX (>= 0.85)
    """
    if risk_score >= YELLOW_MAX:
        return "red"
    elif risk_score >= GREEN_MAX:
        return "yellow"
    elif risk_score >= ALERT_MIN:
        return "green"
    else:
        return "none"


def train_and_save_model(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    model_save_path: Path = MODEL_PATH,
    calibrator_save_path: Path = CALIBRATOR_PATH,
) -> Tuple[xgb.XGBClassifier, IsotonicRegression]:
    """
    Trains XGBoost on train_df, validates on val_df with early stopping,
    fits IsotonicRegression on validation probabilities, and persists artifacts.
    """
    X_train = train_df[FEATURE_NAMES].values
    y_train = train_df["label"].values.astype(int)

    X_val = val_df[FEATURE_NAMES].values
    y_val = val_df["label"].values.astype(int)

    # Class imbalance weight
    n_pos = sum(y_train == 1)
    n_neg = sum(y_train == 0)
    scale_pos = (n_neg / n_pos) if n_pos > 0 else 1.0

    model = xgb.XGBClassifier(
        max_depth=4,
        n_estimators=200,
        learning_rate=0.1,
        scale_pos_weight=min(scale_pos, 10.0),  # moderate boost
        eval_metric="logloss",
        early_stopping_rounds=15,
        random_state=42,
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    # Validation predictions for probability calibration
    val_raw_probs = model.predict_proba(X_val)[:, 1]

    # Isotonic Regression Calibrator (monotonically non-decreasing)
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(val_raw_probs, y_val)

    # Persist artifacts
    model_save_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_save_path))
    joblib.dump(calibrator, str(calibrator_save_path))

    # Reset cache
    global _CACHED_MODEL, _CACHED_CALIBRATOR
    _CACHED_MODEL = model
    _CACHED_CALIBRATOR = calibrator

    print(f"Trained XGBoost model saved to: {model_save_path}")
    print(f"Isotonic calibrator saved to: {calibrator_save_path}")

    return model, calibrator
