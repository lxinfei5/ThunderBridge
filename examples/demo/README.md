# UltraCode-Shim demo

A tiny, self-contained scenario for trying UltraCode-Shim (and for recording a
demo). `life.py` is a deliberately buggy + bare-bones Conway's Game of Life.

## Try it

```
# 1. See the "before" (it runs, but it's buggy and boring)
python3 life.py

# 2. Launch UltraCode in THIS folder, pick a model with /model, enable auto mode
windows\Start-UltraCode.ps1      # or  ../../bin/ultracode   on mac/linux

# 3. Paste the task from PROMPT.md and let it work, then watch the glider crawl
```

The task (see [PROMPT.md](PROMPT.md)) makes the model fix a real bug, add an
animated color renderer, add starting patterns + flags, and a self-test it runs
itself — a good showcase of UltraCode's dynamic Workflow on whatever backend you
picked.

Pure Python standard library; nothing to install.
