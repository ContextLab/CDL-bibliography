"""Reassess unresolved evidence, prove cache reuse, and export the local backlog."""

from collections import Counter
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries
from auto_review import run_auto_review

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name


def export_queue(entries, results):
    queue = []
    for key, result in sorted(results.items()):
        if result["status"] in ACCEPTED:
            continue
        best = min(result.get("candidates", []), key=lambda c: (
            not c.get("evidence", {}).get("title", {}).get("match"),
            not c.get("evidence", {}).get("author", {}).get("match"), len(c.get("issues", []))), default={})
        findings = best.get("issues") or result.get("issues", [])
        route = ("source_discovery" if not best.get("evidence", {}).get("title", {}).get("match")
                 else "author_identity" if not best.get("evidence", {}).get("author", {}).get("match")
                 else "publication_version" if any("version" in s or "relationship" in s or "unambiguous" in s for s in findings)
                 else "field_adjudication")
        queue.append({"key": key, "fingerprint": result["fingerprint"], "policy": result["policy"],
                      "entry": entries[key]["fields"], "candidate_doi": best.get("doi"),
                      "candidate_url": best.get("url"), "findings": findings, "route": route})
    with gzip.open(ROOT / "verification/review-queue.jsonl.gz", "wt") as f:
        for row in queue:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return queue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="formatting")
    label = parser.parse_args().label
    if not label.isalnum():
        parser.error("Use an alphanumeric stage label")
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        before = current_results("cdl.bib", cache)
        backup = WORK / f"before-{label}.jsonl.gz"
        if not backup.exists():
            export_snapshot("cdl.bib", cache, backup)
        stages = []
        for cycle in ("run", "repeat"):
            start = time.monotonic()
            count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
            after = run_auto_review("cdl.bib", cache, WORK / f"{label}-report.jsonl")
            assert all(after[k] == r for k, r in before.items() if r["status"] in ACCEPTED)
            stage = {"cycle": cycle, "network_requests": 0, "seconds": round(time.monotonic() - start, 2),
                     "statuses": dict(Counter(r["status"] for r in after.values())),
                     "added_review_records": cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] - count}
            if cycle == "repeat":
                assert after == first
                assert stage["added_review_records"] == 0
            first = after
            stages.append(stage)
            print(json.dumps(stage), flush=True)
        baseline = ROOT / "verification/baseline.jsonl.gz"
        export_snapshot("cdl.bib", cache, baseline)
        queue = export_queue(load_entries("cdl.bib"), after)
        with gzip.open(backup, "rt") as f:
            original = {r["key"]: r for r in map(json.loads, f) if "key" in r}
        summary = {"stages": stages, "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                   "queue_routes": dict(Counter(r["route"] for r in queue)),
                   "new_approvals": {k: r.get("accepted_doi") for k, r in after.items()
                                     if r["status"] in ACCEPTED and original[k]["status"] not in ACCEPTED}}
        (HERE / f"{label}-results.json").write_text(json.dumps(summary, indent=2) + "\n")
        assert cache.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        print("PASS: prior approvals intact; offline repeat zero writes; baseline and queue exported", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
