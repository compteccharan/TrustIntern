"""SQLite persistence for investigation reports."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

# Vercel functions can write only under /tmp, and that disk is ephemeral.
if os.environ.get("VERCEL"):
    DATA_DIR = Path("/tmp/trustintern-data")
else:
    DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "trustintern.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS investigations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                score INTEGER NOT NULL,
                risk_level TEXT NOT NULL,
                report_json TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_report(report: dict[str, Any]) -> dict[str, Any]:
    init_db()
    created_at = report["created_at"]
    score = report["score"]
    risk_level = report["risk_level"]
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO investigations (created_at, score, risk_level, report_json)
            VALUES (?, ?, ?, ?)
            """,
            (created_at, score, risk_level, json.dumps(report)),
        )
        report_id = int(cur.lastrowid)
        report = dict(report)
        report["id"] = report_id
        conn.execute(
            "UPDATE investigations SET report_json = ? WHERE id = ?",
            (json.dumps(report), report_id),
        )
        conn.commit()
    return report


def list_reports() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT report_json FROM investigations ORDER BY id DESC"
        ).fetchall()
    return [json.loads(r["report_json"]) for r in rows]


def get_report(report_id: int) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT report_json FROM investigations WHERE id = ?",
            (report_id,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["report_json"])
