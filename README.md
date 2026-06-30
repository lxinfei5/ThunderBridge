# ⚡ ThunderBridge

*Bridge Claude Code's UltraCode mode to any model — with the speed of thunder.*

[![License: MIT](https://img.shields.io/badge/License-MIT-8b5cf6.svg)](LICENSE)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-6366f1)
![deps: stdlib only](https://img.shields.io/badge/deps-stdlib%20only-a855f7)
![platforms](https://img.shields.io/badge/platforms-Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-c026d3)

> Forked from [UltraCode-Shim](https://github.com/OnlyTerp/UltraCode-Shim) by OnlyTerp — the
> original breakthrough. ThunderBridge adds passthrough-first defaults, dynamic port
> allocation, and streamlined single-model configuration.

---

## What it does

Use Claude Code's **UltraCode** mode (xhigh effort + deep-reasoning workflow harness)
with **any model you already pay for** — pick it live from the `/model` menu, or set
it once before launch.

One command. Your normal Claude Code install is left untouched.

---

## How it works

At the API level, "UltraCode" is just `effort=xhigh` + adaptive thinking + a big
`max_tokens` + one system reminder — **there is no secret model**. ThunderBridge runs
a loopback proxy that injects this envelope into every request, then forwards to the
backend you configure. Full breakdown: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

### Passthrough mode (default)

When your upstream already speaks the Anthropic Messages API natively (e.g., Tencent
Maas, DeepSeek's `/anthropic` endpoint, any Anthropic-compatible gateway),
ThunderBridge runs in **passthrough mode** — zero protocol translation, just envelope
injection. No OpenAI translation layer, no tool-call repair overhead.

For an example, see `config.astockos.json`.

### Orchestrator + Worker

Claude Code's `/model` menu is single-slot — but its dynamic-workflow engine issues
sub-agent traffic as the stock model regardless of your pick. ThunderBridge turns
that single slot into **two**:

- **Orchestrator** (left column) — the main interactive loop
- **Worker** (right column) — every Workflow/Task sub-agent

Pick one model for both, or a strong model for planning and a cheaper one for parallel
work. The proxy classifies requests by structural signal (main loop carries
`AskUserQuestion`, `EnterPlanMode`, `ExitPlanMode`; sub-agents never do) and routes
accordingly. Toggle off with `UC_ORCH_WORKER=0`.

### Auto Router (optional)

Don't want to pick at all? Enable the Auto Router and the proxy decides per task —
trivial turns go cheap, hard turns escalate to your strongest model. A small
classifier model you nominate scores each candidate 0–1, then the proxy selects
the cheapest candidate above your quality threshold (default 0.7). The classifier
never sees price, so it can't be biased.

```jsonc
"router": {
  "enabled": true,
  "classifier": "claude-mimo",        // cheap fast model for scoring
  "threshold": 0.7,                   // minimum quality score
  "candidates": [
    { "id": "claude-minimax-m3",    "cost": 0.3, "card": "cheap; single-file edits, codegen" },
    { "id": "claude-gpt-5.5-codex", "cost": 5.0, "card": "frontier; big refactors, debugging, images" }
  ]
}
```

Off until configured. Full guide: [docs/AUTO_ROUTER.md](docs/AUTO_ROUTER.md).

### Reliability hardening

Built for long, autonomous workflow runs:

- **Empty-turn auto-retry** — transparently re-issues blipped turns; zero latency on normal ones
- **Stream-stall timeout** — a silent stream won't freeze the entire run
- **Tool-call repair** — rejecting a tool mid-run works on strict backends like DeepSeek
- **Reasoning keepalive** — models that think silently (MiniMax-M3, etc.) show live activity, not frozen UI

All tunable via env vars. Details: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md#6-reliability--surviving-long-and-dynamic-workflows).

---

## Quick start

### Prerequisites

- **Claude Code CLI**: `npm i -g @anthropic-ai/claude-code`
- **Python 3.8+** (standard library only — nothing to `pip install`)
- **At least one backend credential** (API key, or `codex login` for GPT-5.5)

### Install

**macOS / Linux / WSL:**

```bash
curl -fsSL https://raw.githubusercontent.com/lxinfei5/ThunderBridge/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/lxinfei5/ThunderBridge/main/install.ps1 | iex
```

**Manual install** (if you prefer to inspect the code first):

```bash
git clone https://github.com/lxinfei5/ThunderBridge.git
cd ThunderBridge
python3 scripts/doctor.py              # sanity-check + offline self-test
cp config.example.json config.json     # edit to add your models and keys
./bin/thunderbridge                    # launch
```

### Configure

Edit one file: **`config.json`** (copied from `config.example.json` on first run).

Two sections:

- **`models`** — what appears in `/model`. Every `id` **must start with `claude` or `anthropic`** (Claude Code filters the rest).
- **`routes`** — where each model ID actually goes. The route key must match the model `id`.

Example — Anthropic passthrough (your Maas gateway, DeepSeek `/anthropic`, etc.):

```jsonc
{
  "models": [
    { "id": "claude-deepseek", "display_name": "DeepSeek V4 (UltraCode)" }
  ],
  "routes": {
    "claude-deepseek": {
      "upstream": "https://your-gateway.example.com",
      "model": "your-model-id",
      "auth": "passthrough"
    }
  }
}
```

Example — OpenAI-compatible backend (MiMo, OpenRouter, Ollama, etc.):

```jsonc
{
  "models": [
    { "id": "claude-mimo", "display_name": "MiMo v2.5 Pro" }
  ],
  "routes": {
    "claude-mimo": {
      "type": "openai_compat",
      "upstream": "https://token-plan-sgp.xiaomimimo.com/v1",
      "model": "mimo-v2.5-pro",
      "auth": "Bearer ${MIMO_API_KEY}"
    }
  }
}
```

Route types:

| `type` | Use for | Needs |
|---|---|---|
| *(omit)* | Anthropic-compatible endpoints (real Claude, Maas, DeepSeek `/anthropic`) | Optional `auth`/`upstream` |
| `openai_compat` | MiMo, DeepSeek, OpenRouter, OpenAI, Ollama, local llama.cpp | API key |
| `codex_oauth` | GPT-5.5 via ChatGPT/Codex login | `codex login` once |
| `cursor_agent` | Cursor Composer (experimental) | `cursor-agent login` |
| `auto` | Auto Router — pick the right model per task | `router` block + classifier |

> **API keys** can go inline in `config.json` (gitignored), as `${ENV_VAR}` references,
> or in a gitignored `ultracode.env` file that the launcher loads.

Full walkthrough: [docs/ADD_A_MODEL.md](docs/ADD_A_MODEL.md).

### Launch

```bash
thunderbridge
```

The launcher: starts the proxy on a dynamic port → opens the orchestrator/worker
selector → launches Claude Code. Type `/model` anytime to switch. The proxy cleans
up automatically on exit.

Environment variables:

| Variable | Effect | Default |
|---|---|---|
| `UC_SELECTOR=0` | Skip the two-column model selector | selector shown |
| `UC_ORCH_WORKER=0` | One model for everything (no orchestrator/worker split) | split enabled |
| `UC_FORCE_EFFORT=0` | Don't inject `effort=xhigh` | `xhigh` |
| `UC_FORCE_THINKING=0` | Don't inject `thinking: adaptive` | `adaptive` |
| `UC_MAX_TOKENS` | Override max_tokens floor | 64000 |
| `UC_ROUTER_LOG=1` | Show Auto Router decisions live | off |

---

## Safety

The launcher sets environment variables **only for the launched process** using a
session-scoped `--settings` file. It never touches your global Claude config or
credentials. Remove the launcher with `./install.sh --uninstall`.

---

## Verification

Run the offline self-test (no network, no keys needed):

```bash
python3 test_proxy.py
```

Proves the proxy, discovery, UltraCode envelope, tool-call translation, and routing
all work. Runs in CI on Linux/Windows × Python 3.8/3.12.

---

## Demo

```bash
cd examples/demo/
thunderbridge
# Paste the prompt from examples/demo/PROMPT.md
```

A buggy Conway's Game of Life — the prompt asks to fix a bug, add an animated color
renderer and starting patterns, and run a self-test culminating in a glider crawling
across the terminal.

---

## Docs

| File | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | Runbook for AI assistants (install → configure → test → troubleshoot) |
| [docs/SETUP.md](docs/SETUP.md) | Human setup guide (Windows + macOS/Linux) |
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Mechanism + reverse-engineering evidence |
| [docs/AUTO_ROUTER.md](docs/AUTO_ROUTER.md) | Auto Router — per-task model selection |
| [docs/DIRECTIVES.md](docs/DIRECTIVES.md) | Routing directives — pin requests to models from prompts |
| [docs/ADD_A_MODEL.md](docs/ADD_A_MODEL.md) | Add any backend to the `/model` menu |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Symptom → cause → fix reference |

---

## License

MIT — see [LICENSE](LICENSE). This is an unofficial, community project; it is not
affiliated with Anthropic, OpenAI, or any model provider. You are responsible for
complying with the terms of whatever accounts you route through it.
