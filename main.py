"""Archaludon ex + Cinderace — Rule-based agent (Public version)

Deck Concept:
  Cinderace's Explosiveness places it face-down as Active during setup.
  Turn 1 Turbo Flare ({C}=50) accelerates up to 3 Basic Energy from deck
  to benched Duraludon. Evolving into Archaludon ex triggers Assemble Alloy,
  attaching up to 2 Basic Metal Energy from discard to Metal Pokemon.
  Metal Defender ({M}{M}{M}=220) is the main attack; no Weakness next turn.
  Duraludon can attack directly with Raging Hammer ({M}{M}{C}=80 + 10 per
  damage counter) without evolving. Relicanth's Memory Dive also unlocks
  Raging Hammer on Archaludon ex after evolution. Hero's Cape gives +100 HP
  (HP400). Full Metal Lab reduces attack damage to Metal Pokemon by 30.

Pokemon:
  Duraludon (169)      - Basic Metal HP130. Hammer In {M}=30.
                         Raging Hammer {M}{M}{C}=80+10*damage_counters.
  Archaludon ex (190)  - Stage 1 from Duraludon, HP300. Assemble Alloy: on evolve
                         from hand, attach up to 2 Metal Energy from discard.
                         Metal Defender {M}{M}{M}=220, no Weakness next turn.
  Cinderace (666)      - Stage 2 HP160. Explosiveness: place face-down as Active
                         in setup from opening hand. Turbo Flare {C}=50, attach
                         up to 3 Basic Energy from deck to benched Pokemon.
  Relicanth (57)       - Basic HP100. Memory Dive: evolved Pokemon can use attacks
                         from previous Evolutions. Archaludon ex -> Raging Hammer.

Trainers:
  Poke Pad (1152), Ultra Ball (1121), Pokegear 3.0 (1122), Night Stretcher (1097),
  Jumbo Ice Cream (1147), Hero's Cape (1159), Boss's Orders (1182),
  Explorer's Guidance (1185), Lillie's Determination (1227), Full Metal Lab (1244) x4.

Energy: Basic Metal Energy (8) x11

Score system:
  Setup/play/evolve/attach: 1000~28000 (high = do first)
  Attack: damage value (always last — attacking ends the turn)
  Negative = skip if above minCount
"""

import os
import random
import sys

try:
    ROOT = __file__
except NameError:
    ROOT = None
CG_PATH = "/kaggle_simulations/agent"
for p in ([os.path.dirname(os.path.abspath(ROOT))] if ROOT else []) + [CG_PATH]:
    if p and p not in sys.path and os.path.isdir(p):
        sys.path.insert(0, p)

from cg.api import (
    AreaType,
    LogType,
    OptionType,
    SelectContext,
    all_card_data,
    to_observation_class,
)

try:
    from cg.api import all_attack
    ALL_ATTACKS = {a.attackId: a for a in all_attack()}
except Exception:
    ALL_ATTACKS = {}

# ── Card IDs ──

DURALUDON = 169
ARCHALUDON_EX = 190
CINDERACE = 666
RELICANTH = 57
CRUSTLE_LINE = {344, 345, 532}
STARMIE_LINE = {1030, 1031}
LUCARIO_LINE = {677, 678}
MIRROR_LINE = {169, 190}  # opp plays Duraludon/Archaludon ex → mirror match
HOP_LINE = {288, 289, 299, 304, 307, 308, 309, 310, 878, 879}
HOP_SNORLAX = 304

METAL_ENERGY = 8

# ── Score bands (MAIN context) ──────────────────────────────────────────
# Meaning: higher band always beats lower band regardless of card. Numeric
# values within a band still matter for ordering choices of the same type
# (e.g. which Pokemon to evolve first), but should never leak into another
# band's range. Kept headroom (2000) between bands for tie-break math
# (e.g. "+ mc * 2000") without spilling into the next band up.
SCORE_FORCED = 100000        # forced/mandatory actions (Explosiveness activate)
SCORE_BOSS_LETHAL = 20000    # Boss's Orders pull that ends the game this turn
SCORE_EVOLVE_ALLOY = 26000   # Assemble Alloy trigger (mc>=2): must happen before anything else
SCORE_SEARCH = 20000         # Ultra Ball / Full Metal Lab / core items
SCORE_PLAY_POKEMON = 18000   # Bench a Basic (Duraludon/Relicanth)
SCORE_EVOLVE_PLAIN = 16000   # Evolve without full Alloy value, still high prio
SCORE_RETREAT_READY = 13000  # Retreat into an attack-ready ex/Duraludon
SCORE_ATTACH_CORE = 12000    # Metal Energy onto a 0-1 energy attacker
SCORE_SUPPORTER = 5000       # Lillie/Explorer baseline
SCORE_SUPPORTER_PRIMARY = 16000  # Explorer as primary play (own band; do NOT
                                  # alias to SCORE_EVOLVE_PLAIN even though the
                                  # value matches today — they mean different
                                  # things and may need to diverge later)
SCORE_UTILITY = 1000         # generic fallback
SCORE_SKIP = -500            # soft skip: only taken if nothing else legal
SCORE_HARD_SKIP = -5000      # hard skip: strongly avoid (e.g. Crustle no-ex)
# ─────────────────────────────────────────────────────────────────────────

POKE_PAD = 1152
ULTRA_BALL = 1121
POKEGEAR = 1122
NIGHT_STRETCHER = 1097
JUMBO_ICE_CREAM = 1147
HERO_CAPE = 1159
DUSK_BALL = 1102  # Look at bottom 7 of deck, may take a Pokemon found there. Free
                  # (no discard/energy cost), not an Ace Spec -> can run alongside
                  # Hero's Cape. Weaker per-use than a whole-deck tutor (only 7
                  # cards), added in place of situational Jumbo Ice Cream copies
                  # to raise setup-by-T6 without giving up Cape's Lucario tech.
BOSS = 1182
EXPLORER = 1185
LILLIE = 1227
JUDGE = 1213
FULL_METAL_LAB = 1244

RAGING_HAMMER = 224
METAL_DEFENDER = 253

_ATTACK_BASE_DMG = {METAL_DEFENDER: 220, 965: 50, 223: 30, 61: 30}

_SETUP_ACTIVE_PRIORITY = {
    CINDERACE: (100000, "Active: Cinderace Explosiveness"),
    DURALUDON: (20000, "Active fallback: Duraludon"),
    RELICANTH: (5000, "Active fallback: Relicanth"),
}

ALWAYS_SAFE_DISCARD = {METAL_ENERGY, CINDERACE}

CARD_DB = {c.cardId: c for c in all_card_data()}

MEGA_BRAVE = 983
PREMIUM_POWER_PRO = 1141
HARIYAMA_LINE = {673, 674}

# Mill archetype signal cards (our own Crustle Wall's mirror: Great Tusk mills
# the deck, Xerosic's Machinations locks the hand). Xerosic is a Supporter —
# it leaves play the turn it's used, so detection must also check discard,
# not just active+bench.
GREAT_TUSK = 58
XEROSIC_MACHINATIONS = 1197
MILL_SIGNAL_IDS = {GREAT_TUSK}  # C0-1: Xerosic alone is not enough to declare mill

# Track opponent's last-turn attack via logs
_opp_last_attack_id = None
_cur_turn_logs = []
# Sticky once-seen flag: replays_16/17 showed the existing Crustle matchup
# protections (skip Metal Defender into ex-immunity, throttle draw at low
# deck count) only fire while Crustle-line Pokemon are currently in
# ids & CRUSTLE_LINE  (see detect_matchup). Great Tusk decks can go several
# turns before Crustle is out, or lose all Crustle copies to KOs later, during
# which the matchup silently reverted to "generic" and dropped protection.
# This flag, once True, stays True for the rest of the game.
_opp_mill_seen = False


def _update_opp_attack_tracking(obs):
    global _opp_last_attack_id, _cur_turn_logs
    yi = obs.current.yourIndex
    for entry in obs.logs:
        if entry.type == LogType.TURN_END:
            for prev in _cur_turn_logs:
                if prev.type == LogType.ATTACK and getattr(prev, 'playerIndex', yi) != yi:
                    _opp_last_attack_id = prev.attackId
            _cur_turn_logs.clear()
        else:
            _cur_turn_logs.append(entry)


# ── Board helpers ──

def read_deck_csv():
    fp = "deck.csv"
    if not os.path.exists(fp):
        fp = "/kaggle_simulations/agent/deck.csv"
    with open(fp) as f:
        return [int(line) for line in f.read().strip().split("\n")]


