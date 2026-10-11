"""Pure parser for ``air_alert_ua`` message texts.

DRAFT: rules follow the format documented in the original processor. They must be confirmed on real
messages after the first backfill before this module is considered final.

    🔴 16:29 Повітряна тривога в Донецька область
    #Донецька_область

    🟡 06:22 Відбій тривоги в Дніпропетровська область
    (тривога ще триває у якомусь районі)
    #Дніпропетровська_область

The kind (start/end) comes from the first line, locations from the hashtags on the last line.
The event time is NOT parsed from the text: it is the message's ``posted_at``.
"""

from dataclasses import dataclass, field
from typing import Literal

from airalert.tg.locations import Location, lookup

Kind = Literal["start", "end"]

TEST_REGION = "Тестовий Регіон"


@dataclass(frozen=True)
class LocationEvent:
    location: Location
    kind: Kind
    partial: bool = False  # 🟡: oblast-level end while some raion is still under alert


@dataclass
class ParseResult:
    events: list[LocationEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # reasons for parse_errors
    ignored: str | None = None  # recognised but intentionally skipped (no text, test region)


def detect_kind(first_line: str) -> Kind | None:
    is_start = "Повітряна тривога" in first_line or "🔴" in first_line
    is_end = "Відбій" in first_line or "🟢" in first_line or "🟡" in first_line
    if is_start == is_end:
        return None
    return "start" if is_start else "end"


def parse(text: str | None) -> ParseResult:
    if not text or not text.strip():
        return ParseResult(ignored="no_text")
    if TEST_REGION in text:
        return ParseResult(ignored="test_region")

    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    kind = detect_kind(lines[0])
    if kind is None:
        return ParseResult(errors=["unknown_kind"])

    tags = [t for t in lines[-1].split() if t.startswith("#")]
    if not tags:
        return ParseResult(errors=["no_hashtags"])

    partial = "🟡" in lines[0]
    result = ParseResult()
    for tag in tags:
        loc = lookup(tag)
        if loc is None:
            result.errors.append(f"unknown_hashtag:{tag.lower()}")
        else:
            result.events.append(LocationEvent(loc, kind, partial))
    return result
