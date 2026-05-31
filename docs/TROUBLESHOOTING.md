# Troubleshooting

First, always run the doctor — it catches most problems and prints the fix:

```
python scripts/doctor.py        # mac/linux: python3
```

The proxy log is at:
- Windows: `%LOCALAPPDATA%\UltraCode-Shim\ultracode_proxy.log`
- mac/linux/WSL: `~/.local/state/ultracode-shim/proxy.log`

---

### My model doesn't appear in `/model`

- **Id doesn't start with `claude` or `anthropic`.** Claude Code filters
  discovered ids with `/^(claude|anthropic)/i`. Rename it (e.g. `claude-mimo`).
- **Discovery not enabled.** The launcher sets
  `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`; if you started `claude` yourself,
  set it (and `ANTHROPIC_BASE_URL`) or just use the launcher.
- **First open timing.** Discovery fetches in the background. Close `/model` and
  reopen, or restart Claude Code — the launcher pre-seeds the cache so it should
  show immediately.
- **You're not on an OAuth login.** Gateway discovery only triggers for
  first-party (OAuth) logins, not raw `ANTHROPIC_API_KEY` keys.

### The model is listed but the answer is an error / empty

- Check the proxy log (path above) for the upstream status line.
- **401 / "invalid api key":** the route's `auth` in `config.json` (or the
  `${VAR}` it references) is wrong/empty, or the header format is wrong. Re-run
  the doctor.
- **404 / "model not found":** the route's `model` isn't a valid id for that
  backend (remember: it's the backend's id, not the `claude-…` alias), or
  `upstream` is wrong.
- **Codex 401 / "run codex login":** your ChatGPT/Codex token expired — run
  `codex login` again.

### It replies in text but never calls tools

The route is probably **passthrough** (or pointing at a chat endpoint that drops
tools). Set `"type": "openai_compat"` for that route — the proxy then translates
Anthropic `tool_use`/`tool_result` ⇄ OpenAI `tool_calls` both ways. Real Claude
(passthrough) already handles tools natively.

### "Proxy did not become healthy"

- Another process is on the port. Pick another: set `proxy.listen_port` in
  `config.json` (or `UC_LISTEN_PORT`) and relaunch, or stop the stale
  `python … proxy.py`.
- Python not found. Ensure `python` (Windows) / `python3` (mac/linux) is on PATH.
- Run the proxy in the foreground to see the error:
  `python proxy.py` (Ctrl-C to stop).

### PowerShell won't run the script

```
powershell -ExecutionPolicy Bypass -File .\windows\Start-UltraCode.ps1
```

### Claude Code isn't found by the launcher

Install it (`npm i -g @anthropic-ai/claude-code`) and make sure `claude` is on
PATH (`claude --version`).

### Did I break my normal Claude Code?

No — this project never edits your global `~/.claude` config or credentials; it
only sets env for the launched process and uses a session `--settings` file. Use
the **"Claude Code (Normal)"** icon for the stock experience, or
`windows\Uninstall.ps1` to remove the shim entirely.

### Prove the install itself is fine

Run the offline self-test (no network, no keys):

```
python test_proxy.py
```

If that passes, the code is good and the problem is configuration/credentials. If
it fails, your clone is broken — re-clone and report the output.
