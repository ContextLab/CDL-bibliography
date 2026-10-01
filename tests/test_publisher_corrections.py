"""Publisher title evidence cannot hide conflicts in other exposed fields."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from cdlbib.auto_review import reassess
from cdlbib.publisher_corrections import publisher_title_proposal


def case():
    data = json.loads((Path(__file__).parent / "fixtures/pagination_corrections.json").read_text())["MoheEtal14"]
    entry = data["entry"]
    entry["fields"].update(pages="315--324", title="A wrong title")
    previous = reassess(entry, data["previous"])
    primary = next(c for c in previous["candidates"] if c["source"] == "crossref")
    response = {"url": "https://journals.sagepub.com/doi/10.1177/0956797613511257", "retrieved_at": "2026-09-16",
                "document_sha256": "a" * 64, "metadata": {"citation_title": primary["record"]["title"],
                "citation_doi": [primary["doi"]], "citation_journal_title": primary["record"]["container-title"],
                "citation_publication_date": ["2014/02/01"], "citation_volume": ["25"], "citation_issue": ["2"],
                "citation_firstpage": ["315"], "citation_lastpage": ["324"]}}
    return entry, previous, response


def test_corroborated_title_proposal_is_pure():
    entry, previous, response = case()
    before = deepcopy((entry, previous, response))
    proposal = publisher_title_proposal(entry, previous, response)
    assert proposal is not None
    assert set(proposal["changes"]) == {"title"}
    assert (entry, previous, response) == before
    proposed = dict(entry, fields=dict(entry["fields"], title=proposal["changes"]["title"]["after"]))
    assert reassess(proposed, previous)["status"] == "metadata_verified"


@pytest.mark.parametrize("field,value", [("doi", "10.1234/wrong"), ("title", "A different title"),
    ("author", "Somebody Else"), ("journal_title", "Other Journal"), ("volume", "999"),
    ("issue", "99"), ("firstpage", "314"), ("lastpage", "325"), ("publication_date", "2015/01/01")])
def test_exposed_publisher_conflicts_block_title_changes(field, value):
    entry, previous, response = case()
    response["metadata"]["citation_" + field] = [value]
    assert publisher_title_proposal(entry, previous, response) is None


@pytest.mark.parametrize("broken", ["host", "path", "hash", "duplicate_doi", "duplicate_title", "hold", "other_field"])
def test_identity_and_source_requirements(broken):
    entry, previous, response = case()
    if broken == "host": response["url"] = "https://example.org/doi/10.1177/0956797613511257"
    elif broken == "path": response["url"] = "https://journals.sagepub.com/blog/post"
    elif broken == "hash": response.pop("document_sha256")
    elif broken == "duplicate_doi": response["metadata"]["citation_doi"].append("10.1234/other")
    elif broken == "duplicate_title": response["metadata"]["citation_title"].append("Other title")
    elif broken == "hold": previous["external_evidence"] = [{"issue": "Unresolved identity"}]
    else:
        entry["fields"]["year"] = "1999"
        previous = reassess(entry, previous)
    assert publisher_title_proposal(entry, previous, response) is None


def test_known_pubmed_conflict_cannot_be_discarded():
    entry, previous, response = case()
    next(c["raw_record"] for c in previous["candidates"] if c["source"] == "europepmc")["pageInfo"] = "999-1000"
    assert publisher_title_proposal(entry, previous, response) is None


def test_publisher_route_works_for_records_not_indexed_in_pubmed():
    entry, previous, response = case()
    previous["candidates"] = [c for c in previous["candidates"] if c["source"] != "europepmc"]
    assert publisher_title_proposal(entry, previous, response) is not None


def test_frontiers_route_retries_old_host_failure_and_caches_result(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cdlbib.publisher_corrections import fetch_publisher_head
    from cdlbib.verification import Cache
    doi = "10.3389/fpsyg.2017.01454"
    cache = Cache(tmp_path / "cache.sqlite3")
    client = SimpleNamespace(refresh=False)
    calls = []
    def fetch(session, url, hosts, **kwargs):
        calls.append(url)
        assert "journal.frontiersin.org" in hosts
        assert "www.frontiersin.org" in hosts
        assert "journal.frontiersin.org" in kwargs["https_redirect_hosts"]
        return ('<html><head><meta name="citation_doi" content="' + doi + '"></head></html>',
                "https://www.frontiersin.org/journals/psychology/articles/" + doi + "/full")
    monkeypatch.setattr("cdlbib.publisher_corrections.get_source", fetch)
    old = {"error": "PDF URL must use HTTPS", "metadata": {}}
    try:
        cache.save_response("publisher-title-head-v2:" + doi, old)
        first = fetch_publisher_head(cache, client, doi)
        assert first["metadata"]["citation_doi"] == [doi]
        assert fetch_publisher_head(cache, client, doi) == first
        assert len(calls) == 1
        other = "10.1234/other"
        cache.save_response("publisher-title-head-v2:" + other, old)
        assert fetch_publisher_head(cache, client, other) == old
        assert len(calls) == 1
    finally:
        cache.close()


@pytest.mark.parametrize("target,allowed", [
    ("http://link.springer.com/article/10.1234/test", True),
    ("http://link.springer.com:80/article/10.1234/test", True),
    ("http://example.org/article/10.1234/test", False),
    ("http://link.springer.com.evil.test/article/10.1234/test", False),
    ("http://user@link.springer.com/article/10.1234/test", False),
    ("http://link.springer.com:8080/article/10.1234/test", False),
])
def test_legacy_redirects_never_send_http_or_upgrade_arbitrary_hosts(monkeypatch, target, allowed):
    from cdlbib.search_tools import get_source
    monkeypatch.setattr("cdlbib.search_tools.time.sleep", lambda seconds: None)
    class Response:
        def __init__(self, status, headers):
            self.status_code, self.headers = status, headers
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): yield b"<html><head></head></html>"
    class Session:
        def __init__(self): self.urls = []
        def get(self, url, **kwargs):
            self.urls.append(url)
            return Response(302, {"Location": target}) if len(self.urls) == 1 else Response(200, {})
    session = Session()
    args = (session, "https://doi.org/10.1234/test", {"doi.org", "link.springer.com"})
    if allowed:
        _, url = get_source(*args, https_redirect_hosts={"link.springer.com"})
        assert url == "https://link.springer.com/article/10.1234/test"
    else:
        with pytest.raises(ValueError):
            get_source(*args, https_redirect_hosts={"link.springer.com"})
        assert len(session.urls) == 1
    assert all(url.startswith("https://") for url in session.urls)


def xml_case():
    from xml.sax.saxutils import escape
    from cdlbib.publisher_corrections import elsevier_metadata
    import hashlib
    entry, previous, response = case()
    metadata = response["metadata"]
    xml = ('<full-text-retrieval-response xmlns="http://www.elsevier.com/xml/svapi/article/dtd" '
           'xmlns:dc="http://purl.org/dc/elements/1.1/" '
           'xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"><coredata>'
           '<prism:aggregationType>Journal</prism:aggregationType>'
           '<dc:title>' + escape(metadata["citation_title"][0]) + '</dc:title>'
           '<prism:doi>' + metadata["citation_doi"][0] + '</prism:doi>'
           '<prism:publicationName>' + escape(metadata["citation_journal_title"][0]) + '</prism:publicationName>'
           '<prism:coverDate>2014-02-01</prism:coverDate>'
           '<prism:volume>25</prism:volume><prism:issueIdentifier>2</prism:issueIdentifier>'
           '<prism:pageRange>315-324</prism:pageRange></coredata></full-text-retrieval-response>')
    response.update(url="https://api.elsevier.com/content/article/doi/" + metadata["citation_doi"][0],
                    source_kind="elsevier_coredata", raw_xml=xml, metadata=elsevier_metadata(xml),
                    document_sha256=hashlib.sha256(xml.encode()).hexdigest())
    return entry, previous, response


def test_coredata_title_proposal_retains_hashed_original_source():
    entry, previous, response = xml_case()
    proposal = publisher_title_proposal(entry, previous, response)
    assert proposal and proposal["publisher_source"] == response


@pytest.mark.parametrize("broken", ["doi_url", "hash", "metadata", "namespace", "nested_core", "duplicate_core", "markup", "entity", "page_conflict", "identity_conflict"])
def test_xml_source_identity_and_parsing_fail_closed(broken):
    import hashlib
    entry, previous, response = xml_case()
    if broken == "doi_url": response["url"] += "other"
    elif broken == "hash": response["document_sha256"] = "b" * 64
    elif broken == "metadata": response["metadata"]["citation_title"] = ["Another title"]
    else:
        xml = response["raw_xml"]
        if broken == "namespace": xml = xml.replace("http://www.elsevier.com/xml/svapi/article/dtd", "http://example.org/")
        elif broken == "nested_core": xml = xml.replace("<coredata>", "<references><coredata>").replace("</coredata>", "</coredata></references>")
        elif broken == "duplicate_core": xml = xml.replace("</coredata>", "</coredata><coredata/>")
        elif broken == "markup": xml = xml.replace("<dc:title>", "<dc:title><b/>")
        elif broken == "entity": xml = '<!DOCTYPE x [<!ENTITY evil "replacement">]>' + xml
        elif broken == "page_conflict": xml = xml.replace("</coredata>", "<prism:startingPage>999</prism:startingPage></coredata>")
        else: xml = xml.replace("</coredata>", "<dc:identifier>doi:10.1234/other</dc:identifier></coredata>")
        response.update(raw_xml=xml, document_sha256=hashlib.sha256(xml.encode()).hexdigest())
    assert publisher_title_proposal(entry, previous, response) is None


def test_xml_ignores_reference_titles_and_normalizes_only_issn_punctuation():
    from cdlbib.publisher_corrections import elsevier_metadata
    _, _, response = xml_case()
    xml = response["raw_xml"].replace("</coredata>", "<prism:issn>00068993</prism:issn></coredata><references><dc:title>Wrong referenced work</dc:title></references>")
    parsed = elsevier_metadata(xml)
    assert parsed["citation_title"] == response["metadata"]["citation_title"]
    assert parsed["citation_issn"] == ["0006-8993"]


def author_case():
    entry, previous, response = case()
    primary = next(c for c in previous['candidates'] if c['source'] == 'crossref')
    entry['fields'].update(title=primary['record']['title'][0], author='Wrong Person')
    response['metadata']['citation_author'] = [p['family'] + ', ' + p['given'] for p in primary['record']['author']]
    return entry, reassess(entry, previous), response


def test_publisher_author_repair_is_pure_and_requires_complete_byline():
    from cdlbib.publisher_corrections import publisher_field_proposal
    entry, previous, response = author_case()
    before = deepcopy((entry, previous, response))
    proposal = publisher_field_proposal(entry, previous, response, 'author')
    assert proposal and set(proposal['changes']) == {'author'}
    assert (entry, previous, response) == before
    corrected = dict(entry, fields=dict(entry['fields'], author=proposal['changes']['author']['after']))
    assert reassess(corrected, previous)['status'] == 'metadata_verified'


@pytest.mark.parametrize('broken', ['missing', 'omitted', 'reordered', 'different_given', 'other_title', 'other_doi', 'other_year', 'pubmed', 'duplicate'])
def test_publisher_author_repair_preserves_identity_and_source_conflicts(broken):
    from cdlbib.publisher_corrections import publisher_field_proposal
    entry, previous, response = author_case()
    people = response['metadata']['citation_author']
    if broken == 'missing': response['metadata'].pop('citation_author')
    elif broken == 'omitted': people.pop()
    elif broken == 'reordered': people.reverse()
    elif broken == 'different_given': people[0] = people[0].split(',')[0] + ', A Different'
    elif broken == 'other_title': response['metadata']['citation_title'] = ['Different work']
    elif broken == 'other_doi': response['metadata']['citation_doi'] = ['10.1234/other']
    elif broken == 'other_year': response['metadata']['citation_publication_date'] = ['2000']
    elif broken == 'pubmed':
        next(c['raw_record'] for c in previous['candidates'] if c['source'] == 'europepmc')['pageInfo'] = '999-1000'
    else:
        primary = next(c for c in previous['candidates'] if c['source'] == 'crossref')
        primary['record']['author'][1] = deepcopy(primary['record']['author'][0])
        people[1] = people[0]
    assert publisher_field_proposal(entry, previous, response, 'author') is None
