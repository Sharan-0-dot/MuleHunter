"""
SQLite database persistence for Mule Hunter backend.

Schema:
  - alerts: alert history with typology, risk, amounts, summary provenance, and audio URLs.
  - clusters: tracked cluster snapshots, accounts list, features, summary text.
  - alert_tx: transactions internal to the cluster in the window at alert time (ensures account details survive window eviction).
  - officers: hardware fingerprint mappings (sensor_id -> officer).
  - pi_events: audit trail of acknowledgement events from Raspberry Pi.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Dict, List, Optional, Set, Tuple

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

DB_PATH = backend_dir / "data" / "mulehunter.db"


def get_db_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes tables, seeds hardware officer credentials, and creates audit table."""
    from app.audit import init_audit_table
    init_audit_table()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        alert_id TEXT PRIMARY KEY,
        cluster_id TEXT NOT NULL,
        level TEXT NOT NULL,
        risk_score REAL NOT NULL,
        typology TEXT NOT NULL,
        accounts_count INTEGER NOT NULL,
        total_amount_inr INTEGER NOT NULL,
        wav_url TEXT NOT NULL,
        listen_seconds INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        summary_source TEXT NOT NULL,
        llm_latency_ms REAL,
        tts_fallback INTEGER NOT NULL DEFAULT 0
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clusters (
        cluster_id TEXT PRIMARY KEY,
        accounts_json TEXT NOT NULL,
        features_json TEXT NOT NULL,
        risk_score REAL NOT NULL,
        level TEXT NOT NULL,
        typology TEXT NOT NULL,
        summary_text TEXT NOT NULL,
        summary_source TEXT NOT NULL,
        audio_path TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS alert_tx (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id TEXT NOT NULL,
        tx_id TEXT NOT NULL,
        ts TEXT NOT NULL,
        src TEXT NOT NULL,
        dst TEXT NOT NULL,
        amount REAL NOT NULL,
        kind TEXT NOT NULL,
        FOREIGN KEY(alert_id) REFERENCES alerts(alert_id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS officers (
        sensor_id INTEGER PRIMARY KEY,
        officer_id TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pi_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id TEXT NOT NULL,
        event TEXT NOT NULL,
        ts TEXT NOT NULL,
        received_at TEXT NOT NULL
    );
    """)

    # Seed hardware fingerprint mappings per 00_MASTER.md section 8.4:
    # 1,2 -> Officer A (O-1), 3,4 -> Officer B (O-2), 5 -> Admin (O-3)
    officer_seeds = [
        (1, "O-1", "Officer A", "officer"),
        (2, "O-1", "Officer A", "officer"),
        (3, "O-2", "Officer B", "officer"),
        (4, "O-2", "Officer B", "officer"),
        (5, "O-3", "Admin", "admin"),
    ]
    cur.executemany("""
    INSERT OR REPLACE INTO officers (sensor_id, officer_id, name, role)
    VALUES (?, ?, ?, ?)
    """, officer_seeds)

    conn.commit()
    conn.close()


def get_max_alert_id() -> int:
    """Returns the highest numerical alert ID in the database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT alert_id FROM alerts")
    rows = cur.fetchall()
    conn.close()
    max_id = 0
    for r in rows:
        try:
            aid = r["alert_id"]
            if aid.startswith("A-"):
                num = int(aid[2:])
                if num > max_id:
                    max_id = num
        except Exception:
            pass
    return max_id


def clear_db():
    """Clears alerts and cluster history on simulation reset."""
    from app.audit import clear_audit
    clear_audit()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM alerts")
    cur.execute("DELETE FROM clusters")
    cur.execute("DELETE FROM alert_tx")
    cur.execute("DELETE FROM pi_events")
    conn.commit()
    conn.close()


def save_cluster_and_alert(
    alert_dict: dict,
    cluster_obj,
    summary_text: str,
    summary_source: str,
    audio_path: str,
    llm_latency_ms: Optional[float] = None,
    tts_fallback: bool = False,
    window_txs: Optional[List] = None,
):
    """
    Atomically persists cluster, alert, and cluster transactions into SQLite.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Upsert cluster
    accounts_json = json.dumps(list(cluster_obj.accounts))
    features_json = json.dumps(getattr(cluster_obj, "features", {}))

    cur.execute("""
    INSERT INTO clusters (
        cluster_id, accounts_json, features_json, risk_score, level,
        typology, summary_text, summary_source, audio_path, first_seen, last_seen
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(cluster_id) DO UPDATE SET
        accounts_json = excluded.accounts_json,
        features_json = excluded.features_json,
        risk_score = excluded.risk_score,
        level = excluded.level,
        typology = excluded.typology,
        summary_text = excluded.summary_text,
        summary_source = excluded.summary_source,
        audio_path = excluded.audio_path,
        last_seen = excluded.last_seen;
    """, (
        cluster_obj.cluster_id,
        accounts_json,
        features_json,
        alert_dict["risk_score"],
        alert_dict["level"],
        alert_dict["typology"],
        summary_text,
        summary_source,
        str(audio_path),
        now_iso,
        now_iso,
    ))

    # Insert alert
    cur.execute("""
    INSERT OR REPLACE INTO alerts (
        alert_id, cluster_id, level, risk_score, typology,
        accounts_count, total_amount_inr, wav_url, listen_seconds,
        created_at, summary_source, llm_latency_ms, tts_fallback
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        alert_dict["alert_id"],
        alert_dict["cluster_id"],
        alert_dict["level"],
        alert_dict["risk_score"],
        alert_dict["typology"],
        alert_dict["accounts_count"],
        alert_dict["total_amount_inr"],
        alert_dict["wav_url"],
        alert_dict["listen_seconds"],
        alert_dict["created_at"],
        summary_source,
        llm_latency_ms,
        1 if tts_fallback else 0,
    ))

    # Store associated transactions from the window
    if window_txs:
        c_accs = cluster_obj.accounts
        tx_rows = [
            (
                alert_dict["alert_id"],
                t.tx_id,
                t.ts.isoformat(),
                t.src,
                t.dst,
                t.amount,
                t.kind,
            )
            for t in window_txs
            if t.src in c_accs or t.dst in c_accs
        ]
        if tx_rows:
            cur.executemany("""
            INSERT INTO alert_tx (alert_id, tx_id, ts, src, dst, amount, kind)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, tx_rows)

    conn.commit()
    conn.close()


def record_pi_ack(alert_id: str, event: str, ts: str):
    """Stores acknowledgement event from Raspberry Pi."""
    conn = get_db_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("""
    INSERT INTO pi_events (alert_id, event, ts, received_at)
    VALUES (?, ?, ?, ?)
    """, (alert_id, event, ts, now_iso))
    conn.commit()
    conn.close()


def get_officer_by_sensor_id(sensor_id: int) -> Optional[dict]:
    """Look up officer by enrolled fingerprint sensor ID."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT officer_id, name, role FROM officers WHERE sensor_id = ?", (sensor_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"id": row["officer_id"], "name": row["name"], "role": row["role"]}
    return None


def get_cluster_detail(cluster_id: str) -> Optional[dict]:
    """Returns cluster metadata, summary, accounts, and audit timeline."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clusters WHERE cluster_id = ?", (cluster_id,))
    c_row = cur.fetchone()
    if not c_row:
        conn.close()
        return None

    # Get alerts timeline
    cur.execute("SELECT * FROM alerts WHERE cluster_id = ? ORDER BY created_at ASC", (cluster_id,))
    alerts = [dict(r) for r in cur.fetchall()]

    # Get Pi events for this cluster's alerts
    alert_ids = [a["alert_id"] for a in alerts]
    pi_events = []
    if alert_ids:
        placeholders = ",".join("?" for _ in alert_ids)
        cur.execute(f"SELECT * FROM pi_events WHERE alert_id IN ({placeholders}) ORDER BY ts ASC", alert_ids)
        pi_events = [dict(r) for r in cur.fetchall()]

    conn.close()

    res = dict(c_row)
    res["accounts"] = json.loads(res["accounts_json"])
    res["features"] = json.loads(res["features_json"])
    del res["accounts_json"]
    del res["features_json"]

    # Expose p and exposure as risk_components per Step 2
    prob = res["features"].get("probability", res["risk_score"])
    exposure = res["features"].get(
        "exposure", min(1.0, float(res["features"].get("total_amount", 0.0)) / 2_500_000.0)
    )
    res["risk_components"] = {"probability": round(prob, 4), "exposure": round(exposure, 4)}

    res["alerts"] = alerts
    res["pi_events"] = pi_events
    return res


def list_clusters() -> List[dict]:
    """Returns list of all recorded clusters."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT cluster_id, risk_score, level, typology, summary_text, first_seen, last_seen FROM clusters ORDER BY risk_score DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_account_historical_txs(account_id: str) -> List[dict]:
    """Returns transactions involving account_id saved in alert_tx."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT DISTINCT tx_id, ts, src, dst, amount, kind
    FROM alert_tx
    WHERE src = ? OR dst = ?
    ORDER BY ts DESC
    LIMIT 20
    """, (account_id, account_id))
    rows = [
        {"from": r["src"], "to": r["dst"], "amount": r["amount"], "ts": r["ts"]}
        for r in cur.fetchall()
    ]
    conn.close()
    return rows
