"""One-off: fetch Metro Cash & Carry and McDonald's venues and Kyiv raion boundaries from OSM (Overpass).

    uv run python scripts/fetch_stores.py

Writes web/data/stores.geojson (points: name, address, lat, lon, brand, venue = metro | mcdonalds) and
web/data/kyiv_raions.geojson (raion outlines, simplified, coordinates rounded to ~10 m).
Data © OpenStreetMap contributors, ODbL — see LICENSES/OSM-ODbL.txt.
"""

from __future__ import annotations

import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OUT = Path(__file__).resolve().parents[1] / "web" / "data"
UA = "KSE-Agentic-AI-School/phase3 (one-off fetch)"

# Kyiv city = admin_level 4 relation "Київ"; raions are admin_level 10 inside it.
STORES_Q = """
[out:json][timeout:170];
rel(421866);map_to_area->.kyiv;  /* relation 421866 «Київ», admin_level 4 */
(
  nwr(area.kyiv)["brand:wikidata"="Q13610282"];  /* METRO Cash & Carry; checked: same 4 as name~"metro" */
  nwr(area.kyiv)["brand:wikidata"="Q38076"];     /* McDonald's */
  nwr(area.kyiv)["brand"="McDonald's"];
);
out center tags;
"""

RAIONS_Q = """
[out:json][timeout:170];
rel(421866);map_to_area->.kyiv;  /* relation 421866 «Київ», admin_level 4 */
rel(area.kyiv)["boundary"="administrative"]["admin_level"="10"];
out geom;
"""


def overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    for url in MIRRORS:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                res = json.load(r)
            if res.get("remark"):  # e.g. "runtime error: Query timed out" with partial/empty elements
                raise ValueError(res["remark"])
            if not res.get("elements"):  # a busy mirror may answer 200 with nothing; never overwrite data with it
                raise ValueError("empty answer")
            return res
        except (OSError, ValueError) as e:  # 429/504 from busy mirrors, timeouts, HTML error pages
            print(f"  {url}: {e}", file=sys.stderr)
    sys.exit("all Overpass mirrors failed")


def address(tags: dict) -> str:
    street = tags.get("addr:street", "")
    num = tags.get("addr:housenumber", "")
    return f"{street}, {num}".strip(", ") if street else tags.get("addr:full", "")


def fetch_stores() -> list[dict]:
    seen, feats = set(), []
    for el in overpass(STORES_Q)["elements"]:
        tags = el.get("tags", {})
        lat = el.get("lat") or el["center"]["lat"]
        lon = el.get("lon") or el["center"]["lon"]
        venue = "metro" if tags.get("brand:wikidata") == "Q13610282" else "mcdonalds"
        key = (venue, round(lat, 3), round(lon, 3))
        if key in seen:  # node + building outline of the same store
            continue
        seen.add(key)
        props = {
            "id": f"{el['type'][0]}{el['id']}",
            "name": tags.get("name:uk") or tags.get("name") or ("Metro" if venue == "metro" else "McDonald's"),
            "address": address(tags),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "brand": venue,
            "venue": venue,
        }
        feats.append(
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [props["lon"], props["lat"]]},
             "properties": props}
        )
    feats.sort(key=lambda f: (f["properties"]["venue"] != "metro", f["properties"]["name"], f["properties"]["id"]))
    return feats


def _perp(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(x - x1, y - y1)
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / math.hypot(dx, dy)


def simplify(pts: list, eps: float) -> list:
    """Douglas–Peucker, iterative."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        dmax, idx = 0.0, -1
        for k in range(i + 1, j):
            d = _perp(pts[k], pts[i], pts[j])
            if d > dmax:
                dmax, idx = d, k
        if dmax > eps:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(pts, keep, strict=True) if k]


def fetch_raions(eps: float = 0.0008) -> list[dict]:
    feats = []
    for rel in overpass(RAIONS_Q)["elements"]:
        lines = []
        for m in rel.get("members", []):
            if m.get("role") == "outer" and "geometry" in m:
                pts = [(g["lon"], g["lat"]) for g in m["geometry"]]
                pts = [(round(x, 4), round(y, 4)) for x, y in simplify(pts, eps)]
                if len(pts) >= 2:
                    lines.append(pts)
        name = rel["tags"].get("name:uk") or rel["tags"].get("name")
        # Outer ways are drawn as lines: we only need dashed outlines, not fill, so no ring assembly.
        feats.append({"type": "Feature", "properties": {"name": name},
                      "geometry": {"type": "MultiLineString", "coordinates": lines}})
    feats.sort(key=lambda f: f["properties"]["name"])
    return feats


def dump(path: Path, feats: list[dict]) -> int:
    text = json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")
    return len(text.encode())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stores = fetch_stores()
    dump(OUT / "stores.geojson", stores)
    by = {v: [f for f in stores if f["properties"]["venue"] == v] for v in ("metro", "mcdonalds")}
    print("stores: " + ", ".join(f"{v} {len(fs)}" for v, fs in by.items()))
    for f in by["metro"] + by["mcdonalds"][:5]:
        p = f["properties"]
        print(f"  {p['id']:>14}  {p['name']:<30} {p['address']:<40} {p['lat']:.5f},{p['lon']:.5f}")
    raions = fetch_raions()
    size = dump(OUT / "kyiv_raions.geojson", raions)
    print(f"raions: {len(raions)} ({', '.join(f['properties']['name'] for f in raions)}), {size / 1024:.1f} KB")
    if size > 60 * 1024:
        sys.exit("kyiv_raions.geojson > 60 KB: raise eps")


if __name__ == "__main__":
    main()
