import json
from pathlib import Path
import sys

import pytest

from cdlbib import dartmouth_research_adapter as adapter
from cdlbib import search_tools

ENV = {
    "DARTMOUTH_CHAT_API_KEY": "test-secret",
    "BIBCHECK_RESEARCH_MODEL": "qwen.qwen3.5-122b",
}
PDF = "https://publisher.example/paper.pdf"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(adapter.time, "sleep", lambda _: None)


class Response:
    status_code = 200
    headers = {}

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.body.encode()


class ModelSession:
    def __init__(self, findings):
        self.findings = iter(findings)
        self.requests = []

    def get(self, url, **kwargs):
        assert url == adapter.BASE + "/models"
        return Response(
            {
                "data": [
                    {"id": ENV["BIBCHECK_RESEARCH_MODEL"], "tags": [{"name": "Free"}]}
                ]
            }
        )

    def post(self, url, **kwargs):
        assert url == adapter.BASE + "/chat/completions"
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["Authorization"] == "Bearer test-secret"
        assert "test-secret" not in json.dumps(kwargs["json"])
        self.requests.append(kwargs["json"])
        return Response(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(next(self.findings))},
                    }
                ],
                "usage": {"total_tokens": 100},
            }
        )


class Search:
    backend = "duckduckgo"

    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return {"query": query, "results": [{"url": PDF, "title": "A paper"}]}


def payload():
    return {
        "phase": "discover",
        "entry": {"title": "A paper"},
        "allowed_pdf_hosts": ["publisher.example"],
        "previous_evidence": {"candidates": []},
    }


def search_action(query="A paper PDF"):
    return {
        "action": "web_search",
        "query": query,
        "source_index": None,
        "uncertainties": [],
    }


def select(index=0):
    return {
        "action": "select",
        "query": None,
        "source_index": index,
        "uncertainties": ["Confirm edition"],
    }


def no_html(*args, **kwargs):
    raise ValueError("No landing HTML")


def test_model_search_tool_returns_actual_source_and_trace(monkeypatch):
    monkeypatch.setattr(adapter, "get_source", no_html)
    model = ModelSession([search_action(), select()])
    search = Search()
    finding = adapter.run(payload(), model, ENV, search)
    assert search.queries == ["A paper PDF"]
    assert finding["pdf_url"] == PDF
    assert finding["uncertainties"] == ["Confirm edition"]
    assert finding["provider_trace"]["searches"][0]["query"] == "A paper PDF"
    assert len(finding["provider_trace"]["calls"]) == 2
    assert "status" not in finding


@pytest.mark.parametrize("index", [True, -1, 99, "0", None])
def test_fabricated_source_selection_rejected(index):
    with pytest.raises(ValueError, match="retrieved PDF"):
        adapter.run(payload(), ModelSession([select(index)]), ENV, Search())


def test_repeated_queries_and_budget_fail_closed(monkeypatch):
    monkeypatch.setattr(adapter, "get_source", no_html)
    for queries, reason in [
        (["same", "same"], "repeated"),
        (["one", "two", "three", "four"], "budget"),
    ]:
        search = Search()
        with pytest.raises(ValueError, match=reason):
            adapter.run(
                payload(),
                ModelSession([search_action(q) for q in queries]),
                ENV,
                search,
            )
        assert len(search.queries) <= 3


def test_model_can_revise_search_after_no_pdf(monkeypatch):
    monkeypatch.setattr(adapter, "get_source", no_html)
    search = Search()
    original = search.search

    def first_empty(query):
        result = original(query)
        if len(search.queries) == 1:
            result["results"] = []
        return result

    search.search = first_empty
    model = ModelSession([search_action("first"), search_action("revised"), select()])
    assert adapter.run(payload(), model, ENV, search)["pdf_url"] == PDF
    second_input = json.loads(model.requests[1]["messages"][1]["content"])
    assert second_input["search_results"][0]["results"] == []


def test_extraction_selects_passages_and_rejects_unknown_ids():
    extraction = {
        "phase": "extract",
        "entry": {"title": "Not shown to model"},
        "pages": [{"page": 1, "text": "A paper"}],
    }
    field = {"field": "title", "value": "A paper", "passage_ids": ["p1l1"]}
    model = ModelSession([{"fields": [field], "uncertainties": []}])
    result = adapter.run(extraction, model, ENV)
    assert result["fields"]["title"]["quote"] == "A paper"
    assert result["fields"]["title"]["grounding"] == "literal_text_present"
    assert "Not shown to model" not in json.dumps(model.requests)
    for fields in [
        [dict(field, passage_ids=["p99l1"])],
        [field, field],
        [dict(field, field="approved")],
        [dict(field, quote="Invented")],
    ]:
        with pytest.raises(ValueError):
            adapter.run(
                extraction, ModelSession([{"fields": fields, "uncertainties": []}]), ENV
            )


