"""Resumable automatic review using saved Crossref evidence and PubMed metadata.

No model votes, citation edits, or human approvals. Secondary evidence can resolve
only explicitly supported differences; substantive source conflicts remain open.
"""

from copy import deepcopy
import re

from verification import (
    ACCEPTED,
    author_evidence,
    assess_candidates,
    collapse_apa_twins,
    dumps,
    POLICY,
    ProviderError,
    compare_record,
    print_year_route,
    rival_blocks,
    export_snapshot,
    given_name_tokens,
    given_token_matches,
    load_entries,
    normalize_author_suffix,
    same_suffix,
    source_name_suffix,
    without_suffix_tokens,
    normalize_doi,
    normalize_pages,
    normalized,
    split_authors,
    outcome,
    record_advisories,
    run_lock,
    validate_output_path,
    valid_doi_alias,
    write_report,
)
from bibtexparser.customization import splitname

EPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
# Resolver upgrades revisit unresolved saved evidence once. Previously accepted
# entries retain their approval and original checked_at without reassessment.
RESOLVER_VERSION = 30  # 30: verification/machinery-2026-09-25 PR-test fixes. 29: verification/apply-2026-09-25 stage 1 rules (suffixes ignored; catalogue
#     publisher same-firm variants). 28: verification/phase0-2026-09-22 rules
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


def safe_compare(fields, record, doi_alias=None):
    try:
        return compare_record(fields, record, doi_alias)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {}, [f"Unsupported source metadata: {exc}"]


def secondary_notice_flags(candidates):
    """A matching registry row cannot overrule a DOI-linked correction notice."""
    flagged = set()
    for candidate in candidates:
        if candidate.get('source') == 'arxiv-repository':
            from arxiv_review import notice_dois
            flagged.update(notice_dois(candidate))
        if candidate.get('source') == 'biorxiv-preprint':
            from preprint_review import notice_dois
            flagged.update(notice_dois(candidate))
            continue
        if candidate.get("source") == "pmc-jats":
            from pmc_metadata import notice_dois
            flagged.update(notice_dois(candidate))
            continue
        if candidate.get("source") != "europepmc":
            continue
        raw = candidate.get("raw_record", {})
        try:
            doi = normalize_doi(candidate["doi"])
            if (raw.get("source") != "MED" or not re.fullmatch(r"\d+", str(raw.get("id", "")))
                    or normalize_doi(raw.get("doi", "")) != doi):
                continue
            types = raw.get("pubTypeList", {}).get("pubType", [])
            relations = raw.get("commentCorrectionList", {}).get("commentCorrection", [])
            labels = list(types) + [r.get("type", "") for r in relations]
            if raw.get("isRetracted") == "Y" or any(
                word in str(label).lower() for label in labels
                for word in ("errat", "retract", "correct", "expression of concern")
            ):
                flagged.add(doi)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return flagged


class PubmedSuffixConflict(ValueError):
    pass


def pubmed_author_suffix(person):
    """Retain a suffix in PubMed's exact surname-initials-suffix full name."""
    suffix = person.get("suffix", "")
    full = normalized(person.get("fullName", ""))
    family, initials = person.get("lastName", ""), person.get("initials", "")
    if not family or not initials:
        return suffix
    prefix = normalized(family + " " + initials) + " "
    if full.startswith(prefix):
        tail = full[len(prefix):]
        if re.fullmatch(r"(?:jr|sr|ii|iii|iv|v|vi|vii|viii|ix|x)\.?", tail):
            if suffix and normalize_author_suffix(suffix) != normalize_author_suffix(tail):
                raise PubmedSuffixConflict("Conflicting PubMed author suffix fields")
            if suffix:
                return suffix
            return tail.rstrip(".").upper() if tail[0] in "ivx" else tail.rstrip(".").capitalize()
    return suffix


def secondary_suffix_dois(candidates):
    """Identify source-addressed suffix witnesses, independent of entry text."""
    found = set()
    for candidate in candidates:
        raw = candidate.get("raw_record", {})
        try:
            doi = normalize_doi(candidate["doi"])
            if (candidate.get("source") != "europepmc" or raw.get("source") != "MED"
                    or not re.fullmatch(r"\d+", str(raw.get("id", "")))
                    or normalize_doi(raw.get("doi", "")) != doi):
                continue
            for person in raw.get("authorList", {}).get("author", []):
                try:
                    suffix = pubmed_author_suffix(person)
                except PubmedSuffixConflict:
                    suffix = "conflicting"
                if suffix:
                    found.add(doi)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return found


