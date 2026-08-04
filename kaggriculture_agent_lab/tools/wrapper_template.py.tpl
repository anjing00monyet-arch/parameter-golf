
PRODUCTS = (
    "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
    "EGG", "MILK", "WOOL", "FERTILIZER",
)
BASE_PRICE = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60,
    "STRAWBERRY": 120, "MELON": 250, "EGG": 50,
    "MILK": 160, "WOOL": 200, "FERTILIZER": 100,
}
GLUT_WEIGHT = {
    "WHEAT": 0.2, "CARROT": 0.7, "TOMATO": 0.8,
    "STRAWBERRY": 2.0, "MELON": 3.5, "EGG": 0.3,
    "MILK": 2.0, "WOOL": 3.2, "FERTILIZER": 0.6,
}
CORE_ACTIONS = __CORE_ACTIONS__
ADAPTIVE_TRIAD = __ADAPTIVE_TRIAD__
TREASURY_START = __TREASURY_START__
TREASURY_FLUSH = __TREASURY_FLUSH__
TERMINAL_WORK_START = __TERMINAL_WORK_START__
CLONE_FRONT_RUN = __CLONE_FRONT_RUN__
FRONT_RUN_HORIZON = __FRONT_RUN_HORIZON__
FRONT_RUN_ITEMS = __FRONT_RUN_ITEMS__

_LAST_STEP = -1
_CLONE_CONFIDENCE = 0


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _player(obs):
    return int(_get(obs, "player", 0) or 0)


def _farms(obs):
    return _get(obs, "farms", []) or []


def _farm(obs):
    farms = _farms(obs)
    player = _player(obs)
    return farms[player] if player < len(farms) else {}


def _private(obs):
    return _get(obs, "private", {}) or {}


def _shed(obs):
    return _get(_private(obs), "shed", {}) or {}


def _seeds(obs):
    return _get(_private(obs), "seeds", {}) or {}


def _inventories(obs):
    return _get(_private(obs), "inventories", []) or []


def _prices(obs):
    market = _get(obs, "market", {}) or {}
    return _get(market, "prices", {}) or {}


def _positions(farm):
    result = [list(_get(farm, "farmer", [0, 0]) or [0, 0])]
    result.extend(
        list(position)
        for position in (_get(farm, "hands", []) or [])
    )
    return result


def _iter_tiles(farm):
    for row in (_get(farm, "tiles", []) or []):
        for tile in (row or []):
            if isinstance(tile, dict) or hasattr(tile, "kind"):
                yield tile


def _public_signature(farm):
    counts = {
        "COW": 0, "SHEEP": 0, "GOOSE": 0,
        "WHEAT": 0, "CARROT": 0, "TOMATO": 0,
        "STRAWBERRY": 0, "MELON": 0,
        "PASTURE": 0, "COOP": 0, "WEED": 0,
    }
    for tile in _iter_tiles(farm):
        animal = _get(tile, "animal", None)
        crop = _get(tile, "crop", None)
        kind = _get(tile, "kind", None)
        if animal in counts:
            counts[animal] += 1
        elif crop in counts:
            counts[crop] += 1
        elif kind in counts:
            counts[kind] += 1

    positions = tuple(
        sorted(tuple(position) for position in _positions(farm))
    )
    quadrants = tuple(
        sorted(_get(farm, "unlocked_quadrants", []) or [])
    )
    return (
        len(_get(farm, "hands", []) or []),
        quadrants,
        positions,
        tuple(counts[item] for item in sorted(counts)),
    )


def _signature_distance(left, right):
    left_hands, left_quads, left_positions, left_counts = left
    right_hands, right_quads, right_positions, right_counts = right

    distance = abs(left_hands - right_hands)
    distance += 3 * abs(len(left_quads) - len(right_quads))
    distance += sum(
        abs(a - b)
        for a, b in zip(left_counts, right_counts)
    )

    if left_positions != right_positions:
        distance += 2

    return distance


