# Auto Router — pick the right model for every task, automatically

The Auto Router gives UltraCode-Shim one extra pick in `/model`:
**`Auto (smart routing)`**. Choose it and the proxy decides, *per task*, which of
your configured backends to use — sending trivial turns to a cheap model and
hard turns to your strongest one. The goal is the same one Factory Droid's
router pitches: **keep frontier-level quality while cutting cost**, except here
it runs entirely on the models *you* already pay for.

It is **off unless you configure it**, fully local (stdlib only, no new deps),
and degrades safely: if anything goes wrong it falls back to a sensible default
and never breaks a request.

---

## How it works (30 seconds)

1. You pick **`Auto (smart routing)`** (or set it as your orchestrator/worker).
2. On each new task, the proxy sends a *tiny* scoring request to a cheap
   **classifier** model you nominate. The classifier reads the task + a short
   **capability card** for each candidate and returns a score `0.0–1.0` per
   candidate — the probability that model nails the task on the first try.
3. The proxy picks the **cheapest candidate whose score clears `threshold`**
   (default `0.7`). If none clear it, it takes the highest-scoring one.
4. The real request is routed to that backend. The decision is **cached for the
   rest of that task** (its tool-call round-trips reuse it), so you pay the
   classifier cost once per task, not once per request.

```
                         ┌─────────────────────────────┐
  you pick "Auto"  ──▶   │  classifier (cheap model)    │
                         │  scores each candidate 0–1   │
                         └──────────────┬──────────────┘
                                        │ scores
                                        ▼
              cheapest candidate with score ≥ threshold (else best)
                                        │
                                        ▼
                    real request ──▶  that backend (e.g. MiniMax / MiMo / GPT-5.5)
```

## Prove it works (offline, no keys)

A self-contained demo spins up a mock multi-backend server, starts the **real**
`proxy.py` with the router enabled, and runs real tasks of increasing difficulty
through it — showing which backend each one actually hit:

```
python3 examples/auto_router_demo.py
```

```text
#  Task                                         Classifier scores                Routed to      Cost
1  add a docstring to the foo() helper          cheap=0.90 mid=0.92 strong=0.95  claude-cheap   $0.3
2  write a CRUD REST endpoint with tests        cheap=0.50 mid=0.85 strong=0.95  claude-mid     $1.0
3  refactor the auth module across 8 files ...  cheap=0.40 mid=0.55 strong=0.95  claude-strong  $5.0
4  what does this screenshot show?  [image]     cheap=0.90 mid=0.92 strong=0.95  claude-strong  $5.0  ← only vision-capable
5  (repeat task #1)                             served from cache                claude-cheap   $0.3  ← classifier not re-called
RESULT: PASS
```

Note row 4: even though the cheap model *scored* 0.90, the task has an image, so
the proxy hard-zeroes the models that can't see and the only vision-capable
candidate wins. Row 5 shows the per-task cache: the repeat is served without
re-calling the classifier. The same routing logic is also locked down by the
offline self-test (`python3 test_proxy.py`).

The classifier **never sees price**. It scores on capability only; cost is
applied afterward by the "cheapest among those good enough" rule. That keeps the
classifier from being biased toward expensive models.

---

## Quick start

The shipped `config.example.json` already has a working router block. To use it:

1. Keep the candidate models you actually have keys for (delete the rest). Any
   candidate without a configured route is **skipped automatically**, so the
   router keeps working with whatever subset remains.
2. Point `router.classifier` at the cheapest fast model you kept.
3. `python3 scripts/doctor.py` — it validates the router block.
4. Launch, pick **`Auto (smart routing)`** in the selector or `/model`.

That's it.

---

## Configuration reference

The `router` block in `config.json`:

```jsonc
"router": {
  "enabled": true,                 // master switch
  "id": "claude-auto",             // the picker id (must also be in models + a type:auto route)
  "classifier": "claude-mimo",     // a route id used as the cheap scorer
  "threshold": 0.7,                // cheapest candidate scoring >= this wins
  "default": "claude-mimo",        // used if the classifier can't run at all
  "cache": true,                   // reuse one classification across a task
  "candidates": [
    {
      "id": "claude-minimax-m3",   // must be a route in "routes"
      "cost": 0.3,                 // RELATIVE price weight (only ordering matters)
      "supports_images": false,    // image tasks skip models that can't see
      "card": "Very cheap, fast. Strong on single-file edits, codegen from a clear spec, simple refactors, data wrangling. Weak on big multi-file refactors, subtle debugging, niche domains."
    },
    {
      "id": "claude-gpt-5.5-codex",
      "cost": 5.0,
      "supports_images": true,
      "card": "Frontier reasoning + agentic coding. Best for the hardest work: large multi-file refactors, subtle debugging, architecture, long autonomous workflows, and image tasks."
    }
  ]
}
```

You also need the picker itself registered (the example already does this):

