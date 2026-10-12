"""sim.py on the shared cases (tests/fixtures/sim_cases.json — the same file a JS port must pass)."""

import itertools
import json
from pathlib import Path

import numpy as np
import pytest

from airalert.model import sim

FIX = json.loads((Path(__file__).parent / "fixtures" / "sim_cases.json").read_text())


@pytest.mark.parametrize("r", FIX["rng"], ids=lambda r: f"seed{r['seed']}")
def test_mulberry32_reference(r):
    g = sim.mulberry32(r["seed"])
    assert [g() for _ in r["uniforms"]] == r["uniforms"]


def test_mulberry32_known_value():
    assert sim.mulberry32(1)() == pytest.approx(0.6270739405881613, abs=0)


@pytest.mark.parametrize("r", FIX["shop_time"], ids=lambda r: f"seed{r['seed']}")
def test_shop_time(r):
    assert sim.shop_time(r["seed"], r["mean"], r["sd"]) == r["value"]


@pytest.mark.parametrize("c", FIX["cases"], ids=lambda c: c["name"])
def test_shared_cases(c):
    assert sim.simulate(c["scenarios"], c["elapsed_min"], c["params"], seed=c["seed"]) == c["expect"]


def _case(name):
    return next(c for c in FIX["cases"] if c["name"].startswith(name))


def test_semantics():
    assert _case("no alerts")["expect"]["p"] == 1
    assert _case("alert starts mid")["expect"]["p"] == 0
    ok = _case("current alert ends in 10, wait_max 15")["expect"]
    assert ok["p"] == 1 and ok["wait_median"] == 10
    assert _case("current alert ends in 10, wait_max 5")["expect"]["p"] == 0
    assert _case("open_delay 0")["expect"]["p"] == 1 and _case("open_delay 10")["expect"]["p"] == 0
    b = _case("beyond horizon")["expect"]
    assert b["p"] is None and b["share_beyond"] == 1


def _random_scen(seed=0, n=300):
    rng = np.random.default_rng(seed)
    sc = []
    for i in range(n):
        alerts, t = [], -float(rng.uniform(0, 30)) if rng.uniform() < 0.3 else float(rng.uniform(0, 60))
        while t < 120:
            e = t + float(rng.uniform(5, 60))
            alerts.append([round(t), None if e > 120 else round(e)])
            if e > 120:
                break
            t = e + float(rng.uniform(5, 80))
        sc.append({"m": i % 5, "alerts": alerts})
    return {"horizon_min": 120, "members": 5, "scenarios": sc}


BASE = {"depart_in": 0, "travel": 15, "shop_mean": 40, "shop_sd": 10, "wait_max": 10, "open_delay": 0}


def test_monotone_in_shop_mean_and_wait_max():
    sc = _random_scen()
    ps = [sim.simulate(sc, 0, {**BASE, "shop_mean": m}, curve=False)["p"] for m in (25, 40, 55, 70)]
    assert all(a >= b for a, b in itertools.pairwise(ps))
    ws = [sim.simulate(sc, 0, {**BASE, "wait_max": w}, curve=False)["p"] for w in (0, 10, 20, 40)]
    assert all(a <= b for a, b in itertools.pairwise(ws))


def test_deterministic_and_band():
    sc = _random_scen(1)
    a, b = sim.simulate(sc, 2, BASE, seed=5), sim.simulate(sc, 2, BASE, seed=5)
    assert a == b
    lo, hi = a["p_band"]
    assert lo <= hi and len(a["curve"]) == 13 and a["best"] in a["curve"]
