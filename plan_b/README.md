# Plan B (candB: Archaludon ex + Cinderace) — exposure & mill-race guards

Decision-support module for the Plan B pilot, built the same way as
`crustle_wall/`: pure functions over the replay observation schema, backed by
counterfactual replay evidence rather than assumption.

## Why

`replays_16` (53 resolved Plan B games, 30W/23L) surfaced two issues, ranked by
frequency × severity:

| issue | scope | evidence |
|---|---|---|
| Archaludon mirror is the worst *and* most common matchup | 12/53 games, 33% win rate | mirror losses correlate with the opponent reaching a live Archaludon ex attack before us in 7/8 losses (1 tie); we never lost a mirror where we got there first |
| self deck-out | 2/23 losses | zero prizes lost to opponent in both; one opponent ran the Great Tusk mill archetype (our own Crustle Wall's mirror) and decked us in 89 steps |

A first hypothesis — that our Pokémon-search items were whiffing — was tested
and **refuted**: Ultra Ball hit Duraludon/Archaludon ex 60/61 times (98%)
across all 53 games. The actual driver, confirmed on the mirror-loss games, is
pre-evolution Duraludon (130 hp) sitting active and getting KO'd before Archaludon
ex is available to evolve into: 8 such KOs on our side across the 8 mirror
losses vs. 3 on the opponent's side in those same games (vs. 3 vs 2 in the 4
wins — the imbalance is real but not the sole explanation for every loss).

## Guards

- **`decide_pre_evolution_exposure`** — if Archaludon ex is in hand and Duraludon
  is evolution-eligible, always evolve (that removes the exposure outright).
  Otherwise, if the opponent can KO the active Duraludon next turn
  (`ThreatTracker.max_incoming`, reused from `crustle_wall.control` — it's
  deck-agnostic), retreat to a bench Pokemon that *isn't itself* an unevolved
  Duraludon. Retreating Duraludon-for-Duraludon is not offered as an option —
  it doesn't reduce exposure.
- **`detect_mill_archetype`** / **`mill_race_settings`** — flags an opponent as
  the mill archetype as soon as Great Tusk or Xerosic's Machinations is seen
  among their revealed cards, and tightens `crustle_wall.control.MillRaceController`'s
  gating (higher `safe_margin`, earlier exit from setup phase) once confirmed.
  Plan B has no anti-mill tech and runs heavy deck-thinning (Ultra Ball /
  Pokégear 3.0 / Poké Pad / Explorer's Guidance), so it's structurally exposed
  in a long game regardless of opponent archetype — the archetype flag just
  lets the pilot tighten earlier instead of reacting once the deck is already low.

## Honest scope (backtest on replays_16 mirror games)

```
python3 -m plan_b.backtest '<path>/replays_16/*.json'
```

11 pre-evolution Duraludon KOs occurred across the 12 mirror games. Of those,
**6 had a safe retreat available** (a Cinderace or Relicanth already benched) —
that's the guard's ceiling. The other 5 had no bench option but another
unevolved Duraludon, which retreating into doesn't fix; those need either more
Pokemon count/diversity in the 60 or acceptance as unavoidable variance.

Mill-archetype detection was checked against the actual Vishesh Banna loss: it
flags the matchup 26 events into a 188-event game (~14% in), well before the
deck count crisis at the end.

## Integrating

```python
from crustle_wall.control import ThreatTracker
from plan_b import guard as pb

tracker = ThreatTracker(opp_player_index=opp_idx)
is_mill = pb.detect_mill_archetype(opponent_revealed_card_ids)
mill_settings = pb.mill_race_settings(is_mill)  # feed into MillRaceController(**mill_settings)

if active_is_unevolved_duraludon:
    retreat_target = pb.find_retreat_target(state, own_idx, retreat_energy_available)
    decision = pb.decide_pre_evolution_exposure(
        state, own_idx, opp_idx, tracker, active_mon,
        evolution_card_in_hand=archaludon_ex_in_hand,
        retreat_target_serial=retreat_target)
```

## Tests

```
python3 -m plan_b.test_guard
```

9 cases, anchored on the real episode-86603157 state (Duraludon serial 15, no
safe retreat available) plus the retreat/evolve/safe branches and mill
detection.
