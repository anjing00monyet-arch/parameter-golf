# Kaggriculture Agent Lab

A working harness around a Kaggriculture submission: the current candidate
agent, the unmodified baseline it was built from, contract tests, and the
tooling to check, compare, and package it.

## What's actually in here

- **`agent/main.py`** — candidate agent ("V24 Clone Cash Shield"): the
  public zero-waste tape from episode `89549522` (seat 1), plus four
  evidence-gated wrapper patches: `adaptive_triad`, treasury flush,
  terminal cash work, and `clone_front_run` — mirror/clone defense that
  detects an opponent farm whose signature (animal/crop/structure counts,
  hand count, positions) tracks its own too closely and front-runs the
  scripted high-margin sells (MELON/STRAWBERRY/MILK/WOOL) before a mirrored
  copy of this strategy sells into the same price.
- **`baselines/frontier_router_original.py`** — the same tape, completely
  unmodified. No defenses, no patches. Exists only as the A/B anchor.
- **`configs/default.json`** — the spec that produced `agent/main.py`
  (`agent_spec`), plus engine/A-B run defaults.
- **`configs/core_actions.json`** + **`tools/wrapper_template.py.tpl`** —
  the reusable pieces `tools/new_experiment.py` recombines to build new
  candidates without hand-editing generated code.
- **`tests/test_agent_contract.py`** — pytest suite: syntax, single
  `agent()` definition, module load, action-shape contract across
  synthetic observations (including the special-case steps: 333-335
  adaptive triad, 704+ terminal work, 710/718 treasury), a full 720-step
  sequential run, and a check that clone-confidence actually rises against
  a mirrored opponent signature.
- **`tools/`** — see below.
- **`prompts/`** — role-split guardrails (`strategist.md` /
  `implementer.md` / `reviewer.md`) for iterating on this with AI help
  without any one role quietly promoting an unvalidated change.
- **`.github/workflows/ci.yml`** — static check + contract tests + submission
  build on every push/PR touching this folder. **Does not** run real-engine
  A/B (`tools/run_ab.py`) — that needs `kaggle-environments` with the
  `kaggriculture` environment registered, which isn't on public PyPI as of
  this writing. If you push this folder as the root of its own repository,
  drop the `working-directory: kaggriculture_agent_lab` default in the
  workflow; GitHub Actions only picks up `.github/workflows` at a repo root.
- **`notebooks/submission_builder.ipynb`** — minimal Kaggle-Notebook-ready
  version of the same static-check + package flow, with an optional
  real-engine smoke cell.
- **`submissions/submission.tar.gz`** — built output, `main.py` only at the
  archive root. Regenerate with `tools/build_submission.py` after any
  change to `agent/main.py`.

## What's honest about what's *not* verified here

This sandbox does not have `kaggle_environments` with the `kaggriculture`
environment installed, and can't reach the Kaggle replay CDN reliably. So:

- `pytest` and `tools/static_check.py` prove the agent is syntactically
  valid, loads, and returns well-shaped actions across representative game
  states (including the mirror-defense trigger path). **They do not prove
  it wins games.**
- `tools/run_smoke.py` and `tools/run_ab.py` both try the real engine first
  and say so explicitly if they fall back or fail — they never fabricate a
  win rate. Run them on a Kaggle Notebook (or anywhere the real engine is
  installed) for an actual competitive read.

## Quickstart

```bash
pip install -r requirements-dev.txt
python tools/static_check.py agent/main.py
pytest
python tools/build_submission.py
```

## A/B comparison (needs the real engine)

```bash
python tools/run_ab.py \
  --candidate agent/main.py \
  --baseline baselines/frontier_router_original.py \
  --games 20 \
  --base-seed 8000
```

20 seeds x seat-swap = 40 matches total. Fails loudly (not silently with
fake numbers) if the real engine isn't available where you run it.

## Starting a new experiment

```bash
python tools/new_experiment.py \
  --name wider_front_run \
  --hypothesis "Extending front-run horizon to 2 steps captures a better price before a mirrored opponent's tape catches up." \
  --spec '{"adaptive_triad": true, "treasury_start": 710, "treasury_flush": 718, "terminal_work_start": 704, "clone_front_run": true, "front_run_horizon": 2, "front_run_items": ["MELON", "STRAWBERRY", "MILK", "WOOL"]}'
```

Creates `experiments/wider_front_run/{spec.json, agent.py, NOTES.md}`.
Nothing is promoted to `agent/main.py` automatically — see
`prompts/reviewer.md`.

## Replay analysis

```bash
python tools/analyze_replays.py --episode-id 89549522
python tools/analyze_replays.py --file path/to/replay.json
```
