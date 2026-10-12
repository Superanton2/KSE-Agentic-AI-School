"""Replay mode: the product without a Telegram session, on the committed data.

Sources are the committed ``data/processed/alerts.parquet`` (UkraineAlarmSignal rows for Kyiv City, the same label
source as the live reader), cut by ``known_at <= clock`` on every read — the API sees only what was known at the
replay moment. The model is refit from the committed grid on labels whose window closed before ``--until``
(``fit``), into ``data/work/replay/`` — never over ``data/processed`` or ``model_card.json``.
"""

import json
import pickle
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from airalert.api import live as L
from airalert.config import KYIV
from airalert.model import data as D

DEMO_AT = pd.Timestamp("2026-10-07T11:30:00Z")  # 14:30 Kyiv: calm, an alert ended 1 h ago, the next came at 15:29
DEMO_ALERT_AT = pd.Timestamp("2026-10-07T13:45:00Z")  # 16:45 Kyiv: 16 min into a 4.5-hour air raid
LABEL_MARGIN = pd.Timedelta(minutes=130)  # the 120-min label window + 10 min for the end messages to arrive


def volunteer_alerts(data_dir: Path) -> pd.DataFrame:
    """Kyiv City alerts from the volunteer channel in the committed parquet (``alert_type`` kept)."""
    a = pd.read_parquet(data_dir / "processed" / "alerts.parquet")
    a = a[(a["source"] == "tg_volunteer") & (a["granularity"] == "raw") & (a["location"] == KYIV)
          & a["alert_type"].isin(["air_raid", "air_raid_red"])]
    return a[["alert_type", "started_at", "finished_at", "start_known_at", "end_known_at"]].reset_index(drop=True)


def known_by(a: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """Rows whose start was known by t; ends not yet known are erased (as ``Sources.truncate``)."""
    a = a[a["start_known_at"] <= t].copy()
    late = a["end_known_at"].isna() | (a["end_known_at"] > t)
    a.loc[late, ["finished_at", "end_known_at"]] = pd.NaT
    return a.reset_index(drop=True)


class Reader:
    """``live.read`` replacement: the same ``Live`` built from the committed parquet as of ``now``."""

    def __init__(self, data_dir: Path):
        self.all = volunteer_alerts(data_dir)

    def __call__(self, now: pd.Timestamp) -> L.Live:
        a = known_by(self.all, now)
        a = a[a["finished_at"].isna() | (a["finished_at"] >= now - L.HISTORY)]
        red_on = bool(((a["alert_type"] == "air_raid_red") & a["finished_at"].isna()).any())
        air = a[a["alert_type"] == "air_raid"].assign(naive=False, src="tg_volunteer")[D.ALERT_COLS]
        return L.Live(D.merge_overlaps(air), red_on, now, None, False)


def fit(data_dir: Path, until: pd.Timestamp, out_dir: Path) -> dict:
    """Product ensemble on grid rows whose label window closed by ``until`` → ``out_dir/model_final.pkl``."""
    from airalert.model import pipeline

    summ = json.loads((pipeline.eval_dir(data_dir) / "summary.json").read_text())
    model = summ["product"]
    g = pd.read_parquet(data_dir / "processed" / pipeline.GRID_FILE)
    g = g[g["t"] + LABEL_MARGIN <= until].reset_index(drop=True)
    a = known_by(volunteer_alerts(data_dir), until)
    alerts = D.merge_overlaps(a[a["alert_type"] == "air_raid"].assign(naive=False, src="tg_volunteer")[D.ALERT_COLS])
    art = pipeline.fit_members(g, alerts, until, model, summ["C"][model])
    art["replay_until"] = until.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / pipeline.FINAL_FILE
    tmp = out.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(art, f)
    tmp.replace(out)
    return art


def data_end(data_dir: Path) -> pd.Timestamp:
    """The newest ``known_at`` in the committed alerts: the fallback model is fitted up to here."""
    a = volunteer_alerts(data_dir)
    return max(a["start_known_at"].max(), a["end_known_at"].max()).tz_convert("UTC")


def default_dir(data_dir: Path, until: pd.Timestamp) -> Path:
    return data_dir / "work" / "replay" / until.strftime("%Y%m%dT%H%MZ")


def now_utc() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(UTC))
