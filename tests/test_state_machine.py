from datetime import UTC, datetime, timedelta

from airalert.tg.locations import Location
from airalert.tg.state_machine import TimedEvent, build_intervals

KYIV = Location("Kyiv City", "oblast")
T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=2)


def ev(kind, minutes, loc=KYIV, msg_id=None, delay=0):
    t = T0 + timedelta(minutes=minutes)
    return TimedEvent(loc, kind, t, t + timedelta(seconds=delay), msg_id or minutes + 1)


def test_start_end_closes_interval():
    ivs, errs = build_intervals([ev("start", 0), ev("end", 30)], NOW)
    assert not errs and len(ivs) == 1
    assert (ivs[0].started_at, ivs[0].finished_at, ivs[0].flags) == (T0, T0 + timedelta(minutes=30), set())


def test_dup_start_keeps_earliest_and_flags():
    ivs, _ = build_intervals([ev("start", 0), ev("start", 10), ev("end", 30)], NOW)
    assert len(ivs) == 1 and ivs[0].started_at == T0 and ivs[0].flags == {"dup_start"}


def test_end_without_start_is_error():
    ivs, errs = build_intervals([ev("end", 5)], NOW)
    assert ivs == [] and [e.reason for e in errs] == ["end_without_start"]


def test_open_alert_stays_open():
    ivs, _ = build_intervals([ev("start", 0)], NOW)
    assert ivs[0].finished_at is None and ivs[0].end_known_at is None


def test_open_over_24h_flagged_not_closed():
    ivs, _ = build_intervals([ev("start", 0)], T0 + timedelta(hours=25))
    assert ivs[0].finished_at is None and "open_over_24h" in ivs[0].flags


def test_locations_independent():
    raion = Location("Kyivska oblast", "raion", "Buchanskyi raion")
    oblast = Location("Kyivska oblast", "oblast")
    ivs, errs = build_intervals(
        [ev("start", 0, raion), ev("start", 1, oblast), ev("end", 10, oblast), ev("end", 20, raion)], NOW
    )
    assert not errs
    assert {(i.location.level, i.finished_at - i.started_at) for i in ivs} == {
        ("raion", timedelta(minutes=20)),
        ("oblast", timedelta(minutes=9)),
    }


def test_known_at_carried():
    ivs, _ = build_intervals([ev("start", 0, delay=3), ev("end", 30, delay=7)], NOW)
    assert ivs[0].start_known_at - ivs[0].started_at == timedelta(seconds=3)
    assert ivs[0].end_known_at - ivs[0].finished_at == timedelta(seconds=7)


def tev(kind, minutes, alert_type, loc=KYIV, soft=False):
    t = T0 + timedelta(minutes=minutes)
    return TimedEvent(loc, kind, t, t, minutes + 1, "", alert_type, soft)


def test_air_raid_end_closes_threats():
    ivs, errs = build_intervals(
        [tev("start", 0, "air_raid"), tev("start", 5, "drones"), tev("end", 30, "air_raid")], NOW
    )
    assert not errs
    drones = next(i for i in ivs if i.alert_type == "drones")
    assert drones.finished_at == T0 + timedelta(minutes=30) and "closed_by_air_raid_end" in drones.flags


def test_specific_threat_end_only_closes_that_threat():
    ivs, _ = build_intervals([tev("start", 0, "kab"), tev("start", 1, "drones"), tev("end", 10, "kab")], NOW)
    assert {i.alert_type: i.finished_at is None for i in ivs} == {"kab": False, "drones": True}


def test_unspecified_end_closes_all_threats_not_air_raid():
    ivs, errs = build_intervals(
        [
            tev("start", 0, "air_raid"),
            tev("start", 1, "kab"),
            tev("start", 2, "threat_other"),
            tev("end", 10, "threat_unspecified"),
        ],
        NOW,
    )
    assert not errs
    state = {i.alert_type: (i.finished_at is None, i.flags) for i in ivs}
    assert state["air_raid"] == (True, set())
    assert state["kab"] == (False, {"closed_by_unspecified_end"})


def test_soft_start_is_not_dup():
    ivs, _ = build_intervals([tev("start", 0, "air_raid"), tev("start", 5, "air_raid", soft=True)], NOW)
    assert ivs[0].flags == set()


def test_source_gap_censors_open_intervals_and_restarts():
    gap_end = T0 + timedelta(hours=10)
    events = [
        tev("start", 0, "air_raid"),
        tev("start", 10 * 60 + 5, "air_raid"),
        tev("end", 10 * 60 + 30, "air_raid"),
    ]
    ivs, errs = build_intervals(events, T0 + timedelta(hours=11), gap_ends=[gap_end])
    assert not errs and len(ivs) == 2
    assert ivs[0].finished_at is None and ivs[0].flags == {"source_gap"}
    assert ivs[1].finished_at == T0 + timedelta(minutes=630) and ivs[1].flags == set()


def test_find_gaps():
    from airalert.tg.state_machine import find_gaps

    ts = [T0, T0 + timedelta(hours=1), T0 + timedelta(hours=8)]
    assert find_gaps(ts, T0 + timedelta(hours=8, minutes=5)) == [T0 + timedelta(hours=8)]
    assert find_gaps(ts, T0 + timedelta(hours=20)) == [T0 + timedelta(hours=8), T0 + timedelta(hours=20)]
