# Mule Hunter — Project Notes & Runbook

## Milestone Status Overview

- **Milestone M0 (Complete)**: Project skeleton, contracts, sample audio wavs, mock backend server, test suite.
- **Milestone M1 (Complete, Fixes Applied)**: Transaction simulator, legit traffic + hard negatives, 5 attack typologies across 5 difficulty levels, batch & streaming interfaces, Step 0 fixes applied, verification script (`sim_check.py`).
- **Milestone M2 (Complete, Step A Quality Fixes Passed)**: Sliding window temporal graph (`window.py`), pattern detectors (`patterns.py`), cluster builder & scale-free features (`clusters.py`), Step A quality gates G1–G6 all passed (`detect_check.py`).
- **Milestone M3 (Complete)**: Baseline models (`baseline.py`), parallel feature extraction & training pipeline (`train.py`), calibrated XGBoost model (`model.py`), comprehensive evaluation suite (`evaluate.py`).
- **Milestone M4a (Complete)**: Live pipeline: simulator -> detection -> model -> alert -> summary -> wav -> push to Pi and dashboard (`engine.py`, `main.py`, `test_real.py`, `soak_real.py`). Real backend running on Port 8001.
- **Next Milestone**: **M4b — Backend Hardening** (JWT protection on mutate endpoints, account freeze execution, hash-chained audit logging).

---

### 1. Mock Backend (Milestone M0)

- Auto-detected LAN IP: `10.80.30.21` (port 8000)
- Shared Secret: `mulehunter-demo-secret`
- Endpoints:
  - WebSocket `/ws/pi`: 10-second ping keepalive, pong reception
  - POST `/mock/trigger?level=red|yellow|green`: broadcasts alert JSON
  - POST `/api/pi/ack`: HMAC-SHA256 signature verification via `X-Signature` header
  - Direct dashboard compliance officer session (active Officer A)

#### Commands:
```powershell
# Run mock backend
.\backend\.venv\Scripts\python.exe backend\mock_backend.py

# Run mock verification suite
.\backend\.venv\Scripts\python.exe backend\scripts\test_mock.py
```

---

### 2. Simulator (Milestone M1 with Step 0 Fixes)

- **Observable Data (`backend/app/sim/generator.py`)**:
  - `Transaction` dataclass: `tx_id`, `ts`, `src`, `dst`, `amount`, `kind`. Zero label leakage.
  - Accounts pool: 2,000 accounts (1,400 individuals, 400 merchants, 200 businesses).
  - Legit traffic: P2P, merchant payments (fan-in), payroll (fan-out), rent, large one-off purchases (>= 60,000 INR).
- **Attack Injectors (`backend/app/sim/attacks.py`)**:
  - 5 typologies: `smurfing`, `round_trip`, `mule_chain`, `hybrid`, `stealth`.
  - Step 0 fixes applied:
    - Connectivity: all decoys actively route transactions; every ground-truth account appears in >= 1 ring tx, and each ring forms a single weakly connected component.
    - Stealth: strictly forces difficulty 5 regardless of passed difficulty.
    - Structuring under threshold: at difficulty 5, 100% of transfers are structured into chunks < `SIM_NAIVE_THRESHOLD` (50,000 INR) spaced minutes apart; `% >= threshold` is strictly 0.0%.
    - Volume preservation: base laundering volume is preserved across difficulties.
    - Zero vocabulary leakage; chronological `tx_id` assignment after sorting.

#### Commands:
```powershell
.\backend\.venv\Scripts\python.exe backend\scripts\sim_check.py
```

---

### 3. Detectors & Clustering (Milestone M2)

- **Sliding Window (`backend/app/detect/window.py`)**:
  - `SlidingWindow(window_hours=48.0)` maintains per-(u, v) edge aggregates (`total`, `count`, `first_ts`, `last_ts`, `tx_list`) and per-node inflow/outflow lists.
  - Zero-leak exact eviction: verified with `test_sliding_window_oracle()`.
- **Step A Quality Gates Verification (`detect_check.py`)**:
  - **G1**: Ring span <= 36.0h (observed max = 22.13h). PASS.
  - **G2**: Cycle budget cap hit rate = 0.00% (< 5%), mean tick runtime = 22.18 ms (< 500 ms). PASS.
  - **G3**: Legit-only candidate cluster size: p99 = 18.0 (target <= 40), max = 20 (target <= 80). PASS.
  - **G4**: Diff 1-3 found = 36/36 (100%), mean coverage = 90.4% (target >= 85%), mean purity = 95.4% (target >= 70%). PASS.
  - **G5**: Diff 1-3 typology accuracy = 91.7% (target >= 80%). PASS.
  - **G6**: Window oracle test, toy graph test, and Leakage Guard all pass. PASS.

