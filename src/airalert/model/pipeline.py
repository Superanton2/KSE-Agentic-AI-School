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


def build_grid(data_dir: Path, reports_dir: Path, check_leak: int = 200, db: Path | None = None,
               report: bool = True) -> pd.DataFrame:
    sources, end = load(data_dir, db)
    times = F.grid(D.TRAIN_START, end)
    g = F.build(sources, times, end)
    leak = leak_check(sources, g, check_leak)
    if not all(ok for _, ok in leak):
        raise RuntimeError("leak check failed: features differ on truncated sources")
    g.to_parquet(data_dir / "processed" / GRID_FILE, index=False, compression="zstd")
    if report:
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
        "Base rates (calm t): " + ", ".join(f"P(start ≤ {h}) = {calm[f'y_{h}'].mean():.3f}" for h in F.HORIZONS)
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


# ---------------------------------------------------------------- step 2: models and evaluation

MODELS = ["B0", "B1", "M1a", "M1b"]
COLORS = {"B0": "#2a78d6", "B1": "#eb6834", "M1a": "#1baf7a", "M1b": "#eda100"}
INK, MUTED, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e4e3df"
VAL_DAYS = [pd.Timestamp("2026-08-24").date() + pd.Timedelta(days=i) for i in range(20)]  # 08-24 … 09-12
TEST_DAYS = [D.TEST_START_DAY + pd.Timedelta(days=i) for i in range((D.TEST_END_DAY - D.TEST_START_DAY).days + 1)]


