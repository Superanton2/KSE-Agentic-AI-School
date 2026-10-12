"""Dev server for web/: like `python -m http.server -d web 8080`, plus the headers FastAPI will send later.

    python scripts/serve_web.py [--port 8080] [--host 127.0.0.1]

- Cache-Control: no-store — the browser never runs stale JS/CSS after an edit.
- CSP with frame-ancestors, Permissions-Policy, Referrer-Policy — these do not work from <meta>.
Geolocation needs a secure context: http://localhost works, http://<LAN IP> from a phone does not.
"""

from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data: https://server.arcgisonline.com; "
    "connect-src 'self' https://routing.openstreetmap.de https://photon.komoot.io; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": CSP,
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=()",
    "X-Content-Type-Options": "nosniff",
}


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".geojson": "application/geo+json", ".mjs": "text/javascript"}

    def end_headers(self) -> None:
        for k, v in HEADERS.items():
            self.send_header(k, v)
        super().end_headers()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), functools.partial(Handler, directory=str(WEB)))
    print(f"serving {WEB} at http://{args.host}:{args.port}/  (?mock=calm|alert|alert-red|stale|flip|unsure)")
    server.serve_forever()


if __name__ == "__main__":
    main()
