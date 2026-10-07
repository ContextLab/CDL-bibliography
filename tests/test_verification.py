import json
from pathlib import Path
import sys

import pytest
from typer.testing import CliRunner

from cdlbib.verification import (
    Cache,
    record_approval,
    PoliteClient,
    ProviderError,
    author_evidence,
    compare_record,
    current_results,
    load_entries,
    normalized,
    normalize_doi,
    run_verification,
    verify_entry,
)
from cdlbib.verification_cli import app


BIB = r"""@article{Test20,
 title={Neural {HMM}: G\"{o}del's result},
 author={A B Smith and C {van der Meer}},
 journal={A Journal}, year={2020}, volume={2}, number={3}, pages={12--19},
 doi={10.1234/example}}
"""


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "a.bib"
    path.write_text(BIB)
    return path, load_entries(path)["Test20"]


@pytest.fixture
def record():
    return {
        "DOI": "10.1234/example",
        "type": "journal-article",
        "title": ["Neural HMM: Gödel's result"],
        "author": [
            {"given": "Alice B", "family": "Smith"},
            {"given": "Charles", "family": "van der Meer"},
        ],
        "container-title": ["A Journal"],
        "published": {"date-parts": [[2020]]},
        "volume": "2",
        "issue": "3",
        "page": "12-19",
    }


def response(record):
    return {
        "body": {"status": "ok", "message": record},
        "url": "https://api.crossref.org/test",
        "retrieved_at": "2026-09-09T00:00:00Z",
        "http_status": 200,
    }


def test_full_metadata_match(entry, record):
    evidence, issues = compare_record(entry[1]["fields"], record)
    assert not issues
    assert all(v["match"] for v in evidence.values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "Neural HMM"),
        ("title", "Neural HMM Gödel's result"),
        ("title", "Neural HMM: Godel's result"),
        ("author", "A B Smith"),
        ("author", "C {van der Meer} and A B Smith"),
        ("author", "A Q Smith and C {van der Meer}"),
        ("year", "2021"),
        ("pages", "1219"),
        ("pages", "12--18"),
        ("volume", "3"),
        ("doi", "10.1234/another"),
        ("ENTRYTYPE", "misc"),
        ("editor", "J Editor"),
        ("force", "True"),
    ],
)
def test_bad_fields_cannot_pass(entry, record, field, value):
    fields = dict(entry[1]["fields"], **{field: value})
    if field == "force":
        record["title"] = ["Wrong paper"]
    assert compare_record(fields, record)[1]


def test_preprint_and_online_years_need_review(entry, record):
    record["type"] = "posted-content"
    assert compare_record(entry[1]["fields"], record)[1]
    record["type"] = "journal-article"
    record["published-online"] = {"date-parts": [[2019]]}
    assert any(
        "conflicting" in x for x in compare_record(entry[1]["fields"], record)[1]
    )


@pytest.mark.parametrize(
    "field", ["author", "title", "published", "page", "volume", "issue"]
)
def test_missing_source_evidence_fails(entry, record, field):
    del record[field]
    assert compare_record(entry[1]["fields"], record)[1]


def test_subtitle_and_braces(entry, record):
    record["title"] = ["Neural HMM"]
    record["subtitle"] = ["Gödel's result"]
    assert not compare_record(entry[1]["fields"], record)[1]
    assert normalized("{DNA}") != normalized("{RNA}")
    assert normalized("Maße") != normalized("Masse")
    with pytest.raises(ValueError):
        normalized(r"Unknown \evil{stuff}")
    with pytest.raises(ValueError):
        normalized("$x^2$")
    with pytest.raises(ValueError):
        normalized(r"alpha \? beta")


def test_authors_not_bag_of_surnames():
    assert author_evidence(
        "Doe, Jr, John", [{"family": "Doe", "given": "John", "suffix": "Jr"}]
    )[0]
    assert not author_evidence("John Doe", [{"family": "Doe", "given": "James"}])[0]
    assert not author_evidence(
        "J Doe and others", [{"family": "Doe", "given": "John"}]
    )[0]
    assert author_evidence(
        "{Research and Development Group}", [{"name": "Research and Development Group"}]
    )[0]


def test_doi_preserves_special_characters():
    assert normalize_doi("https://doi.org/10.1234/AB%28C%29") == "10.1234/ab(c)"
    assert normalize_doi("10.1234/a,b;c:d") == "10.1234/a,b;c:d"


@pytest.mark.parametrize(
    "replacement",
    [
        lambda s: s.replace("title=", "title ="),
        lambda s: s.replace("2020", "2021"),
        lambda s: s.replace("number={3},", "number={3}, note={test},"),
        lambda s: s.replace("\n", "\r\n"),
    ],
)
def test_raw_edit_invalidates_without_network(entry, tmp_path, replacement):
    path, original = entry
    cache = Cache(tmp_path / "cache.sqlite3")
    cache.put(path, original, {"status": "human_verified"})
    assert current_results(path, cache)["Test20"]["status"] == "human_verified"
    path.write_bytes(replacement(BIB).encode())
    assert all(r["status"] == "pending" for r in current_results(path, cache).values())
    cache.close()


