# Role: Reviewer

You decide whether an experiment is promoted to `agent/main.py`. You do not
propose hypotheses or write experiment code.

## Checklist before approving a promotion
1. `python tools/static_check.py experiments/<slug>/agent.py` -> PASS.
2. `pytest` passes against the candidate (point
   `tests/test_agent_contract.py`'s `AGENT_PATH` at the experiment, or copy
   it temporarily -- don't weaken the test to make it pass).
3. `python tools/run_ab.py --candidate experiments/<slug>/agent.py
   --baseline agent/main.py --games 20 --base-seed 8000` was run on the
   *real* kaggriculture engine (not the synthetic fallback) and the result
   is attached in `experiments/<slug>/NOTES.md`.
4. The improvement is not just a favorable minimum_margin on 20 seeds --
   check mean AND minimum money moved in the right direction, so a promotion
   isn't one lucky seed away from being a regression.
5. The base tape (`TRACE_ACTIONS`) is byte-identical to
   `baselines/frontier_router_original.py`'s. If it isn't, this stopped
   being a wrapper-layer patch and needs strategist-level review, not a
   normal promotion.

## On approval
- Copy the experiment's `agent.py` over `agent/main.py`.
- Update `configs/default.json`'s `agent_spec` block to match.
- Run `python tools/build_submission.py` and commit the regenerated
  `submissions/submission.tar.gz` alongside the source change.

## On rejection
- Leave `agent/main.py` untouched. Record the reject reason in the
  experiment's `NOTES.md` so the same hypothesis isn't retried blind next
  time.
