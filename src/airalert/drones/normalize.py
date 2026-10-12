"""Text normalisation shared by the parser and the gazetteer."""

import re
import unicodedata

# ’ ʼ ` ´ ʹ ′ ‘ -> '
_APOSTROPHES = re.compile("[\\u2019\\u02bc`\\u00b4\\u02b9\\u2032\\u2018]")
# zero-width chars, variation selectors, soft hyphen, combining stress mark (GeoNames "Ові́діополь")
_INVISIBLE = re.compile("[\\u200b-\\u200f\\u2060\\ufe0f\\ufe0e\\u00ad\\u0301]")
_MARKDOWN = re.compile(r"\*\*|__|~~|`")
# Pictographs, dingbats, flags, arrows etc. (kept separately by :func:`emojis` before stripping).
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf\u2190-\u21ff\u2b00-\u2bff\u203c\u2049\u3030\u303d\u2122\u2139\u24c2]"
)
_SPACES = re.compile("[ \t\u00a0\u2009\u202f]+")


def normalize(text: str) -> str:
    """NFC, unified apostrophes, no invisible chars / markdown, single spaces. Keeps emojis and newlines."""
    t = unicodedata.normalize("NFC", text or "")
    t = _APOSTROPHES.sub("'", t)
    t = _INVISIBLE.sub("", t)
    t = _MARKDOWN.sub("", t)
    return "\n".join(_SPACES.sub(" ", line).strip() for line in t.split("\n"))


def emojis(line: str) -> list[str]:
    return _EMOJI.findall(line)


def strip_emoji(line: str) -> str:
    return _SPACES.sub(" ", _EMOJI.sub(" ", line)).strip()


def lines(text: str) -> list[str]:
    """Normalised non-empty lines (emojis kept)."""
    return [ln for ln in normalize(text).split("\n") if ln]


def key(name: str) -> str:
    """Lookup key for place names: lower-case, normalised apostrophes/dashes/spaces, ґ->г, ё->е."""
    t = normalize(name).lower().replace("ґ", "г").replace("ё", "е")
    t = re.sub(r"[‐-―-]+", "-", t)
    t = re.sub(r"\s*-\s*", "-", t)
    return re.sub(r"\s+", " ", t).strip(' .,!?:;"«»()')
