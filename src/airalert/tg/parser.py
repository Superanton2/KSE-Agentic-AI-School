"""Pure parser for ``air_alert_ua`` message texts.

Checked against 7207 real messages (2026-08-25 … 2026-09-07). Every event message looks like

    <emoji> HH:MM <title>
    <optional body lines>
    #Hashtag_1 #Hashtag_2

and falls into one of:
- air raid:  "🔴 Повітряна тривога в …" / "🟢|🟡 Відбій тривоги в …"
             (🟡 + "тривога ще триває у: …" = this location is clear, sub-areas still alerting)
- threats:   "🔴🔴 Загроза ударних БпЛА в …!", "🟠 УВАГА!!! Загроза застосування КАБів", "🔴 Загроза
             артобстрілу!", … and their ends "🟢|🟡 Відбій загрози …", "🟡 Відбій по КАБам", "🟠 ВІДБІЙ …"
- info:      "🟠 БЕЗКОШТОВНА ЕВАКУАЦІЯ", channel announcements without the "<emoji> HH:MM" header.

The event time is NOT parsed from the text: it is the message's ``posted_at``.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from airalert.tg.locations import Location, lookup

Kind = Literal["start", "end"]

AIR_RAID = "air_raid"
THREAT_UNSPECIFIED = "threat_unspecified"  # an end that does not say which threat it ends
# Order matters: the first match wins ("балістичного озброєння … БпЛА" is ballistic).
THREAT_TYPES: list[tuple[str, re.Pattern]] = [
    ("radiation", re.compile(r"радіаці")),
    ("street_fight", re.compile(r"вуличн\w* бо")),
    ("artillery", re.compile(r"артобстріл|артилер")),
    ("ballistic", re.compile(r"балісти")),
    ("kab", re.compile(r"\bкаб|авіабомб|авіаційн\w* бомб")),
    ("missile", re.compile(r"ракет|бандерол")),
    ("drones", re.compile(r"бпла|дрон|шахед|молнія")),
]
ALERT_TYPES = (AIR_RAID, *(t for t, _ in THREAT_TYPES), "threat_other")

TEST_REGION = "Тестовий Регіон"
_HEADER = re.compile(r"^(?P<emoji>(?:🔴|🟠|🟡|🟢)+)\s*\d{1,2}:\d{2}\s*(?P<title>.*)$")
_INFO = re.compile(r"евакуаці")
_END_WORD = re.compile(r"відбій|вілбій")
_STILL_ACTIVE = "тривога ще триває у"


@dataclass(frozen=True)
class LocationEvent:
    location: Location
    kind: Kind
    alert_type: str = AIR_RAID
    partial: bool = False  # 🟡: this location is clear while listed sub-areas still alert
    soft: bool = False  # level (re)announcement: starting while already active is not an anomaly


@dataclass
class ParseResult:
    events: list[LocationEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # reasons for parse_errors
    ignored: str | None = None  # recognised but intentionally skipped (no text, test region, info)


def _threat_type(text: str) -> str | None:
    for name, rx in THREAT_TYPES:
        if rx.search(text):
            return name
    return None


def classify(lines: list[str]) -> tuple[Kind, str, bool] | str:
    """(kind, alert_type, partial) for an event message, or an ignore/error reason string."""
    m = _HEADER.match(lines[0])
    if not m:
        return "ignored:info"
    emoji, title = m["emoji"], m["title"].lower()
    # Body without the hashtag line and the "still active in" list (it names areas, not threats).
    body = "\n".join(lines[:-1]).lower().split(_STILL_ACTIVE)[0]
    partial = emoji == "🟡"

    if "повітряна тривога" in title:
        return ("start", AIR_RAID, False)
    if "відбій тривоги" in title:
        return ("end", AIR_RAID, partial)

    is_end = emoji in ("🟢", "🟡") or bool(_END_WORD.search(title))
    threat = _threat_type(body)
    if threat is None and _INFO.search(body):
        return "ignored:info"
    if is_end:
        return ("end", threat or THREAT_UNSPECIFIED, partial)
    return ("start", threat or "threat_other", False)


def parse(text: str | None) -> ParseResult:
    if not text or not text.strip():
        return ParseResult(ignored="no_text")
    if TEST_REGION in text:
        return ParseResult(ignored="test_region")

    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    cls = classify(lines)
    if isinstance(cls, str):
        return ParseResult(ignored=cls.split(":", 1)[1])
    kind, alert_type, partial = cls

    tags = [t for t in lines[-1].split() if t.startswith("#")]
    if not tags:
        return ParseResult(errors=["no_hashtags"])

    result = ParseResult()
    for tag in tags:
        loc = lookup(tag)
        if loc is None:
            result.errors.append(f"unknown_hashtag:{tag.lower()}")
        else:
            result.events.append(LocationEvent(loc, kind, alert_type, partial))
    return result
