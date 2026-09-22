"""List source-backed correction candidates; never edit entries or cache reviews."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
import correction_proposals as cp
from pmc_corrections import pmc_coordinate_proposal, pmc_publisher_proposal
from verification import Cache, current_results, load_entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if ROOT / ".bibcheck" not in args.output.resolve().parents:
        parser.error("Keep unaudited proposals in the ignored .bibcheck directory")
    keys = json.loads(args.manifest.read_text())["entries"]
    entries = load_entries(ROOT / "cdl.bib")
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        results = current_results(ROOT / "cdl.bib", cache, entries)
        holds = {}
        for path in Path(__file__).parent.glob("*audit-exclusions.json"):
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                holds.update(data)
        generators = [cp.pagination_proposal, cp.coordinate_proposal,
                      cp.publication_proposal, cp.suffix_proposal, cp.issue_year_proposal,
                      cp.journal_history_proposal, pmc_publisher_proposal, pmc_coordinate_proposal,
                      lambda e, r: pmc_coordinate_proposal(e, r, include_authors=True),
                      lambda e, r: cp.publication_proposal(e, r, include_identity_fields=True)]
        generators += [lambda e, r, f=f: cp.field_proposal(e, r, f)
                       for f in ("title", "volume", "number", "year", "doi", "author", "journal")]
        proposals = []
        for key in keys:
            entry, result = entries[key], results[key]
            if result["status"] != "needs_review":
                continue
            if entry["fingerprint"] != keys[key]:
                raise ValueError(f"Unresolved entry changed after the frozen manifest: {key}")
            seen = set()
            for generate in generators:
                p = generate(entry, result)
                if p and json.dumps(p["changes"], sort_keys=True) not in seen:
                    seen.add(json.dumps(p["changes"], sort_keys=True))
                    proposals.append(p)
                    print(json.dumps({"key": key, "kind": p["kind"], "changes": p["changes"],
                                      "prior_hold": holds.get(key)}, ensure_ascii=False), flush=True)
        args.output.write_text(json.dumps(proposals, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({"candidates": len(proposals), "keys": len({p["key"] for p in proposals})}), flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
