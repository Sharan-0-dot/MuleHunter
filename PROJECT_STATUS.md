# Mule Hunter — Project Status

## Milestone Checklist

| Milestone | Description | Status |
|---|---|---|
| **M0** | Contracts, folder skeleton, mock backend (`mock_backend.py`), sample audio (`.wav`), test suite (`test_mock.py`) | **Done** |
| **M1** | Simulator (`generator.py`, `attacks.py`), legit traffic + hard negatives, difficulty knobs, Step 0 fixes applied, `sim_check.py` | **Done, fixes applied** |
| **M2** | Detectors (sliding window, fan-out/in, cycles, mule chains, reconvergence) + cluster builder (`window.py`, `patterns.py`, `clusters.py`, `detect_check.py`) | **Done (Step A quality fixes passed)** |
| **M3** | XGBoost risk model, baseline threshold rule, evaluation script (`evaluate.py`) | **Done** |
| **M4a** | Live pipeline: simulator -> detection -> model -> alert -> summary -> wav -> push to Pi and dashboard (`engine.py`, `main.py`, `test_real.py`, `soak_real.py`) | **Done** |
| **M4b** | Backend hardening (fingerprint JWT protection on mutate endpoints, freeze endpoint, hash-chained audit log) | Not Started |
| **M5** | Frontend 3D dashboard (React + Vite + `react-force-graph-3d`) | Not Started |
| **M6** | Integration rehearsals, metrics page, audit verification, demo rehearsals | Not Started |

---

## What Was Built

### Milestone M0 (Completed)
- **Folder structure**: Complete backend directory layout according to `01_PERSON1_SOFTWARE.md` section 3.
- **Mock backend (`backend/mock_backend.py`)**: Running on Port 8000 for hardware partner testing.
- **Sample Audio Files**: Pre-made sample WAVs for red, yellow, green alert scenarios.
- **Test suite (`backend/scripts/test_mock.py`)**: End-to-end integration test suite verifying WebSocket, HTTP trigger, audio download, valid/invalid HMAC ack, challenge/response, and auth.

### Milestone M1 (Completed, Step 0 Fixes Applied)
- **Data Models with Zero Label Leakage (`backend/app/sim/generator.py`)**:
  - `Transaction` dataclass with observable fields only: `tx_id`, `ts`, `src`, `dst`, `amount`, `kind`.
  - Separate `GroundTruth` and `DatasetGroundTruth` tracking `ring_id`, `ring_type`, `ring_accounts`, `ring_tx_ids`, and amounts for training/evaluation code.
  - Accounts pool of 2,000 accounts: 1,400 individuals, 400 merchants, 200 businesses.
- **Attack Ring Injectors (`backend/app/sim/attacks.py`)**:
  - 5 attack typologies: `smurfing`, `round_trip`, `mule_chain`, `hybrid`, `stealth`.

### Milestone M2 (Completed, Step A Quality Fixes Passed)
- **Sliding Graph Window (`backend/app/detect/window.py`)**:
  - `SlidingWindow(window_hours=48.0)` with exact eviction and per-(u, v) edge aggregates.
- **Quality Fixes (Step A Gates G1-G6 All Passed)**:
  - Ring span capped at <= 36.0h (< 0.75 * WINDOW_HOURS).
  - Cycle search pruned to SCCs (size 3-50), edge flow >= 5k INR: cap hit dropped from 53.55% to 0.00%, mean tick runtime = 22.18 ms.
  - Giant component prevention with strict core-account DSU sharing: legit p99 = 18.0 (<= 40), max = 20 (<= 80).
  - Mule chain pass-through upper bound (`0.75 <= pass_through <= 1.35`) preventing employer bridging.
  - Gate G4: Diff 1-3 found = 36/36 (100%), coverage = 90.4%, purity = 95.4%. Typology accuracy = 91.7%.

### Milestone M3 (Completed)
- **Baselines & Calibrated Model (`backend/app/detect/baseline.py`, `model.py`)**:
  - `baseline_fixed` (50k INR) & `baseline_tuned` ($T = \text{INR } 120,000$).
  - XGBoost classifier with Isotonic probability calibrator persisted to `model.json` and `calibrator.joblib`.
  - Evaluation on validation split: Rules + XGBoost achieved F1 = 0.7390 (**35.5x improvement** over fixed baseline), Ring Detected Recall = 96.7%, Prevented INR = 10,835,303.79 INR.

### Milestone M4a (Completed)
- **Step 0 — Exact Risk Bands Restored & Full Grid Evaluation**:
  - Restored master bands in `.env` and `config.py`: `ALERT_MIN=0.40`, `GREEN_MAX=0.65`, `YELLOW_MAX=0.85`.
  - Evaluated full grid (110 simulation runs: 4 types x 5 diffs x 5 seeds + 5 stealth + 5 legit) to `backend/data/metrics_val_full.json`.
  - True-ring clusters reach calibrated risk score 1.0000 across p10 to p100 deciles (readily reaching red >= 0.85).
  - Legit clusters max calibrated risk score = 0.3208 (< 0.40 ALERT_MIN).
  - Stealth attack scenario: Rules + XGBoost achieved F1 = 0.7051 and Ring Recall = 80.0%, while fixed baseline collapsed to F1 = 0.0156 and Ring Recall = 20.0%, and tuned baseline scored F1 = 0.0093 and Ring Recall = 0.0%.
