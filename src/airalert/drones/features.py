"""As-of "pressure field" features on a 5-minute UTC grid for the alert model.

Row t uses only what was known by t (``known_at <= t``): the tracker runs in ``known_at`` order (an edit is a new
observation at the time we could read it), and the Monte Carlo for each observation is seeded by the
observation's identity — so recomputing from data truncated at t gives bit-identical features (tested).

Source: kudy_letyt (main); kpszsu only as auxiliary counters (``kpszsu_*``); kyiv_nebo for the "over the city" flag.

Features (active track = last observation within ``ACTIVE_MIN`` before t; sums are weighted by the "2х" count):
- ``n_tracks_r{30,80,150,300}`` — active tracks whose position estimate lies in the ring (0–30, 30–80, 80–150,
  150–300 km from central Kyiv);
- ``n_heading_kyiv`` — active tracks whose course is within ±30° of the bearing to Kyiv;
- ``n_target_kyiv_ring`` — active tracks whose announced target is within 30 km of Kyiv;
- ``min_eta_min`` — minimum over tracks of the median time to enter R=20 km (NaN if no track gets ≥ 50%);
- ``p_any_reach_{15,30,60,120}`` = 1 − Π(1 − p_i), p_i = P(track i enters R=20 km within H | not yet entered);
- ``n_jet_active``, ``mentions_last_{15,60}m``, ``minutes_since_last_kyiv_ring_mention`` (NaN before the first);
- ``kyiv_nebo_over_city`` — a kyiv_nebo post naming a place in Kyiv city in the last 10 min;
- ``kpszsu_mentions_last_15m``, ``kpszsu_kyiv_ring_last_15m`` — auxiliary.
"""

import zlib

import numpy as np
import pandas as pd

from airalert.drones import motion as mo
from airalert.drones import tracker as tk
from airalert.drones.gazetteer import KYIV_LAT, KYIV_LON, bearing_deg, haversine_km

GRID_MIN = 5
ACTIVE_MIN = tk.CLOSE_AFTER_MIN
RINGS = ((0, 30), (30, 80), (80, 150), (150, 300))
KYIV_RING_KM = 30
HEADING_TOL = 30
MC_PARTICLES = 300
MC_MAX_DIST_KM = 800  # farther tracks cannot plausibly reach Kyiv within 2 h + ACTIVE_MIN at drone speeds
MC_MINUTES = max(mo.HORIZONS) + ACTIVE_MIN
FEATURES = [
    *[f"n_tracks_r{b}" for _, b in RINGS],
    "n_heading_kyiv",
    "n_target_kyiv_ring",
    "min_eta_min",
    *[f"p_any_reach_{h}" for h in mo.HORIZONS],
    "n_jet_active",
    "mentions_last_15m",
    "mentions_last_60m",
    "minutes_since_last_kyiv_ring_mention",
    "kyiv_nebo_over_city",
    "kpszsu_mentions_last_15m",
    "kpszsu_kyiv_ring_last_15m",
]


def _seed(r) -> int:
    return zlib.crc32(f"{r.channel}:{r.msg_id}:{r.version}:{r.line_no}:{r.place_norm}:{r.track_id}".encode())


def entry_curves(tracks: pd.DataFrame, params: mo.MotionParams) -> np.ndarray:
    """F[i, m] = P(first entry into R=20 km by minute m after observation i), m = 0..MC_MINUTES."""
    F = np.zeros((len(tracks), MC_MINUTES + 1), dtype=np.float64)
    for i, r in enumerate(tracks.itertuples(index=False)):
        d0 = haversine_km(r.pos_lat, r.pos_lon, KYIV_LAT, KYIV_LON)
        if d0 <= mo.KYIV_RADIUS_KM:
            F[i] = 1.0
            continue
        if d0 > MC_MAX_DIST_KM:
            continue
        rng = np.random.default_rng(_seed(r))
        heading = r.heading_to_target
        if np.isnan(heading):  # unknown course: uniform
            heading_arr = rng.uniform(0, 360, MC_PARTICLES)
        else:
            heading_arr = np.full(MC_PARTICLES, heading)
        path = _paths(heading_arr, tk.V_TYPICAL[r.speed_class], params, rng)
        kx, ky = mo.to_xy(KYIV_LAT, KYIV_LON, r.pos_lat, r.pos_lon)
        inside = np.hypot(path[..., 0] - kx, path[..., 1] - ky) <= mo.KYIV_RADIUS_KM
        first = np.where(inside.any(axis=1), inside.argmax(axis=1), MC_MINUTES + 1)
        F[i] = (first[:, None] <= np.arange(MC_MINUTES + 1)[None, :]).mean(axis=0)
    return F


