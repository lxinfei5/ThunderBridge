# Demo prompt

Open Claude Code (UltraCode) **in this folder**, pick a model from `/model`, turn
on auto/accept-edits mode, and paste the prompt below. It's designed to show
UltraCode's dynamic Workflow doing real multi-step work with a visible payoff.

---

> `life.py` is Conway's Game of Life. It runs but it's buggy and boring. Do all
> of this in one go, then run it for me:
>
> 1. **Fix the simulation bug.** A 2×2 "block" must stay perfectly stable and a
>    3-cell "blinker" must oscillate. Add a `--selftest` flag that asserts both
>    and prints `OK`.
> 2. **Make it come alive:** animate continuously in place (clear the screen
>    between frames, ~12 fps) with **live cells drawn in color**, and show the
>    generation count.
> 3. **Add starting patterns:** `--pattern glider|blinker|random` (default
>    `random`) and `--steps N` (default: run until Ctrl-C).
> 4. Keep it pure Python standard library, cross-platform, and add a short
>    module docstring + `--help`.
>
> Then run `python3 life.py --selftest`, and finally launch it with the glider so
> I can watch it crawl.

---

Why this is a good demo: it requires **planning** (fix → verify → feature →
run), edits across the file, adds a **self-test it actually runs** (red→green),
and ends on a **glider visibly crawling across the screen in color** — great for
a short clip. Any backend in the `/model` menu runs it with the full UltraCode
harness.
