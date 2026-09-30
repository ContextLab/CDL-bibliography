"""Additional metadata routes for entries no Crossref search could pin down.

Routes (all discovery unless stated):

* PubMed E-utilities: ESearch by citation coordinates (volume, first page,
  year, first-author surname) and by title words plus first-author surname,
  then EFetch MEDLINE XML. A MEDLINE record is AUTHORITATIVE (user policy
  2026-09-22: Crossref or PubMed may each serve as the one source).
* Europe PMC by the APA doubled-slash DOI form (``10.1037//``). User-approved
  as a lookup key only; the PubMed record found still has to match fully.
* OpenAlex and Semantic Scholar title matches. These are LEADS only: a DOI or
  PMID they carry counts only after Crossref or PubMed returns the record.

Nothing here edits cdl.bib or approves anything. Judgement reuses the
committed resolver: new Crossref/Europe PMC candidates are appended to the
entry's saved evidence and re-judged with ``auto_review.reassess`` and
``correction_proposals.single_source_proposal``. MEDLINE records WITHOUT a
Crossref twin get the same identity rule (``single_source_identity``) and
the same field comparison (``compare_record``) and guards.

Requests go through ``verification.PoliteClient`` (serial, paced, bounded
retries, no negative caching of failures) backed by this module's own SQLite
cache; the main verification cache may be consulted read-only so repeats of
already-fetched Crossref DOIs cost nothing.
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from urllib.parse import parse_qs, quote, urlparse
import xml.etree.ElementTree as ET

import requests

from verification import (Cache, PoliteClient, ProviderError, compare_record, dumps, normalize_doi,
                          normalized, split_authors)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
OPENALEX = "https://api.openalex.org/works"
S2_MATCH = "https://api.semanticscholar.org/graph/v1/paper/search/match"
EPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
AUTHORITATIVE = {"crossref", "pubmed", "europepmc"}
LEAD_ONLY = {"openalex", "semanticscholar"}
HOST_INTERVALS = {  # seconds between requests; the client is strictly serial
    "api.crossref.org": 1.0,
    "eutils.ncbi.nlm.nih.gov": 0.5,  # NCBI: at most 3/s without an API key
    "www.ebi.ac.uk": 0.5,
    "api.openalex.org": 0.5,
    "api.semanticscholar.org": 1.5,  # shared unauthenticated pool
}
# MEDLINE publication types that are notices, not the cited article.
NOTICE_TYPES = {"published erratum", "retraction of publication", "expression of concern", "preprint"}
# CommentsCorrections RefTypes that do not change the cited work's identity.
BENIGN_REFTYPES = {"CommentIn", "CommentOn", "Cites"}
STOPWORDS = set("a an and are as at be by for from has in into is it its of on or that the their this to "
                "was were with within without de der die das und la le les des du el".split())


# --------------------------------------------------------------------------
# Transport


class CountingSession(requests.Session):
    """Counts network requests per host (the client's own counter is global)."""

    def __init__(self):
        super().__init__()
        self.by_host = Counter()
        self.blocked = {}  # host -> reason; cached responses still serve

    def get(self, url, *args, **kwargs):
        host = urlparse(url).hostname
        if host in self.blocked:
            raise ProviderError(f"{host}: not requested ({self.blocked[host]})")
        self.by_host[host] += 1
        return super().get(url, *args, **kwargs)


def block_on_budget(client, host, exc, limit=3600):
    """A provider that asks us to wait more than ``limit`` seconds (OpenAlex's
    free daily budget answers 429 with Retry-After ~ hours) is not requested
    again in this run; its cached responses still serve."""
    if not hasattr(client.session, "blocked"):
        return False
    match = re.search(r"HTTP 429; retry after (\d+)s", str(exc))
    if match and int(match[1]) > limit:
        client.session.blocked[host] = f"429 with Retry-After {match[1]} s at {time.strftime('%H:%M:%S')}"
        return True
    # A provider outage (5xx after the client's own bounded retries) twice in a
    # row: stop requesting it for this run rather than paying ~90 s per entry.
    outages = client.__dict__.setdefault("outages", Counter())
    if re.search(r"HTTP 5\d\d", str(exc)):
        outages[host] += 1
        if outages[host] >= 2:
            client.session.blocked[host] = f"repeated HTTP 5xx outage at {time.strftime('%H:%M:%S')}"
            return True
    return False


class LayeredCache:
    """This module's own response cache, with an optional READ-ONLY fallback
    to the main verification cache. A main-cache hit is copied (with its
    original fetch time) into the own cache so later repeats need neither."""

    def __init__(self, own_path, main_path=None):
        self.own = Cache(own_path)
        self.path = self.own.path
        self.db = self.own.db
        self.main = None
        if main_path and Path(main_path).exists():
            self.main = sqlite3.connect(f"file:{Path(main_path)}?mode=ro", uri=True, timeout=30)
        self.hits = Counter()

    def response(self, request, ttl):
        row = self.own.db.execute("SELECT fetched,body FROM responses WHERE request=?", (request,)).fetchone()
        if row and time.time() - row[0] < ttl:
            self.hits["own"] += 1
            return json.loads(row[1])
        if self.main is not None:
            row = self.main.execute("SELECT fetched,body FROM responses WHERE request=?", (request,)).fetchone()
            if row and time.time() - row[0] < ttl:
                self.hits["main"] += 1
                with self.own.db:
                    self.own.db.execute("INSERT OR REPLACE INTO responses VALUES (?,?,?)", (request, row[0], row[1]))
                return json.loads(row[1])
        return None

    def save_response(self, request, body):
        self.hits["network"] += 1
        self.own.save_response(request, body)

    def close(self):
        self.own.close()
        if self.main is not None:
            self.main.close()


def contact_email(main_path):
    """CROSSREF_MAILTO, else the contact already used in cached Crossref requests."""
    import os
    contact = os.environ.get("CROSSREF_MAILTO")
    if contact:
        return contact
    db = sqlite3.connect(f"file:{Path(main_path)}?mode=ro", uri=True)
    try:
        for (body,) in db.execute("SELECT body FROM responses"):
            url = urlparse(json.loads(body).get("url", ""))
            if url.hostname == "api.crossref.org":
                values = parse_qs(url.query).get("mailto", [])
                if values:
                    return values[0]
    finally:
        db.close()
    raise ValueError("No contact email: set CROSSREF_MAILTO")


def make_client(own_path, main_path=None, contact=None, offline=False):
    """PoliteClient over the layered cache. ``offline`` refuses any request."""
    cache = LayeredCache(own_path, main_path)
    contact = contact or contact_email(main_path)
    session = CountingSession()
    if offline:
        def refuse(url, *args, **kwargs):
            raise ProviderError(f"offline: request to {urlparse(url).hostname} refused")
        session.get = refuse
    client = PoliteClient(cache, contact, interval=0.5, session=session)
    client.host_intervals.update(HOST_INTERVALS)
    client.contact = contact
    return client


# --------------------------------------------------------------------------
# Text helpers


def fold(value):
    """Lower-case, accent-free plain text (for queries and lead screening only)."""
    try:
        text = normalized(value or "")
    except ValueError:
        text = re.sub(r"\\[A-Za-z]+|[{}\\$]", "", str(value or "")).lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def words(value):
    return re.findall(r"[a-z0-9]+", fold(value))


def first_surname(fields):
    from name_parsing import splitname
    try:
        name = split_authors(fields.get("author", ""))[0]
    except (IndexError, ValueError):
        return ""
    if not name or name.startswith("{"):
        return ""
    try:
        parts = splitname(name, strict_mode=True)
    except Exception:  # noqa: BLE001 - malformed names give no query term
        return ""
    return fold(" ".join(parts["last"]))


def first_page(fields):
    match = re.match(r"\s*([A-Za-z]{0,3}\d+)", fields.get("pages", ""))
    return match[1] if match else ""


def title_similarity(a, b):
    return SequenceMatcher(None, " ".join(words(a)), " ".join(words(b))).ratio()


def lead_matches(fields, title, surnames, year=None):
    """Screen an aggregator hit: similar title and the same first-author surname.

    Screening only decides whether a lead is worth confirming; identity is
    always decided later against the Crossref or PubMed record."""
    if not title or title_similarity(fields.get("title", ""), title) < 0.85:
        return False
    surname = first_surname(fields)
    if not surname or not surnames:
        return False
    return words(surname) == words(surnames[0])


# --------------------------------------------------------------------------
# PubMed


def pubmed_citation_term(fields):
    """volume[vi] AND page[pg] AND year[dp] AND surname[au]; None if incomplete."""
    volume, page, year = fields.get("volume", "").strip(), first_page(fields), fields.get("year", "").strip()
    surname = first_surname(fields)
    if not (re.fullmatch(r"\d+", volume) and page and re.fullmatch(r"\d{4}", year) and surname):
        return None
    return f"{volume}[vi] AND {page}[pg] AND {year}[dp] AND {surname}[au]"


def pubmed_title_term(fields, limit=8):
    """Up to ``limit`` significant title words [ti] plus first-author surname."""
    surname = first_surname(fields)
    significant = [w for w in words(fields.get("title", "")) if w not in STOPWORDS and len(w) > 2]
    if len(significant) < 2 or not surname:
        return None
    chosen = sorted(dict.fromkeys(significant), key=lambda w: (-len(w), significant.index(w)))[:limit]
    chosen.sort(key=significant.index)
    return " AND ".join(f"{w}[ti]" for w in chosen) + f" AND {surname}[au]"


def forget(client, url, params, xml=False):
    """Drop a cached response that turned out to be a provider error page.

    NCBI reports backend outages as HTTP 200 with an ERROR field, which the
    generic client caches like data; a cached error must never stand in for a
    search result on the next run."""
    identity = dumps([url, {k: v for k, v in params.items() if k != "mailto"}, xml])
    cache = getattr(client.cache, "own", client.cache)
    with cache.db:
        cache.db.execute("DELETE FROM responses WHERE request=?", (identity,))


def esearch(client, term, retmax=10, _retry=True):
    params = {"db": "pubmed", "term": term, "retmode": "json", "retmax": retmax, "tool": "bibcheck",
              "email": client.contact}
    response = client.get(EUTILS + "esearch.fcgi", params)
    body = response["body"]
    result = body.get("esearchresult") if isinstance(body, dict) else None
    if response["http_status"] != 200 or not isinstance(result, dict) or "ERROR" in result:
        forget(client, EUTILS + "esearch.fcgi", params)
        if _retry:
            return esearch(client, term, retmax, _retry=False)
        raise ProviderError(f"PubMed ESearch error for {term!r}: {str(result)[:200]}")
    ids = result.get("idlist")
    if not isinstance(ids, list) or any(not re.fullmatch(r"\d+", str(i)) for i in ids):
        raise ProviderError("Malformed PubMed ESearch id list")
    return {"term": term, "count": int(result.get("count", 0)), "pmids": [str(i) for i in ids],
            "url": response["url"], "retrieved_at": response["retrieved_at"]}


def efetch(client, pmids):
    pmids = sorted(dict.fromkeys(str(p) for p in pmids), key=int)
    if not pmids:
        return {}, None
    if len(pmids) > 50:
        raise ValueError("EFetch batches are limited to 50 PMIDs")
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "tool": "bibcheck",
              "email": client.contact}
    response = client.get(EUTILS + "efetch.fcgi", params, xml=True)
    try:
        if response["http_status"] != 200 or not response["body"]:
            raise ProviderError("PubMed EFetch returned no body")
        records = parse_medline(response["body"])
        if not records and "<PubmedBookArticle>" not in response["body"]:
            raise ProviderError(f"PubMed EFetch returned no article for {pmids}")
    except ProviderError:
        forget(client, EUTILS + "efetch.fcgi", params, xml=True)
        raise
    for record in records.values():
        record["retrieved_at"] = response["retrieved_at"]
        record["request_url"] = response["url"]
    return records, response


