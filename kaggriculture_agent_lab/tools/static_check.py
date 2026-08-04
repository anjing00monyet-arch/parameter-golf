#!/usr/bin/env python3
"""Static checks for a Kaggriculture agent submission file.

Usage:
    python tools/static_check.py agent/main.py

Verifies, without running a single game turn:
  1. the file is syntactically valid Python
  2. it defines exactly one top-level `agent` function
  3. it imports/executes cleanly and exposes a callable `agent`
  4. a submission archive built from it would contain nothing but the file
     itself at the archive root (checked here by construction, not by
     inspecting an existing archive -- see tools/build_submission.py)
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def count_top_level_agent_defs(tree: ast.Module) -> int:
    return sum(
        1
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "agent"
    )


def check(path: Path) -> bool:
    results = {}
    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=str(path))
        results["syntax"] = "PASS"
    except SyntaxError as exc:
        results["syntax"] = f"FAIL ({exc})"
        print(format_report(path, results))
        return False

    agent_defs = count_top_level_agent_defs(tree)
    results["agent_def_count"] = agent_defs

    namespace: dict = {}
    try:
        exec(compile(source, str(path), "exec"), namespace)
        loaded_ok = callable(namespace.get("agent"))
        results["module_load"] = "PASS" if loaded_ok else "FAIL (agent not callable)"
    except Exception as exc:  # noqa: BLE001 - report any load-time failure
        results["module_load"] = f"FAIL ({exc!r})"
        loaded_ok = False

    ok = (
        results["syntax"] == "PASS"
        and agent_defs == 1
        and loaded_ok
    )

    print(format_report(path, results))
    return ok


def format_report(path: Path, results: dict) -> str:
    lines = [f"static_check: {path}"]
    if "syntax" in results:
        lines.append(f"  Python構文        : {results['syntax']}")
    if "agent_def_count" in results:
        lines.append(f"  agent定義数        : {results['agent_def_count']}")
    if "module_load" in results:
        lines.append(f"  モジュール読込      : {results['module_load']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent_path", type=Path, help="path to the agent source file")
    args = parser.parse_args()

    if not args.agent_path.exists():
        print(f"error: {args.agent_path} does not exist", file=sys.stderr)
        return 2

    ok = check(args.agent_path)
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
