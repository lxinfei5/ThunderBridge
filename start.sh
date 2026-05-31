#!/usr/bin/env bash
#
# start.sh -- ultracode-unlock launcher (macOS / Linux)
#
# What it does:
#   1. Ensures config.json exists (copies config.example.json on first run).
#   2. Reads the listen port from config.json.
#   3. Starts proxy.py in the background.
#   4. Points Claude Code at the proxy + enables gateway model discovery,
#      then launches `claude` in this same shell.
#
# Usage:
#   ./start.sh             # start proxy + launch claude
#   ./start.sh --no-claude # start proxy only
#
# Press Ctrl+C to stop everything.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

CONFIG="$HERE/config.json"
EXAMPLE="$HERE/config.example.json"

NO_CLAUDE=0
for arg in "$@"; do
    case "$arg" in
        --no-claude) NO_CLAUDE=1 ;;
    esac
done

# 1. First-run: seed config.json from the example.
if [ ! -f "$CONFIG" ]; then
    if [ ! -f "$EXAMPLE" ]; then
        echo "ERROR: neither config.json nor config.example.json found in $HERE" >&2
        exit 1
    fi
    cp "$EXAMPLE" "$CONFIG"
    echo "Created config.json from config.example.json."
    echo "EDIT config.json with your provider + API key, then re-run ./start.sh"
    exit 0
fi

# 2. Find a Python interpreter (prefer a local venv).
PYTHON=""
for cand in "$HERE/.venv/bin/python3" "$HERE/venv/bin/python3"; do
    if [ -x "$cand" ]; then PYTHON="$cand"; break; fi
done
if [ -z "$PYTHON" ]; then
    if command -v python3 >/dev/null 2>&1; then PYTHON="python3";
    elif command -v python >/dev/null 2>&1; then PYTHON="python";
    else echo "ERROR: no Python interpreter found (need Python 3.8+)." >&2; exit 1; fi
fi

# 3. Read listen port from config.json (default 8141), using the same Python.
PORT="$("$PYTHON" - "$CONFIG" <<'PY'
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        cfg = json.load(f)
    print(int((cfg.get("proxy") or {}).get("listen_port", 8141)))
except Exception:
    print(8141)
PY
)"

# 4. Launch the proxy in the background.
echo "Starting ultracode-unlock proxy on http://127.0.0.1:$PORT ..."
"$PYTHON" "$HERE/proxy.py" &
PROXY_PID=$!

cleanup() {
    if kill -0 "$PROXY_PID" 2>/dev/null; then
        echo "Stopping proxy (PID $PROXY_PID)..."
        kill "$PROXY_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# Health check.
sleep 1
if command -v curl >/dev/null 2>&1; then
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
        echo "Proxy healthy on port $PORT."
    else
        echo "WARNING: proxy health check failed; it may still be starting." >&2
    fi
fi

# 5. Point Claude Code at the proxy.
export ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT"
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY="1"
echo "ANTHROPIC_BASE_URL=$ANTHROPIC_BASE_URL"

if [ "$NO_CLAUDE" -eq 1 ]; then
    echo "Proxy running (PID $PROXY_PID). Press Ctrl+C to stop."
    wait "$PROXY_PID"
    exit 0
fi

# 6. Launch claude in this shell (inherits env vars above).
if ! command -v claude >/dev/null 2>&1; then
    echo "WARNING: 'claude' CLI not found on PATH. Proxy is running on port $PORT." >&2
    echo "Open a shell with these env vars set and run claude:"
    echo "  export ANTHROPIC_BASE_URL='http://127.0.0.1:$PORT'"
    echo "  export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY='1'"
    wait "$PROXY_PID"
    exit 0
fi

claude "$@"
