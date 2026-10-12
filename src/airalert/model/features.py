"""5-minute forecast grid, discrete-hazard labels and as-of features for the Kyiv alert model.

Everything is decided by ``known_at``: at t an alert is on if its start was known by t and its end was not.
``features_asof(t, sources)`` is the ONE function used in training and in the API; it only reads rows known by t,
so running it on full sources or on ``sources.truncate(t)`` gives identical numbers (tested).

Labels (only for calm t): first start after t falls on step k = ceil((start − t) / 5 min), k = 1…24; hazard rows
(t, k, y) stop at the first start and at the end of data (censoring).
"""

import math

import numpy as np
import pandas as pd

from airalert.drones.gazetteer import KYIV_LAT, KYIV_LON  # noqa: F401  (centre used by drone_mentions)
from airalert.model.data import KYIV_TZ, Sources

STEP_MIN = 5
N_STEPS = 24
HORIZONS = (15, 30, 60, 120)
RINGS = ((0, 30), (30, 80), (80, 150), (150, 300))
DIST_CAP = 400.0

GAP_CAP_MIN = 14 * 24 * 60
KYIV_OBLASTS = {"UA.12", "UA.13"}  # GeoNames admin1: Kyiv City, Kyivska oblast
MISSILE_KM = 120

ALERT_FEATURES = ["n_starts_6h", "n_starts_24h", "n_starts_72h", "rate_14d", "log_min_since_end", "log_last_dur"]
TIME_FEATURES = ["hour_sin", "hour_cos", "night"]


def _drone_names(prefix: str, w: int) -> list[str]:
    return [
        *[f"{prefix}n_ring{b}_{w}m" for _, b in RINGS],
        f"{prefix}n_target_ring30_{w}m",
        f"{prefix}n_jet_ring150_{w}m",
        f"{prefix}min_dist_km_{w}m",
        f"{prefix}none_{w}m",
    ]


DRONE_FEATURES = [
    *_drone_names("", 15),
    *_drone_names("", 30),
    *_drone_names("kps_", 30),
    "kyiv_nebo_any_10m",
    "missile_any_30m",
]
BASE_FEATURES = ALERT_FEATURES + TIME_FEATURES
ALL_FEATURES = BASE_FEATURES + DRONE_FEATURES


def _ns(x: pd.Series) -> np.ndarray:
    return pd.to_datetime(x, utc=True).dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")


def _t64(t: pd.Timestamp) -> np.datetime64:
    return np.datetime64(pd.Timestamp(t).tz_convert("UTC").tz_localize(None), "ns")


NAT = np.datetime64("NaT", "ns")
MIN = np.timedelta64(1, "m")


class Prepared:
    """Sources as sorted numpy arrays (pure function of the sources, no t involved)."""

    def __init__(self, s: Sources):
        a = s.alerts.sort_values("started_at")
        self.a_start = _ns(a["started_at"])
        self.a_end = _ns(a["finished_at"])
        self.a_sk = _ns(a["start_known_at"])
        self.a_ek = _ns(a["end_known_at"])
        m = s.mentions.sort_values(["posted_at", "channel", "msg_id", "version", "line_no"]).reset_index(drop=True)
        self.m_posted = _ns(m["posted_at"])
        self.m_known = _ns(m["known_at"])
        self.m_chan = m["channel"].to_numpy(dtype=object)
        self.m_msg = m["msg_id"].to_numpy(dtype=np.int64)
        self.m_ver = m["version"].to_numpy(dtype=np.int64)
        self.m_dist = m["dist_to_kyiv_km"].to_numpy(dtype=float)
        self.m_count = m["count"].astype("Float64").fillna(1.0).to_numpy(dtype=float)
        self.m_target = (m["rel"] == "target").to_numpy()
        self.m_jet = (m["kind"] == "drone_jet").to_numpy()
        near = m["oblast"].isin(KYIV_OBLASTS).to_numpy() | (self.m_dist <= MISSILE_KM) | (m["channel"] == "kyiv_nebo").to_numpy()
        self.m_missile = m["kind"].isin(["missile", "ballistic"]).to_numpy() & near


def alert_state(p: Prepared, t: pd.Timestamp) -> tuple[bool, np.datetime64 | None]:
    """(alert on at t as known at t, its start)."""
    tt = _t64(t)
    known = p.a_sk <= tt
    on = known & (np.isnat(p.a_ek) | (p.a_ek > tt))
    if on.any():
        return True, p.a_start[np.flatnonzero(on)[-1]]
    return False, None


