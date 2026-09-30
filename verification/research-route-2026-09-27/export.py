"""Export verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz after the
research-route backfill, the way the apply runners do (../apply-2026-09-25e/apply.py:
export_snapshot, then completion-2026-09-15/reassess.py's export_queue).

    .venv/bin/python verification/research-route-2026-09-27/export.py
"""
from collections import Counter
import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "bibcheck"))
sys.path.insert(0, str(ROOT / "verification/completion-2026-09-15"))

from verification import Cache, export_snapshot, load_entries, run_lock  # noqa: E402
import osf_review, datacite_review, acl_review, sfn_abstracts, research_route  # noqa: E402,F401

spec = importlib.util.spec_from_file_location("completion_reassess", ROOT / "verification/completion-2026-09-15/reassess.py")
reassess = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reassess)

cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
try:
    with run_lock(cache):
        results = export_snapshot("cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
        queue = reassess.export_queue(load_entries("cdl.bib"), results)
    print(dict(Counter(r["status"] for r in results.values())), "queue", len(queue))
finally:
    cache.close()
