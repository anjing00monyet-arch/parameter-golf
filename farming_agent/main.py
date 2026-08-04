"""Market Shadow Diversification -- a Kaggriculture rule-based agent.

Strategy summary: keep a fixed base crop/animal portfolio per farm tile
(spread across cheap staples and premium ongoing crops), but deviate from it
only when the market/opponent picture makes the deviation clearly worth it
(the opponent is crowding a crop, the sale price has cratered, or a
newly-unlocked town shop makes something else clearly better). Task
priorities are safety-first: prevent weeds/escapes, then harvest, then
routine care, then expansion/planting.

Kaggriculture gives each farmer/hand exactly ONE op per turn (movement and
interactions are separate turns -- there is no queued multi-step action).
So instead of planning a full path in one shot, this agent recomputes the
best task for every unit fresh each turn and emits a single step toward it:
a move if not there yet, the interaction itself once in place. Because the
task scoring is a deterministic function of the (stable) game state, a unit
naturally keeps converging on the same task turn over turn until it's done.

Grounded directly in kaggriculture.py (crop/animal tables, market params,
shop demand, turn order) -- see CROP_META / ANIMAL_META / SHOPS below.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. Ground-truth game constants (mirrors kaggriculture.py)
# ---------------------------------------------------------------------------

BOARD_SIZE_DEFAULT = 10
TURNS_PER_DAY_DEFAULT = 24
SEASON_DAYS = 30
FINAL_DAY = SEASON_DAYS - 1  # 29

CROP_META: Dict[str, Dict[str, Any]] = {
    "WHEAT":      {"seed": 10, "first_yield_day": 2,  "max_yield_day": 4,  "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20, "first_yield_day": 2,  "max_yield_day": 3,  "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50, "first_yield_day": 8,  "max_yield_day": 8,  "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first_yield_day": 10, "max_yield_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80, "first_yield_day": 10, "max_yield_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}

ANIMAL_META: Dict[str, Dict[str, Any]] = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}
PRODUCT_OF_ANIMAL = {a: m["product"] for a, m in ANIMAL_META.items()}
STRUCTURE_OF_ANIMAL = {a: m["structure"] for a, m in ANIMAL_META.items()}

BASE_PRICE = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250,
    "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100,
}
PRODUCTS = list(BASE_PRICE.keys())
SELLABLE_CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMAL_PRODUCTS = ("EGG", "MILK", "WOOL")

SHOPS: Dict[str, Tuple[str, ...]] = {
    "BAKERY":         ("EGG", "WHEAT"),
    "PIZZA_SHOP":     ("MILK", "TOMATO", "WHEAT"),
    "BRUNCH_SPOT":    ("EGG", "WHEAT", "STRAWBERRY"),
    "YARN_STORE":     ("WOOL",),
    "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"),
    "PET_CAFE":       ("CARROT",),
    "SMOOTHIE_SHOP":  ("STRAWBERRY", "MILK"),
    "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"),
}

LAND_ORDER = ("NE", "SW", "SE")
LAND_PRICES = (1000, 2000, 4000)

FARMER_MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}

# Approximate cycle length (plant/place -> last useful harvest) used only for
# relative scoring between crops, derived from the exact tables above.
def _crop_cycle_days(crop: str) -> int:
    m = CROP_META[crop]
    if m["ongoing"]:
        return m["first_yield_day"] + m["interval"] * (m["max_yield"] - 1) + 1
    return m["max_yield_day"] + 1


CROP_CYCLE_DAYS = {c: _crop_cycle_days(c) for c in CROP_META}

# Leaderboard-derived: across 20 top public submissions (avg final money
# $93k-$123k), essentially every one plants ONLY wheat/melon/strawberry --
# carrot and tomato appear only in the two lowest-scoring of the twenty, in
# small quantities, and correlate with materially worse outcomes. Likewise
# every top submission buys only cow+sheep (never goose, except again the
# two worst performers). Restricting the candidate set to what's actually
# proven to work beats trying to out-theorize it from the raw price table.
PLANTABLE_CROPS: Tuple[str, ...] = ("WHEAT", "MELON", "STRAWBERRY")
KEPT_ANIMALS: Tuple[str, ...] = ("COW", "SHEEP")

# ---------------------------------------------------------------------------
# 2. Base portfolio: a 5x5-local deterministic pattern per quadrant.
#    Index = (y % 5) * 5 + (x % 5) -> crop. Length must be 25.
# ---------------------------------------------------------------------------

def _expand_mix(counts: Tuple[Tuple[str, int], ...]) -> List[str]:
    pattern: List[str] = []
    for crop, n in counts:
        pattern.extend([crop] * n)
    while len(pattern) < 25:
        pattern.append(counts[0][0])
    return pattern[:25]


# Strawberry-dominant: melon's raw per-day margin looks best in isolation,
# but it's a one-time crop, so many melon tiles planted around the same time
# mature and dump onto the market together -- and melon's glut-side price
# function is brutally punishing (squared falloff, above_target=3.6). Top
# submissions instead lean heavily on strawberry: an *ongoing* crop whose
# per-tile production ticks are staggered by each tile's own planting day,
# so its sales trickle in continuously instead of arriving in one glut wave.
# Wheat stays present mainly for animal feed self-sufficiency plus fast,
# cheap cash cycling. Ratio (~60% strawberry / 24% melon / 16% wheat) is
# reverse-engineered from top submissions' seed-purchase volumes normalized
# by each crop's typical replant frequency.
BASE_MIXES: Dict[str, List[str]] = {
    "NW": _expand_mix((("STRAWBERRY", 15), ("MELON", 6), ("WHEAT", 4))),
    "NE": _expand_mix((("STRAWBERRY", 15), ("MELON", 6), ("WHEAT", 4))),
    "SW": _expand_mix((("STRAWBERRY", 15), ("MELON", 6), ("WHEAT", 4))),
    "SE": _expand_mix((("STRAWBERRY", 15), ("MELON", 6), ("WHEAT", 4))),
}

CROWD_FACTOR_K = 0.045
DEMAND_FACTOR_K = 0.09
PRICE_FACTOR_FLOOR = 0.70
PRICE_FACTOR_GAIN = 0.30
PRICE_FACTOR_CAP = 1.35

ADAPTIVE_PRICE_DAMAGE_RATIO = 0.58
ADAPTIVE_RIVAL_CROWD_TILES = 5
# Raised from the original 1.28: the base mix above already encodes a
# proven real-world ratio, not a naive per-day-rate ranking (which would
# wrongly rank wheat/melon above strawberry -- see the BASE_MIXES comment).
# Only deviate from it when the signal is very strong, not on every small
# score wobble.
ADAPTIVE_SCORE_GAP = 1.6
DIVERSIFICATION_THRESHOLD = 0.90
DIVERSIFICATION_MAX_CHOICES = 2
# Per-crop diversification ceiling, as a fraction of owned tiles. Melon
# keeps a tight cap (its own-glut risk is the highest of the three);
# strawberry gets room to be the dominant crop, matching observed play.
CROP_SHARE_CAP: Dict[str, float] = {"STRAWBERRY": 0.65, "MELON": 0.30, "WHEAT": 0.50}
CROP_SHARE_CAP_DEFAULT = 0.35

# Leaderboard-derived fixed cow:sheep ratio (COW/SHEEP purchase totals are
# consistently ~4:3 across every top submission, regardless of milk/wool
# spot prices at purchase time) -- simpler and more reliable than trying to
# re-derive it from a live market signal.
COW_SHEEP_RATIO = (4, 3)
# Total concurrent animal target once fully expanded, by number of owned
# quadrants -- derived from top submissions' total BUY_ANIMAL volume
# (cow+sheep totalled ~14 per game at 3 quadrants owned).
ANIMAL_SLOT_CAP_BY_QUADRANTS: Dict[int, int] = {1: 4, 2: 9, 3: 14, 4: 14}

WHEAT_FEED_RESERVE_DAYS = 4
# Leaderboard-derived: virtually every top submission buys land on exactly
# day 7 and day 10, and stops there -- nobody buys the third ($4000, SE)
# quadrant. With ~19 days left after day 10, its cost doesn't pay back in
# time; the 3-quadrant (75-tile) footprint is the real optimum, not 4.
LAND_FIRST_DAY, LAND_SECOND_DAY = 7, 10
LAND_HARD_DEADLINE = 22
MAX_LAND_PURCHASES = 2
LAND_BUFFER = (100, 150)

ANIMAL_BUY_BUFFER = 250
ANIMAL_LAST_BUY_DAY = {a: FINAL_DAY - m["first_yield_day"] for a, m in ANIMAL_META.items()}

HIRE_HOUR_WINDOW = (0, 5)
# Hire cost is fib-scaled (1, 1, 2, 3, 5, 8, ...) -- the first several hires
# on any given day are essentially free relative to what a hand can harvest
# and sell that same day, so this floor only needs to guard against actually
# going broke, not preserve a large cushion. A high floor here starves out
# recovery: a lean bank balance is exactly when the extra labor is needed
# most (to get tiles watered/harvested and cash flowing again).
HIRE_MONEY_FLOOR = 20
# Leaderboard-derived daily hire-count target (day 0..29), read directly off
# a top submission's actual per-day hire volume: ramps with land ownership
# (day 7 / day 10 jumps line up exactly with the two BUY_LAND days above),
# plateaus at 12 once all 3 quadrants are owned, tapers in the final days as
# there's less season left to capture a new hand's output.
HIRE_TARGET_SCHEDULE: Tuple[int, ...] = (
    4, 5, 6, 6, 6, 7, 6, 8, 10, 11,
    12, 12, 12, 12, 12, 12, 12, 12, 12, 12,
    12, 12, 12, 12, 12, 12, 12, 11, 10, 9,
)

MAX_MARKET_ORDERS = 10
BUY_STOP_DAY = 27
FERTILIZER_BUY_BATCH = 6
FERTILIZER_MONEY_FLOOR = 600

# ---------------------------------------------------------------------------
# 3. Cross-turn state (herd route frozen per episode, like the source design)
# ---------------------------------------------------------------------------

_HERD_ROUTE: Optional[Dict[str, int]] = None
_LAST_SEEN_DAY: int = -1
_LAST_SEEN_HOUR: int = -1


def _maybe_reset_episode_state(day: int, hour: int) -> None:
    global _HERD_ROUTE, _LAST_SEEN_DAY, _LAST_SEEN_HOUR
    if day == 0 and hour == 0 and (_LAST_SEEN_DAY, _LAST_SEEN_HOUR) != (-1, -1) and (_LAST_SEEN_DAY, _LAST_SEEN_HOUR) != (0, 0):
        _HERD_ROUTE = None
    _LAST_SEEN_DAY, _LAST_SEEN_HOUR = day, hour


# ---------------------------------------------------------------------------
# 4. Board / quadrant helpers
# ---------------------------------------------------------------------------

def _quadrant_of(x: int, y: int, board_size: int) -> str:
    half = board_size // 2
    return ("N" if y < half else "S") + ("W" if x < half else "E")


def _shed_access_tiles(board_size: int) -> List[Tuple[int, int]]:
    half = board_size // 2
    return [(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)]


def _passable(tiles, x: int, y: int, board_size: int) -> bool:
    if not (0 <= x < board_size and 0 <= y < board_size):
        return False
    return tiles[y][x] != "LOCKED"


def _dist(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _bfs_first_step(tiles, board_size: int, source: Tuple[int, int], target: Tuple[int, int]) -> Optional[str]:
    """Returns the movement op for the first step of the shortest path, or None if already there / unreachable."""
    if source == target:
        return None
    q = deque([source])
    came_from: Dict[Tuple[int, int], Tuple[Tuple[int, int], str]] = {}
    visited = {source}
    while q:
        cur = q.popleft()
        if cur == target:
            break
        for op, (dx, dy) in sorted(FARMER_MOVES.items(), key=lambda kv: _dist((cur[0] + kv[1][0], cur[1] + kv[1][1]), target)):
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt in visited or not _passable(tiles, nxt[0], nxt[1], board_size):
                continue
            visited.add(nxt)
            came_from[nxt] = (cur, op)
            q.append(nxt)
    if target not in came_from:
        return None
    node = target
    first_op = None
    while node != source:
        prev, op = came_from[node]
        first_op = op
        node = prev
    return first_op


def _nearest_shed_tile(tiles, board_size: int, pos: Tuple[int, int], owned: List[str]) -> Optional[Tuple[int, int]]:
    candidates = [t for t in _shed_access_tiles(board_size) if _quadrant_of(t[0], t[1], board_size) in owned]
    if not candidates:
        return None
    return min(candidates, key=lambda t: _dist(pos, t))


def _is_shed_adjacent(pos: Tuple[int, int], board_size: int) -> bool:
    return pos in set(_shed_access_tiles(board_size))


# ---------------------------------------------------------------------------
# 5. Market / demand reading
# ---------------------------------------------------------------------------

def _price(obs: Dict[str, Any], item: str) -> float:
    return float(obs.get("market", {}).get("prices", {}).get(item, BASE_PRICE.get(item, 1)))


def _town_pull(item: str, obs: Dict[str, Any]) -> float:
    shops = obs.get("town", {}).get("unlocked_shops", ())
    pull = 0.0
    for shop in shops:
        products = SHOPS.get(shop, ())
        if item in products:
            pull += 2.0 if len(products) == 1 else 1.0
    return pull


def _rival_farm(obs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    farms = obs.get("farms", [])
    player = obs.get("player", 0)
    rival_idx = 1 - player
    if 0 <= rival_idx < len(farms):
        return farms[rival_idx]
    return None


def _rival_crop_tiles(obs: Dict[str, Any], crop: str) -> int:
    rival = _rival_farm(obs)
    if rival is None:
        return 0
    count = 0
    for row in rival.get("tiles", ()):
        for tile in row:
            if isinstance(tile, dict) and tile.get("kind") == "PLANT" and tile.get("crop") == crop:
                count += 1
    return count


# ---------------------------------------------------------------------------
# 6. Crop scoring & adaptive tile planning
# ---------------------------------------------------------------------------

def _crop_rate(crop: str, obs: Dict[str, Any], day: int, own_committed: Dict[str, int], crop_cap: Dict[str, int]) -> float:
    meta = CROP_META[crop]

    # Hard diversification cap: melon's raw margin dwarfs everything else
    # (roughly 3-5x), so a *soft* crowding penalty can never talk it down
    # far enough to stop a pure-economics ranking from planting it on every
    # tile -- that would crash melon's own sale price the moment it's all
    # harvested at once. Once we've already committed crop_cap[crop] tiles
    # to a crop this pass, it's simply off the table for further new
    # plantings. Caps are per-crop (see CROP_SHARE_CAP) since strawberry's
    # own-glut risk is much lower than melon's.
    if own_committed.get(crop, 0) >= crop_cap.get(crop, 0):
        return float("-inf")

    price = _price(obs, crop)
    seed = meta["seed"]
    gross = meta["max_yield"] * price - seed

    rival_tiles = _rival_crop_tiles(obs, crop)
    own_tiles = own_committed.get(crop, 0)
    crowd_factor = 1.0 / (1.0 + CROWD_FACTOR_K * rival_tiles + CROWD_FACTOR_K * own_tiles)

    demand_factor = 1.0 + DEMAND_FACTOR_K * _town_pull(crop, obs)

    base = BASE_PRICE[crop]
    price_factor = PRICE_FACTOR_FLOOR + PRICE_FACTOR_GAIN * min(PRICE_FACTOR_CAP, price / base if base else 0.0)

    if day + meta["first_yield_day"] > FINAL_DAY:
        return float("-inf")

    days = max(1, CROP_CYCLE_DAYS[crop])
    return (gross * crowd_factor * demand_factor * price_factor) / days


def _plan_crop_for_tile(x: int, y: int, quadrant: str, obs: Dict[str, Any], day: int, own_committed: Dict[str, int], crop_cap: Dict[str, int]) -> str:
    mix = BASE_MIXES.get(quadrant, BASE_MIXES["NW"])
    idx = (y % 5) * 5 + (x % 5)
    planned = mix[idx]

    planned_price = _price(obs, planned)
    planned_score = _crop_rate(planned, obs, day, own_committed, crop_cap)
    damaged = planned_price <= ADAPTIVE_PRICE_DAMAGE_RATIO * BASE_PRICE[planned]
    crowded = _rival_crop_tiles(obs, planned) >= ADAPTIVE_RIVAL_CROWD_TILES
    capped_out = own_committed.get(planned, 0) >= crop_cap.get(planned, 0)

    ranked = sorted(((_crop_rate(c, obs, day, own_committed, crop_cap), c) for c in PLANTABLE_CROPS), key=lambda p: p[0], reverse=True)
    best_score, best_crop = ranked[0]
    if best_score == float("-inf"):
        return planned
    material_gap = best_score >= ADAPTIVE_SCORE_GAP * max(1.0, planned_score)

    if not (damaged or crowded or capped_out or material_gap):
        return planned

    diversified = [c for s, c in ranked[:3] if s >= DIVERSIFICATION_THRESHOLD * best_score]
    if not diversified:
        return best_crop
    choices = min(DIVERSIFICATION_MAX_CHOICES, len(diversified))
    return diversified[idx % choices]


# ---------------------------------------------------------------------------
# 7. Herd sizing & animal slot planning
# ---------------------------------------------------------------------------

def _animal_slot_cap_for(owned: List[str]) -> int:
    return ANIMAL_SLOT_CAP_BY_QUADRANTS.get(len(owned), 14)


def _herd_target(obs: Dict[str, Any], animal_slot_cap: int) -> Dict[str, int]:
    """Fixed cow:sheep ratio, goose excluded entirely.

    Leaderboard data shows every top submission converging on a ~4:3
    cow:sheep split regardless of milk/wool spot prices at purchase time,
    and never buying goose (the two lowest-scoring submissions of twenty
    were the only ones that did). A live market-reactive split was tried
    and discarded -- it doesn't beat this fixed ratio in practice, and the
    fixed version is simpler and more predictable.
    """
    global _HERD_ROUTE
    if _HERD_ROUTE is not None:
        return _HERD_ROUTE

    cow_share, sheep_share = COW_SHEEP_RATIO
    total_share = cow_share + sheep_share
    cow = max(1, round(animal_slot_cap * cow_share / total_share))
    sheep = max(1, animal_slot_cap - cow)

    _HERD_ROUTE = {"COW": cow, "SHEEP": sheep, "GOOSE": 0}
    return _HERD_ROUTE


def _animal_slot_plan(obs: Dict[str, Any], board_size: int, owned: List[str], herd_target: Dict[str, int]) -> List[Tuple[int, int, str]]:
    """Nearest-to-shed *empty* tiles assigned a target species, for NEW structures only.

    Every already-built structure (COOP/PASTURE, whether occupied yet or
    not) claims one unit of the target headcount permanently -- it must
    NOT be reissued as a fresh build slot on a different tile next turn,
    or this recomputes an unbounded number of "new" slots every turn and
    swallows the whole quadrant into empty coops/pastures that never get
    an animal, instead of leaving room to plant crops.
    """
    farm = obs["farms"][obs.get("player", 0)]
    tiles = farm["tiles"]
    shed_tiles = [t for t in _shed_access_tiles(board_size) if _quadrant_of(*t, board_size) in owned]

    existing_structures = 0
    existing_by_species: Dict[str, int] = {s: 0 for s in ANIMAL_META}
    for row in tiles:
        for tile in row:
            if isinstance(tile, dict) and tile.get("kind") in ("COOP", "PASTURE"):
                existing_structures += 1
                animal = tile.get("animal")
                if animal in ANIMAL_META:
                    existing_by_species[animal] += 1

    total_target = sum(herd_target.values())
    remaining_slots = max(0, total_target - existing_structures)
    if remaining_slots <= 0:
        return []

    empty: List[Tuple[int, int]] = []
    for y in range(board_size):
        for x in range(board_size):
            if _quadrant_of(x, y, board_size) in owned and tiles[y][x] is None:
                empty.append((x, y))

    def dist_to_shed(pos):
        return min(_dist(pos, s) for s in shed_tiles) if shed_tiles else 999

    empty.sort(key=lambda p: (dist_to_shed(p), p[1], p[0]))

    remaining_by_species = {
        s: max(0, herd_target.get(s, 0) - existing_by_species.get(s, 0)) for s in ANIMAL_META
    }
    order: List[str] = []
    while sum(remaining_by_species.values()) > 0 and len(order) < remaining_slots:
        for species in ANIMAL_META:
            if remaining_by_species.get(species, 0) > 0:
                order.append(species)
                remaining_by_species[species] -= 1

    return [(x, y, species) for (x, y), species in zip(empty, order)]


# ---------------------------------------------------------------------------
# 8. Task generation
# ---------------------------------------------------------------------------

Task = Dict[str, Any]


def _add(tasks: List[Task], priority: int, pos: Tuple[int, int], op: List[Any], requires: Optional[str] = None) -> None:
    tasks.append({"priority": priority, "pos": pos, "op": op, "requires": requires})


def _build_tasks(obs: Dict[str, Any], board_size: int, day: int) -> Tuple[List[Task], Dict[str, int]]:
    farm = obs["farms"][obs.get("player", 0)]
    tiles = farm["tiles"]
    owned = farm.get("unlocked_quadrants", ["NW"])
    private = obs.get("private", {})
    shed = private.get("shed", {})

    animal_slot_cap = _animal_slot_cap_for(owned)
    herd_target = _herd_target(obs, animal_slot_cap)
    slot_plan = _animal_slot_plan(obs, board_size, owned, herd_target)
    slot_by_pos = {(x, y): species for x, y, species in slot_plan}

    tasks: List[Task] = []
    seed_need: Dict[str, int] = {c: 0 for c in CROP_META}

    # Seed the self-crowding counter with crops we already have in the
    # ground so freshly-planned tiles are scored against our real exposure,
    # not just the tiles decided earlier in this same pass.
    own_committed: Dict[str, int] = {c: 0 for c in CROP_META}
    for row in tiles:
        for tile in row:
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                own_committed[tile["crop"]] = own_committed.get(tile["crop"], 0) + 1

    total_owned_tiles = 25 * len(owned)
    crop_cap = {
        crop: max(3, round(CROP_SHARE_CAP.get(crop, CROP_SHARE_CAP_DEFAULT) * total_owned_tiles))
        for crop in PLANTABLE_CROPS
    }

    for y in range(board_size):
        for x in range(board_size):
            quadrant = _quadrant_of(x, y, board_size)
            if quadrant not in owned:
                continue
            tile = tiles[y][x]
            pos = (x, y)

            if tile is None:
                species = slot_by_pos.get(pos)
                if species is not None:
                    _add(tasks, 8, pos, ["BUILD_" + STRUCTURE_OF_ANIMAL[species]])
                elif day <= BUY_STOP_DAY:
                    crop = _plan_crop_for_tile(x, y, quadrant, obs, day, own_committed, crop_cap)
                    if day + CROP_META[crop]["first_yield_day"] <= FINAL_DAY:
                        _add(tasks, 9, pos, ["PLANT", crop])
                        seed_need[crop] += 1
                        own_committed[crop] = own_committed.get(crop, 0) + 1
                continue

            if not isinstance(tile, dict):
                continue

            kind = tile.get("kind")

            if kind == "WEED":
                _add(tasks, 6, pos, ["DIG"])
                continue

            if kind == "PLANT":
                consecutive_unwatered = tile.get("consecutive_unwatered", 0)
                watered_today = tile.get("watered_today", False)
                if not watered_today:
                    priority = 0 if consecutive_unwatered >= 1 else 1
                    _add(tasks, priority, pos, ["WATER"])

                meta = CROP_META[tile["crop"]]
                age = day - tile.get("planted_day", day)
                yield_units = tile.get("yield_units", 0)
                if yield_units > 0:
                    if meta["ongoing"]:
                        _add(tasks, 2, pos, ["HARVEST"])
                    elif age >= meta["max_yield_day"]:
                        _add(tasks, 2, pos, ["HARVEST"])

                fert_until = tile.get("fertilized_until_day", -1)
                if fert_until < day and shed.get("FERTILIZER", 0) > 0 and BASE_PRICE[tile["crop"]] >= 60:
                    _add(tasks, 4, pos, ["FERTILIZE"], "FERTILIZER")
                continue

            if kind in ("COOP", "PASTURE"):
                animal = tile.get("animal")
                if animal is None:
                    species = slot_by_pos.get(pos)
                    if species is None:
                        compatible = [s for s, m in ANIMAL_META.items() if m["structure"] == kind]
                        if compatible:
                            species = max(compatible, key=lambda s: herd_target.get(s, 0))
                    if species is not None and shed.get(species, 0) > 0:
                        _add(tasks, 7, pos, ["PLACE", species], species)
                    continue

                consecutive_unfed = tile.get("consecutive_unfed", 0)
                if not tile.get("fed_today", False):
                    priority = 0 if consecutive_unfed >= 1 else 1
                    _add(tasks, priority, pos, ["FEED"], "WHEAT")

                if tile.get("yield_units", 0) > 0:
                    _add(tasks, 2, pos, ["HARVEST"])

                if tile.get("fertilizer_available", False):
                    _add(tasks, 5, pos, ["COLLECT_FERTILIZER"])

                if not tile.get("cared_today", False):
                    _add(tasks, 3, pos, ["CARE"])

    return tasks, seed_need


# ---------------------------------------------------------------------------
# 9. Per-turn unit dispatch
# ---------------------------------------------------------------------------

def _unit_positions(farm: Dict[str, Any]) -> List[Tuple[int, int]]:
    positions = [tuple(farm["farmer"])]
    positions.extend(tuple(p) for p in farm.get("hands", ()))
    return positions


def _unit_inventory(private: Dict[str, Any], idx: int) -> Dict[str, int]:
    invs = private.get("inventories", [])
    return invs[idx] if idx < len(invs) else {}


def _assignment_cost(tiles, board_size, pos, inv, owned, task: Task) -> Optional[int]:
    target = task["pos"]
    requires = task.get("requires")
    if requires and inv.get(requires, 0) <= 0:
        shed = _nearest_shed_tile(tiles, board_size, pos, owned)
        if shed is None:
            return None
        return _dist(pos, shed) + 1 + _dist(shed, target)
    return _dist(pos, target)


def _dispatch(obs: Dict[str, Any], tasks: List[Task], seed_need: Dict[str, int], board_size: int) -> Tuple[List[Any], List[List[Any]]]:
    farm = obs["farms"][obs.get("player", 0)]
    private = obs.get("private", {})
    tiles = farm["tiles"]
    owned = farm.get("unlocked_quadrants", ["NW"])
    seeds = private.get("seeds", {})

    positions = _unit_positions(farm)
    n_units = len(positions)
    actions: List[List[Any]] = [["PASS"] for _ in range(n_units)]
    used_units = set()

    seed_budget = {c: seeds.get(c, 0) for c in CROP_META}

    remaining = list(enumerate(tasks))
    while remaining:
        best_key = None
        best = None
        for t_idx, task in remaining:
            if task["op"][0] == "PLANT" and seed_budget.get(task["op"][1], 0) <= 0:
                continue
            for u_idx in range(n_units):
                if u_idx in used_units:
                    continue
                inv = _unit_inventory(private, u_idx)
                cost = _assignment_cost(tiles, board_size, positions[u_idx], inv, owned, task)
                if cost is None:
                    continue
                key = (task["priority"], cost, task["pos"][1], task["pos"][0], u_idx, t_idx)
                if best_key is None or key < best_key:
                    best_key = key
                    best = (u_idx, t_idx, task)
        if best is None:
            break

        u_idx, t_idx, task = best
        pos = positions[u_idx]
        inv = _unit_inventory(private, u_idx)
        requires = task.get("requires")

        if requires and inv.get(requires, 0) <= 0:
            shed = _nearest_shed_tile(tiles, board_size, pos, owned)
            if pos == shed:
                n = 5 if requires in ("WHEAT", "FERTILIZER") else 1
                actions[u_idx] = ["PICKUP", requires, n]
            else:
                step = _bfs_first_step(tiles, board_size, pos, shed)
                actions[u_idx] = [step] if step else ["PASS"]
        elif pos == task["pos"]:
            actions[u_idx] = list(task["op"])
            if task["op"][0] == "PLANT":
                seed_budget[task["op"][1]] = seed_budget.get(task["op"][1], 0) - 1
        else:
            step = _bfs_first_step(tiles, board_size, pos, task["pos"])
            actions[u_idx] = [step] if step else ["PASS"]

        used_units.add(u_idx)
        remaining = [(i, t) for i, t in remaining if i != t_idx]

    # Idle units carrying pure-sell produce with nothing else to do: head to
    # the shed and drop, so it becomes sellable.
    for u_idx in range(n_units):
        if u_idx in used_units:
            continue
        inv = _unit_inventory(private, u_idx)
        carrying_sellable = any(inv.get(item, 0) > 0 for item in SELLABLE_CROPS[1:] + ANIMAL_PRODUCTS)  # skip WHEAT (feed reserve)
        if not carrying_sellable:
            continue
        pos = positions[u_idx]
        shed = _nearest_shed_tile(tiles, board_size, pos, owned)
        if shed is None:
            continue
        if pos == shed:
            actions[u_idx] = ["DROP"]
        else:
            step = _bfs_first_step(tiles, board_size, pos, shed)
            actions[u_idx] = [step] if step else ["PASS"]

    farmer_action = actions[0]
    hand_actions = actions[1:]
    return farmer_action, hand_actions


# ---------------------------------------------------------------------------
# 10. Market orders
# ---------------------------------------------------------------------------

def _fib(n: int) -> int:
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _sell_orders(obs: Dict[str, Any], animal_count: int) -> List[List[Any]]:
    shed = obs.get("private", {}).get("shed", {})
    orders: List[List[Any]] = []
    wheat_reserve = WHEAT_FEED_RESERVE_DAYS * max(1, animal_count)
    for item in PRODUCTS:
        have = shed.get(item, 0)
        if have <= 0:
            continue
        if item == "WHEAT":
            sellable = max(0, have - wheat_reserve)
        elif item == "FERTILIZER":
            sellable = max(0, have - FERTILIZER_BUY_BATCH)
        else:
            sellable = have
        if sellable > 0:
            orders.append(["SELL", item, sellable])
    return orders


def _land_order(obs: Dict[str, Any], day: int, money: float) -> Tuple[List[List[Any]], float]:
    farm = obs["farms"][obs.get("player", 0)]
    owned = farm.get("unlocked_quadrants", ["NW"])
    n_extra = len(owned) - 1
    # Capped at MAX_LAND_PURCHASES (2): the third quadrant ($4000, SE) is
    # deliberately never bought -- see MAX_LAND_PURCHASES/LAND_FIRST_DAY
    # comment above.
    if n_extra >= MAX_LAND_PURCHASES or day > LAND_HARD_DEADLINE:
        return [], money
    trigger_day = (LAND_FIRST_DAY, LAND_SECOND_DAY)[n_extra]
    if day < trigger_day:
        return [], money
    cost = LAND_PRICES[n_extra]
    buffer = LAND_BUFFER[n_extra]
    if money - cost < buffer:
        return [], money
    return [["BUY_LAND"]], money - cost


def _animal_orders(obs: Dict[str, Any], day: int, herd_target: Dict[str, int], money: float) -> Tuple[List[List[Any]], float]:
    if day >= BUY_STOP_DAY:
        return [], money
    farm = obs["farms"][obs.get("player", 0)]
    shed = obs.get("private", {}).get("shed", {})
    orders: List[List[Any]] = []

    current_counts: Dict[str, int] = {s: 0 for s in ANIMAL_META}
    for row in farm["tiles"]:
        for tile in row:
            if isinstance(tile, dict) and tile.get("animal") in ANIMAL_META:
                current_counts[tile["animal"]] += 1
    for species in ANIMAL_META:
        current_counts[species] += shed.get(species, 0)

    for species, meta in ANIMAL_META.items():
        if day > ANIMAL_LAST_BUY_DAY[species]:
            continue
        missing = max(0, herd_target.get(species, 0) - current_counts[species])
        if missing <= 0:
            continue
        affordable = max(0, int((money - ANIMAL_BUY_BUFFER) // meta["cost"]))
        qty = min(missing, affordable, 2)
        if qty > 0:
            orders.append(["BUY_ANIMAL", species, qty])
            money -= qty * meta["cost"]
    return orders, money


def _seed_orders(obs: Dict[str, Any], day: int, seed_need: Dict[str, int], money: float) -> Tuple[List[List[Any]], float]:
    if day >= BUY_STOP_DAY:
        return [], money
    private = obs.get("private", {})
    seeds = private.get("seeds", {})
    orders: List[List[Any]] = []
    for crop, need in seed_need.items():
        have = seeds.get(crop, 0)
        want = max(0, need - have)
        if want <= 0:
            continue
        cost = CROP_META[crop]["seed"]
        affordable = int(money // cost) if cost else want
        qty = min(want, affordable)
        if qty > 0:
            orders.append(["BUY_SEED", crop, qty])
            money -= qty * cost
    return orders, money


def _product_orders(obs: Dict[str, Any], day: int, animal_count: int, money: float) -> Tuple[List[List[Any]], float]:
    if day >= BUY_STOP_DAY:
        return [], money
    shed = obs.get("private", {}).get("shed", {})
    orders: List[List[Any]] = []

    wheat_reserve = WHEAT_FEED_RESERVE_DAYS * max(1, animal_count)
    wheat_have = shed.get("WHEAT", 0)
    if wheat_have < wheat_reserve and money > 300:
        qty = min(wheat_reserve - wheat_have, 10)
        cost = qty * _price(obs, "WHEAT")
        if money - cost >= 0:
            orders.append(["BUY_PRODUCT", "WHEAT", qty])
            money -= cost

    fert_have = shed.get("FERTILIZER", 0)
    if fert_have < FERTILIZER_BUY_BATCH and money > FERTILIZER_MONEY_FLOOR:
        qty = FERTILIZER_BUY_BATCH - fert_have
        cost = qty * _price(obs, "FERTILIZER")
        if money - cost >= FERTILIZER_MONEY_FLOOR - FERTILIZER_BUY_BATCH * _price(obs, "FERTILIZER"):
            orders.append(["BUY_PRODUCT", "FERTILIZER", qty])
            money -= cost
    return orders, money


def _hire_orders(obs: Dict[str, Any], day: int, hour: int, money: float) -> Tuple[List[List[Any]], float]:
    if not (HIRE_HOUR_WINDOW[0] <= hour <= HIRE_HOUR_WINDOW[1]):
        return [], money
    farm = obs["farms"][obs.get("player", 0)]
    hires_today = farm.get("hires_today", 0)
    current_hands = len(farm.get("hands", []))

    schedule_target = HIRE_TARGET_SCHEDULE[min(day, len(HIRE_TARGET_SCHEDULE) - 1)]
    target_hands = max(0, schedule_target - current_hands)
    orders: List[List[Any]] = []
    n = hires_today
    for _ in range(target_hands):
        cost = _fib(n)
        if money - cost < HIRE_MONEY_FLOOR:
            break
        orders.append(["HIRE"])
        money -= cost
        n += 1
    return orders, money


def _market_orders(obs: Dict[str, Any], day: int, hour: int, seed_need: Dict[str, int]) -> List[List[Any]]:
    farm = obs["farms"][obs.get("player", 0)]
    animal_count = sum(
        1 for row in farm["tiles"] for tile in row
        if isinstance(tile, dict) and tile.get("animal") in ANIMAL_META
    )
    animal_slot_cap = _animal_slot_cap_for(farm.get("unlocked_quadrants", ["NW"]))
    herd_target = _herd_target(obs, animal_slot_cap)

    # Every buy category below draws from the same running bank balance --
    # each function only sees what previous categories left. SELL doesn't
    # cost anything so it goes first without needing to thread money (the
    # engine truncates any single order safely if money runs out mid-order,
    # but without a shared budget here, every category would independently
    # plan against the *full* balance and we'd try to spend it several times
    # over in one turn).
    #
    # On top of that, only expose a *fraction* of the bank as spendable
    # early on, ramping to the full balance by day ~21. Day 7-10 is exactly
    # when the leaderboard-derived land-purchase and hire-ramp schedule
    # peaks (2nd BUY_LAND + jump to 12 hires/day + restocking seeds for a
    # freshly-unlocked quadrant, all landing in the same few days) -- a fast
    # ramp back to 100% spending power right there recreates the same
    # cash-crunch death spiral the pacing exists to prevent, just shifted a
    # week later instead of removed. Keeping a real cushion through that
    # whole window, not just day 0, is what actually avoids it.
    spend_fraction = min(1.0, 0.35 + 0.03 * day)
    money = float(farm.get("money", 0)) * spend_fraction
    ordered: List[List[Any]] = list(_sell_orders(obs, animal_count))

    hire, money = _hire_orders(obs, day, hour, money)
    ordered += hire
    land, money = _land_order(obs, day, money)
    ordered += land
    animal, money = _animal_orders(obs, day, herd_target, money)
    ordered += animal
    seed, money = _seed_orders(obs, day, seed_need, money)
    ordered += seed
    product, money = _product_orders(obs, day, animal_count, money)
    ordered += product
    return ordered[:MAX_MARKET_ORDERS]


# ---------------------------------------------------------------------------
# 11. Top-level agent
# ---------------------------------------------------------------------------

def _agent_impl(obs: Dict[str, Any]) -> Dict[str, Any]:
    day = int(obs.get("day", 0))
    hour = int(obs.get("hour", 0))
    _maybe_reset_episode_state(day, hour)

    farm = obs["farms"][obs.get("player", 0)]
    tiles = farm["tiles"]
    board_size = len(tiles)

    tasks, seed_need = _build_tasks(obs, board_size, day)
    farmer_action, hand_actions = _dispatch(obs, tasks, seed_need, board_size)
    market = _market_orders(obs, day, hour, seed_need)

    return {"farmer": farmer_action, "hands": hand_actions, "market": market}


def agent(obs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return _agent_impl(obs)
    except Exception:
        try:
            n_hands = len(obs["farms"][obs.get("player", 0)].get("hands", []))
        except Exception:
            n_hands = 0
        return {"farmer": ["PASS"], "hands": [["PASS"] for _ in range(n_hands)], "market": []}