def _paths(heading_deg: np.ndarray, v_class: float, params: mo.MotionParams, rng) -> np.ndarray:
    """(particles, MC_MINUTES+1, 2) km paths; same dynamics as motion.simulate, per-particle start heading."""
    n = len(heading_deg)
    speed = np.clip(
        v_class * np.exp(params.sigma_v * rng.standard_normal(n)), 0.3 * v_class, v_class * mo.V_CAP
    )
    theta = np.radians(heading_deg)
    noise = rng.standard_normal((MC_MINUTES, n)) * params.sigma_theta
    path = np.zeros((n, MC_MINUTES + 1, 2))
    x = np.zeros(n)
    y = np.zeros(n)
    for k in range(MC_MINUTES):
        x = x + speed * np.sin(theta)
        y = y + speed * np.cos(theta)
        theta = theta + noise[k]
        path[:, k + 1, 0], path[:, k + 1, 1] = x, y
    return path


def prepare(mentions: pd.DataFrame, centroids: dict, params: mo.MotionParams) -> dict:
    """Everything the grid loop needs, computed once (as-of safe: causal in known_at)."""
    obs = tk.observations(mentions, as_of=True)
    tracks = (
        tk.build_tracks(obs, centroids).sort_values(["t", "track_id"], kind="stable").reset_index(drop=True)
    )
    tracks["pos_dist"] = [
        haversine_km(a, b, KYIV_LAT, KYIV_LON)
        for a, b in zip(tracks["pos_lat"], tracks["pos_lon"], strict=True)
    ]
    to_kyiv = [
        bearing_deg(a, b, KYIV_LAT, KYIV_LON)
        for a, b in zip(tracks["pos_lat"], tracks["pos_lon"], strict=True)
    ]
    diff = (np.asarray(tracks["heading_to_target"]) - np.asarray(to_kyiv) + 180) % 360 - 180
    tracks["heading_kyiv"] = np.abs(diff) <= HEADING_TOL
    F = entry_curves(tracks, params)
    kudy = mentions[mentions["channel"] == "kudy_letyt"]
    ring = kudy[kudy["dist_to_kyiv_km"] <= KYIV_RING_KM]
    kps = mentions[mentions["channel"] == "kpszsu"]
    nebo = mentions[
        (mentions["channel"] == "kyiv_nebo") & (mentions["oblast"] == "UA.12") & mentions["lat"].notna()
    ]
    ns = lambda s: np.sort(s.to_numpy(dtype="datetime64[ns]"))  # noqa: E731
    return {
        "tracks": tracks,
        "F": F,
        "t": tracks["t"].to_numpy(dtype="datetime64[ns]"),
        "kudy_t": ns(kudy["known_at"]),
        "ring_t": ns(ring["known_at"]),
        "kps_t": ns(kps["known_at"]),
        "kps_ring_t": ns(kps[kps["dist_to_kyiv_km"] <= KYIV_RING_KM]["known_at"]),
        "nebo_t": ns(nebo["known_at"]),
    }


def _count_in(arr: np.ndarray, lo: np.datetime64, hi: np.datetime64) -> int:
    """#{x: lo < x <= hi}"""
    return int(np.searchsorted(arr, hi, "right") - np.searchsorted(arr, lo, "right"))


