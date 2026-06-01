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

## 5. Reliability — surviving long and dynamic workflows

UltraCode's value is *long, autonomous* runs (deep reasoning, multi-step
Workflows, multi-agent fan-out). The weak point of any "translate to a third-party
backend" shim is that those backends occasionally hiccup — and on a 40-minute
agent run, one hiccup that isn't handled can wedge the whole session. The proxy
defends against the three failure modes we actually hit in production:

### a. Empty turns are auto-retried

Some upstreams intermittently return an assistant turn with **no text and no tool
call** — a transient blip, or a budget-exhausted `response.incomplete` reasoning
turn at high effort (notably GPT‑5.5 via codex). An empty turn is useless to
Claude Code and can stall a Workflow step. `_events_with_retry()` transparently
re-issues a fresh turn:

- It **buffers only until the first meaningful event**, so a normal turn adds
  **zero latency** and already-streamed output is never duplicated.
- It retries only on an empty/transient result — **never** after meaningful
  output, a fatal (non-retryable `4xx`) error, or partial output already streamed.
- Tunable: `UC_EMPTY_RETRY_ATTEMPTS` (default `2`), `UC_EMPTY_RETRY_BACKOFF`
  (default `0.75`s). Wraps both the `codex_oauth` and `openai_compat` paths.

### b. A stalled stream can't freeze the whole run

A codex stream can open (SSE established) and then go **silent mid-turn**.
Previously that blocked on the 600s socket read timeout — so a single hung
sub-agent could freeze an entire multi-agent / dynamic-workflow run for ~10
minutes. The codex reader now uses a **bounded per-read idle timeout**
(`UC_CODEX_STREAM_IDLE_TIMEOUT`, default `150`s): a stall becomes a *retryable*
error, the empty-turn retry above re-attempts, and the workflow keeps moving.
Lower it for faster recovery; raise it if your effort level legitimately produces
long silent reasoning gaps before the first token.

### c. Rejected / partial tool calls don't 400 strict backends

OpenAI's format requires every assistant `tool_calls` message to be *immediately*
followed by exactly one `tool` message per `tool_call_id`. When you **reject** a
tool call, Claude Code puts your comment in the same turn as (or instead of) the
tool result — which made strict backends like **DeepSeek** reject the next request
with *"insufficient tool messages following tool_calls message"* ([#3][i3]). The
translator now tracks the open tool-call ids, emits the tool replies **first** (in
order), **synthesizes a stub reply** for any call you didn't answer (rejected or
skipped — including partial *parallel* calls), then appends your comment. So
rejecting a tool mid-run just works, on every backend.

[i3]: https://github.com/OnlyTerp/UltraCode-Shim/issues/3

### Reliability knobs

| Env var | Default | What it does |
|---------|---------|--------------|
| `UC_EMPTY_RETRY_ATTEMPTS` | `2` | How many times to re-issue an empty/transient turn. |
| `UC_EMPTY_RETRY_BACKOFF` | `0.75` | Seconds to wait between those retries. |
| `UC_CODEX_STREAM_IDLE_TIMEOUT` | `150` | Per-read idle cap (s) on the codex stream so a stall retries instead of hanging. |

All three are covered by the offline self-test (`test_proxy.py`) so they don't
regress.

## 6. What touches your machine

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
