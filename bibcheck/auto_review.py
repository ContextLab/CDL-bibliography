"""Resumable automatic review using saved Crossref evidence and PubMed metadata.

No model votes, citation edits, or human approvals. Secondary evidence can resolve
only explicitly supported differences; substantive source conflicts remain open.
"""

from copy import deepcopy
import re

from verification import (
    ACCEPTED,
    POLICY,
    ProviderError,
    compare_record,
    export_snapshot,
    load_entries,
    normalize_doi,
    normalize_pages,
    normalized,
    outcome,
    record_advisories,
    run_lock,
    validate_output_path,
    write_report,
)

EPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EPMC_FIELDS = {
    "id",
    "source",
    "pmcid",
    "doi",
    "title",
    "authorList",
    "journalInfo",
    "pubYear",
    "pageInfo",
    "pubTypeList",
    "isOpenAccess",
    "firstPublicationDate",
    "commentCorrectionList",
    "isRetracted",
    "fullTextUrlList",
}


def safe_compare(fields, record):
    try:
        return compare_record(fields, record)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {}, [f"Unsupported source metadata: {exc}"]


def select_result(fields, candidates, attempts):
    """Apply DOI and competing-work guards to all automatic routes alike."""
    supplied = normalize_doi(fields["doi"]) if fields.get("doi") else None
    pubmed_ids = {}
    for c in candidates:
        if c.get("source") == "europepmc":
            pubmed_ids.setdefault(normalize_doi(c["doi"]), set()).add(
                c.get("raw_record", {}).get("id")
            )
    good = {}
    for candidate in candidates:
        if candidate.get("source") not in {"crossref", "europepmc", "pmc-jats"}:
            continue
        if candidate.get("issues") or not candidate.get("evidence"):
            continue
        doi = normalize_doi(candidate["doi"])
        if len(pubmed_ids.get(doi, set())) > 1:
            continue  # One DOI attached to multiple PubMed records is ambiguous.
        if supplied and doi != supplied:
            continue
        good[doi] = candidate
    if len(good) == 1:
        selected = next(iter(good))
        rivals = [
            c
            for c in candidates
            if c.get("doi")
            and normalize_doi(c["doi"]) != selected
            and c.get("evidence", {}).get("title", {}).get("match")
            and c.get("evidence", {}).get("author", {}).get("match")
        ]
        if supplied or not rivals:
            return dict(
                outcome("metadata_verified", [], candidates, attempts),
                accepted_doi=selected,
                accepted_source=good[selected]["source"],
            )
    return outcome(
        "needs_review",
        ["No unambiguous, fully supported metadata match"],
        candidates,
        attempts,
    )


def reassess(entry, previous):
    """Reevaluate saved evidence; an old-policy human approval is not migrated."""
    if not previous:
        return outcome("pending", ["Run crossref verify to collect initial evidence"])
    if previous["status"] == "human_verified" and previous.get("policy") == POLICY:
        return previous
    candidates = []
    for original in previous.get("candidates", []):
        if original.get("source") == "crossref":
            evidence, issues = safe_compare(entry["fields"], original["record"])
            candidates.append(
                dict(
                    original,
                    evidence=evidence,
                    issues=issues,
                    advisories=record_advisories(entry["fields"], original["record"]),
                )
            )
        elif original.get("source") not in {"europepmc", "pmc-jats"}:
            candidates.append(original)
    # Reconstruct secondary judgments from raw records, not cached boolean flags.
    for original in previous.get("candidates", []):
        if original.get("source") == "europepmc" and original.get("raw_record"):
            for primary in list(candidates):
                if primary.get("source") == "crossref" and primary.get(
                    "doi"
                ) == original.get("doi"):
                    candidates.append(
                        assess_epmc(
                            entry["fields"],
                            primary,
                            original["raw_record"],
                            original["retrieved_at"],
                            original["request_url"],
                        )
                    )
                    break
    for original in previous.get("candidates", []):
        if original.get("source") == "pmc-jats" and original.get("raw_xml"):
            from fulltext_review import assess_fulltext

            for primary in list(candidates):
                if primary.get("source") == "crossref" and primary.get(
                    "doi"
                ) == original.get("doi"):
                    candidates.append(
                        assess_fulltext(
                            entry["fields"],
                            primary,
                            original["medline_record"],
                            {
                                "body": original["raw_xml"],
                                "url": original["url"],
                                "retrieved_at": original["retrieved_at"],
                                "document_sha256": original["xml_sha256"],
                            },
                        )
                    )
                    break
    try:
        result = select_result(
            entry["fields"], candidates, previous.get("attempts", [])
        )
    except ValueError as exc:
        result = outcome(
            "needs_review", [str(exc)], candidates, previous.get("attempts", [])
        )
    if previous["status"] == "provider_error" and not candidates:
        result = previous
    if previous.get("external_evidence"):
        result["external_evidence"] = previous["external_evidence"]
        result["status"] = "needs_review"
        result["issues"] = ["Attached external evidence requires explicit adjudication"]
    if previous.get("research_attempt"):
        result["research_attempt"] = previous["research_attempt"]
    if previous.get("discovery_review"):
        result["discovery_review"] = previous["discovery_review"]
    result["auto_review"] = dict(previous.get("auto_review", {}), policy=POLICY)
    return result


