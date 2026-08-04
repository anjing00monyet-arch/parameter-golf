#!/usr/bin/env python3
"""Head-to-head A/B comparison between two agent files.

Usage:
    python tools/run_ab.py \\
        --candidate agent/main.py \\
        --baseline baselines/frontier_router_original.py \\
        --games 20 \\
        --base-seed 8000

For each of `--games` seeds, plays the pair twice with seats swapped, so
`--games 20` runs 40 matches total. Requires the real kaggriculture engine
(kaggle_environments with the kaggriculture environment registered).

This script deliberately does NOT fabricate a win rate when the real engine
isn't available -- it fails loudly instead, so a missing engine can't be
mistaken for "0 wins across 40 games" or similar. Run it on a Kaggle
Notebook, or wherever kaggle-environments>=1.32.2 with the kaggriculture
environment is installed, to get a real result.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent


def load_engine():
    try:
        import importlib.metadata

        importlib.metadata.version("kaggle-environments")
        from kaggle_environments import make
        return make
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "ENGINE UNAVAILABLE: kaggle_environments (with the kaggriculture "
            "environment) is not installed/importable here.\n"
            f"  detail: {exc!r}\n"
            "Run this on a Kaggle Notebook or an environment with the real "
            "engine installed -- this script will not report fake results."
        )


def score_from_state(env, seat: int) -> float:
    final = env.steps[-1][seat]
    try:
        reward = float(final.reward)
    except Exception:  # noqa: BLE001
        reward = 0.0
    if reward != 0:
        return reward
    for states in reversed(env.steps):
        try:
            return float(states[0].observation.farms[seat].money)
        except Exception:  # noqa: BLE001
            continue
    return reward


def play(make, left_path: str, right_path: str, seed: int, episode_steps: int) -> dict:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": episode_steps, "seed": int(seed)},
        debug=False,
    )
    env.run([left_path, right_path])
    final = env.steps[-1]
    return {
        "left_money": score_from_state(env, 0),
        "right_money": score_from_state(env, 1),
        "left_status": str(final[0].status),
        "right_status": str(final[1].status),
    }


def symmetric_pair(make, candidate: str, baseline: str, seed: int, episode_steps: int) -> list[dict]:
    first = play(make, candidate, baseline, seed, episode_steps)
    second = play(make, baseline, candidate, seed, episode_steps)
    rows = [
        {
            "seed": seed,
            "candidate_seat": 0,
            "candidate_money": first["left_money"],
            "baseline_money": first["right_money"],
        },
        {
            "seed": seed,
            "candidate_seat": 1,
            "candidate_money": second["right_money"],
            "baseline_money": second["left_money"],
        },
    ]
    for row in rows:
        row["margin"] = row["candidate_money"] - row["baseline_money"]
        row["result"] = "win" if row["margin"] > 0 else "loss" if row["margin"] < 0 else "tie"
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--base-seed", type=int, default=8000)
    parser.add_argument("--episode-steps", type=int, default=720)
    args = parser.parse_args()

    for path in (args.candidate, args.baseline):
        if not path.exists():
            print(f"error: {path} does not exist", file=sys.stderr)
            return 2

    make = load_engine()

    rows = []
    for offset in range(args.games):
        seed = args.base_seed + offset
        rows.extend(
            symmetric_pair(make, str(args.candidate), str(args.baseline), seed, args.episode_steps)
        )

    monies = [row["candidate_money"] for row in rows]
    margins = [row["margin"] for row in rows]
    wins = sum(row["result"] == "win" for row in rows)
    losses = sum(row["result"] == "loss" for row in rows)

    summary = {
        "candidate": str(args.candidate),
        "baseline": str(args.baseline),
        "games_requested": args.games,
        "matches_played": len(rows),
        "wins": wins,
        "losses": losses,
        "ties": len(rows) - wins - losses,
        "mean_candidate_money": round(statistics.mean(monies), 2),
        "minimum_candidate_money": min(monies),
        "mean_margin": round(statistics.mean(margins), 2),
        "minimum_margin": min(margins),
    }
    print(json.dumps({"summary": summary, "matches": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
