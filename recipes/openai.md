# Recipe: OpenAI (GPT-5.5 / GPT-4o / o-series)

Route Claude Code at OpenAI models through your own OpenAI API key.

## 1. Get an API key
- Go to https://platform.openai.com/api-keys and create a key (`sk-...`).
- Make sure your account/org has access to the model you want (e.g. `gpt-5.5`).

## 2. Edit `config.json`

```json
{
  "proxy": { "listen_port": 8141, "anthropic_upstream": "https://api.anthropic.com", "max_tokens_floor": 64000 },
  "models": [
    { "id": "claude-gpt-5.5", "display_name": "GPT-5.5 (my OpenAI plan)" }
  ],
  "routes": {
    "claude-gpt-5.5": {
      "type": "openai_compat",
      "upstream": "https://api.openai.com",
      "model": "gpt-5.5",
      "auth": "Bearer sk-YOUR_KEY_HERE"
    }
  }
}
```

### Field notes
- **`id`** must start with `claude` or `anthropic` — Claude Code's model menu hides anything else. The part after that is yours; `claude-gpt-5.5` is just a label hook.
- **`display_name`** is what you actually see in the `/model` picker. Make it anything.
- **`upstream`** is the API base URL with **no** `/v1` suffix — the proxy appends `/v1/chat/completions` itself.
- **`model`** is the real model id at OpenAI (`gpt-5.5`, `gpt-4o`, `o3`, etc.).
- **`auth`** is sent verbatim as the `Authorization` header. Use `Bearer sk-...`.

## 3. Start it

```bash
./start.sh            # macOS/Linux
./start.ps1           # Windows PowerShell
```

The first run copies `config.example.json` to `config.json` and stops so you can edit it. Edit, then run again.

## 4. Use it
In Claude Code, run `/model` and pick **GPT-5.5 (my OpenAI plan)**. Every request now gets the ultracode envelope (xhigh effort, adaptive thinking, 64k max_tokens, the ultracode reminder) translated to OpenAI's chat-completions format.

## Troubleshooting
- Run `./doctor.sh` / `./doctor.ps1`.
- `401`/`invalid_api_key` → your `auth` key is wrong or lacks model access.
- Model not in the menu → id didn't start with `claude`/`anthropic`, or `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY` isn't set (start scripts set it for you).
- Answer comes back but the spinner keeps spinning and your next message queues → update to the current `proxy.py` (it closes the stream cleanly after the final event). Full row in the main [README troubleshooting](../README.md#troubleshooting).
