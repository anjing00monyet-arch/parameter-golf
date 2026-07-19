"""Crustle Wall — threat tracking & mill-race control (designs A + B + C).

This module is the *decision core* of the Crustle Wall pilot. It is written as
pure functions over the replay observation schema (the ``current`` state dict
and the ``logs`` event stream), so it is portable regardless of the action
encoding layer that sits on top of it.

It replaces three pieces of the previous (lost) v2 pilot:

  A. MillRaceController   — gate optional draw so we don't self-deck-out.
  B. ThreatTracker        — per-*serial* (individual Pokémon) threat model that
                            fixes the "opponent swaps in a fresh Mega Lucario ex
                            and we wrongly think the big attack is on cooldown"
                            bug. Cooldown is keyed by serial, not attackId, and
                            benched candidates are included in max_incoming.
  C. decide_tusk_action   — combine B into the attack/Switch/skip choice for
                            Great Tusk so we stop feeding OHKO'd Tusks.

Empirical tables (CARD_ATTACKS / EX_CARD_IDS) are learned from the replay
batch; unknown attackers are treated conservatively (see UNKNOWN_EX_DAMAGE).

Observation schema (only the fields used here):

  state = {
    "players": [p0, p1],   # index by absolute playerIndex
  }
  p = {
    "deckCount": int,
    "active": [mon] | [],  # 0 or 1 entries
    "bench":  [mon, ...],
    "prize":  [None|card, ...],   # None == unclaimed
  }
  mon = {
    "serial": int,     # STABLE per-individual id (the key insight)
    "id":     int,     # card id (-> CARD_ATTACKS)
    "hp":     int,     # current remaining hp
    "maxHp":  int,
    "energies": [energyTypeId, ...],   # attached energy, one entry per energy
    "energyCards": [...],
  }

  log event: {"type": 15, "playerIndex", "serial", "attackId", "cardId"}  # attack
             {"type": 16, "playerIndex", "serial", "value"}               # damage (value<=0)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Iterable

# ---------------------------------------------------------------------------
# Learned tables (from replay batch replays_15).  damage is max observed.
# ---------------------------------------------------------------------------

# card_id -> list of (attackId, damage) sorted high->low
CARD_ATTACKS: Dict[int, List[tuple]] = {
    58: [(62, 10)],
    66: [(76, 90)],
    93: [(115, 200)],
    112: [(141, 120)],
    117: [(148, 140)],
    120: [(152, 40)],
    121: [(154, 200), (153, 70)],
    169: [(224, 80), (223, 30)],
    190: [(224, 360), (253, 220), (223, 30)],
    235: [(323, 20)],
    265: [(363, 280)],
    305: [(424, 20)],
    345: [(479, 120)],
    381: [(532, 290), (531, 130)],
    648: [(937, 180)],
    666: [(965, 100)],
    673: [(976, 10)],
    674: [(978, 210)],
    676: [(980, 70)],
    677: [(981, 60)],
    678: [(983, 270), (982, 190)],   # Mega Lucario ex: 983=Mega Brave, 982=filler
    721: [(1042, 80)],
    722: [(1044, 10)],
    741: [(1070, 10)],
    742: [(1071, 60)],
    743: [(1072, 380)],
    861: [(1240, 10)],
    1031: [(1487, 120)],
}

# Attacks that force the *attacker* to sit out the following turn (Mega Brave
# style). Keyed by attackId. After such an attack, that serial can only use its
# other (non-cooldown) attacks next turn.
COOLDOWN_ATTACK_IDS: Dict[int, int] = {
    983: 1,   # Mega Lucario ex "Mega Brave" — cannot attack again next turn
}

# ex Pokémon card ids (Crustle's ability makes it immune to their attacks; also
# used to flag "high threat, assume OHKO" for unknown ex attackers).
EX_CARD_IDS = {96, 117, 121, 140, 184, 190, 269, 381, 648, 678, 723, 861, 1031, 1071}

# Conservative damage assumed for an ex attacker we've never scouted but which
# has enough energy to attack. The meta is full of 200+ single-hit ex, so we
# assume it can OHKO a Great Tusk (140 hp).
UNKNOWN_EX_DAMAGE = 200
UNKNOWN_NONEX_DAMAGE = 60

# Great Tusk / Crustle card ids
GREAT_TUSK_ID = 58
CRUSTLE_ID = 345


# ---------------------------------------------------------------------------
# B. Per-serial threat tracker
# ---------------------------------------------------------------------------

@dataclass
class _MonThreat:
    serial: int
    card_id: int
    cooldown: int = 0   # opp-turns remaining until the big attack is usable


class ThreatTracker:
    """Tracks each opponent Pokémon *by serial* and answers max_incoming().

    The pilot must feed it the opponent's attack events (from ``logs``) via
    :meth:`observe_attack`, and call :meth:`on_opponent_turn_end` once per
    opponent turn so cooldowns tick down.
    """

    def __init__(self, opp_player_index: int):
        self.opp = opp_player_index
        self._state: Dict[int, _MonThreat] = {}

    # -- event ingestion ----------------------------------------------------
    def observe_logs(self, logs: Iterable[dict]) -> None:
        """Scan a log batch and record opponent attacks (type 15)."""
        for log in logs or []:
            if log.get("type") == 15 and log.get("playerIndex") == self.opp:
                self.observe_attack(log.get("serial"), log.get("attackId"))

    def observe_attack(self, serial: int, attack_id: int) -> None:
        card_id = self._state[serial].card_id if serial in self._state else None
        st = self._state.setdefault(serial, _MonThreat(serial, card_id))
        cd = COOLDOWN_ATTACK_IDS.get(attack_id, 0)
        if cd:
            # +1 because we immediately tick down at this same opp turn's end.
            st.cooldown = cd + 1

    def on_opponent_turn_end(self) -> None:
        for st in self._state.values():
            if st.cooldown > 0:
                st.cooldown -= 1

    # -- queries ------------------------------------------------------------
    def _mon_damage(self, mon: dict) -> int:
        """Max damage this specific mon can deal *next* opp turn, honoring its
        per-serial cooldown."""
        serial = mon.get("serial")
        card_id = mon.get("id")
        # keep card_id fresh (it may not have attacked yet)
        if serial in self._state and self._state[serial].card_id is None:
            self._state[serial].card_id = card_id
        cd = self._state[serial].cooldown if serial in self._state else 0

        attacks = CARD_ATTACKS.get(card_id)
        if attacks is None:
            # never scouted this card: assume worst plausible for its class.
            return UNKNOWN_EX_DAMAGE if card_id in EX_CARD_IDS else UNKNOWN_NONEX_DAMAGE

        best = 0
        for atk_id, dmg in attacks:
            if cd > 0 and COOLDOWN_ATTACK_IDS.get(atk_id, 0):
                continue   # this attack is locked out this turn for this serial
            best = max(best, dmg)
        return best

    def _can_attack_next_turn(self, mon: dict, is_active: bool) -> bool:
        """Active mon can always attack. A benched mon is a next-turn threat if
        it already has energy attached (it can be promoted with a free switch /
        Boss's Orders and swing)."""
        if is_active:
            return True
        return len(mon.get("energies") or []) > 0

    def max_incoming(self, state: dict) -> int:
        """Largest single-hit damage the opponent can land next turn against a
        promoted-active target of ours, considering *every* candidate serial
        (active + energized bench). This is what fixes the double-Lucario
        false-safe: a fresh benched Lucario is counted with its own cooldown
        state (0), so swapping does not read as safe."""
        opp = state["players"][self.opp]
        worst = 0
        for mon in opp.get("active") or []:
            if mon and self._can_attack_next_turn(mon, True):
                worst = max(worst, self._mon_damage(mon))
        for mon in opp.get("bench") or []:
            if mon and self._can_attack_next_turn(mon, False):
                worst = max(worst, self._mon_damage(mon))
        return worst


# ---------------------------------------------------------------------------
# A. Mill-race controller
# ---------------------------------------------------------------------------

@dataclass
class MillRaceState:
    own_deck: int
    opp_deck: int
    own_turns_left: float
    opp_turns_left: float
    margin: float           # opp_turns_left - own_turns_left  (>0 = we win race)
    phase: str              # "setup" | "race"


class MillRaceController:
    """Decide whether an *optional* draw/search is allowed, and expose the race
    margin so Tusk-exposure decisions can override when self-deck-out looms.

    ``tusk_mill_per_turn`` is the expected cards we mill off the opponent each
    turn while a Great Tusk is attacking (Great Tusk's attack mills the
    opponent's deck). If no Tusk can attack, pass 0.
    """

    def __init__(self, safe_margin: float = 3.0, setup_deck_floor: int = 20):
        self.safe_margin = safe_margin
        self.setup_deck_floor = setup_deck_floor

    def evaluate(self, state: dict, own_index: int, opp_index: int,
                 planned_optional_draw: int, tusk_mill_per_turn: float,
                 wall_established: bool) -> MillRaceState:
        own_deck = state["players"][own_index]["deckCount"]
        opp_deck = state["players"][opp_index]["deckCount"]

        # own consumption = 1 forced draw/turn + optional draw we intend to use
        own_burn = 1 + max(0, planned_optional_draw)
        opp_burn = 1 + max(0.0, tusk_mill_per_turn)

        own_turns = own_deck / own_burn if own_burn > 0 else float("inf")
        opp_turns = opp_deck / opp_burn if opp_burn > 0 else float("inf")
        margin = opp_turns - own_turns

        if not wall_established or own_deck > self.setup_deck_floor:
            phase = "setup"
        else:
            phase = "race"
        return MillRaceState(own_deck, opp_deck, own_turns, opp_turns, margin, phase)

    def allow_optional_draw(self, race: MillRaceState,
                            needed_to_keep_attacking: bool) -> bool:
        """In setup phase, always allow (we need board). In race phase, only
        allow if the margin is comfortable OR the draw is required to keep the
        Tusk mill engine running (which *feeds* opp_turns_left)."""
        if race.phase == "setup":
            return True
        if needed_to_keep_attacking:
            return True
        return race.margin >= self.safe_margin


# ---------------------------------------------------------------------------
# C. Great Tusk exposure decision (A + B combined)
# ---------------------------------------------------------------------------

@dataclass
class TuskDecision:
    action: str          # "attack_then_retreat" | "attack_and_stay" | "wall_with_crustle"
    reason: str


def decide_tusk_action(state: dict, own_index: int, opp_index: int,
                       tracker: ThreatTracker, race: MillRaceState,
                       tusk_hp: int, can_retreat_to_crustle: bool,
                       skipping_forfeits_race: bool) -> TuskDecision:
    """Decide what to do with an active Great Tusk this turn.

    Rule: if the opponent can OHKO the Tusk next turn (max_incoming >= tusk_hp)
    we must not leave it exposed — retreat to Crustle after attacking, or if we
    can't retreat, wall with Crustle instead of attacking (Tusk survival >
    one turn of mill). The single exception is when the mill race says skipping
    the attack loses us the game on deck-out; then we swing anyway."""
    incoming = tracker.max_incoming(state)
    safe = incoming < tusk_hp

    if safe:
        return TuskDecision("attack_and_stay",
                            f"safe: max_incoming={incoming} < tusk_hp={tusk_hp}")

    # Tusk would be OHKO'd if it stays active.
    if can_retreat_to_crustle:
        return TuskDecision("attack_then_retreat",
                            f"threatened (in={incoming}>=hp={tusk_hp}): mill then hide behind Crustle")

    # Can't retreat. Normally wall with Crustle, but the race can override.
    if skipping_forfeits_race:
        return TuskDecision("attack_and_stay",
                            f"threatened but must swing: skipping deck-outs us "
                            f"(margin={race.margin:.1f})")
    return TuskDecision("wall_with_crustle",
                        f"threatened (in={incoming}>=hp={tusk_hp}), no retreat: preserve Tusk, wall")


# ---------------------------------------------------------------------------
# Small helpers the pilot can reuse
# ---------------------------------------------------------------------------

def prizes_left(state: dict, index: int) -> int:
    return sum(1 for x in (state["players"][index].get("prize") or []) if x is None)


def find_active_card(state: dict, index: int, card_id: int) -> Optional[dict]:
    for mon in state["players"][index].get("active") or []:
        if mon.get("id") == card_id:
            return mon
    return None
