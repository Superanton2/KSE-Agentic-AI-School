"""Probabilistic motion model: correlated random walk (CRW) of the heading, Monte Carlo.

- heading: ``θ_{k+1} = θ_k + σ_θ·√Δt·ε`` (Δt = 1 min), ε ~ N(0, 1) — Brownian motion of the course;
- speed: lognormal around the class speed (jet ≈ 10, drone ≈ 3 km/min), ``v = v_class·exp(σ_v·ε)``, fixed per
  particle and clipped to [0.3, V_CAP]·v_class (the physical range — otherwise σ_v absorbs pseudo-track noise
  as 90 km/min "jets");
- positions in a local equirectangular plane (km) around the start; ``N`` particles, 1-min steps up to 120 min;
- per track: ``P(enter the R=20 km circle around central Kyiv by t+H)`` and the first-entry time distribution.

Calibration (``calibrate``): consecutive observations i -> j of a pseudo-track with a different target; the model
predicts the position after Δt = t_j - t_i from the state at i; the "observed" point is the next target (as the
task prescribes — a proxy, the channels never give the drone's position), with Gaussian observation noise σ_obs
fitted for every model. Baselines: (a) straight line at constant class speed, no noise; (b) stays in place.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from airalert.drones.gazetteer import KYIV_LAT, KYIV_LON
from airalert.drones.tracker import V_MAX, V_TYPICAL

KM_PER_DEG_LAT = 110.57
KYIV_RADIUS_KM = 20.0
V_CAP = min(
    V_MAX["jet"] / V_TYPICAL["jet"], V_MAX["drone"] / V_TYPICAL["drone"]
)  # speed <= 1.2–1.3 x class speed
HORIZONS = (15, 30, 60, 120)


@dataclass(frozen=True)
class MotionParams:
    sigma_theta: float = 0.05  # rad / sqrt(min)
    sigma_v: float = 0.2  # log-speed sd


def to_xy(lat, lon, lat0, lon0):
    """Local plane (km east, km north) around (lat0, lon0)."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return (lon - lon0) * KM_PER_DEG_LAT * np.cos(np.radians(lat0)), (lat - lat0) * KM_PER_DEG_LAT


def simulate(
    n_tracks: int,
    heading_deg: np.ndarray,
    v_class: np.ndarray,
    minutes: np.ndarray | float,
    params: MotionParams,
    n: int = 2000,
    rng: np.random.Generator | None = None,
    keep_path: bool = False,
):
    """Positions (km, relative to each start) of ``n`` particles per track after ``minutes`` (per track).
    With ``keep_path`` returns the whole path at every minute 0..max(minutes): shape (tracks, n, T+1, 2)."""
    rng = rng or np.random.default_rng(0)
    minutes = np.broadcast_to(np.asarray(minutes, float), (n_tracks,))
    steps = int(np.ceil(minutes.max())) if n_tracks else 0
    theta = np.radians(np.asarray(heading_deg, float))[:, None] * np.ones((1, n))
    v = np.asarray(v_class, float)[:, None]
    # lognormal around the class speed, clipped to the physical range of the class (no 90 km/min jets)
    speed = np.clip(v * np.exp(params.sigma_v * rng.standard_normal((n_tracks, n))), 0.3 * v, v * V_CAP)
    x = np.zeros((n_tracks, n))
    y = np.zeros((n_tracks, n))
    path = np.zeros((n_tracks, n, steps + 1, 2)) if keep_path else None
    for k in range(steps):
        dt = np.clip(minutes - k, 0.0, 1.0)[
            :, None
        ]  # fractional last step; 0 once a track's horizon is reached
        x += speed * dt * np.sin(theta)
        y += speed * dt * np.cos(theta)
        theta = theta + params.sigma_theta * np.sqrt(dt) * rng.standard_normal((n_tracks, n))
        if keep_path:
            path[:, :, k + 1, 0], path[:, :, k + 1, 1] = x, y
    return path if keep_path else np.stack([x, y], axis=-1)


