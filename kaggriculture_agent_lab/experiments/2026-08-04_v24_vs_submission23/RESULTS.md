# Real-engine A/B: agent/main.py vs. two baselines

Run against the actual `kaggriculture` environment (kaggle-environments
1.32.2, installed locally for this run), not the synthetic-obs fallback.
Raw `tools/run_ab.py` output is in this folder for reproducibility.

## 1. agent/main.py (V24 Clone Cash Shield) vs. baselines/submission_23_heuristic.py

The user-supplied `submission_23.tar.gz` — a live-decision heuristic
engine (job-priority queue + greedy worker assignment + a tuned "PK knob
layer": `reserve_mult=0.9482`, `mid_herd≈11`, `target_herd≈16`,
`melon_base≈10`, `melon_max≈12`, `max_hands≈13`, `glide_left≈14`,
`forecast_guard=0.8511`).

```
python tools/run_ab.py --candidate agent/main.py \
  --baseline baselines/submission_23_heuristic.py --games 10 --base-seed 8000
```

| metric | value |
|---|---|
| matches played | 20 (10 seeds x seat swap) |
| wins / losses / ties | **20 / 0 / 0** |
| mean candidate money | 130,979 |
| minimum candidate money | 99,476 |
| mean margin | **+18,185** |
| minimum margin | +9,988 (never lost a single match) |

## 2. agent/main.py vs. baselines/frontier_router_original.py (unpatched anchor tape)

Isolates the value of the four wrapper patches (`adaptive_triad`,
`treasury` flush, `terminal_work`, `clone_front_run`) on their own, since
both files replay the same base `TRACE_ACTIONS`.

```
python tools/run_ab.py --candidate agent/main.py \
  --baseline baselines/frontier_router_original.py --games 10 --base-seed 9000
```

| metric | value |
|---|---|
| matches played | 20 |
| wins / losses / ties | 16 / 4 / 0 |
| mean candidate money | 121,946 |
| minimum candidate money | 88,660 |
| mean margin | +1,524 |
| minimum margin | **-8,529** |

The patches are net positive (80% win rate) but not free: 4 of 20 matches
lost, with a worse tail (-8,529 / -7,946) than the typical win size
(+1,500 to +3,500). In every seed where results differ by seat, one seat
wins and the mirrored seat loses (seeds 9001, 9004, 9005, 9009) — the base
tape is turn-priority sensitive on tile conflicts, and the patches inherit
that sensitivity rather than fixing it.

## Takeaway

The dominant profit lever is **which strategy family you submit at all** —
tape-replay-of-a-proven-episode beats the general reactive heuristic by
~18k/game with zero losses across 20 real games. The wrapper patches on
top of the tape are a secondary, smaller lever (+1.5k/game average, but a
real downside tail) — see `RECOMMENDATIONS.md` in this folder for what to
do about the tail before trusting the patches unconditionally.
