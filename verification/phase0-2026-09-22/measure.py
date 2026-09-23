"""Phase 0 offline measurement (resolver 28) from cached evidence only.

Reads cdl.bib and the latest current review of every entry from
.bibcheck/verification.sqlite3 through a READ-ONLY SQLite connection
(``mode=ro``). Nothing is written to the cache or to cdl.bib; no network
request is made. Every needs_review entry is reassessed in memory under the
current code, then offered to the proposal generators; whatever remains is
grouped by pattern for batch decisions.

Usage (from the repository root):
    .venv/bin/python verification/phase0-2026-09-22/measure.py [--baseline OLD.json] [--workers 8]

``--baseline`` optionally names a JSON map {key: {"status": ...}} produced by
reassessing every entry with the pre-Phase-0 code; it only labels currently
verified entries that already failed to re-verify before these rules.
Outputs (next to this script): proposals.json and groups.json.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
import multiprocessing
import os
from pathlib import Path
import random
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
os.chdir(ROOT)  # helpers.py reads bibcheck/*.txt relative to the repository root

# Modules changed by Phase 0. Every other bibcheck module is loaded from the
# committed HEAD so that other work in progress in the tree cannot leak into
# these counts (use --working-tree to measure the whole working tree instead).
PHASE0_MODULES = {"verification.py", "auto_review.py", "correction_proposals.py", "pmc_corrections.py",
                  "publisher_corrections.py", "source_locators.py", "verification_cli.py"}
PHASE0_DATA = {"suffixes.txt", "key_overrides.json"}


def module_path(working_tree):
    if working_tree:
        return ROOT / "bibcheck"
    import shutil
    import subprocess
    import tempfile
    env = dict(os.environ, DEVELOPER_DIR=os.environ.get("DEVELOPER_DIR", "/Library/Developer/CommandLineTools"))
    import atexit
    target = Path(tempfile.mkdtemp(prefix="phase0-modules-"))
    atexit.register(shutil.rmtree, target, True)
    names = subprocess.run(["git", "ls-tree", "--name-only", "HEAD", "bibcheck/"], cwd=ROOT, env=env,
                           check=True, capture_output=True, text=True).stdout.split()
    for name in names:
        base = Path(name).name
        if base in PHASE0_MODULES or base in PHASE0_DATA:
            shutil.copy(ROOT / name, target / base)
        else:
            body = subprocess.run(["git", "show", "HEAD:" + name], cwd=ROOT, env=env,
                                  check=True, capture_output=True).stdout
            (target / base).write_bytes(body)
    return target


WORKING_TREE = "--working-tree" in sys.argv
sys.path.insert(0, str(module_path(WORKING_TREE)))

from verification import Cache, POLICY, load_entries, outcome  # noqa: E402
from auto_review import reassess  # noqa: E402
import correction_proposals as cp  # noqa: E402
import pmc_corrections as pmc  # noqa: E402

NOTICE = "DOI-linked source correction/retraction notice requires adjudication"
SUFFIX = "DOI-linked PubMed author suffix conflicts with the citation"
COORDS = "DOI-linked publisher/PubMed article coordinates conflict with or are missing from the citation"
SEED = 20260922


class ReadOnlyCache(Cache):
    """Cache.get over a read-only connection. Migration/notice writes are
    replaced by in-memory results; the underlying file is never modified."""

    def __init__(self, filename):
        self.path = Path(filename)
        self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)

    def store(self, *args, **kwargs):
        return True  # pretend the (skipped) migration row was stored

    def put(self, bibliography, entry, result):
        result = self.retain_notices(entry, result)
        return dict(result, key=entry["key"], fingerprint=entry["fingerprint"], policy=POLICY)

    def remember_notices(self, candidates):
        return None


ENTRIES: dict = {}
CURRENT: dict = {}


def without_publisher(entry):
    fields = {k: v for k, v in entry["fields"].items() if k != "publisher"}
    return dict(entry, fields=fields)


def slim(proposal, rule=None, source=None, extra=None):
    """Keep the auditable parts of a proposal (no raw source blobs)."""
    changes = {f: {"before": c.get("before"), "after": c.get("after")} for f, c in proposal["changes"].items()}
    out = {"key": proposal["key"], "fingerprint": proposal["fingerprint"], "kind": proposal["kind"],
           "rule": rule or proposal.get("rule") or proposal["kind"], "doi": proposal.get("doi"),
           "pubmed_id": proposal.get("pubmed_id"), "source": source or proposal.get("source"),
           "changes": changes}
    if proposal.get("subclasses"):
        out["subclasses"] = proposal["subclasses"]
    if extra:
        out.update(extra)
    return out


# Two-source generators first (stronger evidence), then the single-source rule.
GENERATORS = [
    ("pmc_article_number", "A1b", "JATS front matter + PubMed (+ Crossref)", pmc.pmc_article_number_proposal),
    ("pmc_coordinates", "PMC-C", "JATS front matter + PubMed", pmc.pmc_coordinate_proposal),
    ("pmc_given_names", "PMC-A", "JATS front matter + PubMed",
     lambda e, p: pmc.pmc_coordinate_proposal(e, p, include_authors=True)),
    ("pagination", "C-PAGES", "Crossref + PubMed", cp.pagination_proposal),
    ("coordinates", "C-COORD", "Crossref + PubMed", cp.coordinate_proposal),
    ("journal_history", "C-JEP", "Crossref + documented JEP title history", cp.journal_history_proposal),
    ("suffix", "C-SUFFIX", "Crossref + PubMed", cp.suffix_proposal),
    ("issue_year", "C-YEAR", "Crossref print date + PubMed", cp.issue_year_proposal),
] + [(f"field_{f}", f"C-{f.upper()}", "Crossref + PubMed",
      (lambda f: lambda e, p: cp.field_proposal(e, p, f))(f))
     for f in ("title", "volume", "number", "year", "author", "journal")] + [
    ("publication", "C-PUB", "Crossref + PubMed", cp.publication_proposal),
    ("combined", "C-COMB", "Crossref + PubMed",
     lambda e, p: cp.publication_proposal(e, p, include_identity_fields=True)),
]


def assess_one(key):
    entry, previous = ENTRIES[key], CURRENT[key]
    out = {"key": key, "type": entry["fields"].get("ENTRYTYPE"), "before": previous.get("status")}
    try:
        result = reassess(entry, previous)
        out["status"] = result["status"]
        out["issues"] = result.get("issues", [])
        out["accepted_doi"] = result.get("accepted_doi")
        out["accepted_source"] = result.get("accepted_source")
        has_publisher = entry["fields"].get("ENTRYTYPE") == "article" and bool(entry["fields"].get("publisher"))
        if previous.get("status") != "needs_review":
            # Regression check: the user-policy publisher drop re-verifies from cache.
            if has_publisher:
                dropped = reassess(without_publisher(entry), previous)
                out["after_publisher_drop"] = dropped["status"]
                out["after_publisher_drop_doi"] = dropped.get("accepted_doi")
            if result["status"] != "metadata_verified":
                # A stored approval that no longer reassesses (older resolver):
                # offer the same source-backed repairs so it can be re-verified.
                working = without_publisher(entry) if has_publisher else entry
                base = reassess(working, previous) if has_publisher else result
                kind, payload = propose(key, entry, working, base, has_publisher)
                out["stale_repair"] = payload if kind == "proposal" else {"held": payload.get("explain")}
            return out
        if result["status"] == "metadata_verified":
            out["outcome"] = "verified_no_edit"
            out["rule_hint"] = rule_hint(entry, previous, result)
            return out
        working = entry
        if has_publisher:
            dropped = reassess(without_publisher(entry), previous)
            if dropped["status"] == "metadata_verified":
                out["outcome"] = "verified_after_publisher_drop"
                out["accepted_doi"] = dropped.get("accepted_doi")
                return out
            working, result = without_publisher(entry), dropped
        kind, payload = propose(key, entry, working, result, has_publisher)
        out["outcome"] = kind
        out.update(payload)
        return out
    except Exception as exc:
        out["status"] = "error"
        out["outcome"] = "error"
        out["error"] = repr(exc)
        return out


def propose(key, entry, working, result, has_publisher):
    """Run the generators in order; return ("proposal", {...}) or ("held", {...})."""
    out = {}
    if True:
        for name, rule, source, generator in GENERATORS:
            try:
                proposal = generator(working, result)
            except Exception as exc:  # a generator failure is a hold, never a proposal
                out.setdefault("generator_errors", []).append(f"{name}: {exc!r}")
                proposal = None
            if proposal:
                proposal = dict(proposal, key=key, fingerprint=entry["fingerprint"])
                out["proposal"] = slim(proposal, rule=rule, source=source,
                                       extra={"generator": name, "requires_publisher_drop": has_publisher})
                return "proposal", out
        explain = {}
        proposal = cp.single_source_proposal(working, result, explain)
        if proposal:
            proposal = dict(proposal, key=key, fingerprint=entry["fingerprint"])
            out["proposal"] = slim(proposal, extra={"generator": "single_source",
                                                    "requires_publisher_drop": has_publisher})
            return "proposal", out
        out["explain"] = explain
        out["held_issues"] = result.get("issues", [])
        out["features"] = features(working, result)
        return "held", out


def rule_hint(entry, previous, result):
    """Which resolver-28 rule a newly verified entry most plausibly used."""
    from verification import apa_twin_key, normalize_doi
    doi = result.get("accepted_doi")
    if not doi:
        return ["route:" + str(result.get("accepted_source"))]
    hints = []
    for c in result.get("candidates", []):
        try:
            same = c.get("doi") and normalize_doi(c["doi"]) == doi
        except ValueError:
            continue
        record = c.get("record") or {}
        if same and c.get("source") == "crossref":
            years = {str(p[0]) for d in ("published", "published-print", "published-online", "issued")
                     for p in record.get(d, {}).get("date-parts", []) or [] if p}
            if len(years) > 1:
                hints.append("R1-print-year")
        elif (c.get("source") == "crossref" and c.get("doi")
              and c.get("evidence", {}).get("title", {}).get("match")
              and c.get("evidence", {}).get("author", {}).get("match")):
            try:
                if apa_twin_key(c["doi"]) == apa_twin_key(doi):
                    hints.append("R2-apa-twin")
                else:
                    hints.append("R2-rival-" + (record.get("type") or "unknown"))
            except ValueError:
                pass
    journal = entry["fields"].get("journal", "")
    if journal:
        from verification import normalize_journal, normalized
        try:
            if normalize_journal(journal) != normalized(journal).replace(" & ", " and "):
                hints.append("R3-journal-alias")
        except ValueError:
            pass
    old_notice = [i for i in previous.get("issues", []) if i in (NOTICE, SUFFIX, COORDS)]
    if old_notice:
        hints.append("flag-scope")
    return sorted(set(hints)) or ["other"]


def features(entry, result):
    """Coarse evidence features used only for grouping held entries."""
    fields = entry["fields"]
    feats = {"has_doi": bool(fields.get("doi")), "flags": [i for i in result.get("issues", []) if i != result.get("issues", [""])[0]]}
    best = None
    try:
        from difflib import SequenceMatcher
        from verification import normalized
        local = normalized(fields.get("title", ""))
        for c in result.get("candidates", []):
            if c.get("source") != "crossref" or not c.get("evidence"):
                continue
            title = c["evidence"].get("title", {})
            try:
                sim = max(SequenceMatcher(None, local, normalized(s)).ratio() for s in title.get("source") or [""])
            except ValueError:
                sim = 0.0
            score = sim + (0.3 if c["evidence"].get("author", {}).get("match") else 0)
            if best is None or score > best[0]:
                best = (score, sim, c)
    except (ValueError, TypeError):
        best = None
    if best:
        score, sim, c = best
        feats["title_sim"] = round(sim, 3)
        feats["best_doi"] = c.get("doi")
        feats["best_type"] = (c.get("record") or {}).get("type")
        feats["best_issue_fields"] = sorted({i.split(":", 1)[0] for i in c.get("issues", [])})
        feats["best_issues"] = c.get("issues", [])
    feats["has_pubmed"] = any(c.get("source") == "europepmc" for c in result.get("candidates", []))
    feats["n_candidates"] = len(result.get("candidates", []))
    return feats


# --------------------------------------------------------------------------
# Grouping of held entries: coarse, batch-answerable patterns.
# --------------------------------------------------------------------------

GROUP_TEXT = {
    "notice-erratum": ("The cited work's own DOI carries an erratum/correction notice (no retractions found). "
                       "Metadata otherwise matches or differs only as listed in the plan's classes A/B/C.",
                       "Acknowledge as content-only errata in one batch after skimming the notice list; C-class rows "
                       "(substantive discrepancy) individually."),
    "coordinates-identity": ("Publisher JATS and PubMed agree on the cited DOI's volume/pages/article number, "
                             "the citation differs, and no automatic route applies (sources disagree, second field, or preprint link).",
                             "Review as one packet; most need the coordinate fix plus one more field."),
    "suffix-jr": ("DOI-linked PubMed has 'Jr' for an author and the citation lacks it; a second fix is also needed.",
                  "Accept 'add Jr from PubMed' for the batch; the second fix follows its own group."),
    "article-more-given-names": ("The citation byline has detail the identified source lacks (full given names, extra "
                                 "initials, accents, letters a registry could not encode, protected capitals).",
                                 "Keep the citation byline; accept these bylines by batch after a 10-entry PDF/publisher spot-check."),
    "article-title-typography": ("Title differs from the source only in punctuation/quote style.",
                                 "Accept the citation's typography (batch)."),
    "article-journal-title-variant": ("Venue differs by a section/subtitle or a later renamed title; Crossref carries the "
                                      "current title and PubMed does not confirm a different venue.",
                                      "Decide per journal family (e.g. QJEP Section A, EEG/Evoked Potentials, JRSS series); ~10 decisions."),
    "article-sources-disagree": ("Crossref and PubMed give different values for the field that differs from the citation.",
                                 "Human check against the publisher page/PDF; batch by field."),
    "article-number-not-in-source": ("The citation has an issue number the identified source does not give (and cannot be "
                                     "taken from the source).",
                                     "Policy: keep or drop an unconfirmed issue number (one batch decision)."),
    "article-external-evidence": ("Entry carries attached external evidence that needs explicit adjudication.",
                                  "Individual review of the attached evidence."),
    "article-author-count": ("Author counts differ between the citation and the source record (missing authors, "
                             "'others', or a sparse registry byline).",
                             "Needs a document: batch-check against publisher pages/PDFs; accept source byline where it is complete."),
    "article-year-online-first": ("Year blocked by online-first dates: Crossref online and print years differ "
                                  "and the issued (earliest) date is the online year.",
                                  "Policy: the print year wins. Accept citations already using the print year; "
                                  "correct those citing the online year (batch)."),
    "article-year-other": ("Cited year is absent from, or conflicts with, the source dates (off by one or more).",
                           "Individual/document check; often a reprint or wrong year."),
    "article-too-many-fields": ("More than two fields differ from the identified record (single-source rule forbids a proposal).",
                                "Human review; batch by journal/decade; often wrong candidate or a heavily garbled citation."),
    "article-ambiguous": ("Two or more distinct records fit the citation about equally well.",
                          "Human choice of record; usually quick."),
    "article-no-record": ("No Crossref/PubMed record meets the identity rule (title/author/year/venue/coordinates).",
                          "Needs a new source (local PDF, publisher page, catalogue) or human sign-off."),
    "article-relation-or-update": ("The identified record has a version/update relationship (preprint link, "
                                   "has-review, correction) that the resolver does not clear.",
                                   "One policy decision per relation type (e.g., accept journal version despite preprint link)."),
    "article-extra-field": ("The entry carries a field with no deterministic verifier (address, month, note, url, ...).",
                            "Policy: drop or keep the unverifiable field for the batch (recommend drop for @article)."),
    "article-type": ("The identified record is not a journal article (book chapter, proceedings, posted content).",
                     "Batch: convert entry type or accept as-is per type."),
    "article-value-held": ("One or two fields differ but the source value is unusable or the sources disagree "
                           "(e.g., no numeric issue, markup in title, Crossref and PubMed differ).",
                           "Human review by sub-pattern (see 'detail' counts)."),
    "article-would-not-verify": ("A source-backed fix exists but the edited entry still would not verify "
                                 "(remaining flag or rival).",
                                 "Human review; mostly notices or rivals."),
    "article-other": ("Other article cases.", "Individual review."),
    "audit-excluded": ("A source-backed proposal exists, but an earlier documented audit held this key "
                       "(verification/**/*audit-exclusions.json: e.g. would discard names, duplicate work).",
                       "Keep held; resolve with the documented evidence (PDF/byline) individually."),
}


DECISION_TYPE = {
    "notice-erratum": "batch", "article-more-given-names": "batch", "article-title-typography": "batch",
    "article-number-not-in-source": "batch", "article-extra-field": "batch", "article-relation-or-update": "batch",
    "article-year-online-first": "batch", "suffix-jr": "batch", "article-type": "batch",
    "article-journal-title-variant": "batch-by-journal", "article-sources-disagree": "individual",
    "article-no-record": "needs-new-source", "article-too-many-fields": "individual", "article-author-count": "individual",
    "article-ambiguous": "individual", "coordinates-identity": "individual", "audit-excluded": "individual",
}


def group_of(row):
    """Return (group id, subpattern) for a held row."""
    issues = row.get("held_issues", [])
    etype = (row.get("type") or "").lower()
    ex = row.get("explain", {})
    if ex.get("reason") == "audit-excluded":
        return "audit-excluded", ex["withheld_proposal"]["kind"]
    if NOTICE in issues:
        return "notice-erratum", etype
    if COORDS in issues:
        return "coordinates-identity", ex.get("reason", "")
    if SUFFIX in issues:
        return "suffix-jr", ex.get("reason", "")
    if etype != "article":
        issue = issues[0] if issues else "unknown"
        return f"{etype}:{issue[:60]}", ""
    reason = ex.get("reason", "")
    fields = ex.get("fields", [])
    detail = ex.get("detail", "")
    feats = row.get("features", {})
    if reason in {"no-identified-record"}:
        return "article-no-record", ("pubmed" if feats.get("has_pubmed") else "no-pubmed")
    if reason == "ambiguous-identity":
        return "article-ambiguous", ""
    if reason == "not-correctable":
        blockers = ex.get("blockers", [])
        if any(b.startswith("extra-field:") for b in blockers):
            return "article-extra-field", ",".join(sorted(b.split(":", 1)[1] for b in blockers if b.startswith("extra-field:")))
        if "type" in blockers:
            return "article-type", str(feats.get("best_type"))
        if "relation" in blockers or "update" in blockers:
            return "article-relation-or-update", ",".join(sorted(blockers))
        return "article-other", ",".join(sorted(blockers))
    if reason == "too-many-fields":
        return "article-too-many-fields", str(len(fields))
    if reason == "value-held":
        if detail.startswith("author: citation byline has detail"):
            best = feats.get("best_issues", [])
            if any("different author counts" in i for i in best):
                return "article-author-count", "citation-longer-or-sparse-source"
            return "article-more-given-names", "+".join(fields)
        if detail.startswith("year:"):
            return "article-year-other", detail
        if "title-typography-only" in detail:
            return "article-title-typography", ""
        if "journal-replacement-unconfirmed" in detail or "journal-extension" in detail:
            return "article-journal-title-variant", detail.split(";")[0]
        if "sources disagree" in detail:
            return "article-sources-disagree", detail.split(":", 1)[0]
        if detail.startswith("number: no plain numeric"):
            return "article-number-not-in-source", ""
        if "drops accents" in detail:
            return "article-more-given-names", "source drops accents/protected case"
        return "article-value-held", detail.split(":", 1)[0] + ": " + detail.split(":", 1)[-1].strip()[:40]
    if reason in {"would-not-verify", "would-not-match-source"}:
        if fields == ["year"] or "year" in fields:
            return "article-year-online-first", reason
        return "article-would-not-verify", "+".join(fields)
    if reason == "not-eligible":
        return "article-external-evidence", ""
    if reason in {"no-field-differs", "advisory-only", "no-change-possible"}:
        best = feats.get("best_issues", [])
        if any(i.startswith("year: conflicting") for i in best):
            return "article-year-online-first", reason
        return "article-other", reason
    if reason == "identifier-conflict":
        return "article-other", "doi/issn conflict"
    return "article-other", reason


def correction_class(proposal):
    """Coarse class for spot-check sampling (10 per class; 20 if multi-field)."""
    generator = proposal.get("generator", "")
    if generator != "single_source":
        return "A1b-ARTICLE-NUMBER" if proposal["rule"] == "A1b" else "TWO-SOURCE"
    subs = proposal.get("subclasses", {})
    if len(subs) != 1:
        return "S1-TWO-FIELDS" + ("-RISKY" if any(v in cp.RISKY_SUBCLASSES for v in subs.values()) else "")
    return COARSE_CLASSES.get(next(iter(subs.values())), "S1-OTHER")


COARSE_CLASSES = {
    "author-given-names-accents-suffix": "S1-AUTHOR-NAMES", "author-byline-completion": "S1-AUTHOR-NAMES",
    "author-surname-spelling": "S1-AUTHOR-SURNAME",
    "pages-complete-range": "S1-PAGES-COMPLETE", "pages-added": "S1-PAGES-COMPLETE",
    "pages-different-start": "S1-COORDINATES", "volume": "S1-COORDINATES", "number": "S1-COORDINATES",
    "year-print-year": "S1-COORDINATES",
    "title-crossref+pubmed": "S1-TITLE-CORROBORATED", "title-crossref-only": "S1-TITLE-CROSSREF-ONLY",
    "journal-jep-history": "S1-JOURNAL-HISTORY-OR-TYPO", "journal-typo": "S1-JOURNAL-HISTORY-OR-TYPO",
    "journal-other-venue": "S1-JOURNAL-REPLACEMENT", "journal-section": "S1-JOURNAL-REPLACEMENT",
}
CLASS_TEXT = {
    "A1b-ARTICLE-NUMBER": "pages = article number, spurious number dropped (JATS + PubMed agree; rule A1b)",
    "TWO-SOURCE": "existing two-source generators (Crossref + PubMed, or JATS + PubMed) now unblocked",
    "S1-AUTHOR-NAMES": "byline gains given names, accents, suffixes or missing co-authors from the source; no citation detail lost",
    "S1-AUTHOR-SURNAME": "a surname spelling changes to the source's (<=2 letters); registry typos are possible",
    "S1-PAGES-COMPLETE": "same first page; end page added or corrected, or pages added",
    "S1-COORDINATES": "volume, issue, different first page, or print year taken from the source",
    "S1-TITLE-CORROBORATED": "title word fix where PubMed has the same title as Crossref",
    "S1-TITLE-CROSSREF-ONLY": "title word fix from Crossref alone (<=2 word edits or missing subtitle)",
    "S1-JOURNAL-HISTORY-OR-TYPO": "pre-1975 'JEP: General' -> 'Journal of Experimental Psychology', or a <=3-letter venue typo",
    "S1-JOURNAL-REPLACEMENT": "a different venue name (identity pinned by exact title, first author, year, volume and first page)",
    "S1-TWO-FIELDS": "two low-risk fields together",
    "S1-TWO-FIELDS-RISKY": "two fields, at least one from a risky subclass",
    "STALE-APPROVAL-REPAIR": "currently verified entries that no longer reassess (approved under an older resolver)",
}


def main():
    global ENTRIES, CURRENT
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--keys", nargs="*")
    parser.add_argument("--working-tree", action="store_true",
                        help="load every bibcheck module from the working tree (default: non-Phase-0 modules from HEAD)")
    args = parser.parse_args()
    started = time.time()
    bib = ROOT / "cdl.bib"
    ENTRIES = load_entries(bib)
    cache = ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
    CURRENT = {k: cache.get(bib, e) or dict(outcome("pending", ["New"]), key=k) for k, e in ENTRIES.items()}
    cache.close()
    before = Counter(r["status"] for r in CURRENT.values())
    keys = args.keys or list(ENTRIES)
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(args.workers) as pool:
        rows = pool.map(assess_one, keys, chunksize=8)
    rows = {r["key"]: r for r in rows}
    if args.keys:  # diagnostic mode: print rows, write nothing
        for r in rows.values():
            print(json.dumps(r, ensure_ascii=False)[:1500])
        return
    baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else {}

    needs = [r for r in rows.values() if r["before"] == "needs_review"]
    verified_before = [r for r in rows.values() if r["before"] in {"metadata_verified", "human_verified"}]
    outcomes = Counter(r.get("outcome") for r in needs)
    regressions = []
    for r in verified_before:
        new_ok = r.get("status") in {"metadata_verified", "human_verified"}
        drop_ok = r.get("after_publisher_drop", "metadata_verified") == "metadata_verified"
        if not new_ok or not drop_ok:
            regressions.append({
                "key": r["key"], "reassess": r.get("status"), "after_publisher_drop": r.get("after_publisher_drop"),
                "repair": (r.get("stale_repair") or {}).get("proposal", {}).get("changes")
                or (r.get("stale_repair") or {}).get("held"),
                "old_code_reassess": baseline.get(r["key"], {}).get("status"),
                "pre_existing": baseline.get(r["key"], {}).get("status") not in (None, "metadata_verified")
                and not (r.get("status") == "metadata_verified" and not drop_ok),
                "issues": r.get("issues", [])[:4]})

    # Proposals ----------------------------------------------------------------
    # Earlier documented holds (verification/**/*audit-exclusions.json) stay held.
    excluded = {}
    for path in sorted(ROOT.glob("verification/**/*audit-exclusions.json")):
        data = json.loads(path.read_text())
        items = data.items() if isinstance(data, dict) else [(d.get("key"), d.get("reason") or d.get("kind")) for d in data]
        for key, reason in items:
            excluded.setdefault(key, []).append(f"{path.relative_to(ROOT)}: {str(reason)[:160]}")
    for r in needs:
        if r.get("outcome") == "proposal" and r["key"] in excluded:
            r["outcome"] = "held"
            r["explain"] = {"reason": "audit-excluded", "detail": excluded[r["key"]],
                            "withheld_proposal": r.pop("proposal")}
    outcomes = Counter(r.get("outcome") for r in needs)  # after audit exclusions
    proposals = [r["proposal"] for r in needs if r.get("outcome") == "proposal"]
    for p in proposals:
        p["class"] = correction_class(p)
    # Stored approvals that no longer reassess (older resolver) get the same repairs.
    for r in verified_before:
        repair = (r.get("stale_repair") or {}).get("proposal")
        if repair and r["key"] not in excluded:
            proposals.append(dict(repair, class_="", stale_approval=True))
            proposals[-1].pop("class_")
            proposals[-1]["class"] = "STALE-APPROVAL-REPAIR"
    add_doi = []
    for r in needs:
        if r.get("outcome") in {"verified_no_edit", "verified_after_publisher_drop"} and not ENTRIES[r["key"]]["fields"].get("doi") and r.get("accepted_doi"):
            add_doi.append({"key": r["key"], "fingerprint": ENTRIES[r["key"]]["fingerprint"], "kind": "add_doi",
                            "rule": "D1", "class": "D1:add_doi(newly verified)", "source": r.get("accepted_source"),
                            "changes": {"doi": {"before": None, "after": r["accepted_doi"]}}})
    for p in proposals:
        if p.get("doi") and not ENTRIES[p["key"]]["fields"].get("doi"):
            add_doi.append({"key": p["key"], "fingerprint": p["fingerprint"], "kind": "add_doi", "rule": "D1",
                            "class": "D1:add_doi(after correction)", "source": p.get("source"),
                            "changes": {"doi": {"before": None, "after": p["doi"]}}})
    existing_add_doi = sum(1 for r in verified_before if not ENTRIES[r["key"]]["fields"].get("doi")
                           and CURRENT[r["key"]].get("accepted_doi"))
    drop_publisher = []
    for key, entry in ENTRIES.items():
        p = cp.drop_publisher_proposal(entry)
        if p:
            drop_publisher.append({"key": key, "fingerprint": entry["fingerprint"], "kind": "drop_publisher",
                                   "rule": "P1", "class": "P1:drop_publisher",
                                   "status_now": CURRENT[key].get("status"),
                                   "changes": p["changes"]})
    classes = defaultdict(list)
    for p in proposals:
        classes[p["class"]].append(p["key"])
    rng = random.Random(SEED)
    class_rows = []
    for name, members in sorted(classes.items(), key=lambda kv: -len(kv[1])):
        multi = any(len(p["changes"]) > 1 for p in proposals if p["class"] == name)
        size = 20 if multi else 10
        class_rows.append({"class": name, "description": CLASS_TEXT.get(name, ""), "count": len(members),
                           "multi_field": multi,
                           "subclasses": dict(Counter(v for p in proposals if p["class"] == name
                                                      for v in (p.get("subclasses") or {p["rule"]: p["rule"]}).values())),
                           "spot_check_size": min(size, len(members)),
                           "spot_check_keys": sorted(rng.sample(sorted(members), min(size, len(members))))})

    # Groups ------------------------------------------------------------------
    held = [r for r in needs if r.get("outcome") in {"held", "error"}]
    grouped = defaultdict(list)
    subpatterns = defaultdict(Counter)
    for r in held:
        if r.get("outcome") == "error":
            gid, sub = "error", r.get("error", "")[:60]
        else:
            gid, sub = group_of(r)
        if ":" in gid and not gid.startswith("article"):
            etype, issue = gid.split(":", 1)
            gid = f"{etype}-unresolved"
            sub = issue
        grouped[gid].append(r["key"])
        subpatterns[gid][sub] += 1
    groups = []
    for gid, members in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        text, decision = GROUP_TEXT.get(gid, (f"Unresolved @{gid.split('-')[0]} entries (non-article).",
                                              "Route to the books/proceedings plans; batch by sub-pattern."))
        groups.append({"group": gid, "description": text, "count": len(members),
                       "decision_type": DECISION_TYPE.get(gid, "route-to-plan" if not gid.startswith(("article", "notice", "coord", "suffix", "audit")) else "individual"),
                       "suggested_batch_decision": decision,
                       "subpatterns": dict(subpatterns[gid].most_common()),
                       "keys": sorted(members)})

    summary = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resolver_version": __import__("auto_review").RESOLVER_VERSION,
        "modules": "working tree" if WORKING_TREE else "Phase 0 modules from working tree; all other bibcheck modules from HEAD",
        "entries": len(ENTRIES), "status_before": dict(before),
        "needs_review_before": len(needs),
        "needs_review_outcomes": dict(outcomes),
        "verified_no_edit_rule_hints": dict(Counter(h for r in needs if r.get("outcome") == "verified_no_edit"
                                                    for h in r.get("rule_hint", []))),
        "proposal_classes": {c["class"]: c["count"] for c in class_rows},
        "add_doi": {"newly_verified_or_corrected": len(add_doi), "already_verified_without_doi": existing_add_doi},
        "drop_publisher_articles": len(drop_publisher),
        "held_groups": {g["group"]: g["count"] for g in groups},
        "currently_verified": len(verified_before),
        "regressions": regressions,
        "seconds": round(time.time() - started, 1),
    }
    (HERE / "proposals.json").write_text(json.dumps({
        "summary": summary, "classes": class_rows, "proposals": proposals,
        "add_doi": add_doi, "drop_publisher": drop_publisher}, indent=1, ensure_ascii=False) + "\n")
    (HERE / "groups.json").write_text(json.dumps({
        "summary": {k: summary[k] for k in ("generated", "needs_review_before", "needs_review_outcomes", "held_groups")},
        "groups": groups}, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "regressions"}, indent=1))
    print("regressions:", len(regressions), "pre-existing:", sum(r["pre_existing"] for r in regressions))
    for r in regressions:
        print("  ", r)


if __name__ == "__main__":
    main()
