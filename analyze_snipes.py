#!/usr/bin/env python3
"""Split self-snipe games from clean games and report it with the uncertainty attached.

Why this exists
---------------
A hand-rolled version of this split produced three numbers that look like
findings but carry no information:

1. "promotion_violation co-occurs 5/5 and 10/10".
   In harness/metrics.py the snipe flag is a *subset* of the violation flag
   (`c0_2_violation = voluntary_avoided_ready or forced_exposed_unready`,
   `suspected_self_inflicted_snipe = forced_exposed_unready`), so any game with
   a snipe necessarily has a violation. 100% is forced by the definition.

2. "archaludon_by_own_turn3 = 0.00% in the snipe group".
   With 5 and 10 games at clean-group rates of 6.9% / 5.7%, the expected count
   is 0.35 and 0.57. Seeing zero happens 70% / 56% of the time under pure
   independence, so it is the most likely observation, not a contrast.

3. "5 -> 10 snipe games".
   Fisher one-sided on 10/150 vs 5/150 gives p = 0.145 with heavily
   overlapping Wilson intervals.

It also splits on BOTH snipe metrics, because they are not the same thing and
only one of them gates adoption:
  * c0_2_self_inflicted_snipe_count -- legacy, HP-based, Duraludon ONLY.
  * c0_2_true_self_snipe_count      -- card-class based, Duraludon AND
    Archaludon ex. This is what mechanism_gates() actually tests.
Analysing only the legacy field is blind to every Archaludon ex case.
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

SNIPE_METRICS = {
    "legacy": "c0_2_self_inflicted_snipe_count",
    "true": "c0_2_true_self_snipe_count",
}
CONFOUNDERS = ("first_attack_own_turn", "archaludon_by_own_turn3", "decisions", "won")
GATE_CEILING = 0.01  # mechanism_gates()' absolute ceiling for the snipe rate


# ----------------------------------------------------------------- statistics
def wilson_interval(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Kept numerically identical to harness/utils.py so figures line up."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def fisher_exact_one_sided(k1: int, n1: int, k2: int, n2: int) -> float:
    """P(candidate >= k1 | same underlying rate). Mirrors harness/utils.py."""
    a, b, c, d = k1, n1 - k1, k2, n2 - k2
    total = a + b + c + d
    if total == 0:
        return 1.0
    row1, col1 = a + b, a + c

    def logc(n: int, k: int) -> float:
        if k < 0 or k > n:
            return float("-inf")
        return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)

    denominator = logc(total, col1)
    tail = 0.0
    for x in range(a, min(row1, col1) + 1):
        term = logc(row1, x) + logc(total - row1, col1 - x) - denominator
        tail += math.exp(term)
    return min(1.0, tail)


def permutation_p(group_a: list[float], group_b: list[float], *,
                  draws: int = 20000, seed: int = 12345) -> float | None:
    """Two-sided permutation test on the difference of means."""
    if not group_a or not group_b:
        return None
    observed = abs(sum(group_a) / len(group_a) - sum(group_b) / len(group_b))
    pool = group_a + group_b
    n_a = len(group_a)
    rng = random.Random(seed)
    hits = 0
    for _ in range(draws):
        rng.shuffle(pool)
        diff = abs(sum(pool[:n_a]) / n_a - sum(pool[n_a:]) / (len(pool) - n_a))
        if diff >= observed - 1e-12:
            hits += 1
    return (hits + 1) / (draws + 1)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------- data
def load_games(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def discover(root: Path) -> dict[str, list[dict]]:
    """Accept an arm-output root, a single arm directory, or a games.csv."""
    if root.is_file():
        return {root.parent.name or root.stem: load_games(root)}
    direct = root / "games.csv"
    if direct.exists():
        return {root.name: load_games(direct)}
    found = {}
    for candidate in sorted(root.glob("*/games.csv")):
        found[candidate.parent.name] = load_games(candidate)
    if not found:
        raise SystemExit(f"no games.csv found under {root}")
    return found


def number(row: dict, key: str) -> float:
    raw = (row.get(key) or "").strip()
    if raw in ("", "None"):
        return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def as_int(row: dict, key: str) -> int:
    value = number(row, key)
    return 0 if value != value else int(value)


# -------------------------------------------------------------------- report
def describe_arm(name: str, rows: list[dict], metric_key: str) -> dict:
    completed = [r for r in rows if r.get("completed") == "1"]
    snipe = [r for r in completed if as_int(r, metric_key) > 0]
    clean = [r for r in completed if as_int(r, metric_key) == 0]
    events = sum(as_int(r, "c0_2_promotion_event_count") for r in completed)
    snipe_events = sum(as_int(r, metric_key) for r in completed)
    return {
        "arm": name,
        "games": len(completed),
        "snipe_games": len(snipe),
        "snipe_rows": snipe,
        "clean_rows": clean,
        "promotion_events": events,
        "snipe_events": snipe_events,
        "event_rate": (snipe_events / events) if events else 0.0,
    }


def print_arm(stats: dict) -> None:
    n, k = stats["games"], stats["snipe_games"]
    lo, hi = wilson_interval(k, n)
    print(f"\n  {stats['arm']}: {k}/{n} games contain a snipe "
          f"= {k / n * 100 if n else 0:.1f}%  95% CI [{lo * 100:.1f}%, {hi * 100:.1f}%]")
    events, snipe_events = stats["promotion_events"], stats["snipe_events"]
    e_lo, e_hi = wilson_interval(snipe_events, events)
    flag = "OVER CEILING" if stats["event_rate"] > GATE_CEILING else "within ceiling"
    print(f"    event rate (what the gate tests): {snipe_events}/{events} "
          f"= {stats['event_rate'] * 100:.2f}%  95% CI [{e_lo * 100:.2f}%, {e_hi * 100:.2f}%]"
          f"  -> {flag} ({GATE_CEILING * 100:.1f}%)")


def print_confounders(stats: dict) -> None:
    snipe, clean = stats["snipe_rows"], stats["clean_rows"]
    if not snipe:
        print("    (no snipe games; nothing to split)")
        return
    print(f"    {'field':<26}{'snipe':>9}{'clean':>9}{'perm p':>9}  note")
    for field in CONFOUNDERS:
        a = [number(r, field) for r in snipe]
        b = [number(r, field) for r in clean]
        a = [x for x in a if x == x]
        b = [x for x in b if x == x]
        if not a or not b:
            continue
        p = permutation_p(a, b)
        note = ""
        # Binary fields: warn when zero was the likeliest observation anyway.
        if set(a) <= {0.0, 1.0} and set(b) <= {0.0, 1.0}:
            base = mean(b)
            expected = len(a) * base
            if sum(a) == 0 and expected < 3:
                note = (f"0/{len(a)} is unremarkable: expected {expected:.2f}, "
                        f"P(zero)={math.pow(1 - base, len(a)):.2f}")
        if not note and min(len(a), len(b)) < 10:
            note = f"n={len(a)} vs {len(b)}: underpowered"
        print(f"    {field:<26}{mean(a):>9.2f}{mean(b):>9.2f}"
              f"{(f'{p:.3f}' if p is not None else '-'):>9}  {note}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path,
                        help="multiarm output root, a single arm dir, or a games.csv")
    parser.add_argument("--matchup", help="restrict to one opponent label, e.g. tusk_mill")
    parser.add_argument("--baseline", help="arm name to compare the others against")
    parser.add_argument("--metric", choices=sorted(SNIPE_METRICS) + ["both"], default="both")
    args = parser.parse_args()

    arms = discover(args.path)
    if args.matchup:
        arms = {name: [r for r in rows if r.get("opponent") == args.matchup]
                for name, rows in arms.items()}
        arms = {name: rows for name, rows in arms.items() if rows}
        if not arms:
            raise SystemExit(f"no rows left after filtering to matchup {args.matchup!r}")

    metrics = sorted(SNIPE_METRICS) if args.metric == "both" else [args.metric]
    scope = args.matchup or "all matchups"
    print(f"scope: {scope}   arms: {', '.join(arms)}")
    print("note: the violation flag is a superset of the snipe flag by definition,")
    print("      so 'snipe games also show a violation' is always 100% and is not reported.")

    for metric in metrics:
        key = SNIPE_METRICS[metric]
        print("\n" + "=" * 78)
        print(f"metric: {metric}  ({key})"
              + ("   <- this is the one mechanism_gates() tests" if metric == "true" else
                 "   <- legacy, Duraludon only; blind to Archaludon ex"))
        print("=" * 78)
        computed = {name: describe_arm(name, rows, key) for name, rows in arms.items()}
        for stats in computed.values():
            print_arm(stats)
            print_confounders(stats)

        baseline = args.baseline or next(iter(computed))
        if baseline not in computed:
            raise SystemExit(f"baseline {baseline!r} not among {sorted(computed)}")
        others = [n for n in computed if n != baseline]
        if others:
            print(f"\n  vs baseline '{baseline}' (Fisher one-sided, candidate worse):")
            base = computed[baseline]
            for name in others:
                cand = computed[name]
                p_games = fisher_exact_one_sided(cand["snipe_games"], cand["games"],
                                                 base["snipe_games"], base["games"])
                p_events = fisher_exact_one_sided(cand["snipe_events"], cand["promotion_events"],
                                                  base["snipe_events"], base["promotion_events"])
                verdict = "significant" if p_events < 0.05 else "not significant"
                print(f"    {name:<12} games p={p_games:.3f}   events p={p_events:.3f}  ({verdict})")


if __name__ == "__main__":
    main()
