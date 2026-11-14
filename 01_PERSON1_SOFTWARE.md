# 01 — PERSON 1: SOFTWARE (Sharan)

> Read `00_MASTER.md` first. Contracts, endpoints, JSON shapes and config live there and are NOT repeated in full here.
> AI assistant instructions: build in the milestone order below. After each milestone, run it and show the output before moving on. Do not add features that are not listed. Keep code simple and readable; the human must be able to explain every module to judges.

## 1. Your scope

You own everything on the laptop: the transaction simulator and attack launcher, the temporal graph, detectors, clustering, XGBoost risk model, baseline, metrics, summaries, TTS wav generation, the FastAPI backend (REST + WebSockets), SQLite persistence, hash-chained audit log, and the React 3D dashboard. Person 2 owns the Raspberry Pi compliance desk; they build against YOUR mock backend first.

## 2. Stack (fixed)

- Python 3.11, FastAPI, uvicorn, websockets, NetworkX, NumPy, pandas, scikit-learn, XGBoost, SQLite (stdlib `sqlite3` or SQLModel), PyJWT, requests.
- Summary: deterministic **template** first; optional Gemini polish with a 4 s timeout and automatic fallback to the template.
- TTS (offline, must never fail): try **Piper** (`en_US` medium voice); fallback **pyttsx3** (`save_to_file`); convert/resample with `ffmpeg` if available. Output WAV mono 16-bit.
- Frontend: Vite + React + `react-force-graph-3d` (three.js), Recharts for the metrics page, plain fetch + WebSocket.

## 3. Repo layout (your folders)

```
backend/
  app/main.py                 # FastAPI app, CORS open, mounts /static
  app/config.py               # reads .env (SHARED_SECRET, BACKEND_URL, thresholds)
  app/db.py                   # sqlite tables: tx, accounts, clusters, alerts, officers, audit
  app/sim/generator.py        # background legit traffic + hard negatives
  app/sim/attacks.py          # attack injectors with difficulty 1-5 + ground-truth labels
  app/detect/window.py        # sliding-window temporal graph
  app/detect/patterns.py      # fan-out/in, cycles, mule chains, reconvergence
  app/detect/clusters.py      # union-find merge, cluster features
  app/detect/model.py         # XGBoost train/load/predict -> risk_score
  app/detect/baseline.py      # per-tx threshold rule
  app/summary/templates.py    # typology summary templates
  app/summary/llm.py          # optional Gemini polish (timeout + fallback)
  app/summary/tts.py          # text -> static/audio/{cluster_id}.wav
  app/api/*.py                # routes per master section 8.5
  app/ws.py                   # /ws/dashboard, /ws/pi, /ws/auth/{id}
  app/auth.py                 # challenge/response, JWT, HMAC verify, officer seed
  app/audit.py                # hash-chained audit log
  scripts/train.py            # generate train data, fit model, save model.json
  scripts/evaluate.py         # held-out eval -> metrics.json
  mock_backend.py             # SHIP IN HOUR 1 for Person 2
  static/audio/               # wavs (+ green.wav yellow.wav red.wav samples)
frontend/                     # Vite React app (pages: Login, Dashboard, Metrics, Audit)
```

## 4. Milestones (do in order)

**M0 (hour 0–1): contracts + mock backend.** Create repo, `.env`, `mock_backend.py` per master 8.7 with sample wavs (any TTS: "Red alert. Seven accounts moved four point two lakh rupees in a loop. Log in to the dashboard for linked accounts."). Run on `0.0.0.0:8000`, send Person 2 your laptop IP and the hotspot name. Verify `POST /mock/trigger?level=red` pushes JSON on `/ws/pi`.

**M1 (1–3h): simulator.** Spec in section 5.

**M2 (3–6h): detectors + clusters.** Spec in section 6.

**M3 (6–8h): model + baseline + evaluation script.** Spec in section 7. Get a first honest F1 table early.

**M4 (8–10h): backend glue.** Streaming loop (simulator → window → detectors → cluster → model → alert), summary + TTS, persistence, `/ws/pi` push, `/ws/dashboard` events, REST endpoints, auth, audit. Replace the mock with the real server (same URLs). Run a real alert to the Pi (hour 8 sync).

**M5 (10–13h): dashboard.** Spec in section 8.

**M6 (13–14h): freeze flow, metrics page, audit page.** Then rehearse.

## 5. Simulator spec

**Time:** simulated clock with a speed multiplier (1×–20×). All timestamps are simulated; expose ISO strings in APIs. Currency is INR.

**Accounts (~2,000):** ~1,400 `individual`, ~400 `merchant`, ~200 `business`. Each has a baseline activity rate and typical amount distribution (lognormal; individuals mostly ₹200–₹20,000, merchants receive many small payments, businesses pay salaries/suppliers).

