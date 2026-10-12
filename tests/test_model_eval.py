"""Purge, KM, scenario generator."""

import time

import numpy as np
import pandas as pd
import pytest

from airalert.model import duration as U
from airalert.model import evaluate as E
from airalert.model import features as F
from airalert.model import scenarios as S


def _grid():
    times = pd.date_range("2026-09-10T00:00Z", "2026-09-14T00:00Z", freq="5min")
    g = pd.DataFrame({"t": times, "calm": True, "k_first": 0, "n_obs": F.N_STEPS})
    return g


@pytest.mark.parametrize("day", ["2026-09-12", "2026-09-13"])
def test_purge_no_training_label_window_reaches_forecast_day(day):
    g = _grid()
    d = pd.Timestamp(day).date()
    mask = E.train_mask(g, d)
    rows = F.hazard_rows(g)
    rows = rows[mask[rows["row"].to_numpy()]]
    last = g["t"].dt.tz_localize(None).to_numpy()[rows["row"].to_numpy()] + (rows["k"].to_numpy() * F.STEP_MIN).astype("timedelta64[m]")
    assert (last <= E.midnight(d).tz_localize(None).to_datetime64()).all()
    assert mask.sum() > 0 and not (mask & E.day_mask(g, d)).any()
    # the last trainable point is exactly 120 min before midnight (Kyiv)
    assert g["t"][mask].max() == E.midnight(d) - pd.Timedelta(minutes=120)


def _alerts(durs, naive):
    s = pd.Timestamp("2026-09-01T00:00Z") + pd.to_timedelta(np.arange(len(durs)) * 1000, "min")
    return pd.DataFrame({"started_at": s, "finished_at": s + pd.to_timedelta(durs, "min"), "naive": naive})


def test_km_naive_is_censored():
    km_c = U.KM.fit(_alerts([30.0] * 10 + [60.0] * 10, [True] * 10 + [False] * 10))
    km_e = U.KM.fit(_alerts([30.0] * 10 + [60.0] * 10, [False] * 20))
    assert km_c.surv(45) == pytest.approx(1.0)  # censored at 30 → no event before 60
    assert km_e.surv(45) == pytest.approx(0.5)


def test_km_conditional_monotone_in_x():
    rng = np.random.default_rng(0)
    km = U.KM.fit(_alerts(rng.exponential(40, 300) + 1, rng.uniform(size=300) < 0.1))
    for e in (0, 10, 30, 90):
        p = km.p_end_within(e, np.arange(0, 200))
        assert (np.diff(p) >= -1e-12).all() and p[0] == pytest.approx(0) and (p <= 1).all()


@pytest.fixture
def km():
    rng = np.random.default_rng(1)
    return U.KM.fit(_alerts(rng.exponential(35, 200) + 1, np.zeros(200, bool)))


def _check_schema(out, members, horizon=120):
    assert set(out) == {"generated_at", "horizon_min", "members", "scenarios"}
    assert out["horizon_min"] == horizon and out["members"] == members
    assert out["generated_at"].endswith("Z")
    assert {s["m"] for s in out["scenarios"]} == set(range(members))
    for s in out["scenarios"]:
        prev_end = None
        for i, (a, b) in enumerate(s["alerts"]):
            assert isinstance(a, int) and (b is None or isinstance(b, int))
            assert a <= horizon
            if b is not None:
                assert a < b <= horizon
            else:
                assert i == len(s["alerts"]) - 1
            if prev_end is not None:
                assert a > prev_end  # sorted, no overlap
            prev_end = b


def test_scenarios_calm(km):
    t0 = time.perf_counter()
    out = S.generate([np.full(24, 0.03)] * 5, km, 0.3, None, n_per_member=200, seed=1)
    assert time.perf_counter() - t0 < 1.0
    _check_schema(out, 5)
    assert len(out["scenarios"]) == 1000
    assert all(a >= 0 for s in out["scenarios"] for a, _ in s["alerts"])
    import json

    assert len(json.dumps(out, separators=(",", ":"))) <= 60_000


def test_scenarios_alert_now(km):
    out = S.generate([np.full(24, 0.03)] * 5, km, 0.3, 12.0, n_per_member=50, seed=2)
    _check_schema(out, 5)
    assert all(s["alerts"][0][0] == -12 for s in out["scenarios"])


def test_first_start_distribution():
    h = np.full(24, 0.05)
    m = S.first_start_minutes(h, np.random.default_rng(0), 200_000)
    assert np.isinf(m).mean() == pytest.approx(0.95**24, abs=0.005)
    assert (m[np.isfinite(m)] > 0).all() and (m[np.isfinite(m)] <= 120).all()
