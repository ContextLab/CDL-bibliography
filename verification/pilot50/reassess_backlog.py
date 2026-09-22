"""Apply the tested resolver revision once to unresolved cached records offline."""

from collections import Counter
import gzip
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from auto_review import RESOLVER_VERSION, run_auto_review
from verification import ACCEPTED, Cache, current_results, export_snapshot


def main():
    work = ROOT / ".bibcheck/pilot50"
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        before = current_results("cdl.bib", cache)
        response_count = cache.db.execute("SELECT count(*) FROM responses").fetchone()[
            0
        ]
        start = time.monotonic()
        after = run_auto_review("cdl.bib", cache, work / "backlog-report.jsonl")
        assert all(
            after[k] == old for k, old in before.items() if old["status"] in ACCEPTED
        )
        assert (
            response_count
            == cache.db.execute("SELECT count(*) FROM responses").fetchone()[0]
        )
        changes = {
            k: {"before": old["status"], "after": after[k]["status"]}
            for k, old in before.items()
            if old["status"] != after[k]["status"]
        }
        # Repeat must not add any review records or change check times.
        reviews = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
        repeated = run_auto_review("cdl.bib", cache, work / "backlog-report.jsonl")
        assert repeated == after
        assert reviews == cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
        summary = {
            "resolver_version": RESOLVER_VERSION,
            "before": dict(Counter(r["status"] for r in before.values())),
            "after": dict(Counter(r["status"] for r in after.values())),
            "changes": changes,
            "network_requests": 0,
            "repeat_added_reviews": 0,
            "seconds": round(time.monotonic() - start, 2),
        }
        (work / "backlog-reassessment.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
        export_snapshot("cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
        print(
            json.dumps({k: v for k, v in summary.items() if k != "changes"}), flush=True
        )
    finally:
        cache.close()


if __name__ == "__main__":
    main()
