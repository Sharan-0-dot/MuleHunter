"""
Mule Hunter — M3 Model Training & Baseline Tuning Pipeline.

1. Generates training dataset from Seeds 1-10 (4 attack types x diff 1-3 = 120 runs + 10 legit = 130 runs, 96h each, 2h ticks).
2. Generates validation dataset from Seeds 50-54 (60 attack runs + 5 legit = 65 runs, 96h each, 2h ticks).
3. Subsamples negatives at <= 20:1 ratio.
4. Caches features to backend/data/train_features.parquet and val_features.parquet.
5. Tunes baseline threshold T on training runs (10k-150k in 5k steps) to maximize F1.
6. Trains XGBoost with early stopping on validation set, fits Isotonic Probability Calibrator, and persists artifacts.
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional, Set, Tuple
import numpy as np
import pandas as pd

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import WINDOW_HOURS, SIM_NAIVE_THRESHOLD
from app.sim.generator import generate_accounts_pool, generate_dataset
from app.sim.attacks import inject_attack
from app.detect.window import SlidingWindow
from app.detect.patterns import detect
from app.detect.clusters import build_clusters
from app.detect.model import FEATURE_NAMES, train_and_save_model
from app.detect.baseline import tune_threshold_on_runs

TRAIN_DATA_PATH = backend_dir / "data" / "train_features.parquet"
VAL_DATA_PATH = backend_dir / "data" / "val_features.parquet"


def _simulate_single_run(
    seed: int,
    attack_type: Optional[str],
    difficulty: int,
    duration_hours: float = 96.0,
    tick_hours: float = 2.0,
) -> Tuple[List[dict], Tuple[List, Set[str]]]:
    """
    Simulates a 96h run with 2h ticks, generating candidate cluster feature dictionaries
    and ground-truth labels (y=1 if >= 50% accounts belong to ground-truth ring, else 0).
    Also returns raw transactions and ground truth accounts for baseline threshold tuning.
    """
    base_ts = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)
    accounts = generate_accounts_pool()
    accounts_dict = {a.account_id: a for a in accounts}

    if attack_type is not None:
        rng = np.random.default_rng(seed=100 * seed + difficulty)
        atk_start = base_ts + timedelta(hours=24)
        ring_txs, gt = inject_attack(
            attack_type=attack_type,
            rng=rng,
            accounts=accounts,
            start_ts=atk_start,
            difficulty=difficulty,
            ring_id=f"RING-{seed}-{difficulty}",
        )
        legit_txs, _ = generate_dataset(
            seed=seed,
            difficulty=1,
            duration_hours=duration_hours,
            attacks=None,
            start_ts=base_ts,
        )
        all_stream = sorted(legit_txs + ring_txs, key=lambda t: t.ts)
        ring_accounts = gt.ring_accounts
    else:
        all_stream, _ = generate_dataset(
            seed=seed,
            difficulty=1,
            duration_hours=duration_hours,
            attacks=None,
            start_ts=base_ts,
        )
        ring_accounts = set()

    window = SlidingWindow(window_hours=WINDOW_HOURS)
    stream_idx = 0
    n_txs = len(all_stream)
    samples: List[dict] = []

    # Stream with tick_hours interval
    num_ticks = int(duration_hours / tick_hours)
    for tick_i in range(1, num_ticks + 1):
        curr_sim_time = base_ts + timedelta(hours=tick_i * tick_hours)

        while stream_idx < n_txs and all_stream[stream_idx].ts <= curr_sim_time:
            window.add(all_stream[stream_idx])
            stream_idx += 1

        window.advance(curr_sim_time)

        instances = detect(window, curr_sim_time)
        clusters = build_clusters(instances, window, accounts_dict)

        for c in clusters:
            feats = c.features
            if ring_accounts:
                overlap = len(c.accounts & ring_accounts)
                y = 1 if (overlap / len(c.accounts)) >= 0.50 else 0
            else:
                y = 0

            row = dict(feats)
            row["label"] = y
            row["seed"] = seed
            row["attack_type"] = attack_type or "legit"
            row["difficulty"] = difficulty
            row["sim_hr"] = tick_i * tick_hours
            row["cluster_id"] = c.cluster_id
            row["typology"] = c.typology
            samples.append(row)

    run_summary = (all_stream, ring_accounts)
    return samples, run_summary


def generate_feature_dataset(
    seeds: List[int],
    difficulties: List[int],
    attack_types: List[str],
    max_neg_ratio: float = 20.0,
    dataset_name: str = "train",
) -> Tuple[pd.DataFrame, List[Tuple[List, Set[str]]]]:
    """
    Generates feature dataset across seeds and difficulties in parallel using ProcessPoolExecutor.
    Subsamples negative samples to at most max_neg_ratio : 1.
    """
    runs_to_execute = []

    # Legit-only runs
    for s in seeds:
        runs_to_execute.append((s, None, 1))

    # Attack runs
    for s in seeds:
        for diff in difficulties:
            for atk in attack_types:
                runs_to_execute.append((s, atk, diff))

    print(f"\n[DATA GENERATION] Launching {len(runs_to_execute)} parallel simulation runs for {dataset_name}...")
    t0 = time.perf_counter()

    all_samples: List[dict] = []
    runs_data: List[Tuple[List, Set[str]]] = []

    workers = max(1, min(16, (os.cpu_count() or 2) - 1))

    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_simulate_single_run, s, atk, diff): (s, atk, diff)
            for (s, atk, diff) in runs_to_execute
        }

        completed = 0
        for future in as_completed(future_map):
            completed += 1
            if completed % 25 == 0 or completed == len(runs_to_execute):
                print(f"  Finished {completed}/{len(runs_to_execute)} simulation runs ({completed/len(runs_to_execute)*100:.1f}%)")
            samples, run_data = future.result()
            all_samples.extend(samples)
            runs_data.append(run_data)

    dt = time.perf_counter() - t0
    print(f"[DATA GENERATION] Completed in {dt:.2f}s. Extracted {len(all_samples):,} candidate cluster snapshots.")

    df = pd.DataFrame(all_samples)
    if df.empty:
        raise RuntimeError("No candidate clusters generated during simulation!")

    pos_df = df[df["label"] == 1]
    neg_df = df[df["label"] == 0]

    n_pos = len(pos_df)
    n_neg = len(neg_df)
    print(f"  Raw balance: {n_pos:,} positives, {n_neg:,} negatives (ratio {n_neg/max(1, n_pos):.1f}:1)")

    # Subsample negatives if ratio exceeds max_neg_ratio
    max_neg = int(n_pos * max_neg_ratio)
    if n_neg > max_neg and max_neg > 0:
        neg_df_sub = neg_df.sample(n=max_neg, random_state=42)
        print(f"  Subsampled negatives to {len(neg_df_sub):,} (exact {max_neg_ratio}:1 ratio)")
        final_df = pd.concat([pos_df, neg_df_sub], ignore_index=True).sample(frac=1.0, random_state=42).reset_index(drop=True)
    else:
        final_df = df.sample(frac=1.0, random_state=42).reset_index(drop=True)

    print(f"  Final {dataset_name} dataset size: {len(final_df):,} rows ({sum(final_df['label'] == 1):,} pos, {sum(final_df['label'] == 0):,} neg)")
    return final_df, runs_data


def run_training_pipeline():
    print("=" * 80)
    print("MULE HUNTER — M3 MODEL TRAINING & EVALUATION PREPARATION")
    print("=" * 80)

    # 1. Training features (Seeds 1-10, diff 1-3)
    train_seeds = list(range(1, 11))
    train_diffs = [1, 2, 3]
    attack_types = ["smurfing", "round_trip", "mule_chain", "hybrid"]

    train_df, train_runs_data = generate_feature_dataset(
        seeds=train_seeds,
        difficulties=train_diffs,
        attack_types=attack_types,
        max_neg_ratio=20.0,
        dataset_name="train",
    )
    TRAIN_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    train_df.to_parquet(TRAIN_DATA_PATH, index=False)
    print(f"Saved training features to: {TRAIN_DATA_PATH}")

    # 2. Validation features (Seeds 50-54, diff 1-3)
    val_seeds = list(range(50, 55))
    val_diffs = [1, 2, 3]

    val_df, _ = generate_feature_dataset(
        seeds=val_seeds,
        difficulties=val_diffs,
        attack_types=attack_types,
        max_neg_ratio=20.0,
        dataset_name="val",
    )
    val_df.to_parquet(VAL_DATA_PATH, index=False)
    print(f"Saved validation features to: {VAL_DATA_PATH}")

    # 3. Baseline threshold tuning on training data
    print("\n[STEP B3] Tuning baseline threshold T on training runs (10k - 150k INR)...")
    optimal_t = tune_threshold_on_runs(train_runs_data)

    # 4. Train XGBoost classifier & Isotonic probability calibrator
    print("\n[STEP B2] Training XGBoost classifier & Isotonic probability calibrator...")
    model, calibrator = train_and_save_model(train_df, val_df)

    print("\n" + "=" * 80)
    print("TRAINING PIPELINE COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_training_pipeline()
