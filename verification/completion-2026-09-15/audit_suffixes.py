"""Reopen suffix conflicts from original cached PubMed evidence, without calls."""
from collections import Counter
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import Cache, current_results, export_snapshot, load_entries, run_lock
from reassess import export_queue

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name


def main():
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        with run_lock(cache):
            backup = WORK / "before-suffix-audit.jsonl.gz"
            if not backup.exists():
                shutil.copyfile(ROOT / "verification/baseline.jsonl.gz", backup)
            entries = load_entries(ROOT / "cdl.bib")
            before = current_results(ROOT / "cdl.bib", cache, entries)
            cache.index_notices()
            after = current_results(ROOT / "cdl.bib", cache, entries)
            assert all(after[k]["fingerprint"] == r["fingerprint"] for k, r in before.items())
            changes = [{"key": k, "before": r["status"], "after": after[k]["status"], "issues": after[k]["issues"]}
                       for k, r in before.items() if r["status"] != after[k]["status"]]
            assert all(r["before"] == "metadata_verified" and r["after"] == "needs_review" for r in changes)
            count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
            assert current_results(ROOT / "cdl.bib", cache, entries) == after
            assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == count
            export_snapshot(ROOT / "cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
            export_queue(entries, after)
            report = {"network_requests": 0, "repeat_review_writes": 0, "status_changes": changes,
                      "suffix_witnesses": cache.db.execute("SELECT count(*) FROM source_author_suffixes").fetchone()[0],
                      "statuses": dict(Counter(r["status"] for r in after.values()))}
            if changes or not (HERE / "suffix-audit-results.json").exists():
                (HERE / "suffix-audit-results.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report), flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
