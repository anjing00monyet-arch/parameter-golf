#!/usr/bin/env python3
"""Smoke-test an agent file.

Tries the real kaggriculture engine (agent vs. the built-in "starter" bot)
first. If kaggle_environments / the kaggriculture environment isn't
installed or reachable, falls back to a synthetic-observation sequential
run so you still get a fast crash/shape check without the real engine.

The fallback mode proves the agent *runs cleanly*; it says nothing about
competitive strength. Only the real-engine path or tools/run_ab.py can
tell you that.

Usage:
    python tools/run_smoke.py agent/main.py
    python tools/run_smoke.py agent/main.py --seed 12001
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB_ROOT))

from tools._synthetic_obs import make_obs  # noqa: E402


def load_module(path: Path) -> dict:
    namespace: dict = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


def try_real_engine(agent_path: Path, seed: int) -> dict | None:
    try:
        importlib.metadata.version("kaggle-environments")
        from kaggle_environments import make
    except Exception as exc:  # noqa: BLE001
        return {"engine_available": False, "reason": repr(exc)}

    try:
        env = make(
            "kaggriculture",
            configuration={"episodeSteps": 720, "seed": seed},
            debug=False,
        )
        env.run([str(agent_path), "starter"])
        final = env.steps[-1]
        return {
            "engine_available": True,
            "left_status": str(final[0].status),
            "right_status": str(final[1].status),
        }
    except Exception as exc:  # noqa: BLE001
        return {"engine_available": False, "reason": repr(exc)}


def run_synthetic_fallback(agent_path: Path) -> dict:
    ns = load_module(agent_path)
    agent = ns["agent"]
    steps_run = 0
    for step in range(720):
        action = agent(make_obs(step))
        assert isinstance(action, dict) and "farmer" in action
        steps_run += 1
    return {"mode": "synthetic_fallback", "steps_run": steps_run, "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent_path", type=Path)
    parser.add_argument("--seed", type=int, default=12001)
    args = parser.parse_args()

    real = try_real_engine(args.agent_path, args.seed)
    if real and real.get("engine_available"):
        real["mode"] = "real_engine"
        print(json.dumps(real, indent=2))
        return 0

    print(json.dumps({"real_engine": real}, indent=2))
    print("kaggriculture engine not available here -- falling back to synthetic smoke run")
    result = run_synthetic_fallback(args.agent_path)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
