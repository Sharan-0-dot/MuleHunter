import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
import requests
import websockets

# Load env from backend/.env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

SHARED_SECRET = os.getenv("SHARED_SECRET", "mulehunter-demo-secret")
PORT = int(os.getenv("PORT", "8000"))
BASE_HTTP = f"http://127.0.0.1:{PORT}"
BASE_WS = f"ws://127.0.0.1:{PORT}"


def sign_payload(body_bytes: bytes) -> str:
    return hmac.new(SHARED_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


async def run_tests():
    print("=" * 60)
    print("MULE HUNTER — MOCK BACKEND VERIFICATION SUITE")
    print("=" * 60)

    # 1. Test /ws/pi and /mock/trigger
    print("\n[TEST 1] Testing /ws/pi and /mock/trigger?level=red...")
    async with websockets.connect(f"{BASE_WS}/ws/pi") as ws_pi:
        # Trigger an alert via HTTP
        resp = requests.post(f"{BASE_HTTP}/mock/trigger?level=red")
        assert resp.status_code == 200, f"Trigger failed: {resp.status_code} {resp.text}"
        trigger_res = resp.json()
        print(f"Trigger response: recipients={trigger_res.get('recipients')}")

        # Receive alert over WebSocket
        msg_text = await asyncio.wait_for(ws_pi.recv(), timeout=5.0)
        alert = json.loads(msg_text)
        print("Received alert over /ws/pi:")
        print(json.dumps(alert, indent=2))

        assert alert.get("type") == "alert"
        assert alert.get("level") == "red"
        assert alert.get("risk_score") == 0.91
        assert alert.get("typology") == "round_tripping"
        assert alert.get("accounts_count") == 7
        assert alert.get("total_amount_inr") == 420000
        wav_url = alert.get("wav_url")
        print(f"Alert wav_url: {wav_url}")

        # 2. Test downloading wav_url
        print("\n[TEST 2] Downloading wav file from wav_url...")
        wav_resp = requests.get(wav_url, timeout=5)
        assert wav_resp.status_code == 200, f"Failed to download wav: {wav_resp.status_code}"
        print(f"Successfully downloaded wav. Size: {len(wav_resp.content):,} bytes")

        # 3. Test correctly signed /api/pi/ack
        print("\n[TEST 3] Testing valid HMAC /api/pi/ack...")
        ack_body = json.dumps({
            "alert_id": alert["alert_id"],
            "event": "received",
            "ts": "2026-11-15T10:42:12Z"
        }).encode("utf-8")
        sig = sign_payload(ack_body)
        ack_resp = requests.post(
            f"{BASE_HTTP}/api/pi/ack",
            data=ack_body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
            timeout=5
        )
        assert ack_resp.status_code == 200, f"Valid ack rejected: {ack_resp.status_code} {ack_resp.text}"
        assert ack_resp.json().get("ok") is True
        print(f"Valid ack accepted: {ack_resp.json()}")

        # 4. Test invalid HMAC /api/pi/ack
        print("\n[TEST 4] Testing invalid HMAC /api/pi/ack (expecting 401)...")
        bad_resp = requests.post(
            f"{BASE_HTTP}/api/pi/ack",
            data=ack_body,
            headers={"X-Signature": "wrong-signature-hex", "Content-Type": "application/json"},
            timeout=5
        )
        assert bad_resp.status_code == 401, f"Expected 401 but got {bad_resp.status_code}"
        print(f"Invalid ack rejected properly: 401 {bad_resp.json()}")

    # 5. Test Challenge -> Fingerprint -> /ws/auth flow
    print("\n[TEST 5] Testing Challenge -> Fingerprint -> /ws/auth flow...")
    ch_resp = requests.post(f"{BASE_HTTP}/api/auth/challenge", timeout=5)
    assert ch_resp.status_code == 200
    ch_data = ch_resp.json()
    challenge_id = ch_data["challenge_id"]
    print(f"Created challenge: {challenge_id}, expires_at={ch_data['expires_at']}")

    # Verify pending challenge
    pending_resp = requests.get(f"{BASE_HTTP}/api/auth/challenge/pending", timeout=5)
    assert pending_resp.status_code == 200
    assert pending_resp.json().get("challenge_id") == challenge_id
    print(f"Verified pending challenge: {pending_resp.json()}")

    # Connect to /ws/auth/{challenge_id}
    async with websockets.connect(f"{BASE_WS}/ws/auth/{challenge_id}") as ws_auth:
        print(f"Connected to /ws/auth/{challenge_id}")

        # Send fingerprint match for sensor_id=1 (Officer A)
        fp_body = json.dumps({
            "challenge_id": challenge_id,
            "sensor_id": 1,
            "confidence": 142
        }).encode("utf-8")
        fp_sig = sign_payload(fp_body)

        fp_resp = requests.post(
            f"{BASE_HTTP}/api/auth/fingerprint",
            data=fp_body,
            headers={"X-Signature": fp_sig, "Content-Type": "application/json"},
            timeout=5
        )
        assert fp_resp.status_code == 200, f"Fingerprint auth failed: {fp_resp.status_code} {fp_resp.text}"
        print(f"Fingerprint API response: {fp_resp.json()}")

        # Receive WebSocket login_ok event
        auth_msg_raw = await asyncio.wait_for(ws_auth.recv(), timeout=5.0)
        auth_msg = json.loads(auth_msg_raw)
        print("Received auth event on /ws/auth:")
        print(json.dumps(auth_msg, indent=2))
        assert auth_msg.get("type") == "login_ok"
        assert auth_msg.get("officer", {}).get("name") == "Officer A"
        assert "token" in auth_msg

    # 6. Test password fallback
    print("\n[TEST 6] Testing password fallback /api/auth/password...")
    pwd_resp = requests.post(
        f"{BASE_HTTP}/api/auth/password",
        json={"username": "officer", "password": "demo123"},
        timeout=5
    )
    assert pwd_resp.status_code == 200
    pwd_data = pwd_resp.json()
    print(f"Password login response: officer={pwd_data['officer']['name']}, token received")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
