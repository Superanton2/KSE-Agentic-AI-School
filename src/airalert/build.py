"""Assemble one clean alert set from all sources -> data/processed/alerts.parquet + manifest.json.

Source selection (air raids), decided from the data (see reports/data_quality.md):
1. ``dataset_official`` (Vadimkin CSV, deduplicated) for alerts that started before ``SEAM``;
2. ``tg_official`` (air_alert_ua, our parser) from ``SEAM`` on, while the channel was publishing;
3. ``tg_volunteer`` (єТривога, our parser) inside official outages (silence > 6 h: 2026-08-29…09-02,
   and since 2026-09-07 when air_alert_ua stopped publishing): intervals that started in the outage or
   were active when it began. Official intervals cut by an outage (flag ``source_gap``) are dropped
   because the volunteer copy of the same alert has a real end.

Threat intervals (drones, KAB, …) exist only in ``tg_official``; the red alert level only in
``tg_volunteer`` (alert_type ``air_raid_red``). ``oblast_union`` is built from air raids only.
"""

import itertools
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from airalert import clean
from airalert.config import OFFICIAL_CHANNEL, VOLUNTEER_CHANNEL
from airalert.tg import store
from airalert.tg.rebuild import load_alerts
from airalert.tg.state_machine import SOURCE_GAP

SEAM = pd.Timestamp("2026-08-26T00:00:00Z")
AIR_RAID_TYPES = ("air_raid",)
OUTPUT_COLUMNS = ["granularity", *clean.ALERT_COLUMNS, "alert_type"]


@dataclass
class Window:
    start: pd.Timestamp
    end: pd.Timestamp  # exclusive; "now" for an outage that is still going on

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def outages(posted_at: pd.Series, now: pd.Timestamp, gap=SOURCE_GAP) -> list[Window]:
    """Silences longer than ``gap`` in a channel: [last message before, first message after)."""
    t = pd.Series(sorted(pd.to_datetime(posted_at, utc=True)))
    if t.empty:
        return [Window(pd.Timestamp.min.tz_localize("UTC"), now)]
    out = [Window(a, b) for a, b in itertools.pairwise(t) if b - a > gap]
    if now - t.iloc[-1] > gap:
        out.append(Window(t.iloc[-1], now))
    return out


def _in_windows(df: pd.DataFrame, windows: list[Window]) -> pd.Series:
    """Started inside a window, or was active at the moment a window began."""
    mask = pd.Series(False, index=df.index)
    for w in windows:
        started_in = (df["started_at"] >= w.start) & (df["started_at"] < w.end)
        active_at_start = (df["started_at"] < w.start) & (
            df["finished_at"].isna() | (df["finished_at"] >= w.start)
        )
        mask |= started_in | active_at_start
    return mask


def _drop_overlapping(off: pd.DataFrame, vol: pd.DataFrame) -> pd.DataFrame:
    """When the official channel comes back, an alert that began during the outage is still running
    in the volunteer copy; drop official intervals overlapping a selected volunteer one (same location
    and type) so it is not counted twice. The volunteer interval keeps its real end."""
    keys = [*clean.LOCATION_KEYS, "alert_type"]
    far = pd.Timestamp("2262-01-01", tz="UTC")
    m = off.reset_index().merge(vol[[*keys, "started_at", "finished_at"]], on=keys, suffixes=("", "_v"))
    hit = (m["started_at"] < m["finished_at_v"].fillna(far)) & (
        m["started_at_v"] < m["finished_at"].fillna(far)
    )
    return off.drop(index=m.loc[hit, "index"].unique())


def assemble(
    dataset_official: pd.DataFrame,
    tg_official: pd.DataFrame,
    tg_volunteer: pd.DataFrame,
    official_outages: list[Window],
    seam: pd.Timestamp = SEAM,
) -> pd.DataFrame:
    """Raw-granularity intervals from all sources, without double counting."""
    ds = dataset_official[dataset_official["started_at"] < seam].assign(alert_type="air_raid")
    off = tg_official[(tg_official["started_at"] >= seam) & ~tg_official["flags"].str.contains("source_gap")]
    vol = tg_volunteer[_in_windows(tg_volunteer, [w for w in official_outages if w.end > seam])]
    off = _drop_overlapping(off, vol)
    parts = [p for p in (ds, off, vol) if not p.empty]
    raw = pd.concat(parts, ignore_index=True)[[*clean.ALERT_COLUMNS, "alert_type"]]
    return raw.sort_values(
        ["started_at", "location", "level", "raion", "hromada"], kind="mergesort"
    ).reset_index(drop=True)


