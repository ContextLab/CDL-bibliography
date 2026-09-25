"""Publication-coordinate repairs corroborated by PMC front matter and PubMed."""

from copy import deepcopy
import re

from auto_review import epmc_record, expanded_pages, reassess, safe_compare, unique_crossref_primaries
from fulltext_review import assess_fulltext
from verification import normalize_doi, normalize_publisher, normalized, split_authors, given_name_tokens, given_token_matches, same_suffix


def pmc_publisher_proposal(entry, previous):
    """Require final publisher front matter and the registry to agree on a repair."""
    fields = entry["fields"]
    if (fields.get("ENTRYTYPE") != "article" or not fields.get("publisher")
            or previous.get("status") != "needs_review" or previous.get("external_evidence")):
        return None
    choices = {}
    for source in previous.get("candidates", []):
        if source.get("source") != "pmc-jats":
            continue
        try:
            doi = normalize_doi(source["doi"])
            if fields.get("doi") and normalize_doi(fields["doi"]) != doi:
                continue
            # Publisher repairs keep the original rule: any duplicate primary holds
            # (tests/test_pmc_publisher_corrections.py 'duplicateprimary').
            primaries = [c for c in previous["candidates"] if c.get("source") == "crossref" and c.get("doi") == doi]
            if len(primaries) != 1:
                continue
            primary = primaries[0]
            med = source["medline_record"]
            response = {"body": source["raw_xml"], "url": source["url"], "retrieved_at": source["retrieved_at"],
                        "document_sha256": source.get("xml_sha256")}
            assessed = assess_fulltext(fields, primary, med, response)
            if (not assessed["issues"] or any(i.split(":", 1)[0] != "publisher" for i in assessed["issues"])
                    or not primary["record"].get("publisher")):
                continue
            publisher = assessed["record"].get("publisher", "")
            if (not publisher or normalize_publisher(publisher) != normalize_publisher(primary["record"]["publisher"])
                    or normalize_publisher(publisher) == normalize_publisher(fields["publisher"])):
                continue
            proposed = dict(fields, publisher=publisher)
            if safe_compare(proposed, primary["record"])[1]:
                continue
            mapped = epmc_record(med, primary["record"])
            evidence, issues = safe_compare(proposed, mapped)
            if (any(i.split(":", 1)[0] not in {"publisher", "isbn"} for i in issues)
                    or not all(evidence.get(f, {}).get("match") for f in ("title", "author", "year", "journal", "volume", "pages"))):
                continue
            checked = reassess(dict(entry, fields=proposed), previous)
            if checked["status"] != "metadata_verified" or checked.get("accepted_doi") != doi:
                continue
            choices[(doi, publisher)] = {"kind": "pmc_corroborated_publisher", "key": entry["key"],
                "fingerprint": entry["fingerprint"], "doi": doi, "pubmed_id": med["id"],
                "changes": {"publisher": {"before": fields["publisher"], "after": publisher}},
                "primary": deepcopy(primary), "publisher_source": deepcopy(source)}
        except (KeyError, ValueError, TypeError, AttributeError, IndexError):
            continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def preserves_byline_details(local, people):
    """Permit missing given-name additions, never lose or change supplied names."""
    from bibtexparser.customization import splitname
    names = split_authors(local)
    if len(names) != len(people):
        return False
    for name, person in zip(names, people):
        parsed = splitname(name, strict_mode=True)
        if (normalized(" ".join(parsed["von"] + parsed["last"])) != normalized(person.get("family", ""))
                or not same_suffix(" ".join(parsed["jr"]), person.get("suffix", ""))):
            return False
        old = given_name_tokens(" ".join(parsed["first"]))
        new = given_name_tokens(person.get("given", ""))
        if (not old or len(old) > len(new)
                or any(not given_token_matches(a, b) for a, b in zip(old, new))):
            return False
    return True