```jsonc
"models": [ { "id": "claude-auto", "display_name": "Auto (smart routing)" }, ... ],
"routes": { "claude-auto": { "type": "auto" }, ... }
```

### Field-by-field

| Field | Meaning |
|-------|---------|
| `enabled` | Turn the router on/off. Also overridable at runtime with `UC_ROUTER=0`. |
| `id` | The picker id. Must appear in `models` **and** have a `{"type":"auto"}` route. Defaults to `claude-auto`. (If you set `enabled` and forget these, the proxy auto-creates them.) |
| `classifier` | A route id (from `routes`) used as the scorer. Use your cheapest, fastest model. If it's missing/unavailable, the router falls back to the cheapest candidate **without scoring**. |
| `threshold` | `0–1`. The bar a candidate's score must clear. **Lower = more aggressive savings** (cheap models win more often); **higher = escalate to strong models sooner**. `0.7` is a good start. |
| `default` | Candidate id used when classification can't run at all. Defaults to the cheapest candidate. |
| `cache` | Reuse one classification across a task's follow-up tool calls. Recommended. |
| `candidates[].id` | Must match a route. Missing routes are silently skipped. |
| `candidates[].cost` | A **relative** weight; units don't matter, only the ordering. Lowest cost among the "good enough" candidates wins. |
| `candidates[].supports_images` | If `false`, the candidate is hard-scored `0` whenever the task includes images. |
| `candidates[].card` | The capability description the classifier reads. **This is the single most important field** — be honest about strengths and weaknesses; that's what makes routing smart. |

### The capability card is where the intelligence lives

The classifier only knows about a model what the card tells it. A good card lists
concrete strengths *and* weaknesses. Examples:

> *"Cheap, fast generalist. Good at standard servers/CRUD, data processing,
> conventional multi-file edits, and tool/test loops. Less reliable on hard
> algorithms, exotic build systems, or long autonomous debugging."*

Vague cards ("a good model") produce vague routing. Specific cards produce sharp
routing.

---

## Orchestrator + Worker

`Auto` works in both tiers (see [HOW_IT_WORKS.md §5](HOW_IT_WORKS.md)):

- Set **orchestrator = Auto** → the main loop is routed per task.
- Set **worker = Auto** (`Worker → Auto`) → every parallel sub-agent is routed
  per task — great for fanning cheap work out while a fixed strong orchestrator
  plans.
- You can mix: e.g. orchestrator = GPT‑5.5, worker = Auto.

---

## Tuning & knobs

| Env var | Default | What it does |
|---------|---------|--------------|
| `UC_ROUTER` | `1` | Set `0` to disable the router even if `enabled` in config. |
| `UC_ROUTER_TIMEOUT` | `12` | Seconds to wait for the classifier before falling back. |
| `UC_ROUTER_MAX_TOKENS` | `600` | Max tokens for the classifier's reply (it only needs to emit small JSON). |
| `UC_ROUTER_LOG` | `0` | Set `1` to log every routing decision + the raw scores. |

**Watch it decide:** run with `UC_ROUTER_LOG=1` and tail the proxy log
(`%LOCALAPPDATA%\UltraCode-Shim\ultracode_proxy.log` on Windows,
`~/.local/state/ultracode-shim/proxy.log` on mac/Linux). Each task prints a line
like:

```
[router] tier=heavy -> claude-mimo (score=0.82; score>=0.70, cheapest) scores={"claude-minimax-m3": 0.55, "claude-mimo": 0.82, "claude-gpt-5.5-codex": 0.93}
```

That log is also the honest way to tell whether routing is *helping you* — watch
which tasks escalate and tune `threshold` / cards accordingly.

---

## Failure behavior (it never breaks your request)

| Situation | What happens |
|-----------|--------------|
| Classifier times out / errors | Falls back to `default` (or cheapest candidate). |
| Classifier id not configured | Deterministic: routes to the cheapest candidate, no scoring. |
| A candidate's route was deleted | That candidate is skipped; routing continues with the rest. |
| Only one candidate available | Routes straight to it (no classifier call). |
| Task has images, candidate can't | That candidate is scored `0` (can't win). |
| Router disabled but `claude-auto` picked | Coerced to the cheapest candidate so nothing dispatches the synthetic id. |

---

## Design notes

The Auto Router takes the well-known "classifier picks the model" idea (popularized
by tools like Factory Droid's router) and builds it on the models *you* already
configure, with two choices worth calling out:

1. **Per-task caching** so you don't pay the classifier tax on every tool-call
   round-trip.
2. **Every decision is logged** (`UC_ROUTER_LOG=1`) — the cheap first step toward
   actually *learning* whether routing helps, which a future feedback loop could
   build on.

It runs on **your** backends instead of a fixed set, so "use my cheap model when
possible, my strong model when needed" means exactly the models you pay for. The
`0.70` threshold and the capability-card approach are both tunable — see the
fields above.
