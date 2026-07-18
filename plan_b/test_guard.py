"""Tests for plan_b.guard, anchored on replays_16 evidence:

  - episode-86603157 (mirror loss): Duraludon serial 15 sat active with 1 energy,
    evolution card not yet in hand, only another unevolved Duraludon (no energy)
    on the bench. No safe retreat existed -> the guard must not invent one.
  - A variant of the same state but with Cinderace already benched -> retreat
    should be recommended.
  - Mill archetype detection, anchored on the Vishesh Banna game where the
    opponent's revealed deck included Great Tusk and Xerosic's Machinations.
"""

import plan_b.guard as g
from crustle_wall.control import ThreatTracker


def _mon(serial, card_id, hp, maxhp, energies, appear_this_turn=False):
    return {"serial": serial, "id": card_id, "hp": hp, "maxHp": maxhp,
            "energies": list(energies), "energyCards": [], "appearThisTurn": appear_this_turn}


# --- 1. Pre-evolution exposure guard ---------------------------------------

def test_real_case_no_safe_retreat_stays():
    """episode-86603157: Duraludon(15) active w/ 1 energy, bench only has a
    second unevolved, energyless Duraludon(16). Opponent's own Archaludon ex
    (190) is online and can one-shot a 130hp Duraludon (max observed dmg 360).
    There is no retreat that actually helps, so the guard must say 'stay',
    not fabricate a retreat target."""
    duraludon = _mon(15, g.DURALUDON_ID, 130, 130, [8])
    state = {"players": [
        {"deckCount": 20, "active": [duraludon],
         "bench": [_mon(16, g.DURALUDON_ID, 130, 130, [])],
         "prize": [None] * 6},
        {"deckCount": 20, "active": [_mon(21, g.ARCHALUDON_ID, 250, 250, [8, 8, 8])],
         "bench": [], "prize": [None] * 5},
    ]}
    tracker = ThreatTracker(opp_player_index=1)
    retreat_target = g.find_retreat_target(state, own_index=0, retreat_energy_available=1)
    assert retreat_target is None, "both bench options are unevolved Duraludon, nothing safer to retreat to"

    decision = g.decide_pre_evolution_exposure(
        state, own_index=0, opp_index=1, tracker=tracker, active_mon=duraludon,
        evolution_card_in_hand=False, retreat_target_serial=retreat_target)
    assert decision.action == "stay", decision


def test_retreat_recommended_when_cinderace_benched():
    """Same threat, but Cinderace is sitting on the bench this time -> retreat."""
    duraludon = _mon(15, g.DURALUDON_ID, 130, 130, [8])
    state = {"players": [
        {"deckCount": 20, "active": [duraludon],
         "bench": [_mon(30, g.CINDERACE_ID, 130, 130, [8])],
         "prize": [None] * 6},
        {"deckCount": 20, "active": [_mon(21, g.ARCHALUDON_ID, 250, 250, [8, 8, 8])],
         "bench": [], "prize": [None] * 5},
    ]}
    tracker = ThreatTracker(opp_player_index=1)
    retreat_target = g.find_retreat_target(state, own_index=0, retreat_energy_available=1)
    assert retreat_target == 30

    decision = g.decide_pre_evolution_exposure(
        state, own_index=0, opp_index=1, tracker=tracker, active_mon=duraludon,
        evolution_card_in_hand=False, retreat_target_serial=retreat_target)
    assert decision.action == "retreat", decision


def test_evolves_when_card_in_hand_and_eligible():
    duraludon = _mon(15, g.DURALUDON_ID, 130, 130, [8], appear_this_turn=False)
    state = {"players": [
        {"deckCount": 20, "active": [duraludon], "bench": [], "prize": [None] * 6},
        {"deckCount": 20, "active": [_mon(21, g.ARCHALUDON_ID, 250, 250, [8, 8, 8])],
         "bench": [], "prize": [None] * 5},
    ]}
    tracker = ThreatTracker(opp_player_index=1)
    decision = g.decide_pre_evolution_exposure(
        state, own_index=0, opp_index=1, tracker=tracker, active_mon=duraludon,
        evolution_card_in_hand=True, retreat_target_serial=None)
    assert decision.action == "evolve", decision


def test_appear_this_turn_blocks_evolve_even_with_card_in_hand():
    duraludon = _mon(15, g.DURALUDON_ID, 130, 130, [], appear_this_turn=True)
    state = {"players": [
        {"deckCount": 20, "active": [duraludon],
         "bench": [_mon(30, g.CINDERACE_ID, 130, 130, [8])], "prize": [None] * 6},
        {"deckCount": 20, "active": [_mon(21, g.ARCHALUDON_ID, 250, 250, [8, 8, 8])],
         "bench": [], "prize": [None] * 5},
    ]}
    tracker = ThreatTracker(opp_player_index=1)
    decision = g.decide_pre_evolution_exposure(
        state, own_index=0, opp_index=1, tracker=tracker, active_mon=duraludon,
        evolution_card_in_hand=True, retreat_target_serial=30)
    assert decision.action == "retreat", decision  # can't evolve this turn, so fall through to threat check


def test_safe_when_opponent_cannot_ko():
    duraludon = _mon(15, g.DURALUDON_ID, 130, 130, [8])
    state = {"players": [
        {"deckCount": 20, "active": [duraludon], "bench": [], "prize": [None] * 6},
        {"deckCount": 20, "active": [_mon(40, g.DURALUDON_ID, 130, 130, [8])],  # opp also unevolved, weak
         "bench": [], "prize": [None] * 5},
    ]}
    tracker = ThreatTracker(opp_player_index=1)
    decision = g.decide_pre_evolution_exposure(
        state, own_index=0, opp_index=1, tracker=tracker, active_mon=duraludon,
        evolution_card_in_hand=False, retreat_target_serial=None)
    assert decision.action == "stay", decision
    assert "safe" in decision.reason


# --- 2. Mill archetype detection --------------------------------------------

def test_detects_mill_archetype_from_great_tusk():
    assert g.detect_mill_archetype([1121, 8, 58, 190]) is True


def test_detects_mill_archetype_from_xerosic():
    assert g.detect_mill_archetype([1121, 1197]) is True


def test_no_false_positive_on_normal_opponent():
    assert g.detect_mill_archetype([1121, 190, 666, 169, 8]) is False


def test_mill_settings_tighten_when_matchup_confirmed():
    normal = g.mill_race_settings(False)
    mill = g.mill_race_settings(True)
    assert mill["safe_margin"] > normal["safe_margin"]
    assert mill["setup_deck_floor"] > normal["setup_deck_floor"]


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