**Legit behaviours (including HARD NEGATIVES, important):**
- P2P transfers between individuals (small, random).
- Merchant payments: many customers → one merchant (**legit fan-in**).
- Payroll: one business → many employees on the same day, equal-ish amounts (**legit fan-out**).
- Rent/utility recurring payments.
- Occasional large one-off purchase (₹60k–₹3L) from an individual to a merchant (trips the naive amount threshold).
These make the problem honest: the detector must separate bad fan-in/out from good using time, amount similarity, reconvergence, pass-through and retention.

**Attacks (`attacks.py`)** each returns transactions + ground-truth set of laundering accounts and a ring id:
- `smurfing`: source S splits total amount T (₹3–15 lakh) into k mules (k = 5–12, near-equal parts), mules forward to destination D (or two destinations) within a delay window.
- `round_trip`: cycle of 3–6 accounts, money returns to origin minus 1–3% fee within hours.
- `mule_chain`: chain of 4–8 accounts, each forwards 95–99% within minutes.
- `hybrid`: smurfing → chain → cycle back to source.
- `stealth`: any of the above at difficulty 5.

**Difficulty 1–5 (knobs):**
| Level | Amount split noise | Delay between hops | Decoys | Per-tx amount vs naive threshold | Legit mixing |
|---|---|---|---|---|---|
| 1 | ~0% | minutes | none | many txs above threshold | none |
| 2 | 5% | tens of minutes | none | mostly above | none |
| 3 | 10% | ~1 hour | 1–2 decoy hops | mixed | light |
| 4 | 20% | hours + jitter | 2–4 decoys, partial convergence | mostly below | moderate (mules also receive/send legit txns) |
| 5 | 30% | hours, irregular | many decoys, 85–90% retention at some hops, structuring below threshold | all below | heavy |

Attack launcher endpoint injects the ring into the live stream over a short sim period, so the presenter sees it form.

## 6. Detection spec (`patterns.py`, `clusters.py`)

Sliding window: last W sim-hours (default 6h, configurable) of edges aggregated per (u, v): total amount, count, first_ts, last_ts. Keep per-node rolling in/out amounts and timestamps for hold-time.

1. **Fan-out(node):** out-distinct-recipients ≥ 4 within window W1 (default 2h), total out ≥ ₹1L, amount coefficient-of-variation low (< 0.5). **Fan-in** symmetric.
2. **Reconvergence:** for each fan-out source, check whether ≥ 2 branches reach a common destination within ≤ 3 hops in time-respecting order → `smurfing_fan_out_fan_in`.
3. **Time-respecting cycles:** DFS from nodes that both receive and send in window; edge timestamps must increase along the path; length 3–6; amount retention (returned/sent) ≥ 0.8; cap work per tick (limit starts, limit depth, dedupe cycles by canonical rotation).
4. **Mule chain:** `pass_through = out/in` within window and `hold = median(time from inflow to next outflow)`. Node is mule-like if pass_through ≥ 0.9 and hold < 30 sim-min (loosen at higher difficulty via model features rather than hard rules). Chain = ≥ 3 consecutive mule-like nodes.
5. **Cluster build:** union-find over accounts that appear in the same pattern instance or share pattern instances. Typology = dominant pattern (hybrid if ≥ 2 pattern types).
6. **Candidate generation is deliberately recall-oriented.** The model removes false positives (payroll, merchants).

**Cluster features:** n_accounts, total_amount, time_span, density, max/mean pass_through, median hold time, amount CV, pattern-type flags (fan_out, fan_in, cycle, chain, reconvergence), cycle length, retention, ratio of amount-just-below-threshold txs, share of accounts that are merchants/businesses.

## 7. Model + evaluation spec

- **Label:** cluster is positive if ≥ 50% of its accounts belong to a ground-truth ring.
- **Model:** XGBoost classifier on cluster features → `risk_score` (probability). Save to `model.json`. Calibrate roughly so the green/yellow/red bands in master 8.1 look sensible.
- **Baseline (`baseline.py`):** flag any transaction ≥ ₹T; accounts in flagged tx are flagged. **Tune T on the training data to maximize F1** so the baseline is fair and judges can't call it a strawman.
- **Protocol (`evaluate.py`):** train on seeds 1–5 at difficulty 1–3 only. Test on held-out seeds 100–104 at difficulty 1–5 (levels 4–5 are unseen by training). Output to `metrics.json`:
  - account-level precision/recall/F1: baseline vs rule-only (ablation) vs rules+XGBoost
  - F1 by difficulty (the headline chart)
  - cluster-level recall of injected rings
  - detection latency (sim-seconds from last ring transaction to alert)
  - ₹ prevented when freeze is approved at alert time
