"""PMC's OAI endpoint refuses urllib3's own TLS context (HTTP 403); PoliteClient mounts
Python's default context for that host.  These tests call the live services."""

import pytest
import requests

from cdlbib.pmc_metadata import fetch_front
from cdlbib.verification import Cache, DefaultTLSAdapter, PoliteClient

# A real PMC article (oai:pubmedcentral.nih.gov:3159445)
PMCID = "PMC3159445"


def test_polite_client_fetches_pmc_front_matter(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite3")
    client = PoliteClient(cache, "test@example.org")
    try:
        result = fetch_front(cache, client, PMCID)
    finally:
        cache.close()
    assert result["http_status"] == 200
    assert result["url"].startswith("https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/")
    assert "3159445" in result["body"] and "<OAI-PMH" in result["body"]


def test_pmc_adapter_is_mounted_only_for_pmc():
    client = PoliteClient(None, "test@example.org")
    assert isinstance(client.session.get_adapter("https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"), DefaultTLSAdapter)
    assert not isinstance(client.session.get_adapter("https://api.crossref.org/works"), DefaultTLSAdapter)


def test_default_tls_adapter_still_verifies_certificates():
    session = requests.Session()
    session.mount("https://", DefaultTLSAdapter())
    with pytest.raises(requests.exceptions.SSLError):
        session.get("https://expired.badssl.com/", timeout=20)
    assert session.get("https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/", params={"verb": "Identify"},
                       timeout=(10, 40)).status_code == 200
