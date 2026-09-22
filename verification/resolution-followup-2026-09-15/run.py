"""Continue a frozen, stratified 100-entry backlog batch and three corrections.

Each stage checkpoints through the production cache. A repeated invocation uses
the same manifest; it never silently selects a fresh batch. No LLM calls.
"""

from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_verification
from auto_review import run_auto_review
from discovery_review import run_discovery_review
from fulltext_review import run_fulltext_review
from publisher_year_review import run_publisher_year_review

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name
CORRECTED = {"GonzEtal19", "PeirEtal19", "WallEtal04"}
spec = importlib.util.spec_from_file_location("previous_batch", HERE.parent / "resolution-2026-09-15/run.py")
previous_batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous_batch)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        before = current_results("cdl.bib", cache)
        entries = load_entries("cdl.bib")
        path = HERE / "manifest.json"
        if not path.exists():
            with gzip.open(ROOT / "verification/review-queue.jsonl.gz", "rt") as f:
                queue = [json.loads(line) for line in f]
            selected = []
            for route in sorted({r["route"] for r in queue}):
                pool = [r for r in queue if r["route"] == route
                        and before[r["key"]]["status"] == "needs_review"
                        and not before[r["key"]].get("external_evidence")
                        and not before[r["key"]].get("discovery_review", {}).get("checked")]
                pool.sort(key=lambda r: hashlib.sha256(("followup100-v1:" + r["key"]).encode()).hexdigest())
                assert len(pool) >= 25, route
                selected += pool[:25]
            assert len(selected) == 100
            manifest = {"selection": "25 per existing queue route; deterministic SHA256 order; no prior expanded discovery or attached research evidence",
                        "entries": selected, "corrected_keys": sorted(CORRECTED)}
            path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            export_snapshot("cdl.bib", cache, WORK / "before.jsonl.gz")
        manifest = json.loads(path.read_text())
        keys = {r["key"] for r in manifest["entries"]} | CORRECTED
        for r in manifest["entries"]:
            assert entries[r["key"]]["fingerprint"] == r["fingerprint"], r["key"]
        client = previous_batch.client_for(cache)
        report = WORK / "report.jsonl"
        stages = []
        for cycle in ("run", "repeat"):
            start, calls = time.monotonic(), client.requests
            count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
            print(cycle + ": verify current entries", flush=True)
            run_verification("cdl.bib", cache, client, report, keys=keys)
            print(cycle + ": expanded title discovery", flush=True)
            run_discovery_review("cdl.bib", cache, client, report, keys=keys, limit=len(keys))
            print(cycle + ": secondary metadata", flush=True)
            run_auto_review("cdl.bib", cache, report, client, keys=keys)
            print(cycle + ": article front matter", flush=True)
            run_fulltext_review("cdl.bib", cache, client, report, keys=keys)
            print(cycle + ": publisher issue years", flush=True)
            after = run_publisher_year_review("cdl.bib", cache, client, report, keys=keys)
            assert all(after[k] == r for k, r in before.items() if r["status"] in ACCEPTED)
            stage = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                     "network_requests": client.requests - calls,
                     "added_review_records": cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] - count,
                     "batch_statuses": dict(Counter(after[r["key"]]["status"] for r in manifest["entries"])),
                     "correction_statuses": {k: after[k]["status"] for k in sorted(CORRECTED)},
                     "library_statuses": dict(Counter(r["status"] for r in after.values()))}
            print(json.dumps(stage), flush=True)
            stages.append(stage)
            if cycle == "repeat":
                assert after == first
                assert stage["network_requests"] == stage["added_review_records"] == 0
            first = after
            (HERE / "results.json").write_text(json.dumps({"stages": stages, "entries": {
                k: {"status": after[k]["status"], "accepted_doi": after[k].get("accepted_doi"),
                    "fingerprint": after[k]["fingerprint"], "issues": after[k].get("issues", [])}
                for k in sorted(keys)}}, indent=2) + "\n")
        export_snapshot("cdl.bib", cache, WORK / "after.jsonl.gz")
        print("PASS: all prior approvals preserved; repeat has zero requests and zero writes", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
