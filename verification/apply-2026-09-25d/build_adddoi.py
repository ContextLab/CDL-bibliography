"""Build adddoi002-proposals.json: DOIs for metadata_verified entries that lack one.

User decisions: "Add verified DOIs to entries once a full match is verified" (2026-09-22) and
"DOIs everywhere ... for the published, peer-reviewed version" (2026-09-25). Rules:

1. Crossref-accepted entries (the missing-DOI advisory, `verification.result_advisories`):
   the accepted DOI, through ../apply-2026-09-23/apply.py `cited_work_doi` (the cited work's
   own clean full-match Crossref record: no notice, no update, record type fits the entry
   type, no rival DOI that also matches title and byline).
2. verify_entry approvals saved without `accepted_doi` bookkeeping: the unique Crossref
   candidate with no issues is the accepted record; the same `cited_work_doi` checks apply.
3. PubMed/PMC-accepted entries (europepmc, pmc-jats) and publisher-page approvals
   (publisher-head): the DOI in the accepted record, only after the DOI's own Crossref
   record is confirmed to be the same work: title, first-author surname, year and venue
   all match (`verification.compare_record` evidence), a journal article, not a notice.
4. Preprint approvals (arxiv-repository, biorxiv-preprint): the repository DOI of the cited
   preprint, unless the saved repository record names a published version (that entry is
   for the preprint -> published swap list, not a DOI).

Anything ambiguous is skipped with its reason. A DOI already on another cdl.bib entry is
skipped. DOIs are lowercase and bare.

    .venv/bin/python verification/apply-2026-09-25d/build_adddoi.py [--offline]
"""
import argparse
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import (Cache, ProviderError, compare_record, current_results, load_entries,  # noqa: E402
                          normalize_doi, normalized, split_authors)
import osf_review, datacite_review, acl_review, sfn_abstracts  # noqa: E402,F401  (route validators)

