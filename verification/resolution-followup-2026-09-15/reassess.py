"""Apply the tested initials fix offline and export the current local baseline."""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock
from auto_review import run_auto_review

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name


def main():
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        # A source audit may reveal a conflict that registry-only matching
        # cannot see. Use the existing external-evidence hold, never approval.
        with run_lock(cache):
            entries = load_entries("cdl.bib")
            for hold in json.loads((HERE / "source-holds.json").read_text()):
                entry = entries[hold["key"]]
                r = cache.get("cdl.bib", entry)
                if r.get("external_evidence"):
                    continue
                assert r["status"] == "needs_review", hold["key"]
                cache.put("cdl.bib", entry, dict(r, external_evidence=[hold],
                    issues=["Attached external evidence requires explicit adjudication"]))
        before = current_results("cdl.bib", cache)
        stages = []
        for cycle in ("run", "repeat"):
            start = time.monotonic()
            n = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
            after = run_auto_review("cdl.bib", cache, WORK / "offline-report.jsonl")
            assert all(after[k] == r for k, r in before.items() if r["status"] in ACCEPTED)
            stage = {"cycle": cycle, "network_requests": 0,
                     "seconds": round(time.monotonic() - start, 2),
                     "statuses": dict(Counter(r["status"] for r in after.values())),
                     "added_review_records": cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] - n}
            if cycle == "repeat":
                assert after == first
                assert stage["added_review_records"] == 0
            first = after
            stages.append(stage)
            print(json.dumps(stage), flush=True)
            (HERE / "offline-stages.json").write_text(json.dumps(stages, indent=2) + "\n")
        original = {}
        with gzip.open(WORK / "before.jsonl.gz", "rt") as f:
            for line in f:
                r = json.loads(line)
                if "key" in r:
                    original[r["key"]] = r
        baseline = ROOT / "verification/baseline.jsonl.gz"
        export_snapshot("cdl.bib", cache, baseline)
        entries = load_entries("cdl.bib")
        queue = []
        for key, r in sorted(after.items()):
            if r["status"] in ACCEPTED:
                continue
            best = min(r.get("candidates", []), key=lambda c: (
                not c.get("evidence", {}).get("title", {}).get("match"),
                not c.get("evidence", {}).get("author", {}).get("match"), len(c.get("issues", []))), default={})
            findings = best.get("issues") or r.get("issues", [])
            route = ("source_discovery" if not best.get("evidence", {}).get("title", {}).get("match")
                     else "author_identity" if not best.get("evidence", {}).get("author", {}).get("match")
                     else "publication_version" if any("version" in s or "relationship" in s or "unambiguous" in s for s in findings)
                     else "field_adjudication")
            queue.append({"key": key, "fingerprint": r["fingerprint"], "policy": r["policy"],
                          "entry": entries[key]["fields"], "candidate_doi": best.get("doi"),
                          "candidate_url": best.get("url"), "findings": findings, "route": route})
        with gzip.open(ROOT / "verification/review-queue.jsonl.gz", "wt") as f:
            for row in queue:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        def accepted_doi(r):
            if r.get("accepted_doi"):
                return r["accepted_doi"]
            # Direct registry verification predates the explicit source label.
            good = {c["doi"] for c in r.get("candidates", []) if not c.get("issues") and c.get("evidence")}
            assert len(good) == 1, r["key"]
            return good.pop()

        summary = {"stages": stages, "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                   "queue_routes": dict(Counter(r["route"] for r in queue)),
                   "new_approvals": {k: accepted_doi(r) for k, r in after.items()
                                     if r["status"] in ACCEPTED and original[k]["status"] not in ACCEPTED},
                   "initials_approvals": {k: accepted_doi(r) for k, r in after.items()
                                          if r["status"] in ACCEPTED and original[k]["status"] not in ACCEPTED
                                          and k not in {"GonzEtal19", "PeirEtal19", "WallEtal04"}}}
        assert cache.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        (HERE / "offline-results.json").write_text(json.dumps(summary, indent=2) + "\n")
        print("PASS: offline repeat has zero writes; all prior approvals unchanged", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