def target_dois(result):
    """Discovery requires title agreement, or author/year plus bibliographic anchors."""
    found = []
    for candidate in result.get("candidates", []):
        if candidate.get("source") != "crossref":
            continue
        evidence = candidate.get("evidence", {})

        def matches(field):
            return evidence.get(field, {}).get("match", False)

        if matches("title") or (
            matches("author")
            and matches("year")
            and matches("pages")
            and matches("volume")
        ):
            try:
                found.append(normalize_doi(candidate["doi"]))
            except ValueError:
                pass
    return list(dict.fromkeys(found))


def fetch_epmc(client, dois):
    """One paced request for up to 25 exact DOIs, never 25 parallel calls."""
    dois = list(dict.fromkeys(normalize_doi(d) for d in dois))
    if not dois or len(dois) > 25 or any(re.search(r'["\\\s]', d) for d in dois):
        raise ValueError("Europe PMC batches need 1–25 DOIs without query delimiters")
    response = client.get(
        EPMC_URL,
        {
            "query": " OR ".join('DOI:"' + d + '"' for d in dois),
            "format": "json",
            "resultType": "core",
            "pageSize": 100,
        },
    )
    body = response["body"]
    if response["http_status"] != 200 or not isinstance(body, dict):
        raise ProviderError("Europe PMC did not return a search response")
    results = body.get("resultList", {}).get("result")
    count = body.get("hitCount")
    if not isinstance(results, list) or type(count) is not int or count != len(results):
        raise ProviderError(
            "Europe PMC response is malformed or truncated; retry a smaller batch"
        )
    indexed = {doi: [] for doi in dois}
    for record in results:
        if not isinstance(record, dict):
            raise ProviderError("Malformed Europe PMC record")
        try:
            doi = normalize_doi(record.get("doi", ""))
        except ValueError:
            continue
        if doi in indexed and record.get("source") == "MED":
            indexed[doi].append({k: v for k, v in record.items() if k in EPMC_FIELDS})
    return indexed, response


def expanded_pages(value):
    """Expand a numeric abbreviated end page (123-9 -> 123-129), retaining prefixes."""
    value = normalize_pages(value)
    match = re.fullmatch(r"([a-z]*)(\d+)-([a-z]*)(\d+)", value)
    if not match:
        return value
    prefix, first, last_prefix, last = match.groups()
    if last_prefix and last_prefix != prefix:
        return value
    if len(last) < len(first):
        end = int(first[: len(first) - len(last)] + last)
        if end < int(first):
            end += 10 ** len(last)
        last = str(end)
    return f"{prefix}{first}-{last_prefix or prefix}{last}"