def reach_kyiv(
    lat: float,
    lon: float,
    heading_deg: float,
    speed_class: str,
    params: MotionParams,
    n: int = 2000,
    seed: int = 0,
) -> dict:
    """P(enter R=20 km around central Kyiv by t+H) for H in HORIZONS, and first-entry time quantiles (min)."""
    path = simulate(
        1,
        np.array([heading_deg]),
        np.array([V_TYPICAL[speed_class]]),
        max(HORIZONS),
        params,
        n,
        np.random.default_rng(seed),
        keep_path=True,
    )[0]
    kx, ky = to_xy(KYIV_LAT, KYIV_LON, lat, lon)
    inside = np.hypot(path[..., 0] - kx, path[..., 1] - ky) <= KYIV_RADIUS_KM  # (n, T+1)
    entered = inside.any(axis=1)
    first = np.where(entered, inside.argmax(axis=1), np.inf)
    out = {f"p_reach_{h}": float((first <= h).mean()) for h in HORIZONS}
    out["eta_median_min"] = float(np.median(first[entered])) if entered.mean() >= 0.5 else float("nan")
    out["eta_p10_min"] = float(np.quantile(first[entered], 0.1)) if entered.any() else float("nan")
    return out


# ---------------------------------------------------------------- calibration


def calibration_pairs(tracks: pd.DataFrame) -> pd.DataFrame:
    """Consecutive observations i -> j of one track where the target changed (movement information)."""
    t = tracks.sort_values(["track_id", "observed_at", "msg_id", "line_no"])
    nxt = t.groupby("track_id")[["lat", "lon", "observed_at"]].shift(-1)
    pairs = t.assign(obs_lat=nxt["lat"], obs_lon=nxt["lon"], t_next=nxt["observed_at"])
    pairs = pairs[pairs["obs_lat"].notna() & pairs["heading_to_target"].notna()]
    pairs = pairs[(pairs["obs_lat"] != pairs["lat"]) | (pairs["obs_lon"] != pairs["lon"])]
    pairs["dt_min"] = (pairs["t_next"] - pairs["observed_at"]).dt.total_seconds() / 60
    pairs = pairs[(pairs["dt_min"] > 0) & (pairs["dt_min"] <= 20)]
    ox, oy = to_xy(
        pairs["obs_lat"], pairs["obs_lon"], pairs["pos_lat"].to_numpy(), pairs["pos_lon"].to_numpy()
    )
    pairs["obs_x"], pairs["obs_y"] = ox, oy
    pairs["v_class"] = pairs["speed_class"].map(V_TYPICAL)
    return pairs.reset_index(drop=True)


def _gauss_logpdf(d2: np.ndarray, sigma: float) -> np.ndarray:
    return -d2 / (2 * sigma**2) - np.log(2 * np.pi * sigma**2)


def _mixture_loglik(particles: np.ndarray, obs: np.ndarray, sigma: float) -> np.ndarray:
    """log mean_k N(obs | particle_k, σ² I) per pair. particles (P, n, 2), obs (P, 2)."""
    d2 = ((particles - obs[:, None, :]) ** 2).sum(-1)
    lp = _gauss_logpdf(d2, sigma)
    mx = lp.max(axis=1, keepdims=True)
    return mx[:, 0] + np.log(np.exp(lp - mx).mean(axis=1))


SIGMA_OBS_GRID = (5, 10, 15, 20, 30, 40, 60, 80)  # km — the next target is not the drone's position


def predict(pairs: pd.DataFrame, model: str, params: MotionParams | None, n: int, seed: int) -> np.ndarray:
    """Predicted positions (P, n, 2) after dt for the 'crw', 'line' (n=1) or 'stay' (n=1) model."""
    h = pairs["heading_to_target"].to_numpy()
    v = pairs["v_class"].to_numpy()
    dt = pairs["dt_min"].to_numpy()
    if model == "stay":
        return np.zeros((len(pairs), 1, 2))
    if model == "line":
        return simulate(len(pairs), h, v, dt, MotionParams(0.0, 0.0), n=1)
    return simulate(len(pairs), h, v, dt, params, n=n, rng=np.random.default_rng(seed))


