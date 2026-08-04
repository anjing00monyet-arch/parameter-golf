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

Across 10 fixed-seed full seasons vs the built-in `starter` baseline (a
single-farmer carrot-only loop), this agent wins **10/10**, landing final
money in the $41k-$70k range (starter stays flat around $3.5k) — roughly
half of what real top-20 public leaderboard submissions reach ($93k-$123k,
see the leaderboard-calibration section below), but a large jump from the
~$3k-$6k this agent scored before that calibration pass.

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

## Leaderboard calibration (2nd pass)

The 2/5 record above got a second pass after analyzing replay data (action
logs + per-day money) for the top 20 public leaderboard submissions
(avg final money $93k-$123k, vs this agent's ~$3k-$6k at the time). The
replays converge on an almost identical strategy across nearly every one of
the twenty, which is a strong signal it's close to a structural optimum
rather than 20 independent local optima:

- **Only wheat/melon/strawberry are ever planted.** Carrot and tomato appear
  only in the two *lowest*-scoring of the twenty, in small quantities, and
  correlate with materially worse outcomes.
- **Only cow+sheep are ever bought, in a consistent ~4:3 ratio** regardless
  of milk/wool spot price at purchase time. Goose appears only in the same
  two worst-scoring submissions.
- **Land is bought on exactly day 7 and day 10, and never a third time** —
  nobody buys the $4000 SE quadrant; the 3-quadrant (75-tile) footprint is
  the real optimum, not 4.
- **Hiring follows a clean day-indexed curve**: ~4-7 hands/day while on one
  quadrant, jumping to 8/10/11/12 exactly as land is bought on day 7-10,
  holding at 12/day through day 26, then tapering to 11/10/9 as the season
  winds down. Hiring happens only in the first few hours of each day.
- **`CARE` is used on essentially every animal every day** (banking a yield
  bonus is free but for one turn's opportunity cost), and collected
  fertilizer is only partially self-used — the rest gets sold rather than
  hoarded.

`main.py` was rewritten to match this: `PLANTABLE_CROPS`/`BASE_MIXES` now
only cover wheat/melon/strawberry (strawberry-dominant, since it's an
*ongoing* crop whose production is naturally staggered across tiles by each
one's own planting day, unlike melon's one-time harvest which dumps many
tiles' yield onto the market at once and craters its own price under
melon's punishing glut-price curve); `_herd_target` is a fixed 4:3 cow:sheep
split with goose excluded; `_land_order` is capped at `MAX_LAND_PURCHASES =
2` on the day-7/day-10 schedule; `_hire_orders` reads `HIRE_TARGET_SCHEDULE`
instead of a pending-task heuristic.

Applying the schedule at face value initially caused a *new* failure mode on
about half of seeds: the leaderboard-derived spend (2nd land purchase + hire
ramp to 12/day + restocking seeds for a freshly-unlocked quadrant) all lands
in the same few days, and this agent's task-completion throughput isn't as
efficient as the real submissions it was calibrated from, so copying their
spend *amounts* without their execution efficiency emptied the bank exactly
at day 7-10 and triggered the same cash-crunch death spiral fixed earlier
for day 0. The existing `spend_fraction` cushion was ramping to 100% by day
~10 -- right into that peak -- so it was slowed to ramp to 100% by day ~21
instead (`0.35 + 0.03 * day`). That alone took the result from 2/5 to
**10/10** across seeds 1-10 (see git history for the intermediate 5/5-vs-2/5
data points).

## Known headroom

- Still roughly half of real top-20 final money ($41k-$70k here vs
  $93k-$123k there) — worker routing/dispatch efficiency (see below) is the
  likely gap, not portfolio choice, which is now leaderboard-calibrated.
- Worker/task assignment is greedy per round (global nearest-cost match
  each turn), not globally optimal across the whole day — this is probably
  where the remaining throughput gap to the real top submissions lives.
- `FERTILIZE` is gated on a flat base-price threshold rather than weighing
  the crop's remaining cycle length against the 3-day fertilizer window.
- Herd composition and the hire/land schedules are fixed day-indexed curves,
  not reactive to how a specific game is actually going (a bad early game
  can't slow down the spend plan, only the affordability floors can).
