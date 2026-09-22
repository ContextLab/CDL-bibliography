"""OAI envelope identity and publication-version boundaries."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from pmc_metadata import article_front, fetch_front, JATS, OAI
from verification import Cache, PoliteClient, ProviderError
from test_fulltext_review import XML, assessment
import test_auto_review

sample = test_auto_review.sample


def envelope(article=XML):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(article)
    for node in root.iter():
        node.tag = JATS + node.tag
    meta = root.find(JATS + "front/" + JATS + "article-meta")
    for kind, value in (("pmcid", "PMC123"), ("pmid", "456")):
        ET.SubElement(meta, JATS + "article-id", {"pub-id-type": kind}).text = value
    text = ET.tostring(root, encoding="unicode")
    return ('<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
            '<request verb="GetRecord" metadataPrefix="pmc_fm" identifier="oai:pubmedcentral.nih.gov:123">'
            'https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/</request><GetRecord><record><header>'
            '<identifier>oai:pubmedcentral.nih.gov:123</identifier></header><metadata>'
            + text + '</metadata></record></GetRecord></OAI-PMH>')


def unwrap(xml):
    return article_front(xml, "PMC123", "10.1234/a", "456")


def test_oai_metadata_uses_existing_field_checks(sample):
    front = unwrap(envelope())
    assert "Wrong paper" not in front
    assert not assessment(sample, front)["issues"]
    assert assessment(sample, front.replace("Alice B", "Alice Q"))["issues"]


@pytest.mark.parametrize("old,new", [
    ('verb="GetRecord"', 'verb="ListRecords"'),
    ('metadataPrefix="pmc_fm"', 'metadataPrefix="pmc"'),
    ('identifier="oai:pubmedcentral.nih.gov:123"', 'identifier="oai:pubmedcentral.nih.gov:124"'),
    ('<header>', '<header status="deleted">'),
    ('<identifier>oai:pubmedcentral.nih.gov:123', '<identifier>oai:pubmedcentral.nih.gov:124'),
    ('>PMC123<', '>PMC124<'), ('>456<', '>457<'), ('>10.1234/a<', '>10.1234/b<'),
    ('</header>', '<identifier>oai:pubmedcentral.nih.gov:123</identifier></header>'),
    ('https://jats.nlm.nih.gov/ns/archiving/1.4/', 'https://example.test/unrecognized/'),
    ('<GetRecord>', '<error code="idDoesNotExist"/><GetRecord>'),
])
def test_wrong_or_ambiguous_identity_is_rejected(old, new):
    with pytest.raises(ValueError):
        unwrap(envelope().replace(old, new))


@pytest.mark.parametrize("markup", [
    '<article-id pub-id-type="manuscript-id">NIHMS1</article-id>',
    '<article-id pub-id-type="manuscript-id-alternative">NIHPA1</article-id>',
    '<article-version article-version-type="pmc-version">2</article-version>',
    '<related-article related-article-type="corrected-article"/>',
])
def test_wrapper_preserves_version_holds(sample, markup):
    xml = envelope(XML.replace("<article-meta>", "<article-meta>" + markup))
    assert assessment(sample, unwrap(xml))["issues"]


def test_wrapper_preserves_semantic_title_markup(sample):
    xml = envelope(XML.replace("its meaning", "its <sub>meaning</sub>"))
    assert assessment(sample, unwrap(xml))["issues"]


def test_xml_entity_declarations_are_not_accepted():
    with pytest.raises(ValueError):
        unwrap('<!DOCTYPE OAI-PMH [<!ENTITY x "value">]>' + envelope())


class Response:
    def __init__(self, status=200, body=None):
        self.status_code, self.headers = status, {}
        self.body = (envelope() if body is None else body).encode()
        self.url = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?identifier=oai:pubmedcentral.nih.gov:123"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.body


class Session:
    def __init__(self, response):
        self.headers, self.response = {}, response

    def get(self, *args, **kwargs):
        assert not kwargs["allow_redirects"] and kwargs["stream"]
        return self.response


def test_fetch_reuses_success_and_negative_response_cache(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite3")
    session = Session(Response())
    client = PoliteClient(cache, "test@example.org", session=session, sleep=lambda _: None)
    first = fetch_front(cache, client, "PMC123")
    assert fetch_front(cache, client, "PMC123") == first
    assert client.requests == 1
    assert client.interval == 1.0
    session.response = Response(404, "missing")
    assert fetch_front(cache, client, "PMC456")["body"] is None
    assert fetch_front(cache, client, "PMC456")["body"] is None
    assert client.requests == 2
    cache.close()


@pytest.mark.parametrize("response", [Response(429), Response(503), Response(302), Response(200, "<html>challenge</html>"), Response(200, "broken XML"), Response(200, "")])
def test_fetch_stops_without_retry_or_caching_provider_failure(tmp_path, response):
    cache = Cache(tmp_path / "cache.sqlite3")
    client = PoliteClient(cache, "test@example.org", session=Session(response), sleep=lambda _: None)
    with pytest.raises(ProviderError):
        fetch_front(cache, client, "PMC123")
    assert client.requests == 1 and client.interval == 1.0
    assert cache.response("pmc-front-v1:PMC123", 86400) is None
    cache.close()