def secondary_suffix_conflicts(fields, candidates):
    """A DOI-linked explicit suffix that differs from the citation's.

    User decision 2026-09-24/25: recognized suffixes (Jr, Sr, II, III, IV) are
    ignored on both sides, so they never conflict; a PubMed record whose own
    suffix fields disagree is ignored for the same reason. Any other suffix text
    still conflicts."""
    flagged = set()
    for candidate in candidates:
        dois = secondary_suffix_dois([candidate])
        if not dois:
            continue
        try:
            names = split_authors(fields.get("author", ""))
            people = candidate["raw_record"]["authorList"]["author"]
            if len(names) != len(people):
                continue
            for name, person in zip(names, people):
                parts = splitname(name, strict_mode=True)
                if normalized(" ".join(parts["von"] + parts["last"])) != normalized(person.get("lastName", "")):
                    continue
                try:
                    suffix = pubmed_author_suffix(person)
                except PubmedSuffixConflict:
                    continue
                if suffix and not same_suffix(" ".join(parts["jr"]), suffix):
                    flagged.update(dois)
        except (ValueError, KeyError, TypeError, AttributeError):
            flagged.update(dois)
    return flagged


def select_result(fields, candidates, attempts):
    """Apply DOI and competing-work guards to all automatic routes alike."""
    supplied = normalize_doi(fields["doi"]) if fields.get("doi") else None
    aliases = {}
    for candidate in candidates:
        receipt = candidate.get("doi_alias") or {}
        prime = candidate.get("record", {}).get("DOI")
        requested = receipt.get("requested_doi")
        if candidate.get("source") == "crossref" and valid_doi_alias(receipt, requested, prime):
            aliases.setdefault(normalize_doi(requested), set()).add(normalize_doi(prime))
    aliases = {alias: next(iter(primes)) for alias, primes in aliases.items() if len(primes) == 1}
    supplied = aliases.get(supplied, supplied)
    flagged = {aliases.get(doi, doi) for doi in secondary_notice_flags(candidates)}
    suffix_conflicts = {aliases.get(doi, doi) for doi in secondary_suffix_conflicts(fields, candidates)}
    from source_locators import locator_conflicts
    coordinates = {aliases.get(doi, doi) for doi in locator_conflicts(fields, candidates)}
    pubmed_ids = {}
    for c in candidates:
        if c.get("source") == "europepmc":
            doi = normalize_doi(c["doi"])
            pubmed_ids.setdefault(aliases.get(doi, doi), set()).add(
                c.get("raw_record", {}).get("id")
            )
    good = {}
    for candidate in candidates:
        if candidate.get("source") not in {
            "crossref",
            "europepmc",
            "pmc-jats",
            "publisher-head",
            "catalogue-imprint",
        }:
            continue
        if not candidate.get("evidence"):
            continue
        if candidate.get("issues") and not print_year_route(fields, candidate, candidates, attempts):
            continue
        doi = normalize_doi(candidate["doi"])
        if doi in aliases:
            continue  # An old alias record cannot override the prime metadata.
        if doi in flagged or doi in suffix_conflicts or doi in coordinates:
            continue
        if len(pubmed_ids.get(doi, set())) > 1:
            continue  # One DOI attached to multiple PubMed records is ambiguous.
        if supplied and doi != supplied:
            continue
        good[doi] = candidate
    twins = set()
    if len(good) == 2 and not supplied:
        # Resolver 28: two clean APA DOI forms of one work are one choice.
        primaries = {doi: unique_crossref_primaries(candidates, doi) for doi in good}
        if all(len(p) == 1 for p in primaries.values()):
            kept = collapse_apa_twins({doi: p[0] for doi, p in primaries.items()})
            if len(kept) == 1:
                twins = set(good)
                good = {doi: good[doi] for doi in kept}
    if len(good) == 1:
        selected = next(iter(good))
        chosen = (unique_crossref_primaries(candidates, selected) or [good[selected]])[0]
        rivals = [
            c
            for c in candidates
            if c.get("doi")
            and aliases.get(normalize_doi(c["doi"]), normalize_doi(c["doi"])) != selected
            and normalize_doi(c["doi"]) not in twins
            and c.get("evidence", {}).get("title", {}).get("match")
            and c.get("evidence", {}).get("author", {}).get("match")
            and rival_blocks(fields, chosen, c)
        ]
        if supplied or not rivals:
            return dict(
                outcome("metadata_verified", [], candidates, attempts),
                accepted_doi=selected,
                accepted_source=good[selected]["source"],
            )
    # Resolver 28: report negative DOI-linked evidence only when it belongs to
    # the cited work (supplied DOI, or a DOI whose record is plausibly the work).
    # The exclusions from `good` above are unchanged and apply to every DOI.
    cited = cited_work_dois(fields, candidates, supplied, aliases)
    return outcome(
        "needs_review",
        ["No unambiguous, fully supported metadata match"]
        + (["DOI-linked source correction/retraction notice requires adjudication"] if flagged & cited else [])
        + (["DOI-linked PubMed author suffix conflicts with the citation"] if suffix_conflicts & cited else [])
        + (["DOI-linked publisher/PubMed article coordinates conflict with or are missing from the citation"] if coordinates & cited else []),
        candidates,
        attempts,
    )