def features_at(prep: dict, t: pd.Timestamp) -> dict:
    tt = np.datetime64(t.tz_convert("UTC").tz_localize(None), "ns")
    act = np.timedelta64(ACTIVE_MIN, "m")
    tr, F, ts = prep["tracks"], prep["F"], prep["t"]
    lo, hi = np.searchsorted(ts, tt - act, "left"), np.searchsorted(ts, tt, "right")
    last: dict[int, int] = {}
    for i in range(lo, hi):  # latest observation of every active track
        last[int(tr.at[i, "track_id"])] = i
    idx = [last[k] for k in sorted(last)]
    out: dict = {}
    sub = tr.loc[idx] if idx else tr.iloc[0:0]
    w = sub["count"].to_numpy(dtype=float) if idx else np.array([])
    for a, b in RINGS:
        out[f"n_tracks_r{b}"] = (
            float(w[((sub["pos_dist"] >= a) & (sub["pos_dist"] < b)).to_numpy()].sum()) if idx else 0.0
        )
    out["n_heading_kyiv"] = float(w[sub["heading_kyiv"].to_numpy()].sum()) if idx else 0.0
    out["n_target_kyiv_ring"] = (
        float(w[(sub["dist_to_kyiv_km"] <= KYIV_RING_KM).to_numpy()].sum()) if idx else 0.0
    )
    out["n_jet_active"] = float(w[(sub["speed_class"] == "jet").to_numpy()].sum()) if idx else 0.0
    etas, ps = [], {h: [] for h in mo.HORIZONS}
    for i in idx:
        e = int((tt - ts[i]) // np.timedelta64(1, "m"))
        f = F[i]
        base = f[e]
        if base >= 1.0:  # already entered (or started inside)
            for h in mo.HORIZONS:
                ps[h].append(1.0)
            etas.append(0.0)
            continue
        cond = (f[e:] - base) / (1.0 - base)  # P(enter within m minutes from now | not yet)
        for h in mo.HORIZONS:
            ps[h].append(float(cond[min(h, len(cond) - 1)]))
        m50 = np.argmax(cond >= 0.5) if (cond >= 0.5).any() else None
        if m50 is not None and m50 <= max(mo.HORIZONS):
            etas.append(float(m50))
    out["min_eta_min"] = min(etas) if etas else float("nan")
    for h in mo.HORIZONS:
        out[f"p_any_reach_{h}"] = float(1.0 - np.prod([1.0 - p for p in ps[h]])) if ps[h] else 0.0
    m15, m60, m10 = (np.timedelta64(k, "m") for k in (15, 60, 10))
    out["mentions_last_15m"] = _count_in(prep["kudy_t"], tt - m15, tt)
    out["mentions_last_60m"] = _count_in(prep["kudy_t"], tt - m60, tt)
    j = np.searchsorted(prep["ring_t"], tt, "right")
    out["minutes_since_last_kyiv_ring_mention"] = (
        float((tt - prep["ring_t"][j - 1]) / np.timedelta64(1, "m")) if j > 0 else float("nan")
    )
    out["kyiv_nebo_over_city"] = int(_count_in(prep["nebo_t"], tt - m10, tt) > 0)
    out["kpszsu_mentions_last_15m"] = _count_in(prep["kps_t"], tt - m15, tt)
    out["kpszsu_kyiv_ring_last_15m"] = _count_in(prep["kps_ring_t"], tt - m15, tt)
    return out


def grid(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(
        start.floor(f"{GRID_MIN}min"), end.floor(f"{GRID_MIN}min"), freq=f"{GRID_MIN}min", tz="UTC"
    )


def build(
    mentions: pd.DataFrame, centroids: dict, params: mo.MotionParams, times: pd.DatetimeIndex
) -> pd.DataFrame:
    prep = prepare(mentions, centroids, params)
    rows = [features_at(prep, t) for t in times]
    df = pd.DataFrame(rows, columns=FEATURES)
    df.insert(0, "t", times)
    return df


# ---------------------------------------------------------------- usefulness check (lift)


def alert_labels(alerts: pd.DataFrame, times: pd.DatetimeIndex, horizons=mo.HORIZONS) -> pd.DataFrame:
    """y_H(t) = a Kyiv City alert *starts* in (t, t+H]; ``in_alert`` = an alert is already on at t (excluded)."""
    k = alerts[(alerts["location"] == "Kyiv City") & (alerts["granularity"] == "oblast_union")]
    starts = np.sort(k["started_at"].to_numpy(dtype="datetime64[ns]"))
    t = times.tz_convert("UTC").tz_localize(None).to_numpy(dtype="datetime64[ns]")
    out = pd.DataFrame({"t": times})
    for h in horizons:
        out[f"y_{h}"] = (
            np.searchsorted(starts, t + np.timedelta64(h, "m"), "right") - np.searchsorted(starts, t, "right")
        ) > 0
    fin = k["finished_at"].fillna(pd.Timestamp.max.tz_localize("UTC")).to_numpy(dtype="datetime64[ns]")
    st = k["started_at"].to_numpy(dtype="datetime64[ns]")
    out["in_alert"] = [bool(((st <= x) & (fin > x)).any()) for x in t]
    return out


def raion_alert_active(alerts: pd.DataFrame, times: pd.DatetimeIndex) -> np.ndarray:
    """Baseline feature: a raion alert in Kyivska oblast is on at t (as known: start_known_at <= t < end_known_at)."""
    r = alerts[
        (alerts["location"] == "Kyivska oblast")
        & (alerts["granularity"] == "raw")
        & (alerts["level"] == "raion")
    ]
    s = r["start_known_at"].to_numpy(dtype="datetime64[ns]")
    e = r["end_known_at"].fillna(pd.Timestamp.max.tz_localize("UTC")).to_numpy(dtype="datetime64[ns]")
    t = times.tz_convert("UTC").tz_localize(None).to_numpy(dtype="datetime64[ns]")
    return np.array([bool(((s <= x) & (e > x)).any()) for x in t])


def lift_table(feats: pd.DataFrame, labels: pd.DataFrame, baseline: np.ndarray) -> pd.DataFrame:
    """Lift = P(alert starts within H | feature on) / P(… | feature off), on grid points outside an alert."""
    on = {
        "raion alert in Kyiv oblast (baseline)": baseline,
        "n_tracks_r30+r80 > 0": (feats["n_tracks_r30"] + feats["n_tracks_r80"]).to_numpy() > 0,
        "n_tracks_r150 > 0": feats["n_tracks_r150"].to_numpy() > 0,
        "n_heading_kyiv > 0": feats["n_heading_kyiv"].to_numpy() > 0,
        "n_target_kyiv_ring > 0": feats["n_target_kyiv_ring"].to_numpy() > 0,
        "p_any_reach_60 > 0.2": feats["p_any_reach_60"].to_numpy() > 0.2,
        "kyiv_nebo_over_city": feats["kyiv_nebo_over_city"].to_numpy() > 0,
        "mentions_last_15m > 0": feats["mentions_last_15m"].to_numpy() > 0,
    }
    free = ~labels["in_alert"].to_numpy()

    def lift(y, x, mask):
        a, b = y[mask & x], y[mask & ~x]
        return float(a.mean() / b.mean()) if len(a) and len(b) and b.mean() > 0 else float("nan")

    rows = []
    for name, x in on.items():
        row = {"feature": name, "share_on": float(x[free].mean())}
        for h in mo.HORIZONS:
            y = labels[f"y_{h}"].to_numpy()
            row[f"lift_{h}"] = lift(y, x, free)
            # incremental: among grid points where the baseline (raion alert) is OFF
            row[f"lift_{h}_no_raion"] = lift(y, x, free & ~baseline)
        rows.append(row)
    return pd.DataFrame(rows)
