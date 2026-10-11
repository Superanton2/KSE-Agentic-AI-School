"""Parser tests on the format documented by the original processor.

TODO(after first backfill): replace/extend with real messages from tests/fixtures/air_alert_ua_sample.json.
"""

from airalert.tg.locations import Location
from airalert.tg.parser import parse

DONETSK = Location("Donetska oblast", "oblast")


def test_start_oblast():
    r = parse("🔴 16:29 Повітряна тривога в Донецька область\n#Донецька_область")
    assert [(e.location, e.kind) for e in r.events] == [(DONETSK, "start")]
    assert not r.errors and r.ignored is None


def test_end_oblast():
    r = parse("🟢 17:02 Відбій тривоги в Донецька область.\n#Донецька_область")
    assert [(e.location, e.kind, e.partial) for e in r.events] == [(DONETSK, "end", False)]


def test_partial_end_closes_oblast_level():
    r = parse(
        "🟡 06:22 Відбій тривоги в Дніпропетровська область\n"
        "(тривога ще триває у якомусь районі)\n#Дніпропетровська_область"
    )
    assert len(r.events) == 1
    e = r.events[0]
    assert (e.location.level, e.kind, e.partial) == ("oblast", "end", True)


def test_many_raions_in_one_message():
    r = parse(
        "🟢 12:33 Відбій тривоги в\n• Мелітопольський район\n• Василівський район\n"
        "#Мелітопольський_район #Василівський_район"
    )
    assert [(e.location.raion, e.kind) for e in r.events] == [
        ("Melitopolskyi raion", "end"),
        ("Vasylivskyi raion", "end"),
    ]


def test_kyiv_city():
    r = parse("🔴 01:02 Повітряна тривога в м. Київ\n#м_Київ")
    assert r.events[0].location == Location("Kyiv City", "oblast")


def test_test_region_ignored():
    assert parse("🔴 10:00 Повітряна тривога в Тестовий Регіон\n#Тестовий_Регіон").ignored == "test_region"


def test_unknown_hashtag_goes_to_errors_but_known_kept():
    r = parse("🔴 10:00 Повітряна тривога в\n• Атлантида\n#Атлантида #Донецька_область")
    assert r.errors == ["unknown_hashtag:#атлантида"]
    assert [e.location for e in r.events] == [DONETSK]


def test_no_text_and_unknown_kind():
    assert parse(None).ignored == "no_text"
    assert parse("   ").ignored == "no_text"
    assert parse("Шановні підписники!\n#новини").errors == ["unknown_kind"]
    assert parse("🔴 10:00 Повітряна тривога").errors == ["no_hashtags"]
