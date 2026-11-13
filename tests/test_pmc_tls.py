"""PMC's OAI endpoint refuses urllib3's own TLS context (HTTP 403); PoliteClient mounts
Python's default context for that host.  These tests call the live services."""

import time

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


def _get_expecting_ssl_error(session, url, attempts=6, wait=2.0):
    """Return the SSLError that a request to ``url`` raises.

    expired.badssl.com resets a large share of connections before it presents its
    certificate (about half of them in November 2026). A reset says nothing about
    whether the certificate would have been checked, so only resets and timeouts are
    retried; an SSLError ends the loop, and a response that arrives at all fails the test.
    """
    dropped = []
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=20)
        except requests.exceptions.SSLError as error:  # before ConnectionError: it is a subclass
            return error
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as error:
            dropped.append(f"{type(error).__name__}: {error}")
            time.sleep(wait * (attempt + 1))
            continue
        pytest.fail(f"{url} answered HTTP {response.status_code}: its certificate was not rejected")
    pytest.fail(f"{url} dropped all {attempts} connections before its certificate was checked:\n"
                + "\n".join(dropped))


def test_default_tls_adapter_still_verifies_certificates():
    session = requests.Session()
    session.mount("https://", DefaultTLSAdapter())
    error = _get_expecting_ssl_error(session, "https://expired.badssl.com/")
    assert "certificate" in str(error).lower()
    assert session.get("https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/", params={"verb": "Identify"},
                       timeout=(10, 40)).status_code == 200
