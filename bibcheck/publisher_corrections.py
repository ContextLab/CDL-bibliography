"""Propose title repairs corroborated by the publisher's own citation metadata.

The publisher's DOI and complete title must agree with the registry. Every
other supplied citation field must already match. These are proposals, not
approvals or automatic bibliography mutations.
"""

from copy import deepcopy
import hashlib
import re
from urllib.parse import quote, unquote, urlparse
import xml.etree.ElementTree as ET

import requests
from name_parsing import splitname

from auto_review import epmc_record, reassess, safe_compare
from correction_proposals import source_authors, source_title
from publisher_metadata import PublisherMetadata
from search_tools import get_source, SourceHTTPError
from verification import compare_record, normalize_doi, normalize_pages, normalize_title, now, ProviderError


PUBLISHERS = {
    "www.sciencedirect.com": "/science/article/",
    "journals.sagepub.com": "/doi/",
    "link.springer.com": "/article/",
    "www.nature.com": "/articles/",
    "onlinelibrary.wiley.com": "/doi/",
    "www.tandfonline.com": "/doi/",
    "royalsocietypublishing.org": "/doi/",
    "www.cambridge.org": "/core/journals/",
    "elifesciences.org": "/articles/",
    "www.jneurosci.org": "/content/",
    "academic.oup.com": "/",
    "direct.mit.edu": "/",
    "journals.plos.org": "/",
    "psycnet.apa.org": "/",
    "jair.org": "/index.php/jair/article/",
    "journals.aps.org": "/",
    "econtent.hogrefe.com": "/doi/",
    "www.frontiersin.org": "/journals/",
    "journal.frontiersin.org": "/article/",
}
HOSTS = set(PUBLISHERS) | {"doi.org", "dx.doi.org", "linkinghub.elsevier.com", "link.aps.org", "doi.apa.org"}


def elsevier_metadata(xml):
    """Read only the article's own coredata, never titles in its references."""
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I):
        raise ValueError("XML declarations with entities are unsupported")
    ns = {"article": "http://www.elsevier.com/xml/svapi/article/dtd",
          "dc": "http://purl.org/dc/elements/1.1/",
          "prism": "http://prismstandard.org/namespaces/basic/2.0/"}
    root = ET.fromstring(xml)
    cores = root.findall("article:coredata", ns)
    if root.tag != "{" + ns["article"] + "}full-text-retrieval-response" or len(cores) != 1:
        raise ValueError("Expected exactly one article coredata record")
    core = cores[0]
    def values(tag):
        nodes = core.findall(tag, ns)
        if any(len(node) or not (node.text or "").strip() for node in nodes):
            raise ValueError("Complex or empty citation metadata is unsupported")
        return [node.text.strip() for node in nodes]
    if values("prism:aggregationType") != ["Journal"]:
        raise ValueError("Publisher record is not a journal article")
    result = {}
    for tag, field in (("dc:title", "title"), ("prism:doi", "doi"), ("prism:publicationName", "journal_title"),
                       ("prism:volume", "volume"), ("prism:issueIdentifier", "issue"),
                       ("prism:coverDate", "publication_date"), ("prism:startingPage", "firstpage"),
                       ("prism:endingPage", "lastpage"), ("dc:creator", "author"), ("dc:publisher", "publisher")):
        found = values(tag)
        if found:
            result["citation_" + field] = found
    dois = result.get("citation_doi", [])
    if len(dois) != 1 or any(normalize_doi(v.removeprefix("doi:")) != normalize_doi(dois[0])
                             for v in values("dc:identifier")):
        raise ValueError("Publisher DOI identity conflict")
    issns = values("prism:issn") + values("prism:eIssn")
    if issns:
        if any(not re.fullmatch(r"\d{4}-?\d{3}[\dXx]", v) for v in issns):
            raise ValueError("Malformed publisher ISSN")
        result["citation_issn"] = list(dict.fromkeys(v.replace("-", "")[:4] + "-" + v.replace("-", "")[4:].upper() for v in issns))
    for page_range in values("prism:pageRange"):
        pages = normalize_pages(page_range).split("-")
        if len(pages) > 2 or not all(pages):
            raise ValueError("Unsupported publisher page range")
        for field, page in (("firstpage", pages[0]), ("lastpage", pages[-1])):
            tag = "citation_" + field
            if tag in result and any(normalize_pages(v) != page for v in result[tag]):
                raise ValueError("Publisher page coordinates conflict")
            result[tag] = [page]
    return result


