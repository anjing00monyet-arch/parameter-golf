"""Plan B (Archaludon ex + Cinderace, candB build) — exposure & mill-race guards.

Two independent guards, motivated by replays_16 (53 Plan B games, 30W/23L):

  1. Pre-evolution exposure guard. Archaludon-mirror losses (4/12, the worst and
     most frequent matchup) correlate with an unevolved Duraludon (130 hp) sitting
     active and getting KO'd before it becomes Archaludon ex. In the 8 mirror
     losses we lost that race 8 pre-evolution Duraludons vs the opponent's 3; in
     the 4 wins it was 3 vs 2 — the imbalance is real but not universal (5/8
     losses show a clear disadvantage, 3/8 don't), so this guard helps a subset,
     not all, of mirror losses. When a fresh Duraludon can't evolve yet (missing
     the evolution card in hand, independent of the appearThisTurn flag) and the
     opponent can KO it next turn, retreat to a less committed bench Pokemon if
     one is available — evolving is always preferred when it is legal and
     available, this guard only covers the turns where it isn't.

  2. Mill-race guard. 2 of 23 losses were self-deck-out with zero prizes lost to
     the opponent — including one where the opponent ran the Great Tusk mill
     archetype (our own Crustle Wall's mirror) and decked us in 89 steps. Plan B
     has no anti-mill tech and runs heavy deck-thinning (Ultra Ball / Pokégear
     3.0 / Poké Pad / Explorer's Guidance), so it is structurally exposed to
     being out-milled in a long game. This reuses crustle_wall.control's
     MillRaceController (it is deck-agnostic) and adds opponent-archetype
     detection so the pilot can tighten economy mode as soon as a mill matchup
     is recognized, rather than only reacting once the deck count is already low.

Both guards are pure functions over the same observation schema as
crustle_wall.control (see that module's docstring for the schema).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from crustle_wall.control import ThreatTracker, MillRaceController, MillRaceState  # noqa: F401

DURALUDON_ID = 169
ARCHALUDON_ID = 190
CINDERACE_ID = 666
RELICANTH_ID = 57

# Card ids that mark an opponent as running the mill archetype (our own
# Crustle Wall's mirror: Great Tusk mills the deck, Xerosic locks the hand).
MILL_ARCHETYPE_CARD_IDS = {58, 1197}  # Great Tusk, Xerosic's Machinations


# ---------------------------------------------------------------------------
# 1. Pre-evolution exposure guard
# ---------------------------------------------------------------------------

@dataclass
class ExposureDecision:
    action: str          # "evolve" | "retreat" | "stay"
    reason: str


def decide_pre_evolution_exposure(state: dict, own_index: int, opp_index: int,
                                  tracker: ThreatTracker, active_mon: dict,
                                  evolution_card_in_hand: bool,
                                  retreat_target_serial: Optional[int]) -> ExposureDecision:
    """Decide what to do with an active, not-yet-evolved Duraludon this turn.

    ``active_mon`` is the Duraludon's own state dict (from
    ``state["players"][own_index]["active"][0]``). ``evolution_card_in_hand``
    tells us whether Archaludon ex is already available to evolve into — Duraludon
    being eligible (not appearThisTurn) is necessary but not sufficient; you also
    need the higher-stage card drawn. ``retreat_target_serial`` is the serial of a
    bench Pokemon we could retreat to (None if no safe/affordable retreat exists,
    e.g. Cinderace or Relicanth already benched with the retreat cost payable).

    Evolving is always the right move when available — that removes the exposure
    outright (Archaludon ex has more hp) and this guard doesn't need to second-guess
    it. This only has to decide what to do in the turns where evolution isn't yet
    possible.
    """
    if evolution_card_in_hand and not active_mon.get("appearThisTurn", False):
        return ExposureDecision("evolve", "Archaludon ex in hand and Duraludon is evolution-eligible")

    tusk_hp = active_mon.get("hp", 130)
    incoming = tracker.max_incoming(state)
    if incoming < tusk_hp:
        return ExposureDecision("stay", f"safe: max_incoming={incoming} < hp={tusk_hp}")

    if retreat_target_serial is not None:
        return ExposureDecision("retreat",
                                f"threatened (in={incoming}>=hp={tusk_hp}) and can't evolve yet: "
                                f"retreat to serial={retreat_target_serial} rather than soak the KO")

    return ExposureDecision("stay",
                            f"threatened (in={incoming}>=hp={tusk_hp}), can't evolve, no retreat available: "
                            f"forced to leave it active")


def find_retreat_target(state: dict, own_index: int, retreat_energy_available: int) -> Optional[int]:
    """Pick a bench Pokemon to retreat to. Retreating only helps if the
    destination isn't itself an unevolved Duraludon — swapping one fragile,
    equally-KO'able Duraludon for another leaves us exactly as exposed, so
    that is not a valid target, not a fallback."""
    if retreat_energy_available <= 0:
        return None
    bench = state["players"][own_index].get("bench") or []
    candidates = [m for m in bench if m and m.get("id") != DURALUDON_ID]
    if not candidates:
        return None
    return candidates[0].get("serial")


# ---------------------------------------------------------------------------
# 2. Mill-race guard: opponent archetype detection
# ---------------------------------------------------------------------------

def detect_mill_archetype(opponent_known_card_ids) -> bool:
    """True if any card we've seen from the opponent (revealed hand, discard,
    board, prizes we've looked at, etc.) marks them as the mill archetype.
    Call this as soon as any opponent card becomes visible, and keep it sticky
    for the rest of the game (once confirmed, an opponent doesn't stop running
    their own deck)."""
    return any(cid in MILL_ARCHETYPE_CARD_IDS for cid in opponent_known_card_ids)


def mill_race_settings(is_mill_matchup: bool) -> dict:
    """Tighter MillRaceController parameters once a mill matchup is confirmed:
    react to a thinner deck earlier (higher safe_margin bar, higher setup_deck_floor
    so we leave "setup phase" and start gating optional draws sooner)."""
    if is_mill_matchup:
        return dict(safe_margin=5.0, setup_deck_floor=30)
    return dict(safe_margin=3.0, setup_deck_floor=20)
