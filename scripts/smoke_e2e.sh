#!/usr/bin/env bash
# End-to-end check from a clean clone, as a reviewer without Telegram would run it:
#   clone HEAD -> make setup -> make demo (background) -> /api/health, /api/state, /api/estimate -> screenshots -> stop.
# Screenshots land in THIS checkout: docs/screenshots/demo-{mobile,desktop}.png.
#   scripts/smoke_e2e.sh [PORT]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8765}"
TMP="$(mktemp -d)"
LOG="$TMP/demo.log"
PID=""

cleanup() {
  [ -n "$PID" ] && pkill -P "$PID" 2>/dev/null; [ -n "$PID" ] && kill "$PID" 2>/dev/null
  pkill -f "airalert serve --port $PORT" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "== clone $(git -C "$REPO" rev-parse --short HEAD) -> $TMP/app"
git clone -q "$REPO" "$TMP/app"
cd "$TMP/app"

echo "== make setup"
make setup

echo "== make demo (port $PORT)"
START=$(date +%s)
make demo PORT="$PORT" OPEN=0 >"$LOG" 2>&1 &
PID=$!
for _ in $(seq 1 120); do
  curl -sf "http://127.0.0.1:$PORT/api/state" >/dev/null && break
  kill -0 "$PID" 2>/dev/null || { cat "$LOG"; echo "make demo exited"; exit 1; }
  sleep 1
done
echo "up in $(( $(date +%s) - START )) s"

check() {  # url, python assertion over `j`
  local body
  body=$(curl -sf "http://127.0.0.1:$PORT$1") || { echo "FAIL $1: no answer"; exit 1; }
  python3 -c "import json,sys; j=json.loads(sys.argv[1]); assert $2, j; print('ok  $1')" "$body" \
    || { echo "FAIL $1: $body"; exit 1; }
}
check /api/health 'j["mode"] == "replay" and j["model"]'
check /api/state 'j["mode"] == "replay" and j["status"] in ("calm", "alert")'
check "/api/estimate?travel=20&shop_mean=60&wait_max=15" '0 <= j["p"] <= 1 and len(j["curve"]) > 0'
check /api/model-card 'j["product_backtest"]["n_trips"] > 0'

echo "== screenshots"
(cd "$REPO" && uv run --with playwright python scripts/web_screenshots.py --base "http://127.0.0.1:$PORT" --states demo,model)
echo "SMOKE OK"
