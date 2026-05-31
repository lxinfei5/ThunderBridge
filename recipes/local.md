# Recipe: Local models (Ollama, LM Studio, llama.cpp, vLLM)

Run a model on your own machine and point Claude Code at it. No API key, no
per-token cost, fully offline. Anything that serves an OpenAI-compatible
`/v1/chat/completions` endpoint works.

## Common local servers & their base URLs

| Server          | Start command (example)                          | Base URL (`upstream`)      |
|-----------------|--------------------------------------------------|----------------------------|
| **Ollama**      | `ollama serve` (then `ollama pull qwen2.5`)      | `http://127.0.0.1:11434`   |
| **LM Studio**   | enable "Local Server" in the app                 | `http://127.0.0.1:1234`    |
| **llama.cpp**   | `./llama-server -m model.gguf --port 8080`       | `http://127.0.0.1:8080`    |
| **vLLM**        | `vllm serve <model> --port 8000`                 | `http://127.0.0.1:8000`    |

> Note: Ollama's OpenAI-compat path also lives under `/v1`, so its base URL is just the host:port — the proxy appends `/v1/chat/completions`.

## Edit `config.json`

```json
{
  "proxy": { "listen_port": 8141, "anthropic_upstream": "https://api.anthropic.com", "max_tokens_floor": 64000 },
  "models": [
    { "id": "claude-local-qwen", "display_name": "Qwen 2.5 (local)" }
  ],
  "routes": {
    "claude-local-qwen": {
      "type": "openai_compat",
      "upstream": "http://127.0.0.1:11434",
      "model": "qwen2.5:latest",
      "auth": "passthrough"
    }
  }
}
```

### Field notes
- **`model`** must match what your local server advertises (`ollama list`, or LM Studio's model id).
- **`auth`**: local servers ignore auth — use `"passthrough"`. The proxy sends a harmless `Bearer unused` so client libraries don't choke.
- For a big local model you may want a **smaller `max_tokens_floor`** (e.g. `8192`) so generations don't run forever. Lower it in the `proxy` block.

## Start & use
```bash
./start.sh        # or ./start.ps1 on Windows
```
`/model` → pick **Qwen 2.5 (local)**. Everything stays on your machine.

## Troubleshooting
- Run `./doctor.sh` / `./doctor.ps1`.
- Connection refused → the local server isn't running, or it's on a different port than your `upstream`.
- Garbage / empty replies → the `model` id is wrong; list your local models and copy the exact id.
- Very slow → expected for big models on CPU; pick a smaller quant or lower `max_tokens_floor`.
- Reply finishes but the spinner keeps spinning / next message queues → update to the current `proxy.py` (it closes the stream cleanly after the final event). See the main [README troubleshooting](../README.md#troubleshooting).
