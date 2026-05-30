# Architecture

## Problem

Claude Code UltraCode mode requires:

- `--model claude-opus-4-8` (or 4.7)
- User/project settings with `"ultracode": true`
- Harness injects Workflow tool, deep-research skills, xhigh effort defaults

Opus 4.8 is the only model most accounts can select for UltraCode, and it is priced accordingly.

## Solution

Intercept Anthropic API calls locally. Claude Code still *requests* Opus; the shim *fulfills* with a cheaper backend.

### Shim gateway (external dependency)

The Anthropic `/v1/messages` handler checks:

```python
if CLAUDE_CODE_ULTRACODE_BACKEND and model in CLAUDE_CODE_ULTRACODE_GATE_MODELS:
    route = _model_route(CLAUDE_CODE_ULTRACODE_BACKEND)
    route_override = CLAUDE_CODE_ULTRACODE_BACKEND
```

Gate models default to `claude-opus-4-8,claude-opus-4-7`.

Supported providers in the reference shim:

| Provider | Example backend | Streamer |
|----------|-----------------|----------|
| `mimo` | `mimo-v2.5-pro` | OpenAI-compatible chat completions |
| `cursor_agent` | `composer-2.5-fast` | `cursor-agent` subprocess |
| `claude_oauth` | passthrough | Real Anthropic (no savings) |
| `codex_oauth` | passthrough | ChatGPT Codex |

Each launcher starts an isolated shim instance:

```bash
env CLAUDE_CODE_ULTRACODE_BACKEND=mimo python3 byok_oai_shim.py --host 127.0.0.1 --port 18766
```

### Launcher lifecycle

```
claude-mimo-ultracode-video          # branded wrapper (title, --name, system prompt)
  └─ claude-mimo-ultracode           # core launcher
       ├─ start_shim()               # spawn byok_oai_shim if not healthy
       ├─ write_settings()           # {"ultracode": true}
       └─ exec claude --model claude-opus-4-8 \
            --settings $SETTINGS_FILE \
            with ANTHROPIC_BASE_URL=http://127.0.0.1:18766
```

State per backend:

```
~/.local/state/claude-mimo-ultracode/
  settings.json    # ultracode flag for Claude Code
  shim.pid         # background shim process
  shim.log         # shim stdout/stderr
```

### Windows desktop chain

```
OneDrive/Desktop/MiMo v2.5 Pro UltraCode VIDEO.lnk
  Target: C:\Users\<you>\.terp\launchers\Claude MiMo UltraCode VIDEO.cmd
  Icon:   Xiaomi logo .ico (or custom)

Claude MiMo UltraCode VIDEO.cmd
  wsl.exe -d Ubuntu --cd ~/repos --exec bash -lc "exec claude-mimo-ultracode-video"
```

`WSLENV` forwards `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, and `CLAUDE_CODE_WORKFLOWS` from WSL to Windows npm `claude` if needed.

### Port map (defaults)

| Backend | Port | Env prefix |
|---------|------|------------|
| MiMo | 18766 | `CLAUDE_MIMO_ULTRACODE_*` |
| Composer | 18767 | `CLAUDE_COMPOSER_ULTRACODE_*` |

Ports are independent so both shims can run simultaneously.

## Request flow (Composer example)

1. User double-clicks **Composer 2.5 Fast UltraCode VIDEO**.
2. WSL runs `claude-composer-ultracode-video`.
3. Shim starts on `:18767` with `CLAUDE_CODE_ULTRACODE_BACKEND=composer-2.5-fast`.
4. Claude Code sends `POST /v1/messages` `model=claude-opus-4-8`, `stream=true`, tools included.
5. Shim logs: `anthropic /v1/messages gateway model=claude-opus-4-8 upstream=composer-2.5-fast provider=cursor_agent`.
6. `_stream_cursor_agent()` spawns `cursor-agent`, converts OpenAI tool deltas → Anthropic SSE.
7. Claude Code renders Workflow/tool UI normally.

## Security notes

- Shims bind `127.0.0.1` only.
- `ANTHROPIC_API_KEY` is a dummy value; real auth is backend-specific (MiMo key, Cursor session).
- Do not expose shim ports beyond loopback.