def unique_crossref_primaries(candidates, doi):
    """Crossref candidates for one DOI, with byte-identical records collapsed.

    Discovery reruns can append an identical copy of a record. Records that
    differ in any way remain separate (and so remain ambiguous to callers).
    """
    found, seen = [], set()
    for candidate in candidates:
        if candidate.get("source") != "crossref":
            continue
        try:
            if normalize_doi(candidate.get("doi", "")) != normalize_doi(doi):
                continue
        except ValueError:
            continue
        body = dumps(candidate.get("record"))
        if body not in seen:
            seen.add(body)
            found.append(candidate)
    return found


CITED_TITLE_SIMILARITY = 0.8


def cited_work_dois(fields, candidates, supplied, aliases=None):
    """DOIs whose negative evidence is reported against this citation.

    With a supplied DOI only that DOI counts. Otherwise a DOI counts unless
    every Crossref record for it has comparison evidence showing a clearly
    different title (no title match and similarity below 0.8). A DOI with no
    Crossref record or no title evidence is kept (fail closed).
    """
    aliases = aliases or {}
    if supplied:
        return {supplied}
    from difflib import SequenceMatcher
    dois = set()
    for candidate in candidates:
        try:
            dois.add(aliases.get(normalize_doi(candidate["doi"]), normalize_doi(candidate["doi"])))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    cited = set()
    for doi in dois:
        primaries = [c for c in candidates if c.get("source") == "crossref" and c.get("doi")
                     and aliases.get(normalize_doi(c["doi"]), normalize_doi(c["doi"])) == doi]
        unrelated = bool(primaries)
        for primary in primaries:
            title = primary.get("evidence", {}).get("title")
            if not title or title.get("match") or not title.get("source"):
                unrelated = False
                break
            try:
                local = normalized(title.get("local", ""))
                best = max(SequenceMatcher(None, local, normalized(s)).ratio() for s in title["source"])
            except (ValueError, TypeError):
                unrelated = False
                break
            if best >= CITED_TITLE_SIMILARITY:
                unrelated = False
                break
        if not unrelated:
            cited.add(doi)
    return cited


# Route reassessment hook (machinery 2026-09-25). A source route registers
# ``reassess_saved(fields, previous) -> result | None`` (like
# reassess_saved_arxiv): it rebuilds its own decision from the raw evidence it
# saved in ``previous`` and returns None when it has nothing saved for this
# entry. ``review_key`` names the route's checkpoint field carried over from
# ``previous`` (like 'arxiv_review'). Registered routes run after the built-in
# ones, in registration order. Pair it with
# verification.register_approval_validator for snapshot imports.
SAVED_REASSESSORS = []


def register_saved_reassessor(reassess_saved, review_key=None):
    if not callable(reassess_saved):
        raise TypeError("A saved-evidence reassessor must be callable")
    if all(fn is not reassess_saved for fn, _ in SAVED_REASSESSORS):
        SAVED_REASSESSORS.append((reassess_saved, review_key))
    return reassess_saved