def fetch_elsevier_metadata(cache, client, doi):
    doi = normalize_doi(doi)
    if not doi.startswith(("10.1016/", "10.1006/")):
        raise ValueError("This collector is limited to Elsevier and Academic Press DOIs")
    identity = "publisher-title-elsevier-xml-v1:" + doi
    cached = cache.response(identity, 30 * 86400)
    if cached is not None and not client.refresh:
        return cached
    url = "https://api.elsevier.com/content/article/doi/" + quote(doi, safe="/")
    class CountedSession:
        def get(self, *args, **kwargs):
            return client.source_request(*args, **kwargs)
    result = {"url": url, "retrieved_at": now(), "source_kind": "elsevier_coredata", "metadata": {}}
    try:
        xml, final = get_source(CountedSession(), url, {"api.elsevier.com"}, params={"httpAccept": "text/xml"})
        result.update(url=final, raw_xml=xml, document_sha256=hashlib.sha256(xml.encode()).hexdigest())
        result["metadata"] = elsevier_metadata(xml)
        if normalize_doi(result["metadata"]["citation_doi"][0]) != doi:
            raise ValueError("Requested and returned publisher DOIs differ")
    except requests.RequestException as exc:
        raise ProviderError("Publisher XML retrieval failed: " + str(exc)) from exc
    except SourceHTTPError as exc:
        if exc.status == 429 or exc.status >= 500:
            raise ProviderError(f"Publisher HTTP {exc.status}; retry later (Retry-After: {exc.retry_after})") from exc
        result["error"] = str(exc)
    except (ValueError, KeyError, ET.ParseError) as exc:
        result["error"] = str(exc)
    cache.save_response(identity, result)
    return result


def eligible(primary, field="title"):
    if field not in {"title", "author"}:
        raise ValueError("Unsupported publisher correction field")
    allowed = ({"title: missing evidence or mismatch"} if field == "title" else
               {"author: " + detail for detail in ("Missing authors or different author counts",
                "Author surnames/order differ", "Author suffix differs", "Missing or incomplete given names",
                "Author given names differ")})
    return (primary.get("source") == "crossref"
            and primary.get("record", {}).get("type") == "journal-article"
            and bool(set(primary.get("issues", [])) & allowed)
            and not set(primary["issues"]) - (allowed | {
                "number: source supplies a field absent from the citation"}))


def contradicts(fields, metadata):
    """Never discard conflicting coordinates exposed by the same HTML head."""
    mapped = {"DOI": metadata["citation_doi"][0], "title": metadata["citation_title"], "type": "journal-article"}
    checked = {"doi", "title"}
    for source, target, evidence in (("journal_title", "container-title", "journal"), ("volume", "volume", "volume"),
                                     ("issue", "issue", "number"), ("publisher", "publisher", "publisher")):
        values = metadata.get("citation_" + source, [])
        if values:
            if len(values) != 1:
                return True
            mapped[target] = values if target == "container-title" else values[0]
            checked.add(evidence)
    dates = metadata.get("citation_publication_date", []) + metadata.get("citation_date", [])
    if dates:
        if (any(not re.fullmatch(r"[1-9]\d{3}(?:[-/]\d{1,2}){0,2}", date) for date in dates)
                or len({date[:4] for date in dates}) != 1):
            return True
        mapped["published"] = {"date-parts": [[int(dates[0][:4])]]}
        checked.add("year")
    people = metadata.get("citation_author", [])
    if people:
        mapped["author"] = []
        for person in people:
            name = splitname(person, strict_mode=True)
            mapped["author"].append({"given": " ".join(name["first"]), "family": " ".join(name["von"] + name["last"]), "suffix": " ".join(name["jr"])})
        checked.add("author")
    pages = normalize_pages(fields.get("pages", ""))
    for tag, expected in (("firstpage", pages.split("-")[0]), ("lastpage", pages.split("-")[-1])):
        values = metadata.get("citation_" + tag, [])
        if values and (len(values) != 1 or normalize_pages(values[0]) != expected):
            return True
    evidence, issues = compare_record(fields, mapped)
    return any(i.split(":", 1)[0] in checked for i in issues)