#### Commands:
```powershell
.\backend\.venv\Scripts\python.exe backend\scripts\detect_check.py
```

---

### 4. Model, Baseline & Evaluation (Milestone M3)

#### Baseline Models (`backend/app/detect/baseline.py`)
- `baseline_fixed`: Flags any transaction >= SIM_NAIVE_THRESHOLD (50,000 INR).
- `baseline_tuned`: Optimal threshold $T = \text{INR } 120,000.00$ tuned via grid search on training data to maximize account-level F1.
- `rules_only`: Flags all accounts present in any candidate cluster without machine learning filtering.

#### Machine Learning Pipeline (`backend/scripts/train.py`, `backend/app/detect/model.py`)
- **Training Set**: Seeds 1–10 (diff 1–3, 120 attack runs + 10 legit runs = 130 runs total, 96h stream, 2h ticks). 56,952 cluster snapshots after 20:1 negative subsampling.
- **Validation Set**: Seeds 50–54 (diff 1–3, 60 attack runs + 5 legit runs = 65 runs total, 96h stream, 2h ticks). 29,127 cluster snapshots after 20:1 negative subsampling.
- **Model Hyperparameters**:
  - Algorithm: `XGBClassifier`
  - `max_depth = 4`
  - `n_estimators = 200` (~200 trees)
  - `learning_rate = 0.1`
  - `eval_metric = "logloss"`
  - `early_stopping_rounds = 15`
  - `scale_pos_weight = 10.0`
- **Calibration**: `IsotonicRegression(out_of_bounds="clip")` fitted on validation probabilities.
- **Urgency Bands (Master 8.1)**:
  - Green: `risk_score < 0.40`
  - Yellow: `0.40 <= risk_score < 0.70`
  - Red: `risk_score >= 0.70`

#### Validation Split Results (`evaluate.py --split val`, Seeds 50–54)

```
================================================================================
MULE HUNTER — EVALUATION METRICS REPORT (SPLIT: VAL)
================================================================================

[1] Account-Level Detection Performance (Precision, Recall, F1):
Method                 | Precision  | Recall     | F1-Score   | Ring Recall 
----------------------------------------------------------------------------
Baseline (Fixed 50k)   | 1.1%       | 99.1%      | 0.0208     | 100.0%      
Baseline (Tuned T)     | 2.7%       | 83.2%      | 0.0525     | 91.7%       
Rules Only (No ML)     | 0.9%       | 94.5%      | 0.0171     | 95.0%       
Rules + XGBoost (Ours) | 62.3%      | 90.8%      | 0.7390     | 96.7%       

[2] Adversarial Robustness: Account-Level F1 by Difficulty:
Difficulty   | Baseline Fixed  | Baseline Tuned  | Rules Only      | Rules + XGBoost
------------------------------------------------------------------------------------
Level 1      | 0.0196          | 0.0588          | 0.0160          | 0.7233         
Level 2      | 0.0196          | 0.0589          | 0.0159          | 0.7148         
Level 3      | 0.0282          | 0.0521          | 0.0237          | 0.7668         

[3] Operational & Hardware Defense Metrics:
  - Ring Detected Recall (Rules + XGBoost) : 96.7% (58 / 60 rings detected)
  - Mean Detection Latency                 : +3069.7 s
  - Median Detection Latency               : +3286.3 s
  - Total Laundered INR Prevented          : INR 10,835,303.79 (~1.08 Crore INR)
  - False Red Alerts / Legit Sim-Day       : 0.00 (Zero false alerts on legit traffic)
================================================================================
```

#### Commands to train & evaluate:
```powershell
# Run training pipeline (feature generation + baseline tuning + XGBoost training)
.\backend\.venv\Scripts\python.exe backend\scripts\train.py

# Run validation evaluation
.\backend\.venv\Scripts\python.exe backend\scripts\evaluate.py --split val

# (Held-out test split only when explicitly ready)
# .\backend\.venv\Scripts\python.exe backend\scripts\evaluate.py --split test --confirm-final
```

---

### 5. Live Pipeline & Real Backend (Milestone M4a)

