"""Screenshots of web/ states for review: docs/screenshots/<state>-<device>.png.

    python scripts/serve_web.py &
    uv run --with playwright python scripts/web_screenshots.py [--base http://localhost:8080] [--states calm,alert]

Suffixes: +nogeo (geolocation denied), +from (start typed in search), +search, +settings, +info, +banner. Fails (exit 1) if the page logs console
errors (CSP violations included) or if any request to our own origin carries the user's coordinates.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
GEO = {"latitude": 50.4392, "longitude": 30.5169, "accuracy": 350}  # пл. Льва Толстого
DEVICES = {
    "mobile": {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True},
    "desktop": {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1},
}


def leaks_coords(req) -> bool:
    blob = req.url + (req.post_data or "")
    return any(f"{v:.3f}" in blob for v in (GEO["latitude"], GEO["longitude"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--states", default="calm,alert,alert-red,stale,unsure,calm+nogeo,calm+from,calm+search,calm+settings,calm+info,flip+banner,model")
    ap.add_argument("--devices", default="mobile,desktop")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for dev in args.devices.split(","):
            for state in args.states.split(","):
                mock, _, flag = state.partition("+")
                geo = {} if flag == "nogeo" else {"geolocation": GEO, "permissions": ["geolocation"]}
                ctx = browser.new_context(**DEVICES[dev], **geo, locale="uk-UA", timezone_id="Europe/Kyiv")
                page = ctx.new_page()
                page.on("console", lambda m, s=state: m.type == "error" and errors.append(f"{s}: {m.text}"))
                page.on("pageerror", lambda e, s=state: errors.append(f"{s}: {e}"))
                page.on("request", lambda r, s=state: r.url.startswith(args.base) and leaks_coords(r)
                        and errors.append(f"{s}: coordinates sent to own origin: {r.url}"))
                path = OUT / f"{state.replace('+', '-')}-{dev}.png"
                if mock == "model":
                    page.goto(f"{args.base}/model.html", wait_until="networkidle")
                    page.wait_for_selector("h1:not(:empty)")
                    page.screenshot(path=str(path), full_page=True)
                    print(path.relative_to(OUT.parents[1]))
                    ctx.close()
                    continue
                page.goto(f"{args.base}/?mock={mock}", wait_until="networkidle")
                page.wait_for_selector("#status-text:not(:empty)")
                if flag == "nogeo":
                    page.wait_for_selector("#hint:not([hidden])", timeout=15000)
                    page.wait_for_timeout(1500)
                    page.screenshot(path=str(path))
                    print(path.relative_to(OUT.parents[1]), "|", page.text_content("#hint"))
                    ctx.close()
                    continue
                try:  # OSRM answers within its 4 s timeout; then the straight-line "≈" estimate is replaced
                    page.wait_for_function(
                        "() => { const c = document.querySelector('#card');"
                        " return !c.hidden && !c.querySelector('#card-trip').textContent.includes('≈'); }",
                        timeout=15000)  # без геолокації браузер чекає 8 с таймауту
                except PWTimeout:
                    print(f"  {state}-{dev}: travel time still approximate", file=sys.stderr)
                page.wait_for_timeout(1500)  # fitBounds animation + tile fade-in
                if flag == "search":
                    page.click("#btn-search")
                    page.keyboard.type("Хрещатик")
                    try:  # Photon: debounce 400 ms + network
                        page.wait_for_selector(".opt-place", timeout=12000)
                    except PWTimeout:
                        print(f"  {state}-{dev}: no Photon results", file=sys.stderr)
                elif flag == "from":  # start = an address from search instead of «my location»
                    page.click("#btn-search")
                    page.keyboard.type("Хрещатик 22")
                    page.wait_for_selector(".opt-place", timeout=12000)
                    page.click(".opt-place")
                    page.wait_for_function(
                        "() => document.querySelector('#card-from').textContent.includes('Хрещатик')"
                        " && !document.querySelector('#card-trip').textContent.includes('≈')", timeout=12000)
                    page.wait_for_timeout(1500)
                elif flag in ("settings", "info"):
                    page.click(f"#btn-{flag}")
                    page.wait_for_selector(f"#{flag}:not([hidden])")
                    page.wait_for_timeout(300)  # slide-in
                elif flag == "banner":  # mock=flip: the 2nd poll (after 15 s) turns calm into alert
                    page.wait_for_selector("#banner:not([hidden])", timeout=25000)
                page.screenshot(path=str(path))
                print(path.relative_to(OUT.parents[1]), "|", page.text_content("#card-trip"))
                ctx.close()
        browser.close()

    for e in errors:
        print("error:", e, file=sys.stderr)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