def test_inherited_and_string_edits_invalidate(tmp_path):
    path = tmp_path / "test.bib"
    text = '@string{jn="Journal"}\n@book{Parent,title={Parent},year={2020}}\n@inbook{Child,title={Child},journal=jn,crossref={Parent}}'
    path.write_text(text)
    initial = load_entries(path)
    path.write_text(text.replace("year={2020}", "year={2021}"))
    assert load_entries(path)["Child"]["fingerprint"] != initial["Child"]["fingerprint"]
    path.write_text(text.replace('jn="Journal"', 'jn="Journal 2"'))
    assert load_entries(path)["Child"]["fingerprint"] != initial["Child"]["fingerprint"]


@pytest.mark.parametrize(
    "text",
    [
        BIB + BIB,
        BIB.replace("title=", "year={2019},title="),
        BIB[:-3],
        "garbage\n" + BIB,
        BIB + "\n@article{broken, title={x}",
        "@book{a,crossref={b}}\n@book{b,crossref={a}}",
        "@book{a,crossref={missing}}",
    ],
)
def test_parser_fails_closed(tmp_path, text):
    path = tmp_path / "bad.bib"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_entries(path)


class Clock:
    def __init__(self):
        self.t = 0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, amount):
        self.sleeps.append(amount)
        self.t += amount


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code, self.body = status, body
        self.headers = headers or {}
        self.url = "https://api.crossref.org/test"

    def json(self):
        return self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def test_throttles_requests_caches_and_honors_retry_after(tmp_path, record):
    good = FakeResponse(
        200,
        response(record)["body"],
        {"x-rate-limit-limit": "1", "x-rate-limit-interval": "3s"},
    )
    session = Session([FakeResponse(429, {}, {"Retry-After": "8"}), good, good])
    clock = Clock()
    cache = Cache(tmp_path / "cache.sqlite3")
    client = PoliteClient(
        cache,
        "valid@example.org",
        session=session,
        sleep=clock.sleep,
        clock=clock.clock,
    )
    assert client.crossref_doi("10.1234/abc")["body"]
    assert client.crossref_doi("10.1234/abc")["body"]
    client.crossref_doi("10.1234/def")
    assert len(session.calls) == 3
    assert clock.sleeps[1] >= 8
    assert clock.sleeps[-1] >= 3.3
    assert session.calls[0][1]["params"]["mailto"] == "valid@example.org"
    assert session.calls[0][1]["allow_redirects"] is False
    cache.close()


