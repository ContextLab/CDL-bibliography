"""Check publisher-supplied JATS front matter, never a paper's reference list."""

import hashlib
import re
import xml.etree.ElementTree as ET

from auto_review import safe_compare, select_result
from verification import (
    POLICY,
    normalize_doi,
    normalized,
    run_lock,
    load_entries,
    write_report,
    export_snapshot,
    validate_output_path,
)


def element_text(element):
    if element is None:
        return ""
    if any(
        e.tag in {"inline-formula", "tex-math", "math", "sup", "sub"} or "}" in e.tag
        for e in element.iter()
    ):
        raise ValueError("Mathematical/semantic title markup requires source review")
    return "".join(element.itertext()).strip()


def front_record(xml, primary, medline):
    """Metadata must belong to the top-level article, with an exact DOI link."""
    if len(xml) > 20_000_000:
        raise ValueError("Article XML exceeds 20 MB")
    root = ET.fromstring(xml)
    if root.tag != "article" or root.get("article-type") not in {
        "research-article",
        "review-article",
        "brief-report",
        "case-report",
        "letter",
        "editorial",
        "commentary",
        "methods-article",
    }:
        raise ValueError("Unrecognized or non-journal full-text publication type")
    meta, journal = root.find("./front/article-meta"), root.find("./front/journal-meta")
    if meta is None or journal is None:
        raise ValueError("Full text lacks article front matter")
    identifiers = meta.findall("./article-id")
    if any(
        x.get("pub-id-type") in {"manuscript", "archive", "arxiv"} for x in identifiers
    ):
        raise ValueError("Author manuscript/preprint requires explicit version review")
    versions = meta.findall("./article-version")
    if (
        any(
            v.get("article-version-type") != "pmc-version" or element_text(v) != "1"
            for v in versions
        )
        or meta.find("./related-article") is not None
    ):
        raise ValueError(
            "Full-text version or related-article annotation requires review"
        )
    dois = {
        normalize_doi(element_text(x))
        for x in identifiers
        if x.get("pub-id-type") == "doi"
    }
    expected = normalize_doi(primary["DOI"])
    if dois != {expected} or normalize_doi(medline["doi"]) != expected:
        raise ValueError("Full-text DOI does not uniquely match both metadata sources")
    title = meta.find("./title-group/article-title")
    if title is None:
        raise ValueError("Full-text title missing")
    titles = [element_text(title)]
    subtitle = meta.find("./title-group/subtitle")
    if subtitle is not None:
        titles = [titles[0] + ": " + element_text(subtitle)]
    people = []
    for group in meta.findall("./contrib-group"):
        for person in group.findall("./contrib"):
            if person.get("contrib-type", group.get("content-type")) != "author":
                continue
            name = person.find("./name")
            collab = person.find("./collab")
            if name is not None:
                people.append(
                    {
                        "family": element_text(name.find("./surname")),
                        "given": element_text(name.find("./given-names")),
                        "suffix": element_text(name.find("./suffix")),
                    }
                )
            elif collab is not None:
                people.append({"name": element_text(collab)})
            else:
                raise ValueError("Unstructured full-text author cannot be inferred")
    issns = [element_text(x) for x in journal.findall("./issn")]
    venues = [
        element_text(x) for x in journal.findall("./journal-title-group/journal-title")
    ]
    venues += [element_text(x) for x in journal.findall("./journal-title")]
    venues += [
        element_text(x)
        for x in journal.findall("./journal-title-group/abbrev-journal-title")
    ]
    if set(issns) & set(primary.get("ISSN", [])):
        venues += primary.get("container-title", [])
    medjournal = medline.get("journalInfo", {}).get("journal", {})
    if set(issns) & {medjournal.get("issn"), medjournal.get("essn")}:
        venues += [
            medjournal[k]
            for k in ("title", "medlineAbbreviation", "isoabbreviation")
            if medjournal.get(k)
        ]
    # Use the journal issue year, corroborated by an explicit publication date
    # in the source. Never use copyright, received, accepted or download dates.
    years = set()
    for date in meta.findall("./pub-date"):
        if (
            date.get("pub-type") in {"ppub", "epub", "epub-ppub", "collection"}
            or (
                date.get("date-type") == "pub"
                and date.get("publication-format") in {"print", "electronic"}
            )
            or not any(
                date.get(k) for k in ("pub-type", "date-type", "publication-format")
            )
        ):
            year = date.findtext("./year", default="")
            if re.fullmatch(r"[1-9]\d{3}", year):
                years.add(year)
    issue_year = str(medline.get("journalInfo", {}).get("yearOfPublication", ""))
    if issue_year not in years:
        raise ValueError(
            "Full-text publication dates do not support the indexed issue year"
        )
    first, last = meta.findtext("./fpage"), meta.findtext("./lpage")
    pages = first + "-" + last if first and last and first != last else first
    elocation = meta.findtext("./elocation-id")
    return {
        "DOI": expected,
        "type": "journal-article",
        "title": titles,
        "author": people,
        "container-title": venues,
        "ISSN": issns,
        "published": {"date-parts": [[int(issue_year)]]},
        "volume": meta.findtext("./volume"),
        "issue": meta.findtext("./issue"),
        "page": pages,
        "article-number": elocation,
        "publisher": element_text(journal.find("./publisher/publisher-name")),
    }