def reassess(entry, previous):
    """Reevaluate saved evidence; an old-policy human approval is not migrated."""
    if not previous:
        return outcome("pending", ["Run crossref verify to collect initial evidence"])
    if previous["status"] == "human_verified" and previous.get("policy") == POLICY:
        return previous
    candidates = []
    for original in previous.get("candidates", []):
        if original.get("source") == "crossref":
            evidence, issues = safe_compare(entry["fields"], original["record"], original.get("doi_alias"))
            candidates.append(
                dict(
                    original,
                    evidence=evidence,
                    issues=issues,
                    advisories=record_advisories(entry["fields"], original["record"]),
                )
            )
        elif original.get("source") not in {"europepmc", "pmc-jats", "publisher-head", "catalogue-imprint"}:
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
    for original in previous.get("candidates", []):
        if original.get("source") == "publisher-head" and original.get("raw_metadata"):
            from publisher_year_review import assess_publisher_year

            primary = next(
                (
                    c
                    for c in candidates
                    if c.get("source") == "crossref"
                    and c.get("doi") == original.get("doi")
                ),
                None,
            )
            if primary:
                candidates.append(
                    assess_publisher_year(
                        entry["fields"],
                        primary,
                        {
                            "metadata": original["raw_metadata"],
                            "url": original["url"],
                            "retrieved_at": original["retrieved_at"],
                            "document_sha256": original["document_sha256"],
                        },
                    )
                )
    from catalogue_imprint import assess_catalogue_imprint, edition_for
    for primary in list(candidates):
        if primary.get("source") != "crossref" or not edition_for(primary):
            continue
        saved = [c for c in previous.get("candidates", []) if c.get("source") == "catalogue-imprint" and c.get("doi") == primary.get("doi")]
        if len(saved) <= 1:
            candidates.append(assess_catalogue_imprint(entry["fields"], primary, saved[0] if saved else None))
    try:
        result = select_result(
            entry["fields"], candidates, previous.get("attempts", [])
        )
    except ValueError as exc:
        result = outcome(
            "needs_review", [str(exc)], candidates, previous.get("attempts", [])
        )
    from catalogue_review import reassess_saved_catalogue
    catalogue = reassess_saved_catalogue(entry['fields'], previous)
    if catalogue is not None:
        result = catalogue
    if previous.get('catalogue_review'):
        result['catalogue_review'] = previous['catalogue_review']
    from preprint_review import reassess_saved_preprint
    preprint = reassess_saved_preprint(entry['fields'], previous)
    if preprint is not None:
        result = preprint
    if previous.get('preprint_review'):
        result['preprint_review'] = previous['preprint_review']
    from arxiv_review import reassess_saved_arxiv
    arxiv = reassess_saved_arxiv(entry['fields'], previous)
    if arxiv is not None:
        result = arxiv
    if previous.get('arxiv_review'):
        result['arxiv_review'] = previous['arxiv_review']
    for reassess_saved, review_key in SAVED_REASSESSORS:
        routed = reassess_saved(entry['fields'], previous)
        if routed is not None:
            result = routed
        if review_key and previous.get(review_key):
            result[review_key] = previous[review_key]
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
    result["auto_review"] = dict(
        previous.get("auto_review", {}),
        policy=POLICY,
        resolver_version=RESOLVER_VERSION,
    )
    # An additive resolver can make a saved DOI eligible for the first time,
    # even without a new discovery response (e.g. repaired author tokenization).
    # Reopen only new targets and preserve the completed DOI lookups.
    if set(target_dois(result)) - set(target_dois(previous)):
        checkpoint = result["auto_review"]
        done = set(checkpoint.get("epmc_checked_dois", []))
        if checkpoint.get("epmc_checked"):
            done.update(target_dois(previous))
        checkpoint.update(epmc_checked=False, epmc_checked_dois=sorted(done))
        checkpoint.pop("fulltext_checked", None)
        checkpoint.pop("publisher_year_policy", None)
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
                found.append(normalize_doi(candidate.get("doi", "")))
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


