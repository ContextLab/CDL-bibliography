"""Collect a frozen PMC front-matter batch and verify cache reuse locally."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from auto_review import select_result
from fulltext_review import assess_fulltext
from pmc_metadata import article_front, fetch_front
from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock
from reassess import export_queue

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name
METADATA_POLICY = "2"
spec = importlib.util.spec_from_file_location("earlier", HERE.parent / "resolution-2026-09-15/run.py")
earlier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(earlier)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--keys", nargs="+")
    args = parser.parse_args()
    if not args.batch.isalnum() or not 1 <= args.limit <= 500:
        parser.error("Use an alphanumeric batch and a limit from 1 to 500")
    # This runner is for an ongoing bulk backfill. Respect PMC's weekday
    # off-peak guidance across batches, rather than evading it with small slices.
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        with run_lock(cache):
            entries = load_entries(ROOT / "cdl.bib")
            before = current_results(ROOT / "cdl.bib", cache, entries)
            path = HERE / f"pmc-metadata-{args.batch}-manifest.json"
            if not path.exists():
                pool = []
                for key, row in before.items():
                    if (row["status"] != "needs_review" or row.get("external_evidence")
                            or (args.keys and key not in args.keys)):
                        continue
                    checkpoint = row.get("auto_review", {})
                    checked = set(checkpoint.get("pmc_metadata_checked", [])) if checkpoint.get("pmc_metadata_policy") == METADATA_POLICY else set()
                    for c in row.get("candidates", []):
                        raw = c.get("raw_record", {})
                        pmcid = raw.get("pmcid")
                        if (c.get("source") != "europepmc" or not pmcid or pmcid in checked
                                or not any(p.get("source") == "crossref" and p.get("doi") == c["doi"] for p in row["candidates"])):
                            continue
                        item = {"key": key, "fingerprint": entries[key]["fingerprint"], "pmcid": pmcid, "doi": c["doi"]}
                        if item not in pool:
                            pool.append(item)
                pool = sorted(pool, key=lambda p: (p["key"], p["pmcid"]))[:args.limit]
                path.write_text(json.dumps(pool, indent=2) + "\n")
            selected = json.loads(path.read_text())
            assert all(entries[p["key"]]["fingerprint"] == p["fingerprint"] for p in selected)
            backup = WORK / f"before-pmc-metadata-{args.batch}.jsonl.gz"
            if not backup.exists():
                export_snapshot(ROOT / "cdl.bib", cache, backup)
            client = earlier.client_for(cache)
            summaries = []
            for cycle in ("run", "repeat"):
                start, calls = time.monotonic(), client.requests
                writes = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
                for item in selected:
                    key, pmcid = item["key"], item["pmcid"]
                    row = cache.get(ROOT / "cdl.bib", entries[key])
                    checkpoint = row.get("auto_review", {})
                    checked = set(checkpoint.get("pmc_metadata_checked", [])) if checkpoint.get("pmc_metadata_policy") == METADATA_POLICY else set()
                    if pmcid in checked or row["status"] in ACCEPTED:
                        continue
                    # Reuse the successful, hash-checked discovery probes.
                    receipt = WORK / f"pmc-front-{pmcid}.json"
                    if receipt.exists() and cache.response("pmc-front-v1:" + pmcid, 30 * 86400) is None:
                        saved = json.loads(receipt.read_text())
                        if saved["status"] == 200:
                            body = (WORK / f"pmc-front-{pmcid}.xml").read_bytes()
                            assert hashlib.sha256(body).hexdigest() == saved["sha256"]
                            cache.save_response("pmc-front-v1:" + pmcid, {"body": body.decode("utf-8"),
                                "http_status": 200, "url": saved["url"], "retrieved_at": saved["retrieved_at"],
                                "document_sha256": saved["sha256"]})
                    if cache.response("pmc-front-v1:" + pmcid, 30 * 86400) is None:
                        eastern = datetime.now(ZoneInfo("America/New_York"))
                        if eastern.weekday() < 5 and 5 <= eastern.hour < 21:
                            raise RuntimeError("Bulk PMC requests require weekday hours outside 5 AM–9 PM US Eastern")
                    response = fetch_front(cache, client, pmcid)
                    primary = next(c for c in row["candidates"] if c.get("source") == "crossref" and c["doi"] == item["doi"])
                    med = next(c["raw_record"] for c in row["candidates"] if c.get("source") == "europepmc"
                               and c["doi"] == item["doi"] and c["raw_record"].get("pmcid") == pmcid)
                    candidates = list(row["candidates"])
                    if response["body"]:
                        front = article_front(response["body"], pmcid, item["doi"], med["id"])
                        candidates.append(assess_fulltext(entries[key]["fields"], primary, med, dict(response, body=front)))
                    attempts = list(row.get("attempts", [])) + [{"source": "pmc-oai", "url": response["url"],
                        "http_status": response["http_status"]}]
                    result = select_result(entries[key]["fields"], candidates, attempts) if response["body"] else dict(row, attempts=attempts)
                    for name in ("discovery_review", "research_attempt", "external_evidence"):
                        if name in row:
                            result[name] = row[name]
                    checked.add(pmcid)
                    result["auto_review"] = dict(row.get("auto_review", {}), pmc_metadata_checked=sorted(checked), pmc_metadata_policy=METADATA_POLICY)
                    cache.put(ROOT / "cdl.bib", entries[key], result)
                    print(f"{cycle}: {key} {pmcid}: {result['status']}", flush=True)
                after = current_results(ROOT / "cdl.bib", cache, entries)
                for key, old in before.items():
                    if old["status"] in ACCEPTED:
                        assert after[key] == old, key
                        assert cache.retain_notices(entries[key], old)["status"] in ACCEPTED, key
                summary = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                    "network_requests": client.requests - calls,
                    "review_writes": cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] - writes,
                    "statuses": dict(Counter(r["status"] for r in after.values()))}
                if cycle == "repeat":
                    assert after == first and summary["network_requests"] == summary["review_writes"] == 0
                first = after
                summaries.append(summary)
                print(json.dumps(summary), flush=True)
            export_snapshot(ROOT / "cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
            export_queue(entries, after)
            (HERE / f"pmc-metadata-{args.batch}-results.json").write_text(json.dumps(summaries, indent=2) + "\n")
    finally:
        cache.close()


if __name__ == "__main__":
    main()