_spec = importlib.util.spec_from_file_location("apply0923", ROOT / "verification/apply-2026-09-23/apply.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
os.chdir(ROOT)

NOTICE = re.compile(r"\b(erratum|errata|corrigendum|correction|retraction|retracted|expression of concern|"
                    r"withdrawn)\b", re.I)
PREPRINT_SOURCES = {"arxiv-repository", "biorxiv-preprint"}
PUBMED_SOURCES = {"europepmc", "pmc-jats", "publisher-head"}


def notice_title(record_title, cited_title):
    """A notice-like word in the record title that the cited title does not share.

    'Correcting the correction of conditional recency slopes' (Farr14) is the cited article
    itself; 'Correction to: ...' for an article without that word is a notice."""
    words = {w.lower() for w in NOTICE.findall(record_title or "")}
    cited = {w.lower() for w in NOTICE.findall(cited_title or "")}
    return bool(words - cited)


def cited_work_doi(entry, result):
    """../apply-2026-09-23/apply.py cited_work_doi, with the notice-title test refined:
    a title word such as 'correction' that the cited title itself contains is not a notice
    (Farr14, JenkEtal02, WallEtal04, GothEtal96). Updates/corrections relations still block."""
    doi, reason = base.cited_work_doi(entry, result)
    if reason != "accepted record looks like a notice":
        return doi, reason
    own = [c for c in result.get("candidates", []) if c.get("source") == "crossref" and c.get("doi")
           and normalize_doi(c["doi"]) == normalize_doi(result["accepted_doi"])]
    title = " ".join((own[0].get("record") or {}).get("title") or []) if own else ""
    if notice_title(title, entry["fields"].get("title", "")):
        return None, reason
    record = own[0].get("record") or {}
    if record.get("relation", {}).get("is-correction-of") or record.get("update-to"):
        return None, "accepted record is an update/notice"
    # the remaining checks of base.cited_work_doi, with the title test passed
    patched = dict(result, candidates=[dict(c, record=dict(c.get("record") or {}, title=["article"]))
                                       if c is own[0] else c for c in result["candidates"]])
    return base.cited_work_doi(entry, patched)


def full_match_candidate(result):
    """verify_entry approvals without accepted_doi: the unique issue-free Crossref candidate."""
    clean = [c for c in result.get("candidates", []) if c.get("source") == "crossref" and c.get("doi")
             and not c.get("issues")]
    dois = {normalize_doi(c["doi"]) for c in clean}
    return (dois.pop(), None) if len(dois) == 1 else (None, f"{len(dois)} issue-free Crossref candidates")


def published_version(result):
    """A published version named by the saved repository record, or None."""
    text = json.dumps([c.get("raw_record") or c.get("raw") or {} for c in result.get("candidates", [])
                       if c.get("source") in PREPRINT_SOURCES or c.get("doi") == result.get("accepted_doi")])
    for pattern in (r'\\?"published\\?"\s*:\s*\\?"(10\.[^"\\]+)', r"<arxiv:doi[^>]*>([^<]+)<",
                    r'relationType\\?"\s*:\s*\\?"Is(?:Previous)?VersionOf[^}]*?relatedIdentifier\\?"\s*:\s*\\?"(10\.[^"\\]+)',
                    r'relatedIdentifier\\?"\s*:\s*\\?"(10\.[^"\\]+)\\?"[^}]*?relationType\\?"\s*:\s*\\?"Is(?:Previous)?VersionOf'):
        for match in re.finditer(pattern, text):
            doi = match[1].lower()
            if not doi.startswith(("10.48550/", "10.1101/")):
                return doi
    return None


def crossref_record(result, doi, client):
    for c in result.get("candidates", []):
        if c.get("source") == "crossref" and c.get("doi") and normalize_doi(c["doi"]) == doi and c.get("record"):
            return c["record"], "saved candidate"
    if client is None:
        return None, "offline"
    return client.trim(client.crossref_doi(doi)), "fetched"


def same_work(fields, record):
    """Title, first-author surname, year and venue of the DOI's Crossref record match the entry."""
    if record.get("type") != "journal-article":
        return f"Crossref type {record.get('type')}"
    title = " ".join(record.get("title") or [])
    if (notice_title(title, fields.get("title", "")) or record.get("update-to")
            or (record.get("relation") or {}).get("is-correction-of")):
        return "Crossref record is a notice/update"
    evidence, _ = compare_record(fields, record)
    bad = [f for f in ("title", "year", "journal") if not evidence.get(f, {}).get("match")]
    authors = record.get("author") or []
    try:
        from bibtexparser.customization import splitname
        parts = splitname(split_authors(fields.get("author", ""))[0], strict_mode=False)
        cited = " ".join(parts["von"] + parts["last"]).replace("{", "").replace("}", "")
        first = authors[0].get("family", "") if authors else ""
        letters = lambda value: re.sub(r"[^\w]", "", normalized(value))  # noqa: E731  'St Jacques' = 'St. Jacques'
        if not first or letters(cited) != letters(first):
            bad.append(f"first author {cited!r} vs {first!r}")
    except (ValueError, IndexError, AttributeError) as exc:
        bad.append(f"first author unreadable ({exc})")
    return "Crossref record differs: " + ", ".join(bad) if bad else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="no Crossref fetches (dry run)")
    args = parser.parse_args()
    entries = load_entries("cdl.bib")
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        client = None if args.offline else base.client_for(cache)
        results = current_results("cdl.bib", cache, entries)
        existing = {normalize_doi(e["fields"]["doi"]): k for k, e in entries.items()
                    if e["fields"].get("doi") and re.match(r"10\.", e["fields"]["doi"].strip().lower())}
        rows, skipped, fetched = [], {}, 0
        for key, entry in entries.items():
            result = results[key]
            if result["status"] != "metadata_verified" or str(entry["fields"].get("doi") or "").strip():
                continue
            source = result.get("accepted_source")
            route, doi, reason = None, None, None
            if source == "crossref":
                route = "crossref-accepted"
                doi, reason = cited_work_doi(entry, result)
            elif source is None and not result.get("accepted_doi"):
                route = "crossref-full-match (no accepted_doi bookkeeping)"
                doi, reason = full_match_candidate(result)
                if doi:
                    doi, reason = cited_work_doi(entry, dict(result, accepted_doi=doi))
            elif source in PUBMED_SOURCES and result.get("accepted_doi"):
                route = f"{source} record DOI, Crossref-confirmed"
                doi = normalize_doi(result["accepted_doi"])
                try:
                    record, how = crossref_record(result, doi, client)
                    fetched += how == "fetched"
                except ProviderError as exc:
                    record, how = None, f"Crossref fetch failed: {exc}"
                reason = same_work(entry["fields"], record) if record else f"no Crossref record ({how})"
                if reason:
                    doi = None
            elif source in PREPRINT_SOURCES and result.get("accepted_doi"):
                route = f"{source} repository DOI"
                doi = normalize_doi(result["accepted_doi"])
                published = published_version(result)
                if published:
                    doi, reason = None, f"published version {published} exists (preprint -> published swap list)"
            else:
                route = f"{source} without accepted DOI"
                reason = "accepted record has no DOI" if not result.get("accepted_doi") else "unsupported source"
            if doi and doi in existing:
                doi, reason = None, f"DOI already on {existing[doi]}"
            if doi and (doi != doi.lower() or not re.fullmatch(r"10\.\d{4,9}/[a-z0-9._;()/:<>\[\]+-]+", doi)):
                doi, reason = None, f"DOI needs manual formatting: {doi}"
            if not doi:
                skipped[key] = {"route": route, "entrytype": entry["fields"]["ENTRYTYPE"], "reason": reason}
                continue
            rows.append({"key": key, "fingerprint": entry["fingerprint"], "kind": "add_doi", "rule": route,
                         "accepted_source": source, "changes": {"doi": {"before": None, "after": doi}}})
            existing[doi] = key
    finally:
        cache.close()
    reasons = Counter(re.sub(r"[:(].*", "", s["reason"]).strip() for s in skipped.values())
    out = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "batch": "adddoi002", "count": len(rows),
           "by_route": dict(Counter(r["rule"] for r in rows)), "crossref_fetches": fetched,
           "skipped_by_reason": dict(reasons), "skipped": skipped, "proposals": rows}
    name = "adddoi002-proposals.json" if not args.offline else "adddoi002-offline-preview.json"
    (HERE / name).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("skipped", "proposals")}, indent=1))


if __name__ == "__main__":
    main()
