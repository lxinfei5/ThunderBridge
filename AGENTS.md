# Runbook for AI assistants

You are helping a user set up **UltraCode-Shim**: it lets Claude Code's UltraCode
mode run on any model the user already pays for, chosen from the pre-launch
orchestrator/worker selector or from the `/model` menu.

Follow these phases in order. Do not skip the doctor. Everything here is pure
Python standard library — **do not** `pip install` anything. Prefer the commands
exactly as written; they are cross-platform-aware.

## Phase 0 — Understand the goal (read once)

The end state: the user double-clicks **"UltraCode (All Models)"**, picks an
orchestrator + worker in the selector, and Claude Code opens already pointed at
that choice. They can still type `/model` later and pick any backend they
configured. The mechanism (no magic): a tiny loopback proxy (`proxy.py`) sits at
`ANTHROPIC_BASE_URL`, advertises the user's models plus synthesized `Worker → X`
entries on `GET /v1/models`, adds the UltraCode envelope to every request, and
routes each pick to its real backend. See `docs/HOW_IT_WORKS.md`.

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

- An **API key** for an OpenAI-compatible service (MiniMax‑M3, MiMo, DeepSeek,
  OpenRouter, OpenAI, Ollama, a local llama.cpp/LM Studio server, etc.) → use
  `openai_compat`.
- A **ChatGPT/Codex login** for GPT‑5.5 → use `codex_oauth` (run `codex login`).
- Just **Claude** → they can still use it, routed as Anthropic passthrough. No
  savings, but UltraCode works.

Then edit **one file**: copy `config.example.json` → `config.json` (the launcher
also does this on first run), and edit `config.json`:

- `models` — one entry per model to show in `/model`. **Every `id` MUST start
  with `claude` or `anthropic`** or Claude Code drops it.
- `routes` — a route for each of those ids (the key must equal the `id`).
- Keys go inline (config.json is gitignored) or as `${VAR}` (export it, or use a
  gitignored `ultracode.env` in the repo root that the launchers load).

See `docs/ADD_A_MODEL.md` for exact templates per backend type.

Rules you must enforce:
- The `id` in `models` and the **key** in `routes` must be identical.
- For `openai_compat`, `model` is the backend's real model id (not the `claude-…` alias).
- For `openai_compat`, `upstream` is the provider's base URL (usually ends in
  `/v1`); the proxy appends `/chat/completions`.
- **Reasoning models that inline `<think>` (e.g. MiniMax‑M3):** add
  `"body": { "reasoning_split": true }` to the route so the chain‑of‑thought is
  split out of the visible answer. The shipped example already does this for
  `claude-minimax-m3`. The `body` dict is the general way to pass any
  provider‑specific request param.

## Phase 4 — Validate the real config

Run the doctor again:
```
python3 scripts/doctor.py
```
Now it validates the user's actual `config.json`: ids are discoverable+routed,
every `${VAR}` referenced by a route is present (or the key is inline), and
`codex_oauth`/`cursor_agent` routes have their login/CLI. Fix every `[FAIL]`
(each prints its fix) until exit code 0.

## Phase 5 — Install icons / launch

- **Windows:** `./windows/Install-DesktopIcons.ps1` (creates "UltraCode (All Models)"
  and "Claude Code (Normal)"). Or launch directly: `./windows/Start-UltraCode.ps1`.
- **macOS/Linux/WSL:** `./bin/ultracode`.

The launcher starts the proxy, seeds Claude Code's gateway-models cache from the
live proxy (including synthesized `Worker → X` entries), opens the two-column
selector, then passes the selected orchestrator as `claude --model ...`. Set
`UC_SELECTOR=0` to skip the selector and choose from `/model` only.

## Phase 6 — Verify end to end

1. Launch UltraCode. Confirm the selector appears and can pick an orchestrator +
   worker (`Same as orchestrator` means one model runs everything).
2. In Claude Code, type `/model` and confirm the user's custom models and
   `Worker → X` entries appear (the proxy serves them on `GET /v1/models`).
3. Send a trivial prompt ("say OK"). Confirm a reply uses the selected model.
4. Pick one that needs tools and ask something requiring a tool call; confirm tools
   fire (the proxy translates tool calls both ways).

If a model doesn't appear or errors, go to `docs/TROUBLESHOOTING.md` and match the
symptom. Common ones:
- Model missing from `/model` → id didn't start with `claude`/`anthropic`, or
  discovery env not set (the launcher sets `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`).
- "responded but never called tools" → that route must be `openai_compat` (not
  passthrough) so tools are translated.
- 401/empty from a backend → wrong/empty key in `config.json`, or expired
  `codex login`.

## Hard rules

- Never commit `config.json` or `ultracode.env` (they're gitignored; they hold
  the user's choices/keys).
- An API key may go inline in `config.json` (gitignored) or as `${VAR}`; never
  commit a real key.
- Don't modify the user's global `~/.claude` config; this tool is session-scoped.
- If the offline self-test (`python3 test_proxy.py`) fails, the problem is the
  code/clone, not the user — report it, don't paper over it.
