# Recipe: Any provider (the general pattern)

Every recipe in this folder is the same three moves. Once you see the pattern,
you can wire up *any* model — cloud or local — without a dedicated recipe.

## The mental model

```
Claude Code  --(ANTHROPIC_BASE_URL)-->  proxy.py  -->  your provider
                                           |
                                           +-- adds ultracode envelope
                                           +-- rewrites the model id
                                           +-- (if openai_compat) translates
                                               Anthropic <-> OpenAI formats
```

You only ever edit **`config.json`**. It has three sections:

1. `proxy` — port + the real Anthropic upstream + the max_tokens floor. Defaults are fine.
2. `models` — one entry per thing you want to appear in Claude Code's `/model` menu.
3. `routes` — where each of those entries actually goes.

## The one rule that trips people up
**Every `models[].id` MUST start with `claude` or `anthropic`.** Claude Code's
gateway model discovery silently drops any id that doesn't. The `display_name`
is unrestricted — that's the label you actually read in the menu.

## Pick a route `type`

### `openai_compat` (almost everything)
Use this for OpenAI, OpenRouter, MIMO, Together, Groq, Fireworks, DeepSeek,
Ollama, LM Studio, llama.cpp, vLLM — anything with an OpenAI-style
`/v1/chat/completions`. The proxy translates request and response both ways.

```json
"routes": {
  "claude-anything": {
    "type": "openai_compat",
    "upstream": "https://api.PROVIDER.com",   // base URL, NO /v1
    "model": "the-real-model-name-at-provider",
    "auth": "Bearer YOUR_KEY"                  // or "x-api-key: KEY", or "passthrough"
  }
}
```

### `anthropic` (pass-through)
Use this only when the backend already speaks the Anthropic Messages API. The
request goes straight through (still wrapped in the ultracode envelope), no
format translation.

```json
"routes": {
  "claude-other-anthropic": {
    "type": "anthropic",
    "upstream": "https://some-anthropic-compatible-host",
    "model": "their-model-id",
    "auth": "passthrough"   // or a literal header
  }
}
```

## `auth` cheat sheet
| You have…                    | Put this in `auth`            |
|------------------------------|-------------------------------|
| A bearer/API key             | `"Bearer sk-..."`             |
| A custom header key          | `"x-api-key: ..."` (split on first `:`) |
| A local server (no auth)     | `"passthrough"`               |
| Want to reuse Claude's OAuth | `"passthrough"`               |

## Multiple models at once
List as many as you want — each `models[]` entry with a matching `routes{}` key
becomes its own `/model` option. Mix providers freely (one OpenAI, one local,
one OpenRouter) in the same `config.json`.

## Verify
```bash
./doctor.sh        # or ./doctor.ps1 on Windows
```
It checks JSON validity, id prefixes, missing routes, placeholder keys, proxy
reachability, and the Claude Code env vars. Fix anything it flags, restart with
`./start.sh` / `./start.ps1`, and pick your model with `/model`.

## A note on the "spinner that won't stop"
If a reply finishes but Claude Code keeps showing the thinking spinner — and the
next thing you type goes into a queue instead of being read — that's the stream
not being closed off cleanly at the end of a turn. The current `proxy.py` in
this kit closes the connection after the final event, which fixes it. If you're
on an older copy, update it. (Same row appears in the main
[README troubleshooting](../README.md#troubleshooting).)