def fetch_publisher_head(cache, client, doi):
    # The new Frontiers route may retry its former unsupported-host result.
    # Other publishers retain their existing positive and negative responses.
    identity = ("publisher-title-frontiers-head-v2:" if normalize_doi(doi).startswith("10.3389/")
                else "publisher-title-head-v2:") + normalize_doi(doi)
    cached = cache.response(identity, 30 * 86400)
    if cached is not None and not client.refresh:
        return cached
    legacy = cache.response("publisher-title-head-v1:" + normalize_doi(doi), 30 * 86400)
    if (legacy is not None and not client.refresh and not normalize_doi(doi).startswith("10.3389/")
            and not legacy.get("error", "").startswith("PDF URL must use HTTPS")):
        cache.save_response(identity, legacy)
        return legacy

    redirects = []
    class CountedSession:
        def get(self, *args, **kwargs):
            response = client.source_request(*args, **kwargs)
            if response.status_code in (301, 302, 303, 307, 308):
                redirects.append({"url": args[0], "status": response.status_code, "location": response.headers.get("Location")})
            return response

    try:
        html, url = get_source(CountedSession(), "https://doi.org/" + quote(doi, safe="/"), HOSTS,
                               max_redirects=6 if normalize_doi(doi).startswith("10.3389/") else 3,
                               https_redirect_hosts=HOSTS - {"doi.org", "dx.doi.org"})
        parser = PublisherMetadata()
        parser.feed(html)
        result = {"url": url, "retrieved_at": now(), "document_sha256": hashlib.sha256(html.encode()).hexdigest(),
                  "metadata": parser.source_metadata(), "redirects": redirects}
    except requests.RequestException as exc:
        raise ProviderError("Publisher retrieval failed: " + str(exc)) from exc
    except SourceHTTPError as exc:
        if exc.status == 429 or exc.status >= 500:
            raise ProviderError(f"Publisher HTTP {exc.status}; retry later (Retry-After: {exc.retry_after})") from exc
        result = {"url": "https://doi.org/" + doi, "retrieved_at": now(), "metadata": {}, "error": str(exc)}
    except ValueError as exc:
        result = {"url": "https://doi.org/" + doi, "retrieved_at": now(), "metadata": {}, "error": str(exc)}
    result.setdefault("redirects", redirects)
    cache.save_response(identity, result)
    return result


def publisher_title_proposal(entry, previous, response):
    return publisher_field_proposal(entry, previous, response, "title")


def publisher_field_proposal(entry, previous, response, field):
    """Require the publisher's own title/byline to corroborate a single repair."""
    if field not in {"title", "author"}:
        raise ValueError("Unsupported publisher correction field")
    if (entry["fields"].get("ENTRYTYPE") != "article" or previous.get("status") != "needs_review"
            or previous.get("external_evidence") or response.get("error")):
        return None
    try:
        url = urlparse(response["url"])
        xml_source = response.get("source_kind") == "elsevier_coredata"
        if (url.scheme != "https" or url.username or url.password or url.port not in (None, 443)):
            return None
        if xml_source:
            if (url.hostname != "api.elsevier.com" or not url.path.startswith("/content/article/doi/")
                    or hashlib.sha256(response["raw_xml"].encode()).hexdigest() != response["document_sha256"]
                    or elsevier_metadata(response["raw_xml"]) != response["metadata"]):
                return None
        elif url.hostname not in PUBLISHERS or not url.path.startswith(PUBLISHERS[url.hostname]):
            return None
        if not re.fullmatch(r"[a-f0-9]{64}", response.get("document_sha256", "")):
            return None
        metadata = response["metadata"]
        if any(not isinstance(v, list) or any(not isinstance(x, str) or not x.strip() for x in v) for v in metadata.values()):
            return None
        if len(metadata.get("citation_doi", [])) != 1 or len(metadata.get("citation_title", [])) != 1:
            return None
        doi = normalize_doi(metadata["citation_doi"][0])
        if xml_source and normalize_doi(unquote(url.path.removeprefix("/content/article/doi/"))) != doi:
            return None
        choices = {}
        for primary in previous.get("candidates", []):
            if not eligible(primary, field) or normalize_doi(primary["record"]["DOI"]) != doi:
                continue
            fields, record = entry["fields"], primary["record"]
            if fields.get("doi") and normalize_doi(fields["doi"]) != doi:
                continue
            titles = safe_compare(fields, record)[0]["title"]["source"]
            if len(titles) != 1 or normalize_title(titles[0]) != normalize_title(metadata["citation_title"][0]):
                continue
            if field == "author" and not metadata.get("citation_author"):
                continue
            value = source_title(titles[0], fields["title"]) if field == "title" else source_authors(record, fields.get("author"))
            if fields.get(field) == value:
                continue
            proposed = dict(entry, fields=dict(fields, **{field: value}))
            if metadata.get("citation_issn") and not set(metadata["citation_issn"]) & set(record.get("ISSN", [])):
                continue
            if contradicts(proposed["fields"], metadata):
                continue
            evidence, issues = safe_compare(proposed["fields"], record)
            if issues or not all(evidence.get(f, {}).get("match") for f in ("title", "author", "year", "journal", "volume", "pages")):
                continue
            secondary_conflict = False
            for candidate in previous.get("candidates", []):
                if candidate.get("source") == "europepmc" and candidate.get("doi") == doi:
                    mapped = epmc_record(candidate["raw_record"], record)
                    _, findings = safe_compare(proposed["fields"], mapped)
                    if any(f.split(":", 1)[0] not in {"publisher", "isbn"} for f in findings):
                        secondary_conflict = True
            if secondary_conflict:
                continue
            selected = reassess(proposed, previous)
            if selected["status"] != "metadata_verified" or selected.get("accepted_doi") != doi:
                continue
            choices[value] = {"kind": "publisher_corroborated_" + field, "key": entry["key"],
                "fingerprint": entry["fingerprint"], "changes": {field: {"before": fields.get(field), "after": value}},
                "doi": doi, "primary": deepcopy(primary), "publisher_source": deepcopy(response)}
        return next(iter(choices.values())) if len(choices) == 1 else None
    except (ValueError, KeyError, TypeError, AttributeError, ET.ParseError):
        return None


