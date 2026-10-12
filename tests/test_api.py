"""API smoke tests on fake collector DBs and a small synthetic model."""

import pickle
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from airalert.api.app import create_app
from airalert.model import features as F
from airalert.model import hazard as HZ
from airalert.model.duration import MAX_MIN
from airalert.sitrep import collector
from airalert.tg import store

NOW = pd.Timestamp("2026-10-12T12:00:00Z")
FIX = Path(__file__).parent / "fixtures"


def _iso(t: pd.Timestamp) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _alerts_db(path: Path, open_alert: bool) -> None:
    rows = []
    for d in range(1, 15):  # one closed alert per day
        s = NOW - pd.Timedelta(days=d, hours=2)
        rows.append(("air_raid", s, s + pd.Timedelta(minutes=40)))
    if open_alert:
        rows.append(("air_raid", NOW - pd.Timedelta(minutes=12), None))
        rows.append(("air_raid_red", NOW - pd.Timedelta(minutes=5), None))
    with closing(store.connect(path)) as c, c:
        for typ, s, e in rows:
            c.execute(
                "INSERT INTO alerts(channel, location, level, alert_type, started_at, finished_at, start_known_at, "
                "end_known_at, source) VALUES ('UkraineAlarmSignal', 'Kyiv City', 'oblast', ?, ?, ?, ?, ?, 'tg_volunteer')",
                (typ, _iso(s), e and _iso(e), _iso(s), e and _iso(e)),
            )
        c.execute("INSERT INTO collector_heartbeat(id, last_seen_at) VALUES (1, ?)", (_iso(NOW - pd.Timedelta(seconds=20)),))


def _sitrep_db(path: Path) -> None:
    with closing(collector.connect(path)) as c:
        text = (FIX / "sitrep_sample.md").read_text(encoding="utf-8")
        collector.store_if_changed(c, collector.MarkdownSitrep.name, collector.Fetched(200, text), _iso(NOW))


def _model(data_dir: Path) -> None:
    rng = np.random.default_rng(0)
    n = 400
    g = pd.DataFrame(rng.uniform(0, 1, size=(n, len(F.ALL_FEATURES))), columns=F.ALL_FEATURES)
    g["t"] = pd.date_range("2026-09-01", periods=n, freq="5min", tz="UTC")
    rows = pd.DataFrame({"row": np.repeat(np.arange(n), F.N_STEPS), "k": np.tile(np.arange(1, F.N_STEPS + 1), n)})
    rows["y"] = (rng.uniform(size=len(rows)) < 0.03).astype(int)
    members = [HZ.Hazard("M1a", HZ.M1A, 1.0).fit(g, rows) for _ in range(5)]
    S = np.clip(1 - np.arange(MAX_MIN + 1) / 120, 0, 1)
    (data_dir / "processed").mkdir(parents=True)
    with open(data_dir / "processed" / "model_final.pkl", "wb") as f:
        pickle.dump({"model": "M1a", "members": members, "km_S": S}, f)
    card = {"skill": {"0-30": 0.02, "30-60": 0.05, "60-120": -0.01}, "test_period": ["2026-09-13", "2026-10-11"]}
    (data_dir / "processed" / "model_card.json").write_text(__import__("json").dumps(card))


@pytest.fixture(params=[False, True], ids=["calm", "alert"])
def client(request, tmp_path):
    _alerts_db(tmp_path / "alerts.sqlite", request.param)
    _sitrep_db(tmp_path / "sitrep.sqlite")
    _model(tmp_path / "data")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<!doctype html><title>x</title>")
    app = create_app(data_dir=tmp_path / "data", web_dir=tmp_path / "web", alerts_db=tmp_path / "alerts.sqlite",
                     sitrep_db=tmp_path / "sitrep.sqlite", clock=lambda: NOW, background=False)
    with TestClient(app) as c:
        yield c, request.param


def test_state(client):
    c, alert = client
    r = c.get("/api/state")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    s = r.json()
    assert set(s) == {"status", "level", "since", "data_as_of", "sources_ok", "mode"} and s["mode"] == "live"
    assert s["data_as_of"] == "2026-10-12T11:59:40Z" and s["sources_ok"] == {"alerts": True, "drones": True}
    if alert:
        assert s["status"] == "alert" and s["since"] == "2026-10-12T11:48:00Z"
        assert s["level"] == "yellow"  # the SITREP sample says yellow for m. Kyiv; it overrides the red flag
    else:
        assert s["status"] == "calm" and s["level"] is None


def test_scenarios_and_etag(client):
    c, alert = client
    r = c.get("/api/scenarios")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    j = r.json()
    assert j["horizon_min"] == 120 and j["members"] == 5 and len(j["scenarios"]) == 1000
    assert j["generated_at"] == "2026-10-12T12:00:00Z" and len(r.content) <= 60_000
    firsts = [s["alerts"][0][0] for s in j["scenarios"] if s["alerts"]]
    assert all(f == -12 for f in firsts) if alert else all(f >= 0 for f in firsts)
    assert c.get("/api/scenarios", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_estimate(client):
    c, _ = client
    r = c.get("/api/estimate", params={"travel": 20, "wait_max": 15})
    assert r.status_code == 200
    e = r.json()
    assert 0 <= e["p"] <= 1 and e["band"][0] <= e["band"][1] and len(e["curve"]) == 13
    assert e["skill_bucket"] == "60-120" and e["unsure"] is True  # skill < 0 in the fake card
    short = c.get("/api/estimate", params={"travel": 5, "shop_mean": 20}).json()
    assert short["skill_bucket"] == "0-30" and short["unsure"] is False
    assert c.get("/api/estimate", params={"travel": -1}).status_code == 422


def test_model_card_static_and_headers(client):
    c, _ = client
    r = c.get("/api/model-card")
    assert r.status_code == 200 and r.json()["skill"]["60-120"] == -0.01
    page = c.get("/")
    assert page.status_code == 200
    for h in ("content-security-policy", "referrer-policy", "x-content-type-options", "permissions-policy"):
        assert h in page.headers
    assert page.headers["referrer-policy"] == "no-referrer" and "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_cold_start_unknown(tmp_path):
    """Empty data/live: the API does not crash; state is «unknown», estimate is 503, health answers."""
    _model(tmp_path / "data")
    app = create_app(data_dir=tmp_path / "data", web_dir=tmp_path / "web", alerts_db=tmp_path / "none.sqlite",
                     sitrep_db=tmp_path / "none2.sqlite", clock=lambda: NOW, background=False)
    with TestClient(app) as c:
        s = c.get("/api/state").json()
        assert s["status"] == "unknown" and s["data_as_of"] is None and s["mode"] == "live"
        assert c.get("/api/estimate?travel=20").status_code == 503
        h = c.get("/api/health").json()
        assert h["sources"]["alerts"]["ok"] is False and h["model"] == "M1a"


def test_health(client):
    c, _ = client
    h = c.get("/api/health").json()
    assert set(h["sources"]) == {"alerts", "drones", "sitrep"}
    assert h["sources"]["alerts"]["ok"] and h["sources"]["sitrep"]["data_as_of"]
