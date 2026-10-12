"""Message text -> per-line structure -> raw mentions (no coordinates yet; see ``mentions.py``).

A state machine over lines: an oblast header (``Київщина:``, ``Запорізька область:``, ``Київ:``, also inline
``Київщина: реактивний БпЛА ...`` or ``Київщина - ...``) sets the current oblast for the following lines.
Each line is split into sentences (kpszsu packs several into one line); each sentence is either a status
(all-clear, shot down, descending, ...), a target sentence (kind + clauses ``курсом на X``, ``повз Y``,
``з півночі``...) or — for kyiv_nebo and emoji-marked kpszsu lines — a bare list of places.
"""

import re
from dataclasses import dataclass, field

from airalert.drones import patterns as pt
from airalert.drones.gazetteer import HEADER_CITIES, clean_place, oblast_code
from airalert.drones.normalize import emojis, key, lines, strip_emoji

BARE_PLACE_CHANNELS = {"kyiv_nebo"}
_GLUED_NA = re.compile(r"\bна(?=[А-ЯІЇЄҐ])")
_NA_PLACE = re.compile(r"^\s*На\s+[А-ЯІЇЄҐ][\w'-]*(?:\s+[\w'-]+){0,2}[.!]?\s*$")
BARE_MAX_WORDS = 4


@dataclass
class RawMention:
    kind: str  # drone_jet | drone | missile | ballistic | kab | unknown
    count: int | None
    plural: bool
    rel: str  # target | via | location | bare
    place_raw: str
    via_raw: str | None = None
    heading_deg: float | None = None  # direction of motion, if stated ("північно-західним курсом")
    from_deg: float | None = None  # side it comes from ("з півночі" -> 0)
    admin1: str | None = None  # oblast scope: header, or "на Житомирщині" in the sentence


@dataclass
class LineParse:
    line_no: int
    text: str
    admin1: str | None
    line_kind: str  # header | noise | status:<x> | <target kind> | other
    mentions: list[RawMention] = field(default_factory=list)


def _kind(sent: str, emoji_kind: str | None) -> tuple[str | None, int]:
    """(kind, end offset of the kind phrase) — text kind wins over the emoji."""
    for kind, p in pt.KIND_PATTERNS:
        m = p.regex.search(sent)
        if m:
            end = m.end()
            # "Реактивний БпЛА": swallow the noun after the adjective
            nxt = pt.KIND_PATTERNS[-1][1].regex.match(sent, end + 1) if kind == "drone_jet" else None
            return kind, nxt.end() if nxt else end
    return emoji_kind, 0


def _status(sent: str) -> str | None:
    for st, p in pt.STATUS_PATTERNS:
        if p.regex.search(sent):
            return st
    return None


def _count(sent: str) -> tuple[int | None, str]:
    m = pt.COUNT.regex.match(sent)
    if m:
        return int(m["count"]), sent[m.end() :]
    m = pt.COUNT_LEAD.regex.match(sent)
    if m:
        c = m["count"].lower()
        return (int(c) if c.isdigit() else pt.COUNT_WORDS.get(c)), sent[m.end() :]
    return None, sent


def _clauses(text: str) -> tuple[str, list[tuple[str, str]]]:
    """'повз Вільнянськ на Запоріжжя' -> ('', [('via','Вільнянськ'), ('on','Запоріжжя')])."""
    ms = list(pt.CLAUSE.finditer(text))
    pre = text[: ms[0].start()] if ms else text
    out = []
    for i, m in enumerate(ms):
        phrase = text[m.end() : ms[i + 1].start() if i + 1 < len(ms) else len(text)]
        out.append((pt.KW_ROLES[m.lastgroup], phrase))
    return pre, out


_PRONOUNS = {"нього", "неї", "них", "ним", "нею", "цим", "того", "цього", "там", "туди", "нас", "наш бік"}
_NOT_PLACES = {
    "кордону",
    "кордоном",
    "кордон",
    "моря",
    "морем",
    "країни",
    "країною",
    "траси",
    "трасі",
    "річки",
    "річкою",
}
_CITY_WORDS = {"місто", "міста", "містом", "місті"}
_MEZHI = re.compile(r"^(?:межі|межу|межею)\s+(?P<a>\w+)(?:\s+(?:та|і)\s+\w+)?\s+(?P<o>област\w*)", re.I)
_FROM_PLACE = re.compile(r"^(?:півноч\w*|півдн\w*|заход\w*|сход\w*|північн\w*|південн\w*)\s+від\s+", re.I)


