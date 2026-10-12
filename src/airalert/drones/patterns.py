"""All regular expressions of the drone parser, in one table, each with real examples (tests check them).

Lines are matched after :func:`airalert.drones.normalize.normalize` (apostrophes unified, NFC) and with
emojis removed; matching is case-insensitive.
"""

import re
from dataclasses import dataclass, field

_I = re.IGNORECASE


@dataclass(frozen=True)
class Pattern:
    name: str
    regex: re.Pattern
    examples: tuple[str, ...] = field(default=())  # strings that must match (search)
    non_examples: tuple[str, ...] = field(default=())  # strings that must not match


def P(name: str, rx: str, examples=(), non_examples=()) -> Pattern:
    return Pattern(name, re.compile(rx, _I), tuple(examples), tuple(non_examples))


# ---------------------------------------------------------------- target kinds (first match wins)
# Order matters: ballistic before missile ("балістична ракета"), jet before plain drone.
KIND_PATTERNS: list[tuple[str, Pattern]] = [
    (
        "ballistic",
        P(
            "kind_ballistic",
            r"\bбалістик\w*|\bбалістичн\w*|\bіскандер\w*|\bкинджал\w*|\bкн-23\b",
            ["Балістика на Павлоград", "2х Балістики на Павлоград", "Балістична ракета на Київ!"],
        ),
    ),
    (
        "kab",
        P(
            "kind_kab",
            r"\bкаб(?:и|ів|ам|ами|ах)?\b|\bкар/каб\b|керован\w* авіаційн\w* бомб\w*",
            [
                "КАБи на Донеччину",
                "Пуски КАБ на Суми",
                "Пуски керованих авіаційних бомб ворожою тактичною авіацією",
            ],
            ["Кабане"],
        ),
    ),
    (
        "missile",
        P(
            "kind_missile",
            r"\bбандерол\w*|\bгруп\w* кр\b|\bкр\b|\bкрилат\w* ракет\w*|\bракет\w*|\bшвидкісн\w* ціл\w*"
            r"|\bциркон\w*|\bкалібр\w*|\bх-\d+\w*|\bонікс\w*"
            r"|баражуюч\w* боєприпас\w*(?:\s+типу)?(?:\s*\"[^\"]*\")?",
            [
                "Бандероль курсом на Синельникове",
                "2х Бандеролі курсом на Бородянку",
                "Група КР курсом на Снігурівку",
                "Швидкісна ціль на Херсон",
                "Циркон на Сумщині",
                "Ракета на Одесу",
                'Баражуючий боєприпас "Бандероль" на Сумщині',
            ],
        ),
    ),
    (
        "drone_jet",
        P(
            "kind_drone_jet",
            r"\bреактивн\w*",
            [
                "Реактивний БпЛА курсом на Бровари",
                "3х.Реактивні БпЛА курсом на Славутич",
                "Реактивний на Бровари",
            ],
        ),
    ),
    (
        "drone",
        P(
            "kind_drone",
            r"\bбпла\b|\bбпл\b|\bдрон\w*|\bшахед\w*|\bгерань\w*|\bгербер\w*|\bмолні\w*|\bланцет\w*|\bмопед\w*",
            [
                "БпЛА курсом на Суми",
                "Молнія курсом на Петропавлівку",
                "Ланцет курсом на Токарі",
                "Ударні БпЛА на м. Запоріжжя",
            ],
        ),
    ),
]
# kpszsu marks the kind with an emoji; used only when the text names no kind.
EMOJI_KINDS = {"🏍": "drone_jet", "🛵": "drone", "🚀": "missile", "💣": "kab", "✈": "missile"}

# ---------------------------------------------------------------- status lines (no target)
STATUS_PATTERNS: list[tuple[str, Pattern]] = [
    (
        "descending",
        P("st_descending", r"\bзнижу\w*|\bпада[єю]\w*|\bпікіру\w*", ["Увага. Знижується!", "Падає"]),
    ),
    (
        "shot_down",
        P(
            "st_shot_down",
            r"^\s*(?:\d+\s*|один\s+|ще\s+)?мінус\w*|\bзбит\w*|\bподавлен\w*|\bвпав\b|\bвпали\b|\bприземлив\w*",
            ["Мінус", "Один мінус, один Видубичі", "Впав", "ЗБИТО/ПОДАВЛЕНО 98 ВОРОЖИХ БПЛА"],
        ),
    ),
    (
        "all_clear",
        P(
            "st_all_clear",
            r"\bвідбій\b|\bчисто\b|поки все\b|\bбільше не (?:летить|фіксу\w*|загрожу\w*)|\bне фіксу\w*|нічого не летить|\bзагроза минула",
            [
                "Відбій",
                "Біля Києва наразі чисто",
                "Біля Києва поки все",
                "Все, більше не летить",
                "Не фіксується",
                "Відбій загрози застосування балістичного озброєння",
                "Мають дати відбій",
            ],
            ["Краще поки бути в безпечних місцях"],
        ),
    ),
    ("explosions", P("st_explosions", r"\bвибух\w*", ["Вибухи в Києві!", "Вибух"])),
    ("recheck", P("st_recheck", r"\bдорозвідк\w*", ["Дорозвідка по БпЛА", "Київщина - дорозвідка по БпЛА"])),
]

