# Add a model

Adding a backend to the `/model` menu is always the same three edits:

1. Add an entry to `config/ultracode_models.json` (what shows in the picker).
2. Add a matching route to `config/ultracode_slots.json` (where it goes).
3. If it uses an API key, add the key to `config/ultracode.env` and reference it
   as `${VAR}` in the slot.

Then re-run `python scripts/doctor.py` and relaunch.

> **The golden rule:** the model `id` **must start with `claude` or `anthropic`**,
> and the `id` in `ultracode_models.json` must exactly equal the **key** in
> `ultracode_slots.json`. Otherwise the model won't show up or won't route.

---

## Pattern A — any OpenAI-compatible API (most models)

Covers MiMo, OpenRouter, OpenAI, Together, Groq, DeepInfra, a local
llama.cpp/Ollama server — anything exposing `POST /v1/chat/completions`. Tool
calls are translated automatically.

`ultracode_models.json`
```json
{ "id": "claude-mymodel", "display_name": "My Model (OpenRouter)" }
```

`ultracode_slots.json`
```json
"claude-mymodel": {
  "type": "openai_compat",
  "model": "vendor/the-real-model-id",
  "upstream": "https://openrouter.ai/api/v1",
  "auth": "Bearer ${OPENROUTER_API_KEY}"
}
```

`ultracode.env`
```
OPENROUTER_API_KEY=sk-or-...
```

Notes:
- `model` is the backend's real model id, **not** the `claude-…` alias.
- `upstream` is the OpenAI base URL **as the provider documents it** (it usually
  ends in `/v1`); the proxy appends `/chat/completions`. Don't add `/chat/completions` yourself.
- Some backends use a header instead of Bearer — use `"auth": "x-api-key: ${MY_KEY}"`.
- Some gateways need a specific header (e.g. a `User-Agent`); add
  `"headers": { "User-Agent": "..." }` to the slot.
- Output length defaults to a safe 8192 tokens. If your backend allows more (or
  rejects that), add `"max_output_tokens": 16384` (or lower) to the slot.
- Local server example: `"upstream": "http://127.0.0.1:11434/v1", "auth": "Bearer ${LOCAL_API_KEY}"`
  (Ollama/llama.cpp ignore the key; any value works).

## Pattern B — GPT‑5.5 via ChatGPT/Codex login (no API key)

`ultracode_models.json`
```json
{ "id": "claude-gpt-5.5-codex", "display_name": "GPT-5.5 (Codex OAuth)" }
```

`ultracode_slots.json`
```json
"claude-gpt-5.5-codex": { "type": "codex_oauth", "model": "gpt-5.5" }
```

Then run `codex login` once. Optional env knobs (set in `ultracode.env`):
`UC_CODEX_EFFORT=high`, `UC_CODEX_SERVICE_TIER=priority`.

## Pattern C — real Claude / any Anthropic-compatible endpoint

Omit `type` for passthrough (keeps Claude Code's own login):

```json
"claude-opus-4-8": {
  "model": "claude-opus-4-8",
  "upstream": "https://api.anthropic.com",
  "auth": "passthrough"
}
```

---

## Popular backends (already in the example config)

The shipped `config/*.example.json` includes ready-to-use entries — keep the ones
you have a plan for and delete the rest. Endpoints/model ids were accurate at time
of writing; check the provider's docs if something 404s.

| Picker label | id | `type` | `upstream` | `model` | key in `ultracode.env` |
|---|---|---|---|---|---|
| GPT‑5.5 (Codex OAuth) | `claude-gpt-5.5-codex` | `codex_oauth` | — | `gpt-5.5` | none (`codex login`) |
| MiMo v2.5 Pro | `claude-mimo` | `openai_compat` | `https://token-plan-sgp.xiaomimimo.com/v1` | `mimo-v2.5-pro` | `MIMO_API_KEY` |
| DeepSeek V4 Pro | `claude-deepseek-v4-pro` | `openai_compat` | `https://api.deepseek.com/v1` | `deepseek-v4-pro` | `DEEPSEEK_API_KEY` |
| DeepSeek V4 Flash | `claude-deepseek-v4-flash` | `openai_compat` | `https://api.deepseek.com/v1` | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` |
| Step Flash | `claude-step-flash` | `openai_compat` | `https://api.stepfun.ai/v1` | `step-3.5-flash` | `STEPFUN_API_KEY` |
| Ollama Cloud | `claude-ollama-cloud` | `openai_compat` | `https://ollama.com/v1` | `gpt-oss:120b` (or any cloud model) | `OLLAMA_API_KEY` |
| OpenCode Go | `claude-opencode` | *(passthrough)* | `https://opencode.ai/zen/go` | the id your plan exposes | `OPENCODE_API_KEY` |
| OpenRouter | `claude-openrouter` | `openai_compat` | `https://openrouter.ai/api/v1` | any OpenRouter slug | `OPENROUTER_API_KEY` |
| Local | `claude-local` | `openai_compat` | `http://127.0.0.1:11434/v1` | your local model | `LOCAL_API_KEY` |

OpenCode Go is Anthropic-native, so it's a **passthrough** slot with a
`User-Agent` header; set `model` to whatever id your OpenCode plan exposes.

## Composer 2.5 Fast (Cursor) — advanced / not plug-and-play

Cursor's Composer is **not** an OpenAI/Anthropic HTTP API — it's driven by the
`cursor-agent` CLI. Routing Claude Code's tool-using harness through it needs a
subprocess bridge (translating `cursor-agent`'s stream to tool calls), which this
repo does **not** ship yet. It's on the roadmap; if you want it, open an issue.
Everything HTTP-based (the table above) works today.

## Field reference

| Field | Meaning |
|-------|---------|
| `type` | omit = Anthropic passthrough · `openai_compat` · `codex_oauth` |
| `model` | the id sent to the backend |
| `upstream` | backend base URL (ignored for `codex_oauth`) |
| `auth` | `passthrough`, or `Bearer ${VAR}` / `x-api-key: ${VAR}` |
| `max_output_tokens` | optional (`openai_compat`); completion cap sent to backend (default 8192) |
| `label` | human note only; never sent |

After editing, validate with `python scripts/doctor.py` — it checks that every
advertised id is routed and that every `${VAR}` you referenced is set.
