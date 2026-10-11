"""Turn parsed start/end events into alert intervals; one state machine per (location, alert_type).

Policy:
- start while idle    -> open an interval
- start while active  -> keep the earlier start, flag ``dup_start`` (never overwrite); "soft" starts
  (єТривога yellow/red level re-announcements) are expected while active and are not flagged
- end while active    -> close it
- end while idle      -> parse_errors ``end_without_start``
- active > 24 h       -> flag ``open_over_24h`` (never closed automatically)
- an interval still open at the end of the journal keeps ``finished_at = None``
- the channel silent for > ``SOURCE_GAP`` (outage: air_alert_ua 2026-08-29…09-02, dead since 09-07)
  -> every open interval gets flag ``source_gap`` and stays without an end (we do not know it, and
  inventing one would be imputation); state restarts after the gap. So "ongoing" means
  ``finished_at IS NULL`` and no ``source_gap`` flag.

Threats (drones, KAB, ballistic, …) are announced inside an air raid and are very often not ended
explicitly: observed in air_alert_ua, the air-raid "Відбій тривоги" for a location ends everything
there. So an air-raid end also closes the open threats of that location (flag
``closed_by_air_raid_end``). An end that does not name its threat (``threat_unspecified``, e.g.
"🟡 Відбій" for Donetsk oblast) is an all-clear for threats there: it closes every open threat of that
location (flag ``closed_by_unspecified_end`` when it closed more than one).
"""

import itertools
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from airalert.tg.locations import Location
from airalert.tg.parser import AIR_RAID, THREAT_UNSPECIFIED, Kind

OPEN_TOO_LONG = timedelta(hours=24)
# air_alert_ua posts every few minutes country-wide; 6 h of silence is an outage, not a quiet night.
SOURCE_GAP = timedelta(hours=6)


@dataclass(frozen=True)
class TimedEvent:
    location: Location
    kind: Kind
    posted_at: datetime
    known_at: datetime  # received_at for live messages, posted_at for backfill
    msg_id: int
    text: str = ""
    alert_type: str = AIR_RAID
    soft: bool = False


@dataclass
class Interval:
    location: Location
    started_at: datetime
    start_known_at: datetime
    start_msg_id: int
    alert_type: str = AIR_RAID
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


def find_gaps(posted: list[datetime], now: datetime, gap: timedelta = SOURCE_GAP) -> list[datetime]:
    """Ends of silences longer than ``gap`` (``now`` included if the channel is silent right now).
    ``posted`` are all message times of the channel, sorted."""
    ends = [b for a, b in itertools.pairwise(posted) if b - a > gap]
    if posted and now - posted[-1] > gap:
        ends.append(now)
    return ends


def build_intervals(
    events: Iterable[TimedEvent], now: datetime, gap_ends: list[datetime] | None = None
) -> tuple[list[Interval], list[Error]]:
    """``events`` must be in channel order (posted_at, msg_id); ``gap_ends`` from ``find_gaps``."""
    active: dict[tuple, Interval] = {}
    gaps = sorted(gap_ends or [])
    done: list[Interval] = []
    errors: list[Error] = []

    def close(key: tuple, ev: TimedEvent, flag: str | None = None) -> None:
        iv = active.pop(key)
        iv.finished_at, iv.end_known_at, iv.end_msg_id = ev.posted_at, ev.known_at, ev.msg_id
        if flag:
            iv.flags.add(flag)
        done.append(iv)

    def censor() -> None:
        for iv in active.values():
            iv.flags.add("source_gap")
            done.append(iv)
        active.clear()

    for ev in events:
        while gaps and ev.posted_at >= gaps[0]:
            gaps.pop(0)
            censor()
        loc = ev.location.key
        if ev.kind == "start":
            key = (loc, ev.alert_type)
            if key in active:
                if not ev.soft:
                    active[key].flags.add("dup_start")
            else:
                active[key] = Interval(ev.location, ev.posted_at, ev.known_at, ev.msg_id, ev.alert_type)
            continue

        open_threats = [k for k in active if k[0] == loc and k[1] != AIR_RAID]
        if ev.alert_type == AIR_RAID:
            if (loc, AIR_RAID) in active:
                close((loc, AIR_RAID), ev)
            elif not open_threats:
                errors.append(Error(ev.msg_id, ev.posted_at, "end_without_start", ev.text))
            for k in open_threats:
                close(k, ev, "closed_by_air_raid_end")
        elif ev.alert_type == THREAT_UNSPECIFIED:
            if not open_threats:
                errors.append(Error(ev.msg_id, ev.posted_at, "end_without_start", ev.text))
            for k in open_threats:
                close(k, ev, "closed_by_unspecified_end" if len(open_threats) > 1 else None)
        elif (loc, ev.alert_type) in active:
            close((loc, ev.alert_type), ev)
        else:
            errors.append(Error(ev.msg_id, ev.posted_at, "end_without_start", ev.text))

    if gaps:  # the journal ends inside a gap (source silent now)
        censor()
    done.extend(active.values())
    for iv in done:
        if (iv.finished_at or now) - iv.started_at > OPEN_TOO_LONG:
            iv.flags.add("open_over_24h")
    done.sort(key=lambda iv: (iv.started_at, iv.start_msg_id, iv.location.key, iv.alert_type))
    return done, errors