_CONJ_TAIL = re.compile(r"\s+(?:та|і|й|а також)\s*$", re.I)
_LIST_SPLIT = re.compile(r"\s*,\s*|\s+(?:та|і|й)\s+", re.I)


def _trim(phrase: str, city: str | None = None, keep_list: bool = False) -> str:
    """Cut a clause phrase down to a place: drop trailing direction/comment words, resolve 'містом' to
    the header city, '(на) півночі від Дніпра' -> 'Дніпра', 'межі Одеської та ... областей' -> oblast.
    A leading sector ('півночі Сумщини', 'північний схід Харківщини') is kept for the oblast check.
    ``keep_list`` keeps 'Мені, Борзну, Козелець' / 'Полтавою та Кременчуком' for :func:`_split_list`."""
    if not keep_list:
        phrase = phrase.split(",")[0] if "," in phrase and not phrase.strip().startswith(",") else phrase
    sector = pt.SECTOR_PREFIX.match(phrase.strip())
    head, body = (sector.group(0), phrase.strip()[sector.end() :]) if sector else ("", phrase)
    m = pt.PLACE_TAIL.search(" " + body)
    if m:
        body = (" " + body)[: m.start()]
    phrase = (head + body).strip(' .,!?:;-—–"«»/')
    phrase = _CONJ_TAIL.sub("", phrase)
    phrase = _FROM_PLACE.sub("", phrase)
    mz = _MEZHI.match(phrase)
    if mz:
        phrase = f"{mz['a']} області"
    low = phrase.lower()
    if low in _CITY_WORDS:
        return city or ""
    if low in _PRONOUNS or low in _NOT_PLACES or not re.search("[а-яіїєґ]", low):
        return ""
    return phrase


def _split_list(phrase: str) -> list[str]:
    return [p for p in (x.strip(" .,!") for x in _LIST_SPLIT.split(phrase)) if p]


def _is_locative_oblast(phrase: str) -> str | None:
    """'Житомирщині', 'Запоріжжі', 'півночі Сумщини', 'заході області' -> admin1 / '' (current oblast) / None."""
    p = pt.SECTOR_PREFIX.sub("", phrase.strip())
    if pt.OBLAST_WORD.match(p.split(" ")[0] if p else ""):
        return ""
    last = p.split(" ")[-1].lower() if p else ""
    locative = last.endswith(("і", "ї"))
    # "на Запоріжжі" / "на Києві" (locative) is the region even though "Запоріжжя" alone is a city
    code = oblast_code(p, headers=locative)
    if code and (locative or p != phrase.strip()):
        return code
    return None


