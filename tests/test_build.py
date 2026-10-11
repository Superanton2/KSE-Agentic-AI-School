"""Assembly of dataset + Telegram sources: seam, outages, no double counting, no leakage."""

import pandas as pd

from airalert import build, clean
from airalert.validate import check_seams

C = build.SEAM
H = pd.Timedelta(hours=1)


def frame(rows, source):
    """rows: (location, start, end | None, flags)."""
    df = pd.DataFrame(
        [
            {
                "location": loc,
                "level": "oblast",
                "raion": "",
                "hromada": "",
                "started_at": s,
                "finished_at": e if e is not None else pd.NaT,
                "source": source,
                "flags": f,
            }
            for loc, s, e, f in rows
        ],
        columns=["location", "level", "raion", "hromada", "started_at", "finished_at", "source", "flags"],
    )
    for c in ("started_at", "finished_at"):
        df[c] = df[c].astype(clean.TS_DTYPE)
    df["start_known_at"], df["end_known_at"] = df["started_at"], df["finished_at"]
    df["start_msg_id"] = df["end_msg_id"] = pd.array([pd.NA] * len(df), dtype="Int64")
    df["alert_type"] = "air_raid"
    return df[[*clean.ALERT_COLUMNS, "alert_type"]]


def test_seam_takes_dataset_before_and_telegram_after():
    ds = frame(
        [("K", C - 2 * H, C - H, ""), ("K", C - 0.5 * H, C + 0.5 * H, ""), ("K", C + 2 * H, C + 3 * H, "")],
        "dataset_official",
    )
    tg = frame([("K", C - 0.5 * H, C + 0.5 * H, ""), ("K", C + 2 * H, C + 3 * H, "")], "tg_official")
    raw = build.assemble(ds.drop(columns="alert_type"), tg, tg.iloc[0:0], [])
    assert list(raw["source"]) == ["dataset_official", "dataset_official", "tg_official"]
    assert check_seams(raw, C).status == "PASS"


def test_outage_filled_by_volunteer_and_official_gap_rows_dropped():
    outage = build.Window(C + 10 * H, C + 30 * H)
    off = frame(
        [
            ("K", C + 1 * H, C + 2 * H, ""),
            ("K", C + 9 * H, None, "source_gap"),  # cut by the outage
            ("K", C + 31 * H, C + 32 * H, ""),
        ],
        "tg_official",
    )
    vol = frame(
        [
            ("K", C + 1 * H, C + 2 * H, ""),  # official covers this: not taken
            ("K", C + 9 * H, C + 11 * H, ""),  # active when the outage began: taken
            ("K", C + 20 * H, C + 21 * H, ""),  # inside the outage: taken
            ("K", C + 29 * H, C + 31.5 * H, ""),  # running when official returns: taken, official dup dropped
        ],
        "tg_volunteer",
    )
    raw = build.assemble(frame([], "dataset_official").drop(columns="alert_type"), off, vol, [outage])
    got = [(r.source, (r.started_at - C) / H) for r in raw.itertuples()]
    assert got == [
        ("tg_official", 1.0),
        ("tg_volunteer", 9.0),
        ("tg_volunteer", 20.0),
        ("tg_volunteer", 29.0),
    ]
    assert check_seams(raw, C).status == "PASS"


def test_outages_detection():
    t = pd.Series([C, C + H, C + 10 * H])
    w = build.outages(t, C + 20 * H)
    assert [(x.start, x.end) for x in w] == [(C + H, C + 10 * H), (C + 10 * H, C + 20 * H)]


def test_no_leak_invariants_on_output():
    off = frame([("K", C + H, C + 2 * H, ""), ("K", C + 3 * H, None, "")], "tg_official")
    off.loc[1, "start_known_at"] = C + 3 * H + pd.Timedelta(seconds=5)  # live: known a bit later
    raw = build.assemble(frame([], "dataset_official").drop(columns="alert_type"), off, off.iloc[0:0], [])
    out = build.to_output(raw, build.union(raw))
    assert (out["start_known_at"] >= out["started_at"]).all()
    closed = out["finished_at"].notna()
    assert (out.loc[closed, "end_known_at"] >= out.loc[closed, "finished_at"]).all()
    assert out.loc[~closed, "end_known_at"].isna().all()  # open alerts: no invented end
    assert set(out["granularity"]) == {"raw", "oblast_union"}
