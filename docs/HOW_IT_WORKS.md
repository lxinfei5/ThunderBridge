# How it works

## The one surprising fact

Claude Code's **UltraCode** mode is not a separate model and does not send a
secret API field. Reverse-engineering the client shows that, at the
`api.anthropic.com` boundary, `--effort xhigh` and `{"ultracode": true}` produce
a **structurally identical** request. The only material thing UltraCode adds is an
injected system reminder. Modeled simply:

```
ultracode  =  output_config.effort = "xhigh"
            + thinking = {"type": "adaptive"}
            + max_tokens >= 64000
            + a "Ultracode is on: ..." system reminder
            + (client-side) the Workflow tool + standing opt-in
```

The Workflow tool, multi-agent runtime, and attachment lifecycle all live
**inside** the Claude Code client and fire regardless of which backend answers the
request. So if we make sure every request carries that envelope, *any* model gets
the UltraCode treatment.

(Evidence: captured request bodies for `xhigh` vs `ultracode:true` were identical;
the recovered `/effort` logic maps `ultracode → {value:"xhigh", ultracode:true}`;
the settings schema describes ultracode as "xhigh effort plus standing
dynamic-workflow orchestration … requires an xhigh-capable model.")

## The two jobs of the proxy

`gateway/ultracode_proxy.py` is a small standard-library HTTP server you point
`ANTHROPIC_BASE_URL` at. It does two things:

### 1. Make any model selectable (`GET /v1/models` discovery)

Claude Code has a built-in "gateway model discovery" feature. When
`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, `ANTHROPIC_BASE_URL` points away
from `api.anthropic.com`, and you're on a first-party (OAuth) login, the client
calls `GET <base_url>/v1/models`, keeps every id matching `/^(claude|anthropic)/i`,
and lists each one in `/model` using its `display_name`.

So the proxy serves `/v1/models` = the real Anthropic list **plus** your custom
models from `config/ultracode_models.json`. That's why your model **ids must start
with `claude` or `anthropic`** — otherwise the client filters them out before you
ever see them. The launcher also seeds Claude Code's
`<config>/cache/gateway-models.json` so your models appear on the very first open.

### 2. Add the envelope + route the pick (`POST /v1/messages`)

On every `/v1/messages` request the proxy:

1. Applies the UltraCode envelope (xhigh / adaptive / max_tokens floor / reminder).
2. Looks up the model id in `config/ultracode_slots.json` and routes it:
   - **passthrough** — forward to an Anthropic-compatible upstream, keeping the
     caller's credential (used for real Claude).
   - **openai_compat** — translate the Anthropic request to OpenAI Chat
     Completions, call the backend, and translate the streamed response back —
     **including tool calls** (Anthropic `tool_use`/`tool_result` ⇄ OpenAI
     `tool_calls`/`role:tool`). This is what lets MiMo/OpenRouter/etc. drive
     Claude Code's tools correctly.
   - **codex_oauth** — talk to the Codex Responses API using a `codex login`
     token (see `gateway/providers/codex_oauth.py`).

```
Claude Code ──▶ /v1/messages (model="claude-mimo")
              │  proxy: + xhigh/adaptive/64k/reminder
              │  slot "claude-mimo" → openai_compat → https://.../v1/chat/completions
              ▼
            MiMo  ──streamed tool_calls/text──▶ proxy ──Anthropic SSE──▶ Claude Code
```

## Why your normal Claude Code is safe

The launcher sets `ANTHROPIC_BASE_URL` and the discovery flag **only for the
process it spawns**, and passes a session-scoped `--settings` file containing
`{"ultracode": true}`. It does not edit your global `~/.claude` config or your
credentials. Close the UltraCode window (or use the "Claude Code (Normal)" icon)
and you're back to stock behavior.

## Files

| File | Role |
|------|------|
| `gateway/ultracode_proxy.py` | the interceptor (envelope + discovery + routing). Stdlib only. |
| `gateway/providers/codex_oauth.py` | optional GPT‑5.5-via-ChatGPT-login helper. Stdlib only. |
| `gateway/test_proxy.py` | offline end-to-end self-test (no network/keys). |
| `config/ultracode_models.json` | what appears in `/model`. |
| `config/ultracode_slots.json` | where each model id is routed. |
| `config/ultracode.env` | API keys (gitignored), referenced as `${VAR}`. |
| `windows/Start-UltraCode.ps1` / `bin/ultracode` | start proxy + launch Claude Code. |
