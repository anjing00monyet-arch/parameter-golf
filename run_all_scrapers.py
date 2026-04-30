"""Run all web scrapers and merge their output into a single JSON file."""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


SCRAPERS = [
    ("web_5s_scraper.py", "web_5s_output.json"),
    ("web_5s_scraper_advanced.py", "web_5s_advanced_output.json"),
]


def run_scraper(script: str) -> bool:
    print(f"\n--- Running {script} ---")
    result = subprocess.run(
        [sys.executable, script],
        capture_output=False,
        text=True,
    )
    return result.returncode == 0


def merge_outputs(output_files: list[str]) -> dict:
    merged = {"merged_at": datetime.now().isoformat(), "sources": []}
    for path in output_files:
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            merged["sources"].append({"file": path, "data": data})
        else:
            merged["sources"].append({"file": path, "data": None, "error": "file not found"})
    return merged


def main():
    print(f"=== run_all_scrapers.py  ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    t0 = time.time()

    statuses = {}
    output_files = []
    for script, out_file in SCRAPERS:
        ok = run_scraper(script)
        statuses[script] = "OK" if ok else "FAILED"
        output_files.append(out_file)

    merged = merge_outputs(output_files)
    merged["scraper_statuses"] = statuses

    out_path = "all_scrapers_output.json"
    Path(out_path).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    elapsed = time.time() - t0
    print(f"\n=== Summary ({elapsed:.1f}s total) ===")
    for script, status in statuses.items():
        print(f"  {script}: {status}")
    print(f"  Merged output -> {out_path}")


if __name__ == "__main__":
    main()