def pmc_coordinate_proposal(entry, previous, *, include_authors=False):
    fields = entry["fields"]
    if (fields.get("ENTRYTYPE") != "article" or previous.get("status") != "needs_review"
            or previous.get("external_evidence")):
        return None
    choices = {}
    for source in previous.get("candidates", []):
        if source.get("source") != "pmc-jats":
            continue
        try:
            doi = normalize_doi(source["doi"])
            if fields.get("doi") and normalize_doi(fields["doi"]) != doi:
                continue
            # Byte-identical duplicate deposits collapse; differing records stay ambiguous.
            primaries = unique_crossref_primaries(previous["candidates"], doi)
            if len(primaries) != 1:
                continue
            primary = primaries[0]
            med = source["medline_record"]
            response = {"body": source["raw_xml"], "url": source["url"],
                        "retrieved_at": source["retrieved_at"], "document_sha256": source.get("xml_sha256")}
            assessed = assess_fulltext(fields, primary, med, response)
            issues = assessed["issues"]
            allowed = {"year", "volume", "number", "pages"}
            if include_authors:
                allowed.add("author")
            if not issues or any(i.split(":", 1)[0] not in allowed for i in issues):
                continue
            record = assessed["record"]
            mapped = epmc_record(med, primary["record"])
            if (not set(record["ISSN"]) & set(mapped.get("ISSN", []))
                    or not set(record["ISSN"]) & set(primary["record"].get("ISSN", []))):
                continue
            # Establish the intended work from unchanged title and complete
            # ordered byline before proposing any publication-coordinate edits.
            original_evidence = safe_compare(fields, mapped)[0]
            identity_fields = ("title",) if include_authors else ("title", "author")
            if (not all(assessed["evidence"].get(f, {}).get("match") and original_evidence.get(f, {}).get("match")
                        for f in identity_fields)
                    or not safe_compare(fields, primary["record"])[0].get("title", {}).get("match")):
                continue
            values = {"year": str(record["published"]["date-parts"][0][0]),
                      "volume": str(record.get("volume") or ""),
                      "number": str(record.get("issue") or ""),
                      "pages": expanded_pages(record.get("page") or record.get("article-number") or "").replace("-", "--")}
            changed = {i.split(":", 1)[0] for i in issues}
            if include_authors:
                if "author" not in changed or not preserves_byline_details(fields.get("author", ""), record["author"]):
                    continue
                from correction_proposals import source_authors
                values["author"] = source_authors(record, fields.get("author"))
            if any(not values[f] or values[f] == fields.get(f) for f in changed):
                continue
            from correction_proposals import shortens_pages, surname_change_hold
            if "pages" in changed and shortens_pages(fields.get("pages"), values["pages"]):
                continue  # a cited range is never shortened (2026-09-24/25)
            if "author" in changed and surname_change_hold(entry["key"], fields.get("author"), values["author"],
                                                           corroborated=True):
                continue
            if (not re.fullmatch(r"[1-9]\d{3}", values["year"])
                    or not re.fullmatch(r"[1-9]\d*", values["volume"])
                    or ("number" in changed and not re.fullmatch(r"[1-9]\d*", values["number"]))
                    or not re.fullmatch(r"[a-z]{0,3}\d+(?:--[a-z]{0,3}\d+(?:\.e\d+)?)?", values["pages"])):
                continue
            proposed = dict(fields, **{f: values[f] for f in changed})
            new = assess_fulltext(proposed, primary, med, response)
            secondary_evidence, secondary_issues = safe_compare(proposed, mapped)
            if (new["issues"] or any(i.split(":", 1)[0] not in {"publisher", "isbn"} for i in secondary_issues)
                    or not all(secondary_evidence.get(f, {}).get("match") for f in ("title", "author", "year", "journal", "volume", "pages"))):
                continue
            checked = reassess(dict(entry, fields=proposed), previous)
            if checked["status"] != "metadata_verified" or checked.get("accepted_doi") != doi:
                continue
            changes = {f: {"before": fields.get(f), "after": values[f]} for f in sorted(changed)}
            identity = (doi, tuple((f, v["after"]) for f, v in changes.items()))
            choices[identity] = {"kind": "pmc_corroborated_given_names" if include_authors else "pmc_corroborated_coordinates", "key": entry["key"],
                                 "fingerprint": entry["fingerprint"], "doi": doi,
                                 "changes": changes, "pubmed_id": med["id"],
                                 "primary": deepcopy(primary), "publisher_source": deepcopy(source)}
        except (KeyError, ValueError, TypeError, AttributeError, IndexError):
            continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def pmc_article_number_proposal(entry, previous):
    """Article-number journals: pages = article number, drop a spurious number.

    Rule A1b (verification/resolution-plan-2026-09-22/plan-doi-conflicts.md),
    resolver 28. All of the following must hold:
    1. exactly one DOI-linked JATS front matter whose article number equals the
       DOI-linked PubMed pageInfo (source_locators coordinates), and one
       Crossref record for that DOI after collapsing identical copies;
    2. JATS, PubMed and (when present) Crossref volumes equal the proposed volume;
    3. the issue is taken only when JATS, PubMed and Crossref agree or are all
       silent; with all silent, ``number`` is deleted; any other shape is held;
    4. the current ``pages`` is empty, ``1--N``, a doi.org URL of this same DOI,
       or already the article number; the current ``number`` is empty, the
       article number, or the agreed issue (anything else is held for a human);
    5. title and ordered byline already match JATS and Crossref;
    6. the full proposal passes JATS front-matter comparison with no issue and
       reassessment verifies the same DOI.
    """
    from source_locators import source_coordinates
    fields = entry["fields"]
    if (fields.get("ENTRYTYPE") != "article" or previous.get("status") != "needs_review"
            or previous.get("external_evidence")):
        return None
    sources = {}
    for source in previous.get("candidates", []):
        coords = source_coordinates(source)
        if coords:
            sources.setdefault(coords[0], []).append((source, coords))
    choices = {}
    for doi, found in sources.items():
        try:
            if fields.get("doi") and normalize_doi(fields["doi"]) != doi:
                continue
            # Repeated retrievals of the same front matter must all state the
            # same coordinates; each copy is checked again below.
            if len({coords for _, coords in found}) != 1:
                continue
            source, (_, volume, page) = found[0]
            if not re.fullmatch(r"[a-z]{0,3}\d+", page):
                continue  # an article number, not a page range
            primaries = unique_crossref_primaries(previous["candidates"], doi)
            if len(primaries) != 1:
                continue
            primary = primaries[0]
            record = primary["record"]
            med = source["medline_record"]
            response = {"body": source["raw_xml"], "url": source["url"],
                        "retrieved_at": source["retrieved_at"], "document_sha256": source.get("xml_sha256")}
            front = assess_fulltext(fields, primary, med, response)
            jats = front["record"]
            if record.get("volume") and normalized(str(record["volume"])) != volume:
                continue
            issues = {str(v) for v in (jats.get("issue"), med.get("journalInfo", {}).get("issue"),
                                       record.get("issue")) if v}
            if len(issues) > 1:
                continue
            if issues and not (jats.get("issue") and med.get("journalInfo", {}).get("issue")):
                continue  # one source's issue alone does not decide the number
            issue = next(iter(issues)) if issues else None
            pages = fields.get("pages")
            if pages:
                url = re.fullmatch(r"(?:https?://)?(?:dx\.)?doi\.org/(.+)", pages.strip())
                span = re.fullmatch(r"1\s*-+\s*(\d+)", pages.strip())
                if not (span or pages.strip() == page
                        or (url and normalize_doi(url[1]) == doi)):
                    continue
            number = fields.get("number")
            if number and number not in {page, issue}:
                continue
            if not all(front["evidence"].get(f, {}).get("match") for f in ("title", "author")):
                continue
            if not safe_compare(fields, record)[0].get("title", {}).get("match"):
                continue
            from correction_proposals import shortens_pages
            if shortens_pages(fields.get("pages"), page):
                continue  # a cited range is never shortened (2026-09-24/25)
            proposed = dict(fields, volume=volume, pages=page)
            if issue:
                proposed["number"] = issue
            else:
                proposed.pop("number", None)
            if proposed == fields:
                continue
            if any(assess_fulltext(proposed, primary, copy["medline_record"],
                                   {"body": copy["raw_xml"], "url": copy["url"], "retrieved_at": copy["retrieved_at"],
                                    "document_sha256": copy.get("xml_sha256")})["issues"]
                   for copy, _ in found):
                continue
            checked = reassess(dict(entry, fields=proposed), previous)
            if checked["status"] != "metadata_verified" or checked.get("accepted_doi") != doi:
                continue
            changes = {f: {"before": fields.get(f), "after": proposed.get(f)}
                       for f in ("volume", "number", "pages") if fields.get(f) != proposed.get(f)}
            choices[doi] = {"kind": "pmc_article_number", "rule": "A1b", "key": entry["key"],
                            "fingerprint": entry["fingerprint"], "doi": doi, "changes": changes,
                            "pubmed_id": med["id"], "primary": deepcopy(primary),
                            "publisher_source": deepcopy(source)}
        except (KeyError, ValueError, TypeError, AttributeError, IndexError):
            continue
    return next(iter(choices.values())) if len(choices) == 1 else None


