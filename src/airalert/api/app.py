"""FastAPI backend: live state, scenarios (refreshed in the background every 30 s), ready trip probabilities,
model card and the static frontend on ``/`` — one origin, no CORS.

Privacy: the browser computes travel time itself; ``/api/estimate`` gets only minutes (no coordinates). Query
strings are never logged (uvicorn access log is off; our log line has the path only).
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import pickle
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from airalert.api import live as L
from airalert.config import get_settings
from airalert.model import data as D
from airalert.model import features as F
from airalert.model import scenarios as S
from airalert.model import sim
from airalert.model.duration import KM
from airalert.model.pipeline import CARD_FILE, FINAL_FILE, SKILL_BUCKETS

log = logging.getLogger("airalert.api")
REFRESH_S = 30
N_PER_MEMBER = 200
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://server.arcgisonline.com; "
       "connect-src 'self' https://routing.openstreetmap.de https://photon.komoot.io; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Permissions-Policy": "geolocation=(self)",
}
MENTION_COLS = ["channel", "msg_id", "version", "line_no", "posted_at", "known_at", "dist_to_kyiv_km", "count",
                "kind", "rel", "oblast"]


def _iso(t: pd.Timestamp | datetime | None) -> str | None:
    if t is None or pd.isna(t):
        return None
    return pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def no_mentions() -> pd.DataFrame:
    """The product model (M1a) uses no drone features; empty mentions keep features_asof's signature."""
    m = pd.DataFrame({c: pd.Series(dtype=object) for c in MENTION_COLS})
    for c in ("posted_at", "known_at"):
        m[c] = pd.to_datetime(m[c], utc=True)
    return m.astype({"msg_id": "int64", "version": "int64", "line_no": "int64", "dist_to_kyiv_km": float,
                     "count": "Int64"})


class Engine:
    """Holds the model, the newest state and the newest scenarios."""

    def __init__(self, data_dir: Path, alerts_db: Path, sitrep_db: Path, clock: Callable[[], pd.Timestamp]):
        self.data_dir, self.alerts_db, self.sitrep_db, self.clock = data_dir, alerts_db, sitrep_db, clock
        self.loaded_mtime = None
        self.load_model()
        self.state: dict | None = None
        self.scen: dict | None = None
        self.scen_body: bytes = b""
        self.etag = ""
        self.lock = asyncio.Lock()

    def load_model(self) -> None:
        """(Re)load the ensemble and the card when the nightly refit replaced them."""
        pkl, card = self.data_dir / "processed" / FINAL_FILE, self.data_dir / "processed" / CARD_FILE
        mtime = (pkl.stat().st_mtime, card.stat().st_mtime)
        if mtime == self.loaded_mtime:
            return
        with open(pkl, "rb") as f:
            art = pickle.load(f)  # our own artefact, written by `airalert model-fit`
        self.members, self.km, self.model_name = art["members"], KM(np.asarray(art["km_S"])), art["model"]
        self.card = json.loads(card.read_text())
        self.loaded_mtime = mtime
        log.info("model %s x%d loaded", self.model_name, len(self.members))

    def refresh(self) -> None:
        now = self.clock()
        try:
            self.load_model()
        except Exception as e:  # half-written files during a refit: keep the old model
            log.warning("model reload skipped: %s", e)
        try:
            lv = L.read(self.alerts_db, self.sitrep_db, now)
        except Exception as e:
            log.warning("live read failed: %s", e)
            if self.state:
                self.state = {**self.state, "sources_ok": {"alerts": False, "drones": False}}
            return
        sources = D.Sources(lv.alerts, no_mentions())
        p = F.Prepared(sources)
        on, start = F.alert_state(p, now)
        level = None
        if on:
            level = lv.sitrep_level or ("red" if lv.red_on else "yellow")
        if on:
            since = pd.Timestamp(start, tz="UTC")
        else:
            ended = lv.alerts["finished_at"].dropna()
            since = ended.max() if len(ended) else None
        hb_ok = lv.heartbeat is not None and now - lv.heartbeat <= pd.Timedelta(minutes=10)
        self.state = {
            "status": "alert" if on else "calm",
            "level": level,
            "since": _iso(since),
            "data_as_of": _iso(lv.heartbeat),
            # one Telegram session collects alerts and drone channels: same heartbeat
            "sources_ok": {"alerts": hb_ok, "drones": hb_ok},
        }
        feats = pd.DataFrame([F.features_asof(now, p)])
        elapsed = float((now - since).total_seconds() / 60) if on else None
        hz = [m.hazards(feats)[0] for m in self.members] if not on else [np.zeros(F.N_STEPS)] * len(self.members)
        seed = int(now.timestamp()) // REFRESH_S
        self.scen = S.generate(hz, self.km, float(feats["rate_14d"].iloc[0]), elapsed, N_PER_MEMBER, seed,
                               now.to_pydatetime())
        self.scen_body = json.dumps(self.scen, separators=(",", ":")).encode()
        self.etag = '"' + hashlib.sha256(self.scen_body).hexdigest()[:20] + '"'

    def estimate(self, params: dict) -> dict:
        now = self.clock()
        elapsed = (now - pd.Timestamp(self.scen["generated_at"])).total_seconds() / 60
        r = sim.simulate(self.scen, elapsed, params, seed=0)
        end = params["depart_in"] + params["travel"] + params["shop_mean"] + params["wait_max"]
        bucket = next((k for k, H in SKILL_BUCKETS.items() if end <= H), "60-120")
        skill = self.card["skill"][bucket]
        wait = {"median": r["wait_median"], "p80": r["wait_p80"]} if r["wait_median"] is not None else None
        return {
            "p": r["p"], "band": r["p_band"], "wait": wait, "curve": r["curve"], "best": r["best"],
            "share_beyond": r["share_beyond"], "unsure": bool(skill < 0), "skill_bucket": bucket,
            "generated_at": self.scen["generated_at"], "data_as_of": self.state["data_as_of"],
            "model": self.model_name,
        }


