"""Poll the alerts.in.ua SITREP once a minute; store the raw text only when it changed.

The endpoint (``/llm`` -> ``api.alerts.in.ua/v3/alerts/active.md``) sends ``Last-Modified`` but no ETag, so
requests carry ``If-Modified-Since`` (and ``If-None-Match`` should an ETag ever appear). Snapshots are
zlib-compressed (~25 KB of Markdown each, it changes almost every minute because of the clock lines).
A future JSON API source plugs in through the same :class:`Source` interface.
"""

import hashlib
import logging
import sqlite3
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from airalert import __version__
from airalert.tg.store import utc_now_iso

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots(
  fetched_at TEXT NOT NULL,
  source TEXT NOT NULL,
  last_modified TEXT,
  sha256 TEXT NOT NULL,
  body BLOB NOT NULL  -- zlib(utf-8 text)
);
CREATE INDEX IF NOT EXISTS snapshots_fetched ON snapshots(source, fetched_at);
CREATE TABLE IF NOT EXISTS collector_heartbeat(
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_seen_at TEXT NOT NULL,
  last_msg_id INTEGER
);
"""


@dataclass(frozen=True)
class Fetched:
    status: int  # 200 or 304
    text: str | None = None
    last_modified: str | None = None
    etag: str | None = None


class Source(Protocol):
    name: str

    def fetch(self, last_modified: str | None, etag: str | None) -> Fetched: ...


def user_agent(contact: str) -> str:
    return f"airalert/{__version__} (KSE air-alert forecasting research{'; ' + contact if contact else ''})"


class MarkdownSitrep:
    name = "alerts_in_ua_md"

    def __init__(self, url: str, contact: str = "", timeout: float = 20):
        self.url, self.timeout = url, timeout
        self.headers = {"User-Agent": user_agent(contact), "Accept": "text/markdown, text/plain"}

    def fetch(self, last_modified: str | None, etag: str | None) -> Fetched:
        headers = dict(self.headers)
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if etag:
            headers["If-None-Match"] = etag
        req = urllib.request.Request(self.url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return Fetched(
                    200,
                    r.read().decode("utf-8"),
                    r.headers.get("Last-Modified"),
                    r.headers.get("ETag"),
                )
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return Fetched(304, last_modified=last_modified, etag=etag)
            raise


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    return conn


def open_db(path: Path):
    return closing(connect(path))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def last_snapshot(conn: sqlite3.Connection, source: str) -> tuple[str, str | None] | None:
    """(sha256, last_modified) of the newest stored snapshot."""
    return conn.execute(
        "SELECT sha256, last_modified FROM snapshots WHERE source=? ORDER BY rowid DESC LIMIT 1", (source,)
    ).fetchone()


def store_if_changed(conn: sqlite3.Connection, source: str, f: Fetched, fetched_at: str) -> bool:
    with conn:
        conn.execute(
            "INSERT INTO collector_heartbeat(id, last_seen_at) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
            (fetched_at,),
        )
        if f.status != 200 or f.text is None:
            return False
        digest = sha256(f.text)
        last = last_snapshot(conn, source)
        if last and last[0] == digest:
            return False
        conn.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?,?)",
            (fetched_at, source, f.last_modified, digest, zlib.compress(f.text.encode("utf-8"), 9)),
        )
        return True


def read_snapshots(conn: sqlite3.Connection, source: str, limit: int | None = None) -> list[tuple[str, str]]:
    """[(fetched_at, text)], newest first."""
    q = "SELECT fetched_at, body FROM snapshots WHERE source=? ORDER BY rowid DESC"
    rows = conn.execute(q + (f" LIMIT {int(limit)}" if limit else ""), (source,)).fetchall()
    return [(t, zlib.decompress(b).decode("utf-8")) for t, b in rows]


def poll_once(conn: sqlite3.Connection, src: Source, state: dict) -> bool:
    f = src.fetch(state.get("last_modified"), state.get("etag"))
    state["last_modified"], state["etag"] = f.last_modified, f.etag
    return store_if_changed(conn, src.name, f, utc_now_iso())


def poll_forever(
    conn: sqlite3.Connection,
    src: Source,
    every: float,
    sleep: Callable[[float], None] = time.sleep,
    iterations: int | None = None,
) -> None:
    last = last_snapshot(conn, src.name)
    state = {"last_modified": last[1] if last else None, "etag": None}
    n = 0
    while iterations is None or n < iterations:
        started = time.monotonic()
        try:
            if poll_once(conn, src, state):
                log.info("%s: new snapshot", src.name)
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError) as e:
            log.warning("%s: fetch failed: %s", src.name, e)
        n += 1
        if iterations is None or n < iterations:
            sleep(max(0.0, every - (time.monotonic() - started)))
