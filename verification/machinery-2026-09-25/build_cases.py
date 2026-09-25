"""Freeze the real PR #87/#88 cases the machinery tests use (no network).

The PR check (verification/pr-check-2026-09-25) ran each PR bibliography against
a scratch cache. This script copies, unmodified, each named entry and the
latest current review row for it from that scratch cache (opened read-only,
``mode=ro``) into cases.json.gz next to this file. Entries come from the
``*.fixed.bib`` runs (the ENTRY-WRONG fixes applied) unless listed in RAW.

    .venv/bin/python verification/machinery-2026-09-25/build_cases.py <scratch prcheck dir>
"""
import gzip
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
sys.path.insert(0, str(ROOT / "verification/apply-2026-09-25"))
from build_cases import ReadOnlyCache  # noqa: E402
from verification import load_entries  # noqa: E402

KEYS = {
    "pr88": ["FeliEtal98", "Schr03", "PigeEtal12", "LantEtal26", "Mann23", "Mann24", "ChenEtal21",
             "SchwEtal22", "KothEtal25", "KonkEtal21", "HeusMann18"],
    "pr87": ["Chom56", "Chom65", "Klee56", "BauEtal17", "DalaTrig05", "Sips13", "ReimGure19"],
}
RAW = {"pr88": ["KothEtal25"]}  # also keep the unfixed PR entry (no Pages field)


def main(prcheck):
    prcheck = Path(prcheck)
    cache = ReadOnlyCache(prcheck / "pr.sqlite3")
    cases = {}
    try:
        for pr, keys in KEYS.items():
            for variant in ("fixed", "raw"):
                if variant == "raw" and not RAW.get(pr):
                    continue
                bib = prcheck / (f"{pr}.fixed.bib" if variant == "fixed" else f"{pr}.bib")
                entries = load_entries(bib)
                for key in (keys if variant == "fixed" else RAW[pr]):
                    previous = cache.get(bib, entries[key])
                    if previous is None:
                        raise ValueError(f"No cached review for {key} in {bib.name}")
                    name = key if variant == "fixed" else key + ":raw"
                    cases[name] = {"pr": pr, "bib": bib.name, "entry": entries[key], "previous": previous}
    finally:
        cache.close()
    out = HERE / "cases.json.gz"
    with gzip.open(out, "wt") as f:
        json.dump({"source": f"{prcheck.name}/pr.sqlite3 (read-only scratch cache of the 2026-09-25 PR check)",
                   "cases": cases}, f, ensure_ascii=False, sort_keys=True)
    print(out, len(cases), "cases")


if __name__ == "__main__":
    main(sys.argv[1])
