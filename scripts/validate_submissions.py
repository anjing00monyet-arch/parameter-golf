#!/usr/bin/env python3
"""Validate Parameter Golf leaderboard submissions.

A submission lives in a dated record folder under one of the track directories:

    records/track_10min_16mb/<YYYY-MM-DD>_<slug>/
    records/track_non_record_16mb/<YYYY-MM-DD>_<slug>/

Each folder must contain a `submission.json` (metadata) and a `README.md`
(write-up). The schema used across historical records is loose, so this checker
enforces a small, stable set of invariants rather than a rigid schema:

  * submission.json parses as JSON
  * a README.md exists alongside it
  * an author is identifiable (`author` or `github_id`)
  * a score is present and sane (val_bpb / val_loss / mean_* / seed_results)
  * the reported artifact size, if given, is within the 16,000,000-byte cap
  * the `track` field, if given, matches the parent track directory
  * the folder name starts with an ISO date and has no spaces

By default only records that changed relative to a base git ref are validated
(the PR gate), so the messy legacy corpus is grandfathered. Use --all to audit
every record folder.

Exit status is non-zero if any ERROR-level finding is reported (unless
--warn-only is passed).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

# The artifact cap is 16 MB expressed as 16,000,000 bytes (decimal), matching
# the "16,000,000-byte cap" language in the challenge's own baseline record.
ARTIFACT_CAP_BYTES = 16_000_000

# Recognised track directories and the value their `track` field should carry.
TRACK_DIRS = {
    "track_10min_16mb": "10min_16mb",
    "track_non_record_16mb": "non_record_16mb",
}

RECORDS_ROOT = "records"

# Fields that may carry the headline score, checked in priority order.
SCORE_FIELDS = ("val_bpb", "bpb", "mean_val_bpb", "val_loss", "mean_val_loss")

# Fields that may carry the artifact size in bytes.
SIZE_FIELDS = (
    "bytes_total",
    "model_size_bytes",
    "artifact_bytes",
    "artifact_size_bytes",
    "artifact_bytes_max",
    "artifact_bytes_mean",
    "total_bytes",
    "size_bytes",
    "bytes_model_compressed",
)

# A plausible bits-per-byte / loss lives in this open interval. Anything outside
# is almost certainly a units mistake or a placeholder.
SCORE_MIN, SCORE_MAX = 0.0, 20.0

DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")

ERROR = "error"
WARNING = "warning"


@dataclass
class Finding:
    level: str
    path: str
    message: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def error(self, path: str, message: str) -> None:
        self.findings.append(Finding(ERROR, path, message))

    def warn(self, path: str, message: str) -> None:
        self.findings.append(Finding(WARNING, path, message))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == WARNING]


def _iter_scores(data: dict):
    """Yield every numeric score-like value found in a submission dict."""
    for key in SCORE_FIELDS:
        if key in data:
            yield key, data[key]
    seed_results = data.get("seed_results")
    if isinstance(seed_results, dict):
        for seed, res in seed_results.items():
            if isinstance(res, dict):
                for key in ("val_bpb", "val_loss", "bpb"):
                    if key in res:
                        yield f"seed_results.{seed}.{key}", res[key]


def _iter_sizes(data: dict):
    """Yield every numeric size-like value found in a submission dict."""
    for key in SIZE_FIELDS:
        if key in data:
            yield key, data[key]
    seed_results = data.get("seed_results")
    if isinstance(seed_results, dict):
        for seed, res in seed_results.items():
            if isinstance(res, dict) and "artifact_bytes" in res:
                yield f"seed_results.{seed}.artifact_bytes", res["artifact_bytes"]


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_record(folder: str, report: Report) -> None:
    """Validate a single record folder, appending findings to `report`."""
    folder = folder.rstrip("/")
    sub_path = os.path.join(folder, "submission.json")
    readme_path = os.path.join(folder, "README.md")
    name = os.path.basename(folder)

    # --- location & naming -------------------------------------------------
    parent = os.path.basename(os.path.dirname(folder))
    expected_track = TRACK_DIRS.get(parent)
    if expected_track is None:
        report.error(
            folder,
            f"record folder is not under a known track directory "
            f"({', '.join(TRACK_DIRS)}); found parent '{parent}'",
        )

    if " " in name:
        report.error(folder, f"folder name contains spaces: '{name}'")

    m = DATE_PREFIX_RE.match(name)
    if not m:
        report.error(
            folder,
            f"folder name must start with an ISO date prefix 'YYYY-MM-DD_'; got '{name}'",
        )
        folder_date = None
    else:
        folder_date = m.group(1)
        try:
            dt.date.fromisoformat(folder_date)
        except ValueError:
            report.error(folder, f"folder date prefix '{folder_date}' is not a valid date")
            folder_date = None

    # --- required files ----------------------------------------------------
    if not os.path.isfile(readme_path):
        report.error(folder, "missing README.md write-up")

    if not os.path.isfile(sub_path):
        report.error(folder, "missing submission.json")
        return

    try:
        with open(sub_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        report.error(sub_path, f"submission.json is not valid JSON: {exc}")
        return
    except OSError as exc:
        report.error(sub_path, f"could not read submission.json: {exc}")
        return

    if not isinstance(data, dict):
        report.error(sub_path, "submission.json must contain a JSON object")
        return

    # --- author ------------------------------------------------------------
    if not (data.get("author") or data.get("github_id")):
        report.error(sub_path, "no author identified (need 'author' or 'github_id')")

    # --- score -------------------------------------------------------------
    scores = list(_iter_scores(data))
    if not scores:
        report.error(
            sub_path,
            "no score found (expected one of "
            f"{', '.join(SCORE_FIELDS)}, or seed_results.*.val_bpb)",
        )
    else:
        for key, value in scores:
            if not _is_number(value):
                report.error(sub_path, f"score field '{key}' is not a finite number: {value!r}")
            elif not (SCORE_MIN < value < SCORE_MAX):
                report.error(
                    sub_path,
                    f"score field '{key}' = {value} is outside the plausible "
                    f"range ({SCORE_MIN}, {SCORE_MAX})",
                )

    # --- artifact size cap -------------------------------------------------
    sizes = list(_iter_sizes(data))
    if not sizes:
        report.warn(
            sub_path,
            "no artifact size reported; consider adding 'bytes_total' "
            f"(cap is {ARTIFACT_CAP_BYTES:,} bytes)",
        )
    for key, value in sizes:
        if not _is_number(value):
            report.error(sub_path, f"size field '{key}' is not a finite number: {value!r}")
        elif value <= 0:
            report.error(sub_path, f"size field '{key}' = {value} must be positive")
        elif value > ARTIFACT_CAP_BYTES:
            report.error(
                sub_path,
                f"size field '{key}' = {value:,} bytes exceeds the "
                f"{ARTIFACT_CAP_BYTES:,}-byte artifact cap",
            )

    # --- track consistency -------------------------------------------------
    track = data.get("track")
    if track is not None and expected_track is not None and track != expected_track:
        report.error(
            sub_path,
            f"'track' field '{track}' does not match the parent directory "
            f"(expected '{expected_track}')",
        )

    # --- date consistency (advisory) --------------------------------------
    raw_date = data.get("date") or data.get("run_date")
    if raw_date and folder_date:
        sub_date = str(raw_date)[:10]
        try:
            dt.date.fromisoformat(sub_date)
        except ValueError:
            report.warn(sub_path, f"date field '{raw_date}' is not an ISO date")
        else:
            if sub_date != folder_date:
                report.warn(
                    sub_path,
                    f"date field '{sub_date}' differs from folder date '{folder_date}'",
                )


# --------------------------------------------------------------------------
# Discovery of records to validate
# --------------------------------------------------------------------------

def all_record_folders() -> list[str]:
    folders: set[str] = set()
    for track_dir in TRACK_DIRS:
        base = os.path.join(RECORDS_ROOT, track_dir)
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            full = os.path.join(base, entry)
            if os.path.isdir(full):
                folders.add(full)
    return sorted(folders)


def _git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def changed_record_folders(base: str) -> list[str]:
    """Record folders touched between `base` and the working tree.

    Uses a three-dot diff (merge base) so only the changes introduced on this
    branch/PR are considered. Deleted-only folders are skipped.
    """
    try:
        diff = _git(["diff", "--name-only", f"{base}...HEAD"])
    except subprocess.CalledProcessError:
        # base may be unknown (fresh branch / shallow clone); fall back to a
        # two-dot diff against the ref directly, then to the last commit.
        try:
            diff = _git(["diff", "--name-only", base])
        except subprocess.CalledProcessError:
            diff = _git(["diff", "--name-only", "HEAD~1"])

    prefix = RECORDS_ROOT + os.sep
    folders: set[str] = set()
    for line in diff.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        parts = line.split("/")
        # records/<track>/<record>/<...>
        if len(parts) >= 3:
            folder = os.path.join(parts[0], parts[1], parts[2])
            if os.path.isdir(folder):
                folders.add(folder)
    return sorted(folders)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def emit(report: Report, github: bool) -> None:
    for f in report.findings:
        if github:
            # GitHub Actions annotation — surfaces inline on the PR.
            print(f"::{f.level} file={f.path}::{f.message}")
        else:
            tag = "ERROR" if f.level == ERROR else "warn "
            print(f"[{tag}] {f.path}: {f.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all", action="store_true", help="validate every record folder")
    scope.add_argument(
        "--changed",
        action="store_true",
        help="validate only record folders changed relative to --base (default)",
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="git ref to diff against in --changed mode (default: origin/main)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="explicit record folders to validate (overrides --all/--changed)",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="never exit non-zero, even on errors (for audits)",
    )
    parser.add_argument(
        "--github",
        action="store_true",
        default=bool(os.environ.get("GITHUB_ACTIONS")),
        help="emit GitHub Actions annotations (auto-on under GITHUB_ACTIONS)",
    )
    args = parser.parse_args(argv)

    if args.paths:
        folders = [p.rstrip("/") for p in args.paths]
        mode = "explicit paths"
    elif args.all:
        folders = all_record_folders()
        mode = "all records"
    else:
        folders = changed_record_folders(args.base)
        mode = f"changed vs {args.base}"

    report = Report()
    for folder in folders:
        validate_record(folder, report)

    emit(report, args.github)

    n_err, n_warn = len(report.errors), len(report.warnings)
    print(
        f"\nValidated {len(folders)} record folder(s) [{mode}]: "
        f"{n_err} error(s), {n_warn} warning(s)."
    )
    if not folders:
        print("No submissions to validate.")

    if n_err and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
