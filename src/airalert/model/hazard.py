"""Discrete-time logistic hazard: a separate L2 logistic regression per block of steps.

Blocks {1–3, 4–6, 7–12, 13–24}: within a block the step enters as one-hot dummies, the features are shared, so the
coefficients show how a feature's effect fades with the horizon. Features are transformed (log1p for counts,
distance / cap), standardised inside the fold, rows weighted by recency (half-life 14 days to the fold end).
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from airalert.model import features as F

BLOCKS = ((1, 3), (4, 6), (7, 12), (13, 24))
HALF_LIFE_DAYS = 14.0
M1A = F.BASE_FEATURES
M1B = F.ALL_FEATURES


def design(g: pd.DataFrame, cols: list[str]) -> np.ndarray:
    out = []
    for c in cols:
        x = g[c].to_numpy(dtype=float)
        if c.startswith(("n_", "kps_n_")):
            x = np.log1p(x)
        elif "min_dist_km" in c:
            x = x / F.DIST_CAP
        out.append(x)
    return np.column_stack(out)


def recency_weights(t: pd.Series, end: pd.Timestamp, half_life_days: float = HALF_LIFE_DAYS) -> np.ndarray:
    age = (end - pd.to_datetime(t, utc=True)).dt.total_seconds().to_numpy() / 86400
    return 0.5 ** (np.clip(age, 0, None) / half_life_days)


class Hazard:
    def __init__(self, name: str, cols: list[str], C: float = 1.0):
        self.name, self.cols, self.C = name, cols, C

    def fit(self, g: pd.DataFrame, rows: pd.DataFrame, w_t: np.ndarray | None = None) -> "Hazard":
        """``g`` grid (index = ``rows.row``), ``rows`` hazard rows, ``w_t`` weight per grid row."""
        X = design(g, self.cols)
        self.scaler = StandardScaler().fit(X[np.unique(rows["row"].to_numpy())])
        Xs = self.scaler.transform(X)
        w = np.ones(len(g)) if w_t is None else w_t
        self.models = []
        for lo, hi in BLOCKS:
            r = rows[(rows["k"] >= lo) & (rows["k"] <= hi)]
            Z = np.hstack([Xs[r["row"].to_numpy()], self._dummies(r["k"].to_numpy(), lo, hi)])
            y = r["y"].to_numpy()
            m = LogisticRegression(C=self.C, max_iter=2000, fit_intercept=False)
            m.fit(Z, y, sample_weight=w[r["row"].to_numpy()])
            self.models.append(m)
        return self

    @staticmethod
    def _dummies(k: np.ndarray, lo: int, hi: int) -> np.ndarray:
        return (k[:, None] == np.arange(lo, hi + 1)[None, :]).astype(float)

    def hazards(self, g: pd.DataFrame) -> np.ndarray:
        Xs = self.scaler.transform(design(g, self.cols))
        h = np.empty((len(g), F.N_STEPS))
        for (lo, hi), m in zip(BLOCKS, self.models, strict=True):
            for k in range(lo, hi + 1):
                Z = np.hstack([Xs, self._dummies(np.full(len(g), k), lo, hi)])
                h[:, k - 1] = m.predict_proba(Z)[:, 1]
        return h

    def coefs(self) -> pd.DataFrame:
        """Standardised feature coefficients per block (the step dummies left out)."""
        return pd.DataFrame(
            {f"k{lo}-{hi}": m.coef_[0][: len(self.cols)] for (lo, hi), m in zip(BLOCKS, self.models, strict=True)},
            index=self.cols,
        )
