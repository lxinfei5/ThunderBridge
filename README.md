# Ultracode Unlock — give Claude Code's best mode to *any* model

Claude Code has a hidden top-tier mode called **ultracode** (xhigh effort +
adaptive thinking + the multi-agent Workflow tool). Out of the box it only turns
on for `claude-opus-4-8` / `claude-opus-4-7`. This kit lets you run **that same
mode while the actual answers come from a different model you already pay for** —
your GPT/Codex plan, a MIMO plan, a local model, OpenRouter, anything that speaks
the OpenAI chat API.

> **How it works in one sentence:** a tiny local proxy sits between Claude Code
> and Anthropic, forces the "ultracode" request shape on every call, and reroutes
> the models *you* choose to *your* backend — Claude Code never knows the
> difference, and **nothing about `claude.exe` is modified.**

This is a **shim**. You keep using the normal `claude` CLI; you just launch it
through one script.

---

## 🤖 The lazy path: let your AI set it up

You don't have to read any of this. If you have an AI coding assistant — **Claude
Code, Cursor, Cline, Aider, a ChatGPT agent**, anything that can read a repo and
run commands — just tell it:

> **"Set this repo up for me. I want to use \<your model/plan\> in Claude Code's
> ultracode mode. Read AGENTS.md and follow it."**

This repo ships an [`AGENTS.md`](AGENTS.md) — a deterministic runbook written
*for the AI*. Your assistant will check your prerequisites, ask only for your
backend choice and API key, write your `config.json`, run the doctor, start the
proxy, and confirm it works. The rest of this README is the human version of the
same steps, if you'd rather do it yourself.

---

## ⚡ 60-second start (the brainless path)

You need three things first (the **doctor** script checks all of them for you):