def epmc_record(raw, primary):
    if raw.get("source") != "MED" or not re.fullmatch(r"\d+", str(raw.get("id", ""))):
        raise ValueError("Secondary evidence must be an identified PubMed record")
    if normalize_doi(raw["doi"]) != normalize_doi(primary["DOI"]):
        raise ValueError("Secondary DOI differs from Crossref DOI")
    types = raw.get("pubTypeList", {}).get("pubType", [])
    if (
        "Journal Article" not in types
        or any(
            word in str(types).lower()
            for word in ("retract", "erratum", "preprint", "correction")
        )
        or raw.get("commentCorrectionList")
        or raw.get("isRetracted") == "Y"
    ):
        raise ValueError(
            "Secondary publication type or correction relationship requires review"
        )
    info = raw.get("journalInfo", {})
    journal = info.get("journal", {})
    issns = [journal[k] for k in ("issn", "essn") if journal.get(k)]
    venues = [
        journal[k]
        for k in ("title", "medlineAbbreviation", "isoabbreviation")
        if journal.get(k)
    ]
    # These are linked by identifier, not a hand-written/fuzzy journal alias list.
    if set(issns) & set(primary.get("ISSN", [])):
        venues += primary.get("container-title", [])
    authors = []
    for person in raw.get("authorList", {}).get("author", []):
        given = person.get("firstName", "")
        if not given and re.fullmatch(r"[A-Z]{1,5}", person.get("initials", "")):
            given = " ".join(person["initials"])
        authors.append(
            {
                "given": given,
                "family": person.get("lastName", ""),
                "suffix": person.get("suffix", ""),
            }
        )
    title = raw.get("title", "")
    # MEDLINE adds sentence punctuation to titles. Only one final period is
    # removed; colons, question marks, internal punctuation and accents survive.
    if title.endswith(".") and not title.endswith(".."):
        title = title[:-1]
    year = info.get("yearOfPublication")
    if not re.fullmatch(r"[1-9]\d{3}", str(year)):
        raise ValueError("Secondary record lacks a journal issue publication year")
    return {
        "DOI": raw["doi"],
        "type": "journal-article",
        "title": [title],
        "author": authors,
        "container-title": venues,
        "ISSN": issns,
        "published": {"date-parts": [[year]]},
        "volume": info.get("volume"),
        "issue": info.get("issue"),
        "page": expanded_pages(raw.get("pageInfo", "")),
    }


def compatible_authors(primary, secondary):
    """Missing given-name tokens may be supplemented; conflicting names cannot."""
    first, second = primary.get("author", []), secondary.get("author", [])
    if not first or len(first) != len(second):
        return False
    for a, b in zip(first, second):
        if normalized(a.get("family", "")) != normalized(b.get("family", "")):
            return False
        if normalized(a.get("suffix", "")) != normalized(b.get("suffix", "")):
            return False
        aa = normalized(a.get("given", "")).replace(".", "").split()
        bb = normalized(b.get("given", "")).replace(".", "").split()
        for x, y in zip(aa, bb):
            if x != y and not ((len(x) == 1 or len(y) == 1) and x[0] == y[0]):
                return False
    return True


def assess_epmc(fields, primary, raw, retrieved_at, request_url):
    evidence, issues, resolved, mapped = {}, [], [], {}
    try:
        mapped = epmc_record(raw, primary["record"])
        secondary_evidence, secondary_issues = safe_compare(fields, mapped)
        evidence = deepcopy(primary.get("evidence", {}))
        # Every overridden field must itself pass full local-vs-secondary checks.
        for issue in primary.get("issues", []):
            field = issue.split(":", 1)[0]
            supported = secondary_evidence.get(field, {}).get("match")
            can_resolve = False
            if field == "author" and supported:
                can_resolve = compatible_authors(primary["record"], mapped)
            elif field == "journal" and supported:
                can_resolve = bool(
                    set(mapped["ISSN"]) & set(primary["record"].get("ISSN", []))
                )
            elif field == "pages" and supported:
                original = expanded_pages(primary["record"].get("page", ""))
                target = expanded_pages(fields.get("pages", ""))
                can_resolve = (
                    not original
                    or original == target
                    or ("-" not in original and original == target.split("-")[0])
                )
            elif (
                field == "year" and supported and issue.startswith("year: conflicting")
            ):
                dates = (
                    primary["record"].get("published-print", {}).get("date-parts", [])
                )
                can_resolve = (
                    len(dates) == 1
                    and dates[0]
                    and str(dates[0][0]) == fields.get("year")
                    and all(
                        secondary_evidence.get(f, {}).get("match")
                        and primary["evidence"].get(f, {}).get("match")
                        for f in ("volume", "pages")
                    )
                )
            if can_resolve:
                resolved.append(
                    {"finding": issue, "authority": "PubMed via Europe PMC"}
                )
                evidence[field] = dict(
                    secondary_evidence[field], source_name="europepmc"
                )
            else:
                issues.append(issue)
        # Independently establish identity; metadata fields missing in MEDLINE
        # cannot waive an original Crossref blocker or hide a conflicting value.
        for field in (
            "title",
            "author",
            "year",
            "journal",
            "volume",
            "number",
            "pages",
        ):
            check = secondary_evidence.get(field)
            if check and not check["match"]:
                issues.append(f"Secondary {field}: missing evidence or mismatch")
        if primary["record"].get("type") != "journal-article":
            issues.append(
                "Crossref publication type differs from secondary journal article"
            )
        # No supplied field disappears: every original blocker is retained unless
        # resolved by the explicit rules above; extra MEDLINE fields are evidence.
        if not secondary_evidence:
            issues += secondary_issues
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        issues.append(f"Unsupported secondary evidence: {exc}")
    return {
        "source": "europepmc",
        "doi": primary["doi"],
        "url": "https://europepmc.org/article/MED/" + str(raw.get("id", "")),
        "record": mapped,
        "raw_record": raw,
        "evidence": evidence,
        "issues": list(dict.fromkeys(issues)),
        "resolved_findings": resolved,
        "retrieved_at": retrieved_at,
        "request_url": request_url,
    }


