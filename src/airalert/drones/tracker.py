"""Pseudo-tracks: chain mentions of the same threat across messages (the channels give no drone IDs).

Approximation (documented, measured in reports/drone_motion.md):
- an *observation* is one mention with coordinates: "курсом на Y" (+ "повз X") posted at ``observed_at``;
- mention j continues track i if ``0 <= t_j - t_i <= MAX_GAP_MIN``, same speed class and
  ``dist(target_i, target_j) <= v_max(class) * dt + SLACK_KM``; greedy, nearest candidate first; a track takes at
  most one mention per message (two lines of one post are two threats); the count ("2х") is carried;
- a track closes after ``CLOSE_AFTER_MIN`` without continuation;
- state after each observation: position estimate = the waypoint ("повз X") if given, else the previous target
  (the first observation: its oblast centroid when the target is not in Kyiv, else the target itself),
  heading = bearing from the position estimate to the current target.
kudy_letyt is the main source (kpszsu only auxiliary: parser recall 0.66 raw on the hold-out).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from airalert.drones.gazetteer import bearing_deg, haversine_km

MAX_GAP_MIN = 20
CLOSE_AFTER_MIN = 25
SLACK_KM = 30
SPEED_CLASS = {"drone_jet": "jet", "drone": "drone", "unknown": "drone"}
V_MAX = {"jet": 12.0, "drone": 4.0}  # km/min (jet ≈ 600–700 km/h, Shahed ≈ 185 km/h, + margin)
V_TYPICAL = {"jet": 10.0, "drone": 3.0}
TRACK_KINDS = set(SPEED_CLASS)
POINT_TYPES = {"settlement", "kyiv_local"}


@dataclass
class Track:
    track_id: int
    speed_class: str
    rows: list[int] = field(default_factory=list)  # indices into the mentions frame
    last_t: pd.Timestamp | None = None
    last_lat: float = 0.0
    last_lon: float = 0.0
    count: int = 1


def observations(mentions: pd.DataFrame, channels=("kudy_letyt",)) -> pd.DataFrame:
    """Mentions usable for tracking: drones, point places, not late-edited history, latest text version."""
    m = mentions[
        mentions["channel"].isin(channels)
        & mentions["kind"].isin(TRACK_KINDS)
        & mentions["lat"].notna()
        & mentions["place_type"].isin(POINT_TYPES)
        & ~mentions["late_edit"]
        & mentions["rel"].isin(["target", "via", "bare"])
    ].copy()
    # an edited message replaces its earlier version; keep the latest version of each message line
    m = m.sort_values("version").drop_duplicates(["channel", "msg_id", "line_no", "place_norm"], keep="last")
    m["speed_class"] = m["kind"].map(SPEED_CLASS)
    m["count"] = m["count"].fillna(1).astype(int)
    return m.sort_values(["observed_at", "msg_id", "line_no"]).reset_index(drop=True)


def associate(obs: pd.DataFrame) -> pd.Series:
    """track_id per observation (greedy nearest-neighbour association, see module docstring)."""
    track_of = np.full(len(obs), -1, dtype=int)
    open_tracks: list[Track] = []
    next_id = 0
    for _, grp in obs.groupby(["observed_at", "channel", "msg_id"], sort=True):
        t = grp["observed_at"].iloc[0]
        open_tracks = [tr for tr in open_tracks if (t - tr.last_t).total_seconds() <= CLOSE_AFTER_MIN * 60]
        # candidate pairs (distance, track, row), nearest first; one row per track per message
        pairs = []
        for i, r in grp.iterrows():
            for tr in open_tracks:
                if tr.speed_class != r["speed_class"]:
                    continue
                dt = (t - tr.last_t).total_seconds() / 60
                if dt > MAX_GAP_MIN:
                    continue
                d = haversine_km(tr.last_lat, tr.last_lon, r["lat"], r["lon"])
                if d <= V_MAX[tr.speed_class] * dt + SLACK_KM:
                    pairs.append((d, id(tr), tr, i))
        used_tracks, used_rows = set(), set()
        for _d, _, tr, i in sorted(pairs, key=lambda x: (x[0], x[1])):
            if id(tr) in used_tracks or i in used_rows:
                continue
            used_tracks.add(id(tr))
            used_rows.add(i)
            track_of[i] = tr.track_id
            tr.rows.append(i)
            tr.last_t, tr.last_lat, tr.last_lon = t, obs.at[i, "lat"], obs.at[i, "lon"]
            tr.count = max(tr.count, int(obs.at[i, "count"]))
        for i, r in grp.iterrows():
            if i in used_rows:
                continue
            tr = Track(next_id, r["speed_class"], [i], t, r["lat"], r["lon"], int(r["count"]))
            next_id += 1
            open_tracks.append(tr)
            track_of[i] = tr.track_id
    return pd.Series(track_of, index=obs.index, name="track_id")


def build_tracks(obs: pd.DataFrame, centroids: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """Observations with ``track_id``, ``step`` and the motion state at each observation:
    ``pos_lat/pos_lon`` (position estimate), ``heading_to_target`` (deg), ``prev_*`` (previous observation)."""
    obs = obs.copy()
    obs["track_id"] = associate(obs)
    obs = obs.sort_values(["track_id", "observed_at", "msg_id", "line_no"]).reset_index(drop=True)
    obs["step"] = obs.groupby("track_id").cumcount()
    # previous observation (for calibration pairs) and the last *different* earlier target (position estimate:
    # kudy_letyt repeats the same "курсом на Y" in consecutive posts — that is no movement information)
    prev = obs.groupby("track_id")[["lat", "lon", "observed_at"]].shift()
    obs["prev_lat"], obs["prev_lon"], obs["prev_t"] = prev["lat"], prev["lon"], prev["observed_at"]
    cen = obs["oblast"].map(lambda a: centroids.get(a, (np.nan, np.nan)))
    pos_lat, pos_lon = np.full(len(obs), np.nan), np.full(len(obs), np.nan)
    last_tid, cur, last_target = None, (np.nan, np.nan), None
    for i, (tid, la, lo, vla, vlo, ob, c) in enumerate(
        zip(
            obs["track_id"],
            obs["lat"],
            obs["lon"],
            obs["via_lat"],
            obs["via_lon"],
            obs["oblast"],
            cen,
            strict=True,
        )
    ):
        target = (la, lo)
        if tid != last_tid:  # first observation: oblast centroid (outside Kyiv) or the target itself
            cur = c if ob != "UA.12" and not np.isnan(c[0]) else target
            last_target = None
        elif last_target is not None and target != last_target:
            cur = last_target
        if not np.isnan(vla):
            cur = (vla, vlo)
        pos_lat[i], pos_lon[i] = cur
        last_tid, last_target = tid, target
    obs["pos_lat"], obs["pos_lon"] = pos_lat, pos_lon
    obs["heading_to_target"] = [
        bearing_deg(a, b, c, d) if (a, b) != (c, d) else np.nan
        for a, b, c, d in zip(obs["pos_lat"], obs["pos_lon"], obs["lat"], obs["lon"], strict=True)
    ]
    obs["track_len"] = obs.groupby("track_id")["step"].transform("size")
    return obs


def track_stats(tracks: pd.DataFrame) -> dict:
    n = len(tracks)
    return {
        "observations": n,
        "tracks": int(tracks["track_id"].nunique()),
        "share_in_tracks_len_ge2": round(float((tracks["track_len"] >= 2).mean()), 3) if n else float("nan"),
        "median_track_len": float(tracks.groupby("track_id").size().median()) if n else float("nan"),
        "moving_steps": int(
            (tracks["step"] > 0).sum()
            - (tracks["lat"].eq(tracks["prev_lat"]) & tracks["lon"].eq(tracks["prev_lon"])).sum()
        ),
    }
