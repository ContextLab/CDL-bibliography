"""Run the frozen wider sample or reassess the whole cached backlog locally."""

import argparse
from collections import Counter
import gzip
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import (
    ACCEPTED,
    Cache,
    PoliteClient,
    current_results,
    export_snapshot,
    load_entries,
    run_verification,
)
from auto_review import run_auto_review
from discovery_review import run_discovery_review
from fulltext_review import run_fulltext_review
from publisher_year_review import run_publisher_year_review

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck/resolution-2026-09-15"


def client_for(cache):
    contact = os.environ.get("CROSSREF_MAILTO")
    if not contact:
        for (body,) in cache.db.execute("SELECT body FROM responses"):
            url = urlparse(json.loads(body).get("url", ""))
            if url.hostname == "api.crossref.org":
                values = parse_qs(url.query).get("mailto", [])
                if values:
                    contact = values[0]
                    break
    return PoliteClient(cache, contact)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["wide", "publisher", "backlog"])
    parser.add_argument(
        "--publisher",
        action="store_true",
        help="Apply the tested publisher year layer to the full backlog",
    )
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        keys = (
            {
                r["key"]
                for r in json.loads((HERE / "wide50.json").read_text())["entries"]
            }
            if args.mode == "wide"
            else None
        )
        if args.mode == "publisher":
            keys = {
                r["key"]
                for r in json.loads((HERE / "wide50.json").read_text())["entries"]
            }
            keys |= {
                r["key"]
                for r in json.loads(
                    (ROOT / "verification/pilot50/manifest.json").read_text()
                )["entries"]
            }
        client = client_for(cache) if keys or args.publisher else None
        before = current_results("cdl.bib", cache)
        stages = []
        report = WORK / (args.mode + "-report.jsonl")
        for cycle in ("run", "repeat"):
            start = time.monotonic()
            requests_before = client.requests if client else 0
            review_count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[
                0
            ]
            if args.mode == "wide":
                print(cycle + ": verify current fingerprints", flush=True)
                run_verification("cdl.bib", cache, client, report, keys=keys)
                print(cycle + ": expanded discovery", flush=True)
                run_discovery_review(
                    "cdl.bib", cache, client, report, limit=50, keys=keys
                )
            print(cycle + ": reassess and secondary sources", flush=True)
            after = run_auto_review(
                "cdl.bib",
                cache,
                report,
                client if args.mode == "wide" else None,
                keys=keys,
            )
            if args.mode == "wide":
                print(cycle + ": original article XML", flush=True)
                after = run_fulltext_review("cdl.bib", cache, client, report, keys=keys)
            if args.mode in {"wide", "publisher"} or args.publisher:
                after = run_publisher_year_review(
                    "cdl.bib", cache, client, report, keys=keys
                )
            assert all(
                after[k] == old
                for k, old in before.items()
                if old["status"] in ACCEPTED
            ), "Prior approval changed"
            selected = {k: r for k, r in after.items() if keys is None or k in keys}
            stage = {
                "cycle": cycle,
                "seconds": round(time.monotonic() - start, 2),
                "network_requests": client.requests - requests_before if client else 0,
                "statuses": dict(Counter(r["status"] for r in selected.values())),
                "added_review_records": cache.db.execute(
                    "SELECT count(*) FROM reviews"
                ).fetchone()[0]
                - review_count,
            }
            print(json.dumps(stage), flush=True)
            stages.append(stage)
            if cycle == "repeat":
                assert stage["network_requests"] == 0
                assert stage["added_review_records"] == 0
                assert after == first
            first = after
        summary = {
            "mode": args.mode,
            "stages": stages,
            "changes": {
                k: {"before": before[k]["status"], "after": r["status"]}
                for k, r in after.items()
                if before[k]["status"] != r["status"]
            },
            "entries": {
                k: {
                    "fingerprint": r["fingerprint"],
                    "status": r["status"],
                    "accepted_doi": r.get("accepted_doi"),
                }
                for k, r in selected.items()
            },
        }
        (HERE / (args.mode + "-results.json")).write_text(
            json.dumps(summary, indent=2) + "\n"
        )
        if args.mode == "backlog":
            export_snapshot("cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
            entries = load_entries("cdl.bib")
            with gzip.open(ROOT / "verification/review-queue.jsonl.gz", "wt") as f:
                for k, result in sorted(after.items()):
                    if result["status"] in ACCEPTED:
                        continue
                    candidates = result.get("candidates", [])
                    best = min(
                        candidates,
                        key=lambda c: (
                            not c.get("evidence", {}).get("title", {}).get("match"),
                            not c.get("evidence", {}).get("author", {}).get("match"),
                            len(c.get("issues", [])),
                        ),
                        default={},
                    )
                    findings = best.get("issues") or result.get("issues", [])
                    route = (
                        "source_discovery"
                        if not best.get("evidence", {}).get("title", {}).get("match")
                        else "author_identity"
                        if not best.get("evidence", {}).get("author", {}).get("match")
                        else "publication_version"
                        if any(
                            "version" in s or "relationship" in s or "unambiguous" in s
                            for s in findings
                        )
                        else "field_adjudication"
                    )
                    row = {
                        "key": k,
                        "fingerprint": result["fingerprint"],
                        "policy": result["policy"],
                        "entry": entries[k]["fields"],
                        "candidate_doi": best.get("doi"),
                        "candidate_url": best.get("url"),
                        "findings": findings,
                        "route": route,
                    }
                    f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        print(
            "PASS: unchanged repeat makes no requests or reviews; prior approvals preserved",
            flush=True,
        )
    finally:
        cache.close()


if __name__ == "__main__":
    main()