# ---------------------------------------------------------------- structure
HEADER = P(
    "header",
    r"^(?P<region>[А-ЯІЇЄҐ][\w' .-]{2,40}?)\s*(?::|\s-\s|\s—\s)\s*(?P<rest>.*)$",
    [
        "Київщина:",
        "Запорізька область:",
        "Київ: Реактивний БпЛА курсом на Гнідин",
        "Київщина - реактивний БпЛА на Бориспіль.",
    ],
)
COUNT = P(
    "count",
    r"^(?P<count>\d{1,3})\s*[хxX×]\s*\.?\s*",
    ["2х Реактивні БпЛА", "3х.Реактивні БпЛА", "6х Реактивних БпЛА"],
)
COUNT_WORDS = {
    "один": 1,
    "одна": 1,
    "одне": 1,
    "два": 2,
    "дві": 2,
    "три": 3,
    "чотири": 4,
    "п'ять": 5,
    "шість": 6,
    "сім": 7,
    "вісім": 8,
    "дев'ять": 9,
    "десять": 10,
    "ще один": 1,
    "ще одна": 1,
}
COUNT_LEAD = P(
    "count_lead",
    r"^(?:ще\s+)?(?P<count>\d{1,3}|один|одна|два|дві|три|чотири|п'ять|шість|сім|вісім|дев'ять|десять)\b\s*",
    ["2 на Правому", "4 над Києвом", "Ще один на Лівому березі", "один Видубичі", "Ще 2 на Гостомель"],
)
PLURAL = P(
    "plural",
    r"\b(?:реактивні|ударні|бпла\s+групи|групи|група|бандеролі|ракети|балістики|цілі|кр\b)",
    ["Реактивні БпЛА на Чернігівщині", "Група БпЛА на півночі Сумщини"],
)
# Sentence split inside one line (kpszsu): after ! ? or a full stop that ends a word of 3+ letters.
SENTENCE_SPLIT = re.compile(r"(?<=[!?])\s+|(?<=[а-яіїєґ']{3}\.)\s+|(?<=\))\.\s+", _I)

# Clause keywords -> role. Longest alternatives first; "на" last. Groups: (?P<kw>...).
CLAUSE_KEYWORDS: list[tuple[str, str]] = [
    (r"курсом\s+на", "target"),
    (r"курс\s+на", "target"),
    (r"(?:у|в)\s+напрямку(?:\s+на)?", "target"),
    (r"напрямок\s+на", "target"),
    (r"(?:у|в)\s+бік", "target"),
    (r"(?:залітає|летить|прямує|рухається)\s+(?:на|в бік|у бік)", "target"),
    (r"на\s*/\s*повз", "via"),
    (r"(?:південніше|північніше|західніше|східніше)", "via"),
    (r"повз(?:\s+н\.\s?п\.)?", "via"),
    (r"через", "via"),
    (r"(?:у|в)\s+(?:районі|р-ні)\.?", "via"),
    (r"над", "via"),
    (r"вздовж", "via"),
    (r"біля", "via"),
    (r"(?:з|із|зі)\s+боку", "from"),
    (r"(?:з|із|зі)", "from"),
    (r"до", "target"),
    (r"на", "on"),  # target (accusative) or location (locative) — decided by the phrase
]
CLAUSE = re.compile(
    r"(?<![\w'-])(?P<kw>" + "|".join(f"(?:{k})" for k, _ in CLAUSE_KEYWORDS) + r")(?![\w'-])\s*", _I
)
KW_ROLE = [(re.compile(rf"^(?:{k})$", _I), role) for k, role in CLAUSE_KEYWORDS]

