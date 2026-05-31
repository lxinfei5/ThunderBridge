# THEORY — what "ultracode" actually is, and why this shim works

You don't need to read this to use the kit. Read it if you want to understand
*why* it works, trust that it's safe, or adapt it.

This is condensed from a full reverse-engineering of the live Claude Code
binary (`claude.exe`, v2.1.15x, Bun-compiled). The long version, with recovered
code and loopback request captures, is in the sibling `ultracode-re/` folder.

---

## 1. Ultracode is not a model. It's a request shape + a prompt.

When you turn on **ultracode** in Claude Code, nothing exotic gets sent to
Anthropic. At the `api.anthropic.com` boundary, ultracode is **identical** to
plain `xhigh` effort. The captured request body is just:

```json
{
  "model": "claude-opus-4-8",
  "max_tokens": 64000,
  "thinking": { "type": "adaptive" },
  "context_management": { "edits": [{ "type": "clear_thinking_20251015", "keep": "all" }] },
  "output_config": { "effort": "xhigh" },
  "stream": true
}
```

There is **no API field called `ultracode`.** The only thing that makes
ultracode behave differently from plain `xhigh` is a **system reminder** Claude
Code injects into the prompt:

> *Ultracode is on: optimize for the most exhaustive, correct answer — not the
> fastest or cheapest. Use the Workflow tool on every substantive task; token
> cost is not a constraint…*

…plus the **Workflow tool** (multi-agent orchestration) being treated as a
"standing opt-in" while that reminder is present. Both of those live **inside
`claude.exe`** and fire no matter which backend actually answers the request.

**That's the whole trick.** If we can (a) make Claude Code *turn ultracode on*
and (b) make sure every outgoing request carries that envelope, then the model
that actually answers can be anything — it just receives an `xhigh`-shaped
request and an extra system message. So we put a tiny proxy in the middle.

---

## 2. The two gates inside Claude Code

To get ultracode active for a non-Opus model, two checks inside `claude.exe`
have to pass. We satisfy both **without patching the binary**.

### Gate A — the Workflow gate

Ultracode refuses to enable unless "dynamic workflows" are available. The
recovered logic keys off an environment variable:

```
CLAUDE_CODE_WORKFLOWS=1   →  workflows available + default-on
```

`start.ps1` / `start.sh` set this for you.

### Gate B — the "xhigh-capable model" gate (`kcH`)

Recovered (minified, paraphrased):

```js
function kcH(model) {
  // explicit per-model override wins, if present
  // deny-list: claude-3-*, opus-4-0..4-6, sonnet-4-*, haiku-4-5  → false
  if (id === "claude-opus-4-8" || id === "claude-opus-4-7") return true   // allow-list
  return modelDeclaresXhigh(model)                                        // capability route
}
```

The simplest way past it: **keep the id Claude Code thinks it's using on the
allow-list** (`claude-opus-4-8`), and let the proxy rewrite the model on the way
out. Claude Code believes it's talking to Opus; your backend receives `gpt-5.5`
(or whatever). The capability gate only decides whether the *harness* turns
ultracode ON — once on, the outgoing request is ordinary `xhigh`, and the proxy
handles the rest.

---

## 3. How your custom models show up in `/model` (gateway discovery)

Newer Claude Code (2.1.156+) has a real **gateway model discovery** path. Three
recovered functions drive it:

| Function | What it does |
|---|---|
| `gk4()` | **Gate.** Enables discovery when `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, you're on first-party OAuth, **and** `ANTHROPIC_BASE_URL` ≠ `api.anthropic.com` (i.e. you're pointed at our proxy). All true under this kit. |
| `nk4()` | **Fetch.** GETs `<base_url>/v1/models?limit=1000`, keeps only ids matching `/^(claude\|anthropic)/i`, and writes them to `cache/gateway-models.json`. |
| `lk4()` | **Render.** Reads that cache and lists each model in the `/model` picker with **`label = display_name`**. |

So our proxy answers `GET /v1/models` with the real Anthropic list **plus** your
custom models (from `config.json`), and Claude Code lists them by their real
display names. The launcher also pre-seeds `gateway-models.json` so they show on
the *first* launch (Claude Code refreshes it itself afterward).

**This is why every custom id must start with `claude` or `anthropic`** — ids
that don't match `nk4()`'s filter are silently dropped. The `display_name` has
no such restriction, so the label you see can be anything.

---

## 4. What the proxy does to each request

`proxy.py` is stdlib-only (no `pip install`). On every `POST /v1/messages` it:

1. **Routes the model.** If the incoming `model` matches a route in your
   `config.json`, it rewrites the model id and (for `openai_compat` routes)
   redirects to your backend, translating Anthropic↔OpenAI both ways.
2. **Forces the ultracode envelope:** `output_config.effort=xhigh`,
   `thinking.type=adaptive`, `max_tokens ≥ 64000`.
3. **Injects the ultracode system reminder** if it isn't already there
   (idempotent — it won't double-inject).
4. **Passes auth through** untouched for Anthropic routes (your OAuth keeps
   working); for `openai_compat` routes it sends your configured `auth` header.

On any JSON parse failure it forwards the original bytes unchanged, so it can
never corrupt a request.

---

## 5. The full picture

```text
  Claude Code (claude.exe)             proxy.py  (127.0.0.1:8141)        backends
  ─────────────────────────           ────────────────────────         ─────────
  ultracode ON                                                          
  /model shows your models   ──GET /v1/models──►  real list + your models
                                                                         
  you pick "GPT-5.5"                                                     
  sends model=claude-gpt-5.5 ──POST /v1/messages─►  route matched:       
                                                    • effort=xhigh        
                                                    • thinking=adaptive   
                                                    • +ultracode reminder  
                                                    • model→gpt-5.5        
                                                    • Anthropic→OpenAI ──► api.openai.com
                                                                         
  you pick "Opus 4.8"        ──POST /v1/messages─►  envelope forced ────► api.anthropic.com
```

The harness-side half of ultracode — the Workflow multi-agent tool, the
attachment lifecycle (`ultra_effort_enter` / sparse / exit reminders), the
quality patterns — all runs inside `claude.exe` regardless of which backend
answered. So your routed model gets the *whole* ultracode experience.

---

## 6. Honest caveats

- **Tool-calling fidelity.** The `openai_compat` translator bridges chat text
  and summarizes tool blocks. It's a solid chat/agent bridge, not a 1:1
  tool-calling spec translation. Backends with native OpenAI tool-calling work
  best; exotic tool schemas may degrade to text.
- **Your backend must accept the request.** If it chokes on unknown fields,
  most OpenAI-compatible servers simply ignore `output_config`/`thinking`. If
  yours doesn't, see `recipes/any-provider.md`.
- **Output token limits.** Replies that cut off mid-answer almost always mean
  your *backend's* max-output-tokens is set too low — raise it there, not here.
  (We saw this exact failure with a provider defaulting to 8192.)

<a name="loopback-notes"></a>
- **Loopback quirks (advanced).** If you run the proxy inside WSL while Claude
  Code runs on Windows, WSL2's mirrored-loopback can occasionally stall. Run the
  proxy on the **same** OS as Claude Code (what this kit does by default) and you
  won't hit it.

---

*Full recovered code, request captures, and confidence tables:
see the `ultracode-re/` folder.*
