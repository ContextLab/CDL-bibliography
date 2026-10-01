"""Validate PMC OAI front matter before the existing JATS metadata assessment.

This route uses metadata made available independently of full-text licenses.
It does not turn an author manuscript into the version of record.
"""

import hashlib
import re
import xml.etree.ElementTree as ET

import requests

from verification import normalize_doi, now, ProviderError

OAI = "{http://www.openarchives.org/OAI/2.0/}"
JATS = "{https://jats.nlm.nih.gov/ns/archiving/1.4/}"
ENDPOINT = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
METADATA_POLICY = "2"


def metadata_targets(previous):
    """Select unqueried, uniquely identified PMC metadata records."""
    checkpoint = previous.get("auto_review", {})
    checked = (set(checkpoint.get("pmc_metadata_checked", []))
               if checkpoint.get("pmc_metadata_policy") == METADATA_POLICY else set())
    choices = {}
    for candidate in previous.get("candidates", []):
        if candidate.get("source") != "europepmc":
            continue
        raw = candidate.get("raw_record", {})
        if not isinstance(raw, dict):
            continue
        pmcid, pmid = raw.get("pmcid", ""), raw.get("id", "")
        try:
            doi = normalize_doi(candidate.get("doi", ""))
            raw_doi = normalize_doi(raw.get("doi", ""))
        except (ValueError, TypeError, AttributeError):
            continue
        if (raw.get("source") != "MED" or not isinstance(pmcid, str)
                or not re.fullmatch(r"PMC[1-9]\d*", pmcid)
                or not re.fullmatch(r"[1-9]\d*", str(pmid))
                or raw_doi != doi
                or pmcid in checked):
            continue
        primaries = [c for c in previous.get("candidates", [])
                     if c.get("source") == "crossref" and c.get("doi") == doi]
        if len(primaries) == 1:
            choices.setdefault(pmcid, {})[(doi, str(pmid))] = (primaries[0], raw)
    # Conflicting mappings of one PMC identifier must never choose a record by
    # candidate order. Leave them unresolved for source adjudication.
    return {pmcid: next(iter(records.values())) for pmcid, records in choices.items()
            if len(records) == 1}


def check_bulk_hours():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    eastern = datetime.now(ZoneInfo("America/New_York"))
    if eastern.weekday() < 5 and 5 <= eastern.hour < 21:
        raise ProviderError("Bulk PMC requests require weekday hours outside 5 AM–9 PM US Eastern")


def run_pmc_metadata_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    """Review unresolved DOI-linked PMC records, including non-OA metadata.

    Entry checkpoints and the independent HTTP cache both prevent repeat calls.
    A new entry fingerprint must pass the current field checks afresh.
    """
    from auto_review import select_result
    from fulltext_review import assess_fulltext
    from verification import (load_entries, run_lock, validate_output_path,
                              write_report, export_snapshot)
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    checked_entries = 0
    with run_lock(cache):
        entries = load_entries(filename)
        bulk = len(entries) if keys is None else len(keys)
        try:
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
                previous = cache.get(filename, entry)
                if (not previous or previous["status"] != "needs_review"
                        or previous.get("external_evidence")):
                    continue
                targets = metadata_targets(previous)
                if not targets:
                    continue
                if limit is not None and checked_entries >= limit:
                    break
                for pmcid, (primary, medline) in targets.items():
                    if bulk > 100 and (client.refresh or cache.response("pmc-front-v1:" + pmcid, 30 * 86400) is None):
                        check_bulk_hours()
                    response = fetch_front(cache, client, pmcid)
                    candidates = list(previous.get("candidates", []))
                    if response["body"]:
                        front = article_front(response["body"], pmcid, primary["doi"], str(medline["id"]))
                        candidates.append(assess_fulltext(entry["fields"], primary, medline, dict(response, body=front)))
                    attempts = list(previous.get("attempts", [])) + [{
                        "source": "pmc-oai", "url": response["url"], "http_status": response["http_status"]}]
                    result = select_result(entry["fields"], candidates, attempts) if response["body"] else dict(previous, attempts=attempts)
                    for name in ("research_attempt", "discovery_review", "external_evidence"):
                        if name in previous:
                            result[name] = previous[name]
                    checkpoint = previous.get("auto_review", {})
                    checked = (set(checkpoint.get("pmc_metadata_checked", []))
                               if checkpoint.get("pmc_metadata_policy") == METADATA_POLICY else set())
                    checked.add(pmcid)
                    result["auto_review"] = dict(checkpoint, pmc_metadata_checked=sorted(checked), pmc_metadata_policy=METADATA_POLICY)
                    cache.put(filename, entry, result)
                    previous = cache.get(filename, entry)
                    if previous["status"] != "needs_review":
                        break
                checked_entries += 1
                if checked_entries % 10 == 0:
                    print(f"PMC metadata entries checked: {checked_entries}; requests: {client.requests}", flush=True)
        finally:
            results = write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
    return results


