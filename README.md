# UltraCode-Shim

Run **Claude Code UltraCode** (Opus 4.8 gate, Workflow tool, deep-reasoning harness) while routing actual inference to a cheaper backend you choose — MiMo, Cursor Composer, or any model your local shim supports.

Claude Code only unlocks UltraCode for `claude-opus-4-8`. That model is expensive. This project gives you **one desktop icon per backend**: double-click, get the full UltraCode UX, pay the backend you picked.

## How it works

```
Desktop .lnk  →  Windows .cmd  →  WSL launcher  →  local shim  →  backend model
     │                │                 │                  │
  MiMo icon      wsl.exe bash      claude-mimo-      byok_oai_shim    MiMo v2.5 Pro
  Composer icon                   ultracode-video   /v1/messages     Composer 2.5 Fast
```

1. **Claude Code** starts with `--model claude-opus-4-8` and `{"ultracode": true}` settings — passes the UltraCode gate.
2. **`ANTHROPIC_BASE_URL`** points at a local shim on loopback (not Anthropic).
3. **The shim** sees `model=claude-opus-4-8` plus `CLAUDE_CODE_ULTRACODE_BACKEND=<your-backend>` and routes to MiMo, Cursor Agent, etc.
4. **Claude Code never knows** — it gets Anthropic-shaped SSE back with tool calls intact.

Each backend gets its own port, state dir, and desktop shortcut so you can run MiMo UltraCode and Composer UltraCode side by side.

## Requirements

- **Windows 11 + WSL2** (Ubuntu tested) — desktop icons launch via `wsl.exe`.
- **Claude Code CLI** installed (`npm i -g @anthropic-ai/claude-code` or Windows npm path).
- **Local API shim** with Anthropic `/v1/messages` gateway and UltraCode override support. This repo ships launchers; the gateway lives in [`byok_oai_shim.py`](https://github.com/OnlyTerp/devin-local-proxy) (or your own compatible shim).
- **Backend credentials** as needed:
  - **MiMo**: `DEVIN_MIMO_API_KEY` in `~/.config/devin/mimo.env`
  - **Composer**: Cursor CLI (`cursor-agent`) on PATH inside WSL

## Quick install

```bash
git clone https://github.com/OnlyTerp/UltraCode-Shim.git ~/UltraCode-Shim
cd ~/UltraCode-Shim
./scripts/install.sh
```

Then from **Windows PowerShell** (creates `.cmd` helpers + Desktop shortcuts):

```powershell
cd \\wsl.localhost\Ubuntu\home\$env:USERNAME\UltraCode-Shim
.\scripts\install-desktop-icons.ps1
```

Or pass `-DesktopPath` if your Desktop is elsewhere (OneDrive sync):

```powershell
.\scripts\install-desktop-icons.ps1 -DesktopPath "$env:USERPROFILE\OneDrive\Desktop"
```

## Desktop icons (included presets)

| Shortcut | Backend | Default port | Icon |
|----------|---------|--------------|------|
| MiMo v2.5 Pro UltraCode VIDEO | MiMo v2.5 Pro | 18766 | Xiaomi logo |
| Composer 2.5 Fast UltraCode VIDEO | Cursor Composer 2.5 Fast | 18767 | Cursor icon |
| Claude MiMo UltraCode | MiMo (interactive, pauses on exit) | 18766 | Windows Terminal |

**VIDEO** variants set the terminal title and session name for screen recordings. Use those for demos; use the plain MiMo shortcut for daily work.

## Smoke test

```bash
claude-mimo-ultracode --smoke
claude-composer-ultracode --smoke
```

Expected: one-line reply (`MIMO_ULTRACODE_OK` / `COMPOSER_ULTRACODE_OK`).

## Add a new backend

1. Add a route in your shim's `MODEL_ROUTES` (e.g. `"my-model": ("provider", "upstream-slug")`).
2. Copy `bin/claude-composer-ultracode` → `bin/claude-mybackend-ultracode`.
3. Set `CLAUDE_*_ULTRACODE_BACKEND`, port, and health-check model list.
4. Add a `-video` wrapper and `.cmd` launcher.
5. Register it in `scripts/install-desktop-icons.ps1` `$Presets` array.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for shim env vars and gateway details.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLAUDE_MIMO_ULTRACODE_PORT` | `18766` | MiMo shim listen port |
| `CLAUDE_COMPOSER_ULTRACODE_PORT` | `18767` | Composer shim listen port |
| `CLAUDE_*_ULTRACODE_PROXY_DIR` | `$HOME/devin-local-proxy` | Directory containing `byok_oai_shim.py` |
| `CLAUDE_CODE_ULTRACODE_BACKEND` | set by launcher | Backend route override inside shim |
| `DEVIN_MIMO_ENV` | `~/.config/devin/mimo.env` | MiMo API key file |
| `CURSOR_AGENT_WORKSPACE` | `$PWD` or `$HOME/repos` | Workspace passed to cursor-agent |

Copy `config/mimo.env.example` → `~/.config/devin/mimo.env` and fill in your key.

## Why this saves money

UltraCode is gated on Opus 4.8. Without a shim, every Workflow pass, every tool round-trip, every deep-research fan-out bills Opus rates. Routing to MiMo or Composer keeps the **harness** (workflows, skills, memory, tool approval) while the **tokens** come from your chosen backend.

Typical setup: Opus for the 5% of tasks that genuinely need it; MiMo or Composer icons for everything else that still wants UltraCode depth.

## License

MIT — see [LICENSE](LICENSE).
