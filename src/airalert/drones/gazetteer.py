"""Place names -> coordinates.

Sources (both in the repo, see ``LICENSES/geonames-CC-BY-4.0.txt``):
- ``data/gazetteer/ua_places.csv.gz`` — GeoNames ``UA`` populated places (feature class P) with their Ukrainian
  names (``alternatenames/UA``: ``uk``, including historic names, e.g. pre-2016/2024 renames), built by
  ``airalert drones-gazetteer``;
- ``data/gazetteer/kyiv_local.csv`` — hand-curated Kyiv districts/neighbourhoods/landmarks (seeded from
  GeoNames ``Kyiv City`` sections, plus what GeoNames lacks: Видубичі, Гідропарк, banks, reservoir...).

Resolution of a raw place phrase within an oblast context (from the message header):
1. clean (``(Одещина)`` -> oblast hint, punctuation, ``Вишгород/Київ`` -> first);
2. exact key match -> ``exact``;
3. pymorphy3 (uk) inflection of each word to the nominative -> ``lemma``; fallback: suffix rules;
4. rapidfuzz ratio >= 92, **only within the oblast** -> ``fuzzy``;
5. several candidates left and no way to tell -> ``ambiguous`` (no coordinates); nothing -> ``none``.
Oblast names as targets ("на Чернігівщину") resolve to the oblast centroid (``place_type='oblast'``).
"""

import csv
import gzip
import io
import math
import re
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path

from airalert.drones.normalize import key, normalize

KYIV_LAT, KYIV_LON = 50.4501, 30.5234
KYIV_CITY, KYIV_OBLAST = "UA.12", "UA.13"
KYIV_AREA_KM = 60  # header "Київ:" also covers villages next to the city (Гнідин, Чабани, ...)
GEONAMES_URLS = {
    "places": "https://download.geonames.org/export/dump/UA.zip",
    "alt": "https://download.geonames.org/export/dump/alternatenames/UA.zip",
}
FUZZY_MIN = 92
NEIGHBOUR_KM = 200  # out-of-oblast fallback radius around the header oblast's centroid
_CYRILLIC = re.compile("[А-Яа-яІіЇїЄєҐґ]")
_UK_LETTERS = re.compile("[ІіЇїЄєҐґ']")

