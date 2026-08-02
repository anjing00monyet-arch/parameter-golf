# Market Shadow Diversification — Kaggriculture agent

`main.py` is a rule-based agent for the [Kaggriculture](https://www.kaggle.com/competitions/kaggriculture)
Kaggle simulation competition. Strategy: keep a fixed base crop/animal
portfolio spread across the farm, deviating from it per-tile only when the
market/opponent picture makes the deviation clearly worth it (the opponent
is crowding a crop, the sale price has cratered, or a self-diversification
cap is hit). Task priorities are safety-first: prevent weeds/animal escapes,
then harvest, then routine care, then expansion/planting. Every farmer/hand
recomputes its best task fresh each turn and takes one step toward it (move
if not there yet, the interaction itself once in place) — Kaggriculture
gives each unit exactly one op per turn, there's no queued multi-step action.

This was built directly against the installed `kaggle_environments` package's
`kaggriculture.py` (crop/animal tables, market price formula, shop demand,
turn-processing order) rather than from an external rules writeup, and has
been run against the real engine (not a mock) throughout development.

## Files

- `main.py` — the agent (`agent(obs) -> action`). Self-contained, submission-ready
  as-is (`kaggle competitions submit kaggriculture -f main.py -m "..."`).

## Verified against the real engine

```bash
pip install kaggle-environments   # already bundles the kaggriculture env
python3 -c "
from kaggle_environments import make
import main

env = make('kaggriculture', configuration={'episodeSteps': 720})
env.run([main.agent, 'starter'])
print([(i, s.reward) for i, s in enumerate(env.steps[-1])])
"
```

No exceptions across full 30-day (720-turn) seasons; `agent()` also has a
top-level try/except that falls back to all-`PASS` so a bug never forfeits
the match outright.

Across 5 fixed-seed full seasons vs the built-in `starter` baseline (a
single-farmer carrot-only loop), this agent wins 2/5 and is competitive
(within ~700 coins) in the other 3 — a reasonable rule-based baseline, not a
tuned/dominant one. The known headroom below is where the next tuning pass
should go.

## Bugs found and fixed during development (not just "reproduced")

Three were serious enough to fix rather than carry forward, since they broke
the agent's own economy against the real engine (verified by running it):

1. **Shared market budget.** Each buy category (hire/land/animal/seed/product)
   originally priced its purchases against the *full* bank balance
   independently, instead of a running total. On turn one this queued
   6 hires + 3 animals + a 22-tile seed order simultaneously, and the engine's
   per-order truncation (which prevents going negative) silently spent the
   entire $3000 bankroll in one turn. Fixed by threading one `money` value
   through the whole `_market_orders` pipeline.
2. **Self-crowding / monoculture.** The crop-scoring formula only discounted
   for the *rival's* visible tile count, never our own. Since melon's raw
   margin is ~3-5x every other crop at unpressured prices, this meant nearly
   every empty tile independently "adaptively" switched to melon — the exact
   self-supply-crash failure mode the diversification logic was supposed to
   prevent. A soft same-crop penalty wasn't enough to counteract that gap;
   fixed with a hard per-crop share cap (`CROP_SHARE_CAP`, 35% of owned
   tiles) enforced during the same planning pass.
3. **Runaway animal-structure building.** The animal-slot planner picked its
   target tiles from currently-empty tiles every turn without subtracting
   structures already built in previous turns. Since a freshly-built
   COOP/PASTURE is no longer "empty," the next turn's fresh plan just picked
   *another* batch of empty tiles to build on — consuming the entire
   quadrant (22 of 25 tiles) as unoccupied structures within a few turns and
   starving crop planting completely. Fixed by counting existing structures
   against the target headcount before generating new build tasks.

A fourth issue was tuning rather than correctness: the hire-cost floor
(`HIRE_MONEY_FLOOR`) was set high enough that a lean bank balance blocked
hiring even though hire cost is fib-scaled and the first several hires on
any day are nearly free (1, 1, 2, 3, 5, 8, ...) — exactly when the extra
labor is needed most to get cash flowing again. Lowered from 150 to 20, and
added a day-ramped spend fraction (`spend_fraction`, 45%→100% by day ~10) so
the agent doesn't commit its entire day-0 bankroll into seeds/animals/hands
before any harvest has come in.

## Known headroom (not yet tuned)

- Herd composition (`_herd_target`) is decided once per episode and frozen —
  it does not react to shops unlocking later.
- Worker/task assignment is greedy per round (global nearest-cost match
  each turn), not globally optimal across the whole day.
- `FERTILIZE` is gated on a flat base-price threshold rather than weighing
  the crop's remaining cycle length against the 3-day fertilizer window.
- Land-purchase and hiring schedules are fixed day thresholds, not reactive
  to how the season is actually going.
- The 2/5 record vs `starter` suggests the spend-pacing and crop-mix weights
  could still use another tuning pass — `CROP_SHARE_CAP`, `spend_fraction`,
  and `BASE_MIXES` are the first places to experiment.