def _text(node):
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def parse_medline(xml):
    """PubmedArticleSet XML -> {pmid: raw record}. Books are skipped."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ProviderError("Malformed MEDLINE XML") from exc
    if root.tag != "PubmedArticleSet":
        raise ProviderError("Not a PubmedArticleSet")
    out = {}
    for item in root.findall("PubmedArticle"):
        citation = item.find("MedlineCitation")
        article = citation.find("Article")
        pmid = citation.findtext("PMID")
        journal = article.find("Journal")
        issue = journal.find("JournalIssue")
        date = issue.find("PubDate")
        year = date.findtext("Year") or (re.match(r"\s*(\d{4})", date.findtext("MedlineDate") or "") or [None, None])[1]
        authors = []
        for person in article.findall("AuthorList/Author"):
            if person.find("CollectiveName") is not None:
                authors.append({"name": _text(person.find("CollectiveName"))})
                continue
            authors.append({"family": person.findtext("LastName") or "",
                            "fore": person.findtext("ForeName") or "",
                            "initials": person.findtext("Initials") or "",
                            "suffix": person.findtext("Suffix") or ""})
        dois = [e.text.strip() for e in article.findall("ELocationID") if e.get("EIdType") == "doi" and e.text]
        dois += [a.text.strip() for a in item.findall("PubmedData/ArticleIdList/ArticleId")
                 if a.get("IdType") == "doi" and a.text]
        pmcs = [a.text.strip() for a in item.findall("PubmedData/ArticleIdList/ArticleId")
                if a.get("IdType") == "pmc" and a.text]
        out[pmid] = {
            "pmid": pmid,
            "title": _text(article.find("ArticleTitle")),
            "vernacular_title": _text(article.find("VernacularTitle")),
            "authors": authors,
            "author_list_complete": (article.find("AuthorList").get("CompleteYN", "Y")
                                     if article.find("AuthorList") is not None else "N"),
            "journal_title": journal.findtext("Title") or "",
            "iso_abbreviation": journal.findtext("ISOAbbreviation") or "",
            "medline_ta": citation.findtext("MedlineJournalInfo/MedlineTA") or "",
            "issns": [i.text.strip() for i in journal.findall("ISSN") if i.text],
            "volume": issue.findtext("Volume") or "",
            "issue": issue.findtext("Issue") or "",
            "year": year or "",
            "pages": article.findtext("Pagination/MedlinePgn") or "",
            "dois": list(dict.fromkeys(d.lower() for d in dois)),
            "pmcids": pmcs,
            "publication_types": [_text(t) for t in article.findall("PublicationTypeList/PublicationType")],
            "relations": [{"type": c.get("RefType"), "pmid": c.findtext("PMID") or "",
                           "source": c.findtext("RefSource") or ""}
                          for c in citation.findall("CommentsCorrectionsList/CommentsCorrections")],
        }
    return out


def medline_is_notice(raw):
    """Errata, retraction notices, expressions of concern and preprint records
    are never the cited article (a retracted or commented article still is)."""
    types = {t.lower() for t in raw.get("publication_types", [])}
    return bool(types & NOTICE_TYPES)


def medline_blocking_relations(raw):
    return [r for r in raw.get("relations", []) if r.get("type") not in BENIGN_REFTYPES]


def medline_venues(raw):
    return [v for v in (raw.get("journal_title"), raw.get("iso_abbreviation"), raw.get("medline_ta")) if v]


def venue_matches_medline(local, raw):
    """Venue equality up to case/punctuation, against the NLM title, the part of
    it before NLM's ' : ' disambiguator, the ISO abbreviation or MedlineTA."""
    want = words(local)
    if want[:1] == ["the"]:
        want = want[1:]
    for venue in medline_venues(raw) + [raw.get("journal_title", "").split(" : ")[0]]:
        have = words(venue)
        if have[:1] == ["the"]:
            have = have[1:]
        if want and want == have:
            return venue
    return None


