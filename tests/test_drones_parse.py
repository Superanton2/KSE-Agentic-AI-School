"""Drone-channel parser: pattern table, real-message fixtures, hand-written cases, gazetteer, versions."""

import json
from pathlib import Path

import pandas as pd
import pytest

from airalert.drones import evaluate as ev
from airalert.drones import mentions as dm
from airalert.drones import patterns as pt
from airalert.drones.gazetteer import Gazetteer, clean_place, lemma_forms
from airalert.drones.normalize import key, normalize
from airalert.drones.parse import parse_message

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "drones"
EMPTY_EDITS = pd.DataFrame(columns=["channel", "msg_id", "edited_at", "old_text", "new_text", "received_at"])


@pytest.fixture(scope="module")
def gz() -> Gazetteer:
    return Gazetteer.load(ROOT / "data" / "gazetteer")


def _raw(channel: str, msgs: list[dict], mode: str = "backfill") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "channel": channel,
                "msg_id": m["msg_id"],
                "posted_at": m.get("posted_at", "2026-10-12T08:49:13+00:00"),
                "edited_at": m.get("edited_at"),
                "text": m["text"],
                "received_at": m.get("received_at", m.get("posted_at", "2026-10-12T08:49:13+00:00")),
                "ingest_mode": mode,
            }
            for m in msgs
        ]
    )


def _mentions(gz, channel: str, text: str) -> list[tuple]:
    _, men = dm.build(_raw(channel, [{"msg_id": 1, "text": text}]), EMPTY_EDITS, gz)
    return [
        (
            r.kind,
            None if pd.isna(r["count"]) else int(r["count"]),
            r.place_norm if pd.notna(r.place_norm) else None,
            r.oblast,
        )
        for _, r in men.iterrows()
    ]


# ---------------------------------------------------------------- pattern table


@pytest.mark.parametrize("p", pt.ALL_PATTERNS, ids=lambda p: p.name)
def test_pattern_examples(p):
    for ex in p.examples:
        assert p.regex.search(normalize(ex)), f"{p.name} should match {ex!r}"
    for ex in p.non_examples:
        assert not p.regex.search(normalize(ex)), f"{p.name} should not match {ex!r}"


# ---------------------------------------------------------------- real messages (reviewed fixtures)


