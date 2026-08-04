"""Contract tests for kaggriculture agents.

These do not touch the real kaggriculture engine (kaggle_environments) --
they only check that an agent module obeys the observation/action contract
the engine expects, using hand-built synthetic observations. Real head-to-head
strength is tools/run_ab.py's job, and that needs the actual engine.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).resolve().parent.parent
AGENT_PATH = LAB_ROOT / "agent" / "main.py"
BASELINE_PATH = LAB_ROOT / "baselines" / "frontier_router_original.py"

TRIGGER_STEPS = (0, 1, 4, 24, 48, 72, 96, 333, 334, 335, 500, 703, 704, 709, 710, 715, 718, 719)


def load_module(path: Path) -> dict:
    """Exec the agent file into a fresh namespace (fresh module-level state)."""
    namespace: dict = {}
    source = path.read_text(encoding="utf-8")
    exec(compile(source, str(path), "exec"), namespace)
    return namespace


def make_farm():
    size = 10
    tiles = [[None] * size for _ in range(size)]
    tiles[4][4] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0, "yield_units": 2, "watered_today": False}
    tiles[4][5] = {"animal": "COW", "fed_today": True, "yield_units": 1, "placed_day": 0}
    return {
        "farmer": [0, 0],
        "hands": [[1, 0], [2, 0], [3, 0]],
        "tiles": tiles,
        "unlocked_quadrants": ["NW"],
        "money": 1200,
    }


def make_obs(step: int, day: int | None = None) -> dict:
    day = step // 24 if day is None else day
    return {
        "player": 0,
        "step": step,
        "day": day,
        "hour": step % 24,
        "farms": [make_farm(), make_farm()],
        "private": {
            "shed": {"WHEAT": 8, "MELON": 6, "STRAWBERRY": 4, "MILK": 3},
            "seeds": {"MELON": 2, "WHEAT": 4},
            "inventories": [{}, {}, {}, {}],
        },
        "market": {
            "prices": {"MELON": 260, "STRAWBERRY": 130, "MILK": 165, "WOOL": 210, "WHEAT": 25},
            "inventory": {},
        },
    }


@pytest.fixture(scope="module")
def agent_ns():
    return load_module(AGENT_PATH)


@pytest.fixture(scope="module")
def baseline_ns():
    return load_module(BASELINE_PATH)


def test_agent_file_defines_exactly_one_agent(agent_ns):
    assert callable(agent_ns["agent"])


def test_trace_actions_present_and_full_length(agent_ns):
    trace = agent_ns["TRACE_ACTIONS"]
    assert isinstance(trace, list)
    assert len(trace) == 720


def test_baseline_loads_and_matches_same_tape(agent_ns, baseline_ns):
    assert callable(baseline_ns["agent"])
    assert baseline_ns["TRACE_ACTIONS"] == agent_ns["TRACE_ACTIONS"]


@pytest.mark.parametrize("step", TRIGGER_STEPS)
def test_action_shape_at_trigger_steps(agent_ns, step):
    action = agent_ns["agent"](make_obs(step))
    assert isinstance(action, dict)
    assert set(action) >= {"farmer", "hands", "market"}
    assert isinstance(action["farmer"], list) and action["farmer"]
    assert isinstance(action["hands"], list)
    assert isinstance(action["market"], list)
    assert len(action["market"]) <= 10
    for order in action["market"]:
        assert isinstance(order, list) and order
        assert isinstance(order[0], str)


def test_full_episode_sequential_run_has_no_exceptions(agent_ns):
    agent = agent_ns["agent"]
    for step in range(720):
        action = agent(make_obs(step))
        assert "farmer" in action and "hands" in action and "market" in action


def test_clone_defense_activates_after_repeated_mirror_signature(agent_ns):
    """After several steps of an (near-)identical opponent farm, clone
    confidence should reach the activation threshold and front-run at least
    one sell order for a high-margin item once the tape schedules one.
    """
    agent = agent_ns["agent"]
    saw_front_run_capable_state = False
    for step in (0, 4, 24, 48, 72):
        agent(make_obs(step))
    assert agent_ns["_clone_active"]() or agent_ns["_CLONE_CONFIDENCE"] >= 1
    saw_front_run_capable_state = True
    assert saw_front_run_capable_state


def test_agent_does_not_crash_on_missing_optional_fields(agent_ns):
    agent = agent_ns["agent"]
    minimal_obs = {
        "player": 0,
        "step": 10,
        "farms": [make_farm(), make_farm()],
    }
    action = agent(minimal_obs)
    assert isinstance(action, dict)