def medline_record(raw, cited_venue=None):
    """Crossref-shaped view of a MEDLINE record for ``compare_record``.

    The venue list is the NLM title variants; when the cited venue equals one
    of them up to case and punctuation (``venue_matches_medline``) the cited
    spelling is included, and the record says so in ``venue_rule``."""
    from auto_review import expanded_pages
    people = []
    for person in raw["authors"]:
        if "name" in person:
            people.append({"name": person["name"]})
            continue
        given = person["fore"] or " ".join(person["initials"])
        people.append({"given": given, "family": person["family"], "suffix": person["suffix"]})
    title = raw["title"]
    if title.endswith(".") and not title.endswith(".."):
        title = title[:-1]
    venues = medline_venues(raw)
    matched = venue_matches_medline(cited_venue, raw) if cited_venue else None
    if matched:
        venues = venues + [cited_venue]
    record = {
        "PMID": raw["pmid"],
        "type": "journal-article",
        "title": [title],
        "author": people,
        "container-title": venues,
        "ISSN": raw["issns"],
        "published": {"date-parts": [[int(raw["year"])]]} if re.fullmatch(r"\d{4}", raw["year"]) else {},
        "volume": raw["volume"] or None,
        "issue": raw["issue"] or None,
        "page": expanded_pages(raw["pages"]) if raw["pages"] else None,
    }
    if len(raw["dois"]) == 1:
        record["DOI"] = raw["dois"][0]
    if matched:
        record["venue_rule"] = f"cited venue equals NLM venue {matched!r} up to case/punctuation"
    return record


