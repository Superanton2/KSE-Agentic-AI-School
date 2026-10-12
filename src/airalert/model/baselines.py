"""Baselines. Both return per-step hazards h[t, k] (k = 1…24) so every model is evaluated the same way.

- ``B0`` — one constant hazard per 5-min step: the (recency-weighted) mean over the training hazard rows.
- ``B1`` — 14-day rate: λ = starts / calm hours over the 14 days before t (feature ``rate_14d``), constant hazard
  h = 1 − exp(−λ·5 min), so P(start ≤ H) = 1 − exp(−λH).
"""

import numpy as np
import pandas as pd

from airalert.model.features import N_STEPS, STEP_MIN


class B0:
    name = "B0"

    def fit(self, g: pd.DataFrame, rows: pd.DataFrame, w: np.ndarray | None = None) -> "B0":
        self.h = float(np.average(rows["y"], weights=w))
        return self

    def hazards(self, g: pd.DataFrame) -> np.ndarray:
        return np.full((len(g), N_STEPS), self.h)


class B1:
    name = "B1"

    def fit(self, g=None, rows=None, w=None) -> "B1":
        return self

    def hazards(self, g: pd.DataFrame) -> np.ndarray:
        lam = g["rate_14d"].to_numpy(dtype=float)[:, None]  # per hour
        return np.repeat(1 - np.exp(-lam * STEP_MIN / 60), N_STEPS, axis=1)


def cum_prob(h: np.ndarray, horizon_min: int) -> np.ndarray:
    """P(start ≤ H) = 1 − Π_{k ≤ H/5} (1 − h_k)."""
    return 1 - np.prod(1 - h[:, : horizon_min // STEP_MIN], axis=1)
