# Recipe: OpenRouter (one key, hundreds of models)

[OpenRouter](https://openrouter.ai) exposes many providers behind one
OpenAI-compatible endpoint. Great for trying lots of models with a single key.

## 1. Get an API key
- Sign up at https://openrouter.ai and create a key (`sk-or-...`).

## 2. Edit `config.json`

```json
{
  "proxy": { "listen_port": 8141, "anthropic_upstream": "https://api.anthropic.com", "max_tokens_floor": 64000 },
  "models": [
    { "id": "claude-llama-405b", "display_name": "Llama 3.1 405B (OpenRouter)" },
    { "id": "claude-deepseek",   "display_name": "DeepSeek V3 (OpenRouter)" }
  ],
  "routes": {
    "claude-llama-405b": {
      "type": "openai_compat",
      "upstream": "https://openrouter.ai/api",
      "model": "meta-llama/llama-3.1-405b-instruct",
      "auth": "Bearer sk-or-YOUR_KEY_HERE"
    },
    "claude-deepseek": {
      "type": "openai_compat",
      "upstream": "https://openrouter.ai/api",
      "model": "deepseek/deepseek-chat",
      "auth": "Bearer sk-or-YOUR_KEY_HERE"
    }
  }
}
```

### Field notes
- **`upstream`** is `https://openrouter.ai/api` (no `/v1`). The proxy appends `/v1/chat/completions`.
- **`model`** is OpenRouter's slug, e.g. `meta-llama/llama-3.1-405b-instruct`, `deepseek/deepseek-chat`, `qwen/qwen-2.5-72b-instruct`. Browse them at https://openrouter.ai/models.
- You can list as many models as you like — each becomes its own `/model` entry. Reuse the same key in every route.

## 3. Start & use
```bash
./start.sh        # or ./start.ps1 on Windows
```
Then `/model` in Claude Code and pick your OpenRouter entry.

## Notes & troubleshooting
- OpenRouter sometimes wants `HTTP-Referer` / `X-Title` headers for ranking, but they're optional for API use; this proxy doesn't send them.
- Run `./doctor.sh` / `./doctor.ps1` to verify routing.
- `402`/quota errors → top up credits on OpenRouter.
- `404 model` → the slug is wrong; copy it exactly from the OpenRouter models page.
- Reply finishes but the spinner keeps spinning / next message queues → update to the current `proxy.py` (it closes the stream cleanly after the final event). See the main [README troubleshooting](../README.md#troubleshooting).
