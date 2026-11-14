"""
Audit log functions: hash-chained tamper-evident log.

Each entry: hash = sha256(prev_hash + canonical_json_payload)
Events logged: alert_created, pi_ack, escalate, login_ok, login_failed, freeze.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

DB_PATH = backend_dir / "data" / "mulehunter.db"
GENESIS_HASH = "0" * 64  # starting prev_hash for the first entry


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_audit_table():
    """Create audit_log table if not exists."""
    conn = _get_db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type  TEXT    NOT NULL,
        payload_json TEXT   NOT NULL,
        prev_hash   TEXT    NOT NULL,
        hash        TEXT    NOT NULL,
        created_at  TEXT    NOT NULL
    )
    """)
    conn.commit()
    conn.close()


def _canonical(payload: Dict[str, Any]) -> str:
    """Canonical JSON: sorted keys, no extra whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _get_last_hash(cur: sqlite3.Cursor) -> str:
    cur.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    return row["hash"] if row else GENESIS_HASH


def append_audit(event_type: str, payload: Dict[str, Any]) -> str:
    """Append one entry to the audit log. Returns the new entry's hash."""
    init_audit_table()
    conn = _get_db()
    cur = conn.cursor()
    prev_hash = _get_last_hash(cur)
    canon = _canonical(payload)
    new_hash = hashlib.sha256((prev_hash + canon).encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute(
        "INSERT INTO audit_log (event_type, payload_json, prev_hash, hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (event_type, canon, prev_hash, new_hash, now),
    )
    conn.commit()
    conn.close()
    return new_hash


def list_audit(limit: int = 50) -> List[dict]:
    """Return most recent audit entries (oldest first within the page)."""
    init_audit_table()
    conn = _get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, event_type, payload_json, prev_hash, hash, created_at FROM audit_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = [
        {
            "id": r["id"],
            "event_type": r["event_type"],
            "payload": json.loads(r["payload_json"]),
            "prev_hash": r["prev_hash"],
            "hash": r["hash"],
            "created_at": r["created_at"],
        }
        for r in cur.fetchall()
    ]
    conn.close()
    return list(reversed(rows))  # oldest first


def verify_audit() -> Dict[str, Any]:
    """Verify the entire audit chain. Returns ok, entries count, first_bad_index."""
    init_audit_table()
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, payload_json, prev_hash, hash FROM audit_log ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()

    expected_prev = GENESIS_HASH
    for idx, row in enumerate(rows):
        # Verify prev_hash chain
        if row["prev_hash"] != expected_prev:
            return {"ok": False, "entries": len(rows), "first_bad_index": idx}
        # Verify hash
        recomputed = hashlib.sha256((row["prev_hash"] + row["payload_json"]).encode("utf-8")).hexdigest()
        if recomputed != row["hash"]:
            return {"ok": False, "entries": len(rows), "first_bad_index": idx}
        expected_prev = row["hash"]

    return {"ok": True, "entries": len(rows), "first_bad_index": None}


def clear_audit():
    """Clears audit log on simulation reset."""
    init_audit_table()
    conn = _get_db()
    conn.execute("DELETE FROM audit_log")
    conn.commit()
    conn.close()
