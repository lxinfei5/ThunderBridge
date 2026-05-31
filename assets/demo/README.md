# Demo media + recording guide

Drop your screen recording here and the README will show it off.

- **For GitHub:** save a looping `demo.gif` in this folder, then uncomment the
  image line in the root `README.md` (under **## Demo**):
  `![UltraCode-Shim demo](assets/demo/demo.gif)`
- **For X/Twitter:** post the `.mp4` directly (X autoplays video; no GIF needed).

## Shot list (≈45–60s, for the X video)

The repo ships a ready-made demo in [`examples/demo/`](../../examples/demo/) so
the on-camera task always works. Record in that folder.

1. **The hook (3s).** Desktop with the **"UltraCode (All Models)"** icon. Double-click it.
2. **One icon → every model (5s).** Claude Code opens. Type `/model` and scroll the
   list — GPT‑5.5, MiMo, DeepSeek, OpenRouter, Composer… all under one icon. Pick one
   (GPT‑5.5 via Codex login makes a clean story: "no API key, just my ChatGPT login").
3. **Auto mode (2s).** Toggle auto / accept-edits so it can run end-to-end.
4. **The ask (5s).** Paste the prompt from `examples/demo/PROMPT.md`
   ("fix the bug, animate it in color, add patterns + a self-test, then run it").
5. **The workflow (20–25s, sped up 2–4×).** Let UltraCode plan and edit: it fixes the
   neighbor bug, adds the animated color renderer, adds `--pattern`/`--steps`, writes a
   self-test. Show the Workflow/steps UI ticking.
6. **Proof (5s).** It runs `python3 life.py --selftest` → `OK`.
7. **The payoff (8s).** It launches with `--pattern glider` and a colored glider crawls
   across the terminal. End on that.

Optional caption: *"Claude Code's UltraCode mode — now on any model I already
pay for. One icon, pick from /model, full deep-reasoning harness."*

## Recording tips

- Use a roomy terminal (≈100×30) and a large font; the glider should be clearly visible.
- Hide secrets: don't show `config.json` contents or `/healthz` (it lists routes).
- Light/dark either works; the renderer uses ANSI color so a dark theme pops.

## Make a GIF from an mp4 (optional)

```
ffmpeg -i demo.mp4 -vf "fps=12,scale=900:-1:flags=lanczos" -loop 0 demo.gif
# smaller file:  add  -filter_complex "[0:v] palettegen"  /  "paletteuse"  passes
```