# admin1 code -> (canonical name, aliases as written in headers / targets; inflected forms come from pymorphy)
OBLASTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "UA.01": ("Черкаська", ("Черкащина", "Черкаська область", "Черкаська")),
    "UA.02": ("Чернігівська", ("Чернігівщина", "Чернігівська область", "Чернігівська")),
    "UA.03": ("Чернівецька", ("Чернівеччина", "Буковина", "Чернівецька область", "Чернівецька")),
    "UA.04": (
        "Дніпропетровська",
        ("Дніпропетровщина", "Дніпропетровська область", "Дніпропетровська", "Січеславщина"),
    ),
    "UA.05": ("Донецька", ("Донеччина", "Донецька область", "Донецька")),
    "UA.06": (
        "Івано-Франківська",
        (
            "Івано-Франківщина",
            "Франківщина",
            "Прикарпаття",
            "Івано-Франківська область",
            "Івано-Франківська",
            "Івано-Франківськ",
        ),
    ),
    "UA.07": ("Харківська", ("Харківщина", "Харківська область", "Харківська")),
    "UA.08": ("Херсонська", ("Херсонщина", "Херсонська область", "Херсонська")),
    "UA.09": (
        "Хмельницька",
        ("Хмельниччина", "Хмельничина", "Хмельницька область", "Хмельницька", "Хмельницький"),
    ),
    "UA.10": (
        "Кіровоградська",
        ("Кіровоградщина", "Кіровоградищина", "Кропивниччина", "Кіровоградська область", "Кіровоградська"),
    ),
    "UA.11": ("Крим", ("Крим", "АР Крим")),
    "UA.12": ("м. Київ", ("Київ", "м. Київ", "місто Київ")),
    "UA.13": ("Київська", ("Київщина", "Київська область", "Київська")),
    "UA.14": ("Луганська", ("Луганщина", "Луганська область", "Луганська")),
    "UA.15": ("Львівська", ("Львівщина", "Львівська область", "Львівська")),
    "UA.16": ("Миколаївська", ("Миколаївщина", "Миколаївська область", "Миколаївська")),
    "UA.17": ("Одеська", ("Одещина", "Одеська область", "Одеська")),
    "UA.18": ("Полтавська", ("Полтавщина", "Полтавська область", "Полтавська")),
    "UA.19": ("Рівненська", ("Рівненщина", "Рівненська область", "Рівненська")),
    "UA.21": ("Сумська", ("Сумщина", "Сумська область", "Сумська")),
    "UA.22": ("Тернопільська", ("Тернопільщина", "Тернопільська область", "Тернопільська")),
    "UA.23": ("Вінницька", ("Вінниччина", "Вінничина", "Вінницька область", "Вінницька")),
    "UA.24": ("Волинська", ("Волинь", "Волинська область", "Волинська", "Луцьк")),
    "UA.25": ("Закарпатська", ("Закарпаття", "Закарпатська область", "Закарпатська")),
    "UA.26": ("Запорізька", ("Запоріжжя", "Запорізька область", "Запорізька", "Запоріжчина")),
    "UA.27": ("Житомирська", ("Житомирщина", "Житомирська область", "Житомирська")),
}
FOREIGN = {
    "білорусь": "BY",
    "росія": "RU",
    "рф": "RU",
    "брянщина": "RU",
    "курщина": "RU",
    "бєлгородщина": "RU",
    "молдова": "MD",
    "придністров'я": "MD",
    "акваторія чорного моря": "SEA",
    "чорне море": "SEA",
    "акваторія азовського моря": "SEA",
    "азовське море": "SEA",
}
# Cities used as headers ("Львів:", "⚠ Одеса") -> their oblast; as targets they are cities.
CITY_HEADERS = {
    "Київ": "UA.12",
    "м. Київ": "UA.12",
    "місто Київ": "UA.12",
    "Івано-Франківськ": "UA.06",
    "Хмельницький": "UA.09",
    "Луцьк": "UA.24",
    "Запоріжжя": "UA.26",
    "Львів": "UA.15",
    "Житомир": "UA.27",
    "Павлоград": "UA.04",
    "Дніпро": "UA.04",
    "Кривий Ріг": "UA.04",
    "Одеса": "UA.17",
    "Харків": "UA.07",
    "Суми": "UA.21",
    "Чернігів": "UA.02",
    "Полтава": "UA.18",
    "Кременчук": "UA.18",
    "Черкаси": "UA.01",
    "Вінниця": "UA.23",
    "Рівне": "UA.19",
    "Тернопіль": "UA.22",
    "Ужгород": "UA.25",
    "Чернівці": "UA.03",
    "Миколаїв": "UA.16",
    "Херсон": "UA.08",
    "Кропивницький": "UA.10",
    "Біла Церква": "UA.13",
    "Бровари": "UA.13",
    "Бориспіль": "UA.13",
}
# Alias keys that are *headers only* (a city used as a header names its oblast, but as a target it is a city).
HEADER_CITIES = {key(c) for c in CITY_HEADERS}
_HEADER_ONLY = HEADER_CITIES


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float
    admin1: str  # GeoNames admin1 code ("UA.13"); "" for foreign / unknown
    kind: str  # settlement | kyiv_local | oblast
    population: int = 0
    fcode: str = ""


@dataclass(frozen=True)
class Resolved:
    place_norm: str | None
    lat: float | None
    lon: float | None
    admin1: str | None
    match: str  # exact | lemma | fuzzy | ambiguous | none
    place_type: str | None = None  # settlement | kyiv_local | oblast
    candidates: int = 0
    options: tuple = ()  # for "ambiguous": the same-name places in scope (context disambiguation)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


_OBLAST_ALIAS = {
    key(a): code for code, (_, aliases) in OBLASTS.items() for a in aliases if key(a) not in HEADER_CITIES
}
_CITY_HEADER_KEYS = {key(c): code for c, code in CITY_HEADERS.items()}


