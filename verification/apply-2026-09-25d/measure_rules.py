"""Offline, read-only: does the stage 2B-ii (2026-09-25) comparator code change any saved decision?

Opens the main cache read-only (no writes, no network) and re-runs
``auto_review.reassess`` with the current code on every current result. Reports
entries whose status would change (lost: verified -> not; newly: needs_review ->
verified) and any errors. Writes measure-<label>.json next to this file.

    .venv/bin/python verification/apply-2026-09-25d/measure_rules.py LABEL
"""
from collections import Counter
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, os.environ.get("BIBCHECK_DIR", str(ROOT / "bibcheck")))
sys.path.insert(0, str(ROOT / "verification/apply-2026-09-25"))
os.chdir(ROOT)
import verification  # noqa: E402,F401  (from BIBCHECK_DIR before build_cases adds ROOT/bibcheck)
from build_cases import ReadOnlyCache  # noqa: E402
sys.path.insert(0, os.environ.get("BIBCHECK_DIR", str(ROOT / "bibcheck")))
import auto_review  # noqa: E402
from verification import ACCEPTED, current_results, load_entries  # noqa: E402
import osf_review, datacite_review, acl_review, sfn_abstracts  # noqa: E402,F401  (route validators)


def main():
    label = sys.argv[1]
    entries = load_entries(ROOT / "cdl.bib")
    cache = ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        results = current_results(ROOT / "cdl.bib", cache, entries)
    finally:
        cache.close()
    lost, newly, errors = {}, {}, {}
    for key, previous in results.items():
        try:
            after = auto_review.reassess(entries[key], previous)
        except Exception as exc:  # reported per key, never skipped silently
            errors[key] = f"{type(exc).__name__}: {exc}"
            continue
        if previous["status"] in ACCEPTED and after["status"] not in ACCEPTED:
            lost[key] = {"source": previous.get("accepted_source"), "issues": after.get("issues", [])[:3]}
        elif previous["status"] not in ACCEPTED and after["status"] in ACCEPTED:
            newly[key] = {"source": after.get("accepted_source")}
    out = {"statuses": dict(Counter(r["status"] for r in results.values())), "lost": lost,
           "newly_verifiable": newly, "errors": errors}
    (HERE / f"measure-{label}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(verification.__file__)
    print(json.dumps({"statuses": out["statuses"], "lost": sorted(lost), "newly": sorted(newly),
                      "errors": len(errors)}))


if __name__ == "__main__":
    main()