def get_card(obs, area, index, player_index):
    if area is None or index is None:
        return None
    ps = obs.current.players[player_index]
    if area == AreaType.DECK and obs.select and obs.select.deck is not None:
        return obs.select.deck[index] if index < len(obs.select.deck) else None
    if area == AreaType.HAND and ps.hand is not None:
        return ps.hand[index] if index < len(ps.hand) else None
    if area == AreaType.DISCARD:
        return ps.discard[index] if index < len(ps.discard) else None
    if area == AreaType.ACTIVE:
        return ps.active[index] if index < len(ps.active) else None
    if area == AreaType.BENCH:
        return ps.bench[index] if index < len(ps.bench) else None
    if area == AreaType.PRIZE:
        return ps.prize[index] if index < len(ps.prize) else None
    if area == AreaType.STADIUM:
        return obs.current.stadium[index] if index < len(obs.current.stadium) else None
    if area == AreaType.LOOKING and obs.current.looking is not None:
        return obs.current.looking[index] if index < len(obs.current.looking) else None
    return None


def option_card(obs, opt):
    yi = obs.current.yourIndex
    pi = opt.playerIndex if opt.playerIndex is not None else yi
    if opt.type == OptionType.PLAY:
        return get_card(obs, AreaType.HAND, opt.index, pi)
    return get_card(obs, opt.area, opt.index, pi)


def option_target(obs, opt):
    if opt.inPlayArea is None or opt.inPlayIndex is None:
        return None
    return get_card(obs, opt.inPlayArea, opt.inPlayIndex, obs.current.yourIndex)


def my_state(obs):
    return obs.current.players[obs.current.yourIndex]


def opp_state(obs):
    return obs.current.players[1 - obs.current.yourIndex]


def active_pokemon(obs):
    ps = my_state(obs)
    return ps.active[0] if ps.active else None


def opp_active_pokemon(obs):
    ps = opp_state(obs)
    return ps.active[0] if ps.active else None


def opp_bench_pokemon(obs):
    return [p for p in opp_state(obs).bench if p]


def all_my_pokemon(obs):
    ps = my_state(obs)
    return [p for p in (ps.active + ps.bench) if p]


def hand_ids(obs):
    hand = my_state(obs).hand
    return [c.id for c in hand if c] if hand else []


def discard_ids(obs):
    return [c.id for c in (my_state(obs).discard or []) if c]


def metal_in_discard(obs):
    return sum(1 for c in (my_state(obs).discard or []) if c and c.id == METAL_ENERGY)


def energy_count(pokemon):
    if pokemon is None:
        return 0
    if getattr(pokemon, "energyCards", None) is not None:
        return len(pokemon.energyCards)
    return len(getattr(pokemon, "energies", []) or [])


def retreat_cost(pokemon):
    data = CARD_DB.get(pokemon.id) if pokemon else None
    return getattr(data, "retreatCost", 0) if data else 0


def damage_on(pokemon):
    if pokemon is None:
        return 0
    return max(0, getattr(pokemon, "maxHp", pokemon.hp) - pokemon.hp)


def has_tool(pokemon):
    return bool(getattr(pokemon, "tools", []) or [])


def count_in_play(obs, card_id):
    return sum(1 for p in all_my_pokemon(obs) if p.id == card_id)


def has_in_play(obs, card_id):
    return any(p.id == card_id for p in all_my_pokemon(obs))


def need_duraludon(obs):
    return sum(1 for p in all_my_pokemon(obs) if p.id in {DURALUDON, ARCHALUDON_EX}) < 2


def need_archaludon(obs):
    has_dura, ex_count = False, 0
    for p in all_my_pokemon(obs):
        if p.id == DURALUDON:
            has_dura = True
        elif p.id == ARCHALUDON_EX:
            ex_count += 1
    return has_dura and ex_count < 2


def safe_discard_count(obs):
    ids = hand_ids(obs)
    mt = metal_in_discard(obs)
    safe = 0
    for cid in ids:
        if cid == METAL_ENERGY and mt + safe < 2:
            safe += 1
        elif cid == CINDERACE:
            safe += 1
    draw_in_hand = sum(1 for c in ids if c in (LILLIE, EXPLORER))
    if draw_in_hand >= 2:
        safe += draw_in_hand - 1
    return safe


def prize_value(pokemon):
    data = CARD_DB.get(pokemon.id) if pokemon else None
    if data and getattr(data, "megaEx", False):
        return 3
    if data and getattr(data, "ex", False):
        return 2
    return 1


def best_attack_damage(obs, attack_id):
    if attack_id == RAGING_HAMMER:
        return 80 + damage_on(active_pokemon(obs)) // 10 * 10
    return _ATTACK_BASE_DMG.get(attack_id, 0)


def is_metal_weak(pokemon):
    if pokemon is None:
        return False
    data = CARD_DB.get(pokemon.id)
    w = getattr(data, "weakness", None) if data else None
    if w is None:
        return False
    return getattr(w, "value", w) == METAL_ENERGY


def effective_damage(base_damage, target):
    return base_damage * 2 if is_metal_weak(target) else base_damage


def _first_option_index(obs, card_id):
    for o in obs.select.option:
        oc = option_card(obs, o)
        if oc and oc.id == card_id:
            return getattr(o, 'index', None)
    return None


# ── Attack routes ──

def direct_attack_energy_route(obs, pokemon):
    e = energy_count(pokemon)
    if e >= 3:
        return True, False
    if e == 2 and not obs.current.energyAttached and METAL_ENERGY in hand_ids(obs):
        return True, True
    return False, False


def can_evolve_to_archaludon_now(pokemon, obs):
    if pokemon is None or pokemon.id != DURALUDON:
        return False
    if ARCHALUDON_EX not in hand_ids(obs):
        return False
    return not getattr(pokemon, "appearThisTurn", True)


def alloy_attack_energy_route(obs, pokemon):
    if not can_evolve_to_archaludon_now(pokemon, obs):
        return False, False
    current = energy_count(pokemon)
    alloy = min(2, metal_in_discard(obs))
    total = current + alloy
    if total >= 3:
        return True, False
    if total == 2 and not obs.current.energyAttached and METAL_ENERGY in hand_ids(obs):
        return True, True
    return False, False


def attack_energy_route(obs, pokemon):
    if pokemon is None:
        return False, False
    if pokemon.id == ARCHALUDON_EX:
        return direct_attack_energy_route(obs, pokemon)
    if pokemon.id == DURALUDON:
        ok, uses_attach = direct_attack_energy_route(obs, pokemon)
        if ok:
            return True, uses_attach
        return alloy_attack_energy_route(obs, pokemon)
    return False, False


def archaludon_ex_attack_route(obs):
    active = active_pokemon(obs)
    if active and active.id in {ARCHALUDON_EX, DURALUDON}:
        ok, uses_attach = attack_energy_route(obs, active)
        if ok:
            return {"attacker": active, "uses_attach": uses_attach, "needs_retreat": False}

    if active is None or obs.current.retreated or energy_count(active) < retreat_cost(active):
        return None
    ps = my_state(obs)
    for pokemon in [p for p in ps.bench if p]:
        if pokemon.id not in {ARCHALUDON_EX, DURALUDON}:
            continue
        ok, uses_attach = attack_energy_route(obs, pokemon)
        if ok:
            return {"attacker": pokemon, "uses_attach": uses_attach, "needs_retreat": True}
    return None


