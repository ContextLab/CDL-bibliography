"""Re-export verification/baseline.jsonl.gz and review-queue.jsonl.gz from the main cache.

Used after the first initials attempt was stopped by the PMC bulk-hours guard and
cdl.bib was restored to the suffix-strip state (README, "initials attempt 1"). Reading a
result attaches source evidence learned since it was saved (Cache.retain_notices), so one
needs_review entry (InouEtal15) gained the PMC front-matter record fetched during the
attempt. No status changes; this export records the current state exactly.

    .venv/bin/python verification/apply-2026-09-27/resync_baseline.py
"""
from collections import Counter
import importlib.util
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("apply0923", ROOT / "verification/apply-2026-09-23/apply.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
os.chdir(ROOT)
from verification import Cache, current_results, export_snapshot, run_lock  # noqa: E402

cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
try:
    with run_lock(cache):
        export_snapshot("cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
        results = current_results("cdl.bib", cache)
    base.export_queue(results)
    print(dict(Counter(r["status"] for r in results.values())))
finally:
    cache.close()
