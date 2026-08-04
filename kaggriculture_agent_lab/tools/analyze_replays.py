#!/usr/bin/env python3
"""Basic aggregate stats over a kaggriculture replay JSON.

Accepts a local file path or an episode id (fetched from the public
Kaggle replay CDN, same endpoint the original analysis notebook used).

Usage:
    python tools/analyze_replays.py --file replay_89549522.json
    python tools/analyze_replays.py --episode-id 89549522
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path


def public_replay_url(episode_id: int) -> str:
    return f"https://www.kaggleusercontent.com/episodes/{int(episode_id)}.json"


def fetch_replay(episode_id: int) -> dict:
    with urllib.request.urlopen(public_replay_url(episode_id), timeout=60) as response:
        return json.loads(response.read())


def state_value(state, key, default=None):
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def analyze(replay: dict) -> dict:
    steps = replay.get("steps", [])
    if len(steps) < 2:
        raise ValueError("replay has no action steps")

    num_seats = len(steps[1])
    sell_counts = [Counter() for _ in range(num_seats)]
    action_counts = [Counter() for _ in range(num_seats)]
    money_timeline = [[] for _ in range(num_seats)]

    for states in steps[1:]:
        for seat in range(num_seats):
            if seat >= len(states):
                continue
            action = state_value(states[seat], "action", None)
            if not isinstance(action, dict):
                continue

            farmer = action.get("farmer") or ["PASS"]
            action_counts[seat][farmer[0]] += 1
            for hand in action.get("hands", []) or []:
                if hand:
                    action_counts[seat][hand[0]] += 1
            for order in action.get("market", []) or []:
                if isinstance(order, list) and order and order[0] == "SELL" and len(order) >= 3:
                    sell_counts[seat][order[1]] += max(0, int(order[2] or 0))

            observation = state_value(states[seat], "observation", None)
            farms = state_value(observation, "farms", None) if observation is not None else None
            if farms and seat < len(farms):
                money = state_value(farms[seat], "money", None)
                if money is not None:
                    money_timeline[seat].append(float(money))

    final_state = steps[-1]
    result = {
        "num_seats": num_seats,
        "total_steps": len(steps) - 1,
        "seats": [],
    }
    for seat in range(num_seats):
        final_reward = None
        try:
            raw_reward = state_value(final_state[seat], "reward", None)
            final_reward = None if raw_reward is None else float(raw_reward)
        except Exception:  # noqa: BLE001
            pass
        result["seats"].append({
            "seat": seat,
            "status": str(state_value(final_state[seat], "status", "UNKNOWN")),
            "final_reward": final_reward,
            "final_money": money_timeline[seat][-1] if money_timeline[seat] else None,
            "sells_by_item": dict(sell_counts[seat]),
            "action_type_counts": dict(action_counts[seat]),
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="local replay JSON path")
    source.add_argument("--episode-id", type=int, help="public episode id to download")
    args = parser.parse_args()

    if args.file:
        replay = json.loads(args.file.read_text(encoding="utf-8"))
    else:
        replay = fetch_replay(args.episode_id)

    print(json.dumps(analyze(replay), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
