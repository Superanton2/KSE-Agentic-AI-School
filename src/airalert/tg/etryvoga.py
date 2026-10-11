"""Pure parser for the volunteer channel ``UkraineAlarmSignal`` (єТривога).

Checked on real messages 2026-08-25 … 2026-10-11. Two shapes (batch places carry "• " since 09-25):

    single:  "🚨 Київ\\nПовітряна тривога. Прямуйте в укриття!"
    batch:   "🟢 Відбій тривоги\\nКиїв\\nБучанський район (Київська обл.)\\n…"

Since 2026-09-06 the channel announces air raids by danger level instead of 🚨:
    🟡 Жовтий рівень тривоги          -> air raid start
    🔴 Червоний рівень тривоги        -> air raid start + red level start
    🟡 Відбій червоної тривоги …      -> red level end (the yellow air raid continues)
    🟢 Відбій тривоги                 -> air raid end (closes red level too, via the state machine)

Threat notices (🛸 drones, 💣 KAB, 🚀 high-speed targets, 💥 shelling, ⚠️ explosions, 👁️ recon) have no
end messages in this channel, so they are point notices, not intervals: they are counted as ignored
(``threat_notice``) and stay in raw_messages for later feature work.
"""

import re
from functools import lru_cache

from airalert.tg.locations import Location, hashtag_map, to_en, to_hashtag
from airalert.tg.parser import AIR_RAID, LocationEvent, ParseResult

AIR_RAID_RED = "air_raid_red"

_FIRST = re.compile(r"^(?P<emoji>[^\w\s(«\"]+)\s*(?P<rest>.*)$")
_RAION = re.compile(r"^(?P<raion>.+ район) \((?P<oblast>.+) обл\.\)$")
# "Конотоп (Сумська обл.)" or a city district "Київський (Харків, Харківська обл.)"
_IN_OBLAST = re.compile(r"^(?P<place>.+?) \((?:(?P<city>[^,()]+), )?(?P<oblast>[^,()]+) обл\.\)$")
_IN_KYIV = re.compile(r"^(?P<place>.+) \(Київ\)$")
_OBLAST = re.compile(r"^(?P<oblast>.+) обл\.$")
_TRUNCATED = re.compile(r"^…\s*та ще \d+")
THREAT_EMOJI = {"🛸", "💣", "🚀", "💥", "⚠️", "👁️", "👁"}


@lru_cache
def _raions() -> dict[tuple[str, str], Location]:
    """(oblast EN, raion hashtag) -> Location, from the same states.json as air_alert_ua."""
    return {(loc.location, tag): loc for tag, loc in hashtag_map().items() if loc.level == "raion"}


def parse_place(line: str) -> Location | None:
    line = re.sub(r"^[•\-–]\s*", "", line.strip())  # list bullets used since 2026-09-25
    if line == "Київ":
        return Location("Kyiv City", "oblast")
    if m := _IN_KYIV.match(line):  # a Kyiv district/neighbourhood (threat notices only)
        return Location("Kyiv City", "hromada", "", to_en(m["place"]))
    if m := _RAION.match(line):
        oblast = to_en(f"{m['oblast']} область")
        return _raions().get((oblast, to_hashtag(m["raion"])))
    if m := _IN_OBLAST.match(line):
        place = f"{m['place']} ({m['city']})" if m["city"] else m["place"]
        return Location(to_en(f"{m['oblast']} область"), "hromada", "", to_en(place))
    if m := _OBLAST.match(line):
        return Location(to_en(f"{m['oblast']} область"), "oblast")
    return None


def _kinds(emoji: str, title: str) -> list[tuple[str, str]] | str:
    """[(kind, alert_type), …] for the message, or an ignore reason."""
    t = title.lower()
    if emoji == "🚨" and ("повітряна тривога" in t or not t):
        return [("start", AIR_RAID)]
    if emoji == "🟡" and "жовтий рівень" in t:
        return [("start", AIR_RAID)]
    if emoji == "🔴" and "червоний рівень" in t:
        return [("start", AIR_RAID), ("start", AIR_RAID_RED)]
    if emoji == "🟡" and "відбій червоної" in t:
        return [("end", AIR_RAID_RED)]
    if emoji == "🟢" and ("відбій тривоги" in t or "тривога у місті відсутня" in t):
        return [("end", AIR_RAID)]
    if emoji in THREAT_EMOJI or emoji == "🟢":
        return "threat_notice"
    return "info"


def _sections(lines: list[str]) -> list[tuple[str, str, list[str]]]:
    """Split a message into (emoji, title, places) sections.

    A batch message may hold several sections, e.g. "🚨 Повітряна тривога\n<places>\n🟢 Відбій тривоги\n<places>".
    """
    sections: list[tuple[str, str, list[str]]] = []
    for line in lines:
        m = None if _TRUNCATED.match(line) else _FIRST.match(line)
        if m and parse_place(m["rest"]) is None and m["rest"]:
            sections.append((m["emoji"].strip(), m["rest"], []))  # batch header
        elif not sections and m:
            sections.append((m["emoji"].strip(), "", [m["rest"]]))  # single: "<emoji> <place>"
        elif sections and not sections[-1][1] and len(sections[-1][2]) == 1:
            emoji, _, places = sections[-1]
            sections[-1] = (emoji, line, places)  # single: the event line follows the place
        elif sections:
            sections[-1][2].append(line)
    return sections


def parse(text: str | None) -> ParseResult:
    if not text or not text.strip():
        return ParseResult(ignored="no_text")
    if re.search(r"тривога у \d+ район", text):  # hourly/summary counters, not events
        return ParseResult(ignored="info")
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 2 or not _FIRST.match(lines[0]):
        return ParseResult(ignored="info")

    result = ParseResult()
    ignored: list[str] = []
    for emoji, title, places in _sections(lines):
        kinds = _kinds(emoji, title)
        if isinstance(kinds, str):
            ignored.append(kinds)
            continue
        if not places:
            result.errors.append("no_places")
        soft = emoji != "🚨"  # yellow/red level messages re-announce an ongoing air raid
        for line in places:
            if _TRUNCATED.match(line):
                result.errors.append("truncated_place_list")
                continue
            loc = parse_place(line)
            if loc is None:
                result.errors.append(f"unknown_place:{line}")
                continue
            result.events += [LocationEvent(loc, kind, alert_type, soft=soft) for kind, alert_type in kinds]
    if not result.events and not result.errors:
        result.ignored = ignored[0] if ignored else "info"
    return result
