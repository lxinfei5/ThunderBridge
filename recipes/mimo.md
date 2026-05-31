# Recipe: MIMO (or any branded OpenAI-compatible API)

This recipe covers MIMO specifically, and stands in for **any** provider that
gives you an OpenAI-style `/v1/chat/completions` endpoint and a bearer key.

## 1. Gather two things from your provider
1. The **base URL** of their API (everything before `/v1/...`).
   - e.g. `https://api.mimo.example`  → use that, with **no** `/v1`.
2. Your **API key** and the exact **model name** they expect.

## 2. Edit `config.json`

```json
{
  "proxy": { "listen_port": 8141, "anthropic_upstream": "https://api.anthropic.com", "max_tokens_floor": 64000 },
  "models": [
    { "id": "claude-mimo-pro", "display_name": "MIMO V2.5 PRO" }
  ],
  "routes": {
    "claude-mimo-pro": {
      "type": "openai_compat",
      "upstream": "https://api.mimo.example",
      "model": "mimo-2.5-pro",
      "auth": "Bearer mimo-YOUR_KEY_HERE"
    }
  }
}
```

### Auth header variations
Most providers use `Authorization: Bearer <key>`. If yours uses a custom header
instead, put `header-name: value` in `auth` (the proxy splits on the first `:`):

```json
"auth": "x-api-key: mimo-YOUR_KEY_HERE"
```

## 3. Start & use
```bash
./start.sh        # or ./start.ps1 on Windows
```
`/model` in Claude Code → pick **MIMO V2.5 PRO**.

## Troubleshooting
- Run `./doctor.sh` / `./doctor.ps1`.
- `404 Not Found` from the proxy log → your `upstream` probably already included `/v1`. Remove it; the proxy adds `/v1/chat/completions`.
- `401` → wrong key or wrong auth header style (try the `x-api-key:` form above).
- Streaming looks chunky/odd → some providers stream non-standard SSE; the proxy falls back to a single-shot stream automatically, so output still arrives.
- Answer arrives but the **spinner keeps spinning** and your next message **queues** → update to the current `proxy.py`; it now closes the stream cleanly after the final event so Claude Code ends the turn. (Full row in the main [README troubleshooting](../README.md#troubleshooting).)
