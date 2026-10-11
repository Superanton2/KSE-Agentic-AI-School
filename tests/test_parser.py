"""air_alert_ua parser on real messages (tests/fixtures/air_alert_ua_sample.json) + synthetic edge cases."""

import pytest

from airalert.tg.locations import Location
from airalert.tg.parser import parse

KYIV = Location("Kyiv City", "oblast")
DONETSK = Location("Donetska oblast", "oblast")

# msg_id -> expected (kind, alert_type) for every event, or the ignore reason
REAL = {
    331768: ("start", "air_raid"),  # 🔴 Повітряна тривога в м. Київ
    338375: ("start", "air_raid"),
    331277: ("end", "air_raid"),  # 🟡 Відбій тривоги … тривога ще триває у
    331188: ("start", "kab"),  # 🔴🔴 Загроза керованих авіабомб
    331191: ("start", "kab"),  # 🟠 УВАГА!!! … КАБів
    331231: ("end", "kab"),  # 🟡 по КАБам відбій
    332003: ("end", "kab"),
    337105: ("start", "kab"),  # 🟠 🔴 ЧЕРВОНИЙ РІВЕНЬ НЕБЕЗПЕКИ: Загроза застосування КАБ
    337135: ("end", "kab"),  # 🟢 🟢 ВІДБІЙ ЧЕРВОНОГО РІВНЯ …
    331262: ("start", "missile"),
    331293: ("start", "artillery"),  # 🔴 Загроза артобстрілу!
    332646: ("end", "artillery"),
    331322: ("start", "drones"),
    331333: ("start", "drones"),
    336749: ("start", "drones"),  # 🟠 🟡 Загроза ударних БпЛА
    338377: ("start", "drones"),
    336170: ("end", "drones"),  # 🟢 Увага / Відбій атаки дронів камікадзе
    337301: ("start", "street_fight"),
    337302: ("end", "street_fight"),
    337656: ("start", "radiation"),
    331210: ("start", "threat_other"),  # 🟠 АБ 9676 … напрямок
    331459: ("end", "threat_unspecified"),  # 🟡 УВАГА!!! тривога ще триває у …
    332018: ("end", "threat_unspecified"),  # 🟡 Відбій
    334745: "info",  # channel announcement
    338009: "no_text",
}


@pytest.mark.parametrize(("msg_id", "expected"), REAL.items())
def test_real_messages(official_msgs, msg_id, expected):
    r = parse(official_msgs[msg_id])
    if isinstance(expected, str):
        assert r.ignored == expected and not r.events
    else:
        assert r.events and not r.errors
        assert {(e.kind, e.alert_type) for e in r.events} == {expected}


def test_kyiv_city_hashtag_real(official_msgs):
    assert [e.location for e in parse(official_msgs[331768]).events] == [KYIV]


def test_partial_flag_on_yellow(official_msgs):
    assert all(e.partial for e in parse(official_msgs[331277]).events)


def test_all_fixtures_parse_without_errors(official_msgs):
    assert {i: parse(t).errors for i, t in official_msgs.items() if parse(t).errors} == {}


def test_many_raions_in_one_message():
    r = parse(
        "🟢 12:33 Відбій тривоги в\n• Мелітопольський район\n• Василівський район\n"
        "#Мелітопольський_район #Василівський_район"
    )
    assert [(e.location.raion, e.kind, e.alert_type) for e in r.events] == [
        ("Melitopolskyi raion", "end", "air_raid"),
        ("Vasylivskyi raion", "end", "air_raid"),
    ]


def test_test_region_ignored():
    assert parse("🔴 10:00 Повітряна тривога в Тестовий Регіон\n#Тестовий_Регіон").ignored == "test_region"


def test_unknown_hashtag_goes_to_errors_but_known_kept():
    r = parse("🔴 10:00 Повітряна тривога в\n• Атлантида\n#Атлантида #Донецька_область")
    assert r.errors == ["unknown_hashtag:#атлантида"]
    assert [e.location for e in r.events] == [DONETSK]


def test_no_text_and_no_hashtags():
    assert parse(None).ignored == "no_text"
    assert parse("   ").ignored == "no_text"
    assert parse("🔴 10:00 Повітряна тривога в м. Київ").errors == ["no_hashtags"]