def replace_pmc_coordinates(text, entry, proposal):
    from correction_proposals import replace_field, replace_pagination, replace_publication
    if not 1 <= len(proposal["changes"]) <= 4 or set(proposal["changes"]) - {"year", "volume", "number", "pages"}:
        raise ValueError("Unsupported PMC coordinate edit")
    if len(proposal["changes"]) > 1:
        return replace_publication(text, entry, proposal)
    if "pages" in proposal["changes"]:
        return replace_pagination(text, {entry["key"]: entry}, [proposal])
    return replace_field(text, entry, proposal)


def replace_pmc_given_names(text, entry, proposal):
    from correction_proposals import replace_field, replace_pagination
    if not 1 <= len(proposal["changes"]) <= 5 or set(proposal["changes"]) - {"year", "volume", "number", "pages", "author"} or "author" not in proposal["changes"]:
        raise ValueError("Unsupported PMC byline edit")
    if text.count(entry["raw"]) != 1:
        raise ValueError("Raw entry is not unique")
    working = deepcopy(entry)
    for field, change in proposal["changes"].items():
        single = dict(proposal, changes={field: change})
        if field == "pages":
            modified = replace_pagination(working["raw"], {working["key"]: working}, [single])
        else:
            modified = replace_field(working["raw"], working, single)
        working["raw"] = modified
        working["fields"][field] = change["after"]
    return text.replace(entry["raw"], working["raw"], 1)