def blocking_pubmed_relationships(raw):
    """Ordinary commentary is distinct from correction or version evidence.

    NLM documents Comment in/on as separate linked citation types. Only those
    two explicit, identified relationships are benign; unknown or malformed
    relations and all correction/republication/preprint types remain blocking.
    """
    container = raw.get("commentCorrectionList")
    if not container:
        return False
    if not isinstance(container, dict):
        return True
    links = container.get("commentCorrection")
    if not isinstance(links, list):
        return True
    return any(not isinstance(link, dict) or not (
        (link.get("type") in {"Comment in", "Comment on"} and link.get("source") == "MED"
         and re.fullmatch(r"\d+", str(link.get("id", ""))))
        # Machinery fix 2026-09-25 (ChenEtal21, SchwEtal22): Europe PMC's
        # "Preprint in" link from the journal article to its own earlier
        # preprint (source PPR) is version provenance, not a correction.
        or (link.get("type") == "Preprint in" and link.get("source") == "PPR"
            and re.fullmatch(r"PPR\d+", str(link.get("id", "")))))
        for link in links)


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
        or blocking_pubmed_relationships(raw)
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
                "suffix": pubmed_author_suffix(person),
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
        if not same_suffix(source_name_suffix(a.get("suffix", "")), source_name_suffix(b.get("suffix", ""))):
            return False  # recognized suffixes are ignored (user decision 2026-09-24/25)
        aa = without_suffix_tokens(given_name_tokens(a.get("given", "")))
        bb = without_suffix_tokens(given_name_tokens(b.get("given", "")))
        for x, y in zip(aa, bb):
            if not (given_token_matches(x, y) or given_token_matches(y, x)):
                return False
    return True


def authors_with_pubmed_suffixes(primary, secondary):
    """Supplement only absent registry suffixes from compatible ordered authors."""
    people = deepcopy(primary.get("author", []))
    other = secondary.get("author", [])
    if not people or len(people) != len(other):
        return None
    added = False
    for first, second in zip(people, other):
        if not first.get("given") or not second.get("given"):
            return None
        if not first.get("suffix") and second.get("suffix"):
            first["suffix"] = second["suffix"]
            added = True
    return people if added and compatible_authors({"author": people}, secondary) else None


def _edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def registry_surname_typo(fields, primary, mapped, secondary_evidence):
    """A Crossref surname typo contradicted by PubMed and by library consensus.

    Machinery fix 2026-09-25 (MeyeEtal88: Crossref "Kounois", DOI-linked
    PubMed 3375400 "Kounios", cited "J Kounios", five other cdl.bib entries
    "Kounios" and none "Kounois"). Returns the resolution record, or None.
    Every condition must hold:
      * the DOI-linked PubMed record shares an ISSN with the Crossref record
        and matches the citation on title, author, year, journal, volume and
        pages, which Crossref also matches except for the byline;
      * Crossref and PubMed list the same number of authors with identical
        surnames except in exactly ONE position, where the two surnames are
        within two edits of each other (both at least four letters) and the
        given names agree (a spelling slip, not another person);
      * library consensus: other cdl.bib entries use the cited spelling for
        that person (surname + first initial) and none uses Crossref's.
    """
    try:
        for field in ("title", "author", "year", "journal", "volume", "pages"):
            if not secondary_evidence.get(field, {}).get("match"):
                return None
            if field != "author" and not primary.get("evidence", {}).get(field, {}).get("match"):
                return None
        if not set(mapped.get("ISSN") or []) & set(primary["record"].get("ISSN") or []):
            return None
        crossref, pubmed = primary["record"].get("author") or [], mapped.get("author") or []
        names = split_authors(fields.get("author", ""))
        if not crossref or not (len(crossref) == len(pubmed) == len(names)):
            return None
        differ = [i for i, (a, b) in enumerate(zip(crossref, pubmed))
                  if normalized(a.get("family", "")) != normalized(b.get("family", ""))]
        if len(differ) != 1:
            return None
        i = differ[0]
        from correction_proposals import _fold, _person_key, library_people
        wrong, right = _fold(crossref[i].get("family", "")), _fold(pubmed[i].get("family", ""))
        if min(len(wrong), len(right)) < 4 or _edit_distance(wrong, right) > 2:
            return None
        given_a = without_suffix_tokens(given_name_tokens(crossref[i].get("given", "")))
        given_b = without_suffix_tokens(given_name_tokens(pubmed[i].get("given", "")))
        if not given_a or not given_b or not all(
                given_token_matches(x, y) or given_token_matches(y, x) for x, y in zip(given_a, given_b)):
            return None
        cited = _person_key(names[i])
        if not cited or cited[0] != right:
            return None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    # A library that cannot be read is an error, never "no consensus".
    people = library_people()
    key = fields.get("ID")
    cited_elsewhere = people.get(cited, set()) - {key}
    registry_elsewhere = people.get((wrong, cited[1]), set()) - {key}
    if not cited_elsewhere or registry_elsewhere:
        return None
    return {"rule": "registry-surname-typo", "registry_surname": crossref[i].get("family", ""),
            "pubmed_surname": pubmed[i].get("family", ""),
            "library_consensus": sorted(cited_elsewhere)}