def eval_dir(data_dir: Path) -> Path:
    p = data_dir / "processed" / "model_eval"
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_eval(data_dir: Path, reports_dir: Path, n_boot: int = 1000) -> dict:
    from airalert.model import evaluate as E
    from airalert.model import hazard as HZ

    g = pd.read_parquet(data_dir / "processed" / GRID_FILE)
    rows = F.hazard_rows(g)
    best, csel = E.select_C(g, rows, VAL_DAYS)
    wf = E.walk_forward(g, rows, TEST_DAYS, best["M1a"], best["M1b"])
    out = eval_dir(data_dir)
    wf.preds.to_parquet(out / "preds.parquet", index=False)
    np.savez_compressed(out / "hazards.npz", **wf.hazards)
    mt = E.metrics(wf.preds, MODELS)
    boots = pd.concat([
        E.day_bootstrap(wf.preds, "M1b", "M1a", n_boot), E.day_bootstrap(wf.preds, "M1b", "B1", n_boot),
        E.day_bootstrap(wf.preds, "M1a", "B1", n_boot),
        *[E.day_bootstrap(wf.preds, m, "B1", n_boot, stat="bss") for m in ("B0", "M1a", "M1b")],
    ], ignore_index=True)
    cal = pd.concat([E.calibration(wf.preds, m, H) for m in MODELS for H in F.HORIZONS], ignore_index=True)
    # coefficients: the model the first test day uses (trained on the selection period)
    m1b = HZ.Hazard("M1b", HZ.M1B, best["M1b"])
    E.fit_on([m1b], g, rows, E.train_mask(g, D.TEST_START_DAY), E.midnight(D.TEST_START_DAY))
    coefs = m1b.coefs()
    res = {"C": best, "C_selection": csel, "metrics": mt, "bootstrap": boots, "calibration": cal, "coefs": coefs,
           "n_test_points": len(wf.preds), "n_test_days": int(wf.preds["day"].nunique())}
    for k in ("C_selection", "metrics", "bootstrap", "calibration"):
        res[k].to_csv(out / f"{k}.csv", index=False)
    coefs.to_csv(out / "coefs_M1b.csv")
    (out / "C.json").write_text(json.dumps(best))
    plots(res, reports_dir / "model")
    return res


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def plots(res: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    cal = res["calibration"]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.6), facecolor=SURFACE)
    for ax, H in zip(axes, F.HORIZONS, strict=True):
        _style(ax)
        ax.plot([0, 1], [0, 1], color=MUTED, linewidth=1, linestyle=(0, (3, 3)))
        for m in MODELS:
            c = cal[(cal["model"] == m) & (cal["H"] == H) & (cal["n"] >= 30)]
            ax.plot(c["p_mean"], c["y_mean"], color=COLORS[m], linewidth=2, marker="o", markersize=4,
                    markeredgecolor=SURFACE, markeredgewidth=1, label=m)
        ax.set_title(f"H = {H} хв", color=INK, fontsize=10, loc="left")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xlabel("прогноз P(старт ≤ H)", color=MUTED, fontsize=8)
    axes[0].set_ylabel("частка фактичних стартів", color=MUTED, fontsize=8)
    axes[-1].legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left")
    fig.suptitle("Калібрування на тесті 09-13…10-11 (10 рівноширинних бінів, n ≥ 30)", color=INK, fontsize=11, x=0.01,
                 ha="left")
    fig.tight_layout()
    fig.savefig(out / "calibration.png", dpi=130, facecolor=SURFACE)
    plt.close(fig)

    b = res["bootstrap"]
    b = b[b["stat"] == "bss"]
    fig, ax = plt.subplots(figsize=(7, 3.8), facecolor=SURFACE)
    _style(ax)
    ax.axhline(0, color=MUTED, linewidth=1)
    for i, m in enumerate(["B0", "M1a", "M1b"]):
        r = b[b["a"] == m]
        x = np.arange(len(F.HORIZONS)) + (i - 1) * 0.18
        ax.errorbar(x, r["point"], yerr=[r["point"] - r["lo"], r["hi"] - r["point"]], fmt="o", color=COLORS[m],
                    markersize=6, elinewidth=2, capsize=0, label=m)
    ax.set_xticks(np.arange(len(F.HORIZONS)), [f"{h} хв" for h in F.HORIZONS])
    ax.set_ylabel("Brier skill score vs B1", color=MUTED, fontsize=8)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower left")
    ax.set_title("BSS відносно B1 (14-денна частота), 95% CI bootstrap по днях", color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(out / "bss.png", dpi=130, facecolor=SURFACE)
    plt.close(fig)


def duration_check(alerts: pd.DataFrame) -> dict:
    from airalert.model import duration as U

    day = kyiv_day(alerts["started_at"])
    before_test = day < D.TEST_START_DAY
    test = alerts[(day >= D.TEST_START_DAY) & (day <= D.TEST_END_DAY)]
    tr17 = alerts[(alerts["started_at"] >= U.KM_START) & before_test]
    tr06 = alerts[(alerts["started_at"] >= pd.Timestamp("2026-06-01T00:00Z")) & before_test]

    def med(a):
        d = (a["finished_at"] - a["started_at"]).dt.total_seconds() / 60
        return float(d[~a["naive"]].median())

    km = U.KM.fit(tr17)
    return {
        "median_before": med(alerts[(alerts["started_at"] >= "2026-06-01") & (alerts["started_at"] < U.KM_START)]),
        "median_train": med(tr17), "median_test": med(test), "n_km": len(tr17), "km_median": km.median(),
        "checks": {"08-17": U.test_check(km, test), "06-01": U.test_check(U.KM.fit(tr06), test)},
    }


def evaluate_all(data_dir: Path, reports_dir: Path, n_trips: int = 2000) -> dict:
    from airalert.model import report

    res = run_eval(data_dir, reports_dir)
    product = product_model(res["metrics"])
    sources, end = load(data_dir)
    dur = duration_check(sources.alerts)
    bt = backtest(data_dir, product, n_trips=n_trips)
    bt.to_parquet(eval_dir(data_dir) / "backtest.parquet", index=False)
    bts = backtest_summary(bt, product)
    out = eval_dir(data_dir)
    (out / "backtest_summary.json").write_text(json.dumps(bts, indent=1, default=float))
    (out / "duration.json").write_text(json.dumps(
        {k: (v if k != "checks" else {s: t.to_dict("records") for s, t in v.items()}) for k, v in dur.items()},
        indent=1, default=float))
    (out / "summary.json").write_text(json.dumps({"product": product, "C": res["C"], "code_sha": git_sha(),
                                                  "run_at": datetime.now(UTC).isoformat(),
                                                  "n_test_points": res["n_test_points"],
                                                  "n_test_days": res["n_test_days"]}, indent=1))
    md = report.render(res, dur, bts, product, git_sha(), period_counts(sources.alerts, end))
    (reports_dir / "model_eval.md").write_text(md, encoding="utf-8")
    return {"res": res, "product": product, "bt": bts, "dur": dur}


# ---------------------------------------------------------------- step 4: product backtest, final ensemble

N_MEMBERS = 5
FINAL_FILE = "model_final.pkl"


def product_model(metrics: pd.DataFrame) -> str:
    """The better of M1a / M1b by mean Brier over horizons on the test (ТЗ: «у продукт іде краща з двох»)."""
    b = metrics[metrics["model"].isin(["M1a", "M1b"])].groupby("model")["brier"].mean()
    return str(b.idxmin())


def km_before(alerts: pd.DataFrame, day) -> "object":
    from airalert.model import duration as U
    from airalert.model import evaluate as E

    a = alerts[(alerts["started_at"] >= U.KM_START) & (alerts["finished_at"] < E.midnight(day))]
    return U.KM.fit(a)


def backtest(data_dir: Path, model: str, n_trips: int = 2000, n_scen: int = 200, seed: int = 0) -> pd.DataFrame:
    """Random trips in the test window: predicted P(success) from scenarios generated at t with the day's
    walk-forward model vs the outcome under the real alerts; the same with B1 scenarios."""
    from airalert.model import scenarios as S
    from airalert.model import sim

    sources, _ = load(data_dir)
    alerts = sources.alerts
    g = pd.read_parquet(data_dir / "processed" / GRID_FILE)
    preds = pd.read_parquet(eval_dir(data_dir) / "preds.parquet")
    hz = np.load(eval_dir(data_dir) / "hazards.npz")
    pos = {t: i for i, t in enumerate(preds["t"])}
    p = F.Prepared(sources)
    gt = g[(kyiv_day(g["t"]) >= D.TEST_START_DAY) & (kyiv_day(g["t"]) <= D.TEST_END_DAY)].reset_index(drop=True)
    rng = np.random.default_rng(seed)
    kms: dict = {}
    real_s = alerts["started_at"].to_numpy(dtype="datetime64[ns]")
    real_e = alerts["finished_at"].to_numpy(dtype="datetime64[ns]")
    rows = []
    while len(rows) < n_trips:
        r = gt.iloc[int(rng.integers(len(gt)))]
        t = r["t"]
        on, start = F.alert_state(p, t)
        if not on and t not in pos:
            continue  # known calm but an alert already (unknowingly) on: no forecast row
        day = kyiv_day(pd.Series([t]))[0]
        km = kms.setdefault(day, km_before(alerts, day))
        elapsed = float((F._t64(t) - start) / F.MIN) if on else None
        travel = float(rng.uniform(10, 40))
        wait_max = float(rng.choice([0, 15]))
        params = {"depart_in": 0, "travel": travel, "shop_mean": 60, "shop_sd": 15, "wait_max": wait_max,
                  "open_delay": 0}
        sd = int(rng.integers(2**31))
        T = sim.shop_time(sd, 60, 15)
        # truth: real alerts relative to t (minutes), no horizon
        tt = F._t64(t)
        near = (real_s < tt + np.timedelta64(400, "m")) & ((real_e > tt - np.timedelta64(1, "D")) | np.isnat(real_e))
        truth = [[float((s - tt) / F.MIN), None if np.isnat(e) else float((e - tt) / F.MIN)]
                 for s, e in zip(real_s[near], real_e[near], strict=True)]
        y, _ = sim.trip(truth, math.inf, 0, 0, travel, T, wait_max, 0)
        row = {"t": t, "day": day, "alert_now": on, "travel": travel, "wait_max": wait_max, "shop": T,
               "success": float(y == "success")}
        for name in (model, "B1"):
            h = hz[name][pos[t]] if not on else np.zeros(F.N_STEPS)
            sc = S.generate([h], km, float(r["rate_14d"]), elapsed, n_per_member=n_scen, seed=sd)
            res = sim.simulate(sc, 0.0, params, seed=sd, curve=False)
            row[f"p_{name}"], row[f"beyond_{name}"] = res["p"], res["share_beyond"]
        rows.append(row)
    return pd.DataFrame(rows)


def backtest_summary(bt: pd.DataFrame, model: str, n_boot: int = 1000, seed: int = 0) -> dict:
    from airalert.model import evaluate as E

    d = bt.dropna(subset=[f"p_{model}", "p_B1"])
    y = d["success"].to_numpy()
    out = {"n_trips": len(bt), "n_scored": len(d), "success_rate": float(y.mean()),
           "share_alert_now": float(d["alert_now"].mean())}
    for name in (model, "B1"):
        p = d[f"p_{name}"].to_numpy()
        out[name] = {"brier": E.brier(p, y), "mean_p": float(p.mean())}
    out["bss_vs_B1"] = 1 - out[model]["brier"] / out["B1"]["brier"]
    rng = np.random.default_rng(seed)
    days = d["day"].to_numpy()
    ud = np.unique(days)
    ea = pd.Series((d[f"p_{model}"].to_numpy() - y) ** 2).groupby(days).sum()
    eb = pd.Series((d["p_B1"].to_numpy() - y) ** 2).groupby(days).sum()
    boots = []
    for _ in range(n_boot):
        s = rng.choice(ud, len(ud))
        boots.append(1 - ea.loc[s].sum() / eb.loc[s].sum())
    out["bss_ci"] = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
    cal = {}
    for name in (model, "B1"):
        p = d[f"p_{name}"].to_numpy()
        q = np.unique(np.quantile(p, np.linspace(0, 1, 11)))
        b = np.clip(np.searchsorted(q, p, "right") - 1, 0, len(q) - 2)
        c = pd.DataFrame({"b": b, "p": p, "y": y}).groupby("b").agg(p_mean=("p", "mean"), y_mean=("y", "mean"),
                                                                     n=("y", "size"))
        cal[name] = c.reset_index(drop=True).to_dict("records")
    out["calibration"] = cal
    for k, sub in (("calm_now", d[~d["alert_now"]]), ("alert_now", d[d["alert_now"]])):
        yy = sub["success"].to_numpy()
        out[k] = {"n": len(sub), "success_rate": float(yy.mean()) if len(sub) else None,
                  **{f"brier_{n}": E.brier(sub[f"p_{n}"].to_numpy(), yy) for n in (model, "B1")}}
    return out


CARD_FILE = "model_card.json"
SKILL_BUCKETS = {"0-30": 30, "30-60": 60, "60-120": 120}


def model_card(data_dir: Path, updated_at: str | None = None, db: Path | None = None) -> dict:
    """data/processed/model_card.json from the saved evaluation run (raw numbers, no rounding in our favour)."""
    ev = eval_dir(data_dir)
    summ = json.loads((ev / "summary.json").read_text())
    product = summ["product"]
    mt = pd.read_csv(ev / "metrics.csv")
    boots = pd.read_csv(ev / "bootstrap.csv")
    cal = pd.read_csv(ev / "calibration.csv")
    bt = json.loads((ev / "backtest_summary.json").read_text())
    dur = json.loads((ev / "duration.json").read_text())
    sources, _ = load(data_dir, db)
    a = sources.alerts
    day = kyiv_day(a["started_at"])
    n_test_starts = int(((day >= D.TEST_START_DAY) & (day <= D.TEST_END_DAY)).sum())

    def bss(H):
        r = mt[(mt["model"] == product) & (mt["H"] == H)]
        return float(r["bss_vs_B1"].iloc[0])

    bss_ci = boots[(boots["stat"] == "bss") & (boots["a"] == product)]
    ab = boots[(boots["stat"] == "diff") & (boots["a"] == "M1b") & (boots["b"] == "M1a")]
    card = {
        "updated_at": updated_at or datetime.now(UTC).isoformat(),
        "evaluated_at": summ["run_at"],
        "code_sha": summ["code_sha"],
        "product_model": product,
        "test_period": [str(D.TEST_START_DAY), str(D.TEST_END_DAY)],
        "n_test_starts": n_test_starts,
        "n_test_points": summ["n_test_points"],
        "reference": "B1 (14-day rate)",
        "skill": {k: bss(H) for k, H in SKILL_BUCKETS.items()},
        "metrics": mt.to_dict("records"),
        "bss_ci": bss_ci[["H", "point", "lo", "hi"]].to_dict("records"),
        "calibration": cal[cal["model"].isin([product, "B1"])].to_dict("records"),
        "ablation": {"comparison": "M1b (with drone features) − M1a (alerts + time), Brier",
                     "by_horizon": ab[["H", "point", "lo", "hi"]].to_dict("records"),
                     "significant": bool(((ab["hi"] < 0) | (ab["lo"] > 0)).any())},
        "duration": {"km_from": "2026-08-17", "median_min": dur["km_median"], "n": dur["n_km"],
                     "check": dur["checks"]["08-17"]},
        "product_backtest": {k: bt[k] for k in ("n_trips", "success_rate", "bss_vs_B1", "bss_ci", product, "B1",
                                                "calibration")},
        "notes": ("Ймовірності — оцінка шансу встигнути, не порада з безпеки. Ознаки дронів не покращили прогноз на "
                  "тесті (див. ablation), тому в продукті модель без них. Тест: один місяць з вищою інтенсивністю "
                  "тривог, ніж у навчанні; довірчі інтервали широкі."),
    }
    out = data_dir / "processed" / CARD_FILE
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(card, ensure_ascii=False, indent=1, default=float))
    tmp.replace(out)
    return card


