#!/usr/bin/env bash
# UltraCode-Shim installer (macOS / Linux / WSL).
#
# Goal: one command turns a fresh machine into "type `ultracode`, pick a model,
# go" -- it gets the code, verifies it with the offline self-test, creates your
# config.json, and builds a small `ultracode` launcher on your PATH.
#
# Run it either way:
#   curl -fsSL https://raw.githubusercontent.com/OnlyTerp/UltraCode-Shim/main/install.sh | bash
#   ./install.sh                      # from inside a clone
#
# Flags / env:
#   --dir DIR        where to clone if not already in a checkout
#                    (default: $UC_INSTALL_DIR or ~/.ultracode-shim)
#   --bin-dir DIR    where to put the `ultracode` launcher
#                    (default: $UC_BIN_DIR or ~/.local/bin)
#   --no-test        skip the offline self-test
#   --uninstall      remove the launcher shim (leaves your clone + config)
#   -h | --help      show this help
#
# Nothing here needs root, touches your global Claude config, or pip-installs
# anything (the proxy is pure standard library).
set -euo pipefail

REPO_URL="https://github.com/OnlyTerp/UltraCode-Shim.git"
INSTALL_DIR="${UC_INSTALL_DIR:-$HOME/.ultracode-shim}"
BIN_DIR="${UC_BIN_DIR:-$HOME/.local/bin}"
RUN_TEST=1
DO_UNINSTALL=0

# ---- pretty output (honors NO_COLOR / non-TTY) -----------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; P=$'\033[38;5;141m'; G=$'\033[38;5;42m'
  Y=$'\033[38;5;214m'; R=$'\033[38;5;203m'; X=$'\033[0m'
else
  B=""; DIM=""; P=""; G=""; Y=""; R=""; X=""
fi
say()  { printf '%s\n' "$*"; }
info() { printf '%s==>%s %s\n' "$P" "$X" "$*"; }
ok()   { printf '%s  ok%s %s\n' "$G" "$X" "$*"; }
warn() { printf '%swarn%s %s\n' "$Y" "$X" "$*" >&2; }
die()  { printf '%sFAIL%s %s\n' "$R" "$X" "$*" >&2; exit 1; }

usage() { sed -n '2,28p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)       INSTALL_DIR="${2:?--dir needs a path}"; shift 2 ;;
    --dir=*)     INSTALL_DIR="${1#*=}"; shift ;;
    --bin-dir)   BIN_DIR="${2:?--bin-dir needs a path}"; shift 2 ;;
    --bin-dir=*) BIN_DIR="${1#*=}"; shift ;;
    --no-test)   RUN_TEST=0; shift ;;
    --uninstall) DO_UNINSTALL=1; shift ;;
    -h|--help)   usage ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

# ---- locate python ---------------------------------------------------------
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || die "Python 3 not found. Install it from https://www.python.org/downloads/ then re-run."
"$PY" - <<'PY' || die "Python 3.8+ is required."
import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)
PY

