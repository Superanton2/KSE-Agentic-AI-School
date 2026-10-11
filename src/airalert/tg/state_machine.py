"""Turn parsed start/end events into alert intervals, one state machine per location.

Policy:
- start while idle    -> open an interval
- start while active  -> keep the earlier start, flag ``dup_start`` (never overwrite)
- end while active    -> close it
- end while idle      -> parse_errors ``end_without_start``
- active > 24 h       -> flag ``open_over_24h`` (never closed automatically)
- an interval still open at the end of the journal keeps ``finished_at = None``
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from airalert.tg.locations import Location
from airalert.tg.parser import Kind

OPEN_TOO_LONG = timedelta(hours=24)


@dataclass(frozen=True)
class TimedEvent:
    location: Location
    kind: Kind
    posted_at: datetime
    known_at: datetime  # received_at for live messages, posted_at for backfill
    msg_id: int
    text: str = ""


@dataclass
class Interval:
    location: Location
    started_at: datetime
    start_known_at: datetime
    start_msg_id: int
    finished_at: datetime | None = None
    end_known_at: datetime | None = None
    end_msg_id: int | None = None
    flags: set[str] = field(default_factory=set)


@dataclass
class Error:
    msg_id: int
    posted_at: datetime
    reason: str
    text: str


def build_intervals(events: Iterable[TimedEvent], now: datetime) -> tuple[list[Interval], list[Error]]:
    """``events`` must be in channel order (posted_at, msg_id)."""
    active: dict[tuple, Interval] = {}
    done: list[Interval] = []
    errors: list[Error] = []
    for ev in events:
        key = ev.location.key
        cur = active.get(key)
        if ev.kind == "start":
            if cur is None:
                active[key] = Interval(ev.location, ev.posted_at, ev.known_at, ev.msg_id)
            else:
                cur.flags.add("dup_start")
        elif cur is None:
            errors.append(Error(ev.msg_id, ev.posted_at, "end_without_start", ev.text))
        else:
            cur.finished_at, cur.end_known_at, cur.end_msg_id = ev.posted_at, ev.known_at, ev.msg_id
            done.append(active.pop(key))
    done.extend(active.values())
    for iv in done:
        if (iv.finished_at or now) - iv.started_at > OPEN_TOO_LONG:
            iv.flags.add("open_over_24h")
    done.sort(key=lambda iv: (iv.started_at, iv.start_msg_id, iv.location.key))
    return done, errors
