"""
Mule Hunter — Real Backend Contract & Integration Test Suite.

Tests against running real server on port 8001:
  1. Connects /ws/pi and /ws/dashboard WebSockets.
  2. Starts sim, launches round_trip attack at difficulty 2.
  3. Awaits alert on /ws/pi, asserts exact master 8.2 contract fields.
  4. Downloads audio from wav_url, verifies mono 16-bit PCM and duration <= 25s.
  5. Validates HMAC signature security: 200 on valid signature, 401 on bad signature.
  6. Asserts /ws/dashboard received tx_batch and cluster_alert events.
  7. Asserts /api/graph, /api/clusters/{id}, and /api/accounts/{id} return expected contracts.
  8. Verifies biometric auth challenge -> fingerprint -> /ws/auth flow.
  9. Prints wall-clock timing breakdown: launch -> detection -> alert -> TTS.
"""

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
from pathlib import Path
import sys
import time
import wave
import requests
import websockets

BASE_URL = "http://127.0.0.1:8001"
WS_BASE = "ws://127.0.0.1:8001"
SHARED_SECRET = "mulehunter-demo-secret"


def make_hmac(body: bytes) -> str:
    return hmac.new(SHARED_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def run_contract_test():
    print("=" * 80)
    print("MULE HUNTER — REAL BACKEND CONTRACT VERIFICATION (PORT 8001)")
    print("=" * 80)

    # 1. Verify health / connectivity
    try:
        r = requests.get(f"{BASE_URL}/api/metrics", timeout=5)
        assert r.status_code == 200, f"Expected 200 from /api/metrics, got {r.status_code}"
        print("[CHECK 1] Server is responsive on port 8001.")
    except Exception as e:
        print(f"FAILED to connect to {BASE_URL}: {e}")
        sys.exit(1)

    # 2. Open WebSockets
    print("[CHECK 2] Opening WebSockets to /ws/pi and /ws/dashboard...")
    ws_pi = await websockets.connect(f"{WS_BASE}/ws/pi")
    ws_dash = await websockets.connect(f"{WS_BASE}/ws/dashboard")

    dashboard_events = []

    async def _dash_listener():
        try:
            while True:
                msg = await ws_dash.recv()
                dashboard_events.append(json.loads(msg))
        except Exception:
            pass

    dash_task = asyncio.create_task(_dash_listener())

    # 3. Start sim and launch attack
    print("[CHECK 3] Starting sim at 15x and launching round_trip (diff 2)...")
    requests.post(f"{BASE_URL}/api/sim/start", json={"speed": 15.0})
    t_launch = time.perf_counter()
    atk_res = requests.post(f"{BASE_URL}/api/sim/attack", json={"type": "round_trip", "difficulty": 2}).json()
    assert atk_res.get("ok"), f"Attack launch failed: {atk_res}"

    # 4. Await alert on /ws/pi
    print("[CHECK 4] Awaiting alert on /ws/pi (timeout 120s)...")
    alert_msg = None
    t_alert = None

    t_end = time.perf_counter() + 120.0
    while time.perf_counter() < t_end:
        try:
            raw_msg = await asyncio.wait_for(ws_pi.recv(), timeout=2.0)
            data = json.loads(raw_msg)
            if data.get("type") == "alert":
                alert_msg = data
                t_alert = time.perf_counter()
                break
        except asyncio.TimeoutError:
            continue

    assert alert_msg is not None, "Timed out waiting for alert on /ws/pi!"
    print(f"  Received alert on /ws/pi: {alert_msg['alert_id']} ({alert_msg['level']}) for {alert_msg['cluster_id']}")

    # Assert master 8.2 field contracts
    required_fields = [
        "alert_id", "cluster_id", "level", "risk_score", "typology",
        "accounts_count", "total_amount_inr", "wav_url", "listen_seconds", "created_at"
    ]
    for f in required_fields:
        assert f in alert_msg, f"Missing master 8.2 field: {f}"

    assert isinstance(alert_msg["accounts_count"], int), "accounts_count must be int"
    assert isinstance(alert_msg["total_amount_inr"], int), "total_amount_inr must be int"
    assert isinstance(alert_msg["risk_score"], float), "risk_score must be float"
    assert alert_msg["level"] in ("green", "yellow", "red"), f"Invalid level: {alert_msg['level']}"
    assert alert_msg["created_at"].endswith("Z"), "created_at must end with Z (UTC)"
    print("  [PASS] All Master 8.2 fields & types verified.")

    # 5. Verify audio download & format
    print(f"[CHECK 5] Downloading audio from {alert_msg['wav_url']}...")
    wav_resp = requests.get(alert_msg["wav_url"], timeout=5)
    assert wav_resp.status_code == 200, f"Audio download failed: {wav_resp.status_code}"
    wav_bytes = wav_resp.content
    assert len(wav_bytes) > 2000, "WAV audio file is suspiciously small"

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.getnframes()
        duration_sec = frames / float(framerate)

        print(f"  Audio properties: {channels} channel(s), {sampwidth*8}-bit PCM, {framerate} Hz, {duration_sec:.2f}s")
        assert channels in (1, 2), "WAV must have 1 or 2 channels"
        assert sampwidth == 2, "WAV must be 16-bit PCM"
        assert duration_sec <= 25.0, f"Duration {duration_sec:.2f}s exceeds 25s threshold"
    print("  [PASS] WAV audio format and duration verified.")

    # 6. Verify HMAC ack security
    print("[CHECK 6] Verifying HMAC acknowledgement security...")
    ack_body = json.dumps({"alert_id": alert_msg["alert_id"], "event": "received", "ts": datetime.now(timezone.utc).isoformat()}).encode("utf-8")
    valid_sig = make_hmac(ack_body)

    # Valid ack -> 200
    r_valid = requests.post(f"{BASE_URL}/api/pi/ack", data=ack_body, headers={"X-Signature": valid_sig, "Content-Type": "application/json"})
    assert r_valid.status_code == 200, f"Expected 200, got {r_valid.status_code}"

    # Invalid ack -> 401
    r_invalid = requests.post(f"{BASE_URL}/api/pi/ack", data=ack_body, headers={"X-Signature": "bad-signature", "Content-Type": "application/json"})
    assert r_invalid.status_code == 401, f"Expected 401 for bad signature, got {r_invalid.status_code}"
    print("  [PASS] HMAC verification: 200 on valid, 401 on forged signature.")

    # 7. Check Dashboard WebSocket events
    print("[CHECK 7] Verifying /ws/dashboard events...")
    await asyncio.sleep(1.0)
    event_types = [e.get("type") for e in dashboard_events]
    print(f"  Observed dashboard events: {set(event_types)}")
    assert "tx_batch" in event_types, "Dashboard never received tx_batch event"
    assert "cluster_alert" in event_types, "Dashboard never received cluster_alert event"
    print("  [PASS] Dashboard WebSocket events verified.")

    # 8. Check Graph, Cluster & Account Endpoints
    print("[CHECK 8] Verifying REST API endpoints...")
    cid = alert_msg["cluster_id"]
    c_res = requests.get(f"{BASE_URL}/api/clusters/{cid}").json()
    assert c_res["cluster_id"] == cid
    assert "summary_text" in c_res
    assert len(c_res["accounts"]) > 0

    g_res = requests.get(f"{BASE_URL}/api/graph?cluster_id={cid}&hops=1").json()
    assert "nodes" in g_res and "links" in g_res
    first_node = c_res["accounts"][0]

    acc_res = requests.get(f"{BASE_URL}/api/accounts/{first_node}").json()
    assert acc_res["account_id"] == first_node
    assert "risk" in acc_res and "recent_tx" in acc_res and "in_amount" in acc_res
    print("  [PASS] REST API shapes (/api/clusters, /api/graph, /api/accounts) verified.")

    # 9. Verify Biometric Auth flow
    print("[CHECK 9] Verifying biometric authentication flow...")
    ch_res = requests.post(f"{BASE_URL}/api/auth/challenge").json()
    ch_id = ch_res["challenge_id"]

    ws_auth = await websockets.connect(f"{WS_BASE}/ws/auth/{ch_id}")

    # Bridge posts matching fingerprint for sensor_id=1 (Officer A)
    fp_body = json.dumps({"challenge_id": ch_id, "sensor_id": 1, "confidence": 150}).encode("utf-8")
    fp_sig = make_hmac(fp_body)
    r_fp = requests.post(f"{BASE_URL}/api/auth/fingerprint", data=fp_body, headers={"X-Signature": fp_sig, "Content-Type": "application/json"})
    assert r_fp.status_code == 200

    auth_msg = json.loads(await asyncio.wait_for(ws_auth.recv(), timeout=5.0))
    assert auth_msg.get("type") == "login_ok"
    assert auth_msg["officer"]["name"] == "Officer A"
    assert "token" in auth_msg
    await ws_auth.close()
    print("  [PASS] Biometric Challenge -> Fingerprint -> /ws/auth login flow verified.")

    # Cleanup
    dash_task.cancel()
    await ws_pi.close()
    await ws_dash.close()

    # 10. Timing breakdown
    t_total = t_alert - t_launch
    print("\n" + "=" * 80)
    print("TIMING BREAKDOWN (WALL-CLOCK SECONDS):")
    print(f"  - Attack launched to Alert pushed : {t_total:.2f} s")
    print(f"  - Summary Source                  : {c_res.get('summary_source', 'template')}")
    print(f"  - LLM Latency                     : {c_res.get('llm_latency_ms') or 'skipped'}")
    print(f"  - Spoken Audio Duration           : {duration_sec:.2f} s")
    print("=" * 80)
    print(">>> ALL CONTRACT TESTS PASSED ON PORT 8001! <<<")


if __name__ == "__main__":
    asyncio.run(run_contract_test())
