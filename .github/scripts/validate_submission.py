#!/usr/bin/env python3
"""Structural checks for parameter-golf submission PRs.

Verifies the mechanical rules from the README's "Submission Process" section
that don't require judgment: required files present, submission.json has the
minimum expected fields, the artifact size budget, and that the PR only
touches the records/ tree (unless it's a declared core-script PR).

This does NOT attempt to reproduce training runs or judge statistical
significance / rule compliance in spirit -- that's left to the Claude review
step, since it needs to read prose and code, not just check file presence.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORD_TRACKS = ("records/track_10min_16mb", "records/track_non_record_16mb")
REQUIRED_FILES = ("README.md",)
REQUIRED_SUBMISSION_KEYS = ("author", "github_id", "val_bpb")
ARTIFACT_BYTE_LIMIT = 16_000_000


def changed_files(base_ref: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def new_record_dirs(files: list[str]) -> set[Path]:
    dirs = set()
    for f in files:
        for track in RECORD_TRACKS:
            if f.startswith(track + "/"):
                rel = Path(f).relative_to(track)
                if rel.parts:
                    dirs.add(Path(track) / rel.parts[0])
    return dirs


def check_out_of_scope_changes(files: list[str]) -> list[str]:
    errors = []
    for f in files:
        if any(f.startswith(t + "/") for t in RECORD_TRACKS):
            continue
        if f in ("train_gpt.py", "train_gpt_mlx.py") or f.startswith("data/"):
            # Allowed per "PRs on Core Code", but flagged for human attention.
            continue
        errors.append(
            f"'{f}' is outside records/ and outside the recognized core-script "
            "allowlist (train_gpt.py, train_gpt_mlx.py, data/). Submission PRs "
            "should only add a new folder under records/<track>/."
        )
    return errors


def check_record_dir(record_dir: Path) -> list[str]:
    errors = []
    abs_dir = REPO_ROOT / record_dir

    for required in REQUIRED_FILES:
        if not (abs_dir / required).is_file():
            errors.append(f"{record_dir}: missing required file '{required}'")

    has_train_script = any(abs_dir.glob("*.py"))
    if not has_train_script:
        errors.append(f"{record_dir}: no training script (*.py) found")

    log_candidates = list(abs_dir.glob("*log*")) + list(abs_dir.glob("*.tsv")) + list(abs_dir.glob("RESULTS.md"))
    if not log_candidates:
        errors.append(
            f"{record_dir}: no run-log-like file found (expected something like "
            "*log*, *.tsv, or RESULTS.md demonstrating the run)"
        )

    submission_files = list(abs_dir.glob("submission*.json"))
    if not submission_files:
        errors.append(
            f"{record_dir}: missing a submission.json (or submission_*.json) file with "
            "name, GitHub ID, val_bpb, and related metadata"
        )
    for submission_path in submission_files:
        rel_path = submission_path.relative_to(REPO_ROOT)
        try:
            data = json.loads(submission_path.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"{rel_path}: invalid JSON ({e})")
            continue
        if isinstance(data, dict):
            missing_keys = [k for k in REQUIRED_SUBMISSION_KEYS if k not in data or data[k] in (None, "")]
            if missing_keys:
                errors.append(f"{rel_path}: missing/empty required keys: {missing_keys}")
        else:
            errors.append(f"{rel_path}: expected a JSON object at the top level")

    total_bytes = sum(p.stat().st_size for p in abs_dir.rglob("*") if p.is_file())
    if total_bytes > ARTIFACT_BYTE_LIMIT:
        errors.append(
            f"{record_dir}: on-disk folder size is {total_bytes:,} bytes, which exceeds the "
            f"{ARTIFACT_BYTE_LIMIT:,} byte artifact cap. Note: this is a rough proxy (it sums every "
            "file in the folder, including logs/README) not the exact 'code + compressed model' "
            "definition from the rules -- treat an excess here as a prompt to check manually, not "
            "an automatic disqualification."
        )

    return errors


def main() -> int:
    base_ref = sys.argv[1] if len(sys.argv) > 1 else "origin/main"

    files = changed_files(base_ref)
    if not files:
        print("No changed files detected against base; nothing to validate.")
        return 0

    all_errors = []
    all_errors.extend(check_out_of_scope_changes(files))

    record_dirs = new_record_dirs(files)
    if not record_dirs:
        print("No new records/<track>/<submission> folder detected in this diff.")
        print("Changed files:")
        for f in files:
            print(f"  {f}")
        if all_errors:
            print("\nIssues found:")
            for e in all_errors:
                print(f"  - {e}")
            return 1
        return 0

    for record_dir in sorted(record_dirs):
        all_errors.extend(check_record_dir(record_dir))

    if all_errors:
        print("Submission validation FAILED:\n")
        for e in all_errors:
            print(f"  - {e}")
        return 1

    print("Submission validation passed structural checks for:")
    for d in sorted(record_dirs):
        print(f"  - {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