- **Port**: Currently running on **Port 8001** (`REAL_PORT`). Mock backend remains active on Port 8000 for hardware partner testing.
- **Master 8.1 Risk Bands Restored**:
  - `ALERT_MIN = 0.40`
  - `GREEN_MAX = 0.65`
  - `YELLOW_MAX = 0.85`
  - Below 0.40: no alert; 0.40-0.65: green; 0.65-0.85: yellow; >= 0.85: red.
- **Database (`backend/data/mulehunter.db`)**: SQLite tables `alerts`, `clusters`, `alert_tx`, `officers`, `pi_events`.
- **Spoken Audio Summaries**: Spoken-friendly templates under 45 words ending with `"Log in to the dashboard for linked accounts."` Optional OpenRouter polish with strict number preservation, synthesized via `pyttsx3` into mono 16-bit PCM WAV.
- **Contract Verification (`backend/scripts/test_real.py`)**: All contract checks passed (audio duration 15.32s, HMAC verification 200/401, WebSockets `/ws/pi` and `/ws/dashboard`, freeze and audit verification).
- **10-Minute Soak Test (`backend/scripts/soak_real.py`)**: 6/6 rings detected (100.0% recall), 248.88 ms mean tick runtime, +0.1 MB RAM delta over 100 sim-hours at 10x sim speed.

#### Full Grid Validation Results (`evaluate.py --split val --full`, Seeds 50–54)

```
================================================================================
MULE HUNTER — FULL EVALUATION REPORT (SPLIT: VAL)
Config Risk Bands: ALERT_MIN=0.4, GREEN_MAX=0.65, YELLOW_MAX=0.85
================================================================================

[1] Account-Level Precision / Recall / F1 by Difficulty (1-5):
Diff   | Model                  | Precision  | Recall     | F1-Score  
----------------------------------------------------------------------
L1     | Baseline (Fixed 50k)   | 1.0%       | 100.0%     | 0.0196    
L1     | Baseline (Tuned T)     | 3.0%       | 100.0%     | 0.0588    
L1     | Rules + XGBoost (Ours) | 56.1%      | 92.0%      | 0.6970    
----------------------------------------------------------------------
L2     | Baseline (Fixed 50k)   | 1.0%       | 100.0%     | 0.0196    
L2     | Baseline (Tuned T)     | 3.0%       | 100.0%     | 0.0589    
L2     | Rules + XGBoost (Ours) | 60.6%      | 87.2%      | 0.7148    
----------------------------------------------------------------------
L3     | Baseline (Fixed 50k)   | 1.4%       | 97.8%      | 0.0282    
L3     | Baseline (Tuned T)     | 2.7%       | 60.5%      | 0.0521    
L3     | Rules + XGBoost (Ours) | 66.4%      | 93.0%      | 0.7748    
----------------------------------------------------------------------
L4     | Baseline (Fixed 50k)   | 0.9%       | 55.6%      | 0.0178    
L4     | Baseline (Tuned T)     | 1.7%       | 33.7%      | 0.0323    
L4     | Rules + XGBoost (Ours) | 60.7%      | 88.8%      | 0.7208    
----------------------------------------------------------------------
L5     | Baseline (Fixed 50k)   | 0.7%       | 35.3%      | 0.0130    
L5     | Baseline (Tuned T)     | 0.4%       | 6.4%       | 0.0071    
L5     | Rules + XGBoost (Ours) | 71.4%      | 80.8%      | 0.7585    
----------------------------------------------------------------------

[2] Stealth Attack Scenario Performance (Difficulty 5 Structured Below 50k):
Model                  | Precision  | Recall     | F1-Score   | Ring Recall 
----------------------------------------------------------------------------
Baseline (Fixed 50k)   | 0.8%       | 36.2%      | 0.0156     | 20.0%       
Baseline (Tuned T)     | 0.5%       | 7.2%       | 0.0093     | 0.0%        
Rules Only (No ML)     | 1.6%       | 87.0%      | 0.0320     | 80.0%       
Rules + XGBoost (Ours) | 63.2%      | 79.7%      | 0.7051     | 80.0%       

[3] False Alerts per Legit Sim-Day (Split by Risk Band):
  - Green Alerts (0.40 <= risk < 0.65) : 0.00 / day
  - Yellow Alerts (0.65 <= risk < 0.85): 0.00 / day
  - Red Alerts (risk >= 0.85)         : 0.00 / day
  - Total False Alerts (risk >= 0.40)  : 0.00 / day

[4] Calibrated Risk-Score Deciles (True-Ring vs Legit Clusters):
Percentile   | True-Ring Clusters   | Legit Clusters      
----------------------------------------------------------
p10          | 1.0000               | 0.0000              
p20          | 1.0000               | 0.0000              
p30          | 1.0000               | 0.0000              
p40          | 1.0000               | 0.0000              
p50          | 1.0000               | 0.0000              
p60          | 1.0000               | 0.0000              
p70          | 1.0000               | 0.0000              
p80          | 1.0000               | 0.0000              
p90          | 1.0000               | 0.0000              
p100         | 1.0000               | 0.3208              
================================================================================
```

