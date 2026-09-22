"""Collect a bounded publisher-title pilot; propose corrections without editing."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from correction_proposals import source_authors, source_title
from publisher_corrections import eligible, fetch_elsevier_metadata, fetch_publisher_head, publisher_field_proposal
from verification import Cache, ProviderError, current_results, load_entries, run_lock

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name
spec = importlib.util.spec_from_file_location("earlier", HERE.parent / "resolution-2026-09-15/run.py")
earlier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(earlier)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--batch", default="001")
    parser.add_argument("--source", choices=["html", "elsevier"], default="html")
    parser.add_argument("--field", choices=["title", "author"], default="title")
    parser.add_argument("--doi-prefix", action="append", default=[])
    args = parser.parse_args()
    if not 1 <= args.limit <= 100 or not args.batch.isalnum():
        parser.error("Use a limit from 1 to 100 and an alphanumeric batch name")
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        with run_lock(cache):
            entries = load_entries("cdl.bib")
            before = current_results("cdl.bib", cache, entries)
            manifest = HERE / f"publisher-titles-{args.batch}-manifest.json"
            if not manifest.exists():
                pool = []
                for k, row in before.items():
                    if row["status"] != "needs_review" or row.get("external_evidence"):
                        continue
                    dois = set()
                    for primary in row.get("candidates", []):
                        if not eligible(primary, args.field):
                            continue
                        if args.source == "elsevier" and not primary["doi"].startswith(("10.1016/", "10.1006/")):
                            continue
                        if args.doi_prefix and primary["doi"].split("/")[0] not in args.doi_prefix:
                            continue
                        try:
                            values = primary["evidence"]["title"]["source"]
                            if len(values) != 1:
                                continue
                            if args.field == "title":
                                source_title(values[0], entries[k]["fields"]["title"])
                            else:
                                source_authors(primary["record"])
                        except (ValueError, KeyError, TypeError):
                            continue
                        dois.add(primary["doi"])
                    if len(dois) == 1:
                        pool.append({"key": k, "fingerprint": entries[k]["fingerprint"], "doi": next(iter(dois)), "field": args.field})
                    if len(pool) == args.limit:
                        break
                manifest.write_text(json.dumps(pool, indent=2) + "\n")
            selected = json.loads(manifest.read_text())
            assert all(entries[p["key"]]["fingerprint"] == p["fingerprint"] for p in selected)
            assert all(p.get("field", "title") == args.field for p in selected)
            client = earlier.client_for(cache)
            summaries = []
            for cycle in ("run", "repeat"):
                start, calls = time.monotonic(), client.requests
                writes = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
                results, proposals = [], []
                for i, item in enumerate(selected, 1):
                    fetch = fetch_elsevier_metadata if args.source == "elsevier" else fetch_publisher_head
                    try:
                        head = fetch(cache, client, item["doi"])
                    except ProviderError as exc:
                        failure = {"cycle": cycle, "status": "incomplete", "key": item["key"],
                                   "completed_entries": len(results), "error": str(exc),
                                   "network_requests": client.requests - calls}
                        (HERE / f"publisher-titles-{args.batch}-failure.json").write_text(json.dumps(failure, indent=2) + "\n")
                        print(json.dumps(failure), flush=True)
                        raise
                    proposal = publisher_field_proposal(entries[item["key"]], before[item["key"]], head, args.field)
                    results.append(dict(item, source=head, proposed=bool(proposal)))
                    if proposal:
                        proposals.append(proposal)
                    (HERE / f"publisher-titles-{args.batch}-sources.json").write_text(json.dumps(results, indent=2) + "\n")
                    (HERE / f"publisher-titles-{args.batch}-proposals.json").write_text(json.dumps(proposals, indent=2) + "\n")
                    print(f"{cycle} {i}/{len(selected)} {item['key']}: " + ("proposal" if proposal else head.get("error", "insufficient or conflicting head metadata")), flush=True)
                report = {"cycle": cycle, "seconds": round(time.monotonic()-start, 2), "network_requests": client.requests-calls,
                          "review_writes": cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]-writes,
                          "proposals": len(proposals), "entries": len(selected)}
                assert report["review_writes"] == 0
                if cycle == "repeat":
                    assert results == first and report["network_requests"] == 0
                first = results
                summaries.append(report)
                print(json.dumps(report), flush=True)
                (HERE / f"publisher-titles-{args.batch}-results.json").write_text(json.dumps(summaries, indent=2) + "\n")
    finally:
        cache.close()


if __name__ == "__main__":
    main()