def _update_clone_profile(obs, step):
    global _CLONE_CONFIDENCE

    if not CLONE_FRONT_RUN:
        return

    farms = _farms(obs)
    if len(farms) < 2:
        return

    player = _player(obs)
    opponent = 1 - player

    if step in (4, 24) or (step >= 48 and step % 24 == 0):
        own_signature = _public_signature(farms[player])
        opponent_signature = _public_signature(farms[opponent])
        distance = _signature_distance(
            own_signature,
            opponent_signature,
        )
        if distance <= 1:
            _CLONE_CONFIDENCE = min(8, _CLONE_CONFIDENCE + 1)
        elif distance <= 4:
            _CLONE_CONFIDENCE = max(0, _CLONE_CONFIDENCE - 1)
        else:
            _CLONE_CONFIDENCE = max(0, _CLONE_CONFIDENCE - 3)


def _clone_active():
    return CLONE_FRONT_RUN and _CLONE_CONFIDENCE >= 2


def _actor_tile(obs, actor):
    farm = _farm(obs)
    positions = _positions(farm)
    tiles = _get(farm, "tiles", []) or []

    if actor >= len(positions):
        return None

    x, y = positions[actor]
    if y < 0 or y >= len(tiles):
        return None
    if x < 0 or x >= len(tiles[y]):
        return None
    return tiles[y][x]


def _actor_inventory(obs, actor):
    inventories = _inventories(obs)
    if actor < len(inventories):
        return inventories[actor] or {}
    return {}


def _is_shed_adjacent(obs, actor):
    farm = _farm(obs)
    tiles = _get(farm, "tiles", []) or []
    positions = _positions(farm)

    if actor >= len(positions):
        return False

    size = len(tiles) or 10
    half = size // 2
    access = {
        (half - 1, half - 1),
        (half, half - 1),
        (half - 1, half),
        (half, half),
    }
    return tuple(positions[actor]) in access


def _adaptive_triad(action, obs, step):
    if not ADAPTIVE_TRIAD or step not in (333, 334, 335):
        return

    hands = list(action.get("hands", []) or [])
    hand_index = 2
    actor = hand_index + 1

    if hand_index >= len(hands):
        return

    tile = _actor_tile(obs, actor)
    seeds = _seeds(obs)
    kind = _get(tile, "kind", None)
    animal = _get(tile, "animal", None)
    watered = bool(_get(tile, "watered_today", False))

    if step == 333:
        if tile is None and int(seeds.get("MELON", 0) or 0) > 0:
            hands[hand_index] = ["PLANT", "MELON"]
        elif tile is not None and animal is None:
            hands[hand_index] = ["DIG"]

    elif step == 334:
        if tile is None and int(seeds.get("MELON", 0) or 0) > 0:
            hands[hand_index] = ["PLANT", "MELON"]
        elif kind == "PLANT" and not watered:
            hands[hand_index] = ["WATER"]

    elif step == 335:
        if kind == "PLANT" and not watered:
            hands[hand_index] = ["WATER"]
        else:
            hands[hand_index] = copy.deepcopy(
                CORE_ACTIONS[335]["hands"][hand_index]
            )

    action["hands"] = hands


def _existing_sells(orders):
    result = {}
    for order in orders:
        if (
            isinstance(order, list)
            and len(order) >= 3
            and order[0] == "SELL"
        ):
            result[order[1]] = (
                result.get(order[1], 0)
                + max(0, int(order[2] or 0))
            )
    return result


def _future_sales(step):
    result = {item: 0 for item in PRODUCTS}
    for future_step in range(step, len(TRACE_ACTIONS)):
        for order in TRACE_ACTIONS[future_step].get("market", []) or []:
            if (
                isinstance(order, list)
                and len(order) >= 3
                and order[0] == "SELL"
                and order[1] in result
            ):
                result[order[1]] += max(0, int(order[2] or 0))
    return result


def _front_run(action, obs, step):
    if not _clone_active() or FRONT_RUN_HORIZON <= 0:
        return

    orders = list(action.get("market", []) or [])
    if len(orders) >= 10:
        return

    shed = _shed(obs)
    current = _existing_sells(orders)
    prices = _prices(obs)
    planned = {}

    end = min(
        len(TRACE_ACTIONS),
        step + FRONT_RUN_HORIZON + 1,
    )
    for future_step in range(step + 1, end):
        distance = future_step - step
        for order in TRACE_ACTIONS[future_step].get("market", []) or []:
            if not (
                isinstance(order, list)
                and len(order) >= 3
                and order[0] == "SELL"
                and order[1] in FRONT_RUN_ITEMS
            ):
                continue
            item = order[1]
            quantity = max(0, int(order[2] or 0))
            if item not in planned:
                planned[item] = [distance, quantity]
            else:
                planned[item][1] += quantity

    choices = []
    for item, (distance, quantity) in planned.items():
        available = max(
            0,
            int(shed.get(item, 0) or 0)
            - current.get(item, 0),
        )
        quantity = min(available, quantity)
        if quantity <= 0:
            continue

        price = float(prices.get(item, BASE_PRICE[item]) or 0)
        priority = (
            price
            * quantity
            * GLUT_WEIGHT.get(item, 1.0)
            + (FRONT_RUN_HORIZON + 1 - distance)
            * BASE_PRICE[item]
        )
        choices.append((priority, item, quantity))

    if choices:
        choices.sort(reverse=True)
        _, item, quantity = choices[0]
        orders.append(["SELL", item, quantity])
        action["market"] = orders[:10]


