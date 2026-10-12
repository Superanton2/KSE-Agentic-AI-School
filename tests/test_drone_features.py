"""As-of drone features: no look-ahead (bit-identical recomputation on truncated data), basic semantics."""

import numpy as np
import pandas as pd

from airalert.drones import features as fe
from airalert.drones import motion as mo
from airalert.drones.gazetteer import KYIV_LAT, KYIV_LON, haversine_km

T0 = pd.Timestamp("2026-09-20T20:00:00Z")
PARAMS = mo.MotionParams(0.35, 0.5)


def _m(
    minute,
    msg_id,
    lat,
    lon,
    kind="drone_jet",
    channel="kudy_letyt",
    version=0,
    count=1,
    oblast="UA.13",
    delay_s=5,
):
    t = T0 + pd.Timedelta(minutes=minute)
    return {
        "channel": channel,
        "msg_id": msg_id,
        "version": version,
        "line_no": 0,
        "observed_at": t,
        "known_at": t + pd.Timedelta(seconds=delay_s),
        "kind": kind,
        "count": count,
        "lat": lat,
        "lon": lon,
        "place_type": "settlement",
        "late_edit": False,
        "rel": "target",
        "place_norm": f"p{msg_id}",
        "via_lat": np.nan,
        "via_lon": np.nan,
        "oblast": oblast,
        "dist_to_kyiv_km": haversine_km(lat, lon, KYIV_LAT, KYIV_LON),
    }


def _mentions():
    rows = [
        # a jet from Chernihiv region towards Kyiv: Носівка -> Бровари -> Київ
        _m(0, 1, 50.93, 31.58),
        _m(6, 2, 50.51, 30.79),
        _m(9, 3, 50.45, 30.52, oblast="UA.12"),
        # a slow drone far south, an edited post (version 1 known later), a late-known message (known 40 min later)
        _m(3, 10, 48.46, 35.04, kind="drone", oblast="UA.04"),
        _m(8, 10, 48.50, 34.90, kind="drone", version=1, oblast="UA.04"),
        _m(12, 11, 49.80, 30.12, delay_s=2400),
        # auxiliary channels
        _m(10, 100, 50.45, 30.52, channel="kyiv_nebo", kind="unknown", oblast="UA.12"),
        _m(5, 200, 50.51, 30.79, channel="kpszsu"),
    ]
    return pd.DataFrame(rows)


def test_features_identical_on_truncated_data():
    m = _mentions()
    times = pd.date_range(T0, T0 + pd.Timedelta(minutes=60), freq="5min", tz="UTC")
    full = fe.build(m, {}, PARAMS, times)
    for i, t in enumerate(times):
        again = fe.features_at(fe.prepare(m[m["known_at"] <= t], {}, PARAMS), t)
        for c in fe.FEATURES:
            a, b = again[c], full.at[i, c]
            assert (np.isnan(a) and np.isnan(b)) if isinstance(a, float) and np.isnan(a) else a == b, (
                t,
                c,
                a,
                b,
            )


def test_semantics():
    m = _mentions()
    times = pd.DatetimeIndex([T0 + pd.Timedelta(minutes=k) for k in (-5, 7, 15, 40)])
    f = fe.build(m, {}, PARAMS, times).set_index("t")
    before, mid, late = f.iloc[0], f.iloc[1], f.iloc[3]
    assert before["mentions_last_15m"] == 0 and np.isnan(before["minutes_since_last_kyiv_ring_mention"])
    assert mid["n_jet_active"] >= 1 and mid["n_target_kyiv_ring"] >= 1  # Бровари is < 30 km from Kyiv
    assert mid["p_any_reach_15"] <= mid["p_any_reach_30"] <= mid["p_any_reach_60"] <= mid["p_any_reach_120"]
    assert f.iloc[2]["kyiv_nebo_over_city"] == 1 and late["kyiv_nebo_over_city"] == 0
    assert f.iloc[1]["kpszsu_mentions_last_15m"] == 1
    # tracks expire after ACTIVE_MIN; the late-known message (known at +52 min) is not visible at +40
    assert late["n_jet_active"] == 0
