# How it works

UltraCode-Shim is a tiny loopback proxy plus a launcher. There is no magic and
no secret model. This page explains the mechanism and the reverse-engineering it
is based on.

## 1. What "UltraCode" actually is

At the Anthropic API boundary, Claude Code's **UltraCode** mode is not a hidden
model — it's an *envelope* applied to an ordinary `/v1/messages` request:

| Field | UltraCode value | Meaning |
|-------|-----------------|---------|
| `output_config.effort` | `"xhigh"` | maximum reasoning effort |
| `thinking` | `{"type": "adaptive"}` | extended/adaptive thinking on |
| `max_tokens` | `>= 64000` | room for long, thorough answers |
| `system` | + an *"Ultracode is on…"* reminder block | steers toward the Workflow/quality harness |

That's it. Anything that speaks the Anthropic Messages API and honors those
fields gets the UltraCode treatment. Because it's just request shape, we can put
the *same* envelope on a request and then forward it to **any** backend.

## 2. The proxy

`proxy.py` is a standard-library HTTP server you point Claude Code at via
`ANTHROPIC_BASE_URL` (the launchers do this for you). For every request it:

1. **Forces the envelope** on `POST /v1/messages` — sets `effort=xhigh`, adaptive
   `thinking`, raises `max_tokens` to the floor (default 64000), and injects the
   reminder if it isn't already present. (Toggle with `UC_FORCE_EFFORT`,
   `UC_FORCE_THINKING`, `UC_MAX_TOKENS`, `UC_INJECT_REMINDER`.)
2. **Serves `GET /v1/models`**, merging Anthropic's real model list with your
   own entries from `config.json` so they show up in the `/model` picker.
3. **Routes** each model id Claude Code sends to a real backend, per the
   `routes` map in `config.json`.

## 3. Why your models appear in `/model` (gateway discovery)

Recent Claude Code supports **gateway model discovery**: when
`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, it calls `GET /v1/models` on the
gateway and lists what comes back in `/model`. The launchers set that env var and
also pre-seed Claude Code's `cache/gateway-models.json` so your models show on
the very first open.

> **Hard rule from Claude Code:** discovered ids are filtered with
> `/^(claude|anthropic)/i`. Any model id that does **not** start with `claude`
> or `anthropic` is silently dropped. That's why every `id` in `config.json`
> looks like `claude-mimo`, `claude-openrouter`, etc.

Gateway discovery only triggers on a first-party (OAuth) login, not on a raw
`ANTHROPIC_API_KEY`.

## 4. Routing each pick to a real backend

When you pick a model, Claude Code sends its id as `model`. The proxy looks that
id up in `config.json` → `routes` and forwards accordingly:

- **Anthropic passthrough** (no `type`, or `type: "anthropic"`) — forwards the
  request unchanged to `upstream` (default `api.anthropic.com`, i.e. real
  Claude) or any Anthropic-compatible endpoint. Tools work natively.
- **`openai_compat`** — translates the Anthropic request to an OpenAI
  Chat Completions request, POSTs it to `upstream + /chat/completions`, and
  translates the response back. **Tool calls are translated both ways**
  (Anthropic `tool_use`/`tool_result` ⇄ OpenAI `tool_calls`/`role:tool`), and
  streaming SSE is re-emitted as Anthropic SSE. This covers MiMo, DeepSeek,
  StepFun, Ollama, OpenRouter, OpenAI, local llama.cpp/LM Studio, etc.
- **`codex_oauth`** — sends to GPT‑5.5 via your ChatGPT/Codex *login* (no API
  key), using `providers/codex_oauth.py` and the token from `codex login`.
- **`cursor_agent`** (experimental) — bridges to Cursor's Composer through the
  `cursor-agent` CLI via `providers/cursor_agent.py`. Reasoning works well;
  tool-calling is a best-effort text bridge.

## 5. What touches your machine

- The launchers set env (`ANTHROPIC_BASE_URL`, discovery flag) for **the launched
  process only** and pass Claude Code a session-scoped `--settings` file. Your
  global `~/.claude` config and credentials are never modified.
- `config.json` (your keys/choices) is **gitignored**.
- The proxy is stopped when Claude Code exits.

## File map

| Path | What |
|------|------|
| `proxy.py` | the interceptor: envelope + `/v1/models` discovery + routing. Stdlib only. |
| `providers/codex_oauth.py` | optional GPT‑5.5-via-ChatGPT-login helper. Stdlib only. |
| `providers/cursor_agent.py` | optional Cursor Composer bridge (experimental). Stdlib only. |
| `config.json` | your models + routes + keys (copied from `config.example.json`; gitignored). |
| `test_proxy.py` | offline end-to-end self-test (no network/keys). |
| `scripts/doctor.py` | environment + config validator that runs the self-test. |
| `windows/Start-UltraCode.ps1`, `bin/ultracode` | launchers (start proxy, run Claude Code, clean up). |
