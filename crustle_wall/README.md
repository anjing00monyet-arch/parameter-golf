# Crustle Wall — threat tracking & mill-race control

Decision core for the Crustle Wall pilot (Great Tusk mill + Crustle ex-immunity
wall + Xerosic hand-lock, aiming for a deck-out special win). Written as pure
functions over the replay observation schema so it is independent of the action
encoding layer.

## Why

Loss analysis on batch `replays_15` (Crustle Wall: 7W / 12L) found the real
bottlenecks were **not** where v2 was aimed:

| loss cause | count | fix |
|---|---|---|
| self deck-out (we milled ourselves first, 1–4 card margin) | 4 / 12 | `MillRaceController` (A) |
| Great Tusk (140 hp) OHKO'd, board collapse (Grimmsnarl/Dragapult/Alakazam/Lucario) | most | `ThreatTracker` + `decide_tusk_action` (B, C) |
| double Mega Lucario ex false-safe (cooldown was keyed by attackId, not the individual) | 2 | per-serial cooldown in `ThreatTracker` (B) |

## Pieces

- **A `MillRaceController`** — each turn computes deck-out turns-left for both
  sides and a race margin. In the race phase it refuses non-essential optional
  draws/searches (Poké Pad, Explorer's Guidance, Pokégear) unless they keep the
  Tusk mill engine running. Directly targets the self-deck-out losses.
- **B `ThreatTracker`** — tracks every opponent Pokémon **by `serial`**.
  Cooldown (e.g. Mega Lucario ex "Mega Brave", attack 983) is per-individual,
  and `max_incoming()` includes energized bench candidates. Swapping in a fresh
  Lucario no longer reads as safe.
- **C `decide_tusk_action`** — if `max_incoming >= tusk_hp`, retreat the Tusk to
  Crustle after attacking (or wall instead of attacking when no retreat), unless
  the mill race says skipping deck-outs us.

## Integrating

```python
from crustle_wall import control as cw

tracker = cw.ThreatTracker(opp_player_index=opp_idx)
mill    = cw.MillRaceController(safe_margin=3.0, setup_deck_floor=20)

# each time you receive an observation `state` with its `logs`:
tracker.observe_logs(logs)
if opponent_turn_just_ended(logs):
    tracker.on_opponent_turn_end()

race = mill.evaluate(state, own_idx, opp_idx,
                     planned_optional_draw=n,
                     tusk_mill_per_turn=expected_mill,
                     wall_established=crustle_is_out)

if considering_optional_draw:
    ok = mill.allow_optional_draw(race, needed_to_keep_attacking=would_stall_tusk)

decision = cw.decide_tusk_action(state, own_idx, opp_idx, tracker, race,
                                 tusk_hp=active_tusk_hp,
                                 can_retreat_to_crustle=have_switch_or_free_retreat,
                                 skipping_forfeits_race=race.margin < 0)
```

The pilot still owns action encoding; this module only decides *what* to do.

## Tables

`CARD_ATTACKS` / `EX_CARD_IDS` are learned from `replays_15` (max observed
damage per attack id). Unscouted attackers fall back to `UNKNOWN_EX_DAMAGE`
(200, assume OHKO-capable) or `UNKNOWN_NONEX_DAMAGE` (60). Re-mine and extend
these from new batches as the meta shifts.

## Tests

```
python3 -m crustle_wall.test_control
```

Cases reproduce the two real loss patterns (double-Lucario false-safe, thin
mill race) plus the retreat/wall/swing branches.

## Backtest over replays_15

```
python3 -m crustle_wall.backtest '<path>/replays_15/*.json'
```

Honest scope: this does not re-simulate games (no pilot in this repo), so it
reports *decision-point coverage*, not a win count.

- **C (Tusk exposure):** 37 Great Tusks were KO'd in the active spot across the
  19 games; **27** had a Crustle already benched, i.e. a retreat/wall was
  available and `decide_tusk_action` would have fired. (It fires in wins too —
  preserving the mill engine and denying prizes is good regardless — so 27 is
  the touch ceiling, not a claim that all should be prevented; the mill-race
  override intentionally still swings when skipping would deck us out.)
- **A (mill race):** 4 of the 12 losses were self-deck-out, lost by **1, 2, 4,
  and 8** cards. Three of four are within a couple of gated optional draws.
- **Coverage:** **9 of 12 losses** are touched by A and/or B+C. The remaining 3
  (Kazuhiro Sato, kokenbo, Jai Japan) are short games where we lost with all 6
  prizes still up — the wall never came online. That is a **setup-speed**
  problem, out of scope for these guards and the next thing to investigate.

Validate the next live batch on *loss composition* (prize-race / self-deck-out /
never-set-up), not win rate: at n≈19 the win-rate CI is ±22%, but the loss mix
shifts measurably.
