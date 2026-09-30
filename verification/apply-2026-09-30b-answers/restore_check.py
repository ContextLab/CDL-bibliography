"""Restore verification/baseline.jsonl.gz into an EMPTY database and compare with the live one.

    python restore_check.py EMPTY.sqlite3
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import Cache, current_results, import_snapshot  # noqa: E402
import verification_cli  # noqa: E402,F401  (registers every route approval validator, as `crossref restore` does)

BIB = str(ROOT / "cdl.bib")
empty = Path(sys.argv[1])
assert not empty.exists(), "the target database must not exist yet"
fresh = Cache(empty)
live = Cache(ROOT / ".bibcheck/verification.sqlite3")
try:
    restored = import_snapshot(BIB, fresh, str(ROOT / "verification/baseline.jsonl.gz"))
    a, b = current_results(BIB, live), current_results(BIB, fresh)
    differ = {k: sorted(f for f in set(a[k]) | set(b[k]) if a[k].get(f) != b[k].get(f))
              for k in a if a[k] != b[k]}
    status_differ = sorted(k for k in a if a[k]["status"] != b[k]["status"])
    from collections import Counter
    print(json.dumps({"restored": restored,
                      "live": dict(sorted(Counter(r["status"] for r in a.values()).items())),
                      "fresh": dict(sorted(Counter(r["status"] for r in b.values()).items())),
                      "status_differ": status_differ,
                      "results_differ": differ}))
    assert not status_differ and not differ
    print("PASS: restore into an empty database equals the live results for every entry")
finally:
    fresh.close()
    live.close()
