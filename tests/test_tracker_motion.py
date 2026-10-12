"""Pseudo-tracker on synthetic sequences; CRW motion model properties."""

import numpy as np
import pandas as pd
import pytest

from airalert.drones import motion as mo
from airalert.drones import tracker as tk

T0 = pd.Timestamp("2026-09-20T20:00:00Z")


def _obs(rows):
    """rows: (minute, msg_id, lat, lon, kind[, count])"""
    df = pd.DataFrame(
        [
            {
                "observed_at": T0 + pd.Timedelta(minutes=r[0]),
                "channel": "kudy_letyt",
                "msg_id": r[1],
                "line_no": 0,
                "lat": r[2],
                "lon": r[3],
                "kind": r[4],
                "count": r[5] if len(r) > 5 else 1,
                "speed_class": tk.SPEED_CLASS[r[4]],
                "via_lat": np.nan,
                "via_lon": np.nan,
                "oblast": "UA.13",
                "place_norm": f"p{i}",
            }
            for i, r in enumerate(rows)
        ]
    )
    return df.reset_index(drop=True)


def test_continuation_and_count_carry():
    # jet: Бровари -> Київ (≈ 20 km) after 5 min: continues; "2х" kept
    tr = tk.build_tracks(_obs([(0, 1, 50.51, 30.79, "drone_jet", 2), (5, 2, 50.45, 30.52, "drone_jet")]), {})
    assert tr["track_id"].nunique() == 1 and tr["track_len"].tolist() == [2, 2]
    assert tr.iloc[1][["pos_lat", "pos_lon"]].tolist() == [50.51, 30.79]  # position = previous target


def test_gap_over_25_min_starts_new_track():
    tr = tk.build_tracks(_obs([(0, 1, 50.51, 30.79, "drone_jet"), (26, 2, 50.45, 30.52, "drone_jet")]), {})
    assert tr["track_id"].nunique() == 2


def test_impossible_speed_starts_new_track():
    # drone (≤ 4 km/min): 300 km in 5 min is impossible -> new track; a jet class never joins a drone track
    tr = tk.build_tracks(
        _obs(
            [(0, 1, 50.45, 30.52, "drone"), (5, 2, 48.46, 35.04, "drone"), (6, 3, 50.46, 30.53, "drone_jet")]
        ),
        {},
    )
    assert tr["track_id"].nunique() == 3


def test_one_mention_per_track_per_message():
    # two drones announced in the same post towards nearby places are two tracks
    tr = tk.build_tracks(_obs([(0, 1, 50.51, 30.79, "drone_jet"), (0, 1, 50.50, 30.80, "drone_jet")]), {})
    assert tr["track_id"].nunique() == 2


def test_repeated_target_keeps_position_estimate():
    o = _obs([(0, 1, 50.0, 30.0, "drone"), (3, 2, 50.2, 30.2, "drone"), (5, 3, 50.2, 30.2, "drone")])
    tr = tk.build_tracks(o, {})
    assert tr.iloc[2][["pos_lat", "pos_lon"]].tolist() == [50.0, 30.0]  # last *different* target
    assert not np.isnan(tr.iloc[2]["heading_to_target"])


def test_crw_without_noise_is_the_straight_line():
    xy = mo.simulate(
        2, np.array([90.0, 0.0]), np.array([10.0, 3.0]), np.array([7.5, 20.0]), mo.MotionParams(0, 0), n=5
    )
    np.testing.assert_allclose(xy[0], np.tile([75.0, 0.0], (5, 1)), atol=1e-9)  # east, 10 km/min x 7.5 min
    np.testing.assert_allclose(xy[1], np.tile([0.0, 60.0], (5, 1)), atol=1e-9)  # north, 3 km/min x 20 min


def test_p_reach_monotone_in_horizon_and_reproducible():
    # a jet 100 km east of Kyiv heading west
    lat, lon = 50.45, 30.52 + 100 / (mo.KM_PER_DEG_LAT * np.cos(np.radians(50.45)))
    p = mo.MotionParams(0.35, 0.5)
    a = mo.reach_kyiv(lat, lon, 270.0, "jet", p, seed=3)
    b = mo.reach_kyiv(lat, lon, 270.0, "jet", p, seed=3)
    assert repr(a) == repr(b)  # same seed -> identical (incl. NaN)
    vals = [a[f"p_reach_{h}"] for h in mo.HORIZONS]
    assert vals == sorted(vals) and vals[-1] > 0.3
    assert a["p_reach_15"] > mo.reach_kyiv(lat, lon, 90.0, "jet", p, seed=3)["p_reach_15"]  # heading away


def test_speed_is_clipped_to_the_class_range():
    xy = mo.simulate(1, np.array([0.0]), np.array([10.0]), 10.0, mo.MotionParams(0.0, 3.0), n=2000)
    dist = np.hypot(xy[0, :, 0], xy[0, :, 1])
    assert dist.max() <= 10.0 * mo.V_CAP * 10 + 1e-6 and dist.min() >= 0.3 * 10 * 10 - 1e-6


@pytest.mark.parametrize("model", ["crw", "line", "stay"])
def test_calibration_pairs_and_loglik_run(model):
    o = _obs([(0, 1, 50.0, 30.0, "drone"), (5, 2, 50.1, 30.1, "drone"), (10, 3, 50.2, 30.15, "drone")])
    tr = tk.build_tracks(o, {})
    pairs = mo.calibration_pairs(tr)
    assert len(pairs) >= 1
    pred = mo.predict(pairs, model, mo.MotionParams(0.1, 0.2), n=50, seed=0)
    ll, s = mo.loglik(pairs, pred)
    assert np.isfinite(ll) and s in mo.SIGMA_OBS_GRID
