# Setup

Works on **Windows 11** (no WSL required) and on **macOS / Linux / WSL**.

## 1. Prerequisites

| Need | Check | Get it |
|------|-------|--------|
| Python 3.8+ | `python --version` / `python3 --version` | https://www.python.org/downloads (Windows: tick **Add Python to PATH**) |
| Claude Code CLI | `claude --version` | `npm i -g @anthropic-ai/claude-code` |
| UltraCode access | you've used `/effort ultracode` before | part of your Claude plan |
| ≥1 backend credential | — | an API key and/or `codex login` (see below) |

There is **nothing to pip install** — the proxy is pure standard library.

## 2. Clone and check

```
git clone https://github.com/OnlyTerp/UltraCode-Shim.git
cd UltraCode-Shim
python scripts/doctor.py      # windows: python   |  mac/linux: python3
```

The doctor runs an offline self-test. If it says `ALL TESTS PASSED`, the install
is good and you can configure your models. (It's safe to run the doctor anytime.)

## 3. Configure your models

The launcher copies `config/*.example.*` to real files on first run, but you can
do it now:

```
# from config/
copy ultracode_models.example.json ultracode_models.json   # windows
copy ultracode_slots.example.json  ultracode_slots.json
copy ultracode.example.env         ultracode.env
# (mac/linux: use cp)
```

Edit them for the plans you have — see [ADD_A_MODEL.md](ADD_A_MODEL.md). Put API
keys in `ultracode.env` (gitignored) and reference them as `${VAR}` in the slots.

### GPT‑5.5 via ChatGPT/Codex login (optional)

If you want the `codex_oauth` backend:

1. Install the Codex CLI and run `codex login` once. This creates `~/.codex/auth.json`.
2. Keep the `claude-gpt-5.5-codex` entries in the example configs (or add your own).

No API key is needed for this path — it reuses your ChatGPT login.

## 4. Re-run the doctor

```
python scripts/doctor.py
```

Resolve any `[FAIL]` lines (each prints the fix), until it exits cleanly.

## 5a. Windows: Desktop icons

```powershell
.\windows\Install-DesktopIcons.ps1
```

Creates two Desktop shortcuts:

- **UltraCode (All Models)** — starts the proxy and Claude Code with discovery on.
- **Claude Code (Normal)** — plain `claude`, your usual install, untouched.

To target a non-default Desktop:
`.\windows\Install-DesktopIcons.ps1 -DesktopPath "$env:USERPROFILE\Desktop"`

If PowerShell blocks the script, run it once as:
`powershell -ExecutionPolicy Bypass -File .\windows\Install-DesktopIcons.ps1`

## 5b. macOS / Linux / WSL

```
./bin/ultracode
```

(Optionally symlink it onto your PATH: `ln -s "$PWD/bin/ultracode" ~/.local/bin/ultracode`.)

## 6. Use it

Double-click **UltraCode (All Models)** (or run the launcher). When Claude Code
opens, type `/model` and pick a backend. Everything runs with full UltraCode.

## Uninstall

- Windows: `.\windows\Uninstall.ps1` (removes the icons + session state; leaves
  your config and Claude Code alone).
- Everywhere: delete the repo folder. Your `~/.claude` and credentials are never
  modified by this project.
