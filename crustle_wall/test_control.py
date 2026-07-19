"""Tests for crustle_wall_control, built around the two real loss patterns
found in replay batch replays_15:

  1. double Mega Lucario ex false-safe (episode-86502143 vs Team Pierogachu):
     serial 76 uses the big attack (983) and would be read as "on cooldown /
     safe", but a *second* Lucario (serial 77) with energy is on the bench and
     can OHKO next turn. The old attackId-keyed cooldown missed it.

  2. self-deck-out race (episode-86516269 vs Naoki Susami, episode-86495589 vs
     Kevin Ramirez): we milled ourselves out first by a 1-4 card margin. The
     mill controller must refuse a non-essential optional draw in the race
     phase when the margin is thin.
"""

from crustle_wall import control as m


def _mon(serial, card_id, hp, maxhp, energies):
    return {"serial": serial, "id": card_id, "hp": hp, "maxHp": maxhp,
            "energies": list(energies), "energyCards": []}


# --- B: double-Lucario false-safe ------------------------------------------

def test_double_lucario_not_safe_after_cooldown():
    LUC = 678
    # opp active = Lucario s76 (just used Mega Brave, now on cooldown),
    # bench = fresh Lucario s77 with 3 energy ready to swing.
    state = {"players": [
        {"deckCount": 10, "active": [], "bench": [], "prize": [None] * 6},   # us (idx0)
        {"deckCount": 10,
         "active": [_mon(76, LUC, 250, 250, [6, 6, 6])],
         "bench": [_mon(77, LUC, 250, 250, [6, 6, 6])],
         "prize": [None] * 4},
    ]}
    tracker = m.ThreatTracker(opp_player_index=1)
    # s76 used Mega Brave (983) this turn.
    tracker.observe_attack(76, 983)
    tracker.on_opponent_turn_end()

    # s76 is on cooldown -> can only do 190. BUT s77 is fresh -> 270.
    dmg76 = tracker._mon_damage(state["players"][1]["active"][0])
    assert dmg76 == 190, dmg76
    incoming = tracker.max_incoming(state)
    assert incoming == 270, f"expected 270 from fresh benched Lucario, got {incoming}"
    # Great Tusk (hp 140) is therefore NOT safe.
    assert incoming >= 140


def test_single_lucario_on_cooldown_is_safe_for_now():
    LUC = 678
    state = {"players": [
        {"deckCount": 10, "active": [], "bench": [], "prize": [None] * 6},
        {"deckCount": 10,
         "active": [_mon(76, LUC, 250, 250, [6, 6, 6])],
         "bench": [],  # no second threat
         "prize": [None] * 4},
    ]}
    tracker = m.ThreatTracker(opp_player_index=1)
    tracker.observe_attack(76, 983)
    tracker.on_opponent_turn_end()
    incoming = tracker.max_incoming(state)
    assert incoming == 190, incoming   # only the filler attack available


def test_benched_lucario_without_energy_is_not_counted():
    LUC = 678
    state = {"players": [
        {"deckCount": 10, "active": [], "bench": [], "prize": [None] * 6},
        {"deckCount": 10,
         "active": [_mon(76, LUC, 250, 250, [6, 6, 6])],
         "bench": [_mon(77, LUC, 250, 250, [])],  # no energy -> can't swing next turn
         "prize": [None] * 4},
    ]}
    tracker = m.ThreatTracker(opp_player_index=1)
    tracker.observe_attack(76, 983)
    tracker.on_opponent_turn_end()
    # active on cooldown (190), bench not ready -> max is 190, not 270.
    assert tracker.max_incoming(state) == 190


def test_unknown_ex_treated_as_ohko_threat():
    state = {"players": [
        {"deckCount": 10, "active": [], "bench": [], "prize": [None] * 6},
        {"deckCount": 10,
         "active": [_mon(50, 269, 250, 250, [4, 4, 4])],  # Iono's Bellibolt ex (no attack scouted)
         "bench": [], "prize": [None] * 4},
    ]}
    tracker = m.ThreatTracker(opp_player_index=1)
    assert tracker.max_incoming(state) == m.UNKNOWN_EX_DAMAGE >= 140


# --- A: mill race ----------------------------------------------------------

def test_race_phase_blocks_thin_margin_optional_draw():
    # thin race: we have 5 deck, opp 8; Tusk mills ~2/turn.
    state = {"players": [
        {"deckCount": 5, "active": [], "bench": [], "prize": [None] * 6},
        {"deckCount": 8, "active": [], "bench": [], "prize": [None] * 6},
    ]}
    ctrl = m.MillRaceController(safe_margin=3.0, setup_deck_floor=20)
    race = ctrl.evaluate(state, own_index=0, opp_index=1,
                         planned_optional_draw=2, tusk_mill_per_turn=2.0,
                         wall_established=True)
    assert race.phase == "race"
    # own_turns = 5/3 = 1.67, opp_turns = 8/3 = 2.67, margin ~1.0 < 3 -> block.
    assert race.margin < 3.0
    assert ctrl.allow_optional_draw(race, needed_to_keep_attacking=False) is False
    # but if that draw is what keeps Tusk swinging, allow it.
    assert ctrl.allow_optional_draw(race, needed_to_keep_attacking=True) is True


