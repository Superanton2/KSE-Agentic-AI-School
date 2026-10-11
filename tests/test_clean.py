import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from airalert import clean

T0 = pd.Timestamp("2026-01-01", tz="UTC")


def alerts(rows):
    """rows: (location, level, raion, start_min, end_min | None)."""
    df = pd.DataFrame(
        [
            {
                "location": loc,
                "level": level,
                "raion": raion,
                "hromada": "",
                "started_at": T0 + pd.Timedelta(minutes=s),
                "finished_at": T0 + pd.Timedelta(minutes=e) if e is not None else pd.NaT,
                "source": "test",
                "flags": "",
            }
            for loc, level, raion, s, e in rows
        ]
    )
    for c in ("started_at", "finished_at"):
        df[c] = df[c].astype(clean.TS_DTYPE)
    df["start_known_at"], df["end_known_at"] = df["started_at"], df["finished_at"]
    df["start_msg_id"] = df["end_msg_id"] = pd.array([pd.NA] * len(df), dtype="Int64")
    return df[clean.ALERT_COLUMNS]


def test_dedup_exact():
    df = alerts([("A", "oblast", "", 0, 10), ("A", "oblast", "", 0, 10), ("A", "oblast", "", 20, 30)])
    assert len(clean.dedup(df)) == 2


def test_merge_overlaps_and_flags():
    df = alerts([("A", "oblast", "", 0, 10), ("A", "oblast", "", 5, 20), ("A", "oblast", "", 30, 40)])
    m = clean.merge_overlaps(df)
    assert len(m) == 2
    assert m.iloc[0]["finished_at"] == T0 + pd.Timedelta(minutes=20)
    assert m.iloc[0]["flags"] == "merged_overlap" and m.iloc[1]["flags"] == ""


def test_open_interval_swallows_later():
    m = clean.merge_overlaps(alerts([("A", "oblast", "", 0, None), ("A", "oblast", "", 30, 40)]))
    assert len(m) == 1 and pd.isna(m.iloc[0]["finished_at"]) and pd.isna(m.iloc[0]["end_known_at"])


def test_union_per_oblast_across_levels():
    df = alerts([("A", "raion", "r1", 0, 10), ("A", "raion", "r2", 5, 15), ("A", "oblast", "", 30, 35)])
    u = clean.oblast_union(df)
    assert list(u["level"].unique()) == ["oblast"] and len(u) == 2


intervals = st.lists(
    st.tuples(st.sampled_from(["r1", "r2", "r3"]), st.integers(0, 500), st.integers(1, 120)),
    min_size=1,
    max_size=40,
)


@settings(max_examples=200, deadline=None)
@given(intervals)
def test_union_properties(rows):
    df = clean.dedup(alerts([("A", "raion", r, s, s + d) for r, s, d in rows]))
    u = clean.oblast_union(df)
    starts, ends = u["started_at"].tolist(), u["finished_at"].tolist()
    assert all(ends[i] < starts[i + 1] for i in range(len(u) - 1)), "union has overlaps"
    dur = lambda d: (d["finished_at"] - d["started_at"]).sum()  # noqa: E731
    assert dur(u) <= dur(df)
    assert dur(u) >= (df["finished_at"] - df["started_at"]).max()
    assert u["start_known_at"].ge(u["started_at"]).all() and u["end_known_at"].ge(u["finished_at"]).all()
