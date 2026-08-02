# Market Shadow Diversification — farming AI agent

`agent.py` reconstructs, as runnable Python, the deterministic market-reactive
rule-based farm agent described alongside this module: a fixed base crop/animal
portfolio that is only abandoned when the market or opponent situation makes
the deviation clearly worth it (crowding avoidance via rival tile counts,
forward demand pull from unlocked town shops), paired with safety-first task
prioritization (feed > emergency watering > harvest > watering > weeding >
planting) and BFS-based worker routing.

## Files

- `agent.py` — the agent (`agent(obs) -> action`), fully self-contained.
- `demo.py` — a synthetic smoke test showing the expected `obs`/action shapes
  and confirming the agent runs end-to-end without exceptions.

## Schema note

No concrete `obs`/action wire-format shipped with the original design — only
prose plus isolated, truncated code fragments (the source snippet the analysis
was based on ends mid-`return {`). `agent.py`'s module docstring spells out the
`obs`/action schema this implementation assumes; if your actual game
environment differs, only the `_read_*`/task-emission glue needs adjusting —
the strategic logic (crop scoring, adaptive substitution, herd sizing, task
priorities, BFS movement, greedy assignment, market/land/hiring rules)
sits above that boundary and does not need to change.

## Known, intentionally-reproduced weaknesses

Carried over from the original design on purpose (see the accompanying
analysis for the full discussion):

- Herd composition (`_herd_target`) is decided once per episode and frozen —
  it does not react to shops unlocking later.
- Worker/task assignment is greedy per round, not globally optimal.
- Sell quantities use the current spot price and don't model per-unit price
  impact from a large sale.
- Hiring always targets 10 hands regardless of actual workload.
- Fertilizer is collected but never applied back to crops.

## Deviations from the original description

Two items were fixed because they are outright bugs rather than design
choices, and reproducing them verbatim would make the agent non-functional or
self-defeating:

1. The original snippet is cut off mid-`return {`, which is a syntax error.
   Completed here.
2. `TOMATO` was listed as an adaptive-substitution candidate but missing from
   the seed-purchase shopping list, so the agent could select it and then
   never actually be able to plant it. `SEED_SHOPPING_LIST` now includes it.

Everything else — including the late-game animal-purchase weakness noted in
the analysis — is reproduced as designed, with `ANIMAL_LAST_BUY_DAY` added as
an opt-in constant (already wired in) since leaving it out would have made
end-game coin spending purely wasteful rather than merely suboptimal.