1. **Claude Code** installed and logged in (`claude` works in your terminal).
2. **Python 3.8+** (`python3 --version`).
3. **One backend** that speaks the OpenAI `/v1/chat/completions` API — see
   [Pick your backend](#pick-your-backend) below. If you don't have one yet,
   start with the [Provider recipes](recipes/).

Then:

### Windows (PowerShell)

```powershell
cd ultracode-unlock
.\doctor.ps1          # tells you exactly what (if anything) is missing
.\start.ps1           # starts the proxy + launches Claude Code through it
```

### macOS / Linux

```bash
cd ultracode-unlock
chmod +x doctor.sh start.sh
./doctor.sh           # tells you exactly what (if anything) is missing
./start.sh            # starts the proxy + launches Claude Code through it
```

Inside Claude Code, type **`/model`**. You'll see your custom models listed by
their real names. Pick one — Claude Code now runs in ultracode mode, answered by
your model. Done.

If anything looks wrong, **run the doctor script again** — it prints a fix for
every red ✗. See [Troubleshooting](#troubleshooting).

---

## What you actually get

| You select in `/model` | Claude Code thinks it's | Really answered by |
|---|---|---|
| `Opus 4.8` (default) | Opus 4.8 | Real Anthropic Opus (untouched) |
| your custom model #1 | a "claude-…" gateway model | **your backend** (e.g. GPT-5.5 Codex) |
| your custom model #2 | a "claude-…" gateway model | **your backend** (e.g. MIMO) |

Every one of them runs with the full ultracode envelope: `xhigh` effort, adaptive
thinking, 64k output ceiling, the Workflow multi-agent tool, and the ultracode
system reminder. The reverse-engineering that proves this is in
[`THEORY.md`](THEORY.md).

---

## Pick your backend

You only need **one**. The kit ships ready-to-copy recipes:

| Your plan / backend | Recipe |
|---|---|
| **OpenAI / ChatGPT / Codex** (GPT-5.5, gpt-4o, o-series) | [`recipes/openai.md`](recipes/openai.md) |
| **MIMO** plan | [`recipes/mimo.md`](recipes/mimo.md) |
| **OpenRouter** (one key, hundreds of models) | [`recipes/openrouter.md`](recipes/openrouter.md) |
| **Local** (Ollama / LM Studio / llama.cpp) | [`recipes/local.md`](recipes/local.md) |
| **Anything else** that speaks OpenAI chat API | [`recipes/any-provider.md`](recipes/any-provider.md) |

Each recipe is: *copy two small blocks into `config.json`, run `doctor`, run
`start`.* That's the whole job.

---

## Configure it (one file: `config.json`)

Copy the template and edit it. **You never touch the Python or the launcher.**

```bash
cp config.example.json config.json
```

`config.json` has two lists:

- **`models`** — what shows up in the `/model` picker (id + the label you want
  to see).
- **`routes`** — where each of those ids actually goes (your backend URL, the
  real model name there, and how to authenticate).

A complete two-model example (GPT plan + MIMO plan):

```jsonc
{
  "models": [
    { "id": "claude-gpt-5.5",  "display_name": "GPT-5.5 (my OpenAI plan)" },
    { "id": "claude-mimo-pro", "display_name": "MIMO V2.5 PRO" }
  ],
  "routes": {
    "claude-gpt-5.5": {
      "type": "openai_compat",
      "upstream": "https://api.openai.com",
      "model": "gpt-5.5",
      "auth": "Bearer sk-REPLACE_ME"
    },
    "claude-mimo-pro": {
      "type": "openai_compat",
      "upstream": "https://api.mimo.example",
      "model": "mimo-2.5-pro",
      "auth": "Bearer mimo-REPLACE_ME"
    }
  }
}
```

**The one rule you must follow:** every `id` in `models`/`routes` **must start
with `claude` or `anthropic`.** That's a filter inside Claude Code — ids that
don't start that way get silently dropped from the picker. The `display_name` can
be anything you like; that's what you actually see.

Full field reference is in [`config.example.json`](config.example.json) (it's
commented).

---

## Troubleshooting

**First move, always:** run `./doctor.sh` (or `.\doctor.ps1`). It checks Claude
Code, Python, the port, the proxy health, and whether your custom models are
being advertised — and prints the exact fix for each failure. 90% of "it doesn't
work" is one of these:

| Symptom | Likely cause | Fix |
|---|---|---|
| My model isn't in `/model` | id doesn't start with `claude`/`anthropic`, **or** gateway discovery is off | Rename the id; the launcher sets the discovery flag for you — relaunch via `start` |
| Picker shows it but selecting it errors | backend URL/model/auth wrong | `doctor` does a live test call and prints the backend's error verbatim |
| `Proxy did not become healthy` | port 8141 already in use, or Python missing | `doctor` finds a free port and the wrong-python case |
| Selecting my model still answers like Opus | you launched plain `claude`, not through `start` | Always launch with `start.ps1` / `start.sh` |
| Answer arrives but the **thinking spinner keeps spinning**, and your **next message goes into a queue** instead of being read | the streaming reply wasn't being closed off cleanly, so Claude Code thought the turn was still open | **Fixed in this version** — the proxy now closes the stream after the final event. If you patched an older copy of `proxy.py`, update to the current one (or ensure it sends `Connection: close` and closes the socket after the last SSE event) |
| Replies cut off mid-answer / mid-tool-call | your backend's max output tokens too low | raise it on the provider side (see your recipe's "token limit" note) |
| Works in terminal, fails from another app | (advanced) loopback proxying flapped | restart the proxy; see [`THEORY.md`](THEORY.md#loopback-notes) |

Still stuck? Open an issue with the **full output of `doctor`** (it's safe to
share — it redacts your keys) and your `config.json` **with the `auth` values
removed**.

---

## Safety & rollback

- **Non-destructive.** Nothing in `claude.exe` is patched. The proxy only
  rewrites request fields and forwards bytes; on any parse error it forwards the
  original request unchanged.
- **Your keys stay local.** `config.json` lives on your machine and is
  gitignored by this kit. The proxy talks straight to your backend.
- **To turn it off:** just launch plain `claude` again (don't use `start`). To
  remove it entirely, delete the `ultracode-unlock` folder. There's nothing else
  to clean up.

---

## Files in this kit

```text
ultracode-unlock/
├── README.md              ← you are here
├── AGENTS.md              ← runbook for an AI assistant ("set this up for me")
├── THEORY.md              ← the reverse-engineering: what ultracode really is
├── config.example.json    ← copy to config.json and edit (commented)
├── start.ps1 / start.sh   ← one command: proxy up + launch Claude through it
├── doctor.ps1 / doctor.sh ← diagnose everything, print exact fixes
├── proxy.py               ← the interceptor (stdlib only, no pip installs)
└── recipes/
    ├── openai.md          ← GPT / ChatGPT / Codex plan
    ├── mimo.md            ← MIMO plan
    ├── openrouter.md      ← OpenRouter
    ├── local.md           ← Ollama / LM Studio / llama.cpp
    └── any-provider.md    ← the general pattern for ANY OpenAI-compatible backend
```

---

*This kit is reverse-engineering for interoperability and personal use. It does
not modify Claude Code and does not bypass authentication — you still log in
normally. Respect the terms of every provider whose model you route to.*
