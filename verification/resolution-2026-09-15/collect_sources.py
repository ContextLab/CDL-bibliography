"""Cache primary HTML metadata, including failures; never grant approvals.

Usage: collect_sources.py [--retry-errors] [--offline]
Source bodies stay ignored locally. URL/hash/metadata/outcomes are portable.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from publisher_metadata import PublisherMetadata
from search_tools import get_source
from verification import normalize_doi, now
from publisher_year_review import FIELDS

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck/resolution-2026-09-15/sources"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((HERE / "source-urls.json").read_text())
    hosts = {urlparse(r["url"]).hostname for r in manifest} | {
        "link.springernature.com",
        "www.nature.com",
    }
    session = requests.Session()
    calls, results = 0, []
    for row in manifest:
        identity = hashlib.sha256(
            ("publisher-head-v1:" + row["url"]).encode()
        ).hexdigest()
        path = WORK / (identity + ".json")
        result = json.loads(path.read_text()) if path.exists() else None
        if result is None or (args.retry_errors and result["status"] == "unavailable"):
            if args.offline:
                raise SystemExit("No cached source outcome for " + row["key"])
            calls += 1
            try:
                html, final = get_source(session, row["url"], hosts)
                head = PublisherMetadata()
                head.feed(html)
                metadata = {
                    k: v for k, v in head.source_metadata().items() if k in FIELDS
                }
                sha = hashlib.sha256(html.encode()).hexdigest()
                (WORK / (sha + ".html")).write_text(html)
                # HTTP 200 with no metadata is a collection gap, not success.
                result = {
                    "status": "metadata_retrieved"
                    if metadata
                    else "missing_citation_metadata",
                    "url": final,
                    "retrieved_at": now(),
                    "sha256": sha,
                    "metadata": metadata,
                }
            except (ValueError, requests.RequestException) as exc:
                # Do not turn a sandbox DNS failure into a durable source result.
                if isinstance(exc, requests.ConnectionError):
                    raise
                result = {
                    "status": "unavailable",
                    "url": row["url"],
                    "retrieved_at": now(),
                    "error": str(exc),
                }
            path.write_text(json.dumps(result, indent=2) + "\n")
        result = dict(result, key=row["key"], expected_doi=row["doi"])
        if "metadata" in result:
            result["metadata"] = {
                k: v for k, v in result["metadata"].items() if k in FIELDS
            }
        dois = result.get("metadata", {}).get("citation_doi", [])
        try:
            result["doi_matches"] = bool(dois) and {normalize_doi(d) for d in dois} == {
                normalize_doi(row["doi"])
            }
        except ValueError:
            result["doi_matches"] = False
        results.append(result)
        print(
            row["key"],
            result["status"],
            "DOI match:",
            result["doi_matches"],
            flush=True,
        )
    (HERE / "source-results.json").write_text(json.dumps(results, indent=2) + "\n")
    print("New source fetches:", calls, flush=True)


if __name__ == "__main__":
    main()
