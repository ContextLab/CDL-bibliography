"""Freeze the real cached cases the stage 1 rule tests use (no network).

Reads cdl.bib and the latest current review rows from the main cache opened
read-only (``mode=ro``). Rows and entries are copied unmodified. Also copies
the author fields of the cdl.bib entries that spell J Kounios (the library
consensus behind the MeyeEtal88 regression test).

    .venv/bin/python verification/apply-2026-09-25/build_cases.py
"""
import gzip
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
os.chdir(ROOT)
from verification import Cache, load_entries  # noqa: E402

KEYS = {
    "BrodMurd77": "Crossref B B Murdock Jr; citation without suffix",
    "CalvEtal73": "Crossref A A Ward Jr + DOI-linked PubMed suffix; citation without suffix",
    "RoedKarp06a": "Crossref H L Roediger III; citation without suffix",
    "RoedKarp06b": "Crossref H L Roediger III; citation without suffix",
    "MeyeEtal88": "Crossref typo Kounois; five other cdl.bib entries spell J Kounios",
    "MarmEtal78": "Crossref gives first page 483 only; citation 483--490",
    "SimoEtal04": "Crossref gives first page 305 only; citation 305--329",
    "AndeEtal94": "Crossref completes 1063 to 1063--1087 (never blocked)",
    "DoesEtal08": "Kitaj -> Kitajo, stated by Crossref and the DOI-linked PubMed record",
    "CleeMcCl91": "McCleeland -> McClelland; other cdl.bib entries spell J L McClelland",
    "MartJohn15": "Johnson -> Johnston from Crossref alone, no corroboration",
}


class ReadOnlyCache(Cache):
    def __init__(self, filename):
        self.path = Path(filename)
        self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)

    def store(self, *args, **kwargs):
        return True

    def put(self, bibliography, entry, result):
        return self.retain_notices(entry, result)

    def remember_notices(self, candidates):
        return None


def main(extra=()):
    entries = load_entries(ROOT / "cdl.bib")
    cache = ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
    cases = {}
    try:
        for key, why in list(KEYS.items()) + [(k, "catalogue publisher variant") for k in extra]:
            cases[key] = {"why": why, "entry": entries[key], "previous": cache.get(ROOT / "cdl.bib", entries[key])}
    finally:
        cache.close()
    library = {k: {"author": e["fields"].get("author")} for k, e in entries.items()
               if any(s in (e["fields"].get("author") or "") for s in ("Kounios", "McClelland", "McCleeland",
                                                                       "Kitajo", "Johnston", "Johnson"))}
    out = ROOT / "verification/apply-2026-09-25/cases.json.gz"
    with gzip.open(out, "wt") as f:
        json.dump({"source": "cdl.bib + .bibcheck/verification.sqlite3 (read-only), 2026-09-25",
                   "cases": cases, "library_authors": library}, f, ensure_ascii=False, sort_keys=True)
    print(out, len(cases), "cases,", len(library), "library bylines")


if __name__ == "__main__":
    main(sys.argv[1:])