def run_auto_review(filename, cache, report, client=None, limit=None, snapshot=None):
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    with run_lock(cache):
        entries = load_entries(filename)
        try:
            results = {}
            for key, entry in entries.items():
                previous = cache.get(filename, entry, any_policy=True)
                compare_previous = {
                    k: v
                    for k, v in (previous or {}).items()
                    if k not in {"key", "fingerprint", "checked_at", "policy"}
                }
                result = (
                    compare_previous
                    if previous
                    and previous.get("policy") == POLICY
                    and previous.get("auto_review", {}).get("policy") == POLICY
                    else reassess(entry, previous)
                )
                if previous and (
                    previous.get("policy") != POLICY or compare_previous != result
                ):
                    result = cache.put(filename, entry, result)
                results[key] = result
            print(
                f"Offline reassessment: {sum(r['status'] in ACCEPTED for r in results.values())} accepted",
                flush=True,
            )
            if client is not None:
                targets = {}
                selected = 0
                for key, result in results.items():
                    if (
                        result.get("external_evidence")
                        or result["status"] != "needs_review"
                        or result.get("auto_review", {}).get("epmc_checked")
                    ):
                        continue
                    dois = target_dois(result)
                    if not dois:
                        continue
                    if limit is not None and selected >= limit:
                        break
                    selected += 1
                    for doi in dois:
                        targets.setdefault(doi, []).append(key)
                dois = list(targets)
                remaining = {
                    key: set(target_dois(results[key]))
                    for keys in targets.values()
                    for key in keys
                }
                for start in range(0, len(dois), 25):
                    batch = dois[start : start + 25]
                    indexed, response = fetch_epmc(client, batch)
                    for doi in batch:
                        for key in targets[doi]:
                            result = results[key]
                            for primary in list(result["candidates"]):
                                if (
                                    primary.get("source") == "crossref"
                                    and normalize_doi(primary["doi"]) == doi
                                ):
                                    for raw in indexed[doi]:
                                        result["candidates"].append(
                                            assess_epmc(
                                                entries[key]["fields"],
                                                primary,
                                                raw,
                                                response["retrieved_at"],
                                                response["url"],
                                            )
                                        )
                            remaining[key].discard(doi)
                            result = dict(
                                select_result(
                                    entries[key]["fields"],
                                    result["candidates"],
                                    result["attempts"],
                                ),
                                auto_review={
                                    "policy": POLICY,
                                    "epmc_checked": not remaining[key],
                                },
                            )
                            result["attempts"].append(
                                {
                                    "source": "europepmc",
                                    "doi": doi,
                                    "url": response["url"],
                                    "matches": len(indexed[doi]),
                                    "retrieved_at": response["retrieved_at"],
                                }
                            )
                            results[key] = cache.put(filename, entries[key], result)
                    print(
                        f"Second-source DOIs checked: {min(start + 25, len(dois))}/{len(dois)}; requests: {client.requests}",
                        flush=True,
                    )
        finally:
            final = write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
    return final
