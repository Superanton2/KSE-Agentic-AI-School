"""SITREP Markdown -> current warning status per region/area (pure functions).

Section 3 ("CURRENT WARNING STATUS") has one paragraph per region, e.g.::

    **m. Kyiv (м. Київ)** — air raid alert in effect since 10:27, ongoing for 1 h 39 min. Alert level: yellow (drone level).
    **Kyivska oblast (Київська область)** — air raid alert in effect since 09:53, ongoing for 2 h 13 min.
      6 areas affected: Vyshhorodskyi (Вишгородський), ..., Boryspilskyi (Бориспільський) [yellow (drone level)]. ...
    **Kharkivska oblast (...)** — ... 4 areas affected: red (missile / mass-strike level): Lozivskyi (Лозівський);
      yellow (drone level): Kharkivskyi (Харківський), m. Kharkiv (м. Харків), Kharkivska (Харківська). ...

Levels come either as a trailing ``[level (...)]`` that applies to the areas before it, or as a ``level (...):``
prefix that applies to the areas after it. Times are Europe/Kyiv local; the report date comes from the
``LOCAL TIME`` line. No level => red (as the report's own legend says).
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

KYIV_TZ = ZoneInfo("Europe/Kyiv")
LEVELS = ("red", "yellow")
KYIV_REGIONS = ("м. Київ", "Київська область")

_LOCAL_TIME = re.compile(
    r"^LOCAL TIME .*\((?:Europe/Kyiv, )?(?P<iso>\d{4}-\d{2}-\d{2}T[\d:]+[+-]\d{2}:\d{2})\)", re.M
)
_REGION = re.compile(
    r"^\*\*(?P<en>[^*(]+?) \((?P<uk>[^)]+)\)\*\* — (?P<what>.+?) in effect since "
    r"(?:(?P<mon>[A-Z][a-z]{2}) (?P<day>\d{1,2}), )?(?P<hm>\d{1,2}:\d{2}), ongoing for (?P<dur>[^.]+)\.(?P<rest>.*)$",
    re.M,
)
_CITY_LEVEL = re.compile(r"Alert level: (?P<level>red|yellow)\b")
_AFFECTED = re.compile(r"\d+ areas? affected: (?P<list>.+?)(?:\. The most recent|\.\s*$)")
_TOKEN = re.compile(r"(?P<open>\[)?(?P<en>[^,;:\[\]()]+?) \((?P<uk>[^)]+)\)(?P<colon>:)?")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}


@dataclass(frozen=True)
class AreaStatus:
    region_en: str
    region_uk: str
    area_en: str | None  # None => the region as a whole (e.g. m. Kyiv)
    area_uk: str | None
    warning: str  # "air raid alert", "air raid alert and artillery shelling threat", ...
    level: str  # red | yellow
    started_at: datetime  # UTC (region-level start; the report gives no per-area start)
    elapsed_min: float


def report_time(text: str) -> datetime:
    m = _LOCAL_TIME.search(text)
    if not m:
        raise ValueError("no LOCAL TIME line")
    return datetime.fromisoformat(m["iso"]).astimezone(UTC)


def section(text: str, number: int) -> str:
    m = re.search(rf"^## {number}\. .*?$(?P<body>.*?)(?=^## \d+\. |\Z)", text, re.M | re.S)
    return m["body"].strip() if m else ""


def _start(m: re.Match, now_local: datetime) -> datetime:
    h, mi = map(int, m["hm"].split(":"))
    if m["mon"]:
        month, day = _MONTHS[m["mon"]], int(m["day"])
        year = now_local.year - (1 if month > now_local.month else 0)
        local = datetime(year, month, day, h, mi, tzinfo=KYIV_TZ)
    else:
        local = now_local.replace(hour=h, minute=mi, second=0, microsecond=0)
        if local > now_local:  # defensive: "since 23:58" read just after midnight
            local -= timedelta(days=1)
    return local.astimezone(UTC)


def _areas(rest: str) -> list[tuple[str, str, str]]:
    """[(area_en, area_uk, level)] from the 'N areas affected: ...' clause."""
    m = _AFFECTED.search(rest)
    if not m:
        return []
    out: list[list] = []
    forward: str | None = None
    for t in _TOKEN.finditer(m["list"]):
        en = t["en"].strip()
        if en in LEVELS:
            if t["open"]:  # "[yellow (drone level)]" closes the preceding run
                for a in out:
                    if a[2] is None:
                        a[2] = en
            else:  # "red (...):" opens a run
                forward = en
            continue
        out.append([en, t["uk"], forward])
    return [(en, uk, lvl or "red") for en, uk, lvl in out]


def parse_status(text: str) -> list[AreaStatus]:
    now = report_time(text)
    now_local = now.astimezone(KYIV_TZ)
    out = []
    for m in _REGION.finditer(section(text, 3)):
        started = _start(m, now_local)
        common = dict(
            region_en=m["en"].strip(),
            region_uk=m["uk"],
            warning=m["what"],
            started_at=started,
            elapsed_min=round((now - started).total_seconds() / 60, 1),
        )
        rest = m["rest"]
        areas = _areas(rest)
        if areas:
            out += [AreaStatus(area_en=en, area_uk=uk, level=lvl, **common) for en, uk, lvl in areas]
        else:
            lvl = _CITY_LEVEL.search(rest)
            out.append(AreaStatus(area_en=None, area_uk=None, level=lvl["level"] if lvl else "red", **common))
    return out


def kyiv_status(text: str) -> list[AreaStatus]:
    """m. Kyiv and the raions of Kyivska oblast currently under warning."""
    return [a for a in parse_status(text) if a.region_uk in KYIV_REGIONS]


def threat_log(text: str) -> str:
    """Section 4 (THREAT ACTIVITY) as raw text."""
    return section(text, 4)
