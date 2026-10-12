"""Read the collectors' SQLite files for the API — read-only, never writing.

In Docker the API mounts ``data/live`` read-only, so it cannot checkpoint or delete a WAL the collector is writing
(the cross-container hazard of Docker Desktop). Without shared locks a read can occasionally fail mid-checkpoint;
we retry and otherwise keep the last good state (``sources_ok`` = false).
"""

import logging
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from airalert.config import KYIV, VOLUNTEER_CHANNEL
from airalert.model import data as D

log = logging.getLogger("airalert.api")
HISTORY = pd.Timedelta(days=16)  # the features look back 14 days
STALE_SITREP = pd.Timedelta(minutes=10)


def ro_connect(db: Path, timeout: float = 5) -> sqlite3.Connection:
    """Read-only, from a read-only mount. A WAL database without its -wal/-shm files (the writer checkpointed and
    removed them) cannot be opened with ``mode=ro`` when the directory is not writable; without a -wal file the
    main file holds every committed transaction, so ``immutable=1`` reads exactly that."""
    if not db.exists():
        raise sqlite3.OperationalError(f"no database {db}")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=timeout)
    try:
        c.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
        return c
    except sqlite3.OperationalError:
        c.close()
        if Path(f"{db}-wal").exists():
            raise
        return sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True, timeout=timeout)


_ro = ro_connect


def _retry(fn, attempts: int = 3):
    for i in range(attempts):
        try:
            return fn()
        except sqlite3.Error as e:
            if i == attempts - 1:
                raise
            log.warning("sqlite read failed (%s), retrying", e)
            time.sleep(0.2 * (i + 1))
    return None


@dataclass
class Live:
    alerts: pd.DataFrame  # D.ALERT_COLS, Kyiv air raids
    red_on: bool  # an open air_raid_red for Kyiv in the volunteer channel
    heartbeat: pd.Timestamp | None
    sitrep_level: str | None
    sitrep_ok: bool
    sitrep_heartbeat: pd.Timestamp | None = None


def read_alerts(db: Path, now: pd.Timestamp) -> tuple[pd.DataFrame, bool, pd.Timestamp | None]:
    since = (now - HISTORY).isoformat()

    def q():
        with closing(_ro(db)) as c:
            rows = c.execute(
                "SELECT alert_type, started_at, finished_at, start_known_at, end_known_at FROM alerts "
                "WHERE channel = ? AND location = ? AND (finished_at IS NULL OR finished_at >= ?)",
                (VOLUNTEER_CHANNEL, KYIV, since),
            ).fetchall()
            (hb,) = c.execute("SELECT max(last_seen_at) FROM collector_heartbeat").fetchone()
        return rows, hb

    rows, hb = _retry(q)
    df = pd.DataFrame(rows, columns=["alert_type", "started_at", "finished_at", "start_known_at", "end_known_at"])
    for c in ("started_at", "finished_at", "start_known_at", "end_known_at"):
        df[c] = pd.to_datetime(df[c], utc=True, format="ISO8601")
    red_on = bool(((df["alert_type"] == "air_raid_red") & df["finished_at"].isna()).any())
    a = df[df["alert_type"] == "air_raid"].assign(naive=False, src="tg_volunteer")[D.ALERT_COLS]
    return D.merge_overlaps(a), red_on, (pd.Timestamp(hb) if hb else None)


def read_sitrep(db: Path, now: pd.Timestamp) -> tuple[str | None, bool, pd.Timestamp | None]:
    """Kyiv City level from the newest SITREP, if the SITREP collector is alive."""
    from airalert.sitrep import collector, parser

    if not db.exists():
        return None, False, None

    def q():
        with closing(_ro(db)) as c:
            (hb,) = c.execute("SELECT max(last_seen_at) FROM collector_heartbeat").fetchone()
            snaps = collector.read_snapshots(c, collector.MarkdownSitrep.name, limit=1)
        return hb, snaps

    hb, snaps = _retry(q)
    hb = pd.Timestamp(hb) if hb else None
    if hb is None or not snaps or now - hb > STALE_SITREP:
        return None, False, hb
    city = [a for a in parser.kyiv_status(snaps[0][1]) if a.region_uk == "м. Київ" and a.area_uk is None]
    return (city[0].level if city else None), True, hb


def read(alerts_db: Path, sitrep_db: Path, now: pd.Timestamp) -> Live:
    alerts, red_on, hb = read_alerts(alerts_db, now)
    try:
        level, ok, shb = read_sitrep(sitrep_db, now)
    except Exception as e:  # the SITREP only refines the level; never fail the state because of it
        log.warning("sitrep read failed: %s", e)
        level, ok, shb = None, False, None
    return Live(alerts, red_on, hb, level, ok, shb)