def _alert_features(p: Prepared, tt: np.datetime64) -> dict:
    known = p.a_sk <= tt
    st = p.a_start[known]
    end_known = known & ~np.isnat(p.a_ek) & (p.a_ek <= tt)
    out = {}
    for h in (6, 24, 72):
        out[f"n_starts_{h}h"] = float(((st > tt - np.timedelta64(h, "h")) & (st <= tt)).sum())
    lo = tt - np.timedelta64(14, "D")
    n14 = float(((st > lo) & (st <= tt)).sum())
    s, e = p.a_start[known], np.where(end_known[known], p.a_end[known], tt)
    busy = (np.minimum(e, tt) - np.maximum(s, lo)) / MIN
    calm_h = max((14 * 24 * 60 - float(np.clip(busy, 0, None).sum())) / 60, 1.0)
    out["rate_14d"] = n14 / calm_h
    if end_known.any():
        i = np.flatnonzero(end_known)
        j = i[np.argmax(p.a_end[i])]
        out["log_min_since_end"] = math.log1p(min(max((tt - p.a_end[j]) / MIN, 0.0), GAP_CAP_MIN))
        out["log_last_dur"] = math.log1p(max((p.a_end[j] - p.a_start[j]) / MIN, 0.0))
    else:
        out["log_min_since_end"] = math.log1p(GAP_CAP_MIN)
        out["log_last_dur"] = math.log1p(30.0)
    return out


def _time_features(t: pd.Timestamp) -> dict:
    lt = pd.Timestamp(t).tz_convert(KYIV_TZ)
    h = lt.hour + lt.minute / 60
    return {"hour_sin": math.sin(2 * math.pi * h / 24), "hour_cos": math.cos(2 * math.pi * h / 24),
            "night": float(lt.hour < 6)}


def _window(p: Prepared, tt: np.datetime64, w_min: int) -> np.ndarray:
    """Indices of mention rows posted in (t − w, t], known by t, latest known version of each message."""
    lo = np.searchsorted(p.m_posted, tt - np.timedelta64(w_min, "m"), "right")
    hi = np.searchsorted(p.m_posted, tt, "right")
    idx = np.arange(lo, hi)
    idx = idx[p.m_known[idx] <= tt]
    if not len(idx):
        return idx
    best: dict[tuple, int] = {}
    for i in idx:
        key = (p.m_chan[i], p.m_msg[i])
        best[key] = max(best.get(key, -1), int(p.m_ver[i]))
    return np.array([i for i in idx if p.m_ver[i] == best[(p.m_chan[i], p.m_msg[i])]], dtype=np.int64)


def _drone_block(p: Prepared, idx: np.ndarray, prefix: str, w: int) -> dict:
    d, c = p.m_dist[idx], p.m_count[idx]
    ok = ~np.isnan(d)
    out = {}
    for a, b in RINGS:
        out[f"{prefix}n_ring{b}_{w}m"] = float(c[ok & (d >= a) & (d < b)].sum())
    out[f"{prefix}n_target_ring30_{w}m"] = float(c[ok & p.m_target[idx] & (d <= 30)].sum())
    out[f"{prefix}n_jet_ring150_{w}m"] = float(c[ok & p.m_jet[idx] & (d < 150)].sum())
    out[f"{prefix}min_dist_km_{w}m"] = float(min(d[ok].min(), DIST_CAP)) if ok.any() else DIST_CAP
    out[f"{prefix}none_{w}m"] = float(not ok.any())
    return out


def _drone_features(p: Prepared, tt: np.datetime64) -> dict:
    w30 = _window(p, tt, 30)
    chan = p.m_chan[w30] if len(w30) else np.array([], dtype=object)
    w15 = w30[p.m_posted[w30] > tt - np.timedelta64(15, "m")] if len(w30) else w30
    chan15 = p.m_chan[w15] if len(w15) else np.array([], dtype=object)
    out = {}
    out |= _drone_block(p, w15[chan15 == "kudy_letyt"], "", 15)
    out |= _drone_block(p, w30[chan == "kudy_letyt"], "", 30)
    out |= _drone_block(p, w30[chan == "kpszsu"], "kps_", 30)
    nebo = w30[(chan == "kyiv_nebo")] if len(w30) else w30
    out["kyiv_nebo_any_10m"] = float((p.m_posted[nebo] > tt - np.timedelta64(10, "m")).any()) if len(nebo) else 0.0
    out["missile_any_30m"] = float(p.m_missile[w30].any()) if len(w30) else 0.0
    return out