- Report honestly, including difficulty levels where we also degrade. A line like "ours drops from 0.93 to 0.78 while baseline drops to 0.21" is more credible than "100% everywhere".

## 8. Dashboard spec (frontend)

Pages: `/login`, `/` (dashboard), `/metrics`, `/audit`.

**Dashboard layout:** top bar (sim start/stop/speed, live tx counter, officer name); left: alert feed (colored by level, click = fly to cluster); center: 3D graph; right: node/cluster panel; bottom or modal: attack launcher (5 buttons + difficulty slider).

**3D graph (`react-force-graph-3d`):**
- Render a **focused subgraph**: the active cluster + 1-hop neighbours + a capped sample (≤ 300) of background nodes, dimmed. Never render all 2,000 nodes live.
- Node color by risk (blue calm → yellow → red), size by volume, frozen = ice-blue. Directional particles on links show money flow; link width by amount.
- **Click a node →** camera flies to it and the right panel shows the account detail shape (master 8.6) plus a recent-transaction list and its cluster typology/summary text.
- Click cluster in feed → camera fly + highlight only that ring.
- Toggle for 2D fallback (`react-force-graph-2d`) if the GPU struggles.
- Live updates via `/ws/dashboard` (`tx_batch` every ~500 ms, `cluster_alert`, `pi_ack`, `frozen`).

**Login page:** shows "Scan your finger on the desk", opens `/ws/auth/{challenge_id}`, auto-redirects on `login_ok`; also a small "Use password" form (fallback).

**Metrics page:** table (precision/recall/F1 × baseline vs ours), line chart F1-vs-difficulty, latency, ₹ prevented. Note "synthetic data" on the page.

## 9. Backend behaviours that must be exact

- Alert created ⇒ persist cluster + alert ⇒ generate summary text ⇒ TTS wav saved as `static/audio/{cluster_id}.wav` ⇒ THEN push `alert` to `/ws/pi` (wav must exist before the Pi downloads it).
- Summary text ≤ ~45 words (~15–20 s of speech), ends with: "Log in to the dashboard for linked accounts." Example template: "{Level} alert. {n} accounts moved {amount} in {span}, matching {typology}. Money entered through {source} and left through {destination}. Risk {score} percent."
- Pi `ack` events and officer login/freeze events go into the audit log (SHA-256 chain: each entry stores `prev_hash` and `hash = sha256(prev_hash + payload)`). Provide `GET /api/audit` and a verify function.
- If no `explain_*` ack within `listen_seconds + 5`, send `{"type":"escalate"}` to the Pi.
- Freeze: JWT required; mark accounts frozen; subsequent simulated tx from frozen accounts are blocked and counted as ₹ prevented; send `clear` to the Pi; broadcast `frozen`.
- Mutating Pi/auth endpoints require valid HMAC (`X-Signature`).

## 10. Prompting plan for Antigravity/Gemini (practical)

- Start every agent session by giving it all three context files.
- Ask for **one milestone at a time**; end each prompt with "run it and show me the output".
- Ask it to write `scripts/evaluate.py` early and show the table; fix weak spots before building UI.
- Use a second model/pass only for review (look for: timestamp bugs, window eviction, off-by-one in cycle detection, leakage between train/test seeds).
- Keep a small `NOTES.md` of decisions so a fresh agent session regains context.

## 11. Definition of done (your checklist)

- [x] Mock backend delivered in hour 1, Person 2 unblocked (M0)
- [x] Simulator & attack generators (M1)
- [x] Sliding window, pattern detectors & clustering (M2)
- [x] XGBoost model, baseline models & evaluation pipeline (M3)
- [ ] All 5 attack types launchable at difficulty 1–5 from the UI
- [ ] Held-out metrics table + F1-vs-difficulty chart generated by `evaluate.py` and shown on `/metrics`
- [ ] Real alert reaches the Pi with a valid wav (hour 8 sync)
- [ ] 3D graph: click any node → detail panel; click cluster → fly + highlight
- [x] Compliance officer session & role-based freeze
- [ ] Freeze works, `clear` reaches Pi, ₹ prevented shown
- [ ] Audit chain verifies
- [ ] Three full dry runs of the demo script (master section 12) with the real hardware
- [ ] Backup screen recording saved

## 12. Honest risks (watch these)

- Cycle search can explode: cap starts/depth, run detection on a tick (e.g. every 1–2 s wall-clock), not per transaction.
- Train/test leakage: different seeds, and difficulty 4–5 never in training.
- Over-polished hardware, weak metrics: metrics are what protect you if another team also has a good demo.
- Don't claim "real-time at bank scale". Say "streaming prototype on synthetic data".
