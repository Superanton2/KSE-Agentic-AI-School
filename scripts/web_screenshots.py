"""Screenshots of web/ states for review: docs/screenshots/<state>-<device>.png.

    python -m http.server -d web 8080 &
    uv run --with playwright python scripts/web_screenshots.py [--base http://localhost:8080] [--states calm,alert]

Fails (exit 1) if the page logs console errors — CSP violations included.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
DEVICES = {
    "mobile": {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True},
    "desktop": {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--states", default="calm,alert,alert-red,stale")
    ap.add_argument("--devices", default="mobile,desktop")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for dev in args.devices.split(","):
            ctx = browser.new_context(**DEVICES[dev], locale="uk-UA", timezone_id="Europe/Kyiv")
            for state in args.states.split(","):
                page = ctx.new_page()
                page.on("console", lambda m, s=state: m.type == "error" and errors.append(f"{s}: {m.text}"))
                page.on("pageerror", lambda e, s=state: errors.append(f"{s}: {e}"))
                page.goto(f"{args.base}/?mock={state}", wait_until="networkidle")
                page.wait_for_selector("#status-text:not(:empty)")
                page.wait_for_timeout(800)  # tile fade-in
                path = OUT / f"{state}-{dev}.png"
                page.screenshot(path=str(path))
                print(path.relative_to(OUT.parents[1]))
                page.close()
            ctx.close()
        browser.close()

    for e in errors:
        print("console error:", e, file=sys.stderr)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
