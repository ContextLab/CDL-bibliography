"""Publication-coordinate repairs corroborated by PMC front matter and PubMed."""

from copy import deepcopy
import re

from auto_review import epmc_record, expanded_pages, reassess, safe_compare
from fulltext_review import assess_fulltext
from verification import normalize_doi, normalize_publisher, normalized, split_authors, given_name_tokens, given_token_matches, normalize_author_suffix


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
                or normalize_author_suffix(" ".join(parsed["jr"])) != normalize_author_suffix(person.get("suffix", ""))):
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
            primaries = [c for c in previous["candidates"] if c.get("source") == "crossref" and c.get("doi") == doi]
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
                values["author"] = source_authors(record)
            if any(not values[f] or values[f] == fields.get(f) for f in changed):
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
