"""SQLite storage: ``raw_messages`` is an append-only journal; ``alerts`` and ``parse_errors`` are
derived from it and can always be rebuilt (``airalert rebuild-alerts``)."""

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_messages(
  channel TEXT NOT NULL,
  msg_id INTEGER NOT NULL,
  posted_at TEXT NOT NULL,
  edited_at TEXT NULL,
  text TEXT NOT NULL,
  received_at TEXT NOT NULL,
  ingest_mode TEXT NOT NULL CHECK (ingest_mode IN ('backfill','live')),
  PRIMARY KEY (channel, msg_id)
);
CREATE TABLE IF NOT EXISTS message_edits(
  channel TEXT NOT NULL,
  msg_id INTEGER NOT NULL,
  edited_at TEXT,
  old_text TEXT,
  new_text TEXT,
  received_at TEXT NOT NULL,
  UNIQUE (channel, msg_id, edited_at)
);
CREATE TABLE IF NOT EXISTS parse_errors(
  channel TEXT NOT NULL,
  msg_id INTEGER,
  posted_at TEXT,
  reason TEXT NOT NULL,
  text TEXT
);
CREATE TABLE IF NOT EXISTS collector_heartbeat(
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_seen_at TEXT NOT NULL,
  last_msg_id INTEGER
);
CREATE TABLE IF NOT EXISTS alerts(
  channel TEXT NOT NULL,
  location TEXT NOT NULL,
  level TEXT NOT NULL CHECK (level IN ('oblast','raion','hromada')),
  raion TEXT NOT NULL DEFAULT '',
  hromada TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  finished_at TEXT NULL,
  start_known_at TEXT NOT NULL,
  end_known_at TEXT NULL,
  source TEXT NOT NULL,
  flags TEXT NOT NULL DEFAULT '',
  start_msg_id INTEGER,
  end_msg_id INTEGER
);
CREATE INDEX IF NOT EXISTS raw_messages_posted ON raw_messages(channel, posted_at);
"""

ALERT_DB_COLUMNS = [
    "channel",
    "location",
    "level",
    "raion",
    "hromada",
    "started_at",
    "finished_at",
    "start_known_at",
    "end_known_at",
    "source",
    "flags",
    "start_msg_id",
    "end_msg_id",
]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def iso(dt: datetime | None) -> str | None:
    """Telethon datetimes are tz-aware UTC; store them as ISO strings with +00:00."""
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class RawMessage:
    channel: str
    msg_id: int
    posted_at: str
    edited_at: str | None
    text: str
    received_at: str
    ingest_mode: str


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    return conn


def insert_messages(conn: sqlite3.Connection, rows: Iterable[RawMessage]) -> int:
    """Idempotent insert; an already stored (channel, msg_id) keeps its first-seen version."""
    with conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO raw_messages VALUES (?,?,?,?,?,?,?)",
            [
                (r.channel, r.msg_id, r.posted_at, r.edited_at, r.text, r.received_at, r.ingest_mode)
                for r in rows
            ],
        )
        return conn.total_changes - before


def record_edit(
    conn: sqlite3.Connection, channel: str, msg_id: int, edited_at: str | None, new_text: str
) -> bool:
    """Log an edit. ``raw_messages.text`` stays as first seen (what was known at ``posted_at``);
    only ``edited_at`` is bumped. Returns True if the edit was new."""
    with conn:
        row = conn.execute(
            "SELECT text FROM raw_messages WHERE channel=? AND msg_id=?", (channel, msg_id)
        ).fetchone()
        if row is None:
            return False
        last = conn.execute(
            "SELECT new_text FROM message_edits WHERE channel=? AND msg_id=? ORDER BY rowid DESC LIMIT 1",
            (channel, msg_id),
        ).fetchone()
        old_text = last[0] if last else row[0]
        if old_text == new_text:
            return False
        cur = conn.execute(
            "INSERT OR IGNORE INTO message_edits VALUES (?,?,?,?,?,?)",
            (channel, msg_id, edited_at, old_text, new_text, utc_now_iso()),
        )
        conn.execute(
            "UPDATE raw_messages SET edited_at=? WHERE channel=? AND msg_id=?", (edited_at, channel, msg_id)
        )
        return cur.rowcount > 0


def max_msg_id(conn: sqlite3.Connection, channel: str) -> int | None:
    return conn.execute("SELECT MAX(msg_id) FROM raw_messages WHERE channel=?", (channel,)).fetchone()[0]


def min_posted_at(conn: sqlite3.Connection, channel: str) -> tuple[int, str] | None:
    row = conn.execute(
        "SELECT msg_id, posted_at FROM raw_messages WHERE channel=? ORDER BY msg_id LIMIT 1", (channel,)
    ).fetchone()
    return (row[0], row[1]) if row else None


def heartbeat(conn: sqlite3.Connection, last_msg_id: int | None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO collector_heartbeat(id, last_seen_at, last_msg_id) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_seen_at=excluded.last_seen_at, "
            "last_msg_id=COALESCE(excluded.last_msg_id, collector_heartbeat.last_msg_id)",
            (utc_now_iso(), last_msg_id),
        )


def read_messages(conn: sqlite3.Connection, channel: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM raw_messages WHERE channel=? ORDER BY posted_at, msg_id", conn, params=(channel,)
    )


def count(conn: sqlite3.Connection, table: str, channel: str | None = None) -> int:
    if table not in {"raw_messages", "message_edits", "parse_errors", "alerts"}:
        raise ValueError(table)
    q = f"SELECT COUNT(*) FROM {table}" + (" WHERE channel=?" if channel else "")
    return conn.execute(q, (channel,) if channel else ()).fetchone()[0]


def replace_derived(
    conn: sqlite3.Connection, channel: str, alerts: pd.DataFrame, errors: list[tuple]
) -> None:
    """Atomically replace alerts and parse_errors for one channel."""
    with conn:
        conn.execute("DELETE FROM alerts WHERE channel=?", (channel,))
        conn.execute("DELETE FROM parse_errors WHERE channel=?", (channel,))
        if not alerts.empty:
            conn.executemany(
                f"INSERT INTO alerts({','.join(ALERT_DB_COLUMNS)}) VALUES ({','.join('?' * len(ALERT_DB_COLUMNS))})",
                alerts[ALERT_DB_COLUMNS]
                .astype(object)
                .where(alerts[ALERT_DB_COLUMNS].notna(), None)
                .values.tolist(),
            )
        conn.executemany("INSERT INTO parse_errors VALUES (?,?,?,?,?)", errors)


def read_alerts(conn: sqlite3.Connection, channel: str) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM alerts WHERE channel=?", conn, params=(channel,))


def open_db(path: Path):
    return closing(connect(path))