def _target_sentence(
    sent: str, kind: str, start: int, admin1: str | None, city: str | None = None, multi: bool = False
) -> list[RawMention]:
    """Mentions of one sentence: the main one (first target + last waypoint), plus every further distinct
    target ('на Чернігів та в напрямку Житомира'), every waypoint of a list ('повз Мені, Борзну, Козелець',
    'між Полтавою та Кременчуком') and, for kyiv_nebo (``multi``), comma lists of targets."""
    count, _ = _count(sent)
    plural = bool(pt.PLURAL.regex.search(sent)) or (count or 1) > 1
    pre, clauses = _clauses(sent[start:])
    heading = from_deg = None
    hm = pt.HEADING_PHRASE.regex.search(sent)
    if hm:
        heading = pt.direction_deg(hm["a"] or hm["b"])
    fm = pt.FROM_SIDE.regex.search(sent)
    if fm:
        from_deg = pt.direction_deg(fm["d"].replace("із ", "").replace("з ", ""))
    targets: list[str] = []
    vias: list[str] = []
    scope = admin1
    for role, phrase in clauses:
        listy = role in ("via", "between") or (multi and role in ("target", "on"))
        ph = _trim(phrase, city, keep_list=listy)
        if not ph:
            continue
        # compass words are lower-case; "Південне", "Західне" are villages
        d = pt.direction_deg(ph) if ph[:1].islower() and pt.DIRECTION.match(ph) else None
        if role in ("target", "on") and d is not None:
            heading = heading if heading is not None else d
            continue
        if role == "from":
            continue  # approach side handled by FROM_SIDE; "з Брянщини"/"з Чорного моря" carry no target
        if role == "on":
            loc = _is_locative_oblast(ph)
            if loc is not None:
                scope = loc or scope
                continue
            role = "target"
        if role == "target":
            loc = _is_locative_oblast(ph)  # "в напрямку Одещини" is a target oblast, keep as target
            if loc == "":
                continue
            parts = _split_list(ph) if listy else [ph]
            targets += [p for p in parts if p not in targets and (p == parts[0] or _looks_like_place(p))]
        else:  # via / between
            vias += [p for p in _split_list(ph) if p not in vias]
    if not targets and not vias:
        rest = _trim(pre)
        if rest and len(rest.split()) <= BARE_MAX_WORDS and rest[:1].isupper():
            targets = [rest]  # "Реактивний БпЛА Біла Церква" (rare) -> treat as target
        elif scope and scope != admin1:  # only an oblast: "БпЛА на Сумщині"
            return [RawMention(kind, count, plural, "location", f"@{scope}", None, heading, from_deg, scope)]
        else:
            return []
    if len(targets) > 1:  # "на Чернігівщину в напрямку Сновська": the settlement makes the oblast redundant
        settlements = [t for t in targets if _is_locative_oblast(t) is None and oblast_code(t) is None]
        targets = settlements or targets
    if targets:
        main = RawMention(
            kind, count, plural, "target", targets[0], vias[-1] if vias else None, heading, from_deg, scope
        )
        extra = [
            RawMention(kind, count, plural, "target", t, None, None, from_deg, scope) for t in targets[1:]
        ]
        extra += [RawMention(kind, count, plural, "via", v, None, None, None, scope) for v in vias[:-1]]
    else:
        main = RawMention(kind, count, plural, "via", vias[-1], None, heading, from_deg, scope)
        extra = [RawMention(kind, count, plural, "via", v, None, None, None, scope) for v in vias[:-1]]
    return [main, *extra]


# Capitalised words in kyiv_nebo that are not places (sentence starts, verbs, slang).
_BARE_STOP = {
    "все",
    "всі",
    "увага",
    "попередньо",
    "схоже",
    "можливо",
    "напевно",
    "наче",
    "також",
    "і",
    "й",
    "та",
    "а",
    "наступний",
    "наступні",
    "ще",
    "знову",
    "очікуємо",
    "кружляє",
    "кружляють",
    "залишився",
    "залишились",
    "летить",
    "летять",
    "один",
    "одна",
    "два",
    "дві",
    "тушки",
    "тривога",
    "загроза",
    "дорозвідка",
    "мінус",
    "плюс",
    "так",
    "ні",
    "поки",
    "наразі",
    "чекаємо",
    "обережно",
}
_VERB_END = re.compile(r"(?:ться|ється|ються|ся|ють|ує|ює|ить|ать|ять|ли|ло|ла)$", re.I)
_CONNECTORS = {"масив", "траса", "острів", "берег", "березі", "поле", "гора", "сади", "яр", "заспа", "ліс"}


def _looks_like_place(ph: str) -> bool:
    words = ph.split()
    if not words or len(words) > BARE_MAX_WORDS or words[0].lower() in _BARE_STOP:
        return False
    if pt.DIRECTION.match(ph) or (
        len(words) == 1 and _VERB_END.search(words[0]) and words[0].lower()[-2:] != "ли"
    ):
        return False
    return all(w[:1].isupper() or w.lower() in _CONNECTORS or w[:1].isdigit() or "-" in w for w in words)