def route_pubmed(client, fields):
    """Two ESearch queries, one EFetch of the union (at most 10 PMIDs)."""
    searches, pmids = [], []
    for kind, term in (("citation", pubmed_citation_term(fields)), ("title", pubmed_title_term(fields))):
        if not term:
            continue
        found = esearch(client, term)
        found["kind"] = kind
        searches.append(found)
        if found["count"] <= 5:  # a broad hit list is not a lookup
            pmids += found["pmids"]
    pmids = list(dict.fromkeys(pmids))[:10]
    records = efetch(client, pmids)[0] if pmids else {}
    return {"searches": searches, "records": records}


# --------------------------------------------------------------------------
# Europe PMC (APA doubled-slash DOI form, lookup key only)


def apa_double_slash(doi):
    doi = normalize_doi(doi)
    if doi.startswith("10.1037/") and not doi.startswith("10.1037//"):
        return "10.1037//" + doi[len("10.1037/"):]
    return None


def route_epmc_doi(client, doi):
    """Exact DOI query; returns (MED raw records, response)."""
    from auto_review import fetch_epmc
    indexed, response = fetch_epmc(client, [doi])
    return indexed.get(normalize_doi(doi), []), response


# --------------------------------------------------------------------------
# Aggregators (leads only)


def route_openalex(client, fields):
    title = " ".join(words(fields.get("title", "")))
    if len(title.split()) < 2:
        return {"leads": [], "hits": 0}
    response = client.get(OPENALEX, {"filter": "title.search:" + title, "per_page": 5,
                                     "select": "id,doi,display_name,publication_year,ids,authorships,type"})
    body = response["body"]
    if response["http_status"] != 200 or not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise ProviderError("OpenAlex returned no result list")
    leads = []
    for work in body["results"]:
        names = [(a.get("author") or {}).get("display_name") or a.get("raw_author_name") or ""
                 for a in work.get("authorships") or []]
        surnames = [n.split()[-1] if n.split() else "" for n in names]
        if not lead_matches(fields, work.get("display_name") or "", surnames):
            continue
        ids = work.get("ids") or {}
        doi = work.get("doi") or ids.get("doi")
        pmid = ids.get("pmid")
        leads.append({"source": "openalex", "id": work.get("id"), "title": work.get("display_name"),
                      "year": work.get("publication_year"), "type": work.get("type"),
                      "doi": normalize_doi(doi) if doi else None,
                      "pmid": re.sub(r"\D", "", pmid.rsplit("/", 1)[-1]) if pmid else None})
    return {"leads": leads, "hits": len(body["results"]), "url": response["url"]}


