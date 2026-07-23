"""Build submission.zip from main.py (+ deck.csv if present).

Run: python3 make_submission.py

Why this exists: running main.py directly in a notebook cell executes
`from cg.api import ...` at import time, which only resolves inside the
actual evaluation harness (/kaggle_simulations/agent on sys.path). Outside
that harness (e.g. a plain notebook commit run) the import fails with
ModuleNotFoundError: No module named 'cg' -- see crustleplanb.log. Zipping
the source instead of executing it sidesteps that: the zip's contents are
never imported by the notebook kernel, only unpacked by the harness at
episode start.

deck.csv (the card-id list read by read_deck_csv()) is not stored in this
repo -- add your own deck.csv next to main.py before running this script,
or it will be omitted from the zip and the agent will fail to find it at
episode start.
"""

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "submission.zip")
FILES = ["main.py", "deck.csv"]


def main():
    present = [f for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    missing = [f for f in FILES if f not in present]
    if "main.py" not in present:
        sys.exit("main.py not found next to make_submission.py -- nothing to package")
    if missing:
        print(f"[make_submission] warning: missing {missing}, excluding from zip", file=sys.stderr)

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in present:
            zf.write(os.path.join(ROOT, f), arcname=f)

    print(f"[make_submission] wrote {OUT} with {present}")


if __name__ == "__main__":
    main()
