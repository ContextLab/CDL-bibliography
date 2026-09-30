"""Freeze the real records the stage 2B-ii (2026-09-25) machinery tests use (cases.json.gz).

Read-only: the cdl.bib entries and their saved review rows from
verification/baseline.jsonl.gz (commit 89c5b70) - Crossref records for the ordinal and
proceedings-name rules, LoC MARCXML for the publisher-initials rule.

    .venv/bin/python verification/apply-2026-09-25d/build_cases.py
"""
import gzip
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import load_entries  # noqa: E402

CROSSREF = {"NguyEtal18": "10.1145/3210240.3210322", "TianEtal16a": "10.1145/2973750.2973772",
            "CarvEtal22a": "10.1109/comsnets53615.2022.9668473", "AltmSchu02": "10.4324/9781315782379-49"}
CATALOGUE = ("Marr82", "MeltMart72")


def main():
    entries = load_entries(ROOT / "cdl.bib")
    rows = {}
    with gzip.open(ROOT / "verification/baseline.jsonl.gz", "rt") as f:
        next(f)
        for line in f:
            r = json.loads(line)
            if r["key"] in CROSSREF or r["key"] in CATALOGUE:
                rows[r["key"]] = r
    cases = {}
    for key, doi in CROSSREF.items():
        record = next(c["record"] for c in rows[key]["candidates"]
                      if c.get("source") == "crossref" and c.get("doi", "").lower() == doi)
        cases[key] = {"fields": entries[key]["fields"], "status": rows[key]["status"], "record": record}
    for key in CATALOGUE:
        # the accepted LoC edition: the catalogue candidate whose evidence matched every field
        review = next(c for c in rows[key]["candidates"] if c.get("raw_marcxml") and not c.get("issues")
                      and c.get("evidence", {}).get("publisher", {}).get("match"))
        cases[key] = {"fields": entries[key]["fields"], "status": rows[key]["status"],
                      "raw_marcxml": review["raw_marcxml"], "evidence": review["evidence"]}
    with gzip.open(HERE / "cases.json.gz", "wt") as f:
        json.dump({"source": "verification/baseline.jsonl.gz at 89c5b70", "cases": cases}, f, ensure_ascii=False)
    print({k: v["status"] for k, v in cases.items()})


if __name__ == "__main__":
    main()