def _fixture_cases():
    for f in sorted(FIX.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for m in data["messages"]:
            yield pytest.param(f.stem, m, id=f"{f.stem}:{m['msg_id']}")


def test_fixture_counts():
    n = {f.stem: len(json.loads(f.read_text(encoding="utf-8"))["messages"]) for f in FIX.glob("*.json")}
    assert n["kudy_letyt"] >= 40 and n["kpszsu"] >= 10 and n["kyiv_nebo"] >= 10


@pytest.mark.parametrize(("channel", "msg"), list(_fixture_cases()))
def test_real_messages(gz, channel, msg):
    _, men = dm.build(_raw(channel, [msg]), EMPTY_EDITS, gz)
    got = [
        [
            int(r.line_no),
            r.kind,
            None if pd.isna(r["count"]) else int(r["count"]),
            None if pd.isna(r.place_norm) else r.place_norm,
            None if pd.isna(r.oblast) else r.oblast,
        ]
        for _, r in men.iterrows()
    ]
    assert got == msg["expected"]


# ---------------------------------------------------------------- hand-written expectations


@pytest.mark.parametrize(
    ("channel", "text", "expected"),
    [
        # kudy_letyt format from the task, plus real 2026-10-12 attack posts
        (
            "kudy_letyt",
            "Київщина:\nРеактивний БпЛА курсом на Бровари\n2х Реактивні БпЛА курсом на Васильків\n"
            "Чернігівщина:\n3х.Реактивні БпЛА курсом на Славутич",
            [
                ("drone_jet", None, "Бровари", "UA.13"),
                ("drone_jet", 2, "Васильків", "UA.13"),
                ("drone_jet", 3, "Славутич", "UA.13"),
            ],
        ),
        (
            "kudy_letyt",
            "Київ:\nРеактивний БпЛА курсом на Відрадний \nРеактивний БпЛА курсом на Сирець",
            [("drone_jet", None, "Відрадний", "UA.12"), ("drone_jet", None, "Сирець", "UA.12")],
        ),
        ("kudy_letyt", "Київ: Реактивний БпЛА курсом на Гнідин", [("drone_jet", None, "Гнідин", "UA.13")]),
        ("kudy_letyt", "Київ:\nРеактивний БпЛА курсом на Шулявку", [("drone_jet", None, "Шулявка", "UA.12")]),
        ("kudy_letyt", "Увага. Знижується!", []),
        ("kudy_letyt", "Київ:\nДорозвідка по БпЛА", []),
        (
            "kudy_letyt",
            "Дніпропетровщина:\nБандероль курсом на Синельникове",
            [("missile", None, "Синельникове", "UA.04")],
        ),
        ("kudy_letyt", "Дніпропетровщина:\nБандероль курсом на Самар", [("missile", None, "Самар", "UA.04")]),
        (
            "kudy_letyt",
            "Кіровоградщина:\nРеактивний БпЛА курсом на Олександрію\nРеактивний БпЛА курсом на Компаніївку",
            [("drone_jet", None, "Олександрія", "UA.10"), ("drone_jet", None, "Компаніївка", "UA.10")],
        ),
        ("kudy_letyt", "2х Бандеролі на Овідіополь (Одещина)", [("missile", 2, "Овідіополь", "UA.17")]),
        (
            "kudy_letyt",
            "Одещина:\nРеактивний БпЛА курсом на Південне",
            [("drone_jet", None, "Південне", "UA.17")],
        ),
        ("kudy_letyt", "📢 Надіслати новину", []),
        # kpszsu: emoji kinds, genitive targets, approach side, bare Kyiv districts
        (
            "kpszsu",
            "🏍 Київщина: реактивний БпЛА в напрямку Димера з півночі.",
            [("drone_jet", None, "Димер", "UA.13")],
        ),
        ("kpszsu", "🏍 Видубичі!", [("drone_jet", None, "Видубичі", "UA.12")]),
        (
            "kpszsu",
            "🏍 Борщагівка! Виноградар!",
            [("drone_jet", None, "Борщагівка", "UA.12"), ("drone_jet", None, "Виноградар", "UA.12")],
        ),
        ("kpszsu", "🛵 БпЛА на Харків з півночі.", [("drone", None, "Харків", "UA.07")]),
        (
            "kpszsu",
            "🏍 Черкащина: реактивний БпЛА в напрямку Умані, Христинівки",
            [("drone_jet", None, "Умань", "UA.01")],
        ),
        ("kpszsu", '🚀Дніпропетровщина: "Бандероль" курсом на Самар.', [("missile", None, "Самар", "UA.04")]),
        ("kpszsu", "💣КАБи на Дніпропетровщину!", [("kab", None, "Дніпропетровська", "UA.04")]),
        # kyiv_nebo: bare districts / suburbs, counts, all-clear
        (
            "kyiv_nebo",
            "Борщагівки, Вишневе",
            [("unknown", None, "Борщагівка", "UA.12"), ("unknown", None, "Вишневе", "UA.13")],
        ),
        ("kyiv_nebo", "2 на Правому", [("unknown", 2, "Правий берег", "UA.12")]),
        ("kyiv_nebo", "Один мінус, один Видубичі", [("unknown", 1, "Видубичі", "UA.12")]),
        ("kyiv_nebo", "Біля Києва поки все", []),
        ("kyiv_nebo", "Сам Київ поки без загроз", []),
    ],
)
def test_hand_written(gz, channel, text, expected):
    assert _mentions(gz, channel, text) == expected


def test_status_line_kinds():
    kinds = {
        t: parse_message(t, "kyiv_nebo")[0].line_kind
        for t in ["Падає", "Відбій", "Мінус", "Дорозвідка в області"]
    }
    assert kinds == {
        "Падає": "status:descending",
        "Відбій": "status:all_clear",
        "Мінус": "status:shot_down",
        "Дорозвідка в області": "status:recheck",
    }
    assert (
        parse_message("Увага. Знижується!", "kudy_letyt")[0].line_kind == "status:descending"
    )  # a threat, not all-clear


def test_summary_messages_have_no_mentions():
    t = '💥 За попередніми даними, станом на 09:00, протиповітряною обороною збито/подавлено 92 ворожі БпЛА\n▪ 5 крилатих ракет "Калібр";'
    assert all(lp.line_kind == "summary" and not lp.mentions for lp in parse_message(t, "kpszsu"))


def test_via_and_heading():
    (lp,) = parse_message("🏍 Реактивний БпЛА на Вінниччині повз Бершадь північно-західним курсом.", "kpszsu")
    (m,) = lp.mentions
    assert (m.rel, m.place_raw, m.heading_deg, m.admin1) == ("via", "Бершадь", 315.0, "UA.23")
    (lp,) = parse_message("Реактивний БпЛА повз Вільнянськ на Запоріжжя", "kudy_letyt")
    assert (lp.mentions[0].place_raw, lp.mentions[0].via_raw) == ("Запоріжжя", "Вільнянськ")


# ---------------------------------------------------------------- gazetteer


def test_normalize_and_key():
    assert normalize("Дубовʼязівку’") == "Дубов'язівку'"
    assert key("  Ові́діополь!") == "овідіополь"
    assert clean_place("м.Миколаїв") == "Миколаїв" and clean_place("Вишгород/Київ!") == "Вишгород"


@pytest.mark.parametrize(
    ("phrase", "oblast", "expected", "match"),
    [
        ("Бровари", "UA.13", "Бровари", "exact"),
        ("Шулявку", "UA.12", "Шулявка", "lemma"),
        ("Дарницю", "UA.12", "Дарниця", "lemma"),
        ("Умані", "UA.01", "Умань", "lemma"),
        ("Білу Церкву", "UA.13", "Біла Церква", "lemma"),
        ("Новгород-Сіверський", "UA.02", "Новгород-Сіверський", "exact"),
        ("Юріївку", "UA.04", "Юр'ївка", "fuzzy"),  # GeoNames spelling Юр'ївка
        ("Славутич", "UA.02", "Славутич", "exact"),  # Kyiv oblast exclave, listed under Чернігівщина
        ("Кременчук", None, "Кременчук", "exact"),  # a big city beats same-name villages
        ("Київ (Оболонь)", None, "Оболонь", "exact"),
        ("Чернігівщину", None, "Чернігівська", "exact"),
    ],
)
def test_gazetteer_resolve(gz, phrase, oblast, expected, match):
    r = gz.resolve(phrase, oblast)
    assert (r.place_norm, r.match) == (expected, match)
    assert r.lat is not None


def test_homonyms_without_oblast_are_ambiguous(gz):
    for phrase in ["Олександрівку", "Березанку"]:
        r = gz.resolve(phrase, None)
        assert r.match == "ambiguous" and r.lat is None and r.candidates > 1


def test_homonym_resolved_by_header(gz):
    a, b = gz.resolve("Березанку", "UA.16"), gz.resolve("Олександрію", "UA.10")
    assert (a.place_norm, a.admin1, b.place_norm) == ("Березанка", "UA.16", "Олександрія")


def test_lemma_forms_cover_cases():
    assert "дарниця" in lemma_forms("Дарницю")
    assert "біла церква" in lemma_forms("Білу Церкву")


def test_context_picks_nearest_homonym(gz):
    r = gz.resolve("Лебедівку", "UA.13")
    assert r.match == "ambiguous" and len(r.options) >= 2
    near = r.options[0]
    picked = dm._by_context(r, [(near.lat + 0.01, near.lon + 0.01)])
    assert (picked.match, picked.lat, picked.lon) == ("context", near.lat, near.lon)
    assert dm._by_context(r, []).match == "ambiguous"


# ---------------------------------------------------------------- versions / known_at (no leakage)


def test_versions_known_at():
    raw = pd.DataFrame(
        [
            # history, edited 20 s after posting -> known at edit time
            {
                "channel": "c",
                "msg_id": 1,
                "posted_at": "2026-09-01T10:00:00+00:00",
                "edited_at": "2026-09-01T10:00:20+00:00",
                "text": "a",
                "received_at": "2026-10-12T09:34:00+00:00",
                "ingest_mode": "backfill",
            },
            # history, edited an hour later -> late edit
            {
                "channel": "c",
                "msg_id": 2,
                "posted_at": "2026-09-01T10:00:00+00:00",
                "edited_at": "2026-09-01T11:00:00+00:00",
                "text": "b",
                "received_at": "2026-10-12T09:34:00+00:00",
                "ingest_mode": "backfill",
            },
            # live with one logged edit
            {
                "channel": "c",
                "msg_id": 3,
                "posted_at": "2026-10-12T10:00:00+00:00",
                "edited_at": "2026-10-12T10:00:30+00:00",
                "text": "orig",
                "received_at": "2026-10-12T10:00:01+00:00",
                "ingest_mode": "live",
            },
        ]
    )
    edits = pd.DataFrame(
        [
            {
                "channel": "c",
                "msg_id": 3,
                "edited_at": "2026-10-12T10:00:30+00:00",
                "old_text": "orig",
                "new_text": "new",
                "received_at": "2026-10-12T10:00:31+00:00",
            }
        ]
    )
    v = {(x.msg_id, x.version): x for x in dm.versions(raw, edits)}
    assert v[(1, 0)].known_at == pd.Timestamp("2026-09-01T10:00:20Z") and not v[(1, 0)].late_edit
    assert v[(2, 0)].late_edit
    assert v[(3, 0)].known_at == pd.Timestamp("2026-10-12T10:00:01Z")
    assert v[(3, 0)].superseded_at == v[(3, 1)].known_at == pd.Timestamp("2026-10-12T10:00:31Z")
    assert (v[(3, 1)].text, v[(3, 1)].observed_at) == ("new", pd.Timestamp("2026-10-12T10:00:30Z"))


# ---------------------------------------------------------------- evaluation


def test_evaluate_counts_tp_fp_fn(gz):
    _, men = dm.build(
        _raw(
            "kudy_letyt",
            [{"msg_id": 1, "text": "Київщина:\nРеактивний БпЛА курсом на Бровари\n2х БпЛА курсом на Фастів"}],
        ),
        EMPTY_EDITS,
        gz,
    )
    gold = [
        {
            "id": "kudy_letyt:1:0:1",
            "mentions": [{"place": "Бровари", "oblast": "Київська", "kind": "drone_jet", "count": 1}],
        },
        {
            "id": "kudy_letyt:1:0:2",
            "mentions": [{"place": "Фастів", "oblast": "Київська", "kind": "drone_jet", "count": 2}],
        },
        {"id": "kudy_letyt:1:0:0", "mentions": [{"place": "Біла Церква", "kind": "drone_jet"}]},
    ]
    table, errors = ev.evaluate(gold, men)
    row = table.set_index(["channel", "field"])
    assert (row.loc[("kudy_letyt", "place"), ["tp", "fp", "fn"]] == [2, 0, 1]).all()
    assert (
        row.loc[("kudy_letyt", "kind"), ["tp", "fp", "fn"]] == [1, 1, 2]
    ).all()  # Фастів: drone vs gold drone_jet
    assert {e["error"] for e in errors} == {"missed", "kind"}
