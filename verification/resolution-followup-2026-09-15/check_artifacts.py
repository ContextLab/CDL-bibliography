"""Compare hand-recorded source observations and restore the complete baseline."""

from collections import Counter
import gzip
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import Cache, current_results, import_snapshot, normalized, normalize_pages

HERE = Path(__file__).parent


def main():
    with gzip.open(ROOT / "verification/baseline.jsonl.gz", "rt") as f:
        rows = {r["key"]: r for r in map(json.loads, f) if "key" in r}
    comparisons = []
    for correction in json.loads((HERE / "corrections.json").read_text()):
        expected = correction["manual_expected"]
        r = rows[correction["key"]]
        assert r["status"] == "metadata_verified"
        good = [c for c in r["candidates"] if c.get("doi") and c.get("evidence") and not c.get("issues")]
        assert {c["doi"].lower() for c in good} == {expected["doi"].lower()}
        c = good[0]
        record = c["record"]
        # Independent manual expectations were recorded from the source before
        # inspecting the successful automated result. Initial signatures preserve
        # the complete byline's order and every middle initial.
        authors = [" ".join([*[part[0].upper() for part in p["given"].replace(".", " ").split()],
                             p["family"]]) for p in record["author"]]
        checks = {
            "doi": c["doi"].lower() == expected["doi"].lower(),
            "title": normalized(record["title"][0]) == normalized(expected["title"]),
            "year": str(record["published"]["date-parts"][0][0]) == expected["year"],
            "volume": record["volume"] == expected["volume"],
            "pages": normalize_pages(record["page"]) == normalize_pages(expected["pages"]),
            "ordered_authors": authors == expected["authors"],
        }
        assert all(checks.values()), (correction["key"], checks, authors)
        comparisons.append({"key": correction["key"], "checks": checks,
                            "source_url": correction["source_url"]})
    assert rows["Samm69"]["status"] == "needs_review"
    assert rows["Samm69"]["external_evidence"]
    with TemporaryDirectory(prefix="bibcheck-followup-restore-") as work:
        restored = Cache(Path(work) / "fresh.sqlite3")
        try:
            import_snapshot("cdl.bib", restored, ROOT / "verification/baseline.jsonl.gz")
            actual = current_results("cdl.bib", restored)
            assert len(actual) == len(rows) == 6422
            for key, expected in rows.items():
                for field in ("status", "fingerprint", "checked_at", "accepted_doi", "external_evidence"):
                    assert actual[key].get(field) == expected.get(field), (key, field)
            assert restored.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            restored.close()
    result = {"manual_comparisons": comparisons, "full_baseline_restore": "pass",
              "restored_entries": len(rows), "statuses": dict(Counter(r["status"] for r in rows.values())),
              "sammon_conflict_hold_restored": True}
    (HERE / "artifact-checks.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
