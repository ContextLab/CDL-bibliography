"""Only a permanent Crossref work-to-work redirect establishes a DOI alias."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from verification import Cache, PoliteClient, ProviderError, assess_candidates, compare_record, valid_doi_alias
from auto_review import reassess, select_result
from test_verification import Clock, FakeResponse, Session, entry, record, response

ALIAS = "10.1234/alias"
PRIME = "10.1234/example"


def client_for(tmp_path, responses):
    clock = Clock()
    cache = Cache(tmp_path / "v.sqlite3")
    session = Session(responses)
    client = PoliteClient(cache, "valid@example.org", session=session, sleep=clock.sleep, clock=clock.clock)
    return cache, session, client


@pytest.mark.parametrize("status", [301, 308])
def test_authoritative_alias_is_cached_and_survives_reassessment(tmp_path, entry, record, status):
    cache, session, client = client_for(tmp_path, [
        FakeResponse(status, {}, {"Location": "/works/10.1234/example"}),
        FakeResponse(200, response(record)["body"]),
    ])
    try:
        result = client.crossref_doi(ALIAS)
        assert valid_doi_alias(result["doi_alias"], ALIAS, PRIME)
        assert client.crossref_doi(ALIAS) == result
        assert len(session.calls) == client.requests == 2
        assert all(not kwargs["allow_redirects"] for _, kwargs in session.calls)
        fields = dict(entry[1]["fields"], doi=ALIAS)
        candidates = assess_candidates(fields, result)
        assert not candidates[0]["issues"]
        assert candidates[0]["record"]["DOI"] == PRIME
        previous = {"status": "needs_review", "candidates": candidates}
        reviewed = reassess({"fields": fields}, previous)
        assert reviewed["status"] == "metadata_verified"
        assert reviewed["accepted_doi"] == PRIME
        assert compare_record(dict(fields, year="1990"), record, result["doi_alias"])[1]
    finally:
        cache.close()


@pytest.mark.parametrize("location", [
    "https://evil.example/works/10.1234/example", "http://api.crossref.org/works/10.1234/example",
    "https://api.crossref.org.evil.example/works/10.1234/example", "/members/123",
    "/works/10.1234/alias", "https://user@api.crossref.org/works/10.1234/example",
    "/works/10.1234/example?unexpected=1", "/works/10.1234/example#fragment",
])
def test_redirect_escape_is_rejected_before_following(tmp_path, location):
    cache, session, client = client_for(tmp_path, [FakeResponse(301, {}, {"Location": location})])
    try:
        with pytest.raises(ProviderError): client.crossref_doi(ALIAS)
        assert len(session.calls) == 1
        assert cache.db.execute("SELECT count(*) FROM responses").fetchone()[0] == 0
    finally:
        cache.close()


@pytest.mark.parametrize("wrong", ["chain", "wrong_doi", "missing"])
def test_alias_destination_must_be_the_single_named_record(tmp_path, record, wrong):
    if wrong == "chain": second = FakeResponse(301, {}, {"Location": "/works/10.1234/third"})
    elif wrong == "missing": second = FakeResponse(404, {})
    else:
        record["DOI"] = "10.1234/other"
        second = FakeResponse(200, response(record)["body"])
    cache, session, client = client_for(tmp_path, [FakeResponse(301, {}, {"Location": "/works/10.1234/example"}), second])
    try:
        with pytest.raises(ProviderError): client.crossref_doi(ALIAS)
        assert len(session.calls) == 2
    finally:
        cache.close()


def alias_candidate(fields, record):
    receipt = {"requested_doi": ALIAS, "prime_doi": PRIME, "http_status": 301,
               "from_url": "https://api.crossref.org/works/" + ALIAS,
               "to_url": "https://api.crossref.org/works/" + PRIME}
    return assess_candidates(fields, dict(response(record), doi_alias=receipt))[0]


def test_old_alias_metadata_cannot_override_current_prime_metadata(entry, record):
    fields = dict(entry[1]["fields"], doi=ALIAS)
    old = deepcopy(record)
    old["DOI"] = ALIAS
    obsolete = assess_candidates(fields, response(old))[0]
    primary = alias_candidate(fields, record)
    assert select_result(fields, [obsolete, primary], [])["status"] == "metadata_verified"
    changed = dict(record, title=["A different title"])
    primary = alias_candidate(fields, changed)
    assert select_result(fields, [obsolete, primary], [])["status"] == "needs_review"


def test_alias_does_not_hide_an_erratum_or_multiple_pubmed_identities(entry, record):
    fields = dict(entry[1]["fields"], doi=ALIAS)
    primary = alias_candidate(fields, record)
    source = {"source": "europepmc", "doi": ALIAS, "issues": ["Notice"],
              "raw_record": {"source": "MED", "id": "123", "doi": ALIAS, "isRetracted": "Y"}}
    assert select_result(fields, [primary, source], [])["status"] == "needs_review"
    del source["raw_record"]["isRetracted"]
    other = deepcopy(source)
    other["doi"] = other["raw_record"]["doi"] = PRIME
    other["raw_record"]["id"] = "456"
    assert select_result(fields, [primary, source, other], [])["status"] == "needs_review"


def test_alias_lookup_requires_receipt_and_retains_negative_checkpoint(entry, record):
    from auto_review import alias_targets, apply_alias_lookup
    doubled = "10.1234//example"
    old = dict(record, DOI=doubled)
    local = deepcopy(entry[1])
    local["fields"].pop("doi")
    fields = local["fields"]
    previous = {"status": "needs_review", "candidates": assess_candidates(fields, response(old)) + assess_candidates(fields, response(record)),
                "auto_review": {"epmc_checked": True, "epmc_checked_dois": [doubled, PRIME]}}
    assert alias_targets(previous) == [doubled]
    checked = apply_alias_lookup(local, previous, doubled, response(old))
    assert checked["status"] == "needs_review"
    assert alias_targets(checked) == []
    assert checked["auto_review"]["epmc_checked_dois"] == [doubled, PRIME]
    assert not checked["attempts"][-1]["confirmed"]


def test_live_alias_workflow_repeats_without_requests_or_writes(tmp_path, entry, record):
    from auto_review import run_auto_review
    doubled = "10.1234//example"
    cache, session, client = client_for(tmp_path, [
        FakeResponse(301, {}, {"Location": "/works/10.1234/example"}),
        FakeResponse(200, response(record)["body"]),
    ])
    path, local = entry
    from verification import load_entries
    path.write_text(path.read_text().replace(",\n doi={10.1234/example}", ""))
    local = load_entries(path)["Test20"]
    fields = local["fields"]
    old = dict(record, DOI=doubled)
    previous = {"status": "needs_review", "candidates": assess_candidates(fields, response(old)) + assess_candidates(fields, response(record)), "attempts": []}
    try:
        cache.put(path, local, previous)
        first = run_auto_review(path, cache, tmp_path / "report.jsonl", client)
        assert first[local["key"]]["status"] == "metadata_verified"
        count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
        second = run_auto_review(path, cache, tmp_path / "report.jsonl", client)
        assert second == first and client.requests == 2
        assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == count
    finally:
        cache.close()


def test_alias_and_secondary_lookup_share_the_entry_limit(tmp_path, entry, record):
    from auto_review import run_auto_review
    from verification import load_entries
    path, _ = entry
    raw = path.read_text().replace(",\n doi={10.1234/example}", "")
    second = raw.replace("Test20", "Test21").replace("year={2020}", "year={2019}")
    path.write_text(raw + second)
    entries = load_entries(path)
    doubled = "10.1234//example"
    cache, session, client = client_for(tmp_path, [
        FakeResponse(301, {}, {"Location": "/works/10.1234/example"}),
        FakeResponse(200, response(record)["body"]),
    ])
    try:
        for key, local in entries.items():
            candidates = assess_candidates(local["fields"], response(record))
            if key == "Test20":
                candidates += assess_candidates(local["fields"], response(dict(record, DOI=doubled)))
            cache.put(path, local, {"status": "needs_review", "candidates": candidates, "attempts": []})
        result = run_auto_review(path, cache, tmp_path / "report.jsonl", client, limit=1)
        assert result["Test20"]["status"] == "metadata_verified"
        assert result["Test21"]["status"] == "needs_review"
        assert client.requests == 2
        assert not result["Test21"].get("auto_review", {}).get("epmc_checked")
    finally:
        cache.close()