def _bare_places(sent: str, kind: str, admin1: str | None, city: str | None = None) -> list[RawMention]:
    """kyiv_nebo 'Васильків, Глеваха' / '2 на Правому' / kpszsu '🏍 Борщагівка! Виноградар!'."""
    out = []
    sent = re.split(r"\s+[-—–]\s+", sent)[0]  # "Правий берег - уважно"
    for seg in [s for s in sent.replace(";", ",").split(",") if s.strip()]:
        st = _status(seg)
        if st and st not in ("shot_down", "descending"):
            continue
        if st:  # "Вишгород мінус": the status word goes, the place stays
            seg = next(p for s_, p in pt.STATUS_PATTERNS if s_ == st).regex.sub(" ", seg).strip()
            if not seg:
                continue
        count, rest = _count(seg.strip())
        pre, clauses = _clauses(rest)
        phrases = [p for r, p in clauses if r in ("on", "target", "via")] or [pre]
        for ph in phrases:
            ph = _trim(ph, city)
            if ph and _looks_like_place(ph[:1].upper() + ph[1:] if ph in (city or "",) else ph):
                out.append(RawMention(kind, count, (count or 1) > 1, "bare", ph, admin1=admin1))
    return out


def _header(line: str, is_last: bool) -> tuple[str | None, str | None, str]:
    """(admin1 or None, header city or None, rest of line) if the line starts with an oblast header.
    A city used as a header ('Київ:', 'Луцьк:') also gives the city meant by 'над містом'."""
    m = pt.HEADER.regex.match(line)
    region, rest = (m["region"].split(" та ")[0].split(",")[0], m["rest"]) if m else (None, line)
    if region is None and not is_last:
        bare = line.strip(" !.:")
        if bare and len(bare.split()) <= 3:  # "⚠ Київ" followed by more lines
            region, rest = bare, ""
    if region:
        code = oblast_code(region, headers=True)
        if code:
            city = region.strip() if key(region) in HEADER_CITIES else None
            return code, city, rest
    return None, None, line


def parse_message(text: str, channel: str) -> list[LineParse]:
    out: list[LineParse] = []
    admin1: str | None = None
    city: str | None = None
    msg_emoji_kind: str | None = None  # kpszsu: "🏍 Київ:" then "Дарниця" / "На Боярку" on the next lines
    ls = lines(text)
    if pt.SUMMARY.regex.search(text or ""):
        return [LineParse(i, raw, None, "summary") for i, raw in enumerate(ls)]
    for i, raw in enumerate(ls):
        em = emojis(raw)
        emoji_kind = next((pt.EMOJI_KINDS[e] for e in em if e in pt.EMOJI_KINDS), None)
        msg_emoji_kind = emoji_kind or msg_emoji_kind
        line = strip_emoji(raw).lstrip("+• ").strip()
        line = _GLUED_NA.sub("на ", line)  # "наЗапоріжжі"
        if pt.NOISE.regex.search(raw) or not line:
            out.append(LineParse(i, raw, admin1, "noise"))
            continue
        code, hcity, rest = _header(line, is_last=i == len(ls) - 1)
        if code:
            admin1, city = code, hcity
            if not rest.strip():
                out.append(LineParse(i, raw, admin1, "header"))
                continue
            line = rest
        lp = LineParse(i, raw, admin1, "other")
        for sent in [s for s in pt.SENTENCE_SPLIT.split(line) if s.strip()]:
            kind, start = _kind(sent, emoji_kind)
            st = _status(sent)
            m = None
            if kind and (pt.CLAUSE.search(sent, start) or start > 0):
                ms = _target_sentence(sent, kind, start, admin1, city, multi=channel in BARE_PLACE_CHANNELS)
                m = ms[0] if ms else None
            if m:
                lp.mentions += ms
                lp.line_kind = (
                    m.kind
                    if lp.line_kind in ("other",) or lp.line_kind.startswith("status")
                    else lp.line_kind
                )
                continue
            bare_ok = (
                channel in BARE_PLACE_CHANNELS
                or (msg_emoji_kind is not None and start == 0)
                or (channel == "kpszsu" and _NA_PLACE.match(sent) is not None)  # "На Бабинці." (no emoji)
            )
            if bare_ok and len(sent.split()) <= 12:
                ms = _bare_places(sent, kind or msg_emoji_kind or "unknown", admin1, city)
                if ms:
                    lp.mentions += ms
                    if lp.line_kind == "other":
                        lp.line_kind = ms[0].kind
                    if st and lp.line_kind == "other":
                        lp.line_kind = f"status:{st}"
                    continue
            if st and (lp.line_kind == "other"):
                lp.line_kind = f"status:{st}"
            elif kind and lp.line_kind == "other":
                lp.line_kind = kind
        out.append(lp)
    return out


def place_phrase(raw: str) -> str:
    return clean_place(raw)
