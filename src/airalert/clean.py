"""Normalisation of alert intervals into one schema, dedup, overlap merging and oblast union.

Unified alert schema (one row = one interval for one location):
    location, level, raion, hromada, started_at, finished_at, start_known_at, end_known_at,
    source, flags, start_msg_id, end_msg_id
All timestamps are tz-aware UTC (microsecond unit). ``finished_at`` is NaT for open alerts.
"""

import pandas as pd

TS_DTYPE = "datetime64[us, UTC]"
LOCATION_KEYS = ["location", "level", "raion", "hromada"]
ALERT_COLUMNS = [
    *LOCATION_KEYS,
    "started_at",
    "finished_at",
    "start_known_at",
    "end_known_at",
    "source",
    "flags",
    "start_msg_id",
    "end_msg_id",
]
LEVELS = ("oblast", "raion", "hromada")

# The author's parser closes a stale alert as started_at + 1h without marking it.
AUTHOR_IMPUTED_SECONDS = 3600
# eTryvoga processor draws the end as started_at + 30 min when the "end" message is missing.
VOLUNTEER_NAIVE_SECONDS = 1800

_FAR_FUTURE = pd.Timestamp("2262-01-01", tz="UTC")


def to_utc(values: pd.Series) -> pd.Series:
    """Parse ISO strings to tz-aware UTC; unparseable / empty values become NaT."""
    return pd.to_datetime(values.replace("", None), utc=True, format="ISO8601", errors="coerce").astype(
        TS_DTYPE
    )


def add_flag(flags: pd.Series, mask: pd.Series, flag: str) -> pd.Series:
    """Append ``flag`` to the comma-separated flags where ``mask`` is true."""
    out = flags.copy()
    mask = mask.fillna(False).astype(bool)
    out[mask] = out[mask].map(lambda f: _join_flags([f, flag]))
    return out


def _join_flags(parts) -> str:
    found = set()
    for p in parts:
        if isinstance(p, str) and p:
            found.update(x for x in p.split(",") if x)
    return ",".join(sorted(found))


def empty_alerts() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="str") for c in ALERT_COLUMNS})
    for c in ("started_at", "finished_at", "start_known_at", "end_known_at"):
        df[c] = df[c].astype(TS_DTYPE)
    for c in ("start_msg_id", "end_msg_id"):
        df[c] = df[c].astype("Int64")
    return df


def _finalise(df: pd.DataFrame) -> pd.DataFrame:
    for c in ("start_msg_id", "end_msg_id"):
        df[c] = pd.array(df[c], dtype="Int64") if c in df else pd.array([pd.NA] * len(df), dtype="Int64")
    return df[ALERT_COLUMNS].reset_index(drop=True)


def normalize_official(raw: pd.DataFrame) -> pd.DataFrame:
    """Vadimkin ``official_data_en.csv`` -> unified schema (no rows dropped)."""
    df = pd.DataFrame(
        {
            "location": raw["oblast"],
            "level": raw["level"],
            "raion": raw["raion"].fillna(""),
            "hromada": raw["hromada"].fillna(""),
            "started_at": to_utc(raw["started_at"]),
            "finished_at": to_utc(raw["finished_at"]),
            "source": "dataset_official",
            "flags": "",
        }
    )
    # The dataset is a historical snapshot: we "learn" about an event when it is published.
    df["start_known_at"] = df["started_at"]
    df["end_known_at"] = df["finished_at"]
    duration = (df["finished_at"] - df["started_at"]).dt.total_seconds()
    df["flags"] = add_flag(df["flags"], duration == AUTHOR_IMPUTED_SECONDS, "end_imputed")
    return _finalise(df)


def normalize_volunteer(raw: pd.DataFrame) -> pd.DataFrame:
    """Vadimkin ``volunteer_data_en.csv`` (eTryvoga, oblast level only) -> unified schema."""
    df = pd.DataFrame(
        {
            "location": raw["region"],
            "level": "oblast",
            "raion": "",
            "hromada": "",
            "started_at": to_utc(raw["started_at"]),
            "finished_at": to_utc(raw["finished_at"]),
            "source": "dataset_volunteer",
            "flags": "",
        }
    )
    df["start_known_at"] = df["started_at"]
    df["end_known_at"] = df["finished_at"]
    df["flags"] = add_flag(df["flags"], raw["naive"].str.lower() == "true", "naive_end")
    return _finalise(df)


def dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Drop exact duplicate intervals (same location, start, end, source)."""
    return df.drop_duplicates(subset=[*LOCATION_KEYS, "started_at", "finished_at", "source"]).reset_index(
        drop=True
    )


def merge_overlaps(
    df: pd.DataFrame, keys: list[str] = LOCATION_KEYS, flag: str | None = "merged_overlap"
) -> pd.DataFrame:
    """Merge overlapping or touching intervals within each ``keys`` group.

    Open intervals (NaT end) extend to infinity and swallow everything after them.
    Knowledge times stay leak-free: the merged start is known when the earliest row was known,
    the merged end when the last contributing end was known.
    """
    if df.empty:
        return df.copy()
    d = df.sort_values([*keys, "started_at"], kind="mergesort").reset_index(drop=True)
    by = [d[k] for k in keys]
    end = d["finished_at"].fillna(_FAR_FUTURE)
    running_end = end.groupby(by, sort=False).cummax()
    prev_end = running_end.groupby(by, sort=False).shift()
    run = (prev_end.isna() | (d["started_at"] > prev_end)).cumsum()

    sizes = run.map(run.value_counts())
    if (sizes == 1).all():
        return d

    single = d[sizes == 1]
    multi = d[sizes > 1].assign(_run=run[sizes > 1], _end=end[sizes > 1])
    g = multi.groupby("_run", sort=False)
    out = g.head(1).set_index("_run")
    last = multi.loc[g["_end"].idxmax()].set_index("_run")
    out["finished_at"] = last["finished_at"]
    out["end_msg_id"] = last["end_msg_id"]
    out["end_known_at"] = g["end_known_at"].max().where(out["finished_at"].notna())
    out["flags"] = g["flags"].agg(lambda s: _join_flags([*s, flag] if flag else s))
    merged = pd.concat([single, out.drop(columns="_end").reset_index(drop=True)], ignore_index=True)
    merged = merged.sort_values([*keys, "started_at"], kind="mergesort").reset_index(drop=True)
    for c in ("start_msg_id", "end_msg_id"):
        merged[c] = merged[c].astype("Int64")
    for c in ("started_at", "finished_at", "start_known_at", "end_known_at"):
        merged[c] = merged[c].astype(TS_DTYPE)
    return merged[df.columns]


def oblast_union(df: pd.DataFrame) -> pd.DataFrame:
    """ "Alert anywhere in the oblast": union of all intervals of an oblast across all levels."""
    d = df.assign(level="oblast", raion="", hromada="")
    return merge_overlaps(d, keys=["location"], flag=None)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Full cleaning for one source: dedup then merge overlaps per exact location."""
    return merge_overlaps(dedup(df))
