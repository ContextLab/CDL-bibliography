from pathlib import Path
import sys

from cdlbib.discovery_review import run_discovery_review
from cdlbib.verification import Cache, load_entries


def test_expanded_discovery_uses_strict_checks_and_checkpoints(tmp_path):
    bib = tmp_path / "a.bib"
    bib.write_text(
        "@article{A,title={Exact title},author={A Smith},year={2020},journal={Journal},volume={2},pages={1--9}}"
    )
    cache = Cache(tmp_path / "v.sqlite3")
    entry = load_entries(bib)["A"]
    cache.put(bib, entry, {"status": "needs_review", "candidates": []})

    class Client:
        calls = 0

        def get(self, url, params):
            self.calls += 1
            assert params == {"query.title": "exact title", "rows": 20}
            return {
                "url": url,
                "retrieved_at": "2026-09-10",
                "body": {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1234/exact",
                                "type": "journal-article",
                                "title": ["Exact title"],
                                "author": [{"given": "Alice", "family": "Smith"}],
                                "published": {"date-parts": [[2020]]},
                                "container-title": ["Journal"],
                                "volume": "2",
                                "page": "1-9",
                            }
                        ]
                    }
                },
            }

    client = Client()
    report = tmp_path / "report.jsonl"
    assert (
        run_discovery_review(bib, cache, client, report)["A"]["status"]
        == "metadata_verified"
    )
    assert (
        run_discovery_review(bib, cache, client, report)["A"]["status"]
        == "metadata_verified"
    )
    assert client.calls == 1
    # An actual edit invalidates the old fingerprint and its discovery marker.
    bib.write_text(bib.read_text().replace("2020", "2021"))
    entry = load_entries(bib)["A"]
    assert cache.get(bib, entry) is None
    cache.put(bib, entry, {"status": "needs_review", "candidates": []})
    assert (
        run_discovery_review(bib, cache, client, report)["A"]["status"]
        == "needs_review"
    )
    assert client.calls == 2
    cache.close()


def test_frozen_benchmark_recomputes_records():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "verification/benchmark/run.py"
    spec = importlib.util.spec_from_file_location("verification_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run()
    assert report["works"] == 30 and report["cases"] == 60
    assert report["false_acceptances"] == 0 and report["missed_matches"] == 0


def test_discovered_doi_gets_secondary_lookup_without_repeating_old_doi(tmp_path):
    from cdlbib.auto_review import run_auto_review
    from cdlbib.verification import assess_candidates, POLICY

    bib = tmp_path / "a.bib"
    bib.write_text(
        "@article{A,title={Exact title},author={A Smith},year={2020},journal={Journal},volume={2},pages={1--9},publisher={Unknown}}"
    )
    cache = Cache(tmp_path / "v.sqlite3")
    entry = load_entries(bib)["A"]
    record = {
        "DOI": "10.1234/old",
        "type": "journal-article",
        "title": ["Exact title"],
        "author": [{"given": "Alice", "family": "Smith"}],
        "published": {"date-parts": [[2020]]},
        "container-title": ["Journal"],
        "volume": "2",
        "page": "1-9",
    }

    def response(items):
        return {
            "url": "https://api.crossref.org/works",
            "retrieved_at": "2026-09-15",
            "body": {"message": {"items": items}},
        }

    cache.put(
        bib,
        entry,
        {
            "status": "needs_review",
            "candidates": assess_candidates(entry["fields"], response([record])),
            "attempts": [],
            "auto_review": {
                "policy": POLICY,
                "epmc_checked": True,
                "fulltext_checked": True,
            },
        },
    )

    class Client:
        requests = 0
        queries = []

        def get(self, url, params):
            self.requests += 1
            if "query.title" in params:
                return response([dict(record, DOI="10.1234/new")])
            self.queries.append(params["query"])
            return {
                "url": url,
                "retrieved_at": "2026-09-15",
                "http_status": 200,
                "body": {"hitCount": 0, "resultList": {"result": []}},
            }

    client = Client()
    report = tmp_path / "report.jsonl"
    result = run_discovery_review(bib, cache, client, report)["A"]
    assert result["auto_review"]["epmc_checked_dois"] == ["10.1234/old"]
    assert not result["auto_review"].get("fulltext_checked")
    run_auto_review(bib, cache, report, client)
    assert client.queries == ['DOI:"10.1234/new"']
    count = client.requests
    run_discovery_review(bib, cache, client, report)
    run_auto_review(bib, cache, report, client)
    assert client.requests == count
    assert cache.get(bib, entry)["auto_review"]["epmc_checked_dois"] == [
        "10.1234/new",
        "10.1234/old",
    ]
    cache.close()