# ---- figure out where the repo is (local checkout vs. clone) ---------------
# Resolve this script through symlinks so a local run is detected correctly.
SELF="${BASH_SOURCE[0]:-$0}"
if [ -f "$SELF" ]; then
  while [ -h "$SELF" ]; do
    d="$(cd -P "$(dirname "$SELF")" && pwd)"; SELF="$(readlink "$SELF")"
    case "$SELF" in /*) ;; *) SELF="$d/$SELF" ;; esac
  done
  SCRIPT_DIR="$(cd -P "$(dirname "$SELF")" && pwd)"
else
  SCRIPT_DIR=""   # piped via curl|bash; not a real file
fi

is_repo() { [ -f "$1/proxy.py" ] && [ -f "$1/bin/ultracode" ]; }

REPO=""
if [ -n "$SCRIPT_DIR" ] && is_repo "$SCRIPT_DIR"; then
  REPO="$SCRIPT_DIR"
  info "Using this checkout: ${B}$REPO${X}"
elif is_repo "$PWD"; then
  REPO="$PWD"
  info "Using this checkout: ${B}$REPO${X}"
else
  # Not in a checkout -> clone (or update) into INSTALL_DIR.
  command -v git >/dev/null 2>&1 || die "git not found. Install git, or download the repo and run ./install.sh from inside it."
  if is_repo "$INSTALL_DIR"; then
    info "Updating existing clone at ${B}$INSTALL_DIR${X}"
    git -C "$INSTALL_DIR" pull --ff-only --quiet || warn "could not fast-forward; using the existing clone as-is"
  else
    info "Cloning ${B}$REPO_URL${X} -> ${B}$INSTALL_DIR${X}"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 --quiet "$REPO_URL" "$INSTALL_DIR" || die "git clone failed"
  fi
  REPO="$INSTALL_DIR"
fi
is_repo "$REPO" || die "internal: '$REPO' is not a valid UltraCode-Shim checkout"

LAUNCHER="$REPO/bin/ultracode"
chmod +x "$LAUNCHER" 2>/dev/null || true

# ---- uninstall path --------------------------------------------------------
if [ "$DO_UNINSTALL" = "1" ]; then
  removed=0
  for d in "$BIN_DIR" "$HOME/.local/bin" "/usr/local/bin"; do
    shim="$d/ultracode"
    if [ -e "$shim" ] || [ -L "$shim" ]; then
      rm -f "$shim" && { ok "removed $shim"; removed=1; }
    fi
  done
  [ "$removed" = "1" ] || warn "no ultracode launcher found in the usual bin dirs"
  say "Your clone ($REPO) and config.json were left untouched."
  exit 0
fi

# ---- offline self-test (proves the proxy works; uses free ports) -----------
if [ "$RUN_TEST" = "1" ] && [ -f "$REPO/test_proxy.py" ]; then
  info "Running the offline self-test (no network, no keys)..."
  PORTS="$("$PY" - <<'PY'
import socket
def free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
print(free(), free())
PY
)"
  P1="${PORTS%% *}"; P2="${PORTS##* }"
  if UC_TEST_PROXY_PORT="$P1" UC_TEST_MOCK_PORT="$P2" "$PY" "$REPO/test_proxy.py" >/tmp/uc_selftest.$$ 2>&1; then
    ok "self-test passed (proxy, discovery, UltraCode envelope, tool translation)"
    rm -f /tmp/uc_selftest.$$
  else
    sed 's/^/    /' /tmp/uc_selftest.$$ >&2 || true
    rm -f /tmp/uc_selftest.$$
    die "self-test failed -- the clone looks broken. Please open an issue with the output above."
  fi
fi

# ---- config.json (gitignored; holds your picks + keys) ---------------------
if [ ! -f "$REPO/config.json" ]; then
  cp "$REPO/config.example.json" "$REPO/config.json"
  ok "created ${B}config.json${X} from the example (edit it to keep the models you have)"
else
  ok "config.json already exists -- leaving it as-is"
fi

# ---- build the `ultracode` launcher on your PATH ---------------------------
mkdir -p "$BIN_DIR"
SHIM="$BIN_DIR/ultracode"
cat > "$SHIM" <<EOF
#!/usr/bin/env bash
# UltraCode-Shim launcher (generated by install.sh). Points at your checkout;
# edit the repo, not this shim. Re-run install.sh to repoint it.
exec "$LAUNCHER" "\$@"
EOF
chmod +x "$SHIM"
ok "installed launcher: ${B}$SHIM${X} -> $LAUNCHER"

# ---- PATH guidance ---------------------------------------------------------
case ":$PATH:" in
  *":$BIN_DIR:"*) ON_PATH=1 ;;
  *) ON_PATH=0 ;;
esac

say ""
info "${B}Done.${X} UltraCode-Shim is installed."
say ""
if [ "$ON_PATH" = "1" ]; then
  say "  Launch it from anywhere:   ${B}ultracode${X}"
else
  warn "$BIN_DIR is not on your PATH yet."
  # Best-effort: name the right rc file for the user's shell.
  case "${SHELL:-}" in
    */zsh)  RC="$HOME/.zshrc" ;;
    */bash) RC="$HOME/.bashrc" ;;
    *)      RC="your shell profile" ;;
  esac
  say "  Add it (then restart your shell):"
  say "    ${B}echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> $RC${X}"
  say "  Or launch with the full path for now:"
  say "    ${B}$SHIM${X}"
fi
say ""
say "  Next steps:"
say "    1. ${B}Configure your models:${X} edit ${DIM}$REPO/config.json${X}"
say "       (keep the backends you have a key/plan for; delete the rest)."
say "    2. ${B}Sanity-check it:${X}      ${DIM}$PY $REPO/scripts/doctor.py${X}"
say "    3. ${B}Run it:${X}               ${DIM}ultracode${X}  (pick orchestrator + worker, then /model anytime)"
say ""
command -v claude >/dev/null 2>&1 || \
  warn "Claude Code CLI not found yet -- install it before launching:  npm i -g @anthropic-ai/claude-code"
