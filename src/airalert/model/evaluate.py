"""Walk-forward evaluation with purge, metrics, day-bootstrap CIs, calibration.

For a forecast day d (Kyiv), a model is trained on grid points t with t + 120 min ≤ 00:00 of d (the label window
closed before d — otherwise the label leaks), and predicts every calm t of d. Refit daily.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from airalert.model import baselines as BL
from airalert.model import features as F
from airalert.model import hazard as HZ
from airalert.model.data import KYIV_TZ, TRAIN_START

LABEL_WINDOW = pd.Timedelta(minutes=F.N_STEPS * F.STEP_MIN)
C_GRID = (0.003, 0.01, 0.03, 0.1, 0.3, 1.0)
EPS = 1e-6


def midnight(day) -> pd.Timestamp:
    return pd.Timestamp(day).tz_localize(KYIV_TZ).tz_convert("UTC")


def train_mask(g: pd.DataFrame, day) -> np.ndarray:
    return ((g["t"] >= TRAIN_START) & (g["t"] + LABEL_WINDOW <= midnight(day))).to_numpy()


def day_mask(g: pd.DataFrame, day) -> np.ndarray:
    return ((g["t"] >= midnight(day)) & (g["t"] < midnight(day + pd.Timedelta(days=1)))).to_numpy()


def make_models(C_a: float, C_b: float) -> list:
    return [BL.B0(), BL.B1(), HZ.Hazard("M1a", HZ.M1A, C_a), HZ.Hazard("M1b", HZ.M1B, C_b)]


def fit_on(models: list, g: pd.DataFrame, rows: pd.DataFrame, mask: np.ndarray, end: pd.Timestamp) -> list:
    keep = rows[mask[rows["row"].to_numpy()]]
    w = HZ.recency_weights(g["t"], end)
    for m in models:
        m.fit(g, keep, w if isinstance(m, HZ.Hazard) else w[keep["row"].to_numpy()])
    return models


@dataclass
class WalkForward:
    preds: pd.DataFrame  # one row per calm test t: t, day, y_H, P_H for each model
    hazards: dict[str, np.ndarray] = field(default_factory=dict)  # model -> (n, 24), rows aligned with preds
    n_train_rows: dict = field(default_factory=dict)


def walk_forward(g: pd.DataFrame, rows: pd.DataFrame, days: list, C_a: float, C_b: float,
                 refit_every: int = 1) -> WalkForward:
    out, hz = [], {}
    models = None
    for i, d in enumerate(days):
        if models is None or i % refit_every == 0:
            mask = train_mask(g, d)
            models = fit_on(make_models(C_a, C_b), g, rows, mask, midnight(d))
        sel = day_mask(g, d) & g["calm"].to_numpy()
        gd = g[sel]
        if not len(gd):
            continue
        p = gd[["t", *[f"y_{h}" for h in F.HORIZONS]]].copy()
        p["day"] = d
        for m in models:
            h = m.hazards(gd)
            hz.setdefault(m.name, []).append(h)
            for H in F.HORIZONS:
                p[f"{m.name}_{H}"] = BL.cum_prob(h, H)
        out.append(p)
    preds = pd.concat(out, ignore_index=True)
    return WalkForward(preds, {k: np.vstack(v) for k, v in hz.items()})


def brier(p, y) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(p, y) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def metrics(preds: pd.DataFrame, models: list[str], ref: str = "B1") -> pd.DataFrame:
    rows = []
    for H in F.HORIZONS:
        d = preds.dropna(subset=[f"y_{H}"])
        y = d[f"y_{H}"].to_numpy()
        b_ref = brier(d[f"{ref}_{H}"].to_numpy(), y)
        for m in models:
            p = d[f"{m}_{H}"].to_numpy()
            b = brier(p, y)
            rows.append({"H": H, "model": m, "n": len(d), "base_rate": float(y.mean()), "mean_p": float(p.mean()),
                         "brier": b, "logloss": logloss(p, y), "bss_vs_B1": 1 - b / b_ref})
    return pd.DataFrame(rows)


def day_bootstrap(preds: pd.DataFrame, a: str, b: str, n_boot: int = 1000, seed: int = 0,
                  stat: str = "diff") -> pd.DataFrame:
    """Per H: point + 95% CI of Brier(a) − Brier(b) (``diff``) or BSS of a vs b (``bss``), resampling days."""
    rng = np.random.default_rng(seed)
    out = []
    for H in F.HORIZONS:
        d = preds.dropna(subset=[f"y_{H}"])
        y = d[f"y_{H}"].to_numpy()
        ea = (d[f"{a}_{H}"].to_numpy() - y) ** 2
        eb = (d[f"{b}_{H}"].to_numpy() - y) ** 2
        g = pd.DataFrame({"day": d["day"].to_numpy(), "ea": ea, "eb": eb, "n": 1}).groupby("day").sum()
        A, B, N = g["ea"].to_numpy(), g["eb"].to_numpy(), g["n"].to_numpy()
        f = (lambda A, B, N: (A.sum() - B.sum()) / N.sum()) if stat == "diff" else (lambda A, B, N: 1 - A.sum() / B.sum())
        idx = rng.integers(0, len(g), size=(n_boot, len(g)))
        boots = np.array([f(A[i], B[i], N[i]) for i in idx])
        lo, hi = np.percentile(boots, [2.5, 97.5])
        out.append({"H": H, "a": a, "b": b, "stat": stat, "point": f(A, B, N), "lo": lo, "hi": hi,
                    "p_a_better": float((boots < 0).mean() if stat == "diff" else (boots > 0).mean())})
    return pd.DataFrame(out)


def calibration(preds: pd.DataFrame, model: str, H: int, bins: int = 10) -> pd.DataFrame:
    """Equal-width bins of the predicted probability (all bins kept; plots hide n < 30)."""
    d = preds.dropna(subset=[f"y_{H}"])
    p, y = d[f"{model}_{H}"].to_numpy(), d[f"y_{H}"].to_numpy()
    b = np.clip((p * bins).astype(int), 0, bins - 1)
    r = pd.DataFrame({"b": b, "p": p, "y": y}).groupby("b").agg(p_mean=("p", "mean"), y_mean=("y", "mean"), n=("y", "size"))
    return r.reset_index().rename(columns={"b": "bin"}).assign(model=model, H=H)


def select_C(g: pd.DataFrame, rows: pd.DataFrame, val_days: list, refit_every: int = 4) -> tuple[dict, pd.DataFrame]:
    """Pick C for M1a and M1b by mean Brier over horizons on rolling validation days (training period only)."""
    res = []
    for C in C_GRID:
        wf = walk_forward(g, rows, val_days, C, C, refit_every=refit_every)
        mt = metrics(wf.preds, ["M1a", "M1b", "B1"])
        for m in ("M1a", "M1b"):
            res.append({"C": C, "model": m, "mean_brier": float(mt[mt["model"] == m]["brier"].mean())})
    res = pd.DataFrame(res)
    best = {m: float(res[res["model"] == m].sort_values("mean_brier").iloc[0]["C"]) for m in ("M1a", "M1b")}
    return best, res