def test_model_preflight_no_silent_substitution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class Models:
        def get(self, url, **kwargs):
            assert url == adapter.BASE + "/models"
            assert kwargs["allow_redirects"] is False
            return Response(
                {"data": [{"id": "qwen.qwen3.5-122b", "tags": [{"name": "Free"}]}]}
            )

    assert adapter.check_model(Models(), ENV) == "qwen.qwen3.5-122b"
    with pytest.raises(ValueError, match="absent or not confirmed free"):
        adapter.check_model(Models(), dict(ENV, BIBCHECK_RESEARCH_MODEL="wrong-model"))
    with pytest.raises(ValueError, match="DARTMOUTH_CHAT_API_KEY"):
        adapter.run(payload(), ModelSession([]), {})


def test_local_key_file_and_environment_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "local-key.txt"
    path.write_text("fixture-file-key\n")
    config = {"BIBCHECK_DARTMOUTH_KEY_FILE": str(path)}
    assert adapter.configuration(config)[0] == "fixture-file-key"
    assert (
        adapter.configuration(dict(config, **ENV))[0] == ENV["DARTMOUTH_CHAT_API_KEY"]
    )
    path.write_text("two tokens")
    with pytest.raises(ValueError, match="single token"):
        adapter.configuration(config)
    path.write_text("")
    with pytest.raises(ValueError, match="local Dartmouth key file"):
        adapter.configuration(config)


def test_search_cache_and_duckduckgo_redirect_parsing(tmp_path, monkeypatch):
    calls = []

    def fetch(*args, **kwargs):
        calls.append(kwargs["params"]["q"])
        return (
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpublisher.example%2Fpaper.pdf">A <b>paper</b></a>',
            "https://html.duckduckgo.com/html/",
        )

    monkeypatch.setattr(search_tools, "get_source", fetch)
    cache = tmp_path / "search.sqlite3"
    search = search_tools.WebSearch("duckduckgo", cache)
    first = search.search('"A paper: étude" PDF')
    assert first["results"][0]["url"] == PDF
    assert first["results"][0]["title"] == "A paper"
    search.close()
    search = search_tools.WebSearch("duckduckgo", cache)
    assert search.search('"A paper: étude" PDF')["cached"] is True
    assert len(calls) == 1
    search.close()


@pytest.mark.parametrize("html", ["<form id='challenge-form'>", "unrecognized page"])
def test_duckduckgo_challenge_is_not_an_empty_success(tmp_path, monkeypatch, html):
    monkeypatch.setattr(search_tools, "get_source", lambda *a, **k: (html, "url"))
    search = search_tools.WebSearch("duckduckgo", tmp_path / "s.sqlite3")
    with pytest.raises(ValueError):
        search.search("paper")
    assert search.db.execute("SELECT count(*) FROM searches").fetchone()[0] == 0
    search.close()


def test_unallowed_redirect_is_never_fetched():
    class Redirect:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append(url)
            assert "Authorization" not in kwargs["headers"]
            response = Response("")
            response.status_code = 302
            response.headers = {"Location": "https://unallowed.example/private"}
            return response

    session = Redirect()
    with pytest.raises(ValueError, match="explicitly allowed"):
        search_tools.get_source(
            session, "https://publisher.example/a", ["publisher.example"]
        )
    assert len(session.calls) == 1


def test_publisher_relative_pdf_metadata_is_retrieved(monkeypatch):
    monkeypatch.setattr(
        adapter,
        "get_source",
        lambda *a, **k: (
            '<head><meta name="citation_pdf_url" content="paper.pdf"></head>',
            "https://publisher.example/article",
        ),
    )
    source = payload()
    source["entry"]["url"] = "https://publisher.example/article"
    result = adapter.discover_sources(source, None)
    assert result[0]["pdf_url"] == PDF


def test_alternative_pdf_survives_when_first_host_is_not_allowed(monkeypatch):
    monkeypatch.setattr(adapter, "get_source", no_html)
    result = adapter.discover_sources(
        payload(),
        None,
        [
            {
                "pdf_url": "https://unallowed.example/a.pdf",
                "pdf_urls": ["https://unallowed.example/a.pdf", PDF],
            }
        ],
    )
    assert [s["pdf_url"] for s in result] == [PDF]


def test_qwen_json_fences_do_not_relax_content_validation():
    for text in ['{"a": 1}', '```json\n{"a": 1}\n```', '{"a": 1}\n```']:
        assert adapter.parse_model_json(text) == {"a": 1}
    for text in ['{"a": 1} prose', '{"a": 1}\n{"a": 2}', '{"a": 1, "a": 2}']:
        with pytest.raises(ValueError):
            adapter.parse_model_json(text)
