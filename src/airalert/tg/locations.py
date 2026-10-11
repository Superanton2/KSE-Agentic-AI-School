"""Hashtag -> location map for ``air_alert_ua`` messages.

Ported from Vadimkin/ukrainian-air-raid-sirens-dataset (MIT, see LICENSES/vadimkin-MIT.txt):
``processors/official_channel_processor.py::load_states`` and ``processors/legacy_states.py``.
Names are transliterated exactly like the dataset's ``*_en.csv`` (translitua + "Kyiv City").
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from translitua import translit

_RAION_RENAMES = {
    ("Дніпропетровська область", "Новомосковський район"): "Самарівський район",
    ("Житомирська область", "Новоград-Волинський район"): "Звягельський район",
}
_COMMUNITY_RENAMES = {
    (
        "Сумська область",
        "Сумський район",
        "Миколаївська сільська територіальна громада",
    ): "Миколаївська територіальна громада",
}
# Hromadas with duplicated names: the author pins them to the one where sirens were actually used.
_HROMADA_PINNED = {
    "Широківська територіальна громада": ("Баштанський район", "Миколаївська область"),
    "Воскресенська територіальна громада": ("Миколаївський район", "Миколаївська область"),
    "Софіївська територіальна громада": ("Баштанський район", "Миколаївська область"),
    "Костянтинівська територіальна громада": ("Миколаївський район", "Миколаївська область"),
    "Привільненська територіальна громада": ("Баштанський район", "Миколаївська область"),
    "Горохівська територіальна громада": ("Баштанський район", "Миколаївська область"),
    "Гребінківська територіальна громада": ("Лубенський район", "Полтавська область"),
    "Покровська територіальна громада": ("Покровський район", "Донецька область"),
    "Лиманська територіальна громада": ("Краматорський район", "Донецька область"),
    "Олександрівська територіальна громада": ("Вознесенський район", "Миколаївська область"),
    "Золочівська територіальна громада": ("Богодухівський район", "Харківська область"),
    "Українська територіальна громада": ("Обухівський район", "Київська область"),
}
# Hashtags seen in the channel that do not follow the naming rule.
HASHTAG_ALIASES = {
    "#херсон": "#м_херсон_та_херсонська_територіальна_громада",  # https://t.me/air_alert_ua/5538
}
_EN_SPECIAL = {"м. Київ": "Kyiv City", "Київ": "Kyiv City"}


@dataclass(frozen=True)
class Location:
    """Location in dataset (English) naming. ``location`` is the oblast-level name."""

    location: str
    level: str
    raion: str = ""
    hromada: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.location, self.level, self.raion, self.hromada)


def to_en(name: str) -> str:
    return "" if not name else _EN_SPECIAL.get(name, translit(name))


def to_hashtag(name: str) -> str:
    """'Запорізька область' -> '#запорізька_область'; 'м. Київ' -> '#м_київ'."""
    tag = name.lower().replace("-", "").replace(" ", "_").replace(".", "").replace("'", "").replace("’", "")
    return f"#{tag}"


def _loc(oblast: str, raion: str, hromada: str, level: str) -> Location:
    return Location(to_en(oblast), level, to_en(raion), to_en(hromada))


@lru_cache
def hashtag_map() -> dict[str, Location]:
    raw = json.loads(resources.files("airalert.tg").joinpath("data/states.json").read_text("utf-8"))
    out: dict[str, Location] = {}
    for state in raw["states"]:
        oblast = state["stateName"]
        out[to_hashtag(oblast)] = _loc(oblast, "", "", "oblast")
        for district in state["districts"]:
            raion = district["districtName"]
            new_raion = _RAION_RENAMES.get((oblast, raion))
            out[to_hashtag(raion)] = _loc(oblast, new_raion or raion, "", "raion")
            if new_raion:
                out[to_hashtag(new_raion)] = _loc(oblast, new_raion, "", "raion")
            for community in district["communities"]:
                hromada = community["communityName"]
                if hromada in _HROMADA_PINNED:
                    pinned_raion, pinned_oblast = _HROMADA_PINNED[hromada]
                    out[to_hashtag(hromada)] = _loc(pinned_oblast, pinned_raion, hromada, "hromada")
                    continue
                new_hromada = _COMMUNITY_RENAMES.get((oblast, new_raion or raion, hromada)) or (
                    _COMMUNITY_RENAMES.get((oblast, raion, hromada))
                )
                # Same quirk as the author: the original-name tag keeps the old raion name.
                out[to_hashtag(hromada)] = _loc(oblast, raion, new_hromada or hromada, "hromada")
                if new_hromada:
                    out[to_hashtag(new_hromada)] = _loc(oblast, new_raion or raion, new_hromada, "hromada")
    for alias, target in HASHTAG_ALIASES.items():
        out[alias] = out[target]
    return out


def lookup(hashtag: str) -> Location | None:
    return hashtag_map().get(hashtag.lower())
