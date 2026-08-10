# Submission validation

`validate_submissions.py` checks that leaderboard submissions are well-formed.
It runs automatically in CI (`.github/workflows/validate-submissions.yml`) and
can be run locally before opening a PR.

## What a submission looks like

Each submission is a dated folder under one of the track directories:

```
records/track_10min_16mb/<YYYY-MM-DD>_<slug>/
records/track_non_record_16mb/<YYYY-MM-DD>_<slug>/
```

and contains at least:

- `submission.json` — metadata (see below)
- `README.md` — the write-up

## What the checker enforces

The `submission.json` schema across historical records is loose, so the checker
verifies a small, stable set of invariants rather than a rigid schema:

| Check | Level |
|-------|-------|
| `submission.json` exists and is valid JSON | error |
| `README.md` exists in the folder | error |
| author identifiable (`author` or `github_id`) | error |
| a score is present and finite in `(0, 20)` — `val_bpb`, `bpb`, `mean_val_bpb`, `val_loss`, `mean_val_loss`, or `seed_results.*.val_bpb` | error |
| every reported artifact size ≤ **16,000,000 bytes** (`bytes_total`, `model_size_bytes`, `artifact_bytes`, …) | error |
| `track` field, if present, matches the parent directory (`10min_16mb` / `non_record_16mb`) | error |
| folder is under a known track directory | error |
| folder name starts with `YYYY-MM-DD_` and has no spaces | error |
| an artifact size is reported at all | warning |
| `date` field matches the folder's date prefix | warning |

## Running locally

```bash
# Validate submissions changed on your branch vs. the base (what CI gates on):
python scripts/validate_submissions.py --changed --base origin/main

# Validate one or more specific folders:
python scripts/validate_submissions.py records/track_non_record_16mb/2026-04-25_HQE_HierarchicalQuantizedEmbedding

# Audit every record folder (reports pre-existing issues too):
python scripts/validate_submissions.py --all --warn-only
```

Exit status is non-zero when any error-level finding is reported, unless
`--warn-only` is passed. Under GitHub Actions, findings are emitted as inline
annotations automatically.

## How CI uses it

- **Pull requests / pushes** — validates only the record folders that changed
  relative to the base branch, so the legacy corpus is grandfathered and only
  new or edited submissions are gated.
- **Manual run** (`workflow_dispatch`) — pick `changed` (default) or `all` to
  audit every folder; the `all` audit reports issues without failing the run.