# ---------------------------------------------------------------------------
# Issue lookups (user decision 2026-09-24, spot-check findings). A proposal may
# write an issue number only when a source states it. When neither Crossref
# nor the DOI-linked PubMed record states it, look it up: PubMed E-utilities
# (by DOI, then by citation match), then the publisher page's citation_issue.
# The stored lookup is evidence for correction_proposals.confirm_issue.
# ---------------------------------------------------------------------------

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
ISSUE_HEAD_HOSTS = HOSTS | {"idp.springer.com"}  # Springer sets a cookie through its IdP, then returns


def _summary_matches(summary, doi, record):
    """A PubMed summary is the work when it names this DOI, or, lacking any DOI,
    has the registry title, volume and first page."""
    from verification import normalized
    dois = [a.get("value", "") for a in summary.get("articleids", []) if a.get("idtype") == "doi"]
    if dois:
        try:
            return any(normalize_doi(d) == normalize_doi(doi) for d in dois)
        except ValueError:
            return False
    try:
        title = (record.get("title") or [""])[0]
        page = normalize_pages(str(record.get("page") or "")).split("-")[0]
        return bool(title and page
                    and normalize_title(summary.get("title", "").rstrip(".")) == normalize_title(title)
                    and normalized(str(summary.get("volume", ""))) == normalized(str(record.get("volume", "")))
                    and normalize_pages(summary.get("pages", "")).split("-")[0] == page)
    except ValueError:
        return False