def assess_epmc(fields, primary, raw, retrieved_at, request_url):
    evidence, issues, resolved, mapped = {}, [], [], {}
    try:
        mapped = epmc_record(raw, primary["record"])
        secondary_evidence, secondary_issues = safe_compare(fields, mapped)
        evidence = deepcopy(primary.get("evidence", {}))
        # A complete registry name plus an explicit PubMed suffix supplies each
        # name part without replacing either source's conflicting information.
        suffix_authors = authors_with_pubmed_suffixes(primary["record"], mapped)
        suffix_match = bool(suffix_authors and author_evidence(fields.get("author", ""), suffix_authors)[0]
                            and set(mapped["ISSN"]) & set(primary["record"].get("ISSN", []))
                            and all(secondary_evidence.get(f, {}).get("match")
                                    and evidence.get(f, {}).get("match")
                                    for f in ("title", "year", "journal", "volume", "pages")))
        if suffix_match:
            secondary_evidence["author"] = {
                "local": fields["author"], "source": suffix_authors, "match": True,
                "detail": "Registry names with explicit DOI-linked PubMed suffixes",
                "name_source": "crossref", "suffix_source": "europepmc",
            }
        # Every overridden field must itself pass full local-vs-secondary checks.
        for issue in primary.get("issues", []):
            field = issue.split(":", 1)[0]
            supported = secondary_evidence.get(field, {}).get("match")
            can_resolve = False
            typo = None
            if field == "author" and supported:
                can_resolve = suffix_match or compatible_authors(primary["record"], mapped)
                if not can_resolve and issue == "author: Author surnames/order differ":
                    typo = registry_surname_typo(fields, primary, mapped, secondary_evidence)
                    can_resolve = bool(typo)
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
            elif field == "number" and supported:
                # MEDLINE sometimes labels a complete issue as "Pt N". Require
                # the exact DOI, ISSN, and all article coordinates in both
                # sources; never strip supplement/part labels globally.
                part = re.fullmatch(r"Pt ([1-9]\d*)", fields.get("number", ""))
                can_resolve = bool(
                    part
                    and str(primary["record"].get("issue", "")) == part[1]
                    and set(mapped["ISSN"]) & set(primary["record"].get("ISSN", []))
                    and all(
                        secondary_evidence.get(f, {}).get("match")
                        and primary["evidence"].get(f, {}).get("match")
                        for f in (
                            "title",
                            "author",
                            "journal",
                            "year",
                            "volume",
                            "pages",
                        )
                    )
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
                    dict({"finding": issue, "authority": "PubMed via Europe PMC"}, **(typo or {}))
                )
                evidence[field] = dict(
                    secondary_evidence[field], source_name="europepmc"
                )
            else:
                issues.append(issue)
        # A missing MED issue is not a contradictory issue. For print-year
        # corroboration only, retain the independently supported Crossref issue
        # after both sources establish every other article identity coordinate.
        # Never insert a guessed issue into the raw/mapped MED record.
        primary_evidence, primary_issues = safe_compare(fields, primary['record'])
        retain_issue = (
            primary_issues == ['year: conflicting or missing publication dates; select the cited edition explicitly']
            and 'issue' not in raw.get('journalInfo', {})
            and primary_evidence.get('number', {}).get('match')
            and set(mapped.get('ISSN', [])) & set(primary['record'].get('ISSN', []))
            and all(primary_evidence.get(f, {}).get('match') and secondary_evidence.get(f, {}).get('match')
                    for f in ('title', 'author', 'year', 'journal', 'volume', 'pages'))
            and any(r['finding'].startswith('year: conflicting') for r in resolved)
        )
        if retain_issue:
            evidence['number'] = dict(primary_evidence['number'], source_name='crossref',
                detail='MED omits issue; Crossref issue retained with complete DOI/ISSN/article-coordinate agreement')
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
            if field == 'number' and retain_issue:
                continue
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