def test_failure_is_not_negative_cached(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite3")
    session = Session([FakeResponse(503, {}, {"Retry-After": "900"})])
    client = PoliteClient(cache, "valid@example.org", session=session)
    with pytest.raises(ProviderError):
        client.crossref_doi("10.1234/abc")
    assert cache.db.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 0


def test_duplicate_doi_candidates_and_wrong_doi(entry, record):
    class Client:
        def crossref_search(self, fields):
            other = dict(record, DOI="10.1234/other")
            return response({"items": [record, other]})

        def crossref_doi(self, doi):
            return response(dict(record, DOI="10.1234/wrong"))

    assert verify_entry(entry[1], Client())["status"] == "needs_review"
    del entry[1]["fields"]["doi"]
    assert verify_entry(entry[1], Client())["status"] == "needs_review"


def test_checkpoint_resume_and_edit_during_run(entry, record, tmp_path):
    path, e = entry
    cache = Cache(tmp_path / "cache.sqlite3")

    class Client:
        requests = 1

        def crossref_doi(self, doi):
            return response(record)

    report = tmp_path / "report.jsonl"
    run_verification(path, cache, Client(), report)
    assert json.loads(report.read_text())["status"] == "metadata_verified"

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError("Unchanged entries must not hit the network")

    run_verification(path, cache, NoNetwork(), report)

    class EditingClient(Client):
        def crossref_doi(self, doi):
            path.write_text(BIB.replace("2020", "2021"))
            return response(record)

    run_verification(path, cache, EditingClient(), report, refresh=True)
    assert json.loads(report.read_text())["status"] == "pending"


def test_stale_human_approval_and_offline_exit(entry, tmp_path):
    path, e = entry
    database = str(tmp_path / "cache.sqlite3")
    runner = CliRunner()
    cache = Cache(database)
    try:
        with pytest.raises(ValueError, match="Entry changed since review; approval rejected"):
            record_approval(
                cache,
                str(path),
                "Test20",
                "stale",
                {"reviewer": "Human", "source": "Book", "note": "Checked all fields"},
            )
    finally:
        cache.close()
    assert (
        runner.invoke(app, ["status", str(path), "--database", database]).exit_code == 1
    )


def test_batch_limits_and_encoding(tmp_path, record):
    session = Session([FakeResponse(200, response({"items": [record]})["body"])])
    client = PoliteClient(
        Cache(tmp_path / "c.sqlite3"), "valid@example.org", session=session
    )
    client.crossref_batch(["10.1234/a", "10.1234/b", "10.1234/a"])
    assert session.calls[0][1]["params"]["filter"] == "doi:10.1234/a,doi:10.1234/b"
    with pytest.raises(ValueError):
        client.crossref_batch(["10.1234/a,b"])


@pytest.mark.parametrize("interval", [float("nan"), float("inf"), -1, 0])
def test_invalid_intervals_cannot_disable_throttling(tmp_path, interval):
    with pytest.raises(ValueError):
        PoliteClient(
            Cache(tmp_path / "cache.sqlite3"), "valid@example.org", interval=interval
        )


def test_search_is_bounded_but_comparison_keeps_all_authors(tmp_path, record):
    session = Session([FakeResponse(200, response({"items": [record]})["body"])])
    client = PoliteClient(
        Cache(tmp_path / "c.sqlite3"), "valid@example.org", session=session
    )
    fields = {
        "title": "Title: subtitle",
        "author": "A Smith and B Jones and C Person",
        "year": "2020",
    }
    client.crossref_search(fields)
    query = session.calls[0][1]["params"]["query.bibliographic"]
    assert "A Smith" in query and "B Jones" not in query
    assert "B Jones" in fields["author"]


def test_cached_evidence_can_be_reassessed_without_network(entry, record, tmp_path):
    path, e = entry
    record["title"] = ["Wrong title"]
    cache = Cache(tmp_path / "cache.sqlite3")
    cache.put(
        path,
        e,
        {
            "status": "metadata_verified",
            "candidates": [
                {
                    "source": "crossref",
                    "record": record,
                    "issues": [],
                    "evidence": {"title": {"match": True}},
                }
            ],
        },
    )

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError("Reassessment must use saved evidence")

    result = run_verification(
        path, cache, NoNetwork(), tmp_path / "report.jsonl", recheck_cached=True
    )
    assert result["Test20"]["status"] == "needs_review"


def test_recheck_that_reproduces_an_approval_writes_nothing(entry, record, tmp_path):
    from cdlbib.auto_review import reassess

    path, e = entry
    cache = Cache(tmp_path / "cache.sqlite3")
    stored = reassess(e, {"status": "metadata_verified", "candidates": [
        {"source": "crossref", "doi": record["DOI"], "record": record}]})
    assert stored["status"] == "metadata_verified"
    cache.put(path, e, stored)
    count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError("Reassessment must use saved evidence")

    for _ in range(2):
        result = run_verification(
            path, cache, NoNetwork(), tmp_path / "report.jsonl", recheck_cached=True
        )
        assert result["Test20"]["status"] == "metadata_verified"
        assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == count


def test_empty_rendered_metadata_is_not_evidence(entry, record):
    entry[1]["fields"]["title"] = "{ }"
    record["title"] = [" "]
    assert compare_record(entry[1]["fields"], record)[1]
    assert not author_evidence("{ }", [{"name": " "}])[0]


def test_null_year_is_not_publication_evidence(entry, record):
    entry[1]["fields"]["year"] = "None"
    record["published"] = {"date-parts": [[None]]}
    assert compare_record(entry[1]["fields"], record)[1]


def test_subtitle_suffix_is_not_a_complete_subtitle(entry, record):
    entry[1]["fields"]["title"] = "Foobar"
    record["title"] = ["Foobar"]
    record["subtitle"] = ["bar"]
    assert compare_record(entry[1]["fields"], record)[1]
    entry[1]["fields"]["title"] = "Foobar: bar"
    assert not compare_record(entry[1]["fields"], record)[1]


def test_no_invented_title_subtitle_combinations(entry, record):
    record["title"] = ["English title", "French title"]
    record["subtitle"] = ["English subtitle", "French subtitle"]
    with pytest.raises(ValueError, match="Ambiguous"):
        compare_record(entry[1]["fields"], record)


def test_real_404_is_cached_without_becoming_approval(tmp_path, entry):
    session = Session(
        [
            FakeResponse(404, None),
            FakeResponse(404, None),
            FakeResponse(200, response({"items": []})["body"]),
        ]
    )
    clock = Clock()
    client = PoliteClient(
        Cache(tmp_path / "c.sqlite3"),
        "valid@example.org",
        session=session,
        sleep=clock.sleep,
        clock=clock.clock,
    )
    assert verify_entry(entry[1], client)["status"] == "needs_review"
    assert verify_entry(entry[1], client)["status"] == "needs_review"
    assert len(session.calls) == 3


def test_malformed_fallback_response_not_cached(tmp_path):
    session = Session([FakeResponse(200, {"data": {"attributes": {}}})])
    cache = Cache(tmp_path / "c.sqlite3")
    client = PoliteClient(cache, "valid@example.org", session=session)
    with pytest.raises(ProviderError):
        client.get("https://api.datacite.org/dois/10.1234/unknown")
    assert cache.db.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 0