def _treasury(action, obs, step):
    if TREASURY_START < 0 or step < TREASURY_START:
        return

    original = list(action.get("market", []) or [])
    shed = _shed(obs)
    prices = _prices(obs)

    remaining = {
        item: max(0, int(shed.get(item, 0) or 0))
        for item in PRODUCTS
    }
    rebuilt = []
    current_sells = {}

    for order in original:
        if not (
            isinstance(order, list)
            and len(order) >= 3
            and order[0] == "SELL"
            and order[1] in remaining
        ):
            rebuilt.append(order)
            continue

        item = order[1]
        quantity = min(
            remaining[item],
            max(0, int(order[2] or 0)),
        )
        if quantity <= 0:
            continue

        rebuilt.append(["SELL", item, quantity])
        remaining[item] -= quantity
        current_sells[item] = (
            current_sells.get(item, 0) + quantity
        )

    has_sell_slot = bool(current_sells)
    future = _future_sales(step + 1)
    additions = []

    for item in PRODUCTS:
        available_after_current = remaining[item]
        if available_after_current <= 0:
            continue

        if step >= TREASURY_FLUSH:
            quantity = available_after_current
        elif has_sell_slot:
            quantity = max(
                0,
                available_after_current - future.get(item, 0),
            )
        else:
            quantity = 0

        if quantity <= 0:
            continue

        price = float(prices.get(item, BASE_PRICE[item]) or 0)
        priority = (
            price
            * quantity
            * GLUT_WEIGHT.get(item, 1.0)
        )
        additions.append((priority, item, quantity))

    additions.sort(reverse=True)

    for _, item, quantity in additions:
        if len(rebuilt) >= 10:
            break
        rebuilt.append(["SELL", item, quantity])

    action["market"] = rebuilt[:10]


def _terminal_local_action(obs, actor):
    inventory = _actor_inventory(obs, actor)
    tile = _actor_tile(obs, actor)

    if _is_shed_adjacent(obs, actor) and any(
        int(value or 0) > 0
        for value in inventory.values()
    ):
        return ["DROP"]

    if int(_get(tile, "yield_units", 0) or 0) > 0:
        return ["HARVEST"]

    if (
        _get(tile, "animal", None) is not None
        and bool(_get(tile, "fertilizer_available", False))
    ):
        return ["COLLECT_FERTILIZER"]

    return ["PASS"]


def _terminal_work(action, obs, step):
    if (
        TERMINAL_WORK_START < 0
        or step < TERMINAL_WORK_START
        or step >= 719
    ):
        return

    farmer = action.get("farmer", ["PASS"])
    if farmer and farmer[0] == "PASS":
        action["farmer"] = _terminal_local_action(obs, 0)

    hands = list(action.get("hands", []) or [])
    for index, hand_action in enumerate(hands):
        if hand_action and hand_action[0] == "PASS":
            hands[index] = _terminal_local_action(obs, index + 1)
    action["hands"] = hands


def agent(obs, config=None):
    global _LAST_STEP, _CLONE_CONFIDENCE

    step = min(
        max(0, int(_get(obs, "step", 0) or 0)),
        len(TRACE_ACTIONS) - 1,
    )

    if step == 0 or step <= _LAST_STEP:
        _CLONE_CONFIDENCE = 0
    _LAST_STEP = step

    _update_clone_profile(obs, step)

    action = copy.deepcopy(TRACE_ACTIONS[step])
    _adaptive_triad(action, obs, step)
    _front_run(action, obs, step)
    _treasury(action, obs, step)
    _terminal_work(action, obs, step)

    return action
