"""Incomplete HTTP-200 responses must neither grant approval nor cache absence."""
import pytest

from test_verification import Cache, Clock, FakeResponse, PoliteClient, ProviderError, Session

URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PARAMS = {"query": 'DOI:"10.1234/a"', "format": "json", "pageSize": 100}


def client_for(tmp_path, bodies):
    responses = [FakeResponse(200, body) for body in bodies]
    for response in responses:
        response.url = URL
    clock = Clock()
    cache = Cache(tmp_path / "cache.sqlite3")
    session = Session(responses)
    client = PoliteClient(cache, "valid@example.org", session=session,
                          sleep=clock.sleep, clock=clock.clock)
    return client, cache, session, clock


def test_partial_then_complete_response_retries_exact_query_and_caches_only_complete(tmp_path):
    partial = {"hitCount": 2, "resultList": {"result": [{"id": "1", "source": "MED"}]}}
    complete = {"hitCount": 2, "resultList": {"result": [
        {"id": "1", "source": "MED"}, {"id": "2", "source": "MED"}]}}
    client, cache, session, clock = client_for(tmp_path, [partial, complete])
    try:
        result = client.get(URL, PARAMS)
        assert len(result["body"]["resultList"]["result"]) == 2
        assert session.calls[0] == session.calls[1]
        assert clock.sleeps[1] >= 2
        assert client.get(URL, PARAMS) == result
        assert client.requests == 2
        assert cache.db.execute("SELECT count(*) FROM responses").fetchone()[0] == 1
    finally:
        cache.close()


@pytest.mark.parametrize("body", [
    {"hitCount": 200, "resultList": {"result": []}},
    {"hitCount": 0, "resultList": None},
    {"hitCount": "0", "resultList": {"result": []}},
    None,
    [],
])
def test_repeated_incomplete_response_fails_closed_without_negative_cache(tmp_path, body):
    client, cache, session, clock = client_for(tmp_path, [body] * 4)
    try:
        with pytest.raises(ProviderError, match="after 4 attempts"):
            client.get(URL, PARAMS)
        assert client.requests == len(session.calls) == 4
        assert clock.sleeps[1:] == [2, 4, 8]
        assert cache.db.execute("SELECT count(*) FROM responses").fetchone()[0] == 0
    finally:
        cache.close()


def test_complete_empty_response_is_cached_without_retry(tmp_path):
    body = {"hitCount": 0, "resultList": {"result": []}}
    client, cache, _, _ = client_for(tmp_path, [body])
    try:
        assert client.get(URL, PARAMS)["body"] == body
        assert client.get(URL, PARAMS)["body"] == body
        assert client.requests == 1
    finally:
        cache.close()
