"""Production review of the entries the organization-author key rule renamed (2026-09-27):
MorrRNS11, Cent23, R12 (renamed only; their fingerprints are unchanged, so Cache.get follows
them) and US20a/US20b (renamed and Force removed, so new fingerprints without a review row).
Runs the apply runners' production pipeline (../apply-2026-09-23/apply.py: pipeline) for these
keys, then a repeat that must make zero network requests and write zero review records.

    .venv/bin/python verification/research-route-2026-09-27/review_renamed.py
"""
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "bibcheck"))
spec = importlib.util.spec_from_file_location("apply0923", ROOT / "verification/apply-2026-09-23/apply.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
import research_route  # noqa: E402,F401  (registers its validator and notice hook)
from verification import Cache  # noqa: E402

KEYS = ["MorrRNS11", "Cent23", "R12", "US20a", "US20b"]
WORK = ROOT / ".bibcheck/research-route-2026-09-27"

cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
try:
    client = base.client_for(cache)
    rows = []
    for cycle in ("run", "repeat"):  # each review layer takes the cache's run lock itself
        calls, count = client.requests, base.review_count(cache)
        after = base.pipeline(cache, client, KEYS, WORK / f"review-renamed-{cycle}.jsonl")
        row = {"cycle": cycle, "network_requests": client.requests - calls,
               "added_review_records": base.review_count(cache) - count,
               "statuses": {k: after[k]["status"] for k in KEYS},
               "library_statuses": dict(Counter(r["status"] for r in after.values()))}
        print(json.dumps(row), flush=True)
        rows.append(row)
    assert rows[1]["network_requests"] == rows[1]["added_review_records"] == 0, rows[1]
    (Path(__file__).parent / "review-renamed.json").write_text(json.dumps(rows, indent=1) + "\n")
finally:
    cache.close()
