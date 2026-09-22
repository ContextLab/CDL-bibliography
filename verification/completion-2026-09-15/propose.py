"""Freeze new paired-source correction candidates for documentary review."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from correction_proposals import field_proposal, pagination_proposal, publication_proposal
from verification import Cache, current_results, load_entries

HERE = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True)
    args = parser.parse_args()
    if not args.batch.isalnum():
        parser.error("Use an alphanumeric batch name")
    target = HERE / f"{args.batch}-proposals-initial.json"
    if target.exists():
        parser.error("Frozen batch already exists; choose a new batch name")
    held = set()
    for path in HERE.glob("*audit-exclusions.json"):
        data = json.loads(path.read_text())
        held.update(data if isinstance(data, dict) else (p["key"] for p in data))
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        entries = load_entries(ROOT / "cdl.bib")
        results = current_results(ROOT / "cdl.bib", cache, entries)
        proposals = []
        for key, row in results.items():
            if key in held or row["status"] != "needs_review" or row.get("external_evidence"):
                continue
            entry = entries[key]
            if entry["fields"].get("ENTRYTYPE") != "article":
                continue
            options = []
            for field in ("title", "author", "journal", "year", "volume", "number", "doi"):
                proposal = field_proposal(entry, row, field)
                if proposal:
                    options.append(proposal)
            proposal = pagination_proposal(entry, row)
            if proposal:
                options.append(proposal)
            if not options:
                proposal = publication_proposal(entry, row, include_identity_fields=True)
                if proposal:
                    options.append(proposal)
            if len(options) == 1:
                proposals.append(options[0])
                print(json.dumps({k: options[0][k] for k in ("key", "kind", "doi", "changes")}, ensure_ascii=False), flush=True)
        target.write_text(json.dumps(proposals, indent=2) + "\n")
        print(json.dumps({"proposals": len(proposals), "kinds": dict(Counter(p["kind"] for p in proposals)), "held_keys": len(held)}), flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