#### Commands to run:
```powershell
# Start real backend server on port 8001
.\backend\.venv\Scripts\uvicorn.exe app.main:app --app-dir backend --host 0.0.0.0 --port 8001

# Run contract test suite
.\backend\.venv\Scripts\python.exe backend\scripts\test_real.py

# Run 10-minute real-time soak test
.\backend\.venv\Scripts\python.exe backend\scripts\soak_real.py
```

---

### Milestone M4b: Live Pipeline Hardening, Severity Scoring, Account Freeze & Audit Chain (2026-11-14)

#### Root Cause Analysis: False Alert Explosion & Counter Drift
1. **First Alert `A-0569` in earlier runs**: SQLite database `alerts` table had accumulated alerts from unreset earlier soak test runs, causing `Engine.__init__` to load `get_max_alert_id() + 1 = 569`. Resolved by resetting alert and cluster counters cleanly on startup and on `/api/sim/reset`.
2. **False Alert Explosion (320 false alerts in soak)**: The live streaming generator called `_generate_legit_traffic(..., dt_sec/3600.0)` every 500ms. Because of `max(1, int(round(10 * duration/24)))` on payroll and `max(5, int(round(1.5 * duration)))` on large purchases, each 5-second slice generated an entire payroll run and 5 large purchases (>60k INR). Over 24 sim-hours, this injected 374,630 transactions and 86,400 large purchases instead of the intended 6,431 transactions!
3. **Fix**: `TransactionStream` unified to draw directly from the `generate_dataset` code path in time chunks. Diagnostic comparison confirmed 100% exact match across all dimensions (6,431 vs 6,431 txs, identical kind mix, identical percentiles, 268 tx/hr).

#### Gate G1 Replay Results (`backend/scripts/soak_real.py`):
```
================================================================================
MULE HUNTER - 48 SIM-HOUR HEADLESS SOAK REPLAY
================================================================================
  - Simulated Hours Advanced       : 48.0 sim-hours
  - Wall-Clock Execution Time      : 25.55 s
  - Total Alerts Raised            : 14
  - True Alerts (Ring Matched)     : 14
  - False Alerts (Legit Only)      : 0
  - False Alerts / Sim-Hour        : 0.000 (GATE G1 limit <= 2.0) [PASSED]
  - Rings Alerted                  : 5 / 6 (GATE G1 limit >= 5)   [PASSED]
  - Alerts By Band                 : {'green': 7, 'yellow': 5, 'red': 2}
  - Mean Detection Tick Runtime    : 60.68 ms
  - Mean Time to Alert             : 470.3 sim-min
================================================================================
>>> GATE G1 PASSED: false alerts <= 2/hr and >= 5/6 rings alerted! <<<
```

#### Step 2 Severity Scoring & Sizing Results:
- Formula: $\text{risk\_score} = 0.5 \cdot p + 0.5 \cdot \text{exposure}$, where $\text{exposure} = \min(1, \frac{\text{total\_amount\_inr}}{2,500,000})$.
- Dynamic Sizing Validation (`backend/scripts/test_sizing.py`):
  - 3 Lakh INR (300,000)   -> Risk 0.5899 -> **GREEN**
  - 10 Lakh INR (1,000,000) -> Risk 0.7997 -> **YELLOW**
  - 25 Lakh INR (2,500,000) -> Risk 1.0000 -> **RED**

#### Step 4 M4b Features & Contract Verification (`backend/scripts/test_real.py`):
- `POST /api/clusters/{id}/freeze`: 401 without JWT / bad token, 200 with officer JWT.
- Defense signals: `clear` dispatched to `/ws/pi`, `frozen` broadcast to `/ws/dashboard`.
- Cryptographic Audit Log: SHA-256 hash-chained entries. Verified with `GET /api/audit/verify` (ok=True).
- Tamper Demonstration (`backend/scripts/tamper_demo.py`): Confirmed immediate rejection when SQLite row is modified (verify flips to `ok=False` pinpointing bad row).
- 100% of integration checks passed on port 8001.