# Compass words (as heading or approach side): nominative/inflected forms.
_DIRS = {
    "північ": 0,
    "північн": 0,
    "півноч": 0,
    "північно-східн": 45,
    "північного сход": 45,
    "північний схід": 45,
    "схід": 90,
    "східн": 90,
    "сход": 90,
    "південно-східн": 135,
    "південного сход": 135,
    "південний схід": 135,
    "південь": 180,
    "південн": 180,
    "півдн": 180,
    "південно-західн": 225,
    "південного заход": 225,
    "південний захід": 225,
    "захід": 270,
    "західн": 270,
    "заход": 270,
    "північно-західн": 315,
    "північного заход": 315,
    "північний захід": 315,
}
_DIR_KEYS = sorted(_DIRS, key=len, reverse=True)
DIRECTION = re.compile(
    r"^(?P<dir>" + "|".join(re.escape(k) for k in _DIR_KEYS) + r")\w*(?:\s+(?:напрям\w*|курс\w*))?$", _I
)
# "північно-західним курсом", "курс південний", "у західному напрямку", "на південь", "курсом на південний захід"
HEADING_PHRASE = P(
    "heading",
    r"(?P<a>(?:північно|південно)-(?:західн|східн)\w*|північн\w*|південн\w*|західн\w*|східн\w*)\s+(?:курсом|напрямк\w*|курс)\b"
    r"|\bкурс\w*\s+(?P<b>(?:північно|південно)-(?:західн|східн)\w*|північн\w*|південн\w*|західн\w*|східн\w*)",
    ["північно-західним курсом", "курс південний", "у західному напрямку", "курсом північно-західним"],
)
FROM_SIDE = P(
    "from_side",
    r"\b(?:з|із|зі)\s+(?P<d>(?:північно|південно)-(?:західн|східн)\w*|півноч\w*|півдн\w*|заход\w*|сход\w*|північного\s+\w+|південного\s+\w+)",
    ["з півночі", "із заходу", "з південного сходу", "зі сходу"],
)
# "на півночі Сумщини", "на заході області", "в центрі Києва" -> a place qualifier, not a target
SECTOR = re.compile(
    r"^(?:на|в|у)?\s*(?:півноч\w*|півдн\w*|заход\w*|сход\w*|центр\w*|північн\w*|південн\w*|межі)\s+(?:та\s+\w+\s+)?",
    _I,
)
SECTOR_PREFIX = re.compile(
    r"^(?:півноч\w*|півдн\w*|заход\w*|сход\w*|центр\w*|території|північн\w*\s+\w+|південн\w*\s+\w+|північ|південь|захід|схід)\s+(?:та\s+\w+\s+)?",
    _I,
)
OBLAST_WORD = re.compile(r"^(?:області|область|регіону)$", _I)
# Non-place noise inside a place phrase (cut everything after it).
PLACE_TAIL = re.compile(
    # direction words only in lower case ("Південне", "Західне" are villages)
    r"\s+(?:(?:у|в)\s+(?=(?-i:північн|південн|західн|східн|напрям|бік))|(?-i:(?:північно|південно)-|північн|південн|західн|східн)"
    r"|курс|через нього|тривог|перебувайте|можлив|з\s|із\s|зі\s|ще\s|вже\s|потім\s|далі\s|➡)",
    _I,
)
# Whole messages that are after-action summaries (counts of shot-down weapons), not situation reports.
SUMMARY = P(
    "summary",
    r"за попередніми даними|збито/подавлено|противник атакував|протиповітряною обороною (?:збито|знешкоджено)"
    r"|ситуація станом на|впродовж доби|у ніч на \d+",
    [
        "💥 За попередніми даними, станом на 09:00, протиповітряною обороною збито/подавлено 92 ворожі БпЛА",
        "У ніч на 10 серпня (з 18:00 09 серпня) противник атакував",
        "💀Ситуація станом на 00:00 11.08.2026",
    ],
    ["Реактивний БпЛА курсом на Бровари"],
)
# Lines that are pure noise for the parser (ads, summaries, footers).
NOISE = P(
    "noise",
    r"^(?:📢|🌐|➖)|надіслати новину|^мапа$|ситуація станом|тримаймо небо|разом – до перемоги|^підтримати|донат|^t\.me/|https?://",
    ["📢 Надіслати новину", "Ситуація станом на 17:25", "Тримаймо небо!"],
)

ALL_PATTERNS: list[Pattern] = [
    *(p for _, p in KIND_PATTERNS),
    *(p for _, p in STATUS_PATTERNS),
    HEADER,
    COUNT,
    COUNT_LEAD,
    PLURAL,
    HEADING_PHRASE,
    FROM_SIDE,
    NOISE,
    SUMMARY,
]


def direction_deg(word: str) -> float | None:
    """'південь' / 'західному' / 'північно-західним' -> compass degrees."""
    w = word.lower().strip(" .,!")
    for k in _DIR_KEYS:
        if w.startswith(k):
            return float(_DIRS[k])
    return None
