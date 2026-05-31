#!/usr/bin/env bash
#
# doctor.sh -- ultracode-unlock health & config checker (macOS / Linux)
#
# Run this when something isn't working. It checks Python, config.json validity,
# model ids + routes, proxy reachability, and Claude Code env vars.
#
# Usage:  ./doctor.sh

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

ok=0; warn=0; fail=0
pass() { printf '  \033[32m[PASS]\033[0m %s\n' "$1"; ok=$((ok+1)); }
warnf(){ printf '  \033[33m[WARN]\033[0m %s\n' "$1"; warn=$((warn+1)); }
failf(){ printf '  \033[31m[FAIL]\033[0m %s\n' "$1"; fail=$((fail+1)); }

echo "ultracode-unlock doctor"
echo "======================="

# Python
PYTHON=""
for cand in "$HERE/.venv/bin/python3" "$HERE/venv/bin/python3"; do
    if [ -x "$cand" ]; then PYTHON="$cand"; break; fi
done
if [ -z "$PYTHON" ]; then
    if command -v python3 >/dev/null 2>&1; then PYTHON="python3";
    elif command -v python >/dev/null 2>&1; then PYTHON="python"; fi
fi
if [ -n "$PYTHON" ]; then pass "Python found: $PYTHON"; else failf "No Python interpreter (need 3.8+)."; fi

# config.json
CONFIG="$HERE/config.json"
PORT=8141
if [ ! -f "$CONFIG" ]; then
    failf "config.json missing. Run ./start.sh once to create it from config.example.json."
elif [ -n "$PYTHON" ]; then
    # Validate JSON and walk models/routes in one pass.
    REPORT="$("$PYTHON" - "$CONFIG" <<'PY'
import json, sys, re
try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        cfg = json.load(f)
except Exception as e:
    print("FAIL config.json is not valid JSON: %s" % e); sys.exit(0)
print("PASS config.json is valid JSON.")
print("PORT %d" % int((cfg.get("proxy") or {}).get("listen_port", 8141)))
models = cfg.get("models") or []
routes = cfg.get("routes") or {}
if not models:
    print("WARN no models configured in config.json.")
for m in models:
    mid = m.get("id", "")
    if not re.match(r"^(claude|anthropic)", mid or ""):
        print("FAIL model id '%s' must start with 'claude' or 'anthropic'." % mid); continue
    r = routes.get(mid)
    if not r:
        print("WARN model '%s' has no entry in 'routes' (passes through to Anthropic)." % mid); continue
    if "REPLACE_ME" in str(r.get("auth", "")):
        print("WARN route '%s' still has a placeholder API key (auth contains REPLACE_ME)." % mid)
    else:
        print("PASS model '%s' -> %s @ %s (model=%s)" % (mid, r.get("type"), r.get("upstream"), r.get("model")))
PY
)"
    while IFS= read -r line; do
        case "$line" in
            PASS\ *) pass "${line#PASS }" ;;
            WARN\ *) warnf "${line#WARN }" ;;
            FAIL\ *) failf "${line#FAIL }" ;;
            PORT\ *) PORT="${line#PORT }" ;;
        esac
    done <<< "$REPORT"
fi

# proxy reachable
if command -v curl >/dev/null 2>&1; then
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
        pass "proxy reachable on http://127.0.0.1:$PORT"
    else
        warnf "proxy not reachable on port $PORT. Start it with ./start.sh (or ./start.sh --no-claude)."
    fi
else
    warnf "curl not found; skipping proxy reachability check."
fi

# env vars
if [ "${ANTHROPIC_BASE_URL:-}" = "http://127.0.0.1:$PORT" ]; then
    pass "ANTHROPIC_BASE_URL points at the proxy."
else
    warnf "ANTHROPIC_BASE_URL is '${ANTHROPIC_BASE_URL:-<unset>}' (expected http://127.0.0.1:$PORT). start.sh sets this for you."
fi
if [ -n "${CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY:-}" ]; then
    pass "gateway model discovery enabled."
else
    warnf "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY not set (needed for the custom /model menu)."
fi

echo ""
echo "Summary: $ok pass, $warn warn, $fail fail"
[ "$fail" -gt 0 ] && exit 1 || exit 0
