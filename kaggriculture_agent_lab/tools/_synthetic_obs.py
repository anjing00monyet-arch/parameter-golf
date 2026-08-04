"""Shared synthetic-observation builder for tools/ scripts that need to run
an agent without the real kaggriculture engine (smoke checks only -- this
says nothing about competitive strength, see tools/run_ab.py's docstring).
"""
from __future__ import annotations


def make_farm() -> dict:
    size = 10
    tiles = [[None] * size for _ in range(size)]
    tiles[4][4] = {
        "kind": "PLANT",
        "crop": "MELON",
        "planted_day": 0,
        "yield_units": 2,
        "watered_today": False,
    }
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
