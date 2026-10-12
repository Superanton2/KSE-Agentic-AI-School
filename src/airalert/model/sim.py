"""Trip simulator over scenarios — the algorithm of ``docs/tasks/phase3_frontend_task.md`` («Браузерний симулятор»).

Deterministic and portable: the PRNG is mulberry32 seeded with ``seed + scenario index`` (32-bit integer maths
that JavaScript reproduces exactly), the normal draw is Box–Muller from two uniforms. Shared cases live in
``tests/fixtures/sim_cases.json``.

Per scenario s: T ~ N(shop_mean, shop_sd) clipped to [shop_min, shop_max] (default [20, 120]); arrive = elapsed +
depart_in + travel; the venue is closed on [start, end + open_delay) of every alert — if arrive falls in such an
interval: open − arrive ≤ wait_max → wait until open = end + open_delay, else failure; open + T > horizon → beyond
horizon; success iff no alert starts in (open, open + T]. With open_delay = 0 this is the original phase-3 rule.
"""

import math

import numpy as np

M32 = 0xFFFFFFFF
SHOP_MIN, SHOP_MAX = 20.0, 120.0
CURVE_STEP, CURVE_MAX = 5, 60


def _imul(a: int, b: int) -> int:
    return (a * b) & M32


def mulberry32(seed: int):
    a = seed & M32

    def nxt() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & M32
        t = a
        t = _imul(t ^ (t >> 15), t | 1)
        t ^= (t + _imul(t ^ (t >> 7), t | 61)) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return nxt


def shop_time(seed: int, mean: float, sd: float, lo: float = SHOP_MIN, hi: float = SHOP_MAX) -> float:
    r = mulberry32(seed)
    u1, u2 = r(), r()
    z = math.sqrt(-2.0 * math.log(1.0 - u1)) * math.cos(2.0 * math.pi * u2)
    return min(max(mean + sd * z, lo), hi)


def trip(alerts: list, horizon: float, elapsed: float, depart_in: float, travel: float, T: float,
         wait_max: float, open_delay: float) -> tuple[str, float | None]:
    """→ (outcome ∈ success | fail | beyond, wait or None if no alert on arrival)."""
    arrive = elapsed + depart_in + travel
    wait = None
    open_ = arrive
    for s, e in alerts:
        if s <= arrive and (e is None or e + open_delay > arrive):
            wait = math.inf if e is None else e + open_delay - arrive
            if wait > wait_max:
                return "fail", wait
            open_ = e + open_delay
            break
    if open_ + T > horizon:
        return "beyond", wait
    for s, _ in alerts:
        if open_ < s <= open_ + T:
            return "fail", wait
    return "success", wait


def _pct(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile; None if empty or the rank falls on an endless alert."""
    if not xs:
        return None
    s = sorted(xs)
    v = s[max(math.ceil(q / 100 * len(s)) - 1, 0)]
    return v if math.isfinite(v) else None


def simulate(scen: dict, elapsed_min: float, params: dict, seed: int = 0, curve: bool = True) -> dict:
    sc = scen["scenarios"]
    H = scen["horizon_min"]
    members = scen.get("members", 1)
    lo, hi = params.get("shop_min", SHOP_MIN), params.get("shop_max", SHOP_MAX)
    Ts = [shop_time(seed + i, params["shop_mean"], params["shop_sd"], lo, hi) for i in range(len(sc))]

    def run(depart_in: float) -> dict:
        ok = np.zeros(members)
        tot = np.zeros(members)
        beyond, waits = 0, []
        for s, T in zip(sc, Ts, strict=True):
            out, w = trip(s["alerts"], H, elapsed_min, depart_in, params["travel"], T, params["wait_max"],
                          params["open_delay"])
            if w is not None:
                waits.append(w)
            if out == "beyond":
                beyond += 1
                continue
            tot[s["m"]] += 1
            ok[s["m"]] += out == "success"
        n = tot.sum()
        per = [ok[m] / tot[m] for m in range(members) if tot[m] > 0]
        return {
            "p": float(ok.sum() / n) if n else None,
            "p_band": [float(_pct(per, 10)), float(_pct(per, 90))] if per else None,
            "share_beyond": beyond / len(sc) if sc else 0.0,
            "wait_median": _pct(waits, 50),
            "wait_p80": _pct(waits, 80),
        }

    res = run(params["depart_in"])
    if curve:
        pts = [{"depart_in": d, "p": run(d)["p"]} for d in range(0, CURVE_MAX + 1, CURVE_STEP)]
        res["curve"] = pts
        valid = [c for c in pts if c["p"] is not None]
        res["best"] = max(valid, key=lambda c: c["p"]) if valid else None
    return res
