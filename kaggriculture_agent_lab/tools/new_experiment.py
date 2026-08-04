#!/usr/bin/env python3
"""Scaffold a new one-hypothesis, one-feature experiment.

Builds a candidate agent.py by layering a single spec (adaptive_triad,
treasury_start/flush, terminal_work_start, clone_front_run/horizon/items)
on top of the same public tape baselines/frontier_router_original.py is
built from, using the reusable wrapper template in
tools/wrapper_template.py.tpl -- the same construction agent/main.py itself
went through.

Usage:
    python tools/new_experiment.py \\
        --name wider_front_run \\
        --hypothesis "Extending front-run horizon to 2 steps sells into a
            higher price before a mirrored opponent's tape catches up." \\
        --spec '{"adaptive_triad": true, "treasury_start": 710,
                 "treasury_flush": 718, "terminal_work_start": 704,
                 "clone_front_run": true, "front_run_horizon": 2,
                 "front_run_items": ["MELON", "STRAWBERRY", "MILK", "WOOL"]}'

Creates experiments/<name>/{spec.json, agent.py, NOTES.md}. Nothing here
touches agent/main.py -- promote an experiment manually once run_ab.py
(on the real engine) confirms it's actually an improvement.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = LAB_ROOT / "baselines" / "frontier_router_original.py"
WRAPPER_TEMPLATE_PATH = LAB_ROOT / "tools" / "wrapper_template.py.tpl"
CORE_ACTIONS_PATH = LAB_ROOT / "configs" / "core_actions.json"
EXPERIMENTS_ROOT = LAB_ROOT / "experiments"


def load_core_actions() -> dict:
    raw = json.loads(CORE_ACTIONS_PATH.read_text(encoding="utf-8"))
    return {int(step): action for step, action in raw.items()}


def build_source(spec: dict) -> str:
    baseline_source = BASELINE_PATH.read_text(encoding="utf-8")
    prefix = baseline_source.rsplit("\ndef agent(obs, config=None):", 1)[0]
    wrapper_template = WRAPPER_TEMPLATE_PATH.read_text(encoding="utf-8")
    core_actions = load_core_actions()

    wrapper = (
        wrapper_template
        .replace("__CORE_ACTIONS__", repr(core_actions))
        .replace("__ADAPTIVE_TRIAD__", repr(bool(spec.get("adaptive_triad", False))))
        .replace("__TREASURY_START__", str(int(spec.get("treasury_start", -1))))
        .replace("__TREASURY_FLUSH__", str(int(spec.get("treasury_flush", 718))))
        .replace("__TERMINAL_WORK_START__", str(int(spec.get("terminal_work_start", -1))))
        .replace("__CLONE_FRONT_RUN__", repr(bool(spec.get("clone_front_run", False))))
        .replace("__FRONT_RUN_HORIZON__", str(int(spec.get("front_run_horizon", 0))))
        .replace("__FRONT_RUN_ITEMS__", repr(tuple(spec.get("front_run_items", ()))))
    )
    return prefix + "\n" + wrapper


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="experiment folder name, e.g. wider_front_run")
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--spec", required=True, help="JSON spec dict")
    args = parser.parse_args()

    spec = json.loads(args.spec)
    out_dir = EXPERIMENTS_ROOT / args.name
    if out_dir.exists():
        raise SystemExit(f"error: experiments/{args.name} already exists")
    out_dir.mkdir(parents=True)

    (out_dir / "spec.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")

    agent_source = build_source(spec)
    (out_dir / "agent.py").write_text(agent_source, encoding="utf-8")

    notes = f"""# Experiment: {args.name}

## Hypothesis
{args.hypothesis}

## Spec
```json
{json.dumps(spec, indent=2)}
```

## Status
Built, not yet evaluated.

## Next step
```
python tools/static_check.py experiments/{args.name}/agent.py
python tools/run_ab.py --candidate experiments/{args.name}/agent.py \\
    --baseline agent/main.py --games 20 --base-seed 8000
```
Promote to agent/main.py only if run_ab.py (real engine) shows a clear,
non-marginal win-rate and money improvement over the current agent/main.py.
"""
    (out_dir / "NOTES.md").write_text(notes, encoding="utf-8")

    print(json.dumps({
        "experiment": args.name,
        "dir": str(out_dir.relative_to(LAB_ROOT)),
        "files": ["spec.json", "agent.py", "NOTES.md"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
