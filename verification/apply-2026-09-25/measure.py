"""Offline, read-only: which held entries do the stage 1 rules newly verify?

Opens the main cache with ``mode=ro`` (no writes, no network) and re-runs
``auto_review.reassess`` on every needs_review entry with the current code.
Each newly verified entry is attributed to a rule by re-checking it with that
rule switched off:

  suffix     it does not verify when suffixes are compared again;
  publisher  it does not verify when the catalogue same-firm rule is off;
  other      neither (reported, never batched silently).

Writes measure.json and, for the no-edit batches, suffix-reassess-keys.json and
publisher-variants-keys.json next to this file.

    .venv/bin/python verification/apply-2026-09-25/measure.py
"""
from collections import Counter
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
sys.path.insert(0, str(HERE))
os.chdir(ROOT)
from build_cases import ReadOnlyCache  # noqa: E402
from verification import ACCEPTED, current_results, load_entries  # noqa: E402
import verification  # noqa: E402
import auto_review  # noqa: E402
import catalogue_review  # noqa: E402


def verifies(entry, previous):
    try:
        return auto_review.reassess(entry, previous)["status"] in ACCEPTED
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def main():
    entries = load_entries(ROOT / "cdl.bib")
    cache = ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        results = current_results(ROOT / "cdl.bib", cache, entries)
    finally:
        cache.close()
    held = {k: r for k, r in results.items() if r["status"] == "needs_review" and not r.get("external_evidence")}
    newly = sorted(k for k, r in held.items() if verifies(entries[k], r))
    same_suffix, firm = verification.same_suffix, catalogue_review.publisher_same_firm
    tokens_rule = verification.without_suffix_tokens
    attribution = {}
    for key in newly:
        verification.same_suffix = auto_review.same_suffix = (
            lambda a, b: verification.normalize_author_suffix(a or "") == verification.normalize_author_suffix(b or ""))
        verification.without_suffix_tokens = auto_review.without_suffix_tokens = lambda tokens: tokens
        without_suffix = verifies(entries[key], held[key])
        verification.same_suffix = auto_review.same_suffix = same_suffix
        verification.without_suffix_tokens = auto_review.without_suffix_tokens = tokens_rule
        catalogue_review.publisher_same_firm = lambda a, b: False
        without_firm = verifies(entries[key], held[key])
        catalogue_review.publisher_same_firm = firm
        attribution[key] = ("suffix" if not without_suffix else "publisher" if not without_firm else "other")
    summary = {"needs_review_reassessed": len(held), "newly_verified": len(newly),
               "by_rule": dict(Counter(attribution.values())), "keys": attribution}
    (HERE / "measure.json").write_text(json.dumps(summary, indent=1) + "\n")
    for batch, rule in (("suffix-reassess", "suffix"), ("publisher-variants", "publisher")):
        keys = sorted(k for k, r in attribution.items() if r == rule)
        (HERE / f"{batch}-keys.json").write_text(json.dumps({"rule": rule, "keys": keys}, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "keys"}), flush=True)
    print(json.dumps(attribution), flush=True)


if __name__ == "__main__":
    main()
