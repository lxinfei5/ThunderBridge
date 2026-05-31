# Runbook for AI assistants

You are helping a user set up **UltraCode-Shim**: it lets Claude Code's UltraCode
mode run on any model the user already pays for, chosen from the `/model` menu.

Follow these phases in order. Do not skip the doctor. Everything here is pure
Python standard library — **do not** `pip install` anything. Prefer the commands
exactly as written; they are cross-platform-aware.

## Phase 0 — Understand the goal (read once)

The end state: the user double-clicks **"UltraCode (All Models)"**, Claude Code
opens, they type `/model`, and they can pick any backend they configured. The
mechanism (no magic): a tiny loopback proxy (`gateway/ultracode_proxy.py`) sits at
`ANTHROPIC_BASE_URL`, advertises the user's models on `GET /v1/models` (so they
appear in the picker), adds the UltraCode envelope to every request, and routes
each pick to its real backend. See `docs/HOW_IT_WORKS.md`.

## Phase 1 — Prerequisites

Run and confirm each:

1. `python3 --version` (or `python --version`) → must be ≥ 3.8.
2. `claude --version` → Claude Code CLI must be installed. If missing:
   `npm i -g @anthropic-ai/claude-code`.
3. Confirm the user has UltraCode access in their Claude plan (they'd have used
   `/effort ultracode` before). If not, this project can't grant it.

## Phase 2 — Get the code + baseline check

1. Clone if not already: `git clone https://github.com/OnlyTerp/UltraCode-Shim.git`
2. From the repo root run the doctor:
   ```
   python3 scripts/doctor.py
   ```
   It runs an **offline self-test** (no network/keys) that proves the proxy,
   discovery, the UltraCode envelope, and tool-call translation all work. If the
   self-test fails, STOP and report the output — the install is broken, not the
   user's config.

## Phase 3 — Ask what they have, then configure

Ask the user which of these they have (only configure those):

- An **API key** for an OpenAI-compatible service (MiMo token, OpenRouter,
  OpenAI, Together, a local llama.cpp/Ollama server, etc.) → use `openai_compat`.
- A **ChatGPT/Codex login** for GPT‑5.5 → use `codex_oauth` (run `codex login`).
- Just **Claude** → they can still use it, routed as Anthropic passthrough (the
  default `claude-opus-4-8` slot). No savings, but UltraCode works.

Then edit two files (copy from the `.example` versions if they don't exist yet):

- `config/ultracode_models.json` — one entry per model to show in `/model`.
  **Every `id` MUST start with `claude` or `anthropic`** or Claude Code drops it.
- `config/ultracode_slots.json` — a route for each of those ids.
- `config/ultracode.env` — put API keys here; reference them as `${VAR}` in slots.
  This file is gitignored; never write a key directly into the JSON.

See `docs/ADD_A_MODEL.md` for exact templates per backend type.

Rules you must enforce:
- The `id` in models and the **key** in slots must be identical.
- For `openai_compat`, `model` is the backend's real model id (not the `claude-…` alias).
- Keys go in `ultracode.env` as `${NAME}`, never inline.

## Phase 4 — Validate the real config

Run the doctor again:
```
python3 scripts/doctor.py
```
Now it validates the user's actual config: ids are discoverable+routed, every
`${VAR}` referenced by an `openai_compat` slot is present, and `codex_oauth` slots
have a `codex login`. Fix every `[FAIL]` (each prints its fix) until exit code 0.

## Phase 5 — Install icons / launch

- **Windows:** `./windows/Install-DesktopIcons.ps1` (creates "UltraCode (All Models)"
  and "Claude Code (Normal)"). Or launch directly: `./windows/Start-UltraCode.ps1`.
- **macOS/Linux/WSL:** `./bin/ultracode`.

## Phase 6 — Verify end to end

1. Launch UltraCode. In Claude Code, type `/model` and confirm the user's custom
   models appear (they may show on the first open or a moment later — the proxy
   serves them on `GET /v1/models`).
2. Pick one and send a trivial prompt ("say OK"). Confirm a reply.
3. Pick one that needs tools and ask something requiring a tool call; confirm tools
   fire (the proxy translates tool calls both ways).

If a model doesn't appear or errors, go to `docs/TROUBLESHOOTING.md` and match the
symptom. Common ones:
- Model missing from `/model` → id didn't start with `claude`/`anthropic`, or
  discovery env not set (the launcher sets `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`).
- "responded but never called tools" → that slot must be `openai_compat` (not
  passthrough) so tools are translated.
- 401/empty from a backend → wrong/empty key in `ultracode.env`, or expired
  `codex login`.

## Hard rules

- Never commit `config/ultracode.env`, `config/ultracode_slots.json`, or
  `config/ultracode_models.json` (they're gitignored; they hold user choices/keys).
- Never put an API key directly in a `.json`; always `${VAR}` + `ultracode.env`.
- Don't modify the user's global `~/.claude` config; this tool is session-scoped.
- If the offline self-test (`python3 gateway/test_proxy.py`) fails, the problem is
  the code/clone, not the user — report it, don't paper over it.