def oblast_code(phrase: str, headers: bool = False) -> str | None:
    """Oblast alias (any case form) -> admin1 / 'BY' / 'RU' / 'MD' / 'SEA'. ``headers=True`` also accepts city
    headers ('Київ:', 'Львів:') that name an oblast only when used as a header."""
    if headers and key(phrase) in _CITY_HEADER_KEYS:
        return _CITY_HEADER_KEYS[key(phrase)]
    if key(phrase) in FOREIGN:
        return FOREIGN[key(phrase)]
    for form in word_forms(phrase):
        if not headers and form in _HEADER_ONLY:
            continue
        code = _OBLAST_ALIAS.get(form) or FOREIGN.get(form)
        if code:
            return code
    return None


# ---------------------------------------------------------------- building the GeoNames extract


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "airalert gazetteer build"})
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    return dest


def _read_zip_member(path: Path, member: str) -> io.TextIOWrapper:
    z = zipfile.ZipFile(path)
    return io.TextIOWrapper(z.open(member), encoding="utf-8")


def build_places(raw_dir: Path, out_dir: Path) -> tuple[Path, int]:
    """Download GeoNames UA dumps into ``raw_dir`` and write ``out_dir/ua_places.csv.gz`` +
    ``out_dir/oblast_centroids.csv``."""
    places_zip = _download(GEONAMES_URLS["places"], raw_dir / "UA.zip")
    alt_zip = _download(GEONAMES_URLS["alt"], raw_dir / "alternatenames_UA.zip")
    uk: dict[str, list[tuple[int, str]]] = defaultdict(list)  # geonameid -> [(rank, name)]
    for row in csv.reader(_read_zip_member(alt_zip, "UA.txt"), delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(row) > 3 and row[2] == "uk" and _CYRILLIC.search(row[3]):
            preferred, colloquial, historic = (len(row) > i and row[i] == "1" for i in (4, 6, 7))
            rank = 0 if preferred else 2 if historic else 3 if colloquial else 1
            uk[row[1]].append((rank, normalize(row[3])))
    rows, centroids = [], []
    for r in csv.reader(_read_zip_member(places_zip, "UA.txt"), delimiter="\t", quoting=csv.QUOTE_NONE):
        gid, fclass, fcode, admin1 = r[0], r[6], r[7], r[10]
        if fclass == "A" and fcode == "ADM1":
            centroids.append((f"UA.{admin1}", float(r[4]), float(r[5])))
        if fclass != "P":
            continue
        # Untagged Cyrillic alternate names (Ukrainian and Russian forms mixed) — lower priority than "uk";
        # ~5.9k places have no "uk" names at all (e.g. Юр'ївка, Dnipropetrovsk oblast).
        generic = [normalize(n) for n in r[3].split(",") if _CYRILLIC.search(n)]
        generic.sort(key=lambda n: not _UK_LETTERS.search(n))  # Ukrainian-looking forms first
        names = [n for _, n in sorted(set(uk.get(gid, [])))] + generic
        names = list(dict.fromkeys(names))
        if not names:
            continue
        rows.append([gid, names[0], "|".join(names[1:]), r[4], r[5], f"UA.{admin1}", fcode, r[14] or "0"])
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "ua_places.csv.gz"
    with gzip.open(out, "wt", encoding="utf-8", newline="", compresslevel=9) as f:
        w = csv.writer(f)
        w.writerow(["geonameid", "name", "alt_names", "lat", "lon", "admin1", "fcode", "population"])
        w.writerows(sorted(rows, key=lambda x: int(x[0])))
    with open(out_dir / "oblast_centroids.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["admin1", "name", "lat", "lon"])
        for a1, lat, lon in sorted(centroids):
            if a1 in OBLASTS:
                w.writerow([a1, OBLASTS[a1][0], f"{lat:.5f}", f"{lon:.5f}"])
    return out, len(rows)


# ---------------------------------------------------------------- lookup


_FCODE_RANK = {
    "PPLC": 0,
    "PPLA": 1,
    "PPLA2": 2,
    "PPLA3": 3,
    "PPL": 4,
    "PPLX": 5,
    "PPLL": 6,
    "PPLH": 9,
    "PPLQ": 9,
}


class Gazetteer:
    def __init__(
        self, places: list[tuple[Place, list[str]]], oblast_centroids: dict[str, tuple[float, float]]
    ):
        # Current names and alternative/historic names are separate: "Олександрівка" must not hit Donetsk
        # (its 19th-century name) while real Oleksandrivkas exist.
        self.index: dict[str, list[Place]] = defaultdict(list)
        self.alt_index: dict[str, list[Place]] = defaultdict(list)
        self.kyiv_local: dict[str, list[Place]] = defaultdict(list)
        for p, names in places:
            for i, n in enumerate(names):
                k = key(n)
                target = (
                    self.kyiv_local if p.kind == "kyiv_local" else self.index if i == 0 else self.alt_index
                )
                if k and p not in target[k]:
                    target[k].append(p)
        # Spelling-insensitive key ("Юріївка" ~ "Юр'ївка"): consulted after exact/lemma forms.
        self.loose_index: dict[str, list[Place]] = defaultdict(list)
        for idx in (self.index, self.alt_index):
            for k, ps in idx.items():
                for p in ps:
                    if p not in self.loose_index[loose_key(k)]:
                        self.loose_index[loose_key(k)].append(p)
        self.by_oblast: dict[str, dict[str, list[Place]]] = defaultdict(dict)
        for k, ps in self.index.items():
            for p in ps:
                self.by_oblast[p.admin1].setdefault(k, []).append(p)
        self.oblast_centroids = oblast_centroids

    @classmethod
    def load(cls, gazetteer_dir: Path) -> "Gazetteer":
        places = []
        with gzip.open(gazetteer_dir / "ua_places.csv.gz", "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                p = Place(
                    r["name"],
                    float(r["lat"]),
                    float(r["lon"]),
                    r["admin1"],
                    "settlement",
                    int(r["population"]),
                    r["fcode"],
                )
                places.append((p, [r["name"], *filter(None, r["alt_names"].split("|"))]))
        with open(gazetteer_dir / "kyiv_local.csv", encoding="utf-8") as f:
            for r in csv.DictReader(row for row in f if not row.startswith("#")):
                p = Place(
                    r["name"], float(r["lat"]), float(r["lon"]), r["admin1"], "kyiv_local", 0, r["kind"]
                )
                places.append((p, [r["name"], *filter(None, r["alt_names"].split("|"))]))
        centroids = {}
        with open(gazetteer_dir / "oblast_centroids.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                centroids[r["admin1"]] = (float(r["lat"]), float(r["lon"]))
        return cls(places, centroids)

    # ------------------------------------------------------------ oblasts

    def oblast_of_header(self, header: str) -> str | None:
        """Header text ('Київщина', 'Запорізька область', 'Київ', 'Білорусь') -> admin1 code / 'BY' / None."""
        k = key(header)
        return FOREIGN.get(k) or _OBLAST_ALIAS.get(k)

    def oblast_as_target(self, phrase: str) -> str | None:
        """'Чернігівщину' / 'Сумщині' / 'Київщини' -> admin1 (headers-only aliases such as 'Київ' excluded)."""
        return oblast_code(phrase)

    def centroid(self, admin1: str) -> tuple[float, float] | None:
        return self.oblast_centroids.get(admin1)

    # ------------------------------------------------------------ places

    def _in_scope(self, places: list[Place], admin1: str | None) -> list[Place]:
        if admin1 is None:
            return places
        if admin1 == KYIV_CITY:  # "Київ:" header: the city and its immediate surroundings
            return [
                p
                for p in places
                if p.admin1 in (KYIV_CITY, KYIV_OBLAST)
                and haversine_km(p.lat, p.lon, KYIV_LAT, KYIV_LON) <= KYIV_AREA_KM
            ]
        return [p for p in places if p.admin1 == admin1]

    def _pick(self, cands: list[Place], scoped: bool = True) -> Place | None:
        """One place among same-name candidates, or None if genuinely ambiguous. Without an oblast scope
        only an unambiguous candidate (or duplicates within 5 km) is accepted."""
        uniq = list({(p.name, round(p.lat, 2), round(p.lon, 2)): p for p in cands}.values())
        if len(uniq) == 1:
            return uniq[0]
        first = uniq[0]
        if max(haversine_km(first.lat, first.lon, p.lat, p.lon) for p in uniq) <= 5:  # duplicated entries
            return first
        if not scoped:  # a big city among same-name villages: "на Кременчук", "Запоріжжя"
            big = sorted(uniq, key=lambda p: -p.population)
            if big[0].population >= 20_000 and big[0].population >= 20 * max(big[1].population, 1):
                return big[0]
            return None
        ranked = sorted(uniq, key=lambda p: (_FCODE_RANK.get(p.fcode, 8), -p.population))
        a, b = ranked[0], ranked[1]
        if (_FCODE_RANK.get(a.fcode, 8), -a.population) < (_FCODE_RANK.get(b.fcode, 8), -b.population) and (
            _FCODE_RANK.get(a.fcode, 8) <= 3 or a.population >= 5 * max(b.population, 1)
        ):
            return a
        return None

    def _lookup(self, k: str, admin1: str | None) -> list[Place]:
        """Candidates for an exact key: Kyiv-local names (Kyiv scope or unknown), current names in scope,
        alternative/historic names in scope, then — out of scope — a unique major city (PPLC/PPLA), so that
        "Київщина: ... курсом на Київ" resolves."""
        if admin1 in (KYIV_CITY, KYIV_OBLAST, None):
            local = self.kyiv_local.get(k, [])
            if local and (admin1 == KYIV_CITY or not self.index.get(k)):
                return local
        for idx in (self.index, self.alt_index):
            cands = self._in_scope(idx.get(k, []), admin1)
            if cands:
                return cands
        if admin1 is not None:
            major = [p for p in self.index.get(k, []) if p.fcode in ("PPLC", "PPLA")]
            if len(major) == 1:
                return major
        return []

    def resolve(self, phrase: str, admin1: str | None) -> Resolved:
        raw = clean_place(phrase)
        if not raw:
            return Resolved(None, None, None, None, "none")
        hint = inline_oblast(phrase, self)
        if hint:
            admin1 = hint
        if admin1 in ("BY", "RU", "MD", "SEA"):
            return Resolved(raw, None, None, admin1, "none", None)
        code = self.oblast_as_target(raw)
        if code and code in self.oblast_centroids:
            lat, lon = self.oblast_centroids[code]
            return Resolved(OBLASTS[code][0], lat, lon, code, "exact", "oblast", 1)
        district = paren_text(phrase)
        if district and key(raw) in _CITY_REFS and self.kyiv_local.get(key(district)):
            p = self.kyiv_local[key(district)][0]  # "Київ (Оболонь)"
            return Resolved(p.name, p.lat, p.lon, p.admin1, "exact", p.kind, 1)
        tried: list[Place] = []
        exact, lemma = exact_forms(raw), lemma_forms(raw)
        for forms, how in ((exact, "exact"), (lemma, "lemma")):
            for form in forms:
                cands = self._lookup(form, admin1)
                if not cands:
                    continue
                p = self._pick(cands, scoped=admin1 is not None)
                if p:
                    return Resolved(p.name, p.lat, p.lon, p.admin1, how, p.kind, len(cands))
                tried = cands
            if tried:
                return Resolved(raw, None, None, admin1, "ambiguous", None, len(tried), tuple(tried))
        # Spelling variants within scope, then a neighbouring oblast (Славутич is Kyiv oblast but sits
        # inside Chernihiv oblast and is listed under "Чернігівщина:").
        for form in dict.fromkeys(loose_key(f) for f in (*exact, *lemma)):
            cands = self._in_scope(self.loose_index.get(form, []), admin1) if admin1 else []
            p = self._pick(cands) if cands else None
            if p:
                return Resolved(p.name, p.lat, p.lon, p.admin1, "fuzzy", p.kind, len(cands))
        if admin1 in self.oblast_centroids:
            clat, clon = self.oblast_centroids[admin1]
            for forms, how in ((exact, "exact"), (lemma, "lemma")):
                for form in forms:
                    near = [
                        p
                        for p in self.index.get(form, [])
                        if haversine_km(p.lat, p.lon, clat, clon) <= NEIGHBOUR_KM
                    ]
                    p = self._pick(near, scoped=False) if near else None
                    if p:
                        return Resolved(p.name, p.lat, p.lon, p.admin1, how, p.kind, len(near))
        # Without an oblast a nationwide name is accepted only if unique (checked above); fuzzy needs scope.
        if admin1 is not None:
            p, n = self._fuzzy(raw, admin1)
            if p:
                return Resolved(p.name, p.lat, p.lon, p.admin1, "fuzzy", p.kind, n)
            if n > 1:
                return Resolved(raw, None, None, admin1, "ambiguous", None, n)
        return Resolved(raw, None, None, admin1, "none")

    def _fuzzy(self, raw: str, admin1: str) -> tuple[Place | None, int]:
        from rapidfuzz import fuzz, process

        if admin1 == KYIV_CITY:
            pool = {k: v for k, v in self.kyiv_local.items()}
            for k, ps in self.index.items():
                ps2 = self._in_scope(ps, admin1)
                if ps2:
                    pool.setdefault(k, ps2)
        else:
            pool = self.by_oblast.get(admin1, {})
        if not pool:
            return None, 0
        best_place, best_n = None, 0
        for form in [*exact_forms(raw), *lemma_forms(raw)]:
            hits = process.extract(form, list(pool), scorer=fuzz.ratio, score_cutoff=FUZZY_MIN, limit=3)
            if not hits:
                continue
            top = [h for h in hits if h[1] == hits[0][1]]
            cands = [p for h in top for p in pool[h[0]]]
            p = self._pick(cands)
            if p:
                return p, len(cands)
            best_n = max(best_n, len(cands))
        return best_place, best_n


@cache
def default_gazetteer(gazetteer_dir: str) -> Gazetteer:
    return Gazetteer.load(Path(gazetteer_dir))


# ---------------------------------------------------------------- phrase helpers

_PAREN = re.compile(r"\(([^)]*)\)")
_CITY_REFS = {"київ", "києва", "києві", "місто", "містом", "міста", "місті"}
# "Вільнянськ Запорізької області" -> oblast hint + place
_OBLAST_SUFFIX = re.compile(r"\s+(?P<o>[А-ЯІЇЄҐа-яіїєґ'-]+(?:ої|ій)\s+(?:області|обл\.?))\s*$")
_TRAILING = re.compile(r"[\s.!?,;:…]+$")
_LEADING_JUNK = re.compile(
    r"^(?:(?:н\.\s?п|смт|с|м|сел)\.\s*|(?:н\.?\s?п\.?|смт|село|місто|селище|села|міста|селища|н/п)\s+)", re.I
)
# "центру Києва", "околиці Броварів", "району Борисполя" -> the place itself
_QUALIFIER = re.compile(r"^(?:центр\w*|околиц\w*|район\w*|р-н\w*|передмісті?|передмісття)\s+", re.I)


def inline_oblast(phrase: str, gz: Gazetteer) -> str | None:
    """'Овідіополь (Одещина)' / 'Вільнянськ Запорізької області' -> admin1."""
    m = _OBLAST_SUFFIX.search(normalize(phrase))
    if m:
        code = gz.oblast_as_target(m["o"])
        if code:
            return code
    for inner in _PAREN.findall(normalize(phrase)):
        code = gz.oblast_of_header(inner) or gz.oblast_as_target(inner)
        if code:
            return code
    return None


def loose_key(k: str) -> str:
    """Key with apostrophes dropped and 'ії'->'ї', 'йі'->'ї': 'юр'ївка' == 'юріївка'."""
    return k.replace("'", "").replace("ії", "ї").replace("йі", "ї").replace("ьо", "о")


def paren_text(phrase: str) -> str | None:
    m = _PAREN.search(normalize(phrase))
    return m.group(1).strip() if m else None


def clean_place(phrase: str) -> str:
    t = normalize(phrase)
    t = _OBLAST_SUFFIX.sub("", _PAREN.sub(" ", t))
    t = re.split(r"\s*/\s*|,\s*|\s+(?:та|і|й)\s+", t)[0]  # 'Вишгород/Київ', 'Умані, Христинівки'
    t = _TRAILING.sub("", t).strip(" \"'«»")
    t = _QUALIFIER.sub("", _LEADING_JUNK.sub("", t))
    return _LEADING_JUNK.sub("", t).strip()


def exact_forms(raw: str) -> list[str]:
    k = key(raw)
    return [k] if k else []


@lru_cache(maxsize=1)
def _morph():
    import pymorphy3

    return pymorphy3.MorphAnalyzer(lang="uk")


_GRAM_CASES = ("accs", "gent", "loct", "datv", "ablt", "nomn")


@lru_cache(maxsize=50_000)
def _word_nominatives(word: str) -> tuple[str, ...]:
    """Nominative forms of a (possibly inflected) word, keeping gender/number; most likely first."""
    if not re.search("[а-яіїєґ]", word.lower()):
        return ()
    out = []
    for p in _morph().parse(word)[:6]:
        if p.tag.case is None and p.tag.POS not in ("NOUN", "ADJF"):
            continue
        infl = p.inflect({"nomn"})
        if infl is not None:
            out.append(infl.word)
        if p.tag.POS in ("NOUN",) and p.normal_form:
            out.append(p.normal_form)
    return tuple(dict.fromkeys(key(w) for w in out))


# Suffix rules (inflected -> nominative) for words pymorphy does not know (small villages).
_SUFFIX_RULES = [
    ("івку", "івка"),
    ("ївку", "ївка"),
    ("ку", "ка"),
    ("цю", "ця"),
    ("ню", "ня"),
    ("лю", "ля"),
    ("ію", "ія"),
    ("ю", "я"),
    ("у", "а"),
    ("у", ""),
    ("а", ""),
    ("я", "ь"),
    ("я", "й"),
    ("і", "ь"),
    ("і", "а"),
    ("і", "я"),
    ("ів", "и"),
    ("ого", "е"),
    ("ого", "ий"),
    ("ої", "а"),
    ("ої", "я"),
    ("ої", "е"),
    ("ій", "а"),
    ("ій", "я"),
    ("ки", "ка"),
    ("ви", "ва"),
    ("ни", "на"),
    ("ця", "ець"),
    ("ка", "ок"),
    ("ла", "ол"),
    ("ра", "ер"),
    ("ева", "ів"),
    ("ова", "ів"),
    ("єва", "їв"),
    ("ина", "ин"),
    ("ина", "ине"),
    ("ого", "ове"),
    ("ого", "еве"),
    ("ого", "ине"),
]


def _suffix_variants(word: str) -> list[str]:
    w = key(word)
    return [w[: -len(a)] + b for a, b in _SUFFIX_RULES if w.endswith(a) and len(w) - len(a) >= 3]


def lemma_forms(raw: str) -> list[str]:
    """Candidate nominative keys for a phrase: per-word pymorphy inflection (cartesian, capped), then suffix rules."""
    words = key(raw).split(" ")
    if not words or not words[0]:
        return []
    per_word: list[list[str]] = []
    for w in words:
        parts = w.split("-")  # 'Новгород-Сіверського' -> inflect each part
        if len(parts) > 1:
            combos = [""]
            for part in parts:
                opts = list(_word_nominatives(part)) or [part]
                combos = [f"{c}-{o}" if c else o for c in combos for o in opts[:3]]
            per_word.append(list(dict.fromkeys([*combos, w]))[:6])
        else:
            per_word.append(list(dict.fromkeys([*_word_nominatives(w), w]))[:6])
    forms = [""]
    for opts in per_word:
        forms = [f"{f} {o}".strip() for f in forms for o in opts][:36]
    suffix = [" ".join([*words[:-1], v]) for v in _suffix_variants(words[-1])]
    if len(words) > 1:  # adjective + noun: inflect both by suffix rules
        suffix += [" ".join(v) for v in zip(*[_suffix_variants(w) or [w] for w in words], strict=False)]
    out = [f for f in dict.fromkeys([*forms, *suffix]) if f and f != key(raw)]
    return out


def word_forms(phrase: str) -> list[str]:
    """Exact key + nominative variants (used for oblast names as targets)."""
    raw = clean_place(phrase)
    return [*exact_forms(raw), *lemma_forms(raw)]
