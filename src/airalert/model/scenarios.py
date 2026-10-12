"""Scenario generator for ``GET /api/scenarios``.

Per ensemble member m (a refit of the product model on a day-bootstrap of the training data), ``n`` scenarios:
- calm now: the first start comes from the member's hazards h_1…h_24 (step k, minute uniform inside the step);
- alert now: the current interval is [−elapsed, end], end from the conditional KM;
- every alert lasts a KM draw; the next starts after an end are exponential with the 14-day rate λ (B1).
Approximation: after the first start we do not re-run the hazard model (features would depend on the simulated
future); λ ignores the time of day. Ends past the horizon (or past the KM support) → ``null``.
"""

from datetime import UTC, datetime

import numpy as np

from airalert.model.duration import KM
from airalert.model.features import N_STEPS, STEP_MIN

HORIZON_MIN = N_STEPS * STEP_MIN


def first_start_minutes(h: np.ndarray, rng: np.random.Generator, n: int) -> np.ndarray:
    """Minutes to the first start under per-step hazards ``h`` (inf if none within the horizon)."""
    surv = np.concatenate([[1.0], np.cumprod(1 - h)])
    pmf = surv[:-1] * h  # P(first start on step k)
    cdf = np.cumsum(pmf)
    u = rng.uniform(size=n)
    k = np.searchsorted(cdf, u, "right")  # 0-based step; N_STEPS = none
    m = (k + rng.uniform(size=n)) * STEP_MIN
    return np.where(k >= N_STEPS, np.inf, m)


def one_scenario(first: float, elapsed: float | None, km: KM, lam_per_min: float, rng: np.random.Generator,
                 horizon: int = HORIZON_MIN) -> list[list]:
    alerts: list[list] = []
    if elapsed is not None:
        start = -float(elapsed)
        end = float(km.sample_remaining(elapsed, rng, 1)[0])  # minutes from now
    else:
        start = first
        if not np.isfinite(start) or start > horizon:
            return alerts
        end = start + float(km.sample_remaining(0, rng, 1)[0])
    while True:
        s_i = int(np.floor(start)) if start < 0 else max(round(start), 0)
        if alerts and s_i <= alerts[-1][1]:
            s_i = alerts[-1][1] + 1
        if s_i > horizon:
            return alerts
        if not np.isfinite(end) or end > horizon:
            alerts.append([s_i, None])
            return alerts
        e_i = max(round(end), s_i + 1)
        alerts.append([s_i, e_i])
        if lam_per_min <= 0:
            return alerts
        start = end + rng.exponential(1 / lam_per_min)
        if start > horizon:
            return alerts
        end = start + float(km.sample_remaining(0, rng, 1)[0])


def generate(member_hazards: list[np.ndarray], km: KM, rate_per_hour: float, elapsed: float | None,
             n_per_member: int = 200, seed: int = 0, generated_at: datetime | None = None) -> dict:
    """``elapsed`` = minutes since the current alert started (None if calm)."""
    rng = np.random.default_rng(seed)
    lam = rate_per_hour / 60
    out = []
    for m, h in enumerate(member_hazards):
        firsts = first_start_minutes(h, rng, n_per_member) if elapsed is None else np.full(n_per_member, np.nan)
        for f in firsts:
            out.append({"m": m, "alerts": one_scenario(float(f), elapsed, km, lam, rng)})
    ga = (generated_at or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    return {"generated_at": ga.isoformat().replace("+00:00", "Z"), "horizon_min": HORIZON_MIN,
            "members": len(member_hazards), "scenarios": out}
