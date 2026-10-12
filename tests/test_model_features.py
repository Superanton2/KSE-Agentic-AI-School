import math

import numpy as np
import pandas as pd
import pytest

from airalert.model import data as D
from airalert.model import features as F

T0 = pd.Timestamp("2026-09-01T00:00Z")


def ts(m: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(minutes=m)


def alerts(rows) -> pd.DataFrame:
    """rows: (start, end, start_known, end_known) in minutes from T0."""
    return pd.DataFrame(
        [{"started_at": ts(a), "finished_at": ts(b), "start_known_at": ts(c), "end_known_at": ts(d),
          "naive": False, "src": "x"} for a, b, c, d in rows],
        columns=D.ALERT_COLS,
    )


def mentions(rows) -> pd.DataFrame:
    """rows: (channel, msg_id, version, posted, known, dist_km, kind, rel)."""
    return pd.DataFrame(
        [{"channel": ch, "msg_id": mid, "version": v, "line_no": 0, "posted_at": ts(p), "known_at": ts(k),
          "dist_to_kyiv_km": d, "count": pd.NA, "kind": kind, "rel": rel, "oblast": "UA.13"}
         for ch, mid, v, p, k, d, kind, rel in rows]
    ).astype({"count": "Int64"})


@pytest.fixture
def sources() -> D.Sources:
    a = alerts([(-300, -250, -300, -250), (100, 140, 103, 150), (400, 430, 400, 431)])
    m = mentions([
        ("kudy_letyt", 1, 0, 50, 50, 200.0, "drone", "target"),
        ("kudy_letyt", 1, 1, 50, 70, 25.0, "drone", "target"),  # edit known later: moves the place to 25 km
        ("kudy_letyt", 2, 0, 82, 95, 60.0, "drone_jet", "bare"),  # late delivery
        ("kpszsu", 3, 0, 85, 85, 120.0, "drone_jet", "target"),
        ("kyiv_nebo", 4, 0, 90, 90, 1.0, "missile", "bare"),
    ])
    return D.Sources(a, m)


def test_truncated_sources_give_identical_features(sources):
    full = F.Prepared(sources)
    for m in range(-60, 500, 5):
        t = ts(m)
        a, b = F.features_asof(t, full), F.features_asof(t, sources.truncate(t))
        for c in F.ALL_FEATURES:
            assert a[c] == b[c] or (math.isnan(a[c]) and math.isnan(b[c])), (m, c)


def test_versions_and_known_at(sources):
    p = F.Prepared(sources)
    f60 = F.features_asof(ts(60), p)
    assert f60["n_ring300_15m"] == 1 and f60["n_ring30_15m"] == 0  # only version 0 known
    f75 = F.features_asof(ts(75), p)
    assert f75["n_ring30_30m"] == 1 and f75["n_ring300_30m"] == 0 and f75["n_target_ring30_30m"] == 1
    f90 = F.features_asof(ts(90), p)  # msg 2 posted at 82 but known only at 95
    assert f90["n_ring80_15m"] == 0 and F.features_asof(ts(95), p)["n_ring80_15m"] == 1
    assert F.features_asof(ts(95), p)["n_jet_ring150_15m"] == 1
    assert f90["kyiv_nebo_any_10m"] == 1 and f90["missile_any_30m"] == 1
    assert F.features_asof(ts(105), p)["kyiv_nebo_any_10m"] == 0


def test_alert_state_by_known_at(sources):
    p = F.Prepared(sources)
    assert F.alert_state(p, ts(101)) == (False, None)  # started at 100, known at 103
    assert F.alert_state(p, ts(103))[0]
    assert F.alert_state(p, ts(145))[0]  # ended at 140, known at 150
    assert not F.alert_state(p, ts(150))[0]


def test_labels_hazard_rows_and_censoring(sources):
    p = F.Prepared(sources)
    times = pd.DatetimeIndex([ts(0), ts(101), ts(145), ts(300), ts(440)])
    lab = F.labels(p, times, data_end=ts(470))
    assert list(lab["calm"]) == [True, False, False, True, True]
    assert lab.loc[0, "k_first"] == 20 and lab.loc[0, "n_obs"] == 20  # start at +100 → step 20
    assert lab.loc[0, "y_60"] == 0 and lab.loc[0, "y_120"] == 1
    assert lab.loc[3, "k_first"] == 20 and lab.loc[3, "y_15"] == 0
    assert lab.loc[4, "k_first"] == 0 and lab.loc[4, "n_obs"] == 6  # censored at data end
    assert lab.loc[4, "y_30"] == 0 and np.isnan(lab.loc[4, "y_60"])
    h = F.hazard_rows(lab)
    r0 = h[h["row"] == 0]
    assert list(r0["k"]) == list(range(1, 21)) and r0["y"].sum() == 1 and r0["y"].iloc[-1] == 1
    assert h[h["row"] == 4]["y"].sum() == 0 and len(h[h["row"] == 4]) == 6
    assert not h["row"].isin([1, 2]).any()


def test_merge_overlaps():
    a = alerts([(0, 30, 0, 30), (20, 50, 20, 50), (60, 70, 60, 70)])
    m = D.merge_overlaps(a)
    assert len(m) == 2 and m.loc[0, "finished_at"] == ts(50)
