#!/usr/bin/env python3
"""Pull just the true_self_snipe events out of a directory of trial JSONs.

Trial files (out/.../trials/trial-NNNNN-...json) carry the full
c0_2_duraludon_promotion_events list under "instrumentation", including which
card was selected, what the other candidates were, and the harness's own
classification. This script filters that down to only the events classified
as "true_self_snipe" (the metric mechanism_gates() actually tests), plus a
little surrounding board context, so the whole batch fits in one small file
instead of 10-20 full trial JSONs.

Usage:
    python extract_true_snipes.py <trials_dir_or_glob> [--variant NAME] > snipes.json
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path


def iter_trial_paths(spec: str) -> list[Path]:
    p = Path(spec)
    if p.is_dir():
        return sorted(p.glob("trial-*.json"))
    matches = sorted(glob.glob(spec))
    if not matches:
        raise SystemExit(f"no files matched: {spec}")
    return [Path(m) for m in matches]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trials", help="directory of trial-*.json, or a glob pattern")
    parser.add_argument("--variant", help="only keep trials whose file name contains this "
                                          "(e.g. an arm/variant name)")
    args = parser.parse_args()

    out = []
    for path in iter_trial_paths(args.trials):
        if args.variant and args.variant not in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] could not parse {path}: {exc}", file=__import__("sys").stderr)
            continue
        trial = data.get("trial", {})
        events = (data.get("instrumentation") or {}).get("c0_2_duraludon_promotion_events") or []
        hits = [e for e in events if e.get("true_self_snipe")]
        if not hits:
            continue
        out.append({
            "file": path.name,
            "variant": trial.get("variant"),
            "opponent": trial.get("opponent"),
            "winner": trial.get("winner"),
            "decisions": trial.get("decisions"),
            "true_self_snipe_events": hits,
        })

    print(json.dumps(out, ensure_ascii=False, indent=2))
    import sys
    print(f"[INFO] {len(out)} trial file(s) with at least one true_self_snipe event "
          f"({sum(len(o['true_self_snipe_events']) for o in out)} events total)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