def pubmed_issue_lookup(client, doi, record):
    """PubMed E-utilities: search by DOI, else ecitmatch on journal, year,
    volume, first page and first-author surname; summaries must match the work."""
    from verification import normalized
    # The contact travels in the User-Agent; request identities stay free of it.
    base = {"tool": "bibcheck"}
    out = {"query": None, "pmids": [], "matched": []}
    search = client.get(EUTILS + "esearch.fcgi", dict(base, db="pubmed", term=f"{doi}[doi]", retmode="json"))
    ids = ((search.get("body") or {}).get("esearchresult") or {}).get("idlist", []) if search["http_status"] == 200 else []
    out["query"] = "doi"
    if not ids:
        venues = record.get("container-title") or []
        people = record.get("author") or []
        years = sorted({str(p[0]) for d in ("published-print", "issued") for p in record.get(d, {}).get("date-parts", []) if p and p[0]})
        page = normalize_pages(str(record.get("page") or "")).split("-")[0]
        if len(venues) == 1 and people and people[0].get("family") and years and record.get("volume") and page:
            key = "k1"
            bdata = "|".join([venues[0].replace("&amp;", "&").replace("|", " "), years[0], str(record["volume"]), page,
                              people[0]["family"], key, ""])
            match = client.get(EUTILS + "ecitmatch.cgi", dict(base, db="pubmed", retmode="xml", bdata=bdata), xml=True)
            out["query"] = "doi, then ecitmatch " + bdata
            text = (match.get("body") or "") if match["http_status"] == 200 else ""
            for line in text.splitlines():
                cells = line.strip().split("|")
                if len(cells) >= 7 and cells[5] == key and re.fullmatch(r"\d+", cells[6].strip()):
                    ids.append(cells[6].strip())
    out["pmids"] = ids
    if ids:
        summary = client.get(EUTILS + "esummary.fcgi", dict(base, db="pubmed", id=",".join(ids), retmode="json"))
        result = (summary.get("body") or {}).get("result", {}) if summary["http_status"] == 200 else {}
        for pmid in ids:
            item = result.get(pmid) or {}
            if item and _summary_matches(item, doi, record):
                out["matched"].append({"pmid": pmid, "issue": item.get("issue", ""), "volume": item.get("volume", ""),
                                       "pages": item.get("pages", ""), "title": item.get("title", ""),
                                       "journal": item.get("fulljournalname", "")})
    return out


def fetch_issue_head(cache, client, doi):
    """The publisher landing page's citation_* head (cached; own identity)."""
    doi = normalize_doi(doi)
    identity = "issue-head-v1:" + doi
    cached = cache.response(identity, 30 * 86400)
    if cached is not None and not client.refresh:
        return cached
    class CountedSession:
        def get(self, *args, **kwargs):
            return client.source_request(*args, **kwargs)
    try:
        html, url = get_source(CountedSession(), "https://doi.org/" + quote(doi, safe="/"), ISSUE_HEAD_HOSTS,
                               max_redirects=6, https_redirect_hosts=ISSUE_HEAD_HOSTS - {"doi.org", "dx.doi.org"})
        parser = PublisherMetadata()
        parser.feed(html)
        result = {"url": url, "retrieved_at": now(), "document_sha256": hashlib.sha256(html.encode()).hexdigest(),
                  "metadata": parser.source_metadata()}
    except requests.RequestException as exc:
        raise ProviderError("Publisher retrieval failed: " + str(exc)) from exc
    except SourceHTTPError as exc:
        if exc.status == 429 or exc.status >= 500:
            raise ProviderError(f"Publisher HTTP {exc.status}; retry later (Retry-After: {exc.retry_after})") from exc
        result = {"url": "https://doi.org/" + doi, "retrieved_at": now(), "metadata": {}, "error": str(exc)}
    except (ValueError, UnicodeDecodeError) as exc:
        result = {"url": "https://doi.org/" + doi, "retrieved_at": now(), "metadata": {}, "error": str(exc)}
    cache.save_response(identity, result)
    return result


def issue_lookup(cache, client, doi, record):
    """PubMed then publisher page; ``complete`` once both were consulted."""
    doi = normalize_doi(doi)
    lookup = {"doi": doi, "pubmed": pubmed_issue_lookup(client, doi, record)}
    if doi.startswith(("10.1016/", "10.1006/")):
        # ScienceDirect landing pages carry no citation_* head for scripts; the
        # publisher's own article API states prism:issueIdentifier.
        head = fetch_elsevier_metadata(cache, client, doi)
    else:
        head = fetch_issue_head(cache, client, doi)
    meta = head.get("metadata") or {}
    if not head.get("error") and not meta:
        head = dict(head, error="page has no citation metadata")
    page_dois = meta.get("citation_doi", []) or [v for v in meta.get("dc.identifier", []) if "10." in v]
    try:
        confirmed = len(page_dois) == 1 and normalize_doi(re.sub(r"^(?:doi:|https?://(?:dx\.)?doi\.org/)", "", page_dois[0].strip(), flags=re.I)) == doi
    except ValueError:
        confirmed = False
    lookup["publisher"] = {"url": head.get("url"), "error": head.get("error"), "doi_confirmed": confirmed,
                           "citation_issue": meta.get("citation_issue", [])}
    lookup["complete"] = True
    return lookup