def route_semantic_scholar(client, fields):
    title = " ".join(words(fields.get("title", "")))
    if len(title.split()) < 2:
        return {"leads": [], "hits": 0}
    response = client.get(S2_MATCH, {"query": title,
                                      "fields": "title,year,authors,venue,externalIds,publicationTypes"})
    body = response["body"]
    if response["http_status"] == 404 or body is None:
        return {"leads": [], "hits": 0, "url": response["url"]}
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ProviderError("Semantic Scholar returned no data list")
    leads = []
    for paper in body["data"]:
        surnames = [(a.get("name") or "").split()[-1] if (a.get("name") or "").split() else ""
                    for a in paper.get("authors") or []]
        if not lead_matches(fields, paper.get("title") or "", surnames):
            continue
        ext = paper.get("externalIds") or {}
        doi = ext.get("DOI")
        try:
            doi = normalize_doi(doi) if doi else None
        except ValueError:
            doi = None
        leads.append({"source": "semanticscholar", "id": paper.get("paperId"), "title": paper.get("title"),
                      "year": paper.get("year"), "venue": paper.get("venue"), "doi": doi,
                      "pmid": str(ext["PubMed"]) if ext.get("PubMed") else None})
    return {"leads": leads, "hits": len(body["data"]), "url": response["url"]}


# --------------------------------------------------------------------------
# Confirmation: authoritative records


def crossref_candidate(client, doi):
    """Crossref record for a lead DOI as a resolver candidate, or None (404)."""
    response = client.crossref_doi(doi)
    if response["http_status"] != 200 or not response.get("body"):
        return None
    record = response["body"]["message"]
    candidate = {"source": "crossref", "doi": record.get("DOI"),
                 "url": "https://doi.org/" + quote(record.get("DOI", ""), safe="/"),
                 "record": record, "retrieved_at": response["retrieved_at"]}
    if response.get("doi_alias"):
        candidate["doi_alias"] = response["doi_alias"]
    return candidate


def epmc_candidates(client, doi):
    raws, response = route_epmc_doi(client, doi)
    return [{"source": "europepmc", "doi": doi, "raw_record": raw,
             "retrieved_at": response["retrieved_at"], "request_url": response["url"]} for raw in raws]


# --------------------------------------------------------------------------
# PubMed-only judgement (MEDLINE record with no Crossref record)