def fit_final(data_dir: Path, model: str, C: float, seed: int = 0, db: Path | None = None) -> dict:
    """Product model refit on all data whose label window closed (t + 120 min ≤ data end) + N_MEMBERS refits on
    day-bootstraps → data/processed/model_final.pkl (members, KM, metadata)."""
    import pickle

    sources, end = load(data_dir, db)
    g = pd.read_parquet(data_dir / "processed" / GRID_FILE)
    art = fit_members(g, sources.alerts, end, model, C, seed)
    out = data_dir / "processed" / FINAL_FILE
    tmp = out.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(art, f)
    tmp.replace(out)  # atomic: the API never sees a half-written file
    return art


def fit_members(g: pd.DataFrame, alerts: pd.DataFrame, end: pd.Timestamp, model: str, C: float,
                seed: int = 0) -> dict:
    """The ensemble on grid rows with t + 120 min ≤ end (members on day-bootstraps) + KM on alerts since KM_START."""
    from airalert.model import duration as U
    from airalert.model import hazard as HZ

    rows = F.hazard_rows(g)
    mask = ((g["t"] >= D.TRAIN_START) & (g["t"] + pd.Timedelta(minutes=120) <= end)).to_numpy()
    rows = rows[mask[rows["row"].to_numpy()]]
    w = HZ.recency_weights(g["t"], end)
    days = kyiv_day(g["t"]).to_numpy()
    ud = np.unique(days[mask])
    cols = HZ.M1A if model == "M1a" else HZ.M1B
    rng = np.random.default_rng(seed)
    members = []
    for _ in range(N_MEMBERS):
        cnt = pd.Series(rng.choice(ud, len(ud))).value_counts()
        mult = pd.Series(days).map(cnt).fillna(0).to_numpy()
        keep = rows[mult[rows["row"].to_numpy()] > 0]
        members.append(HZ.Hazard(model, cols, C).fit(g, keep, w * mult))
    km = U.KM.fit(alerts[alerts["started_at"] >= U.KM_START])
    return {"model": model, "C": C, "members": members, "km_S": km.S, "fitted_at": datetime.now(UTC).isoformat(),
            "train_end": end.isoformat(), "code_sha": git_sha()}