def features_asof(t: pd.Timestamp, sources: Sources | Prepared) -> dict:
    p = sources if isinstance(sources, Prepared) else Prepared(sources)
    tt = _t64(t)
    return _alert_features(p, tt) | _time_features(t) | _drone_features(p, tt)


def grid(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(start.ceil(f"{STEP_MIN}min"), end.floor(f"{STEP_MIN}min"), freq=f"{STEP_MIN}min", tz="UTC")


def labels(p: Prepared, times: pd.DatetimeIndex, data_end: pd.Timestamp) -> pd.DataFrame:
    """Per t: ``calm`` (no alert as known at t and none really on), ``k_first`` (step of the first start, 0 if none
    within the observed steps), ``n_obs`` (observed steps ≤ 24, censoring at data end), y_H (NaN if censored)."""
    t = times.tz_convert("UTC").tz_localize(None).to_numpy(dtype="datetime64[ns]")
    end = _t64(data_end)
    st, en = p.a_start, p.a_end
    j = np.searchsorted(st, t, "right")  # first start strictly after t
    nxt = np.where(j < len(st), st[np.minimum(j, len(st) - 1)], NAT)
    prev_end = np.where(j > 0, en[np.maximum(j - 1, 0)], NAT)
    real_on = (j > 0) & (np.isnat(prev_end) | (prev_end > t))
    known_on = _known_on(p, t)
    gap = (nxt - t) / MIN
    k = np.where(np.isnat(nxt), np.inf, np.ceil(gap / STEP_MIN))
    n_obs = np.clip(np.floor(((end - t) / MIN) / STEP_MIN), 0, N_STEPS)
    seen = k <= n_obs
    out = pd.DataFrame({"t": times, "calm": ~known_on & ~real_on})
    out["k_first"] = np.where(seen, k, 0).astype(int)
    out["n_obs"] = np.where(seen, k, n_obs).astype(int)
    for h in HORIZONS:
        s = h // STEP_MIN
        y = np.where(seen & (k <= s), 1.0, np.where(n_obs >= s, 0.0, np.nan))
        out[f"y_{h}"] = y
    return out


def _known_on(p: Prepared, t: np.ndarray) -> np.ndarray:
    out = np.zeros(len(t), dtype=bool)
    for i in range(len(p.a_start)):
        e = p.a_ek[i]
        out |= (p.a_sk[i] <= t) & (np.isnat(e) | (e > t))
    return out


def hazard_rows(lab: pd.DataFrame) -> pd.DataFrame:
    """Long table (row index into ``lab``, k, y) for calm t: steps 1…n_obs, y = 1 on the first-start step."""
    c = lab[lab["calm"] & (lab["n_obs"] > 0)]
    n = c["n_obs"].to_numpy()
    row = np.repeat(c.index.to_numpy(), n)
    k = np.concatenate([np.arange(1, m + 1) for m in n]) if len(n) else np.array([], dtype=int)
    kf = np.repeat(c["k_first"].to_numpy(), n)
    return pd.DataFrame({"row": row, "k": k, "y": (k == kf).astype(int)})


def build(sources: Sources, times: pd.DatetimeIndex, data_end: pd.Timestamp) -> pd.DataFrame:
    p = Prepared(sources)
    lab = labels(p, times, data_end)
    feats = pd.DataFrame([features_asof(t, p) for t in times], columns=ALL_FEATURES)
    return pd.concat([lab.reset_index(drop=True), feats], axis=1)


# ---------------------------------------------------------------- quick lift


def lift_table(g: pd.DataFrame) -> pd.DataFrame:
    """P(start within H | feature > 0) vs (= 0) on calm grid points."""
    c = g[g["calm"]]
    rows = []
    cand = [f for f in DRONE_FEATURES if not f.startswith(("min_dist", "kps_min_dist")) and "none_" not in f]
    cand += ["near80_30m"]
    c = c.assign(near80_30m=(c["n_ring30_30m"] + c["n_ring80_30m"]))
    for f in cand:
        on = c[f] > 0
        r = {"feature": f, "share_on": float(on.mean())}
        for h in HORIZONS:
            y = c[f"y_{h}"]
            a, b = y[on].dropna(), y[~on].dropna()
            r[f"P{h}_on"], r[f"P{h}_off"] = float(a.mean()) if len(a) else math.nan, float(b.mean())
            r[f"lift{h}"] = r[f"P{h}_on"] / r[f"P{h}_off"] if r[f"P{h}_off"] > 0 else math.nan
        r["n_on"] = int(on.sum())
        rows.append(r)
    return pd.DataFrame(rows)