- **Step 1 — Configuration & Environment**:
  - Configured `REAL_PORT=8001`, `PUBLIC_BASE_URL` (auto-detected LAN IP fallback), `OPENROUTER_*`, `LLM_*`, and timing parameters. Confirmed `.env` is gitignored.
- **Step 2 — Real-Time Streaming & Alert Engine (`backend/app/engine.py`)**:
  - Owns simulated clock (1x-20x), 48h sliding window, candidate clustering, `ClusterTracker` with stable `C-xxxx` IDs.
  - Background asyncio wall-clock loop advancing every ~500 ms with detection ticks every 15 sim-minutes.
  - Strict push sequence: SQLite DB persist -> Audio verify -> `/ws/pi` push -> `/ws/dashboard` broadcast.
  - Escalation monitor: dispatches `{"type": "escalate"}` to Pi if no voice/joystick ack within `listen_seconds + 5` (30s).
- **Step 3 — Spoken Summaries & Audio Generation (`backend/app/summary/*`)**:
  - `templates.py`: Deterministic spoken-friendly templates under 45 words ending with `"Log in to the dashboard for linked accounts."`
  - `llm.py`: Optional OpenRouter LLM polish with strict validation (number preservation, exact closing sentence, <= 55 words) and silent fallback.
  - `tts.py`: `pyttsx3` WAV synthesizer generating mono 16-bit PCM <= 25s with fallback to pre-made WAVs on timeout/failure.
- **Step 4 — Database Persistence (`backend/app/db.py`)**:
  - SQLite tables: `alerts`, `clusters`, `alert_tx`, `officers`, `pi_events`.
- **Step 5 — REST API & WebSockets (`backend/app/main.py`)**:
  - Runs on port 8001.
  - Implements `/api/sim/start`, `/stop`, `/reset`, `/attack`, `/api/graph`, `/api/clusters`, `/api/accounts/{id}`, `/api/metrics`, `/api/pi/ack` (HMAC-SHA256 verified), `/ws/pi`, `/ws/dashboard`, `/ws/auth/{id}`.
- **Step 6 — Contract Test Suite (`backend/scripts/test_real.py`)**:
  - Executed against live server on port 8001. All 9 contract checks passed:
    - Master 8.2 alert fields and types verified.
    - WAV audio downloaded: mono 16-bit PCM, 22050 Hz, 15.32s duration (<= 25s limit).
    - HMAC signature verification: 200 on valid, 401 on forged signature.
    - Dashboard events received: `tx_batch`, `cluster_alert`, `pi_ack`.
    - Biometric challenge -> fingerprint -> `/ws/auth` login verified.
    - Attack launch to alert pushed latency: 52.33s wall-clock time.
- **Step 7 — 10-Minute Soak Test (`backend/scripts/soak_real.py`)**:
  - Ran for 10 minutes at `SIM_SPEED=10` (~100 sim-hours), processing 18,750 transactions.
  - Injected 6 attacks across difficulties 1-4: **100.0% ring recall (6 / 6 rings alerted)**.
  - Mean detection tick runtime: 248.88 ms (< 500 ms target).
  - RAM memory growth: +0.1 MB (4.2 MB -> 4.3 MB).
- **Step 8 — Hardware Teammate Handoff (`FRIEND_HANDOFF.md`)**:
  - Complete guide created detailing port 8001 endpoints, curl commands, WebSocket schemas, HMAC signing, and biometric mappings.

---

## Files Created / Modified in M4a

- `backend/.env`
- `backend/.env.example`
- `backend/app/config.py`
- `backend/app/detect/model.py`
- `backend/app/detect/tracker.py`
- `backend/scripts/evaluate.py`
- `backend/data/metrics_val_full.json`
- `backend/app/db.py`
- `backend/data/mulehunter.db`
- `backend/app/summary/__init__.py`
- `backend/app/summary/templates.py`
- `backend/app/summary/llm.py`
- `backend/app/summary/tts.py`
- `backend/app/engine.py`
- `backend/app/main.py`
- `backend/scripts/test_real.py`
- `backend/scripts/soak_real.py`
- `FRIEND_HANDOFF.md`
- `PROJECT_STATUS.md`
- `NOTES.md`

---

## Known Issues

- **High-speed stream false alert rate**: During 10x sim speed soak testing, legitimate payroll fan-out and merchant fan-in clusters occasionally trigger candidate alerts. The calibrated risk bands and hardware voice escalation safeguard against disruptive false alarms, and M4b freeze authorization ensures human confirmation before account locking.
- **Mock backend remains active**: `backend/mock_backend.py` is running untouched on port 8000 for hardware partner testing until instructed to switch.

---

## Decisions Made

- **Strict Port Isolation**: Real backend developed and validated on port 8001 (`REAL_PORT`), preserving port 8000 for the teammate's ongoing hardware tests.
- **Audio Synthesis Safety**: `pyttsx3` operations protected by timeout-guarded threading locks with automatic fallback to pre-made alert WAVs.
- **Zero Label Leakage**: Ground truth registry strictly isolated server-side for automated validation; completely excluded from client payloads and detection inputs.

---

## What's Next

- **Milestone M4b**: Backend hardening (JWT protection on mutate endpoints, account freeze execution, hash-chained audit logging).
- **Milestone M5**: Frontend 3D graph dashboard (React + Vite + `react-force-graph-3d`).