def assess_fulltext(fields, primary, medline, response):
    record, evidence, issues = {}, {}, []
    xml = response.get("body")
    sha = response.get("document_sha256") or (
        hashlib.sha256(xml.encode("utf-8")).hexdigest()
        if isinstance(xml, str)
        else None
    )
    try:
        record = front_record(xml, primary["record"], medline)
        evidence, issues = safe_compare(fields, record)
        source = primary["record"]
        # The full text may repair an incomplete registry deposit, but cannot
        # turn a preprint/correction into a final article or select a new DOI.
        relations = set(source.get("relation", {}))
        if (
            source.get("type") != "journal-article"
            or source.get("update-to")
            or source.get("updated-by")
            or relations
            - {
                "has-review",
                "references",
                "is-referenced-by",
                "has-preprint",
            }
        ):
            issues.append("Registry version/update relationship still requires review")
        # Require PubMed's volume and pagination to support the same edition.
        from auto_review import expanded_pages

        info = medline.get("journalInfo", {})
        if not record.get("volume") or normalized(record["volume"]) != normalized(
            info.get("volume", "")
        ):
            issues.append(
                "Full-text and PubMed volumes do not establish the same issue"
            )
        page = record.get("page") or record.get("article-number", "")
        if not page or expanded_pages(page) != expanded_pages(
            medline.get("pageInfo", "")
        ):
            issues.append(
                "Full-text and PubMed pagination do not establish the same article"
            )
        if medline.get("commentCorrectionList") or medline.get("isRetracted") == "Y":
            issues.append("PubMed reports a comment/correction/retraction relationship")
    except (ValueError, TypeError, KeyError, AttributeError, ET.ParseError) as exc:
        issues.append(f"Full-text evidence unresolved: {exc}")
    # Portable evidence contains front-matter metadata only. The full downloaded
    # document remains in the local HTTP cache, identified by its separate hash.
    try:
        root = ET.fromstring(xml)
        for child in list(root):
            if child.tag != "front":
                root.remove(child)
        meta = root.find("./front/article-meta")
        if meta is not None:
            for child in list(meta):
                if child.tag not in {
                    "article-id",
                    "article-version",
                    "related-article",
                    "title-group",
                    "contrib-group",
                    "pub-date",
                    "volume",
                    "issue",
                    "fpage",
                    "lpage",
                    "elocation-id",
                }:
                    meta.remove(child)
        xml = ET.tostring(root, encoding="unicode")
    except (ET.ParseError, TypeError):
        xml = None
    return {
        "source": "pmc-jats",
        "doi": primary["doi"],
        "url": response["url"],
        "record": record,
        "evidence": evidence,
        "issues": issues,
        "retrieved_at": response["retrieved_at"],
        "xml_sha256": sha,
        "authority": "Publisher article front matter via Europe PMC",
        "raw_xml": xml,
        "medline_record": medline,
    }


def run_fulltext_review(filename, cache, client, report, limit=None, snapshot=None):
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    checked = 0
    with run_lock(cache):
        entries = load_entries(filename)
        try:
            for key, entry in entries.items():
                previous = cache.get(filename, entry)
                if (
                    not previous
                    or previous["status"] != "needs_review"
                    or previous.get("external_evidence")
                ):
                    continue
                if (
                    previous.get("auto_review", {}).get("fulltext_checked")
                    and previous.get("auto_review", {}).get("fulltext_policy") == "1"
                ):
                    continue
                targets = {}
                for candidate in previous.get("candidates", []):
                    raw = candidate.get("raw_record", {})
                    pmcid = raw.get("pmcid", "")
                    if (
                        candidate.get("source") == "europepmc"
                        and raw.get("isOpenAccess") == "Y"
                        and re.fullmatch(r"PMC\d+", pmcid)
                    ):
                        primary = next(
                            (
                                c
                                for c in previous["candidates"]
                                if c.get("source") == "crossref"
                                and c.get("doi") == candidate["doi"]
                            ),
                            None,
                        )
                        if primary:
                            targets[pmcid] = (primary, raw)
                if not targets:
                    continue
                if limit is not None and checked >= limit:
                    break
                candidates = list(previous["candidates"])
                attempts = list(previous.get("attempts", []))
                for pmcid, (primary, raw) in targets.items():
                    url = (
                        "https://www.ebi.ac.uk/europepmc/webservices/rest/"
                        + pmcid
                        + "/fullTextXML"
                    )
                    response = client.get(url, xml=True)
                    attempts.append(
                        {
                            "source": "pmc-jats",
                            "url": url,
                            "http_status": response["http_status"],
                        }
                    )
                    if response["body"]:
                        candidates.append(
                            assess_fulltext(entry["fields"], primary, raw, response)
                        )
                result = select_result(entry["fields"], candidates, attempts)
                result["auto_review"] = dict(
                    previous.get("auto_review", {}),
                    policy=POLICY,
                    fulltext_checked=True,
                    fulltext_policy="1",
                )
                cache.put(filename, entry, result)
                checked += 1
                if checked % 10 == 0:
                    print(
                        f"Full-text entries checked: {checked}; requests: {client.requests}",
                        flush=True,
                    )
        finally:
            results = write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
    return results
