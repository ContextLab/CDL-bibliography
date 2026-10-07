"""Documentary print-year corroboration and source-identity adversarial cases."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
from cdlbib.publisher_year_review import assess_publisher_year, run_publisher_year_review
from cdlbib.publisher_metadata import PublisherMetadata
from cdlbib.verification import Cache, load_entries, export_snapshot, import_snapshot
from cdlbib.auto_review import reassess
from test_resolution_rules import pilot


def source(key):
    rows = json.loads(
        (ROOT / "tests/fixtures/resolution-2026-09-15-source-results.json").read_text()
    )
    row = deepcopy(next(r for r in rows if r["key"] == key))
    row["document_sha256"] = row["sha256"]
    return row


@pytest.mark.parametrize("key,year", [("MillMcGi52", "1952"), ("TakaEtal77", "1977")])
def test_live_publisher_metadata_distinguishes_archive_date(key, year):
    fields, primary = pilot(key)
    result = assess_publisher_year(fields, primary, source(key))
    assert result["issues"] == []
    assert result["evidence"]["year"]["source"] == [year]
    assert result["raw_metadata"]["citation_online_date"] == ["2025/01/01"]
    assert "citation_abstract" not in result["raw_metadata"]
    previous = {"status": "needs_review", "candidates": [primary, result]}
    assert reassess({"fields": fields}, previous)["status"] == "metadata_verified"
    # Recompute from source values, not saved match flags.
    result["raw_metadata"]["citation_firstpage"] = ["999"]
    assert reassess({"fields": fields}, previous)["status"] == "needs_review"


@pytest.mark.parametrize(
    "field,value",
    [
        ("citation_doi", ["10.1234/wrong"]),
        ("citation_doi", []),
        ("citation_title", ["A different article"]),
        ("citation_author", ["Alice Q. Smith"]),
        ("citation_publication_date", ["2025/01/01"]),
        ("citation_publication_date", ["1952/12", "2025/01/01"]),
        ("citation_publication_date", ["1952/99"]),
        ("citation_issn", ["0000-0000"]),
        ("citation_volume", ["99"]),
        ("citation_firstpage", ["368"]),
        ("citation_lastpage", ["397"]),
        ("citation_issue", ["4", "5"]),
        ("citation_journal_title", ["Different Journal"]),
        ("citation_doi", "10.1007/bf02288914"),
    ],
)
def test_bad_or_ambiguous_publisher_fields_cannot_approve(field, value):
    fields, primary = pilot("MillMcGi52")
    response = source("MillMcGi52")
    response["metadata"][field] = value
    assert assess_publisher_year(fields, primary, response)["issues"]


def test_publisher_source_and_registry_guards():
    fields, primary = pilot("MillMcGi52")
    for url in [
        "https://example.com/core/journals/x",
        "https://www.cambridge.org/blog/x",
        "http://www.cambridge.org/core/journals/x",
    ]:
        response = dict(source("MillMcGi52"), url=url)
        assert assess_publisher_year(fields, primary, response)["issues"]
    bad = deepcopy(primary)
    bad["issues"].append("Source flags an update/correction/retraction relationship")
    assert assess_publisher_year(fields, bad, source("MillMcGi52"))["issues"]
    bad = deepcopy(primary)
    bad["record"]["published-print"] = {"date-parts": [[1951]]}
    assert assess_publisher_year(fields, bad, source("MillMcGi52"))["issues"]


def test_repeated_author_names_are_not_deduplicated():
    parser = PublisherMetadata()
    parser.feed(
        '<head><meta name="citation_author" content="A Smith"><meta name="citation_author" content="A Smith"></head>'
    )
    assert parser.source_metadata()["citation_author"] == ["A Smith", "A Smith"]


def test_local_run_repeat_and_snapshot_preserve_provenance(tmp_path, monkeypatch):
    fields, primary = pilot("MillMcGi52")
    rows = json.loads((ROOT / "tests/fixtures/pilot50-manifest.json").read_text())[
        "entries"
    ]
    row = next(r for r in rows if r["key"] == "MillMcGi52")
    bib = tmp_path / "a.bib"
    bib.write_text(
        "@article{MillMcGi52,"
        + ",".join(
            k + "={" + v + "}"
            for k, v in row["entry"].items()
            if k not in {"ENTRYTYPE", "ID"}
        )
        + "}"
    )
    cache = Cache(tmp_path / "a.sqlite3")
    entry = load_entries(bib)["MillMcGi52"]
    cache.put(
        bib,
        entry,
        {
            "status": "needs_review",
            "candidates": [primary],
            "attempts": [],
            "discovery_review": {"policy": "1"},
        },
    )
    calls = []

    def fetch(cache, client, doi):
        calls.append(doi)
        return source("MillMcGi52")

    monkeypatch.setattr("cdlbib.publisher_year_review.fetch_head", fetch)

    class Client:
        requests = 0

    report = tmp_path / "r.jsonl"
    first = run_publisher_year_review(bib, cache, Client(), report)
    second = run_publisher_year_review(bib, cache, Client(), report)
    assert first == second and len(calls) == 1
    assert first["MillMcGi52"]["accepted_source"] == "publisher-head"
    assert first["MillMcGi52"]["discovery_review"] == {"policy": "1"}
    snapshot = tmp_path / "s.jsonl.gz"
    export_snapshot(bib, cache, snapshot)
    clone = Cache(tmp_path / "b.sqlite3")
    assert import_snapshot(bib, clone, snapshot) == 1
    assert clone.get(bib, entry)["status"] == "metadata_verified"
    cache.close()
    clone.close()


def test_deferred_publisher_requests_are_counted_and_cached(tmp_path, monkeypatch):
    from cdlbib.publisher_year_review import fetch_head
    from cdlbib.verification_cli import DeferredClient

    class Session:
        headers = {}

        def get(self, *args, **kwargs):
            return None

    monkeypatch.setattr("cdlbib.verification.requests.Session", Session)

    def get_source(session, url, hosts):
        session.get(url)
        session.get("https://www.cambridge.org/core/journals/x")
        return (
            '<head><meta name="citation_doi" content="10.1234/a"><meta name="citation_abstract" content="Excluded"></head>',
            "https://www.cambridge.org/core/journals/x",
        )

    monkeypatch.setattr("cdlbib.publisher_year_review.get_source", get_source)
    cache = Cache(tmp_path / "v.sqlite3")
    client = DeferredClient(cache, "test@example.org", 0.5, False)
    first = fetch_head(cache, client, "10.1234/a")
    assert client.requests == 2
    assert "citation_abstract" not in first["metadata"]
    offline = DeferredClient(cache, None, 0.5, False)
    assert fetch_head(cache, offline, "10.1234/a") == first
    assert offline.client is None and offline.requests == 0
    cache.close()


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_publisher_failures_remain_retryable(tmp_path, monkeypatch, status):
    from cdlbib.publisher_year_review import fetch_head
    from cdlbib.search_tools import SourceHTTPError
    from cdlbib.verification import ProviderError
    from cdlbib.verification_cli import DeferredClient

    def fail(*args):
        raise SourceHTTPError(status, "60")

    monkeypatch.setattr("cdlbib.publisher_year_review.get_source", fail)
    cache = Cache(tmp_path / "v.sqlite3")
    client = DeferredClient(cache, None, 1, False)
    with pytest.raises(ProviderError):
        fetch_head(cache, client, "10.1234/a")
    assert cache.db.execute("SELECT count(*) FROM responses").fetchone()[0] == 0
    cache.close()