def loglik(pairs: pd.DataFrame, pred: np.ndarray) -> tuple[float, float]:
    """(mean log-likelihood per pair at the best σ_obs, that σ_obs)."""
    obs = pairs[["obs_x", "obs_y"]].to_numpy()
    best = max((_mixture_loglik(pred, obs, s).mean(), s) for s in SIGMA_OBS_GRID)
    return float(best[0]), float(best[1])


def hit_rates(
    pairs: pd.DataFrame, pred: np.ndarray, sigma: float, qs=(0.5, 0.8), m: int = 300, seed: int = 1
) -> dict:
    """Share of pairs whose observed next target lies inside the q-HPD region of the predictive density
    (particles convolved with N(0, σ_obs²))."""
    rng = np.random.default_rng(seed)
    obs = pairs[["obs_x", "obs_y"]].to_numpy()
    P, n, _ = pred.shape
    idx = rng.integers(0, n, size=(P, m))
    samples = np.take_along_axis(pred, idx[..., None], axis=1) + sigma * rng.standard_normal((P, m, 2))
    sub = pred[:, : min(n, 400)]
    dens_obs = _mixture_loglik(sub, obs, sigma)
    dens_s = np.stack([_mixture_loglik(sub, samples[:, k], sigma) for k in range(m)], axis=1)
    frac_above = (dens_s > dens_obs[:, None]).mean(axis=1)  # mass of the HPD region that excludes obs
    return {f"hit{int(q * 100)}": float((frac_above <= q).mean()) for q in qs}


def calibrate(
    pairs_cal: pd.DataFrame,
    pairs_val: pd.DataFrame,
    theta_grid=(0.0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0),
    sv_grid=(0.0, 0.2, 0.35, 0.5, 0.75, 1.0),
    n: int = 300,
    max_cal_pairs: int = 3000,
    seed: int = 0,
) -> dict:
    """Grid MLE of (σ_θ, σ_v) on the calibration period only; report all models on the validation period."""
    cal = (
        pairs_cal.sample(min(len(pairs_cal), max_cal_pairs), random_state=seed)
        if len(pairs_cal)
        else pairs_cal
    )
    grid = []
    for st in theta_grid:
        for sv in sv_grid:
            ll, so = loglik(cal, predict(cal, "crw", MotionParams(st, sv), n, seed))
            grid.append({"sigma_theta": st, "sigma_v": sv, "loglik_cal": ll, "sigma_obs": so})
    grid = pd.DataFrame(grid)
    best = grid.loc[grid["loglik_cal"].idxmax()]
    params = MotionParams(float(best["sigma_theta"]), float(best["sigma_v"]))
    rows = []
    for name, model, p, n_ in (
        ("crw (fitted)", "crw", params, n),
        ("line, no noise", "line", None, 1),
        ("stay", "stay", None, 1),
    ):
        _, so_cal = loglik(cal, predict(cal, model, p, n_, seed))  # σ_obs fitted on calibration too
        pred_v = predict(pairs_val, model, p, n_, seed + 1)
        obs_v = pairs_val[["obs_x", "obs_y"]].to_numpy()
        ll_v = float(_mixture_loglik(pred_v, obs_v, so_cal).mean())
        pv = pred_v if pred_v.shape[1] > 1 else np.repeat(pred_v, 2, axis=1)
        rows.append(
            {"model": name, "sigma_obs_km": so_cal, "loglik_val": ll_v, **hit_rates(pairs_val, pv, so_cal)}
        )
    return {"params": params, "grid": grid, "models": pd.DataFrame(rows)}
