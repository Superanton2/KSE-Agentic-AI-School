"""Deterministic ``raw_messages`` -> ``alerts`` + ``parse_errors`` per channel (one parser per channel)."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from airalert.tg import etryvoga, parser, store
from airalert.tg.state_machine import TimedEvent, build_intervals, find_gaps

SOURCE_BY_CHANNEL = {"air_alert_ua": "tg_official", "UkraineAlarmSignal": "tg_volunteer"}
PARSER_BY_CHANNEL = {"air_alert_ua": parser.parse, "UkraineAlarmSignal": etryvoga.parse}


@dataclass
class RebuildStats:
    messages: int = 0
    events: int = 0
    alerts: int = 0
    open_alerts: int = 0
    ignored: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)
    messages_with_errors: int = 0
    by_type: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


def rebuild(conn, channel: str, now: datetime | None = None) -> RebuildStats:
    now = now or datetime.now(UTC)
    msgs = store.read_messages(conn, channel)
    stats = RebuildStats(messages=len(msgs))
    events: list[TimedEvent] = []
    errors: list[tuple] = []
    parse = PARSER_BY_CHANNEL[channel]
    for r in msgs.itertuples(index=False):
        res = parse(r.text)
        if res.ignored:
            stats.ignored[res.ignored] += 1
            continue
        if res.errors:
            stats.messages_with_errors += 1
        for reason in res.errors:
            stats.errors[reason.split(":")[0]] += 1
            errors.append((channel, r.msg_id, r.posted_at, reason, r.text))
        posted = _ts(r.posted_at)
        # Live: we learnt about it when we received it. Backfill/history: at publication time.
        known = max(posted, _ts(r.received_at)) if r.ingest_mode == "live" else posted
        events += [
            TimedEvent(e.location, e.kind, posted, known, r.msg_id, r.text, e.alert_type, e.soft)
            for e in res.events
        ]
    stats.events = len(events)

    gaps = find_gaps([_ts(p) for p in msgs["posted_at"]], now)
    stats.gaps = [store.iso(g) for g in gaps]
    intervals, sm_errors = build_intervals(events, now, gaps)
    for e in sm_errors:
        stats.errors[e.reason] += 1
        errors.append((channel, e.msg_id, store.iso(e.posted_at), e.reason, e.text))

    df = pd.DataFrame(
        [
            {
                "channel": channel,
                "location": iv.location.location,
                "level": iv.location.level,
                "raion": iv.location.raion,
                "hromada": iv.location.hromada,
                "alert_type": iv.alert_type,
                "started_at": store.iso(iv.started_at),
                "finished_at": store.iso(iv.finished_at),
                "start_known_at": store.iso(iv.start_known_at),
                "end_known_at": store.iso(iv.end_known_at),
                "source": SOURCE_BY_CHANNEL.get(channel, f"tg_{channel}"),
                "flags": ",".join(sorted(iv.flags)),
                "start_msg_id": iv.start_msg_id,
                "end_msg_id": iv.end_msg_id,
            }
            for iv in intervals
        ],
        columns=store.ALERT_DB_COLUMNS,
    )
    store.replace_derived(conn, channel, df, errors)
    stats.alerts = len(df)
    stats.open_alerts = int(df["finished_at"].isna().sum())
    stats.by_type = df["alert_type"].value_counts().to_dict()
    return stats


def load_alerts(conn, channel: str) -> pd.DataFrame:
    """``alerts`` rows of one channel in the unified clean schema (+ alert_type)."""
    from airalert import clean

    df = store.read_alerts(conn, channel)
    for c in ("started_at", "finished_at", "start_known_at", "end_known_at"):
        df[c] = clean.to_utc(df[c].fillna(""))
    for c in ("start_msg_id", "end_msg_id"):
        df[c] = df[c].astype("Int64")
    df["flags"] = df["flags"].fillna("")
    return df[[*clean.ALERT_COLUMNS, "alert_type"]]
