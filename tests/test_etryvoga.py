"""єТривога parser on real messages (tests/fixtures/etryvoga_sample.json)."""

import pytest

from airalert.tg.etryvoga import parse, parse_place
from airalert.tg.locations import Location

KYIV = Location("Kyiv City", "oblast")

REAL = {
    600708: {("start", "air_raid")},  # 🚨 Київ
    601539: {("end", "air_raid")},  # 🟢 Київ
    602091: {("end", "air_raid")},  # batch 🟢 Відбій тривоги
    599971: {("start", "air_raid")},  # renamed raion Берестинський
    615314: {("start", "air_raid")},  # 🟡 Жовтий рівень (single)
    614480: {("start", "air_raid")},  # 🟡 Жовтий рівень (batch)
    614024: {("start", "air_raid"), ("start", "air_raid_red")},  # 🔴 Червоний рівень
    614025: {("start", "air_raid"), ("start", "air_raid_red")},
    615399: {("end", "air_raid_red")},  # Відбій червоної, жовта ще триває
    616267: {("end", "air_raid")},  # "технічна помилка … тривога у місті відсутня"
    600209: {("start", "air_raid"), ("end", "air_raid")},  # two sections in one message
    615208: {("end", "air_raid_red"), ("start", "air_raid"), ("end", "air_raid")},
    599930: "threat_notice",  # ⚠️ вибухи
    599934: "threat_notice",  # 💣
    599986: "threat_notice",  # 👁️
    600042: "threat_notice",  # 🚀
    600054: "threat_notice",  # 💥
    600212: "threat_notice",  # 🛸 city district
    602234: "threat_notice",  # 🛸 Kyiv district
    601155: "threat_notice",  # 🟢 Відбій загрози БПЛА (threat, not air raid)
    615311: "info",  # hourly summary
    614540: "info",  # announcement
    616715: "info",
}


@pytest.mark.parametrize(("msg_id", "expected"), REAL.items())
def test_real_messages(etryvoga_msgs, msg_id, expected):
    r = parse(etryvoga_msgs[msg_id])
    if isinstance(expected, str):
        assert r.ignored == expected and not r.events and not r.errors
    else:
        assert not r.errors
        assert {(e.kind, e.alert_type) for e in r.events} == expected


def test_kyiv_and_levels_are_soft(etryvoga_msgs):
    assert [(e.location, e.soft) for e in parse(etryvoga_msgs[600708]).events] == [(KYIV, False)]
    assert all(e.soft for e in parse(etryvoga_msgs[615314]).events)


def test_batch_places(etryvoga_msgs):
    locs = [e.location for e in parse(etryvoga_msgs[602091]).events]
    assert locs[0] == KYIV and len(locs) == 4
    assert locs[1] == Location("Chernihivska oblast", "raion", "Nizhynskyi raion")


def test_renamed_raion_maps_to_dataset_name():
    assert parse_place("Берестинський район (Харківська обл.)") == Location(
        "Kharkivska oblast", "raion", "Krasnohradskyi raion"
    )


def test_place_forms():
    assert parse_place("Київ") == KYIV
    assert parse_place("Конотоп (Сумська обл.)") == Location("Sumska oblast", "hromada", "", "Konotop")
    assert parse_place("Київський (Харків, Харківська обл.)").location == "Kharkivska oblast"
    assert parse_place("Харківська обл.") == Location("Kharkivska oblast", "oblast")
    assert parse_place("Севастополь (Крим)") is None


def test_truncated_list_is_an_error(etryvoga_msgs):
    r = parse(etryvoga_msgs[615720])
    assert "truncated_place_list" in r.errors and r.events


def test_bulleted_batch_since_september():
    r = parse(
        "🟢 Відбій тривоги\n• Вознесенський район (Миколаївська обл.)\n• Первомайський район (Миколаївська обл.)"
    )
    assert not r.errors and [e.location.raion for e in r.events] == [
        "Voznesenskyi raion",
        "Pervomaiskyi raion",
    ]
