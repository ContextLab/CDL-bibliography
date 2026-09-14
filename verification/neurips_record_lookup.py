"""Identify the NeurIPS proceedings record for a 2017 paper hash.

Diagnostic only. It writes nothing to the bibliography, the verification
database or the HTTP cache, and records no approval.

Crossref holds no DOI for NeurIPS proceedings papers before 2019, so the
publisher's own proceedings record is the authority for series title, volume
and pagination. Requests here do NOT carry a `mailto` and therefore do not use
the Crossref polite pool; this was an explicit instruction for a bounded one-off
lookup, and it is deliberately not wired into `PoliteClient`, which still
requires a real contact for all bulk verification traffic.

    python verification/neurips_record_lookup.py 3f5ee243547dee91fbd053c1c4a845aa

Compare the printed fields against the citation by hand. A publisher record is
documentary evidence, not a human review.
"""

import json
import sys
import time

import requests

BASE = "https://papers.nips.cc/paper_files/paper"
AGENT = "bibcheck-diagnostic/1.0 (one-off record identification)"
FIELDS = ("title", "book", "page_first", "page_last")


def fetch(session, url):
    response = session.get(url, timeout=30)
    print(f"HTTP {response.status_code}  {url}", file=sys.stderr)
    response.raise_for_status()
    return response


def lookup(paper_hash, year=2017, pause=1.0):
    session = requests.Session()
    session.headers.update({"User-Agent": AGENT})
    stem = f"{BASE}/{year}/file/{paper_hash}"
    bibtex = fetch(session, f"{stem}-Bibtex.bib").text
    time.sleep(pause)
    metadata = fetch(session, f"{stem}-Metadata.json").json()
    return bibtex, {k: metadata.get(k) for k in FIELDS}


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: neurips_record_lookup.py <paper-hash> [year]")
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2017
    bibtex, metadata = lookup(sys.argv[1], year)
    print(bibtex.strip())
    print(json.dumps(metadata, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
