# Profit-maximization notes

Grounded in `RESULTS.md`'s real-engine numbers plus the shared
`MARKET`/`CROPS` constants both agent families agree on (so these figures
aren't guesses -- they're the actual price-impact formula each agent's own
`_price_at` implements).

## 1. Strategy family matters far more than any parameter tweak

agent/main.py beat the heuristic engine 20/20 with a +18,185 average
margin, and beat its own unpatched base tape 16/20 with only a +1,524
average margin. The gap between "tape-replay family" and "reactive
heuristic family" (~18k) dwarfs the gap any single knob inside either
family is likely to close. If the goal is maximum profit, stay on the
tape-replay family; tuning the heuristic engine's `PK` knobs further is a
much smaller lever than switching families at all.

## 2. Melon is the correct centerpiece, and both agents already cap it correctly

Per-tile-day profit at list price, from `CROPS`/`MARKET`:

| crop | seed cost | cycle days | yield/cycle | profit/cycle | profit/tile/day |
|---|---:|---:|---:|---:|---:|
| MELON | 80 | 12 | 6 | 1,420 | **118.3** |
| CARROT | 20 | 3 | 4 | 120 | 40.0 |
| STRAWBERRY | 100 | 10 | 4 | 380 | 38.0 |
| WHEAT | 10 | 4 | 6 | 140 | 35.0 |
| TOMATO | 50 | 8 | 4 | 190 | 23.75 |

Melon's per-tile-day profit is ~3x wheat/carrot/strawberry's. But melon
also has the steepest self-cannibalizing price curve in `MARKET`
(`above_func="sq"`, `above_target=3.60` -- the harshest of any crop), so
flooding melon tiles crashes melon's own price fastest. Both
`baselines/submission_23_heuristic.py`'s `MELON_TILES_{MIN,BASE,MAX} =
8/10/12` and the source tape's NW-quadrant melon allocation already sit at
this saturation point -- that part is not a place to push further; going
past ~12 melon tiles would likely be net-negative on the marginal tile.

## 3. Where the wrapper patches actually leak money

The -8,529 and -7,946 losses in `RESULTS.md` §2 both occur in seat-swapped
pairs where the *other* seat wins by a similar amount -- a turn-priority
effect on tile conflicts, not a strategy error. Two candidate fixes, both
implementable via `tools/new_experiment.py` without touching the base
tape:

- Raise the clone-confidence activation threshold in `agent/main.py`'s
  `_clone_active()` (currently `_CLONE_CONFIDENCE >= 2`) so
  `clone_front_run` only fires on stronger evidence, reducing how often it
  reorders sells into a worse-priority tick.
- Make `_terminal_work`'s idle-PASS-to-DROP/HARVEST conversion conditional
  on the farm not already being ahead, so it doesn't force extra tile
  visits (and conflicts) when the tape's own idle PASS was already fine.

Before trusting either change, re-run `run_ab.py` at higher `--games`
(50+) specifically re-using seeds 9001/9004/9005/9009 as a regression
check, since 20 matches is enough to see the tail but not enough to prove
a fix closes it.

## 4. A latent bug in the heuristic engine lineage (submission_23), for the record

`baselines/submission_23_heuristic.py` tunes `FEED_STOCK_DAYS` through its
`PK` knob layer (`PK["feed_stock_days"] = 2.1026` -> `FEED_STOCK_DAYS =
2`), then immediately overwrites it back to a hardcoded `FEED_STOCK_DAYS =
3` a few lines later (`# overridden below`). The tuned value never takes
effect. Not the reason it lost 20/20 above -- that gap is far too large
for one knob -- but worth fixing if that lineage is revisited, since it
means whatever process tuned `PK` was optimizing against a knob that was
silently inert.
