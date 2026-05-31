# UltraCode-Shim

[![CI](https://github.com/OnlyTerp/UltraCode-Shim/actions/workflows/ci.yml/badge.svg)](https://github.com/OnlyTerp/UltraCode-Shim/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![deps: stdlib only](https://img.shields.io/badge/deps-stdlib%20only-success)

Use Claude Code's **UltraCode** mode (xhigh effort + the Workflow/deep-reasoning
harness) with **any model you already pay for** — pick it live from the `/model`
menu.

One icon. Open Claude Code, type `/model`, and choose any backend you've set up —
all running with the full UltraCode harness. Your normal Claude Code install is
left untouched.

The example config ships ready-to-use entries for **GPT‑5.5 (Codex login)**,
**MiMo v2.5 Pro**, **DeepSeek V4 Pro/Flash**, **Step Flash**, **Ollama Cloud**,
**OpenCode Go**, **OpenRouter**, and **local models** — keep the ones you have a
plan for, delete the rest. (Cursor's Composer needs the `cursor-agent` CLI and
isn't HTTP-based — see [docs/ADD_A_MODEL.md](docs/ADD_A_MODEL.md).)

```
  Claude Code  ──ANTHROPIC_BASE_URL──▶  proxy.py (loopback)  ──▶  the model you picked
   /model menu  ◀── GET /v1/models ──   (adds UltraCode envelope,   (MiMo / OpenRouter /
                                         routes by your config.json)  Codex OAuth / local / Claude)
```

> **How is this possible?** At the API level, "UltraCode" is just
> `effort=xhigh` + adaptive thinking + a big `max_tokens` + one system reminder —
> there is no secret model. The proxy adds that envelope to every request, so any
> backend gets the UltraCode treatment. Full breakdown (with the reverse‑engineering
> evidence) in [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

## Demo

There's a ready-to-run scenario in [`examples/demo/`](examples/demo/) — a buggy
little Game of Life. Launch UltraCode there, pick any model, enable auto mode,
and paste [the prompt](examples/demo/PROMPT.md): it fixes the bug, adds an
animated color renderer + starting patterns, and runs its own self-test, ending
on a glider crawling across the screen.

<!-- Recording goes here. Drop a clip at assets/demo/demo.gif and uncomment: -->
<!-- ![UltraCode-Shim demo](assets/demo/demo.gif) -->

Verified live against real backends: **GPT‑5.5** (Codex login) and **Cursor
Composer**, plus an offline self-test that runs in CI on Linux/Windows ×
Python 3.8/3.12.

## What you need

- **Claude Code CLI** with UltraCode access (`npm i -g @anthropic-ai/claude-code`).
- **Python 3.8+** (standard library only — there is nothing to `pip install`).
- **At least one backend credential**, e.g. an API key (MiMo / OpenRouter / OpenAI /
  a local server) and/or a `codex login` for GPT‑5.5. You only set up the ones you have.

Tested on **Windows 11** (no WSL needed). macOS/Linux/WSL work too via `bin/ultracode`.

## Quick start (Windows)

```powershell
git clone https://github.com/OnlyTerp/UltraCode-Shim.git
cd UltraCode-Shim

# 1. Sanity-check your machine and config (safe to run anytime)
python scripts\doctor.py

# 2. Tell it which models you want (see "Configure your models" below)
#    Copy config.example.json to config.json, keep the models you have,
#    and put your keys in it (config.json is gitignored).
copy config.example.json config.json

# 3. Create Desktop icons (one for UltraCode, one for normal Claude Code)
.\windows\Install-DesktopIcons.ps1

# 4. Double-click "UltraCode (All Models)" — then type /model and pick a backend.
```

macOS / Linux / WSL: run `python3 scripts/doctor.py` then `./bin/ultracode`.
(The launchers copy `config.example.json` → `config.json` for you on first run if
you skip step 2.)

## Configure your models

Everything is in one file: **`config.json`** (copied from `config.example.json`).
It has two sections you edit:

- **`models`** — what shows up in the `/model` menu. Every `id` **must start with
  `claude` or `anthropic`** (Claude Code filters the rest out).
- **`routes`** — where each of those ids actually goes. The route key must match
  the model `id`.

Example — MiMo and an OpenRouter model:

```jsonc
{
  "models": [
    { "id": "claude-mimo",       "display_name": "MiMo v2.5 Pro" },
    { "id": "claude-openrouter", "display_name": "Llama 3.3 70B (OpenRouter)" }
  ],
  "routes": {
    "claude-mimo": {
      "type": "openai_compat",
      "upstream": "https://token-plan-sgp.xiaomimimo.com/v1",
      "model": "mimo-v2.5-pro",
      "auth": "Bearer ${MIMO_API_KEY}"
    },
    "claude-openrouter": {
      "type": "openai_compat",
      "upstream": "https://openrouter.ai/api/v1",
      "model": "meta-llama/llama-3.3-70b-instruct",
      "auth": "Bearer ${OPENROUTER_API_KEY}"
    }
  }
}
```

Put your key right in `config.json` (it's gitignored) or use `${ENV_VAR}` and
export it — or drop keys into a gitignored `ultracode.env` the launchers load.

Route types:

| `type`          | Use for                                            | Needs |
|-----------------|----------------------------------------------------|-------|
| *(omit)*        | Real Claude or any Anthropic-compatible endpoint   | nothing, or `auth`/`upstream` |
| `openai_compat` | MiMo, DeepSeek, OpenRouter, OpenAI, Ollama, local llama.cpp — anything that speaks OpenAI Chat Completions (tools included) | an API key |
| `codex_oauth`   | GPT‑5.5 via a ChatGPT/Codex login (no API key)     | `codex login` once |
| `cursor_agent`  | Cursor Composer (experimental)                     | `cursor-agent login` |

Full walkthrough: [docs/ADD_A_MODEL.md](docs/ADD_A_MODEL.md).

## Is my normal Claude Code safe?

Yes. The UltraCode launcher only sets environment variables **for the launched
process** and uses a session-scoped `--settings` file. It never edits your global
Claude config or credentials. The installer also gives you a **"Claude Code (Normal)"**
icon, so you can always start the plain version. Remove everything with
`windows\Uninstall.ps1`.

## Telling your AI assistant to set this up

This repo is built so you can hand it to an assistant. Point it at
[AGENTS.md](AGENTS.md) — that's a step-by-step runbook (install → configure →
test → troubleshoot) written for an AI to follow.

## Docs

| Doc | What |
|-----|------|
| [AGENTS.md](AGENTS.md) | Runbook for an AI assistant to install/configure/test |
| [docs/SETUP.md](docs/SETUP.md) | Human setup guide (Windows + macOS/Linux) |
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | The mechanism + reverse-engineering evidence |
| [docs/ADD_A_MODEL.md](docs/ADD_A_MODEL.md) | Add any backend to the `/model` menu |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Symptom → cause → fix |

## License

MIT — see [LICENSE](LICENSE). This is an unofficial, community project; it is not
affiliated with Anthropic, OpenAI, or any model provider. You are responsible for
complying with the terms of whatever accounts you route through it.