def fetch_front(cache, client, pmcid):
    """Cache serial metadata requests; stop immediately on provider failure."""
    if not re.fullmatch(r"PMC[1-9]\d*", pmcid):
        raise ValueError("Invalid PMC identifier")
    identity = "pmc-front-v1:" + pmcid
    saved = cache.response(identity, 30 * 86400)
    if saved is not None and not client.refresh:
        return saved
    params = {"verb": "GetRecord", "identifier": "oai:pubmedcentral.nih.gov:" + pmcid[3:],
              "metadataPrefix": "pmc_fm"}
    interval = client.interval
    client.interval = max(interval, 3.1)
    try:
        with client.source_request(ENDPOINT, params=params, timeout=(10, 40),
                                   allow_redirects=False, stream=True,
                                   headers={"Accept-Encoding": "gzip, deflate"}) as response:
            if response.status_code not in (200, 404):
                raise ProviderError(f"PMC metadata HTTP {response.status_code}; stopped without retry "
                                    f"(Retry-After: {response.headers.get('Retry-After')})")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise ProviderError("PMC metadata exceeds 2 MB")
                chunks.append(chunk)
            body = b"".join(chunks)
            result = {"url": response.url, "retrieved_at": now(), "http_status": response.status_code,
                      "body": body.decode("utf-8") if response.status_code == 200 else None,
                      "document_sha256": hashlib.sha256(body).hexdigest()}
            if response.status_code == 200 and (re.search(r"<!\s*(?:DOCTYPE|ENTITY)", result["body"], re.I)
                                   or ET.fromstring(result["body"]).tag != OAI + "OAI-PMH"):
                raise ProviderError("PMC metadata is not an OAI XML response")
    except (requests.RequestException, UnicodeError, ET.ParseError) as exc:
        raise ProviderError("PMC metadata retrieval failed: " + str(exc)) from exc
    finally:
        client.interval = interval
    cache.save_response(identity, result)
    return result


def notice_dois(candidate):
    """Find explicit DOI-linked notices in the article's own front matter."""
    if candidate.get("source") != "pmc-jats":
        return set()
    try:
        xml = candidate["raw_xml"]
        if (not isinstance(xml, str) or len(xml) > 20_000_000
                or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I)):
            return set()
        root = ET.fromstring(xml)
        metas = root.findall("./front/article-meta")
        medline = candidate["medline_record"]
        doi = normalize_doi(candidate["doi"])
        if (root.tag != "article" or len(metas) != 1
                or medline.get("source") != "MED"
                or not re.fullmatch(r"[1-9]\d*", str(medline.get("id", "")))
                or normalize_doi(medline.get("doi", "")) != doi):
            return set()
        ids = [normalize_doi(x.text or "") for x in metas[0].findall("./article-id")
               if x.get("pub-id-type") == "doi"]
        if ids != [doi]:
            return set()
        labels = [root.get("article-type", "")]
        labels.extend(x.get("related-article-type", "") for x in metas[0].findall("./related-article"))
        if any(word in label.lower().replace("-", " ") for label in labels
               for word in ("errat", "retract", "correct", "expression of concern")):
            return {doi}
    except (ValueError, KeyError, TypeError, AttributeError, ET.ParseError):
        pass
    return set()


def article_front(xml, pmcid, doi, pmid):
    """Return one identified JATS article, retaining version and semantic markup."""
    if (not isinstance(xml, str) or len(xml) > 2_000_000
            or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I)):
        raise ValueError("Unsupported or oversized PMC metadata XML")
    if not re.fullmatch(r"PMC[1-9]\d*", pmcid) or not re.fullmatch(r"[1-9]\d*", pmid):
        raise ValueError("Expected explicit PMC and PubMed identifiers")
    root = ET.fromstring(xml)
    identifier = "oai:pubmedcentral.nih.gov:" + pmcid[3:]
    if root.tag != OAI + "OAI-PMH" or root.find(OAI + "error") is not None:
        raise ValueError("PMC OAI response is an error or unknown envelope")
    requests = root.findall(OAI + "request")
    if (len(requests) != 1 or requests[0].get("verb") != "GetRecord"
            or requests[0].get("metadataPrefix") != "pmc_fm"
            or requests[0].get("identifier") != identifier):
        raise ValueError("PMC response request identity differs")
    records = root.findall(OAI + "GetRecord/" + OAI + "record")
    if len(records) != 1:
        raise ValueError("Expected one PMC OAI record")
    headers = records[0].findall(OAI + "header")
    if (len(headers) != 1 or headers[0].get("status") == "deleted"
            or [x.text for x in headers[0].findall(OAI + "identifier")] != [identifier]):
        raise ValueError("PMC record is deleted or its identifier differs")
    metadata = records[0].findall(OAI + "metadata")
    if len(metadata) != 1 or len(metadata[0]) != 1 or metadata[0][0].tag != JATS + "article":
        raise ValueError("Expected exactly one recognized JATS article")
    article = metadata[0][0]
    if len(article.findall(JATS + "front")) != 1:
        raise ValueError("Expected exactly one article front")
    front = article.find(JATS + "front")
    if len(front.findall(JATS + "article-meta")) != 1 or len(front.findall(JATS + "journal-meta")) != 1:
        raise ValueError("Ambiguous or missing article/journal metadata")
    meta = front.find(JATS + "article-meta")
    for kind, expected in (("pmcid", pmcid), ("pmid", pmid), ("doi", normalize_doi(doi))):
        values = [x.text or "" for x in meta.findall(JATS + "article-id") if x.get("pub-id-type") == kind]
        if kind == "doi":
            values = [normalize_doi(v) for v in values]
        if values != [expected]:
            raise ValueError("PMC front-matter " + kind + " identity differs or is ambiguous")
    # Remove only the explicitly recognized JATS namespace. MathML and unknown
    # namespaces remain visible to the conservative semantic-markup guard.
    # Neither reference lists nor nested subarticles can supply citation fields.
    for child in list(article):
        if child is not front:
            article.remove(child)
    for node in article.iter():
        if node.tag.startswith(JATS):
            node.tag = node.tag[len(JATS):]
    return ET.tostring(article, encoding="unicode")