def pubmed_only_assessment(entry, raws, crossref_records=()):
    """Judge MEDLINE records that have no Crossref twin under the S1 rule.

    Returns {"outcome": ..., ...}. Outcomes: verify (every field matches one
    uniquely identified record), proposal (one or two fields differ, all S1
    guards pass), held (identified but not correctable), ambiguous, or none.
    Crossref records that are themselves identified as the cited work take
    precedence: PubMed-only judgement then holds (sources are not merged).
    """
    from correction_proposals import (HELD_SUBCLASSES, MAX_SINGLE_SOURCE_FIELDS, _issue_fields, _title_words,
                                      byline_adds_information, change_subclass, loses_characters,
                                      shortens_pages, single_source_identity, source_authors, source_title,
                                      surname_change_hold)
    from auto_review import expanded_pages
    fields = entry["fields"]
    evaluated = {k: v for k, v in fields.items() if k != "publisher"}
    identified = {}
    for pmid, raw in raws.items():
        if medline_is_notice(raw):
            continue
        try:
            record = medline_record(raw, fields.get("journal"))
        except (ValueError, KeyError, TypeError) as exc:
            identified.setdefault("_errors", []).append(f"{pmid}: {exc}")
            continue
        probe = dict(evaluated)
        if probe.get("doi") and record.get("DOI") is None:
            probe.pop("doi")  # a MEDLINE record without a DOI can still carry the identity by I1/I2
        rule = single_source_identity(probe, record)
        if rule:
            identified[pmid] = (rule, record, raw)
    identified.pop("_errors", None)
    if not identified:
        return {"outcome": "none"}
    if len(identified) > 1:
        return {"outcome": "ambiguous", "reason": "several PubMed records satisfy the identity rule",
                "pmids": sorted(identified)}
    pmid, (rule, record, raw) = next(iter(identified.items()))
    base = {"pmid": pmid, "identity": rule, "source": "pubmed", "record": record,
            "requires_publisher_drop": bool(fields.get("publisher"))}
    for other in crossref_records:
        if single_source_identity(evaluated, other):
            return dict(base, outcome="held", reason="crossref-record-identified",
                        detail=f"Crossref {other.get('DOI')} is also identified; resolver judgement applies")
    if medline_blocking_relations(raw):
        return dict(base, outcome="held", reason="pubmed-relation",
                    detail=", ".join(sorted({r['type'] for r in medline_blocking_relations(raw)})))
    if raw.get("author_list_complete") == "N":
        return dict(base, outcome="held", reason="pubmed-author-list-incomplete")
    probe = dict(evaluated)
    if probe.get("doi") and record.get("DOI") is None:
        return dict(base, outcome="held", reason="citation-doi-not-in-pubmed")
    evidence, issues = compare_record(probe, record)
    changed, blockers = _issue_fields(issues)
    changed.discard("publisher")
    blockers = {b for b in blockers if b != "extra-field:publisher"}
    if blockers:
        return dict(base, outcome="held", reason="not-correctable", blockers=sorted(blockers),
                    fields=sorted(changed))
    if changed == {"number"} and not fields.get("number"):
        return dict(base, outcome="held", reason="advisory-only")
    if not changed:
        return dict(base, outcome="verify", evidence=evidence)
    if {"doi", "issn", "isbn"} & changed:
        return dict(base, outcome="held", reason="identifier-conflict", fields=sorted(changed))
    if len(changed) > MAX_SINGLE_SOURCE_FIELDS:
        return dict(base, outcome="held", reason="too-many-fields", fields=sorted(changed))
    values = {}
    try:
        for field in sorted(changed):
            if field == "title":
                if raw.get("vernacular_title") or raw["title"].startswith("["):
                    raise ValueError("title: MEDLINE gives a translated title")
                old, new = _title_words(fields.get("title", "")), _title_words(record["title"][0])
                if len(new) < len(old) and old[:len(new)] == new:
                    raise ValueError("title: citation title has words the source lacks")
                values[field] = source_title(record["title"][0], fields.get("title", ""))
            elif field == "author":
                if not byline_adds_information(fields.get("author", ""), record["author"]):
                    raise ValueError("author: citation byline has detail the source lacks")
                if any(p.get("family", "").isupper() and len(p.get("family", "")) > 1 for p in record["author"]):
                    raise ValueError("author: MEDLINE surname in capitals (old record style)")
                values[field] = source_authors(record)
                hold = surname_change_hold(entry["key"], fields.get("author"), values[field],
                                           source=f"PubMed {pmid}")
                if hold:
                    raise ValueError(hold)
            elif field == "year":
                values[field] = str(record["published"]["date-parts"][0][0])
            elif field == "journal":
                raise ValueError("journal: NLM title style is not a citation venue")
            elif field in {"volume", "number"}:
                value = str(record.get("issue" if field == "number" else "volume") or "")
                if not re.fullmatch(r"[1-9]\d*", value):
                    raise ValueError(field + ": no plain numeric source value")
                values[field] = value
            elif field == "pages":
                pages = expanded_pages(record.get("page") or "")
                if not re.fullmatch(r"[a-z]{0,3}\d+(?:-[a-z]{0,3}\d+)?", pages):
                    raise ValueError("pages: unsupported source locator")
                values[field] = pages.replace("-", "--")
                if shortens_pages(fields.get("pages"), values[field]):
                    raise ValueError("pages: the source would shorten the cited range")
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return dict(base, outcome="held", reason="value-held", detail=str(exc), fields=sorted(changed))
    values = {f: v for f, v in values.items() if fields.get(f) != v}
    if not values:
        return dict(base, outcome="held", reason="no-change-possible", fields=sorted(changed))
    lossy = sorted(f for f, v in values.items() if loses_characters(fields.get(f), v))
    if lossy:
        return dict(base, outcome="held", reason="value-held", detail="drops accents: " + ", ".join(lossy))
    subclasses = {f: change_subclass(f, fields.get(f), v, year=fields.get("year")) for f, v in values.items()}
    held = sorted(f for f, sub in subclasses.items() if sub in HELD_SUBCLASSES)
    if held:
        return dict(base, outcome="held", reason="value-held",
                    detail="; ".join(f"{f}: {subclasses[f]}" for f in held))
    proposed = dict(probe, **values)
    remaining = compare_record(proposed, record)[1]
    remaining = [i for i in remaining if not i.startswith("publisher")]
    if remaining:
        return dict(base, outcome="held", reason="would-not-match-source", detail="; ".join(remaining))
    return dict(base, outcome="proposal", subclasses=subclasses,
                changes={f: {"before": fields.get(f), "after": v} for f, v in sorted(values.items())})


# --------------------------------------------------------------------------
# One entry, all routes


