"""Offline, read-only: what do the 2026-09-25 machinery fixes change in cdl.bib?

Opens the main cache with ``mode=ro`` (no writes, no network) and re-runs
``auto_review.reassess`` with the current code on EVERY current result:

* newly verifiable: needs_review now, metadata_verified after reassess, with
  no BibTeX edit. Each is attributed to the rule(s) it depends on by
  switching one rule off at a time and re-checking (``rules`` lists every
  rule whose removal makes it fail again; empty means no single rule
  alone explains it);
* lost: metadata_verified now but not after reassess (must be empty);
* errors: any exception while reassessing, reported by key (never skipped).

It also counts the missing-DOI advisories (verification.result_advisories)
on the currently verified entries and on the newly verifiable ones.

Writes newly-verifiable.json next to this file.

    .venv/bin/python verification/machinery-2026-09-25/measure.py
"""
from collections import Counter
import json
import os
from pathlib import Path
import sys
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
sys.path.insert(0, str(ROOT / "verification/apply-2026-09-25"))
os.chdir(ROOT)
from build_cases import ReadOnlyCache  # noqa: E402
import auto_review  # noqa: E402
import catalogue_review  # noqa: E402
import fulltext_review  # noqa: E402
import verification  # noqa: E402
from verification import ACCEPTED, current_results, load_entries, result_advisories  # noqa: E402

_edition = catalogue_review.normalized_edition


def _old_edition(value):
    if "\\textsuperscript" in str(value):
        raise ValueError("Unknown LaTeX command needs source review")
    return _edition(value)


def _old_blocking(raw):
    links = (raw.get("commentCorrectionList") or {}).get("commentCorrection") or []
    if isinstance(links, list) and any(isinstance(l, dict) and l.get("type") == "Preprint in" for l in links):
        return True
    return _blocking(raw)


_blocking = auto_review.blocking_pubmed_relationships

# rule name -> [(module, attribute, switched-off value)]
SWITCHES = {
    "degree-suffix": [(verification, "source_name_suffix", lambda s: s or ""),
                      (auto_review, "source_name_suffix", lambda s: s or "")],
    "issue-numeric": [(verification, "normalize_issue", verification.normalized)],
    "journal-history": [(verification, "journal_history_match", lambda f, r: None)],
    "venue-variant": [(verification, "venue_variant_match", lambda f, r, x: None)],
    "book-series-number": [(verification, "book_title_forms", lambda s: s)],
    "repeated-byline": [(verification, "collapse_repeated_byline", lambda p: (p, None))],
    "leading-the": [(verification, "registry_journal_match", lambda l, r: False)],
    "pubmed-preprint-link": [(auto_review, "blocking_pubmed_relationships", lambda raw: _old_blocking(raw)),
                             (fulltext_review, "blocking_pubmed_relationships", lambda raw: _old_blocking(raw))],
    "surname-typo": [(auto_review, "registry_surname_typo", lambda *a: None)],
    "house-edition": [(catalogue_review, "normalized_edition", _old_edition)],
    "dotted-acronym": [(catalogue_review, "collapse_dotted_acronyms", lambda s: s or "")],
    "same-firm": [(catalogue_review, "publisher_same_firm", lambda a, b: False)],
}


def verifies(entry, previous):
    return auto_review.reassess(entry, previous)["status"] in ACCEPTED


def attribute(entry, previous):
    rules = []
    for name, patches in SWITCHES.items():
        saved = [(module, attr, getattr(module, attr)) for module, attr, _ in patches]
        try:
            for module, attr, off in patches:
                setattr(module, attr, off)
            if not verifies(entry, previous):
                rules.append(name)
        finally:
            for module, attr, value in saved:
                setattr(module, attr, value)
    return rules


def main():
    entries = load_entries(ROOT / "cdl.bib")
    cache = ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        results = current_results(ROOT / "cdl.bib", cache, entries)
    finally:
        cache.close()
    newly, lost, errors, advisories_now = {}, [], {}, {}
    for key, previous in results.items():
        if previous["status"] in ACCEPTED:
            notes = result_advisories(entries[key]["fields"], previous)
            if notes:
                advisories_now[key] = notes
        if previous["status"] not in {"needs_review", "metadata_verified"}:
            continue
        try:
            after = auto_review.reassess(entries[key], previous)
        except Exception as exc:  # reported per key below, never skipped silently
            errors[key] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
            continue
        if previous["status"] == "needs_review" and after["status"] in ACCEPTED:
            newly[key] = {"accepted_source": after.get("accepted_source"),
                          "accepted_doi": after.get("accepted_doi"),
                          "rules": attribute(entries[key], previous),
                          "advisories": result_advisories(entries[key]["fields"], after)}
        elif previous["status"] == "metadata_verified" and after["status"] not in ACCEPTED:
            lost.append(key)
    by_rule = Counter(r for row in newly.values() for r in (row["rules"] or ["none-alone"]))
    summary = {
        "counts": {s: sum(r["status"] == s for r in results.values()) for s in sorted({r["status"] for r in results.values()})},
        "needs_review_reassessed": sum(r["status"] == "needs_review" for r in results.values()),
        "newly_verifiable": len(newly),
        "by_rule": dict(sorted(by_rule.items())),
        "lost_verification": lost,
        "errors": errors,
        "missing_doi_advisories": {"currently_verified": len(advisories_now),
                                   "newly_verifiable": sum(bool(r["advisories"]) for r in newly.values())},
        "keys": newly,
        "currently_verified_missing_doi": advisories_now,
    }
    (HERE / "newly-verifiable.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"keys", "currently_verified_missing_doi"}}), flush=True)
    if errors or lost:
        raise SystemExit(f"{len(errors)} errors, {len(lost)} lost verifications: see newly-verifiable.json")


if __name__ == "__main__":
    main()
