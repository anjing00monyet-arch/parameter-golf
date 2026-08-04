#!/usr/bin/env python3
"""Package agent/main.py into a Kaggle-ready submission.tar.gz.

Produces a deterministic archive (fixed mtime/uid/gid) containing exactly
one file, main.py, at the archive root -- matching what the Kaggriculture
submission format expects.

Usage:
    python tools/build_submission.py
    python tools/build_submission.py --agent agent/main.py --out submissions/submission.tar.gz
"""
from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import tarfile
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent


def build(agent_path: Path, out_path: Path) -> dict:
    source = agent_path.read_text(encoding="utf-8")
    ast.parse(source)  # fail loudly before packaging a broken file
    compile(source, str(agent_path), "exec")

    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w") as archive:
            payload = source.encode("utf-8")
            info = tarfile.TarInfo("main.py")
            info.size = len(payload)
            info.mode = 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(payload))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw.getvalue())

    with tarfile.open(out_path, "r:gz") as archive:
        names = archive.getnames()
        assert names == ["main.py"], f"archive root must contain only main.py, got {names}"
        archived = archive.extractfile("main.py").read().decode("utf-8")
    assert archived == source

    return {
        "agent_source": str(agent_path.relative_to(LAB_ROOT)),
        "submission": str(out_path.relative_to(LAB_ROOT)),
        "submission_bytes": out_path.stat().st_size,
        "archive_root_entries": names,
        "main_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "archive_sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", type=Path, default=LAB_ROOT / "agent" / "main.py")
    parser.add_argument("--out", type=Path, default=LAB_ROOT / "submissions" / "submission.tar.gz")
    args = parser.parse_args()

    import json
    print(json.dumps(build(args.agent, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