def test_setup_phase_always_allows_draw():
    state = {"players": [
        {"deckCount": 40, "active": [], "bench": [], "prize": [None] * 6},
        {"deckCount": 45, "active": [], "bench": [], "prize": [None] * 6},
    ]}
    ctrl = m.MillRaceController()
    race = ctrl.evaluate(state, 0, 1, planned_optional_draw=3,
                         tusk_mill_per_turn=0.0, wall_established=False)
    assert race.phase == "setup"
    assert ctrl.allow_optional_draw(race, needed_to_keep_attacking=False) is True


def test_comfortable_margin_allows_draw():
    state = {"players": [
        {"deckCount": 18, "active": [], "bench": [], "prize": [None] * 6},
        {"deckCount": 6, "active": [], "bench": [], "prize": [None] * 6},
    ]}
    ctrl = m.MillRaceController(safe_margin=3.0)
    race = ctrl.evaluate(state, 0, 1, planned_optional_draw=1,
                         tusk_mill_per_turn=2.0, wall_established=True)
    # own_turns = 18/2 = 9, opp_turns = 6/3 = 2 -> margin -7, we are LOSING race
    # so a non-essential draw should still be blocked.
    assert ctrl.allow_optional_draw(race, needed_to_keep_attacking=False) is False


# --- C: Tusk exposure decision ---------------------------------------------

def _race(margin=5.0, phase="race"):
    return m.MillRaceState(own_deck=10, opp_deck=10, own_turns_left=5,
                           opp_turns_left=5 + margin, margin=margin, phase=phase)


def test_tusk_retreats_when_threatened_and_can_retreat():
    LUC = 678
    state = {"players": [
        {"deckCount": 10, "active": [_mon(11, m.GREAT_TUSK_ID, 140, 140, [20, 20, 20])],
         "bench": [_mon(19, m.CRUSTLE_ID, 150, 150, [20])], "prize": [None] * 6},
        {"deckCount": 10, "active": [_mon(76, LUC, 250, 250, [6, 6, 6])],
         "bench": [], "prize": [None] * 4},
    ]}
    tracker = m.ThreatTracker(1)
    d = m.decide_tusk_action(state, 0, 1, tracker, _race(), tusk_hp=140,
                             can_retreat_to_crustle=True, skipping_forfeits_race=False)
    assert d.action == "attack_then_retreat", d


def test_tusk_walls_when_threatened_and_cannot_retreat():
    LUC = 678
    state = {"players": [
        {"deckCount": 10, "active": [_mon(11, m.GREAT_TUSK_ID, 140, 140, [20, 20, 20])],
         "bench": [_mon(19, m.CRUSTLE_ID, 150, 150, [20])], "prize": [None] * 6},
        {"deckCount": 10, "active": [_mon(76, LUC, 250, 250, [6, 6, 6])],
         "bench": [], "prize": [None] * 4},
    ]}
    tracker = m.ThreatTracker(1)
    d = m.decide_tusk_action(state, 0, 1, tracker, _race(), tusk_hp=140,
                             can_retreat_to_crustle=False, skipping_forfeits_race=False)
    assert d.action == "wall_with_crustle", d


def test_tusk_swings_when_skipping_loses_race():
    LUC = 678
    state = {"players": [
        {"deckCount": 3, "active": [_mon(11, m.GREAT_TUSK_ID, 140, 140, [20, 20, 20])],
         "bench": [], "prize": [None] * 6},
        {"deckCount": 4, "active": [_mon(76, LUC, 250, 250, [6, 6, 6])],
         "bench": [], "prize": [None] * 4},
    ]}
    tracker = m.ThreatTracker(1)
    d = m.decide_tusk_action(state, 0, 1, tracker, _race(margin=0.3), tusk_hp=140,
                             can_retreat_to_crustle=False, skipping_forfeits_race=True)
    assert d.action == "attack_and_stay", d


def test_tusk_stays_when_safe():
    state = {"players": [
        {"deckCount": 10, "active": [_mon(11, m.GREAT_TUSK_ID, 140, 140, [20, 20, 20])],
         "bench": [], "prize": [None] * 6},
        {"deckCount": 10, "active": [_mon(76, 676, 110, 110, [6])],  # Solrock, 70 dmg
         "bench": [], "prize": [None] * 4},
    ]}
    tracker = m.ThreatTracker(1)
    d = m.decide_tusk_action(state, 0, 1, tracker, _race(), tusk_hp=140,
                             can_retreat_to_crustle=True, skipping_forfeits_race=False)
    assert d.action == "attack_and_stay", d


if __name__ == "__main__":
    import sys, traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); passed += 1; print(f"PASS {name}")
            except Exception:
                failed += 1; print(f"FAIL {name}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
