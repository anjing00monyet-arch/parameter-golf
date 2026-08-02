"""Market Shadow Diversification — a deterministic, market-reactive rule-based farm agent.

This module reconstructs, in runnable Python, the agent design described in the
accompanying analysis: a fixed base "portfolio" of crops/animals that is only
deviated from when the market/opponent situation makes the deviation clearly
worth it (crowding avoidance + town demand pull), combined with safety-first
task prioritization (feed > emergency watering > harvest > watering > weeding >
planting) and BFS-based worker routing.

IMPORTANT — schema assumption
------------------------------
No concrete `obs` schema or action wire-format was supplied with the original
description (only prose + isolated code fragments, and the snippet was cut off
mid-function). To produce something that actually runs, this file assumes the
following shapes. Adjust `_read_*` / `_emit_*` helpers at the bottom if your
real environment differs — the strategic logic (sections 1-17 of the writeup)
lives entirely above those adapters and does not need to change.

    obs = {
        "step": int,
        "day": int,                 # 0-indexed, match runs ~30 days (0..29)
        "hour": int,                # 0..23
        "coins": int,
        "land": {                   # region -> list of tile dicts
            "NW": [
                {
                    "x": int, "y": int, "region": "NW",
                    "kind": "CROP" | "ANIMAL" | "EMPTY" | "LOCKED",
                    "crop": "MELON" | ... | None,
                    "planted_day": int | None,
                    "growth_days_needed": int | None,
                    "watered_today": bool,
                    "wilt_risk": bool,          # true if about to die without water
                    "has_weeds": bool,
                    "ready_to_harvest": bool,
                    "animal": "COW" | "SHEEP" | None,
                    "fed_today": bool,
                    "cared_today": bool,
                    "has_pasture": bool,
                    "fertilizer_ready": bool,
                },
                ...
            ],
            "NE": [...], "SW": [...], "SE": [...],
        },
        "owned_regions": ["NW"],
        "shed": {"x": int, "y": int, "region": "NW"},
        "farmer": {"x": int, "y": int, "region": "NW", "carrying": str | None},
        "hands": [
            {"id": int, "x": int, "y": int, "region": "NW", "carrying": str | None},
            ...
        ],
        "inventory": {"WHEAT": int, "MELON_SEED": int, ..., "COW": int, "SHEEP": int},
        "market": {"prices": {"MELON": float, "STRAWBERRY": float, ..., "MILK": float,
                               "WOOL": float, "FERTILIZER": float, "EGG": float}},
        "town": {"shops_unlocked": ["YARN_STORE", "SMOOTHIE_SHOP", ...]},
        "rival": {
            "crop_tiles": {"MELON": int, "STRAWBERRY": int, ...},
            "animal_counts": {"COW": int, "SHEEP": int},
        },
        "land_offers": {"NE": {"price": int, "available": bool}, "SW": {...}, "SE": {...}},
    }

    action = {
        "farmer": [str, ...],           # token list, e.g. ["MOVE_RIGHT", "HARVEST"]
        "hands": [[str, ...], ...],     # one token list per hand, same order as obs["hands"]
        "market": [
            {"action": "SELL", "item": "MILK", "qty": 12},
            {"action": "BUY_SEED", "item": "MELON", "qty": 4},
            {"action": "BUY_ANIMAL", "item": "COW", "qty": 2},
            {"action": "BUY_LAND", "region": "NE"},
            {"action": "HIRE", "qty": 3},
        ],
    }
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# 1. Static knowledge: yields, prices, seed costs, growth windows
# ---------------------------------------------------------------------------

CROPS = ("MELON", "STRAWBERRY", "CARROT", "WHEAT", "TOMATO")

CONSERVATIVE_YIELD: Dict[str, float] = {
    "MELON": 3.0,
    "STRAWBERRY": 4.0,
    "CARROT": 5.0,
    "WHEAT": 6.0,
    "TOMATO": 4.0,
}

BASE_PRODUCT_PRICE: Dict[str, float] = {
    "MELON": 55.0,
    "STRAWBERRY": 28.0,
    "CARROT": 14.0,
    "WHEAT": 9.0,
    "TOMATO": 24.0,
    "MILK": 30.0,
    "WOOL": 34.0,
    "EGG": 6.0,
    "FERTILIZER": 8.0,
}

SEED_COST: Dict[str, float] = {
    "MELON": 40.0,
    "STRAWBERRY": 22.0,
    "CARROT": 8.0,
    "WHEAT": 4.0,
    "TOMATO": 18.0,
}

GROWTH_DAYS: Dict[str, int] = {
    "MELON": 6,
    "STRAWBERRY": 4,
    "CARROT": 3,
    "WHEAT": 3,
    "TOMATO": 5,
}

# Seeds we are willing to buy. NOTE: the original description explicitly flags
# that TOMATO is a candidate in _adaptive_crop but was missing here, which
# means an adaptive switch to TOMATO could never actually be planted. Fixed.
SEED_SHOPPING_LIST: Tuple[str, ...] = ("MELON", "STRAWBERRY", "TOMATO", "CARROT", "WHEAT")

# ---------------------------------------------------------------------------
# 2. Base portfolio (fixed layout), keyed by region -> ((crop, count), ...)
# ---------------------------------------------------------------------------

BASE_MIXES: Dict[str, Tuple[Tuple[str, int], ...]] = {
    "NW": (("MELON", 11), ("STRAWBERRY", 5), ("CARROT", 2), ("WHEAT", 4)),
    "NE": (("STRAWBERRY", 14), ("MELON", 4), ("WHEAT", 3)),
    "SW": (("STRAWBERRY", 20), ("MELON", 2), ("CARROT", 3)),
    "SE": (("STRAWBERRY", 18), ("MELON", 3), ("WHEAT", 4)),
}

ANIMAL_SLOTS_PER_REGION: Dict[str, int] = {"NW": 4, "NE": 5, "SW": 3}
BASE_ANIMAL_TARGET = 4         # before expansion: 2 cows + 2 sheep
EXPANDED_ANIMAL_TARGET = 9     # after expansion: 9 total, split by _herd_target

SELL_ORDER: Tuple[str, ...] = (
    "MILK",
    "FERTILIZER",
    "MELON",
    "STRAWBERRY",
    "TOMATO",
    "CARROT",
    "WHEAT",
    "EGG",
    "WOOL",
)

SELL_CAP_EARLY: Dict[str, int] = {
    "MILK": 20,
    "WOOL": 20,
    "FERTILIZER": 20,
}
SELL_CAP_DEFAULT_EARLY = 28
SELL_CAP_FREE_FROM_DAY = 28  # from this day on, sell everything

WHEAT_PER_ANIMAL_RESERVE = 3
WHEAT_RESERVE_UNTIL_DAY = 29

# Land purchase economics. LAND_DAY / EXPANSION_DEADLINE / EXPANSION_BUFFER
# mirror constants that existed in the original source but were dead code
# (defined, never read by the real purchase logic). We keep them for
# documentation parity but drive purchases off the *_TRIGGER_DAY constants
# below, which match the described behavior (day>=5 first plot, day>=9
# second plot, stop trying after day 18, keep a 300/500 coin buffer).
LAND_DAY = 4                 # unused by design (kept for parity with source)
EXPANSION_DEADLINE = 16      # unused by design (kept for parity with source)
EXPANSION_BUFFER = 500       # unused by design (kept for parity with source)

LAND_FIRST_PURCHASE_DAY = 5
LAND_SECOND_PURCHASE_DAY = 9
LAND_PURCHASE_HARD_DEADLINE = 18
LAND_BUFFER_FIRST = 500
LAND_BUFFER_SECOND = 300
MAX_LAND_PURCHASES = 2

ANIMAL_BUY_CHUNK = 2
ANIMAL_BUY_COIN_BUFFER = 220
ANIMAL_PURCHASE_DEADLINE_DAY = 28

# Improvement noted in the writeup (section 13): without a per-species
# last-buy-day, cows/sheep purchased in the final days never pay back
# (cows need 8 days to first produce, sheep need 6). We add that cutoff.
ANIMAL_LAST_BUY_DAY = {"COW": 19, "SHEEP": 21}

HIRE_TARGET_HANDS = 10
HIRE_HOUR_WINDOW = (0, 3)  # inclusive hours during which hiring happens
HIRE_STOP_FROM_DAY = 28

FINAL_DAY = 29
RETURN_TO_SHED_HOUR = 14

DIVERSIFICATION_TOP_K = 3
DIVERSIFICATION_THRESHOLD = 0.90
DIVERSIFICATION_MAX_CHOICES = 2

ADAPTIVE_PRICE_DAMAGE_RATIO = 0.58
ADAPTIVE_RIVAL_CROWD_TILES = 14
ADAPTIVE_SCORE_GAP = 1.28

CROWD_FACTOR_K = 0.045
DEMAND_FACTOR_K = 0.045
PRICE_FACTOR_FLOOR = 0.70
PRICE_FACTOR_GAIN = 0.30
PRICE_FACTOR_CAP = 1.35

MILK_BASE_PRICE_FOR_SIGNAL = 160.0
WOOL_BASE_PRICE_FOR_SIGNAL = 160.0
MILK_DEMAND_K = 0.07
WOOL_DEMAND_K = 0.07
RIVAL_ANIMAL_CROWD_K = 0.11

HERD_ROUTE_MILK_HEAVY_RATIO = 1.18
HERD_ROUTE_WOOL_HEAVY_RATIO = 0.92
HERD_ROUTE_MILK_HEAVY = (7, 2)
HERD_ROUTE_WOOL_HEAVY = (2, 7)
HERD_ROUTE_NEUTRAL = (5, 4)

CARE_LAST_DAY = 27
CARE_MIN_PRICE = 20.0

DIRECTIONS: Tuple[Tuple[str, int, int], ...] = (
    ("MOVE_UP", 0, -1),
    ("MOVE_DOWN", 0, 1),
    ("MOVE_LEFT", -1, 0),
    ("MOVE_RIGHT", 1, 0),
)

# ---------------------------------------------------------------------------
# 3. Global, cross-turn state (reset when a new episode is detected)
# ---------------------------------------------------------------------------

_MARKET_ROUTE: Optional[Tuple[int, int]] = None  # (cow_target, sheep_target)
_LAST_STEP: int = 0


def _reset_state_if_new_episode(step: int) -> None:
    global _MARKET_ROUTE, _LAST_STEP
    if step == 0 and _LAST_STEP > 0:
        _MARKET_ROUTE = None
    _LAST_STEP = step


# ---------------------------------------------------------------------------
# 4. Small observation helpers
# ---------------------------------------------------------------------------

def _phase(day: int) -> str:
    if day <= 7:
        return "BOOTSTRAP"
    if day <= 21:
        return "COMPOUND"
    if day <= 27:
        return "HARVEST"
    return "LIQUIDATE"


def _all_tiles(obs: Dict[str, Any]):
    for region in obs.get("owned_regions", ()):
        for tile in obs.get("land", {}).get(region, ()):
            yield tile


def _town_pull(crop: str, obs: Dict[str, Any]) -> float:
    """Forward-looking demand signal contributed by shops the town has unlocked."""
    shops = set(obs.get("town", {}).get("shops_unlocked", ()))
    pull = 0.0
    if crop in ("STRAWBERRY", "MELON") and "SMOOTHIE_SHOP" in shops:
        pull += 1.0
    if crop in ("WHEAT",) and "BAKERY" in shops:
        pull += 1.0
    if crop in ("TOMATO",) and "SAUCE_STAND" in shops:
        pull += 0.6
    if crop in ("CARROT",) and "MARKET_STALL" in shops:
        pull += 0.4
    return pull


def _visible_rival_crops(obs: Dict[str, Any], crop: str) -> int:
    return int(obs.get("rival", {}).get("crop_tiles", {}).get(crop, 0))


def _current_price(obs: Dict[str, Any], item: str) -> float:
    return float(obs.get("market", {}).get("prices", {}).get(item, BASE_PRODUCT_PRICE.get(item, 0.0)))


# ---------------------------------------------------------------------------
# 5. Crop scoring & adaptive substitution
# ---------------------------------------------------------------------------

def _crop_rate(crop: str, obs: Dict[str, Any], day: int) -> float:
    """CropRate = ((yield*price - seed) * crowd_factor * demand_factor * price_factor) / days."""
    price = _current_price(obs, crop)
    seed = SEED_COST[crop]
    gross = CONSERVATIVE_YIELD[crop] * price - seed

    rival_tiles = _visible_rival_crops(obs, crop)
    crowd_factor = 1.0 / (1.0 + CROWD_FACTOR_K * rival_tiles)

    demand_factor = 1.0 + DEMAND_FACTOR_K * _town_pull(crop, obs)

    base_price = BASE_PRODUCT_PRICE[crop]
    price_factor = PRICE_FACTOR_FLOOR + PRICE_FACTOR_GAIN * min(
        PRICE_FACTOR_CAP, price / base_price if base_price else 0.0
    )

    days = max(1, GROWTH_DAYS[crop])
    remaining = max(0, FINAL_DAY - day)
    if remaining < days:
        # Can't mature and be harvested before the match ends: worthless.
        return float("-inf")

    return (gross * crowd_factor * demand_factor * price_factor) / days


def _adaptive_crop(region: str, slot_key: int, planned: str, obs: Dict[str, Any]) -> str:
    """Only deviate from the fixed portfolio when the case is clear-cut."""
    day = int(obs.get("day", 0))
    planned_price = _current_price(obs, planned)
    planned_score = _crop_rate(planned, obs, day)

    planted_day = None
    for tile in obs.get("land", {}).get(region, ()):
        if tile.get("kind") == "EMPTY" and tile.get("slot_key") == slot_key:
            planted_day = tile.get("last_planted_day")
            break

    plant_deadline_passed = (
        planted_day is not None and day - planted_day > GROWTH_DAYS.get(planned, 0) + 2
    )
    damaged = planned_price <= ADAPTIVE_PRICE_DAMAGE_RATIO * BASE_PRODUCT_PRICE[planned]
    crowded = _visible_rival_crops(obs, planned) >= ADAPTIVE_RIVAL_CROWD_TILES

    ranked = sorted(
        ((_crop_rate(c, obs, day), c) for c in CROPS),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best_crop = ranked[0]
    material_gap = best_score >= ADAPTIVE_SCORE_GAP * max(1.0, planned_score)

    if not (plant_deadline_passed or damaged or crowded or material_gap):
        return planned

    diversified = [
        crop
        for score, crop in ranked[:DIVERSIFICATION_TOP_K]
        if score >= DIVERSIFICATION_THRESHOLD * best_score
    ]
    if not diversified:
        return best_crop
    choices = min(DIVERSIFICATION_MAX_CHOICES, len(diversified))
    return diversified[slot_key % choices]


def _crop_plan(obs: Dict[str, Any]) -> Dict[Tuple[str, int], str]:
    """Expand BASE_MIXES into a concrete per-slot crop plan, adapting where warranted."""
    plan: Dict[Tuple[str, int], str] = {}
    for region in obs.get("owned_regions", ()):
        mix = BASE_MIXES.get(region, ())
        slot_key = 0
        for crop, count in mix:
            for _ in range(count):
                plan[(region, slot_key)] = _adaptive_crop(region, slot_key, crop, obs)
                slot_key += 1
    return plan


# ---------------------------------------------------------------------------
# 6. Herd sizing (decided once per episode, then frozen)
# ---------------------------------------------------------------------------

def _herd_target(obs: Dict[str, Any]) -> Tuple[int, int]:
    global _MARKET_ROUTE
    if _MARKET_ROUTE is not None:
        return _MARKET_ROUTE

    if len(obs.get("owned_regions", ())) <= 1:
        # Pre-expansion: fixed 2 cows / 2 sheep, no market read yet.
        return (2, 2)

    milk_price = _current_price(obs, "MILK")
    wool_price = _current_price(obs, "WOOL")
    milk_demand = _town_pull("MILK_PRODUCT", obs) or (
        1.0 if "SMOOTHIE_SHOP" in obs.get("town", {}).get("shops_unlocked", ()) else 0.0
    )
    wool_demand = 1.0 if "YARN_STORE" in obs.get("town", {}).get("shops_unlocked", ()) else 0.0
    rival_cows = int(obs.get("rival", {}).get("animal_counts", {}).get("COW", 0))
    rival_sheep = int(obs.get("rival", {}).get("animal_counts", {}).get("SHEEP", 0))

    milk_signal = (
        milk_price / MILK_BASE_PRICE_FOR_SIGNAL
        * (1 + MILK_DEMAND_K * milk_demand)
        / (1 + RIVAL_ANIMAL_CROWD_K * rival_cows)
    )
    wool_signal = (
        wool_price / WOOL_BASE_PRICE_FOR_SIGNAL
        * (1 + WOOL_DEMAND_K * wool_demand)
        / (1 + RIVAL_ANIMAL_CROWD_K * rival_sheep)
    )

    ratio = milk_signal / wool_signal if wool_signal else float("inf")
    if ratio >= HERD_ROUTE_MILK_HEAVY_RATIO:
        _MARKET_ROUTE = HERD_ROUTE_MILK_HEAVY
    elif ratio <= HERD_ROUTE_WOOL_HEAVY_RATIO:
        _MARKET_ROUTE = HERD_ROUTE_WOOL_HEAVY
    else:
        _MARKET_ROUTE = HERD_ROUTE_NEUTRAL
    return _MARKET_ROUTE


def _animal_slots(obs: Dict[str, Any]) -> List[Tuple[str, int, int]]:
    """(region, x, y) candidate slots, ordered close-to-shed first, per region."""
    shed = obs.get("shed", {})
    slots: List[Tuple[str, int, int]] = []
    for region, cap in ANIMAL_SLOTS_PER_REGION.items():
        if region not in obs.get("owned_regions", ()):
            continue
        tiles = [t for t in obs.get("land", {}).get(region, ()) if t.get("kind") in ("EMPTY", "ANIMAL")]
        tiles.sort(key=lambda t: abs(t["x"] - shed.get("x", 0)) + abs(t["y"] - shed.get("y", 0)))
        for tile in tiles[:cap]:
            slots.append((region, tile["x"], tile["y"]))
    return slots


# ---------------------------------------------------------------------------
# 7. Task generation
# ---------------------------------------------------------------------------

Task = Dict[str, Any]


def _add(tasks: List[Task], priority: int, pos: Tuple[int, int], tokens: List[str], required_item: Optional[str] = None) -> None:
    tasks.append({"priority": priority, "pos": pos, "tokens": tokens, "requires": required_item})


def _animal_tasks(obs: Dict[str, Any], herd_target: Tuple[int, int]) -> List[Task]:
    tasks: List[Task] = []
    day = int(obs.get("day", 0))

    cow_target, sheep_target = herd_target
    owned_cows = int(obs.get("inventory", {}).get("COW", 0))
    owned_sheep = int(obs.get("inventory", {}).get("SHEEP", 0))
    slots = _animal_slots(obs)
    animal_tiles = [t for t in _all_tiles(obs) if t.get("kind") == "ANIMAL"]

    for tile in animal_tiles:
        pos = (tile["x"], tile["y"])
        animal = tile.get("animal")

        if not tile.get("has_pasture", True):
            _add(tasks, 0, pos, ["BUILD_PASTURE"])
            continue

        if animal is None:
            if owned_cows > 0 and (owned_cows, owned_sheep) >= (1, 0):
                _add(tasks, 0, pos, ["PLACE:COW"], "COW")
            elif owned_sheep > 0:
                _add(tasks, 0, pos, ["PLACE:SHEEP"], "SHEEP")
            continue

        if tile.get("blocking_obstacle"):
            _add(tasks, 0, pos, ["CLEAR"])

        if not tile.get("fed_today", False):
            _add(tasks, 0, pos, ["FEED"], "WHEAT")

        if tile.get("fertilizer_ready"):
            _add(tasks, 1, pos, ["COLLECT_FERTILIZER"])

        if tile.get("ready_to_harvest"):
            _add(tasks, 1, pos, ["HARVEST"])

        product = "MILK" if animal == "COW" else "WOOL"
        price = _current_price(obs, product)
        cared_today = tile.get("cared_today", False)
        if day <= CARE_LAST_DAY and price >= CARE_MIN_PRICE and not cared_today:
            _add(tasks, 2, pos, ["CARE"])

    del slots  # slots are consulted by placement/purchase logic elsewhere
    return tasks


def _crop_tasks(obs: Dict[str, Any], plan: Dict[Tuple[str, int], str]) -> List[Task]:
    tasks: List[Task] = []
    hour = int(obs.get("hour", 0))

    for region in obs.get("owned_regions", ()):
        for tile in obs.get("land", {}).get(region, ()):
            if tile.get("kind") == "LOCKED":
                continue
            pos = (tile["x"], tile["y"])

            if tile.get("kind") == "CROP":
                wilting = tile.get("wilt_risk", False)
                needs_evening_water = hour >= 18 and not tile.get("watered_today", False)
                if wilting or needs_evening_water:
                    _add(tasks, 3, pos, ["WATER"])
                    continue

                if tile.get("ready_to_harvest"):
                    _add(tasks, 4, pos, ["HARVEST"])
                    continue

                if not tile.get("watered_today", False):
                    _add(tasks, 5, pos, ["WATER"])
                    continue

                if tile.get("has_weeds"):
                    _add(tasks, 7, pos, ["WEED"])
                    continue

            elif tile.get("kind") == "EMPTY":
                slot_key = tile.get("slot_key")
                crop = plan.get((region, slot_key))
                if crop:
                    _add(tasks, 8, pos, [f"PLANT:{crop}"], f"{crop}_SEED")

    return tasks


# ---------------------------------------------------------------------------
# 8. Movement (BFS avoiding LOCKED tiles)
# ---------------------------------------------------------------------------

def _passable(obs: Dict[str, Any], region: str, x: int, y: int) -> bool:
    for tile in obs.get("land", {}).get(region, ()):
        if tile["x"] == x and tile["y"] == y:
            return tile.get("kind") != "LOCKED"
    return True


def _dist(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _bfs_path(obs: Dict[str, Any], region: str, source: Tuple[int, int], target: Tuple[int, int]) -> List[str]:
    """Shortest-path token list from source to target, avoiding LOCKED tiles.

    Among equal-length options, prefers directions that reduce Manhattan
    distance to the target first, so ties resolve toward natural-looking
    movement rather than an arbitrary BFS order.
    """
    if source == target:
        return []

    q: deque = deque([source])
    came_from: Dict[Tuple[int, int], Tuple[Tuple[int, int], str]] = {}
    visited = {source}

    while q:
        cur = q.popleft()
        if cur == target:
            break
        ordered_dirs = sorted(
            DIRECTIONS,
            key=lambda d: _dist((cur[0] + d[1], cur[1] + d[2]), target),
        )
        for token, dx, dy in ordered_dirs:
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt in visited:
                continue
            if not _passable(obs, region, *nxt):
                continue
            visited.add(nxt)
            came_from[nxt] = (cur, token)
            q.append(nxt)

    if target not in came_from and target != source:
        return []

    tokens: List[str] = []
    node = target
    while node != source:
        prev, token = came_from[node]
        tokens.append(token)
        node = prev
    tokens.reverse()
    return tokens


def _move(obs: Dict[str, Any], region: str, source: Tuple[int, int], target: Tuple[int, int]) -> List[str]:
    return _bfs_path(obs, region, source, target)


# ---------------------------------------------------------------------------
# 9. Worker <-> task assignment
# ---------------------------------------------------------------------------

def _shed_pos(obs: Dict[str, Any]) -> Tuple[int, int]:
    shed = obs.get("shed", {})
    return (shed.get("x", 0), shed.get("y", 0))


def _assignment_cost(obs: Dict[str, Any], worker: Dict[str, Any], task: Task) -> int:
    pos = (worker["x"], worker["y"])
    target = task["pos"]
    region = worker.get("region", "NW")
    required = task.get("requires")

    if required and worker.get("carrying") != required:
        shed = _shed_pos(obs)
        return _dist(pos, shed) + 1 + _dist(shed, target)
    return _dist(pos, target)


def _unit_actions(obs: Dict[str, Any], tasks: List[Task]) -> List[List[str]]:
    workers: List[Dict[str, Any]] = list(obs.get("hands", ()))
    farmer = obs.get("farmer")
    if farmer is not None:
        workers = [farmer] + workers

    remaining_tasks = list(enumerate(tasks))
    remaining_workers = set(range(len(workers)))
    actions: List[List[str]] = [["PASS"] for _ in workers]

    while remaining_tasks and remaining_workers:
        best_key = None
        best_choice = None
        for task_idx, task in remaining_tasks:
            for worker_idx in remaining_workers:
                worker = workers[worker_idx]
                cost = _assignment_cost(obs, worker, task)
                key = (task["priority"], cost, task["pos"][1], task["pos"][0], worker_idx, task_idx)
                if best_key is None or key < best_key:
                    best_key = key
                    best_choice = (worker_idx, task_idx, task)

        if best_choice is None:
            break

        worker_idx, task_idx, task = best_choice
        worker = workers[worker_idx]
        region = worker.get("region", "NW")
        pos = (worker["x"], worker["y"])
        required = task.get("requires")

        tokens: List[str] = []
        if required and worker.get("carrying") != required:
            shed = _shed_pos(obs)
            tokens += _move(obs, region, pos, shed)
            tokens.append(f"PICKUP:{required}")
            tokens += _move(obs, region, shed, task["pos"])
        else:
            tokens += _move(obs, region, pos, task["pos"])
        tokens += task["tokens"]

        actions[worker_idx] = tokens or ["PASS"]
        remaining_workers.discard(worker_idx)
        remaining_tasks = [(i, t) for i, t in remaining_tasks if i != task_idx]

    return actions


# ---------------------------------------------------------------------------
# 10. Market actions: selling, land, animals, seeds, hiring
# ---------------------------------------------------------------------------

def _sell_actions(obs: Dict[str, Any]) -> List[Dict[str, Any]]:
    day = int(obs.get("day", 0))
    inventory = obs.get("inventory", {})
    orders: List[Dict[str, Any]] = []

    for item in SELL_ORDER:
        have = int(inventory.get(item, 0))
        if have <= 0:
            continue

        if item == "WHEAT" and day < WHEAT_RESERVE_UNTIL_DAY:
            animal_count = int(inventory.get("COW", 0)) + int(inventory.get("SHEEP", 0))
            reserve = WHEAT_PER_ANIMAL_RESERVE * animal_count
            sellable = max(0, have - reserve)
        elif day >= SELL_CAP_FREE_FROM_DAY:
            sellable = have
        else:
            cap = SELL_CAP_EARLY.get(item, SELL_CAP_DEFAULT_EARLY)
            sellable = min(have, cap)

        if sellable > 0:
            orders.append({"action": "SELL", "item": item, "qty": sellable})

    return orders


def _land_purchase_actions(obs: Dict[str, Any]) -> List[Dict[str, Any]]:
    day = int(obs.get("day", 0))
    coins = int(obs.get("coins", 0))
    owned = list(obs.get("owned_regions", ()))
    offers = obs.get("land_offers", {})

    if day > LAND_PURCHASE_HARD_DEADLINE or len(owned) - 1 >= MAX_LAND_PURCHASES:
        return []

    purchases_so_far = len(owned) - 1  # NW is the starting region
    if purchases_so_far == 0 and day < LAND_FIRST_PURCHASE_DAY:
        return []
    if purchases_so_far == 1 and day < LAND_SECOND_PURCHASE_DAY:
        return []

    buffer = LAND_BUFFER_FIRST if purchases_so_far == 0 else LAND_BUFFER_SECOND

    best_region = None
    best_price = None
    for region, offer in offers.items():
        if region in owned or not offer.get("available"):
            continue
        price = offer.get("price", float("inf"))
        if coins - price < buffer:
            continue
        if best_price is None or price < best_price:
            best_price, best_region = price, region

    if best_region is None:
        return []
    return [{"action": "BUY_LAND", "region": best_region}]


def _animal_purchase_actions(obs: Dict[str, Any], herd_target: Tuple[int, int]) -> List[Dict[str, Any]]:
    day = int(obs.get("day", 0))
    if day >= ANIMAL_PURCHASE_DEADLINE_DAY:
        return []

    coins = int(obs.get("coins", 0))
    inventory = obs.get("inventory", {})
    target_by_species = {"COW": herd_target[0], "SHEEP": herd_target[1]}
    prices = {"COW": _current_price(obs, "COW_PRICE"), "SHEEP": _current_price(obs, "SHEEP_PRICE")}

    orders: List[Dict[str, Any]] = []
    for species, target in target_by_species.items():
        if day > ANIMAL_LAST_BUY_DAY.get(species, day):
            continue
        owned = int(inventory.get(species, 0))
        missing = max(0, target - owned)
        if missing <= 0:
            continue
        unit_price = prices[species] or 1.0
        affordable = max(0, int((coins - ANIMAL_BUY_COIN_BUFFER) // unit_price))
        quantity = min(missing, ANIMAL_BUY_CHUNK, affordable)
        if quantity > 0:
            orders.append({"action": "BUY_ANIMAL", "item": species, "qty": quantity})
            coins -= int(quantity * unit_price)

    return orders


def _seed_purchase_actions(obs: Dict[str, Any], plan: Dict[Tuple[str, int], str]) -> List[Dict[str, Any]]:
    coins = int(obs.get("coins", 0))
    needed: Dict[str, int] = {}
    inventory = obs.get("inventory", {})

    for (region, slot_key), crop in plan.items():
        if crop not in SEED_SHOPPING_LIST:
            continue
        tiles = obs.get("land", {}).get(region, ())
        is_empty_here = any(
            t.get("kind") == "EMPTY" and t.get("slot_key") == slot_key for t in tiles
        )
        if is_empty_here:
            needed[crop] = needed.get(crop, 0) + 1

    orders: List[Dict[str, Any]] = []
    for crop in SEED_SHOPPING_LIST:
        want = needed.get(crop, 0)
        have = int(inventory.get(f"{crop}_SEED", 0))
        to_buy = max(0, want - have)
        if to_buy <= 0:
            continue
        cost = SEED_COST[crop]
        affordable = int(coins // cost) if cost else to_buy
        quantity = min(to_buy, affordable)
        if quantity > 0:
            orders.append({"action": "BUY_SEED", "item": crop, "qty": quantity})
            coins -= int(quantity * cost)

    return orders


def _hire_actions(obs: Dict[str, Any]) -> List[Dict[str, Any]]:
    day = int(obs.get("day", 0))
    hour = int(obs.get("hour", 0))
    if day >= HIRE_STOP_FROM_DAY:
        return []
    if not (HIRE_HOUR_WINDOW[0] <= hour <= HIRE_HOUR_WINDOW[1]):
        return []

    current = len(obs.get("hands", ()))
    missing = max(0, HIRE_TARGET_HANDS - current)
    if missing <= 0:
        return []
    return [{"action": "HIRE", "qty": missing}]


def _market_actions(obs: Dict[str, Any], plan: Dict[Tuple[str, int], str], herd_target: Tuple[int, int]) -> List[Dict[str, Any]]:
    day = int(obs.get("day", 0))
    orders: List[Dict[str, Any]] = []

    orders += _sell_actions(obs)

    if day < SELL_CAP_FREE_FROM_DAY:
        orders += _land_purchase_actions(obs)
        orders += _animal_purchase_actions(obs, herd_target)
        orders += _seed_purchase_actions(obs, plan)
        orders += _hire_actions(obs)

    return orders


# ---------------------------------------------------------------------------
# 11. Endgame liquidation
# ---------------------------------------------------------------------------

def _liquidation_actions(obs: Dict[str, Any]) -> Optional[List[List[str]]]:
    day = int(obs.get("day", 0))
    hour = int(obs.get("hour", 0))
    if day < FINAL_DAY or hour < RETURN_TO_SHED_HOUR:
        return None

    workers: List[Dict[str, Any]] = list(obs.get("hands", ()))
    farmer = obs.get("farmer")
    if farmer is not None:
        workers = [farmer] + workers

    shed = _shed_pos(obs)
    actions: List[List[str]] = []
    for worker in workers:
        region = worker.get("region", "NW")
        pos = (worker["x"], worker["y"])
        tokens = _move(obs, region, pos, shed)
        if worker.get("carrying"):
            tokens.append("DROP")
        actions.append(tokens or ["PASS"])
    return actions


# ---------------------------------------------------------------------------
# 12. Top-level orchestration
# ---------------------------------------------------------------------------

def _agent_impl(obs: Dict[str, Any]) -> Dict[str, Any]:
    step = int(obs.get("step", 0))
    _reset_state_if_new_episode(step)

    day = int(obs.get("day", 0))
    hour = int(obs.get("hour", 0))

    liquidation = _liquidation_actions(obs)
    if liquidation is not None:
        farmer_tokens, hand_tokens = liquidation[0], liquidation[1:]
        market_orders = _sell_actions(obs) if day < FINAL_DAY else []
        return {"farmer": farmer_tokens, "hands": hand_tokens, "market": market_orders}

    herd_target = _herd_target(obs)
    plan = _crop_plan(obs)

    tasks = _animal_tasks(obs, herd_target) + _crop_tasks(obs, plan)
    all_actions = _unit_actions(obs, tasks)

    farmer_tokens = all_actions[0] if obs.get("farmer") is not None else ["PASS"]
    hand_tokens = all_actions[1:] if obs.get("farmer") is not None else all_actions

    market_orders = _market_actions(obs, plan, herd_target)

    return {
        "farmer": farmer_tokens,
        "hands": hand_tokens,
        "market": market_orders,
    }


def agent(obs: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point. Never lets the game crash: falls back to an all-PASS turn."""
    try:
        return _agent_impl(obs)
    except Exception:
        hand_count = len(obs.get("hands", ())) if isinstance(obs, dict) else 0
        return {
            "farmer": ["PASS"],
            "hands": [["PASS"] for _ in range(hand_count)],
            "market": [],
        }
