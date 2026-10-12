from datetime import UTC, datetime
from pathlib import Path

import pytest

from airalert.sitrep import collector, parser

SAMPLE = (Path(__file__).parent / "fixtures" / "sitrep_sample.md").read_text(encoding="utf-8")


def test_report_time_is_utc():
    assert parser.report_time(SAMPLE) == datetime(2026, 10, 12, 9, 7, 10, tzinfo=UTC)


def test_kyiv_city_and_oblast_raions():
    st = parser.kyiv_status(SAMPLE)
    city = [a for a in st if a.region_uk == "м. Київ"]
    assert len(city) == 1 and city[0].area_uk is None
    assert city[0].level == "yellow"
    assert city[0].started_at == datetime(2026, 10, 12, 7, 27, tzinfo=UTC)  # 10:27 Kyiv (EEST)
    assert city[0].elapsed_min == pytest.approx(100.2)
    oblast = {a.area_uk: a.level for a in st if a.region_uk == "Київська область"}
    assert oblast == dict.fromkeys(
        ["Вишгородський", "Броварський", "Бучанський", "Фастівський", "Обухівський", "Бориспільський"],
        "yellow",
    )


def test_mixed_levels_prefix_form():
    kh = {a.area_uk: a.level for a in parser.parse_status(SAMPLE) if a.region_uk == "Харківська область"}
    assert kh == {"Лозівський": "red", "Харківський": "yellow", "м. Харків": "yellow", "Харківська": "yellow"}


def test_start_on_previous_day():
    dn = [a for a in parser.parse_status(SAMPLE) if a.region_uk == "Дніпропетровська область"]
    assert {a.started_at for a in dn} == {datetime(2026, 10, 11, 8, 33, tzinfo=UTC)}
    assert dn[0].warning == "air raid alert and artillery shelling threat"
    assert len(dn) == 13 and {a.level for a in dn} == {"red"}


def test_threat_log_is_raw_section():
    log = parser.threat_log(SAMPLE)
    assert log.startswith("- **12:03 — attack drones")
    assert "## 5." not in log


class FakeSource:
    name = "fake"

    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def fetch(self, last_modified, etag):
        self.calls.append(last_modified)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_store_only_changes_and_send_if_modified_since(tmp_path):
    lm1, lm2 = "Mon, 12 Oct 2026 09:07:10 GMT", "Mon, 12 Oct 2026 09:08:10 GMT"
    src = FakeSource(
        [
            collector.Fetched(200, "a", lm1),
            collector.Fetched(304, last_modified=lm1),
            collector.Fetched(200, "a", lm1),  # same body again
            OSError("network down"),
            collector.Fetched(200, "b", lm2),
        ]
    )
    with collector.open_db(tmp_path / "s.sqlite") as conn:
        collector.poll_forever(conn, src, every=60, sleep=lambda _: None, iterations=5)
        assert [t for _, t in collector.read_snapshots(conn, "fake")] == ["b", "a"]
        assert conn.execute("SELECT COUNT(*) FROM collector_heartbeat").fetchone() == (1,)
    assert src.calls == [None, lm1, lm1, lm1, lm1]


def test_resume_uses_last_stored_last_modified(tmp_path):
    lm = "Mon, 12 Oct 2026 09:07:10 GMT"
    with collector.open_db(tmp_path / "s.sqlite") as conn:
        collector.store_if_changed(conn, "fake", collector.Fetched(200, "a", lm), "2026-10-12T09:07:30+00:00")
        src = FakeSource([collector.Fetched(304, last_modified=lm)])
        collector.poll_forever(conn, src, every=60, sleep=lambda _: None, iterations=1)
    assert src.calls == [lm]


def test_user_agent_has_contact():
    assert collector.user_agent("x@example.org").endswith("; x@example.org)")