def union(raw: pd.DataFrame) -> pd.DataFrame:
    air = raw[raw["alert_type"].isin(AIR_RAID_TYPES)]
    u = clean.oblast_union(air[clean.ALERT_COLUMNS].assign(source=air["source"]))
    # A union interval spanning a source switch keeps the source of the row that started it.
    return u.assign(alert_type="air_raid")


def to_output(raw: pd.DataFrame, oblast_union: pd.DataFrame) -> pd.DataFrame:
    out = pd.concat(
        [raw.assign(granularity="raw"), oblast_union.assign(granularity="oblast_union")], ignore_index=True
    )
    return out[OUTPUT_COLUMNS]


def git_sha(path: Path) -> str:
    """Commit of a git checkout; works without the git binary (e.g. in the container)."""
    if not (path / ".git").exists():
        return os.environ.get("AIRALERT_CODE_SHA", "unknown")
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        head = path / ".git" / "HEAD"
        if not head.exists():
            return "unknown"
        ref = head.read_text().strip()
        if not ref.startswith("ref: "):
            return ref
        ref_file = path / ".git" / ref[5:]
        if ref_file.exists():
            return ref_file.read_text().strip()
        packed = path / ".git" / "packed-refs"
        for line in packed.read_text().splitlines() if packed.exists() else []:
            if line.endswith(ref[5:]):
                return line.split()[0]
        return "unknown"


@dataclass
class BuildResult:
    output: pd.DataFrame
    raw: pd.DataFrame
    tg_official: pd.DataFrame
    tg_volunteer: pd.DataFrame
    official_outages: list[Window]
    volunteer_outages: list[Window]
    manifest: dict


def build(
    conn, dataset_official_clean: pd.DataFrame, dataset_commit: str, repo: Path, now=None
) -> BuildResult:
    now = now or pd.Timestamp.now(tz="UTC")
    tg_off, tg_vol = load_alerts(conn, OFFICIAL_CHANNEL), load_alerts(conn, VOLUNTEER_CHANNEL)
    posted = {ch: store.read_messages(conn, ch)["posted_at"] for ch in (OFFICIAL_CHANNEL, VOLUNTEER_CHANNEL)}
    off_out, vol_out = outages(posted[OFFICIAL_CHANNEL], now), outages(posted[VOLUNTEER_CHANNEL], now)
    raw = assemble(dataset_official_clean, tg_off, tg_vol, off_out)
    output = to_output(raw, union(raw))
    manifest = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code_git_sha": git_sha(repo),
        "vadimkin_dataset_commit": dataset_commit,
        "seam_dataset_to_telegram": SEAM.isoformat(),
        "telegram_max_posted_at": {ch: (p.max() if len(p) else None) for ch, p in posted.items()},
        "official_outages": [w.to_dict() for w in off_out],
        "volunteer_outages": [w.to_dict() for w in vol_out],
        "rows": {
            f"{g}/{s}": int(n) for (g, s), n in output.groupby(["granularity", "source"]).size().items()
        },
        "rows_by_alert_type": {k: int(v) for k, v in raw["alert_type"].value_counts().items()},
        "open_intervals_raw": int(raw["finished_at"].isna().sum()),
        "max_started_at": output["started_at"].max().isoformat(),
    }
    return BuildResult(output, raw, tg_off, tg_vol, off_out, vol_out, manifest)


def write(result: BuildResult, processed_dir: Path) -> tuple[Path, Path]:
    processed_dir.mkdir(parents=True, exist_ok=True)
    pq, mf = processed_dir / "alerts.parquet", processed_dir / "manifest.json"
    result.output.to_parquet(pq, index=False, compression="zstd")
    mf.write_text(json.dumps(result.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return pq, mf
