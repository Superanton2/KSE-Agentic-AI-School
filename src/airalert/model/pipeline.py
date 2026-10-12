"""Glue for the CLI: load sources, build the grid, leakage check, lift report."""

import json
import math
import sqlite3
import subprocess
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from airalert.model import data as D
from airalert.model import features as F

GRID_FILE = "model_grid.parquet"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def alerts_db(data_dir: Path) -> Path:
    return data_dir / "live" / "snapshots" / "alerts.sqlite"


def data_end(db: Path) -> pd.Timestamp:
    """Last collector heartbeat: up to then, no message means no change."""
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as c:
        (v,) = c.execute("select max(last_seen_at) from collector_heartbeat").fetchone()
    return pd.Timestamp(v)


def load(data_dir: Path, db: Path | None = None) -> tuple[D.Sources, pd.Timestamp]:
    db = db or alerts_db(data_dir)
    return D.Sources(D.kyiv_alerts(data_dir, db), D.load_mentions(data_dir)), data_end(db)


def kyiv_day(t: pd.Series) -> pd.Series:
    return pd.to_datetime(t, utc=True).dt.tz_convert(D.KYIV_TZ).dt.date


def leak_check(sources: D.Sources, g: pd.DataFrame, n: int, seed: int = 0) -> list[tuple[pd.Timestamp, bool]]:
    rng = np.random.default_rng(seed)
    out = []
    for i in rng.choice(len(g), size=min(n, len(g)), replace=False):
        t = g.at[i, "t"]
        again = F.features_asof(t, sources.truncate(t))
        same = all(again[c] == g.at[i, c] or (math.isnan(again[c]) and math.isnan(g.at[i, c])) for c in F.ALL_FEATURES)
        out.append((t, same))
    return out


def period_counts(alerts: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    a = alerts.assign(day=kyiv_day(alerts["started_at"]))
    per = {
        "before regime change (2026-06-01…08-16)": (pd.Timestamp("2026-06-01").date(), pd.Timestamp("2026-08-16").date()),
        "train/selection (08-10…09-12)": (pd.Timestamp("2026-08-10").date(), pd.Timestamp("2026-09-12").date()),
        "test (09-13…10-11)": (D.TEST_START_DAY, D.TEST_END_DAY),
        "after test (10-12…)": (pd.Timestamp("2026-10-12").date(), kyiv_day(pd.Series([end]))[0]),
    }
    rows = []
    for name, (lo, hi) in per.items():
        x = a[(a["day"] >= lo) & (a["day"] <= hi)]
        days = (hi - lo).days + 1
        dur = (x["finished_at"] - x["started_at"]).dt.total_seconds() / 60
        rows.append({"period": name, "days": days, "starts": len(x), "starts_per_day": len(x) / days,
                     "median_dur_min": float(dur[~x["naive"]].median()) if len(x) else math.nan,
                     "naive": int(x["naive"].sum())})
    return pd.DataFrame(rows)


def build_grid(data_dir: Path, reports_dir: Path, check_leak: int = 200) -> pd.DataFrame:
    sources, end = load(data_dir)
    times = F.grid(D.TRAIN_START, end)
    g = F.build(sources, times, end)
    g.to_parquet(data_dir / "processed" / GRID_FILE, index=False, compression="zstd")
    leak = leak_check(sources, g, check_leak)
    lift_report(g, sources, end, leak, data_dir, reports_dir)
    return g


def lift_report(g, sources, end, leak, data_dir: Path, reports_dir: Path) -> None:
    train = g[kyiv_day(g["t"]) <= pd.Timestamp("2026-09-12").date()]
    table = F.lift_table(train)
    counts = period_counts(sources.alerts, end)
    m = json.loads((data_dir / "processed" / "manifest.json").read_text())
    outages = [(pd.Timestamp(w["start"]), pd.Timestamp(w["end"])) for w in m["official_outages"]]
    off = D.official_kyiv(data_dir)
    chk = {
        f"{lo:%m-%d}…{hi:%m-%d}": D.official_check(sources.alerts, off, lo, hi, outages)
        for lo, hi in [(D.TRAIN_START, D.SEAM), (D.SEAM, pd.Timestamp("2026-09-07T06:09Z"))]
    }
    chk5 = D.official_check(sources.alerts, off, D.TRAIN_START, D.SEAM, outages, tol_min=10)
    calm = train[train["calm"]]
    md = [
        "# Phase 4 · step 1: grid, labels, features, quick lift",
        "",
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code `{git_sha()}`. Grid: 5-min UTC, "
        f"{g['t'].min():%Y-%m-%d %H:%M} … {g['t'].max():%Y-%m-%d %H:%M} ({len(g)} points, {int(g['calm'].sum())} calm). "
        f"Data end (last collector heartbeat) {end:%Y-%m-%d %H:%M} UTC.",
        "",
        "## Label source",
        "",
        f"Kyiv City air raids from eTryvoga only: Vadimkin volunteer CSV before {D.SEAM:%Y-%m-%d %H:%M} UTC, our "
        "`UkraineAlarmSignal` backfill/live after (it starts 2026-08-25 20:54 UTC). Overlaps merged. "
        "In the CSV part known_at = event time (train only).",
        "",
        "Robustness vs official (starts outside official outages, ±2 min):",
        "",
        "| window | eTryvoga starts | official starts | eTryvoga matched | official matched |",
        "|---|---|---|---|---|",
        *[f"| {k} | {v['volunteer_starts']} | {v['official_starts']} | {v['volunteer_matched']} | {v['official_matched']} |"
          for k, v in chk.items()],
        "",
        f"Before the seam only {chk[next(iter(chk))]['volunteer_matched']} of {chk[next(iter(chk))]['volunteer_starts']} "
        f"match within ±2 min (±10 min: {chk5['volunteer_matched']}): the CSV times are coarser/shifted, the counts agree.",
        "",
        "## Starts per period (Kyiv days)",
        "",
        "| period | days | starts | starts/day | median duration, min (non-naive) | naive ends |",
        "|---|---|---|---|---|---|",
        *[f"| {r.period} | {r.days} | {r.starts} | {r.starts_per_day:.2f} | {r.median_dur_min:.0f} | {r.naive} |"
          for r in counts.itertuples()],
        "",
        "## Leakage test",
        "",
        f"{len(leak)} random grid points: all sources cut at known_at ≤ t, features recomputed — "
        f"**{sum(ok for _, ok in leak)}/{len(leak)} bit-identical**.",
        "",
        "## Quick lift on the training period (08-10…09-12, calm grid points)",
        "",
        f"Base rates (calm t): " + ", ".join(f"P(start ≤ {h}) = {calm[f'y_{h}'].mean():.3f}" for h in F.HORIZONS)
        + f"; n = {len(calm)}.",
        "",
        "P(start ≤ H | feature > 0) / P(start ≤ H | feature = 0); in brackets P(… | > 0).",
        "",
        "| feature | share > 0 | n > 0 | " + " | ".join(f"H={h}" for h in F.HORIZONS) + " |",
        "|---|---|---|" + "---|" * len(F.HORIZONS),
        *[f"| {r['feature']} | {r['share_on']:.1%} | {r['n_on']} | "
          + " | ".join(f"{r[f'lift{h}']:.2f} ({r[f'P{h}_on']:.2f})" for h in F.HORIZONS) + " |"
          for _, r in table.iterrows()],
        "",
    ]
    (reports_dir / "model_lift.md").write_text("\n".join(md) + "\n", encoding="utf-8")