def gather(client, entry, previous, routes=("pubmed", "epmc-apa", "openalex", "s2"), s2_fallback_only=False):
    """Run the routes for one entry; returns raw evidence and per-route log.

    A provider error on one route is recorded (never read as 'nothing found')
    and the other routes still run."""
    fields = entry["fields"]
    log, leads, pubmed = {}, [], {}
    # PoliteClient doubles a host's interval after a 429/5xx (up to 60 s) and
    # never lowers it, so one transient 429 slowed every later request of the
    # run to one per minute. Halve any raised interval once per entry, never
    # below the host's base spacing.
    for host, interval in list(client.host_intervals.items()):
        client.host_intervals[host] = max(HOST_INTERVALS.get(host, client.interval), interval / 2)
    if "pubmed" in routes:
        try:
            found = route_pubmed(client, fields)
            pubmed.update(found["records"])
            log["pubmed"] = {"searches": [{k: s[k] for k in ("kind", "term", "count", "pmids")}
                                          for s in found["searches"]],
                             "pmids": sorted(found["records"])}
        except ProviderError as exc:
            log["pubmed"] = {"error": str(exc)}
            block_on_budget(client, "eutils.ncbi.nlm.nih.gov", exc)
    apa = []
    if "epmc-apa" in routes:
        seen = {normalize_doi(c["doi"]) for c in previous.get("candidates", [])
                if c.get("source") == "europepmc" and c.get("doi")}
        for doi in plausible_candidate_dois(fields, previous):
            twin = apa_double_slash(doi)
            if twin and twin not in seen and doi not in seen:
                apa.append(twin)
        apa = apa[:3]
        log["epmc-apa"] = {"queried": apa, "found": {}}
    for name, func in (("openalex", route_openalex), ("s2", route_semantic_scholar)):
        if name not in routes:
            continue
        if name == "s2":
            if s2_fallback_only and (pubmed or any(lead.get("doi") or lead.get("pmid") for lead in leads)):
                log[name] = {"skipped": "fallback only: another route already produced a lead"}
                continue
            # PoliteClient doubles a host's interval after each 429 and never
            # lowers it; Semantic Scholar's shared unauthenticated pool returns
            # 429 often, which stalled every host at 60 s. Restart each call at
            # a fixed conservative 3 s spacing (in-call retries still back off).
            client.host_intervals["api.semanticscholar.org"] = 3.0
        try:
            found = func(client, fields)
            leads += found["leads"]
            log[name] = {"hits": found["hits"], "leads": found["leads"]}
        except ProviderError as exc:
            log[name] = {"error": str(exc)}
            host = urlparse(OPENALEX if name == "openalex" else S2_MATCH).hostname
            block_on_budget(client, host, exc)
    return {"log": log, "leads": leads, "pubmed": pubmed, "apa": apa}


def plausible_candidate_dois(fields, previous):
    """Saved Crossref candidates whose title is the cited title or close to it."""
    out = []
    for c in previous.get("candidates", []):
        if c.get("source") != "crossref" or not c.get("record"):
            continue
        titles = c["record"].get("title") or []
        if any(title_similarity(fields.get("title", ""), t) >= 0.8 for t in titles):
            try:
                out.append(normalize_doi(c["doi"]))
            except (ValueError, KeyError):
                continue
    return list(dict.fromkeys(out))


