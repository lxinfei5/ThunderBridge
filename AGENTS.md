# AGENTS.md — instructions for an AI assistant setting this up

**If you are an AI agent** (Claude Code, Cursor, Cline, Aider, a ChatGPT agent,
or similar) and your human pointed you at this repo and said *"set this up for
me so I can use any model in Claude Code's ultracode mode"* — this file is your
runbook. Follow it top to bottom. It is deterministic; you should not need to
ask the human anything except their backend choice and API key.

> **What this repo does (one line):** it installs a tiny local proxy that gives
> Claude Code's top-tier *ultracode* request shape (xhigh effort + adaptive
> thinking + 64k output + the Workflow tool) to **any** model your human already
> pays for, and adds those models to Claude Code's `/model` picker. Nothing in
> `claude.exe` is modified.

---

## 0. Preconditions — verify these first

Run these checks. If one fails, tell the human exactly which and stop.

```bash
claude --version        # Claude Code must be installed and logged in
python3 --version       # need Python 3.8+  (on Windows: `python --version` or `py --version`)
```

The proxy is **Python stdlib only** — there is nothing to `pip install`.

---

## 1. Find out what backend the human wants

Ask **one** question: *"Which model/plan do you want to route to, and what's the
API key?"* Map their answer to a recipe in [`recipes/`](recipes/):

| If the human says…                              | Use recipe                |
|-------------------------------------------------|---------------------------|
| OpenAI / ChatGPT / Codex / GPT-5.5 / gpt-4o / o-series | [`recipes/openai.md`](recipes/openai.md) |
| MIMO                                            | [`recipes/mimo.md`](recipes/mimo.md) |
| OpenRouter                                      | [`recipes/openrouter.md`](recipes/openrouter.md) |
| Ollama / LM Studio / llama.cpp / "local"        | [`recipes/local.md`](recipes/local.md) |
| anything else with an OpenAI-style API          | [`recipes/any-provider.md`](recipes/any-provider.md) |

Read the chosen recipe. It tells you the exact `upstream`, `model`, and `auth`
values for that provider.

---

## 2. Create `config.json` (the ONLY file you edit)

Copy the template and fill it in from the recipe + the human's key. **Do not**
edit `proxy.py`, the launchers, or the doctor scripts.

```bash
cp config.example.json config.json
```

Then write `config.json` with two lists — `models` (what shows in `/model`) and
`routes` (where each goes). Minimal one-model example (OpenAI):

```json
{
  "models": [
    { "id": "claude-gpt-5.5", "display_name": "GPT-5.5 (my plan)" }
  ],
  "routes": {
    "claude-gpt-5.5": {
      "type": "openai_compat",
      "upstream": "https://api.openai.com",
      "model": "gpt-5.5",
      "auth": "Bearer sk-THE-HUMANS-KEY"
    }
  }
}
```

### The one hard rule — do not get this wrong
**Every `id` in `models`/`routes` MUST start with `claude` or `anthropic`.**
Claude Code's gateway model discovery silently drops any id that doesn't, so the
model would never appear in the picker. The `display_name` has no restriction —
make it the human-readable label.

`upstream` is the base URL with **no** `/v1` suffix; the proxy appends the right
path itself. `type` is `openai_compat` for any OpenAI-chat backend, or
`anthropic` for a backend that already speaks the Anthropic Messages API.

---

## 3. Validate before launching

Run the doctor. It checks Python, JSON validity, the id-prefix rule, missing
routes, placeholder keys, port reachability, and the Claude Code env vars — and
prints an exact fix for every failure. **Resolve every `[FAIL]` before
continuing.**

```bash
./doctor.sh        # macOS/Linux
.\doctor.ps1       # Windows PowerShell
```

---

## 4. Start it

```bash
./start.sh         # macOS/Linux
.\start.ps1        # Windows PowerShell
```

This launches the proxy on `127.0.0.1:8141`, sets `ANTHROPIC_BASE_URL` and
`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, and starts `claude` in the same
shell so it inherits those env vars. **Claude Code must be launched through this
script** — a plain `claude` won't have the proxy wired in.

---

## 5. Confirm success, then hand back to the human

1. Hit the health endpoint and confirm the custom models are advertised:
   ```bash
   curl -s http://127.0.0.1:8141/healthz
   ```
   The JSON `custom_models` array should list the id(s) from `config.json`.
2. Tell the human: *"Open `/model` in Claude Code and pick **<display_name>**.
   You're now in ultracode mode, answered by your model."*

If the model is selectable but answering fails, the doctor's live test call
prints the backend's verbatim error — relay that to the human (usually a wrong
key or model name).

---

## Hard rules for you, the agent

- **Never** edit `proxy.py`, `start.*`, or `doctor.*`. The only file a setup
  touches is `config.json`.
- **Never** commit or print the human's API key. `config.json` is gitignored by
  this repo for that reason.
- **Never** claim it works without running step 5's health check.
- If the human is on Windows with the proxy in WSL, run the proxy on the **same**
  OS as Claude Code instead (see [`THEORY.md`](THEORY.md#loopback-notes)).
- This kit does **not** patch Claude Code and does **not** bypass login — the
  human still authenticates Claude Code normally. It only changes which backend
  answers and adds models to the picker.

---

## Where to read more
- [`README.md`](README.md) — the human-facing guide.
- [`THEORY.md`](THEORY.md) — what ultracode is and why this works (optional).
- [`recipes/`](recipes/) — per-provider exact values.
