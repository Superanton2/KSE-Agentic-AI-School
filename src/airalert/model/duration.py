"""Kaplan–Meier model of Kyiv alert duration; ``naive`` ends (imputed start + 30 min) are censored at 30 min.

Conditional: P(end ≤ e + x | still on at e) = 1 − S(e + x) / S(e). Mass left beyond the last KM time is "longer
than we can say" (sampled as end = None).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter

MAX_MIN = 24 * 60
NAIVE_CENSOR_MIN = 30.0
KM_START = pd.Timestamp("2026-08-17T00:00Z")  # regime change; durations before were shorter (see report)


def durations(alerts: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(duration min, observed) — naive ends censored at 30 min; open alerts censored at their known age."""
    d = (alerts["finished_at"] - alerts["started_at"]).dt.total_seconds().to_numpy() / 60
    obs = ~alerts["naive"].to_numpy() & ~np.isnan(d)
    d = np.where(alerts["naive"].to_numpy(), NAIVE_CENSOR_MIN, d)
    return np.clip(np.nan_to_num(d, nan=0.0), 0.1, MAX_MIN), obs


@dataclass
class KM:
    S: np.ndarray  # S[m] = P(duration > m minutes), m = 0…MAX_MIN

    @classmethod
    def fit(cls, alerts: pd.DataFrame) -> "KM":
        d, obs = durations(alerts)
        k = KaplanMeierFitter().fit(d, obs)
        S = k.survival_function_at_times(np.arange(MAX_MIN + 1)).to_numpy()
        return cls(np.minimum.accumulate(S))

    def surv(self, m) -> np.ndarray:
        return self.S[np.clip(np.asarray(m, dtype=int), 0, MAX_MIN)]

    def p_end_within(self, elapsed, x) -> np.ndarray:
        """P(end ≤ elapsed + x | on at elapsed)."""
        se = np.maximum(self.surv(elapsed), 1e-12)
        return 1 - self.surv(np.asarray(elapsed) + np.asarray(x)) / se

    def median(self) -> float:
        i = np.flatnonzero(self.S <= 0.5)
        return float(i[0]) if len(i) else float("nan")

    def sample_remaining(self, elapsed: float, rng: np.random.Generator, n: int) -> np.ndarray:
        """Remaining minutes until the end given ``elapsed``; inf if beyond the KM support."""
        se = max(float(self.surv(elapsed)), 1e-12)
        u = rng.uniform(size=n)
        target = u * se  # S(end) = u·S(e)  ⇔  end = first m ≥ e with S(m) ≤ target
        rev = self.S[::-1]  # increasing
        idx = MAX_MIN - np.searchsorted(rev, target, "left")
        m = np.where(target < self.S[-1], np.inf, np.maximum(idx, int(np.ceil(elapsed))) + rng.uniform(size=n))
        return np.maximum(m - elapsed, 0.5)


def test_check(km: KM, test_alerts: pd.DataFrame, at=(0, 10, 30), xs=(15, 30, 60)) -> pd.DataFrame:
    """For test alerts still on at e: mean predicted P(end ≤ e + x) vs observed share, Brier."""
    d, obs = durations(test_alerts)
    rows = []
    for e in at:
        on = d > e
        for x in xs:
            known = on & (obs | (d >= e + x))
            if not known.any():
                continue
            y = (d[known] <= e + x).astype(float)
            p = float(km.p_end_within(e, x))
            rows.append({"elapsed": e, "x": x, "n": int(known.sum()), "p_pred": p, "observed": float(y.mean()),
                         "brier": float(np.mean((p - y) ** 2))})
    return pd.DataFrame(rows)