def alias_targets(result):
    """Probe legacy doubled-slash identifiers; never normalize them by guess."""
    checked = set(result.get("auto_review", {}).get("alias_checked_dois", []))
    targets = set()
    for candidate in result.get("candidates", []):
        if candidate.get("source") != "crossref":
            continue
        try:
            doi = normalize_doi(candidate["doi"])
            evidence = candidate.get("evidence", {})
            if (re.match(r"10\.\d{4,9}//", doi) and doi not in checked
                    and evidence.get("title", {}).get("match")
                    and evidence.get("author", {}).get("match")):
                targets.add(doi)
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(targets)


def apply_alias_lookup(entry, previous, requested, response):
    """Preserve a provider receipt and checkpoint a completed alias lookup."""
    result = deepcopy(previous)
    candidates = assess_candidates(entry["fields"], response)
    for candidate in candidates:
        if not valid_doi_alias(candidate.get("doi_alias"), requested, candidate.get("doi")):
            continue  # A matching title or HTTP 200 is not alias authority.
        if candidate not in result["candidates"]:
            result["candidates"].append(candidate)
    result.setdefault("attempts", []).append({"source": "crossref-alias", "doi": requested,
        "url": response["url"], "retrieved_at": response["retrieved_at"],
        "confirmed": any(valid_doi_alias(c.get("doi_alias"), requested, c.get("doi")) for c in candidates)})
    result = reassess(entry, result)
    checkpoint = result.setdefault("auto_review", {})
    checkpoint["alias_checked_dois"] = sorted(set(checkpoint.get("alias_checked_dois", [])) | {requested})
    return result


def run_auto_review(
    filename, cache, report, client=None, limit=None, snapshot=None, keys=None
):
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    with run_lock(cache):
        entries = load_entries(filename)
        try:
            results = {}
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
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
                    and (
                        previous.get("status") in ACCEPTED
                        or (
                            previous.get("auto_review", {}).get("policy") == POLICY
                            and previous.get("auto_review", {}).get("resolver_version")
                            == RESOLVER_VERSION
                        )
                    )
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
                network_selected = set()
                for key, result in results.items():
                    if result.get("external_evidence") or result["status"] != "needs_review":
                        continue
                    pending_aliases = alias_targets(result)
                    if not pending_aliases:
                        continue
                    if limit is not None and len(network_selected) >= limit:
                        break
                    network_selected.add(key)
                    for doi in pending_aliases:
                        response = client.crossref_doi(doi)
                        result = apply_alias_lookup(entries[key], result, doi, response)
                        results[key] = cache.put(filename, entries[key], result)
                    print(f"Crossref alias checks: {key}; requests: {client.requests}", flush=True)
                targets = {}
                for key, result in results.items():
                    if (
                        result.get("external_evidence")
                        or result["status"] != "needs_review"
                        or result.get("auto_review", {}).get("epmc_checked")
                    ):
                        continue
                    done = set(
                        result.get("auto_review", {}).get("epmc_checked_dois", [])
                    )
                    dois = [d for d in target_dois(result) if d not in done]
                    if not dois:
                        continue
                    if limit is not None and key not in network_selected and len(network_selected) >= limit:
                        continue
                    network_selected.add(key)
                    for doi in dois:
                        targets.setdefault(doi, []).append(key)
                dois = list(targets)
                remaining = {
                    key: set(target_dois(results[key]))
                    - set(
                        results[key].get("auto_review", {}).get("epmc_checked_dois", [])
                    )
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
                            checkpoint = dict(result.get("auto_review", {}))
                            retained = {
                                k: result[k]
                                for k in ("research_attempt", "discovery_review")
                                if k in result
                            }
                            done = set(checkpoint.get("epmc_checked_dois", [])) | {doi}
                            result = dict(
                                select_result(
                                    entries[key]["fields"],
                                    result["candidates"],
                                    result["attempts"],
                                ),
                                **retained,
                                auto_review=dict(
                                    checkpoint,
                                    policy=POLICY,
                                    resolver_version=RESOLVER_VERSION,
                                    epmc_checked=not remaining[key],
                                    epmc_checked_dois=sorted(done),
                                ),
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
