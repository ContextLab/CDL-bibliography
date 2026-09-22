"""Compare recorded assistant checks with actual automated source findings."""

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import normalized, normalize_pages, normalize_doi

HERE = Path(__file__).parent


def main():
    manual = json.loads((HERE / "manual-wide-audit.json").read_text())
    with (ROOT / ".bibcheck/resolution-2026-09-15/wide-report.jsonl").open() as f:
        reports = {r["key"]: r for r in map(json.loads, f)}
    outcomes = []
    for row in manual["entries"]:
        result = reports[row["key"]]
        assert result["status"] == "metadata_verified", row["key"]
        candidate = next(
            c
            for c in result["candidates"]
            if c.get("source") == result.get("accepted_source", "crossref")
            and normalize_doi(c["doi"]) == normalize_doi(row["doi"])
            and not c["issues"]
        )
        evidence = candidate["evidence"]
        people = evidence["author"]["source"]
        signature = ";".join(
            p["family"]
            + ","
            + "".join(
                w[0] for w in re.split(r"[.\s-]+", p.get("given", "")) if w
            ).upper()
            for p in people
        )
        findings = {
            "authors": normalized(signature) == normalized(row["authors"]),
            "year": row["year"] in evidence["year"]["source"],
            "volume": row["volume"] in evidence["volume"]["source"],
            "number": row["number"] == candidate["record"]["issue"],
            "pages": any(
                normalize_pages(row["pages"]) == normalize_pages(v)
                for v in evidence["pages"]["source"]
            ),
            "doi": normalize_doi(row["doi"]) == normalize_doi(candidate["doi"]),
        }
        outcomes.append(
            {
                "key": row["key"],
                "checks": findings,
                "all_match": all(findings.values()),
                "automated_author_signature": signature,
                "automated_source": candidate["source"],
                "manual_source": row["source"],
            }
        )
    summary = {
        "entries": len(outcomes),
        "matching": sum(r["all_match"] for r in outcomes),
        "outcomes": outcomes,
    }
    (HERE / "manual-comparison.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "outcomes"}))
    assert all(r["all_match"] for r in outcomes), [
        r for r in outcomes if not r["all_match"]
    ]


if __name__ == "__main__":
    main()
