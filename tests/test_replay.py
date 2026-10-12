"""Replay mode on the committed parquet: nothing known after the clock reaches the state or the features."""

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from airalert.api import replay as R
from airalert.api.app import create_app, no_mentions
from airalert.model import data as D
from airalert.model import features as F

DATA = Path(__file__).parent.parent / "data"
TIMES = [R.DEMO_AT, R.DEMO_ALERT_AT, pd.Timestamp("2026-09-20T03:07:00Z"), pd.Timestamp("2026-10-01T17:44:00Z")]

pytestmark = pytest.mark.skipif(not (DATA / "processed" / "alerts.parquet").exists(), reason="no committed data")


@pytest.fixture(scope="module")
def reader():
    return R.Reader(DATA)


@pytest.mark.parametrize("t", TIMES)
def test_no_row_known_after_clock(reader, t):
    a = reader(t).alerts
    assert (a["start_known_at"] <= t).all()
    assert (a["end_known_at"].dropna() <= t).all()
    assert a["finished_at"].notna().sum() == a["end_known_at"].notna().sum()


@pytest.mark.parametrize("t", TIMES)
def test_features_match_truncated_sources(reader, t):
    """Features from the replay reader == features from the full history cut at t (the leak test's rule)."""
    full = reader.all[reader.all["alert_type"] == "air_raid"].assign(naive=False, src="tg_volunteer")
    cut = D.Sources(D.merge_overlaps(full[D.ALERT_COLS]), no_mentions()).truncate(t)
    a = F.features_asof(t, D.Sources(reader(t).alerts, no_mentions()))
    b = F.features_asof(t, cut)
    for c in F.BASE_FEATURES:
        assert a[c] == pytest.approx(b[c], nan_ok=True), c


def test_demo_presets(reader):
    assert reader(R.DEMO_AT).alerts["finished_at"].notna().all()  # calm
    assert reader(R.DEMO_ALERT_AT).alerts["finished_at"].isna().any()  # an alert is on


def test_replay_fit_and_api(tmp_path):
    art = R.fit(DATA, R.DEMO_AT, tmp_path)
    assert pd.Timestamp(art["train_end"]) == R.DEMO_AT
    app = create_app(data_dir=DATA, web_dir=tmp_path, replay_at=R.DEMO_AT, pkl=tmp_path / "model_final.pkl",
                     clock=lambda: R.DEMO_AT, background=False)
    with TestClient(app) as c:
        s = c.get("/api/state").json()
        assert s["mode"] == "replay" and s["replay_at"] == "2026-10-07T11:30:00Z" and s["status"] == "calm"
        assert 0 <= c.get("/api/estimate?travel=20").json()["p"] <= 1
