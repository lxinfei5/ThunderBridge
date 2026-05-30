#!/usr/bin/env bash
# Install UltraCode launchers into ~/.local/bin
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"

mkdir -p "$BIN_DIR"

for script in claude-mimo-ultracode claude-mimo-ultracode-video \
              claude-composer-ultracode claude-composer-ultracode-video; do
  src="$REPO_ROOT/bin/$script"
  dst="$BIN_DIR/$script"
  install -m 755 "$src" "$dst"
  echo "installed $dst"
done

MIMO_ENV_DIR="${HOME}/.config/devin"
MIMO_ENV="${MIMO_ENV_DIR}/mimo.env"
if [[ ! -f "$MIMO_ENV" ]]; then
  mkdir -p "$MIMO_ENV_DIR"
  cp "$REPO_ROOT/config/mimo.env.example" "$MIMO_ENV"
  echo "created $MIMO_ENV from example — add your DEVIN_MIMO_API_KEY"
fi

echo
echo "Done. Smoke test:"
echo "  claude-mimo-ultracode --smoke"
echo "  claude-composer-ultracode --smoke"
echo
echo "Windows desktop icons (run from PowerShell):"
echo "  .\\scripts\\install-desktop-icons.ps1"
