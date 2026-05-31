# Add a model

Everything lives in one file: **`config.json`** (copied from
`config.example.json` on first run). To add a backend you edit two sections:

1. **`models`** — what appears in Claude Code's `/model` picker.
2. **`routes`** — where each of those ids actually goes.

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

> **Two rules you must follow:**
> 1. Every `id` in `models` **must start with `claude` or `anthropic`** — Claude
>    Code drops everything else from `/model`.
> 2. The `id` in `models` must **exactly equal** the key in `routes`. Otherwise
>    the model won't appear or won't route.
>
> Run `python scripts/doctor.py` and it checks both for you.

## Where keys go

`config.json` is gitignored, so you can put a key **inline**:

```json
"auth": "Bearer sk-...your-real-key..."
```

…or keep it out of the file with **`${ENV}`** expansion:

```json
"auth": "Bearer ${MIMO_API_KEY}"
```

`${VAR}` is read from your environment. The launchers also load an optional
gitignored **`ultracode.env`** in the repo root, so you can keep keys there:

```
MIMO_API_KEY=...
OPENROUTER_API_KEY=...
```

## Route types

### `openai_compat` — anything that speaks OpenAI Chat Completions

MiMo, DeepSeek, StepFun, Ollama Cloud, OpenRouter, OpenAI, Together, a local
llama.cpp / LM Studio server, etc. Tool calls are translated both ways.

```json
"claude-openrouter": {
  "type": "openai_compat",
  "upstream": "https://openrouter.ai/api/v1",
  "model": "meta-llama/llama-3.3-70b-instruct",
  "auth": "Bearer ${OPENROUTER_API_KEY}"
}
```

- `upstream` is the OpenAI **base URL exactly as the provider documents it**
  (usually ends in `/v1`). The proxy appends `/chat/completions`.
- `model` is the backend's real model id, **not** the `claude-…` alias.
- Optional: `headers` (a dict, values support `${VARS}`) and `max_output_tokens`
  (completion cap, default 8192 — raise it if a backend supports longer output).

A **local** server is the same, with a usually-ignored key:

```json
"claude-local": {
  "type": "openai_compat",
  "upstream": "http://127.0.0.1:11434/v1",
  "model": "your-local-model",
  "auth": "Bearer local"
}
```

### Anthropic passthrough — real Claude or an Anthropic-compatible endpoint

Omit `type` (or set `"anthropic"`). With no `auth`/`upstream` it's just real
Claude with the UltraCode envelope. You can also point at an Anthropic-shaped
gateway and add headers:

```json
"claude-opencode": {
  "upstream": "https://opencode.ai/zen/go",
  "model": "claude-sonnet-4-5",
  "auth": "Bearer ${OPENCODE_API_KEY}",
  "headers": { "User-Agent": "openclaw/2026.4.20" }
}
```

### `codex_oauth` — GPT‑5.5 via a ChatGPT/Codex login (no API key)

```json
"claude-gpt-5.5-codex": { "type": "codex_oauth", "model": "gpt-5.5" }
```

Run `codex login` once (creates `~/.codex/auth.json`). No `auth`/`upstream`
needed. Optional env knobs: `UC_CODEX_EFFORT`, `UC_CODEX_SERVICE_TIER`,
`CODEX_HOME`.

### `cursor_agent` — Cursor Composer (experimental)

```json
"claude-composer": { "type": "cursor_agent", "model": "composer-2.5" }
```

Needs the `cursor-agent` CLI and `cursor-agent login`. It's an autonomous agent,
not a plain endpoint, so we run it in read-only "ask" mode and bridge tool calls
as text markers — great for reasoning/answers, best-effort for tool-calling.

## What ships in the example

`config.example.json` includes ready-to-use entries — keep the ones you have a
plan/key for and delete the rest:

| Picker label | id | `type` | backend |
|--------------|----|--------|---------|
| GPT-5.5 (Codex OAuth) | `claude-gpt-5.5-codex` | `codex_oauth` | `codex login` |
| MiMo v2.5 Pro | `claude-mimo` | `openai_compat` | Xiaomi MiMo |
| DeepSeek V4 Pro/Flash | `claude-deepseek-v4-*` | `openai_compat` | DeepSeek |
| Step Flash | `claude-step-flash` | `openai_compat` | StepFun |
| Ollama Cloud | `claude-ollama-cloud` | `openai_compat` | Ollama Cloud |
| Claude via OpenCode Go | `claude-opencode` | passthrough | OpenCode Go |
| Llama 3.3 70B (OpenRouter) | `claude-openrouter` | `openai_compat` | OpenRouter |
| Local model | `claude-local` | `openai_compat` | local server |
| Composer 2.5 (experimental) | `claude-composer` | `cursor_agent` | cursor-agent |

After editing, validate and launch:

```
python scripts/doctor.py
windows\Start-UltraCode.ps1      # or  ./bin/ultracode  on mac/linux
```
