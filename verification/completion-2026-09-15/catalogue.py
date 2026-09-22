"""Freeze and collect unresolved book editions without approving citations."""
import argparse
import gzip
import json
import importlib.util
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from catalogue_discovery import fetch_search, search_query
from verification import Cache, PoliteClient, load_entries, run_lock

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name
spec = importlib.util.spec_from_file_location("earlier", HERE.parent / "resolution-2026-09-15/run.py")
earlier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(earlier)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--year", action="store_true", help="Discover editions in the explicitly cited year")
    parser.add_argument("--fold-diacritics", action="store_true", help="Omit combining accents in discovery queries only")
    parser.add_argument("--keys", nargs="+", help="Freeze these unresolved book entries")
    args = parser.parse_args()
    if not args.batch.isalnum() or not 1 <= args.limit <= 200:
        parser.error("Use an alphanumeric batch and limit from 1 to 200")
    # Separate response cache permits source collection alongside article work.
    cache = Cache(WORK / "catalogue.sqlite3")
    try:
        with run_lock(cache):
            entries = load_entries(ROOT / "cdl.bib")
            path = HERE / f"catalogue-{args.batch}-manifest.json"
            if not path.exists():
                with gzip.open(ROOT / "verification/review-queue.jsonl.gz", "rt") as stream:
                    unresolved = {r["key"] for r in map(json.loads, stream)}
                prior = {p["key"] for f in HERE.glob("catalogue-*-manifest.json") for p in json.loads(f.read_text())}
                pool = unresolved if args.year or args.keys else unresolved - prior
                if args.keys:
                    assert set(args.keys) <= pool
                    pool &= set(args.keys)
                keys = sorted(k for k in pool if entries[k]["fields"].get("ENTRYTYPE") == "book"
                              and entries[k]["fields"].get("author"))[:args.limit]
                rows = [{"key": k, "fingerprint": entries[k]["fingerprint"], "query": search_query(entries[k]["fields"], include_year=args.year, fold_diacritics=args.fold_diacritics)} for k in keys]
                path.write_text(json.dumps(rows, indent=2) + "\n")
            selected = json.loads(path.read_text())
            assert all(entries[p["key"]]["fingerprint"] == p["fingerprint"] for p in selected)
            assert all(search_query(entries[p["key"]]["fields"], include_year=args.year, fold_diacritics=args.fold_diacritics) == p['query'] for p in selected)
            # Reuse the configured provider contact without changing the main
            # cache or exposing its value in collection artifacts.
            connection = sqlite3.connect(f"file:{ROOT / '.bibcheck/verification.sqlite3'}?mode=ro", uri=True)
            try:
                configured = earlier.client_for(SimpleNamespace(db=connection))
                client = PoliteClient(cache, configured.mailto, interval=3.1)
            finally:
                connection.close()
            summaries = []
            for cycle in ("run", "repeat"):
                start, calls = time.monotonic(), client.requests
                results = []
                for item in selected:
                    source = fetch_search(cache, client, entries[item["key"]]["fields"], include_year=args.year, fold_diacritics=args.fold_diacritics)
                    results.append(dict(item, source=source))
                    (HERE / f"catalogue-{args.batch}-sources.json").write_text(json.dumps(results, indent=2) + "\n")
                    print(f"{cycle} {item['key']}: {source['total_records']} records; truncated={source['truncated']}", flush=True)
                summary = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                           "network_requests": client.requests - calls, "entries": len(results)}
                if cycle == "repeat":
                    assert results == first and summary["network_requests"] == 0
                first = results
                summaries.append(summary)
                (HERE / f"catalogue-{args.batch}-results.json").write_text(json.dumps(summaries, indent=2) + "\n")
                print(json.dumps(summary), flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
