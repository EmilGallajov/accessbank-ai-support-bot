"""SQLite-backed case storage with full lifecycle history.

Tables: cases, case_history, pending_issues.
Case IDs follow the format AB-YYYY-NNNN (zero-padded, monotonically increasing).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from . import config

_lock = threading.Lock()
_initialized = False


SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  user_name TEXT,
  department TEXT NOT NULL,
  language TEXT,
  issue_summary TEXT NOT NULL,
  details TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  resolution TEXT,
  email_message_id TEXT,
  email_thread_id TEXT,
  email_to TEXT,
  attachments TEXT,  -- JSON array of filesystem paths for screenshots/files
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_cases_user ON cases(user_id);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_email_msg ON cases(email_message_id);
CREATE INDEX IF NOT EXISTS idx_cases_email_thread ON cases(email_thread_id);

CREATE TABLE IF NOT EXISTS case_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL,
  source TEXT,
  action TEXT,
  from_status TEXT,
  to_status TEXT,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY(case_id) REFERENCES cases(case_id)
);

CREATE INDEX IF NOT EXISTS idx_history_case ON case_history(case_id);

CREATE TABLE IF NOT EXISTS pending_issues (
  user_id TEXT PRIMARY KEY,
  partial_json TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(config.CASES_DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init() -> None:
    global _initialized
    if _initialized:
        return
    with _lock, _conn() as c:
        c.executescript(SCHEMA)
        # Backwards-compat: older DBs may not have the `attachments` column yet.
        cur = c.execute("PRAGMA table_info(cases)")
        existing_cols = {row["name"] for row in cur.fetchall()}
        if "attachments" not in existing_cols:
            c.execute("ALTER TABLE cases ADD COLUMN attachments TEXT")
        _initialized = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%fZ")[:-3] + "Z"


def _next_case_id() -> str:
    """Generate the next AB-YYYY-NNNN identifier atomically."""
    year = datetime.now(timezone.utc).year
    counter_name = f"case_seq_{year}"
    with _lock, _conn() as c:
        cur = c.execute("SELECT value FROM counters WHERE name = ?", (counter_name,))
        row = cur.fetchone()
        if row is None:
            c.execute("INSERT INTO counters(name, value) VALUES(?, 1)", (counter_name,))
            seq = 1
        else:
            seq = int(row["value"]) + 1
            c.execute("UPDATE counters SET value = ? WHERE name = ?", (seq, counter_name))
    return f"AB-{year}-{seq:04d}"


def add_history(
    case_id: str,
    *,
    source: str,
    action: str,
    from_status: str | None = None,
    to_status: str | None = None,
    note: str | None = None,
) -> None:
    init()
    with _conn() as c:
        c.execute(
            """INSERT INTO case_history
                 (case_id, source, action, from_status, to_status, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (case_id, source, action, from_status, to_status, note),
        )


def create_case(
    *,
    user_id: str,
    user_name: str | None,
    department: str,
    language: str | None,
    issue_summary: str,
    details: str | None,
    attachments: list[str] | None = None,
) -> str:
    """Create a new case in `open` status and return its case_id."""
    init()
    case_id = _next_case_id()
    att_json = json.dumps(attachments) if attachments else None
    with _conn() as c:
        c.execute(
            """INSERT INTO cases
                 (case_id, user_id, user_name, department, language,
                  issue_summary, details, status, attachments)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (case_id, user_id, user_name, department, language, issue_summary, details, att_json),
        )
    note = f"Routed to {department}"
    if attachments:
        note += f" with {len(attachments)} attachment(s)"
    add_history(
        case_id,
        source="agent",
        action="created",
        to_status="open",
        note=note,
    )
    return case_id


def attach_email(case_id: str, *, message_id: str, thread_id: str, to_addr: str) -> None:
    init()
    with _conn() as c:
        c.execute(
            """UPDATE cases
                 SET email_message_id = ?, email_thread_id = ?, email_to = ?,
                     updated_at = ?
               WHERE case_id = ?""",
            (message_id, thread_id, to_addr, _now_iso(), case_id),
        )
    add_history(
        case_id,
        source="agent",
        action="email_sent",
        note=f"Escalation emailed to {to_addr} (msg {message_id})",
    )


def get_case(case_id: str) -> dict[str, Any] | None:
    init()
    with _conn() as c:
        cur = c.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def list_user_cases(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    init()
    with _conn() as c:
        cur = c.execute(
            "SELECT * FROM cases WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def find_by_email_thread(thread_id: str) -> dict[str, Any] | None:
    init()
    with _conn() as c:
        cur = c.execute(
            "SELECT * FROM cases WHERE email_thread_id = ? ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def update_status(
    case_id: str,
    *,
    new_status: str,
    source: str,
    note: str | None = None,
    resolution: str | None = None,
) -> tuple[str, str]:
    """Move a case to a new status. Returns (old_status, new_status)."""
    init()
    with _conn() as c:
        cur = c.execute("SELECT status FROM cases WHERE case_id = ?", (case_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Unknown case {case_id}")
        old_status = row["status"]
        if old_status == new_status and not resolution:
            return old_status, new_status

        if resolution is not None:
            c.execute(
                """UPDATE cases
                     SET status = ?, resolution = ?, updated_at = ?
                   WHERE case_id = ?""",
                (new_status, resolution, _now_iso(), case_id),
            )
        else:
            c.execute(
                "UPDATE cases SET status = ?, updated_at = ? WHERE case_id = ?",
                (new_status, _now_iso(), case_id),
            )
    add_history(
        case_id,
        source=source,
        action="status_change",
        from_status=old_status,
        to_status=new_status,
        note=note,
    )
    return old_status, new_status


def find_latest_resolved_for_user(user_id: str) -> dict[str, Any] | None:
    """Return the user's most recently resolved (but not yet closed) case, or None."""
    init()
    with _conn() as c:
        cur = c.execute(
            """SELECT * FROM cases
                 WHERE user_id = ? AND status = 'resolved'
                 ORDER BY updated_at DESC LIMIT 1""",
            (user_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


# ---- pending_issues (mid-conversation state for incomplete issue reports) ----

def get_pending(user_id: str) -> dict[str, Any] | None:
    init()
    with _conn() as c:
        cur = c.execute(
            "SELECT partial_json FROM pending_issues WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
    if not row:
        return None
    try:
        return json.loads(row["partial_json"])
    except Exception:
        return None


def set_pending(user_id: str, data: dict[str, Any]) -> None:
    init()
    payload = json.dumps(data, ensure_ascii=False)
    with _conn() as c:
        c.execute(
            """INSERT INTO pending_issues(user_id, partial_json, updated_at)
                 VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 partial_json = excluded.partial_json,
                 updated_at = excluded.updated_at""",
            (user_id, payload, _now_iso()),
        )


def clear_pending(user_id: str) -> None:
    init()
    with _conn() as c:
        c.execute("DELETE FROM pending_issues WHERE user_id = ?", (user_id,))
