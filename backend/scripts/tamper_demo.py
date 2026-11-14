"""
Mule Hunter — Audit Log Tamper Demonstration.

1. Verifies the audit chain is initially valid (verify_audit() -> ok=True).
2. Tampering: directly alters a database row in audit_log.
3. Verifies that verify_audit() immediately catches the tampering (ok=False)
   and pinpoints the first bad index.
4. Restores or resets the state.
"""

import json
import sqlite3
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.audit import append_audit, clear_audit, verify_audit, DB_PATH


def run_tamper_demo():
    print("=" * 80)
    print("MULE HUNTER — AUDIT LOG TAMPER DEMONSTRATION")
    print("=" * 80)

    # 1. Start with fresh audit log and insert known entries
    clear_audit()
    print("[1] Seeded 4 sample audit events:")
    append_audit("login_ok", {"method": "password", "officer": "O-1"})
    append_audit("alert_created", {"alert_id": "A-0001", "level": "yellow", "amount": 500000})
    append_audit("pi_ack", {"alert_id": "A-0001", "event": "explain_voice"})
    append_audit("freeze", {"cluster_id": "C-0001", "officer": "O-1", "prevented_inr": 250000})

    # 2. Verify audit chain before tampering
    res_before = verify_audit()
    print(f"[2] Verification BEFORE tampering: ok={res_before['ok']}, entries={res_before['entries']}, first_bad_index={res_before['first_bad_index']}")
    assert res_before["ok"] is True, "Audit log verification failed before tampering!"

    # 3. Direct DB Tampering: modify payload of row 2 (e.g. reduce prevented_inr or change alert level)
    print("\n[3] Tampering: An attacker opens SQLite directly and modifies row #2's payload...")
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT id, payload_json FROM audit_log ORDER BY id ASC")
    rows = cur.fetchall()
    target_id, target_payload = rows[1]  # second row
    data = json.loads(target_payload)
    data["amount"] = 50  # Altered 500,000 to 50
    tampered_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    cur.execute("UPDATE audit_log SET payload_json = ? WHERE id = ?", (tampered_json, target_id))
    conn.commit()
    conn.close()
    print(f"    Modified row {target_id} payload to: {tampered_json}")

    # 4. Verify audit chain after tampering
    res_after = verify_audit()
    print(f"\n[4] Verification AFTER tampering: ok={res_after['ok']}, entries={res_after['entries']}, first_bad_index={res_after['first_bad_index']}")
    assert res_after["ok"] is False, "Audit log failed to detect tampering!"
    assert res_after["first_bad_index"] == 1, f"Expected bad index 1, got {res_after['first_bad_index']}"

    print("\n>>> TAMPER DETECTION CONFIRMED: SHA-256 chain successfully broke at row index 1! <<<")
    print("=" * 80)
    return True


if __name__ == "__main__":
    run_tamper_demo()
