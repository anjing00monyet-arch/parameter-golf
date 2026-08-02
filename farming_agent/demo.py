"""Smoke test / usage example for `agent.agent`.

Builds a small synthetic `obs` matching the schema documented at the top of
agent.py and runs a few turns, printing the returned actions. This is not a
real game engine -- it only proves the agent runs end-to-end without
exceptions and returns well-formed actions.
"""

from agent import agent


def make_tile(x, y, region, kind="EMPTY", **kwargs):
    tile = {
        "x": x, "y": y, "region": region, "kind": kind,
        "crop": None, "planted_day": None, "growth_days_needed": None,
        "watered_today": False, "wilt_risk": False, "has_weeds": False,
        "ready_to_harvest": False, "animal": None, "fed_today": False,
        "cared_today": False, "has_pasture": True, "fertilizer_ready": False,
        "slot_key": None,
    }
    tile.update(kwargs)
    return tile


def make_obs(step=0, day=0, hour=6):
    nw_tiles = [make_tile(x, y, "NW", slot_key=(y * 5 + x)) for y in range(5) for x in range(5)]
    return {
        "step": step,
        "day": day,
        "hour": hour,
        "coins": 800,
        "land": {"NW": nw_tiles},
        "owned_regions": ["NW"],
        "shed": {"x": 0, "y": 0, "region": "NW"},
        "farmer": {"x": 0, "y": 0, "region": "NW", "carrying": None},
        "hands": [
            {"id": i, "x": 1, "y": 1, "region": "NW", "carrying": None}
            for i in range(4)
        ],
        "inventory": {
            "WHEAT": 10, "MELON_SEED": 0, "STRAWBERRY_SEED": 0,
            "CARROT_SEED": 0, "TOMATO_SEED": 0, "COW": 0, "SHEEP": 0,
        },
        "market": {"prices": {
            "MELON": 55, "STRAWBERRY": 28, "CARROT": 14, "WHEAT": 9,
            "TOMATO": 24, "MILK": 30, "WOOL": 34, "EGG": 6, "FERTILIZER": 8,
        }},
        "town": {"shops_unlocked": []},
        "rival": {"crop_tiles": {}, "animal_counts": {}},
        "land_offers": {
            "NE": {"price": 400, "available": True},
            "SW": {"price": 450, "available": True},
            "SE": {"price": 450, "available": True},
        },
    }


if __name__ == "__main__":
    for step in range(3):
        obs = make_obs(step=step, day=step, hour=6)
        result = agent(obs)
        print(f"--- step {step} ---")
        print("farmer:", result["farmer"])
        print("hands:", result["hands"])
        print("market:", result["market"])
