# UltraCode-Shim

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
  Claude Code  ──ANTHROPIC_BASE_URL──▶  ultracode_proxy (loopback)  ──▶  the model you picked
   /model menu  ◀── GET /v1/models ──   (adds UltraCode envelope,        (MiMo / OpenRouter /
                                         routes by your slot map)          Codex OAuth / local / Claude)
```

> **How is this possible?** At the API level, "UltraCode" is just
> `effort=xhigh` + adaptive thinking + a big `max_tokens` + one system reminder —
> there is no secret model. The proxy adds that envelope to every request, so any
> backend gets the UltraCode treatment. Full breakdown (with the reverse‑engineering
> evidence) in [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

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
#    Edit config\ultracode_slots.json and config\ultracode_models.json,
#    put any API keys in config\ultracode.env

# 3. Create Desktop icons (one for UltraCode, one for normal Claude Code)
.\windows\Install-DesktopIcons.ps1

# 4. Double-click "UltraCode (All Models)" — then type /model and pick a backend.
```

macOS / Linux / WSL: run `python3 scripts/doctor.py` then `./bin/ultracode`.

## Configure your models

Two small files in `config/` (copied from the `.example` versions on first run):

- **`ultracode_models.json`** — what shows up in the `/model` menu.
  Every id **must start with `claude` or `anthropic`** (Claude Code filters the rest out).
- **`ultracode_slots.json`** — where each of those ids actually goes.

Example: add MiMo and an OpenRouter model.

`config/ultracode_models.json`
```json
{ "models": [
  { "id": "claude-mimo",            "display_name": "MiMo v2.5 Pro" },
  { "id": "claude-openrouter-llama","display_name": "Llama 3.3 70B (OpenRouter)" }
]}
```

`config/ultracode_slots.json`
```json
{
  "claude-mimo": {
    "type": "openai_compat",
    "model": "mimo-v2.5-pro",
    "upstream": "https://token-plan-sgp.xiaomimimo.com/v1",
    "auth": "Bearer ${MIMO_API_KEY}"
  },
  "claude-openrouter-llama": {
    "type": "openai_compat",
    "model": "meta-llama/llama-3.3-70b-instruct",
    "upstream": "https://openrouter.ai/api/v1",
    "auth": "Bearer ${OPENROUTER_API_KEY}"
  }
}
```

`config/ultracode.env` (gitignored — keys never get committed)
```
MIMO_API_KEY=...
OPENROUTER_API_KEY=...
```

Backend types:

| `type`          | Use for                                            | Needs |
|-----------------|----------------------------------------------------|-------|
| *(omit)*        | Real Claude or any Anthropic-compatible endpoint   | `auth: "passthrough"` |
| `openai_compat` | MiMo, OpenRouter, OpenAI, Together, local llama.cpp/Ollama — anything that speaks OpenAI Chat Completions (tools included) | an API key in `ultracode.env` |
| `codex_oauth`   | GPT‑5.5 via a ChatGPT/Codex login (no API key)     | `codex login` once |

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