def create_app(data_dir: Path | None = None, web_dir: Path | None = None, alerts_db: Path | None = None,
               sitrep_db: Path | None = None, clock: Callable[[], pd.Timestamp] | None = None,
               background: bool = True) -> FastAPI:
    s = get_settings()
    data_dir = data_dir or s.data_dir
    web_dir = web_dir or Path(__import__("os").environ.get("WEB_DIR", "web"))
    clock = clock or (lambda: pd.Timestamp(datetime.now(UTC)))
    eng = Engine(data_dir, alerts_db or s.sqlite_path, sitrep_db or s.sitrep_sqlite_path, clock)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(eng.refresh)
        task = None
        if background:
            async def loop():
                while True:
                    await asyncio.sleep(REFRESH_S)
                    try:
                        await asyncio.to_thread(eng.refresh)
                    except Exception:
                        log.exception("refresh failed")
            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()

    app = FastAPI(title="airalert", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.engine = eng

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            resp.headers[k] = v
        if request.url.path.startswith("/api/") and request.url.path != "/api/model-card":
            resp.headers["Cache-Control"] = "no-store"
        if resp.status_code >= 500:
            log.warning("%s %s -> %s", request.method, request.url.path, resp.status_code)  # path only, no query
        return resp

    def unavailable():
        return JSONResponse({"error": "warming up"}, status_code=503)

    @app.get("/api/state")
    def state():
        return eng.state if eng.state else unavailable()

    @app.get("/api/scenarios")
    def scenarios(request: Request):
        if not eng.scen:
            return unavailable()
        if request.headers.get("if-none-match") == eng.etag:
            return Response(status_code=304, headers={"ETag": eng.etag})
        return Response(eng.scen_body, media_type="application/json", headers={"ETag": eng.etag})

    @app.get("/api/model-card")
    def model_card():
        return eng.card

    @app.get("/api/estimate")
    def estimate(
        travel: float = Query(..., ge=0, le=180),
        depart_in: float = Query(0, ge=0, le=120),
        shop_mean: float = Query(60, ge=sim.SHOP_MIN, le=sim.SHOP_MAX),
        shop_sd: float = Query(15, ge=0, le=60),
        wait_max: float = Query(0, ge=0, le=60),
        open_delay: float = Query(0, ge=0, le=30),
    ):
        if not eng.scen or not eng.state:
            return unavailable()
        params = {"depart_in": depart_in, "travel": travel, "shop_mean": shop_mean, "shop_sd": shop_sd,
                  "wait_max": wait_max, "open_delay": open_delay}
        out = eng.estimate(params)
        return json.loads(json.dumps(out, default=lambda x: None if isinstance(x, float) and math.isinf(x) else x))

    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app
