"""Model inputs: Kyiv City alert intervals from ONE source (eTryvoga) and drone mentions.

Label source = eTryvoga (volunteer). Our Telegram backfill of ``UkraineAlarmSignal`` starts on 2026-08-25 20:54 UTC,
so before ``SEAM`` we take the same source from the Vadimkin volunteer CSV (no ``known_at`` there: known_at = event
time; only used in training). ``naive=True`` (end imputed as start + 30 min) → ``naive`` column, censored for the
duration model. Only ``air_raid`` (``air_raid_red`` is a level nested inside an air raid).
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from airalert.config import KYIV, VOLUNTEER_CHANNEL

SEAM = pd.Timestamp("2026-08-26T00:00:00Z")
TRAIN_START = pd.Timestamp("2026-08-10T00:00:00Z")
TEST_START_DAY = pd.Timestamp("2026-09-13").date()
TEST_END_DAY = pd.Timestamp("2026-10-11").date()
KYIV_TZ = "Europe/Kyiv"
MERGE_GAP = pd.Timedelta(0)

ALERT_COLS = ["started_at", "finished_at", "start_known_at", "end_known_at", "naive", "src"]


def vadimkin_volunteer(path: Path) -> pd.DataFrame:
    v = pd.read_csv(path)
    v = v[v["region"] == KYIV].copy()
    for c in ("started_at", "finished_at"):
        v[c] = pd.to_datetime(v[c], utc=True, format="ISO8601")
    v["naive"] = v["naive"].astype(str).str.lower() == "true"
    v["start_known_at"], v["end_known_at"] = v["started_at"], v["finished_at"]
    v["src"] = "vadimkin_volunteer"
    return v[ALERT_COLS]


def tg_volunteer(db: Path) -> pd.DataFrame:
    from airalert.tg import store

    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as c:
        a = store.read_alerts(c, VOLUNTEER_CHANNEL)
    a = a[(a["location"] == KYIV) & (a["alert_type"] == "air_raid")].copy()
    for c in ("started_at", "finished_at", "start_known_at", "end_known_at"):
        a[c] = pd.to_datetime(a[c], utc=True, format="ISO8601")
    a["naive"] = False
    a["src"] = "tg_volunteer"
    return a[ALERT_COLS]


def merge_overlaps(a: pd.DataFrame) -> pd.DataFrame:
    """Merge overlapping intervals (keep the first start, latest end; ``naive`` only if the kept end is naive)."""
    a = a.sort_values("started_at").reset_index(drop=True)
    out: list[dict] = []
    for r in a.to_dict("records"):
        if out and pd.notna(out[-1]["finished_at"]) and r["started_at"] <= out[-1]["finished_at"] + MERGE_GAP:
            p = out[-1]
            if pd.isna(r["finished_at"]) or r["finished_at"] > p["finished_at"]:
                p["finished_at"], p["end_known_at"], p["naive"] = r["finished_at"], r["end_known_at"], r["naive"]
            continue
        if out and pd.isna(out[-1]["finished_at"]):
            continue
        out.append(dict(r))
    return pd.DataFrame(out, columns=ALERT_COLS)


def kyiv_alerts(data_dir: Path, db: Path | None = None, seam: pd.Timestamp = SEAM) -> pd.DataFrame:
    vol = vadimkin_volunteer(data_dir / "raw" / "vadimkin" / "datasets" / "volunteer_data_en.csv")
    tg = tg_volunteer(db or data_dir / "live" / "snapshots" / "alerts.sqlite")
    a = pd.concat([vol[vol["started_at"] < seam], tg[tg["started_at"] >= seam]], ignore_index=True)
    return merge_overlaps(a)


def official_kyiv(data_dir: Path) -> pd.DataFrame:
    """Official Kyiv City starts (dataset before the seam, our tg_official after) — only for the robustness check."""
    a = pd.read_parquet(data_dir / "processed" / "alerts.parquet")
    k = a[(a["location"] == KYIV) & (a["granularity"] == "raw") & (a["alert_type"] == "air_raid")]
    return k[k["source"].isin(["dataset_official", "tg_official"])].sort_values("started_at")


def official_check(alerts: pd.DataFrame, official: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp,
                   outages: list[tuple[pd.Timestamp, pd.Timestamp]], tol_min: float = 2.0) -> dict:
    """Starts in [lo, hi) outside official outages: counts and share matched within ±tol minutes."""

    def keep(s: pd.Series) -> pd.Series:
        m = (s >= lo) & (s < hi)
        for a, b in outages:
            m &= ~((s >= a) & (s < b))
        return s[m]

    v = keep(alerts["started_at"]).to_numpy(dtype="datetime64[ns]")
    o = keep(official["started_at"]).to_numpy(dtype="datetime64[ns]")

    def matched(x, y):
        if not len(y):
            return 0
        i = np.clip(np.searchsorted(y, x), 1, len(y) - 1)
        d = np.minimum(np.abs(x - y[i - 1]), np.abs(x - y[i])) / np.timedelta64(1, "m")
        return int((d <= tol_min).sum())

    return {"volunteer_starts": len(v), "official_starts": len(o), "volunteer_matched": matched(v, o),
            "official_matched": matched(o, v), "tol_min": tol_min}


@dataclass
class Sources:
    """Everything the as-of features read; each row carries the time it became known."""

    alerts: pd.DataFrame  # ALERT_COLS
    mentions: pd.DataFrame  # drone_mentions.parquet

    def truncate(self, t: pd.Timestamp) -> "Sources":
        """What we could have had at t (for the no-leak test): only rows known by t, with unknown ends erased."""
        a = self.alerts[self.alerts["start_known_at"] <= t].copy()
        late = a["end_known_at"].isna() | (a["end_known_at"] > t)
        a.loc[late, ["finished_at", "end_known_at"]] = pd.NaT
        return Sources(a.reset_index(drop=True), self.mentions[self.mentions["known_at"] <= t].reset_index(drop=True))


def load_mentions(data_dir: Path) -> pd.DataFrame:
    return pd.read_parquet(data_dir / "processed" / "drone_mentions.parquet")
