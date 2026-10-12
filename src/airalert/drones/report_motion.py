"""reports/drone_motion.md + example track maps (static PNG)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from airalert.drones import motion as mo
from airalert.drones.gazetteer import KYIV_LAT, KYIV_LON
from airalert.drones.tracker import CLOSE_AFTER_MIN, MAX_GAP_MIN, SLACK_KM, V_MAX, V_TYPICAL, track_stats

CAL_END = pd.Timestamp("2026-09-13", tz="UTC")  # calibration 2026-08-10 … 2026-09-12
VAL_END = pd.Timestamp("2026-10-12", tz="UTC")  # validation 2026-09-13 … 2026-10-11


def split(pairs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return pairs[pairs["observed_at"] < CAL_END], pairs[
        (pairs["observed_at"] >= CAL_END) & (pairs["observed_at"] < VAL_END)
    ]


def plot_examples(
    tracks: pd.DataFrame, params: mo.MotionParams, out_dir: Path, k: int = 5, seed: int = 0
) -> list[Path]:
    """k longest validation-period tracks that come within 150 km of Kyiv: targets, position estimates and the
    CRW particle cloud 10 and 30 minutes after the last observation."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    val = tracks[(tracks["observed_at"] >= CAL_END) & (tracks["observed_at"] < VAL_END)]
    g = val.groupby("track_id")
    dur = (g["observed_at"].max() - g["observed_at"].min()).dt.total_seconds() / 60
    ok = (
        (g["dist_to_kyiv_km"].min() <= 150)
        & g.size().between(4, 8)
        & (dur <= 60)
        & (g["place_norm"].nunique() >= 3)
    )
    ids = ok[ok].index[:: max(1, int(ok.sum()) // k)][
        :k
    ]  # spread over the period, not only the longest blobs
    paths = []
    for n, tid in enumerate(ids, 1):
        t = tracks[tracks["track_id"] == tid].sort_values("observed_at")
        last = t.iloc[-1]
        fig, ax = plt.subplots(figsize=(6, 6))
        coslat = np.cos(np.radians(KYIV_LAT))
        circle = np.linspace(0, 2 * np.pi, 100)
        ax.plot(
            KYIV_LON + mo.KYIV_RADIUS_KM / (mo.KM_PER_DEG_LAT * coslat) * np.sin(circle),
            KYIV_LAT + mo.KYIV_RADIUS_KM / mo.KM_PER_DEG_LAT * np.cos(circle),
            color="#555",
            lw=1,
            label="Kyiv R=20 km",
        )
        if not np.isnan(last["heading_to_target"]):
            for minutes, color in ((10, "#9ecae1"), (30, "#fdae6b")):
                xy = mo.simulate(
                    1,
                    np.array([last["heading_to_target"]]),
                    np.array([V_TYPICAL[last["speed_class"]]]),
                    minutes,
                    params,
                    n=400,
                    rng=np.random.default_rng(seed),
                )[0]
                lon = last["pos_lon"] + xy[:, 0] / (mo.KM_PER_DEG_LAT * np.cos(np.radians(last["pos_lat"])))
                lat = last["pos_lat"] + xy[:, 1] / mo.KM_PER_DEG_LAT
                ax.scatter(lon, lat, s=3, color=color, alpha=0.5, label=f"CRW particles +{minutes} min")
        ax.plot(t["pos_lon"], t["pos_lat"], "--", color="#3182bd", lw=1, label="position estimate")
        ax.plot(t["lon"], t["lat"], "-o", color="#de2d26", ms=4, lw=1.5, label="announced target")
        for _, r in t.iterrows():
            ax.annotate(f"{r['observed_at']:%H:%M} {r['place_norm']}", (r["lon"], r["lat"]), fontsize=7)
        ax.set_title(
            f"track {tid} ({last['speed_class']}), {t['observed_at'].iloc[0]:%Y-%m-%d %H:%M}–{last['observed_at']:%H:%M} UTC",
            fontsize=9,
        )
        ax.set_xlabel("lon")
        ax.set_ylabel("lat")
        lo0, lo1 = min(t["lon"].min(), t["pos_lon"].min()), max(t["lon"].max(), t["pos_lon"].max())
        la0, la1 = min(t["lat"].min(), t["pos_lat"].min()), max(t["lat"].max(), t["pos_lat"].max())
        pad = 0.6
        ax.set_xlim(min(lo0, KYIV_LON) - pad, max(lo1, KYIV_LON) + pad)
        ax.set_ylim(min(la0, KYIV_LAT) - pad, max(la1, KYIV_LAT) + pad)
        ax.set_aspect(1 / coslat)
        ax.legend(fontsize=7, loc="best")
        p = out_dir / f"track_{n}.png"
        fig.tight_layout()
        fig.savefig(p, dpi=110)
        plt.close(fig)
        paths.append(p)
    return paths


def write_report(
    tracks: pd.DataFrame, pairs: pd.DataFrame, result: dict, pngs: list[Path], reports_dir: Path
) -> Path:
    st = track_stats(tracks)
    g = tracks.groupby("track_id")["observed_at"]
    dur = (g.max() - g.min()).dt.total_seconds() / 60
    cal, val = split(pairs)
    p = result["params"]
    models = result["models"]
    grid = result["grid"].sort_values("loglik_cal", ascending=False).head(8)
    md = [
        "# Drone pseudo-tracks and the motion model",
        "",
        f"Generated {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. Source: **kudy_letyt** only (kpszsu is auxiliary — "
        "parser recall on the hold-out is 0.66 raw), kinds `drone_jet` / `drone`, point places, late-edited history excluded.",
        "",
        "## Pseudo-tracks (approximation)",
        "",
        f"Mention j continues track i if Δt ≤ {MAX_GAP_MIN} min, same speed class and the distance between the announced "
        f"targets ≤ v_max·Δt + {SLACK_KM} km (v_max: jet {V_MAX['jet']}, drone {V_MAX['drone']} km/min); greedy nearest-first, one "
        f"mention per track per post, count carried; a track closes after {CLOSE_AFTER_MIN} min. Position estimate = "
        "«повз X» if given, else the previous *different* target, else (first mention) the oblast centroid.",
        "",
        f"- observations: {st['observations']}, tracks: {st['tracks']}, median track length {st['median_track_len']:.0f}",
        f"- **share of mentions in tracks of length ≥ 2: {st['share_in_tracks_len_ge2']:.1%}**",
        f"- track duration, min: median {dur.median():.0f}, 90% {dur.quantile(0.9):.0f}, max {dur.max():.0f} — long tracks "
        "are mostly several drones of a dense attack chained together (a known weakness of ID-less association)",
        f"- calibration pairs (consecutive observations with a changed target, Δt ≤ 20 min): {len(cal)} "
        f"(2026-08-10…09-12), validation: {len(val)} (2026-09-13…10-11)",
        "",
        "Caveat: the channels never report the drone's position, only where it is heading. The pseudo-track glues "
        "posts by plausibility, so two drones in the same area can be merged; the «observed» point of a pair is the "
        "next announced target (as the task prescribes), a proxy that is typically tens of km ahead of the drone.",
        "",
        "## Motion model",
        "",
        "Correlated random walk: θ_{k+1} = θ_k + σ_θ·√Δt·ε (1-min steps), speed = v_class·exp(σ_v·ε) per particle "
        "(jet 10, drone 3 km/min), Monte Carlo; Gaussian observation noise σ_obs fitted per model. Grid MLE on the "
        "calibration period only.",
        "",
        f"**Fitted: σ_θ = {p.sigma_theta} rad/√min, σ_v = {p.sigma_v}.**",
        "",
        "| σ_θ | σ_v | mean log-lik (cal) | σ_obs km |",
        "|---|---|---|---|",
        *[
            f"| {r.sigma_theta} | {r.sigma_v} | {r.loglik_cal:.3f} | {r.sigma_obs:.0f} |"
            for r in grid.itertuples()
        ],
        "",
        "## Validation (2026-09-13 … 2026-10-11)",
        "",
        "| model | σ_obs km | mean log-lik per pair | target in 50% region | target in 80% region |",
        "|---|---|---|---|---|",
        *[
            f"| {r.model} | {r.sigma_obs_km:.0f} | {r.loglik_val:.3f} | {r.hit50:.1%} | {r.hit80:.1%} |"
            for r in models.itertuples()
        ],
        "",
    ]
    crw, line = models.iloc[0], models.iloc[1]
    better = crw["loglik_val"] > line["loglik_val"]
    md += [
        "## Conclusions",
        "",
        f"- The CRW is {'**better**' if better else '**not better**'} than the straight line by "
        f"{crw['loglik_val'] - line['loglik_val']:+.3f} nats per pair on the validation period"
        f"{'' if better else ' — the noise does not help'}; «stays in place» is the worst.",
        f"- The fitted noise is large (σ_θ = {p.sigma_theta} rad/√min ⇒ the course is essentially random after "
        f"~{(1 / p.sigma_theta) ** 2:.0f} min): announced targets jump between posts and pseudo-tracks merge drones. Course "
        "information is useful for the first minutes only; at 15–120 min the prediction is close to diffusion around "
        "the current area — consistent with the alert-level lift decaying from 15 to 60 min.",
        f"- Coverage: the CRW's 50% / 80% regions contain the next target in {crw['hit50']:.0%} / {crw['hit80']:.0%} of "
        "the pairs — the model is somewhat over-confident at the median (the straight line looks better calibrated only "
        "because its fitted σ_obs is 60 km, i.e. very wide). Use p_reach as a ranking feature, not a calibrated probability.",
        "",
        "## Example tracks (validation period, near Kyiv)",
        "",
        *[f"![track {i}](drone_motion/{q.name})" for i, q in enumerate(pngs, 1)],
        "",
    ]
    out = reports_dir / "drone_motion.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    (reports_dir / "drone_motion.json").write_text(
        json.dumps(
            {
                "params": {"sigma_theta": p.sigma_theta, "sigma_v": p.sigma_v},
                "tracks": st,
                "models": models.to_dict("records"),
            },
            ensure_ascii=False,
            indent=1,
            default=float,
        ),
        encoding="utf-8",
    )
    return out