def planned_archaludon_attacks(obs):
    route = archaludon_ex_attack_route(obs)
    if route is None:
        return []
    attacker = route["attacker"]
    attacks = []
    if attacker.id == ARCHALUDON_EX:
        attacks.append({"damage": 220})
        if has_in_play(obs, RELICANTH):
            attacks.append({"damage": 80 + damage_on(attacker) // 10 * 10})
    if attacker.id == DURALUDON:
        attacks.append({"damage": 80 + damage_on(attacker) // 10 * 10})
        if can_evolve_to_archaludon_now(attacker, obs):
            attacks.append({"damage": 220})
    return attacks


# ── Matchup detection & opponent max damage ──

ALAKAZAM_LINE = {741, 742, 743}
_ALA_BOARD_GAIN = {66: 3, 742: 2, 305: 2, 65: 2, 741: 1}  # Dudunsparce, Kadabra, Dunsparce×2, Abra


def _estimate_alakazam_from_pokes(opp, pokes):
    """(floor, ceiling, ceiling_with_boss) damage from visible Alakazam line."""
    ids = [p.id for p in pokes if p]
    if not (ALAKAZAM_LINE & set(ids)):
        return 0, 0, 0
    base = opp.handCount + 1
    gain = sum(_ALA_BOARD_GAIN.get(i, 0) for i in ids)
    enriching_seen = (
        any(c and c.id == 13 for c in (opp.discard or []))
        or any(c and c.id == 13 for p in pokes if p for c in (getattr(p, "energyCards", None) or []))
    )
    if not enriching_seen:
        gain += 3
    if any(i == 140 for i in ids):
        gain += 3
    return base * 20, (base + gain + 2) * 20, (base + gain - 1) * 20


def _estimate_alakazam(obs):
    """(floor, ceiling, ceiling_with_boss) damage from Powerful Hand."""
    opp = opp_state(obs)
    pokes = ([opp.active[0]] if opp.active else []) + list(opp.bench or [])
    return _estimate_alakazam_from_pokes(opp, pokes)


def detect_matchup(obs):
    global _opp_mill_seen
    opp = opp_state(obs)
    ids = {p.id for p in (opp.active + opp.bench) if p}
    seen_ids = ids | {c.id for c in (opp.discard or []) if c}
    if seen_ids & MILL_SIGNAL_IDS:
        _opp_mill_seen = True
    if (ids & CRUSTLE_LINE) or _opp_mill_seen:
        return "crustle"
    if ids & HOP_LINE:
        return "hop"
    if ids & STARMIE_LINE:
        return "starmie"
    if ids & LUCARIO_LINE:
        return "lucario"
    if ids & ALAKAZAM_LINE:
        return "alakazam"
    if ids & MIRROR_LINE:
        return "mirror"
    return "generic"


def opp_max_damage(obs):
    matchup = detect_matchup(obs)
    if matchup == "alakazam":
        _, ceiling, _ = _estimate_alakazam(obs)
        return ceiling
    if matchup == "crustle":
        return 120
    if matchup == "hop":
        return 220
    if matchup == "lucario":
        return 270  # Mega Brave base. PPP adds +30 each but unpredictable
    if matchup == "starmie":
        return 210
    if matchup == "mirror":
        # Metal Defender 220 base; Raging Hammer = 80 + damage taken, so a
        # wounded opposing Duraludon/Archaludon can exceed 220. Track it.
        threat = 220
        opp = opp_state(obs)
        for p in (opp.active + opp.bench):
            if p and p.id in MIRROR_LINE:
                threat = max(threat, 80 + damage_on(p) // 10 * 10)
        return threat
    return 220


# ── Overrides ──
#
# Each matchup gets one function: (obs, opt, score, reason) -> (score, reason).
# Only Crustle and Hop have active overrides today; Alakazam/Lucario/Starmie
# currently rely on opp_max_damage() + _ICE_CREAM_HP_THRESHOLD for defense
# and have no offense-side overrides yet (see analysis notes).

def _override_crustle(obs, opt, score, reason):
    card = option_card(obs, opt)
    cid = card.id if card else getattr(opt, 'cardId', None)
    ctx = obs.select.context

    if opt.type == OptionType.EVOLVE and cid == ARCHALUDON_EX:
        return SCORE_HARD_SKIP * 2, "Crustle: don't evolve to ex"

    if opt.type == OptionType.ATTACK:
        aid = getattr(opt, 'attackId', None)
        active = active_pokemon(obs)
        opp_act = opp_active_pokemon(obs)
        opp_has_spiky = bool(opp_act and any(
            getattr(c, 'id', None) == 14
            for c in (getattr(opp_act, 'energyCards', None) or [])))
        if (active and active.id == DURALUDON and active.hp == 130
                and opp_act and opp_act.id == 345 and energy_count(opp_act) >= 2
                and opp_has_spiky):
            return -3000, "Crustle: full HP Duraludon waits out Spiky"
        if aid == METAL_DEFENDER:
            # Crustle's ex-immunity only nullifies attacks against Crustle
            # itself — it does not make every Pokemon in a Crustle-archetype
            # deck immune. Great Tusk (140 hp, no immunity) dies to a single
            # Metal Defender (220). Blanket-skipping it whenever the opponent
            # is *recognized* as the Crustle/mill archetype (matchup=="crustle")
            # meant Metal Defender was never used even when the actual active
            # target was a killable, non-immune Great Tusk — the single biggest
            # gap found in replays_16/17's Tusk-matchup losses.
            if opp_act and opp_act.id in CRUSTLE_LINE:
                return SCORE_HARD_SKIP, "Crustle: Metal Defender does 0 (ex-immune target)"
            # else: fall through to the un-overridden score (best_attack_damage),
            # so a killable non-immune active (e.g. Great Tusk) attacks normally.
        elif aid == RAGING_HAMMER:
            return max(score, 200), "Crustle: Raging Hammer"

    if opt.type == OptionType.PLAY:
        if cid == RELICANTH:
            return SCORE_HARD_SKIP, "Crustle: skip Relicanth"
        dc = my_state(obs).deckCount
        if dc <= 14 and cid in (EXPLORER, LILLIE):
            if cid == LILLIE and dc <= 3 and my_state(obs).handCount >= dc + 6:
                return 15000, "Crustle: Lillie to refill deck"
            return SCORE_HARD_SKIP, "Crustle: don't draw with low deck"
        if cid == LILLIE:
            has_metal = any(c and c.id == METAL_ENERGY for c in (my_state(obs).hand or []) if c)
            if not has_metal:
                return score, "Crustle: Lillie OK (no energy in hand)"

    if opt.type == OptionType.ATTACH:
        target = option_target(obs, opt)
        tid = target.id if target else None
        if getattr(opt, 'inPlayArea', None) == AreaType.BENCH and tid == DURALUDON:
            return score + 10000, "Crustle: bench Duraludon energy priority"
        if getattr(opt, 'inPlayArea', None) == AreaType.ACTIVE:
            active = active_pokemon(obs)
            if active and energy_count(active) >= 2:
                return score + 3000, "Crustle: Active 3rd energy"

    if ctx == SelectContext.TO_HAND and opt.type == OptionType.CARD and cid == ARCHALUDON_EX:
        return -3000, "Crustle: skip Archaludon ex"

    if ctx in {SelectContext.DISCARD, SelectContext.DISCARD_CARD_OR_ATTACHED_CARD}:
        if cid == ARCHALUDON_EX and score < 0:
            return 9000, "Crustle: discard Archaludon ex"

    return score, reason


def _override_hop(obs, opt, score, reason):
    """vs Hop: Snorlax (Extra Helpings, +30 dmg to bench) is the priority
    Boss's Orders target. This consolidates the PLAY-Boss decision (should
    we use Boss at all, and does our active threaten Snorlax) that used to
    live inline in score_play. Note: which specific Snorlax to drag (when
    the opponent has one) is still resolved in score_target's SWITCH branch,
    since that requires comparing multiple candidate targets, not a single
    on/off decision.
    """
    card = option_card(obs, opt)
    cid = card.id if card else getattr(opt, 'cardId', None)
    ctx = obs.select.context
    active = active_pokemon(obs)

    if opt.type == OptionType.PLAY and cid == BOSS and not obs.current.supporterPlayed:
        opp_has_snorlax = any(p.id == HOP_SNORLAX for p in opp_bench_pokemon(obs))
        if opp_has_snorlax and active:
            if active.id == CINDERACE:
                has_dura_bench = any(p.id in {DURALUDON, ARCHALUDON_EX}
                                      for p in my_state(obs).bench if p)
                if has_dura_bench:
                    return 16500, "Boss: pull Snorlax (Cinderace Turbo Flare)"
            if active.id == ARCHALUDON_EX and active.hp > 220:
                ok, _ = attack_energy_route(obs, active)
                if ok:
                    return 16500, "Boss: pull Snorlax (Arch can tank Revenge 220)"

    return score, reason


def _override_alakazam(obs, opt, score, reason):
    """vs Alakazam: Powerful Hand's damage scales with the opponent's hand
    size and board (see _ALA_BOARD_GAIN). The line is much less scary while
    still Abra/Kadabra on the bench — dragging it out with Boss before it
    reaches Alakazam (or before Dudunsparce/Kadabra stack more +dmg) caps
    their ceiling. This is a pure Boss-target preference; it does not touch
    whether to play Boss at all (that's decided in score_play's BOSS branch,
    which already checks planned_archaludon_attacks for a KO route).
    """
    if opt.type != OptionType.PLAY:
        return score, reason
    card = option_card(obs, opt)
    cid = card.id if card else None
    if cid != BOSS or obs.current.supporterPlayed:
        return score, reason
    # Only nudge if we don't already have a stronger reason (LETHAL etc.)
    # apply_overrides runs after score_play, so `score` already reflects
    # whether Boss is otherwise justified (attacker ready / KO available).
    if score < 0:
        return score, reason
    bench_ids = {p.id for p in opp_bench_pokemon(obs)}
    early_line = bench_ids & {741, 742}  # Abra, Kadabra — not yet Alakazam
    if early_line and 743 not in bench_ids:
        return score + 500, "Boss: drag early Alakazam line before it enriches"
    return score, reason


def _override_lucario(obs, opt, score, reason):
    # Mega Lucario ex (340 HP, worth 3 prizes) is 2-hit KO'd by Metal Defender
    # (220x2). Key: survive Mega Brave 270 (+30/Premium Power Pro) so our
    # Archaludon lives to land the second hit. Hero's Cape (+100 HP -> 400)
    # turns a lethal Mega Brave into a survivable one, swinging the 3-prize
    # race. Prioritize Cape on our Metal attacker before it is KO'd. Validated
    # on real Mega Lucario decks + a faithful beatdown pilot (+3-10pp).
    card = option_card(obs, opt)
    cid = card.id if card else getattr(opt, 'cardId', None)
    if cid == HERO_CAPE and opt.type in (OptionType.PLAY, OptionType.ATTACH):
        cape_target = None
        if opt.type == OptionType.ATTACH:
            tgt = option_target(obs, opt)
            cape_target = tgt.id if tgt else None
        has_capeable = any(
            p.id in (ARCHALUDON_EX, DURALUDON) and not has_tool(p)
            for p in all_my_pokemon(obs) if p)
        if has_capeable and (opt.type == OptionType.PLAY or cape_target in (ARCHALUDON_EX, DURALUDON)):
            return max(score, 14000), "vs Lucario: Cape to survive Mega Brave (+3-prize swing)"
    return score, reason


def _override_starmie(obs, opt, score, reason):
    # TODO: no offense-side override yet. Same caution as Lucario — add
    # only after replay evidence justifies a specific rule, not by guessing.
    return score, reason


def _override_mirror(obs, opt, score, reason):
    """Mirror (opp also plays Duraludon/Archaludon ex). The mirror is a
    2-hit race between 220-damage attackers, so tempo denial dominates:
    - KO their benched, pre-evolved Duraludon (130 HP, one-shot) before it
      becomes Archaludon: removes their next attacker for 1 cheap prize.
    - KO their benched Cinderace (160 HP, one-shot): removes Turbo Flare
      energy acceleration, slowing every future attacker they field.
    Both bonuses apply to Boss's-Orders target selection (SWITCH/TO_ACTIVE
    on the opponent's side); generic 'Boss: KO' scoring already ranks
    killable targets — these nudges break ties toward the tempo plays.
    """
    ctx = obs.select.context
    if ctx not in {SelectContext.SWITCH, SelectContext.TO_ACTIVE}:
        return score, reason
    yi = obs.current.yourIndex
    if getattr(opt, 'playerIndex', yi) == yi:
        return score, reason
    card = option_card(obs, opt)
    cid = card.id if card else getattr(opt, 'cardId', None)
    if cid == DURALUDON:
        return score + 2500, "mirror: deny next attacker (pre-evo Duraludon)"
    if cid == CINDERACE:
        return score + 1500, "mirror: kill accel engine (Cinderace)"
    return score, reason


_MATCHUP_OVERRIDES = {
    "crustle": _override_crustle,
    "hop": _override_hop,
    "alakazam": _override_alakazam,
    "lucario": _override_lucario,
    "starmie": _override_starmie,
    "mirror": _override_mirror,
}


def apply_overrides(obs, opt, score, reason):
    # Hard rule: don't self-mill with low deck (applies regardless of matchup).
    # Covers both draw supporters; Lillie was the unguarded leak that lost
    # stalled Alakazam games to our own deck-out.
    if opt.type == OptionType.PLAY:
        card = option_card(obs, opt)
        cid = card.id if card else None
        dc = my_state(obs).deckCount
        if dc <= 10 and cid == EXPLORER:
            return SCORE_HARD_SKIP, "hard: don't Explorer with low deck"
        if dc <= 6 and cid == LILLIE and my_state(obs).handCount < dc + 6:
            return SCORE_HARD_SKIP, "hard: don't Lillie into deck-out"

    # A2: 対面別オーバーライドより先に、サイドレース汎用調整を通す
    score, reason = _generic_prize_override(obs, opt, score, reason)

    fn = _MATCHUP_OVERRIDES.get(detect_matchup(obs))
    if fn is None:
        return score, reason
    return fn(obs, opt, score, reason)


# ================================================================
# v6 candidate patches: B1 (2-step lethal) / A2 (prize race) / A3 (draw stop)
# 1提出=1フラグ。まず B1 → 次 A3 → 最後 A2 の順で個別測定推奨。
# ================================================================
ENABLE_B1_TWO_STEP_LETHAL = False   # リトリート→ベンチアタッカーで致死の2手経路を最優先化
ENABLE_A2_PRIZE_RACE      = False   # 相手サイドリーチ時は生存(Ice Cream/Cape)を優先
ENABLE_A3_DRAW_STOP       = True    # 勝ち確 or 山薄+攻撃可能なら任意ドローを止めて山切れ自滅を防ぐ

SCORE_TWO_STEP_LETHAL = 50000       # setup帯(<=32000)より上、FORCED(100000)より下

# ── サイドレース状態 ──
def my_prizes_left(obs):
    return len(my_state(obs).prize)


def opp_prizes_left(obs):
    return len(opp_state(obs).prize)


def my_at_prize_reach(obs):
    # 残り2枚以下 = ex1体KOで勝てる圏内
    return my_prizes_left(obs) <= 2


def opp_at_prize_reach(obs):
    return opp_prizes_left(obs) <= 2


# ── 勝ち確/アタッカー準備 判定（A3・B1共用）──
def attacker_ready(obs):
    return archaludon_ex_attack_route(obs) is not None


def win_secured_this_turn(obs):
    """今の盤面でActiveをKOでき、そのサイドで6枚取り切れる=このターン勝ち確。"""
    opp_act = opp_active_pokemon(obs)
    if not opp_act:
        return False
    attacks = planned_archaludon_attacks(obs)
    if not attacks:
        return False
    if not any(effective_damage(a["damage"], opp_act) >= opp_act.hp for a in attacks):
        return False
    return prize_value(opp_act) >= my_prizes_left(obs)


# ── A3: 山切れ自滅ガード ──
# Judge は手札を山に戻して4枚引く=山が減らない(むしろ増える)ので除外。
# Night Stretcher はトラッシュ回収で山を掘らないので除外。
_OPTIONAL_DRAW_CARDS = {POKE_PAD, POKEGEAR, DUSK_BALL, ULTRA_BALL, LILLIE, EXPLORER}


def _draw_stop_guard(obs, cid):
    if not ENABLE_A3_DRAW_STOP or cid not in _OPTIONAL_DRAW_CARDS:
        return False, ""
    # (1) このターン勝ち確なら任意ドローは全て不要（引いて山切れ即負けの事故を消す）
    if win_secured_this_turn(obs):
        return True, "A3: win secured, skip optional draw"
    # (2) 山が薄く、既に攻撃可能なアタッカーがいるなら掘りを止める
    dc = my_state(obs).deckCount or 0
    if dc <= 3 and attacker_ready(obs):
        return True, f"A3: low deck ({dc}) + attacker ready, skip draw"
    return False, ""


# ── A2: サイドレース汎用オーバーライド（全対面で発火）──
def _generic_prize_override(obs, opt, score, reason):
    if not ENABLE_A2_PRIZE_RACE:
        return score, reason
    card = option_card(obs, opt)
    cid = card.id if card else None
    # 相手がサイドリーチ(<=2)= 次のKOで負ける状況では、
    # 普段HP閾値でスキップする Jumbo Ice Cream / Hero's Cape を生存優先で使う。
    if opt.type == OptionType.PLAY and cid == JUMBO_ICE_CREAM and opp_at_prize_reach(obs):
        active = active_pokemon(obs)
        if active and active.id in {ARCHALUDON_EX, DURALUDON}:
            # 相手の最大打点が今のActiveを落とせるなら、回復して1ターン延命=レース逆転の芽
            if opp_max_damage(obs) >= active.hp and score < 0:
                return 12000, "A2: heal to survive (opp at prize reach)"
    if cid == HERO_CAPE and opt.type in (OptionType.PLAY, OptionType.ATTACH) and opp_at_prize_reach(obs):
        has_capeable = any(p.id in (ARCHALUDON_EX, DURALUDON) and not has_tool(p)
                           for p in all_my_pokemon(obs) if p)
        if has_capeable:
            return max(score, 15000), "A2: Cape survival (opp at prize reach)"
    return score, reason


# ── Scoring ──

def score_setup(obs, opt):
    card = option_card(obs, opt)
    cid = card.id if card else None
    ctx = obs.select.context

    if ctx == SelectContext.MULLIGAN:
        return (10000, "no mulligan") if opt.type == OptionType.NO else (0, "mulligan")
    if ctx == SelectContext.IS_FIRST:
        return (10000, "choose second") if opt.type == OptionType.NO else (0, "go first")
    if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
        return _SETUP_ACTIVE_PRIORITY.get(cid, (0, "unknown Active"))
    if ctx == SelectContext.SETUP_BENCH_POKEMON:
        return -10000, "never bench during setup"
    return 0, "non-setup"


# HP threshold per matchup: skip Ice Cream if HP > this value
_ICE_CREAM_HP_THRESHOLD = {
    "lucario": 270,
    "starmie": 210,
    "crustle": 120,
    "hop": 220,
    "generic": 230,
}


def should_skip_ice_cream(obs, active):
    """Decide whether to skip Jumbo Ice Cream. Returns (skip: bool, reason: str)."""
    # 1. Active must be Archaludon ex
    if active.id != ARCHALUDON_EX:
        return True, "skip Ice Cream: not Archaludon ex"
    # 2. Raging Hammer KO guard: don't heal if it loses a KO (but 220 Metal Defender still KOs → heal OK)
    opp_act = opp_active_pokemon(obs)
    if opp_act and has_in_play(obs, RELICANTH):
        md_kills = effective_damage(220, opp_act) >= opp_act.hp
        if not md_kills:
            rh_dmg = 80 + damage_on(active) // 10 * 10
            rh_after = 80 + max(0, damage_on(active) - 80) // 10 * 10
            if effective_damage(rh_dmg, opp_act) >= opp_act.hp and effective_damage(rh_after, opp_act) < opp_act.hp:
                return True, "skip Ice Cream: healing loses Raging Hammer KO"
    # 3. Alakazam: all-or-nothing Ice Cream decision
    matchup = detect_matchup(obs)
    if matchup == "alakazam":
        floor, ceiling, _ = _estimate_alakazam(obs)
        opp_a = opp_active_pokemon(obs)
        attacks = planned_archaludon_attacks(obs)
        if opp_a and attacks and any(effective_damage(a["damage"], opp_a) >= opp_a.hp for a in attacks):
            _, ceiling, _ = _estimate_alakazam_from_pokes(opp_state(obs), opp_bench_pokemon(obs))
        ice_count = sum(1 for c in (my_state(obs).hand or []) if c and c.id == JUMBO_ICE_CREAM)
        max_hp = getattr(active, "maxHp", active.hp)
        hp_after_all = min(max_hp, active.hp + ice_count * 80)
        if hp_after_all <= active.hp:
            return True, "skip Ice Cream: no effective healing"
        if hp_after_all < floor:
            return True, f"skip Ice Cream: even {ice_count}x heal ({hp_after_all}) < floor {floor}"
        if hp_after_all >= ceiling:
            return False, f"use Ice Cream: {ice_count}x heal ({hp_after_all}) >= ceil {ceiling}"
        return False, f"use Ice Cream: {ice_count}x heal ({hp_after_all}) between floor={floor} ceil={ceiling}"
    # 4. HP above matchup threshold
    threshold = _ICE_CREAM_HP_THRESHOLD.get(matchup, 220)
    if active.hp > threshold:
        return True, f"skip Ice Cream: HP {active.hp} > {threshold} ({matchup})"
    # 5. Use it
    return False, ""


ITEMS = {POKE_PAD, ULTRA_BALL, POKEGEAR, NIGHT_STRETCHER, JUMBO_ICE_CREAM, HERO_CAPE, DUSK_BALL}


def score_play(obs, opt):
    card = option_card(obs, opt)
    cid = card.id if card else None
    ids = hand_ids(obs)

    # ── A3: 山切れ自滅ガード（勝ち確 or 山薄+攻撃可能なら任意ドローを止める）──
    _stop, _why = _draw_stop_guard(obs, cid)
    if _stop:
        return SCORE_HARD_SKIP, _why

    # ── Pokemon: bench if available ──
    if cid in {DURALUDON, RELICANTH}:
        return SCORE_PLAY_POKEMON, "play Pokemon"

    # ── Stadium ──
    if cid == FULL_METAL_LAB:
        active = active_pokemon(obs)
        if active and active.id not in {DURALUDON, ARCHALUDON_EX}:
            return -200, "skip FML: Active not Metal"
        return SCORE_SEARCH, "play Full Metal Lab"

    # ── Items: default 20000, only negative exceptions ──
    if cid in ITEMS:
        if cid == HERO_CAPE:
            if not any(p.id in {ARCHALUDON_EX, DURALUDON} and not has_tool(p) for p in all_my_pokemon(obs)):
                return -500, "save Hero's Cape: no target"
        if cid == JUMBO_ICE_CREAM:
            active = active_pokemon(obs)
            if active:
                skip, reason = should_skip_ice_cream(obs, active)
                if skip:
                    return -500, reason
        if cid == NIGHT_STRETCHER:
            disc = discard_ids(obs)
            has_urgent = (
                (DURALUDON in disc and DURALUDON not in ids and count_in_play(obs, DURALUDON) + count_in_play(obs, ARCHALUDON_EX) <= 1)
                or (ARCHALUDON_EX in disc and ARCHALUDON_EX not in ids and has_in_play(obs, DURALUDON))
                or (METAL_ENERGY in disc and not obs.current.energyAttached
                    and sum(1 for c in (my_state(obs).hand or []) if c and c.id == METAL_ENERGY) == 0
                    and any(p and p.id in (DURALUDON, ARCHALUDON_EX) and energy_count(p) == 2 for p in all_my_pokemon(obs)))
            )
            if not has_urgent:
                return -500, "save Night Stretcher"
        if cid == ULTRA_BALL:
            bench_empty = len([p for p in my_state(obs).bench if p]) == 0
            if bench_empty:
                return 300, "Ultra Ball: bench empty (donk risk)"
            metal_in_hand = sum(1 for c in (my_state(obs).hand or []) if c and c.id == METAL_ENERGY)
            metal_in_trash = metal_in_discard(obs)
            if metal_in_trash == 0 and metal_in_hand >= 1:
                return SCORE_SEARCH, "Ultra Ball: fuel Alloy"
            if safe_discard_count(obs) >= 2 and (need_archaludon(obs) or need_duraludon(obs)):
                return SCORE_SEARCH, "Ultra Ball: search line"
            return -1000, "skip Ultra Ball"
        if cid == DUSK_BALL:
            # No cost (unlike Ultra Ball's discard-2), so there is no downside
            # to firing it early: worst case the bottom 7 has no Pokemon and it
            # whiffs for free. What it fetches is handled by score_to_hand's
            # existing Duraludon/Archaludon-ex priority ordering.
            if need_archaludon(obs) or need_duraludon(obs):
                return SCORE_SEARCH, "Dusk Ball: dig for combo piece"
            return SCORE_SEARCH - 3000, "Dusk Ball: generic dig"
        return SCORE_SEARCH, "play item"

    if cid == EXPLORER:
        if obs.current.supporterPlayed:
            return -1000, "Supporter already used"
        return SCORE_SUPPORTER_PRIMARY, "play Explorer"

    if cid == LILLIE:
        if obs.current.supporterPlayed:
            return -1000, "Supporter already used"
        if BOSS in ids and planned_archaludon_attacks(obs):
            return -500, "save Lillie: Boss in hand with attacker ready"
        return 5000, "play Lillie"

    if cid == JUDGE:
        if obs.current.supporterPlayed:
            return -1000, "Supporter already used"
        # Hand-state adaptive counter: Alakazam's Powerful Hand does 20 dmg per
        # card in their hand (hand 20 -> 400 = OHKO through Cape). Judge resets
        # both hands to 4 (caps them at 80). Replays show we sat on Judge
        # through 162 big-hand moments across 6 losses — never fire it as a
        # generic play, always fire it once their hand-loop is online.
        opp_hand = getattr(opp_state(obs), "handCount", 0) or 0
        if detect_matchup(obs) == "alakazam":
            launcher_up = any(
                p and p.id == 743
                for p in (opp_state(obs).active or []) + (opp_state(obs).bench or []))
            my_hand = my_state(obs).handCount or 0
            if opp_hand >= 7 and launcher_up and opp_hand - my_hand >= 3:
                return 21000, "JUDGE: cap Powerful Hand (net hand destruction)"
            return -600, "save Judge for the hand-loop"
        return 1000, "generic play"

    if cid == BOSS:
        if obs.current.supporterPlayed:
            return -1000, "Supporter already used"
        # NOTE: vs-Hop Snorlax-pull priority and vs-Alakazam early-line-drag
        # priority are handled by matchup overrides via apply_overrides(),
        # which runs on every score_option() result after this returns.
        return score_boss(obs)

    return 1000, "generic play"


def _boss_lethal_check(obs, attacks, remaining):
    """Return (score, reason) if any Boss pull secures game-ending prizes
    this turn, else None. Checked first since it short-circuits everything
    else (a guaranteed win beats board development)."""
    for target in opp_bench_pokemon(obs):
        for atk in attacks:
            if effective_damage(atk["damage"], target) >= target.hp:
                if prize_value(target) >= remaining:
                    return SCORE_BOSS_LETHAL, "LETHAL Boss"
                break
    return None


def _boss_active_ko_case(obs, attacks, opp_act, remaining):
    """Opponent's Active is inside our KO range. Usually correct to just
    attack it rather than spend a Supporter dragging something else —
    unless dragging a bench target would itself be lethal."""
    if prize_value(opp_act) >= remaining:
        return -500, "save Boss: Active KO wins"
    lethal = _boss_lethal_check(obs, attacks, remaining)
    if lethal:
        return lethal
    return -500, "save Boss: can KO Active"


def _boss_bench_pull_case(obs, attacks, remaining):
    """No free KO on Active. Look for the best bench target we can KO by
    dragging it up — prioritized by prize value, then energy investment
    (more energy = more tempo lost for them, i.e. a better drag target)."""
    lethal = _boss_lethal_check(obs, attacks, remaining)
    if lethal:
        return lethal
    best_score, best_reason = -500, "save Boss"
    for target in opp_bench_pokemon(obs):
        for atk in attacks:
            if effective_damage(atk["damage"], target) >= target.hp:
                pv = prize_value(target)
                s = 4000 + pv * 200 + energy_count(target) * 100
                if s > best_score:
                    best_score, best_reason = s, "Boss: pull bench target"
                break
    return best_score, best_reason


def _boss_stall_case(obs):
    """No KO available anywhere and our own energy base is thin (<=2 total,
    no Cinderace, no draw support in hand) — i.e. we're not about to close
    the game soon. In that state, dragging up the opponent's most retreat-
    costly / highest-energy-requirement bench Pokemon buys time rather than
    developing our board."""
    metal_total = sum(1 for c in (my_state(obs).hand or []) if c and c.id == METAL_ENERGY)
    metal_total += sum(energy_count(p) for p in all_my_pokemon(obs) if p)
    has_cind = has_in_play(obs, CINDERACE)
    draw_in_hand = any(c and c.id in (EXPLORER, LILLIE) for c in (my_state(obs).hand or []) if c)
    if metal_total > 2 or has_cind or draw_in_hand:
        return None

    best_stall, stall_reason = -500, "save Boss"
    for target in opp_bench_pokemon(obs):
        te = energy_count(target)
        cd = CARD_DB.get(target.id)
        rc = cd.retreatCost if cd else 0
        min_atk = 99
        if cd and cd.attacks:
            for aid in cd.attacks:
                atk = ALL_ATTACKS.get(aid)
                if atk:
                    min_atk = min(min_atk, len(atk.energies))
        if min_atk == 99:
            min_atk = 1
        ss = 4000 + rc * 1000 + min_atk * 500 - te * 800
        if ss > best_stall:
            best_stall, stall_reason = ss, "Boss stall"
    return best_stall, stall_reason


def score_boss(obs):
    """Decide whether/how to play Boss's Orders. Three cases, checked in
    order: (1) can we already KO the Active without Boss — then only use
    Boss if it's outright lethal elsewhere; (2) can we KO something on the
    bench by dragging it — take the highest-value drag; (3) neither — hold
    Boss unless we're in a stalling posture (thin energy base), in which
    case drag their most awkward-to-replace bench Pokemon.
    """
    if _opp_last_attack_id == MEGA_BRAVE:
        return -500, "save Boss: Mega Brave stuck"
    attacks = planned_archaludon_attacks(obs)
    if not attacks:
        return -500, "save Boss: no attacker"

    opp_act = opp_active_pokemon(obs)
    remaining = len(my_state(obs).prize)
    can_ko_active = opp_act and any(
        effective_damage(atk["damage"], opp_act) >= opp_act.hp for atk in attacks)

    if can_ko_active:
        return _boss_active_ko_case(obs, attacks, opp_act, remaining)

    best_score, best_reason = _boss_bench_pull_case(obs, attacks, remaining)
    if best_score <= 0:
        stall = _boss_stall_case(obs)
        if stall:
            return stall
    return best_score, best_reason


def score_evolve(obs, opt):
    card = option_card(obs, opt)
    target = option_target(obs, opt)
    cid = card.id if card else None
    tid = target.id if target else None
    if cid == ARCHALUDON_EX and tid == DURALUDON:
        target_is_active = opt.inPlayArea == AreaType.ACTIVE
        mc = metal_in_discard(obs)
        if target_is_active:
            if energy_count(target) >= 3 and not has_in_play(obs, ARCHALUDON_EX):
                return 17000, "evolve Active 3-energy Duraludon"
            if mc >= 2:
                return 28000 + mc * 2000, "evolve Active Duraludon"
            if mc == 1:
                return 8000, "delay Active evolve: 1 Metal"
            return -500, "hold: no Metal in discard"
        if mc >= 2:
            return 14000 + mc * 1000, "evolve Bench Duraludon"
        return -1000, "hold: evolve Active first"
    return 10000, "generic evolution"


def attach_target_score(obs, target, area):
    if target is None:
        return 0
    cid = target.id
    e = energy_count(target)

    if e >= 3:
        return -5000
    if cid == CINDERACE and e >= 1:
        return -3000

    score = 0
    if cid == CINDERACE:
        score = 3000
        if e == 0:
            score += 7000 + (12000 if area == AreaType.ACTIVE else 5000)
    elif cid in {DURALUDON, ARCHALUDON_EX}:
        score = 6000 if cid == ARCHALUDON_EX else 5500
        score += {2: 12000, 1: 7000, 0: 4000}.get(e, -1000)
        score += 1000 if area == AreaType.ACTIVE else 500
    else:
        score = 1000 + (1000 if e == 0 else 0)

    # HP-based adjustment
    if target.hp > 0:
        max_hp = getattr(target, "maxHp", target.hp)
        ratio = target.hp / max_hp if max_hp > 0 else 1
        if ratio <= 0.25:
            score -= 1500
        elif ratio <= 0.50:
            score -= 500
        else:
            score += min(1000, target.hp // 40 * 100)
    return score


def score_attach(obs, opt):
    card = option_card(obs, opt)
    target = option_target(obs, opt)
    cid = card.id if card else None
    tid = target.id if target else None

    if cid == HERO_CAPE:
        if tid == ARCHALUDON_EX and target and not has_tool(target):
            return 11000, "Hero's Cape on Archaludon ex"
        if tid == DURALUDON and target and not has_tool(target) and energy_count(target) >= 1:
            return 8000, "Hero's Cape on Duraludon"
        return -1000, "save Hero's Cape"

    if cid != METAL_ENERGY:
        return -500, "skip non-Metal"
    if obs.current.energyAttached:
        return -1000, "already attached"

    return attach_target_score(obs, target, opt.inPlayArea), "attach Metal"


def score_retreat(obs, opt):
    active = active_pokemon(obs)
    if active and active.id == ARCHALUDON_EX and has_tool(active) and active.hp > 200:
        return -5000, "don't retreat HP400 tank"
    route = archaludon_ex_attack_route(obs)
    if route and route["needs_retreat"]:
        # B1: リトリート→ベンチアタッカーの攻撃が致死なら、setup各種より優先して2手KOを取る。
        if ENABLE_B1_TWO_STEP_LETHAL:
            opp_act = opp_active_pokemon(obs)
            attacks = planned_archaludon_attacks(obs)  # 既にベンチアタッカー経路を反映
            if opp_act and attacks and any(
                    effective_damage(a["damage"], opp_act) >= opp_act.hp for a in attacks):
                if prize_value(opp_act) >= my_prizes_left(obs):
                    return SCORE_FORCED, "B1: retreat enables WINNING KO"
                return SCORE_TWO_STEP_LETHAL, "B1: retreat enables lethal KO on active"
        return 13000, "retreat to attack-ready ex"
    return -100, "avoid retreat"


def _attack_wins_game(obs, attack_id):
    """True if using this attack right now KOs the opponent's Active AND
    the prizes taken finish the game. Such an attack must outrank every
    other action — no board development beats winning immediately."""
    opp_act = opp_active_pokemon(obs)
    if not opp_act:
        return False
    dmg = effective_damage(best_attack_damage(obs, attack_id), opp_act)
    if dmg <= 0 or dmg < opp_act.hp:
        return False
    return prize_value(opp_act) >= len(my_state(obs).prize)


_MAIN_DISPATCH = {
    OptionType.PLAY: score_play, OptionType.EVOLVE: score_evolve,
    OptionType.ATTACH: score_attach, OptionType.RETREAT: score_retreat,
}


def score_option(obs, opt):
    ctx = obs.select.context

    if ctx in {SelectContext.IS_FIRST, SelectContext.MULLIGAN,
               SelectContext.SETUP_ACTIVE_POKEMON, SelectContext.SETUP_BENCH_POKEMON}:
        return score_setup(obs, opt)

    if opt.type in {OptionType.YES, OptionType.NO}:
        if ctx == SelectContext.IS_FIRST:
            return score_setup(obs, opt)
        if ctx == SelectContext.ACTIVATE:
            return (SCORE_FORCED, "Explosiveness") if opt.type == OptionType.YES else (-SCORE_FORCED, "never decline")
        return (1, "yes") if opt.type == OptionType.YES else (0, "no")

    if opt.type == OptionType.NUMBER:
        return (opt.number or 0), "number"

    if ctx == SelectContext.MAIN:
        fn = _MAIN_DISPATCH.get(opt.type)
        if fn:
            score, reason = fn(obs, opt)
        elif opt.type == OptionType.ABILITY:
            score, reason = 1, "ability"
        elif opt.type == OptionType.ATTACK:
            if _attack_wins_game(obs, opt.attackId):
                score, reason = SCORE_FORCED, "WINNING attack"
            else:
                score, reason = best_attack_damage(obs, opt.attackId), "attack"
        elif opt.type == OptionType.END:
            score, reason = 0, "end turn"
        else:
            score, reason = 500, "generic MAIN"
    elif ctx == SelectContext.TO_HAND:
        score, reason = score_to_hand(obs, opt)
    elif ctx in {SelectContext.DISCARD, SelectContext.DISCARD_CARD_OR_ATTACHED_CARD}:
        score, reason = score_discard(obs, opt)
    elif ctx in {SelectContext.ATTACH_TO, SelectContext.TO_FIELD, SelectContext.TO_BENCH,
                 SelectContext.ATTACH_FROM, SelectContext.SWITCH, SelectContext.TO_ACTIVE,
                 SelectContext.HEAL, SelectContext.DAMAGE}:
        score, reason = score_target(obs, opt)
    elif ctx == SelectContext.ATTACK:
        if _attack_wins_game(obs, opt.attackId):
            score, reason = SCORE_FORCED, "WINNING attack"
        else:
            score, reason = best_attack_damage(obs, opt.attackId), "attack"
    elif opt.type == OptionType.CARD:
        score, reason = score_to_hand(obs, opt)
    elif opt.type == OptionType.ENERGY:
        score, reason = 1000, "energy"
    elif opt.type == OptionType.END:
        score, reason = 0, "end"
    else:
        score, reason = 100, "fallback"

    score, reason = apply_overrides(obs, opt, score, reason)

    # C0-3: a matchup-specific defensive override must never suppress a legal
    # attack that KOs the current opposing Active. A small positive floor beats
    # END TURN while still allowing higher-band setup/evolution actions first.
    if opt.type == OptionType.ATTACK:
        opp_act = opp_active_pokemon(obs)
        if opp_act and effective_damage(best_attack_damage(obs, opt.attackId), opp_act) >= opp_act.hp:
            score = max(score, 200)
            reason = "C0-3 lethal guard: take available KO"

    return score, reason


def score_to_hand(obs, opt):
    card = option_card(obs, opt)
    cid = card.id if card else opt.cardId
    ids = hand_ids(obs)
    effect = getattr(obs.select, "effect", None)
    effect_id = effect.id if effect else None
    if cid == JUDGE and JUDGE not in ids and detect_matchup(obs) == "alakazam":
        return 26000, "take Judge: the Powerful Hand counter"

    if effect_id == EXPLORER:
        has_ready = any(p and p.id in (DURALUDON, ARCHALUDON_EX) and energy_count(p) >= 3
                        for p in all_my_pokemon(obs))
        metal_in_hand = sum(1 for c in (my_state(obs).hand or []) if c and c.id == METAL_ENERGY)

        if cid == HERO_CAPE:
            has_target = any(p.id == ARCHALUDON_EX and not has_tool(p) for p in all_my_pokemon(obs))
            return (27000 if has_target else 22000), "Explorer: Hero's Cape"
        if cid == METAL_ENERGY:
            if has_ready or metal_in_hand > 0:
                return 0, "Explorer: skip energy"
            if getattr(opt, 'index', 0) == _first_option_index(obs, METAL_ENERGY):
                return 25000, "Explorer: take 1st energy"
            return 0, "Explorer: skip 2nd energy"
        if cid == ARCHALUDON_EX and need_archaludon(obs):
            return 20000, "Explorer: take Archaludon ex"
        if cid == DURALUDON and need_duraludon(obs):
            return 18000, "Explorer: take Duraludon"
        if cid == RELICANTH and not has_in_play(obs, RELICANTH) and RELICANTH not in ids:
            return 15000, "Explorer: take Relicanth"
        sup_count = sum(1 for c in (my_state(obs).hand or []) if c and c.id in (EXPLORER, LILLIE))
        if cid in (EXPLORER, LILLIE) and sup_count == 0:
            return 12000, "Explorer: take supporter"
        return 0, "Explorer: let discard"

    dura_ex_count = count_in_play(obs, DURALUDON) + count_in_play(obs, ARCHALUDON_EX)
    if cid == DURALUDON and DURALUDON not in ids and dura_ex_count <= 1:
        return 22000, "take Duraludon: backup"
    if cid == ARCHALUDON_EX and need_archaludon(obs):
        return 20000, "take Archaludon ex"
    if cid == DURALUDON and need_duraludon(obs):
        return 18000, "take Duraludon"
    if cid == CINDERACE:
        return -2000, "skip Cinderace"
    if cid == RELICANTH and not has_in_play(obs, RELICANTH):
        return 9000, "take Relicanth"
    if cid == METAL_ENERGY:
        return 8000, "take Metal Energy"
    if cid == EXPLORER and not obs.current.supporterPlayed:
        return 7500, "take Explorer"
    if cid == LILLIE and not obs.current.supporterPlayed:
        return 6500, "take Lillie"
    if cid == HERO_CAPE:
        has_target = any(p.id == ARCHALUDON_EX and not has_tool(p) for p in all_my_pokemon(obs))
        return (6000, "take Hero's Cape") if has_target else (1000, "generic take")
    if cid == FULL_METAL_LAB:
        return 5000, "take Full Metal Lab"
    if cid == BOSS:
        return 2500, "take Boss"
    return 1000, "generic take"


def score_discard(obs, opt):
    card = option_card(obs, opt)
    cid = card.id if card else opt.cardId
    ids = hand_ids(obs)
    mt = metal_in_discard(obs)
    effect = getattr(obs.select, "effect", None)
    effect_id = effect.id if effect else None

    if effect_id == ULTRA_BALL:
        mh = ids.count(METAL_ENERGY)
        if cid == METAL_ENERGY:
            if mt < 2 and mh >= 1:
                if getattr(opt, 'index', None) == _first_option_index(obs, METAL_ENERGY):
                    return 20000, "UB: 1st Metal"
                return 8000, "UB: 2nd Metal"
            return 8000, "UB: Metal"
        if cid == CINDERACE:
            return (18000, "UB: Cinderace") if (mt >= 2 or mh == 0) else (14000, "UB: Cinderace")
        draw_count = ids.count(LILLIE) + ids.count(EXPLORER)
        if cid in (LILLIE, EXPLORER) and draw_count >= 2:
            return (12000 if cid == LILLIE else 11000), "UB: surplus supporter"
        if cid == ULTRA_BALL and ids.count(ULTRA_BALL) > 1:
            return 10000, "UB: duplicate"
        if cid in (LILLIE, EXPLORER) and draw_count <= 1:
            return -3000, "UB: keep last supporter"

    if cid == METAL_ENERGY:
        if mt < 2:
            return 15000, "discard Metal"
        return (12000, "discard extra Metal") if ids.count(METAL_ENERGY) > 1 else (-1000, "keep last Metal")
    if cid == CINDERACE:
        return 10000, "discard Cinderace"
    if cid in {BOSS, FULL_METAL_LAB, POKEGEAR}:
        return 8500, "discard utility"
    if cid in {LILLIE, EXPLORER} and ids.count(cid) > 1:
        return 8000, "discard duplicate supporter"
    if cid == RELICANTH and (has_in_play(obs, RELICANTH) or ids.count(RELICANTH) > 1):
        return 6500, "discard extra Relicanth"
    if cid == ARCHALUDON_EX:
        return -5000, "keep Archaludon ex"
    if cid == DURALUDON:
        return -4000, "keep Duraludon"
    return 1000, "generic discard"


def score_target(obs, opt):
    card = option_card(obs, opt)
    cid = card.id if card else opt.cardId
    ctx = obs.select.context

    if ctx == SelectContext.ATTACH_TO:
        return (5000, "Metal") if cid == METAL_ENERGY else (1000, "attach")

    if ctx == SelectContext.ATTACH_FROM:
        if card and energy_count(card) >= 3:
            return -5000, "skip: 3+ energy"
        if card and cid == CINDERACE and energy_count(card) >= 1:
            return -3000, "skip: Cinderace ready"
        return attach_target_score(obs, card, opt.area), "effect attach"

    if ctx in {SelectContext.TO_FIELD, SelectContext.TO_BENCH}:
        if cid == ARCHALUDON_EX:
            return 18000, "target Archaludon ex"
        if cid == DURALUDON:
            return 16000, "target Duraludon"
        if cid == CINDERACE:
            return 3000, "avoid Cinderace"

    if ctx == SelectContext.HEAL:
        return (20000 + damage_on(card), "heal Archaludon ex") if cid == ARCHALUDON_EX else (damage_on(card), "heal")

    if ctx in {SelectContext.SWITCH, SelectContext.TO_ACTIVE}:
        yi = obs.current.yourIndex
        pi = getattr(opt, 'playerIndex', yi)
        if pi != yi and card:
            # vs Hop: prioritize Snorlax (remove Extra Helpings)
            if detect_matchup(obs) == "hop" and cid == HOP_SNORLAX and card:
                active = active_pokemon(obs)
                e = energy_count(card)
                tools = len(getattr(card, 'tools', None) or [])
                if active and active.id == CINDERACE:
                    # Cinderace: pull the least mobile Snorlax (low energy, no tools, high HP)
                    return 30000 - e * 100 - tools * 50 + card.hp, "Boss: Snorlax (immobile target)"
                else:
                    # Archaludon: pull the most threatening Snorlax (high energy, tools, high HP)
                    return 30000 + e * 100 + tools * 50 + card.hp, "Boss: Snorlax (biggest threat)"
            pv = prize_value(card)
            te = energy_count(card)
            killable = any(effective_damage(a["damage"], card) >= card.hp
                           for a in planned_archaludon_attacks(obs))
            if killable:
                return 20000 + pv * 3000 + te * 100, "Boss: KO"
            return 5000 + pv * 1000 + te * 200, "Boss: drag"
        if cid == CINDERACE:
            return 16000, "promote Cinderace (retreat 0)"
        if cid == ARCHALUDON_EX:
            # v6: an already-evolved, attack-ready Archaludon ex was flat 15000 —
            # below Cinderace's 0-retreat pivot (16000) and tied with a merely
            # ready Duraludon's plain-Duraludon floor. Unlike Duraludon, there is
            # no pre-evolution exposure risk here (it's already the evolved
            # form), so the readiness boost applies regardless of forced vs
            # voluntary. Kept 500 above Duraludon's ready tier (32000) so a
            # 220-damage Metal Defender attacker wins ties against an
            # 80-damage Raging Hammer Duraludon when both are switch-ready.
            ready, _ = attack_energy_route(obs, card)
            if energy_count(card) >= 3 or ready:
                return 32500, "switch: attack-ready Archaludon ex"
            return 15000, "promote Archaludon ex"
        if cid == DURALUDON:
            # C0-2: distinguish a KO-forced promotion from our own voluntary
            # retreat/switch. The old rule penalized Duraludon in both cases,
            # which sometimes sent an attack-ready Duraludon past the Active
            # slot and stranded Relicanth in front.
            forced_promotion = not any(p for p in (my_state(obs).active or []) if p)
            if not forced_promotion:
                # v4: never strand an immediately usable Duraludon behind a wall.
                # attack_energy_route can be conservative when a selection happens
                # mid-resolution, so use the visible attached-energy count as an
                # additional hard signal. Three energies means Raging Hammer is live.
                ready, _ = attack_energy_route(obs, card)
                visibly_ready = energy_count(card) >= 3
                if visibly_ready or ready:
                    return 32000, "voluntary switch: guaranteed attack-ready Duraludon"
                # C1: even without attack energy this turn, a Duraludon that can
                # evolve into Archaludon ex right now (Archaludon ex in hand,
                # not appearThisTurn) is worth promoting over a plain bench mon —
                # evolving triggers Assemble Alloy (fetches up to 2 Metal Energy
                # from discard, which is what usually makes it attack-ready next
                # turn) and jumps HP130 -> HP300, so it stops being an easy KO.
                # This must stay below the attack-ready band above (completing
                # AND attacking the same turn is strictly better) and above the
                # plain-Duraludon fallback below.
                if can_evolve_to_archaludon_now(card, obs):
                    return 20000, "voluntary switch: Duraludon completes to Archaludon ex this turn (Assemble Alloy)"
                return 9000, "voluntary switch: Duraludon"

            # Only the forced-promotion branch applies the exposed-before-evolve
            # safety rule. Preserve Duraludon when a safer bench target exists.
            alternatives = []
            for candidate in obs.select.option:
                candidate_card = option_card(obs, candidate)
                if candidate_card and candidate_card.serial != card.serial:
                    alternatives.append(candidate_card)
            if alternatives and opp_max_damage(obs) >= card.hp:
                return 500, "forced promotion: exposed Duraludon (prefer safer bench)"
            return 8000, "forced promotion: Duraludon"
        return 1000, "generic promote"

    if ctx == SelectContext.DAMAGE:
        hp = getattr(card, "hp", 999) if card else 999
        return 10000 - hp, "damage: lowest HP"

    return 1000, "generic target"


# ── Choose & Agent ──

def choose_options(obs):
    scored = []
    for i, opt in enumerate(obs.select.option):
        try:
            score, reason = score_option(obs, opt)
        except Exception as e:
            score, reason = -999999, f"error {type(e).__name__}: {e}"
            print(f"[agent] score_option failed on opt#{i} "
                  f"(type={getattr(opt, 'type', '?')}): {e}", file=sys.stderr)
        scored.append((score, i, reason))

    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)

    selected = []
    for score, i, reason in scored:
        if len(selected) >= obs.select.maxCount:
            break
        if score < 0 and len(selected) >= obs.select.minCount:
            continue
        selected.append(i)

    if len(selected) < obs.select.minCount:
        selected = [i for _, i, _ in scored[:obs.select.minCount]]

    return selected


def agent(obs_dict):
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        global _opp_last_attack_id, _cur_turn_logs, _opp_mill_seen
        _opp_last_attack_id = None
        _cur_turn_logs.clear()
        _opp_mill_seen = False
        return read_deck_csv()
    _update_opp_attack_tracking(obs)
    if not obs.select.option:
        return []
    try:
        return choose_options(obs)
    except Exception as e:
        print(f"[agent] choose_options crashed, falling back to random: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return random.sample(list(range(len(obs.select.option))), obs.select.maxCount)