def confirm(client, entry, previous, gathered):
    """Turn leads into authoritative candidates (Crossref by DOI, PubMed by PMID).

    Returns (new_candidates, pubmed_only_raws, provenance) where provenance maps
    each DOI / 'pmid:N' to the set of routes that led to it."""
    provenance, dois, pmids = {}, [], []
    for pmid, raw in gathered["pubmed"].items():
        provenance.setdefault("pmid:" + pmid, set()).add("pubmed")
        for doi in raw["dois"]:
            provenance.setdefault(doi, set()).add("pubmed")
            dois.append(doi)
    for lead in gathered["leads"]:
        route = "openalex" if lead["source"] == "openalex" else "s2"
        if lead.get("doi"):
            provenance.setdefault(lead["doi"], set()).add(route)
            dois.append(lead["doi"])
        if lead.get("pmid"):
            provenance.setdefault("pmid:" + lead["pmid"], set()).add(route)
            pmids.append(lead["pmid"])
    for twin in gathered["apa"]:
        provenance.setdefault(twin, set()).add("epmc-apa")
    raws = dict(gathered["pubmed"])
    extra = [p for p in dict.fromkeys(pmids) if p not in raws][:10]
    errors = {}
    if extra:
        try:
            fetched = efetch(client, extra)[0]
            raws.update(fetched)
            for pmid, raw in fetched.items():
                for doi in raw["dois"]:
                    provenance.setdefault(doi, set()).update(provenance.get("pmid:" + pmid, set()))
                    dois.append(doi)
        except ProviderError as exc:
            errors["efetch"] = str(exc)
    existing = {}
    for c in previous.get("candidates", []):
        if c.get("source") == "crossref" and c.get("doi"):
            try:
                existing.setdefault(normalize_doi(c["doi"]), c)
            except ValueError:
                pass
    new, crossref_found = [], {}
    for doi in list(dict.fromkeys(dois)) + list(gathered["apa"]):
        try:
            doi = normalize_doi(doi)
        except ValueError:
            continue
        if doi in crossref_found:
            continue
        try:
            candidate = crossref_candidate(client, doi)
        except ProviderError as exc:
            errors["crossref:" + doi] = str(exc)
            block_on_budget(client, "api.crossref.org", exc)
            continue
        crossref_found[doi] = candidate
        if candidate and doi not in existing:
            new.append(candidate)
    # DOI-linked PubMed evidence (Europe PMC core record, as the resolver uses it)
    epmc_seen = {normalize_doi(c["doi"]) for c in previous.get("candidates", [])
                 if c.get("source") == "europepmc" and c.get("doi")}
    for doi, candidate in crossref_found.items():
        if not candidate or doi in epmc_seen:
            continue
        linked = doi in gathered["apa"] or any(doi in raw["dois"] for raw in raws.values())
        if not linked:
            continue
        try:
            found = epmc_candidates(client, doi)
        except ProviderError as exc:
            errors["epmc:" + doi] = str(exc)
            block_on_budget(client, "www.ebi.ac.uk", exc)
            continue
        new += found
        if doi in gathered["apa"]:
            gathered.setdefault("apa_found", {})[doi] = [c["raw_record"].get("id") for c in found]
    # MEDLINE records with no Crossref record for any of their DOIs. A DOI
    # whose Crossref lookup failed is NOT absence: that record is withheld.
    failed = {k.split(":", 1)[1] for k in errors if k.startswith("crossref:")}
    pubmed_only = {pmid: raw for pmid, raw in raws.items()
                   if not any(crossref_found.get(d) or d in existing or d in failed for d in raw["dois"])}
    records = {d: c["record"] for d, c in crossref_found.items() if c}
    records.update({d: c["record"] for d, c in existing.items() if d in crossref_found and not crossref_found[d]
                    and isinstance(c.get("record"), dict)})
    return new, pubmed_only, provenance, errors, {d: bool(c) for d, c in crossref_found.items()}, records


def record_summary(fields, record, ident):
    """How a found authoritative record compares with the citation (for
    review packets and grouping only; never an identity decision)."""
    from correction_proposals import single_source_identity
    title = (record.get("title") or [""])[0]
    people = record.get("author") or []
    family = (people[0].get("family") or people[0].get("name") or "") if people else ""
    try:
        issues = compare_record({k: v for k, v in fields.items() if k != "publisher"}, record)[1]
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        issues = [f"unsupported: {exc}"]
    differs = sorted({i.split(":", 1)[0] for i in issues if i.split(":", 1)[0] in
                      {"title", "author", "year", "journal", "volume", "number", "pages", "doi"}})
    return {"id": ident, "type": record.get("type"), "title": title,
            "title_similarity": round(title_similarity(fields.get("title", ""), title), 3),
            "first_author_match": bool(family) and words(family) == words(first_surname(fields)),
            "identity_rule": single_source_identity({k: v for k, v in fields.items() if k != "publisher"}, record),
            "differs": differs, "other_issues": [i for i in issues if i.split(":", 1)[0] not in differs]}


def judge(entry, previous, new_candidates, pubmed_only):
    """Re-judge with the committed resolver, then the S1 proposal rule, then
    the PubMed-only rule. Returns a dict with 'outcome'."""
    from auto_review import reassess
    from correction_proposals import single_source_proposal
    augmented = dict(previous, candidates=list(previous.get("candidates", [])) + new_candidates)
    before = reassess(entry, previous)
    after = reassess(entry, augmented)
    if after["status"] == "metadata_verified":
        return {"outcome": "verify", "via": "resolver", "doi": after.get("accepted_doi"),
                "accepted_source": after.get("accepted_source"),
                "without_new_evidence": before["status"] == "metadata_verified"}
    explain = {}
    proposal = single_source_proposal(entry, augmented, explain)
    if proposal:
        old = single_source_proposal(entry, previous, {})
        return {"outcome": "proposal", "via": "S1", "doi": proposal["doi"], "rule": proposal["rule"],
                "changes": proposal["changes"], "subclasses": proposal.get("subclasses"),
                "source": proposal["source"], "requires_publisher_drop": proposal["requires_publisher_drop"],
                "without_new_evidence": bool(old)}
    crossref_records = [c["record"] for c in augmented["candidates"] if c.get("source") == "crossref"
                        and isinstance(c.get("record"), dict)]
    pm = pubmed_only_assessment(entry, pubmed_only, crossref_records) if pubmed_only else {"outcome": "none"}
    if pm["outcome"] in {"verify", "proposal"}:
        pm = dict(pm, via="pubmed-only")
        pm.pop("record", None)
        pm.pop("evidence", None)
        return pm
    return {"outcome": "held", "resolver_issues": after.get("issues", []), "s1_explain": explain,
            "pubmed_only": {k: v for k, v in pm.items() if k not in {"record", "evidence"}}}
