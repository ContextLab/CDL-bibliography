import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
import research
from openai_research_adapter import request_payload, run
from verification import Cache, load_entries


def discovery():
    return {
        "phase": "discover",
        "entry": {"title": "A paper"},
        "allowed_pdf_hosts": ["example.org"],
        "previous_evidence": {"candidates": []},
    }


def test_openai_request_has_bounded_tools_and_no_commands():
    body = request_payload(discovery(), "configured-model")
    assert body["max_tool_calls"] == 4
    assert body["max_output_tokens"] == 4000 and body["store"] is False
    assert [tool["type"] for tool in body["tools"]] == ["web_search"]
    assert body["text"]["format"]["strict"] is True
    with pytest.raises(ValueError):
        request_payload(
            {"phase": "extract", "entry": {}, "pages": [{"text": "x" * 100001}]},
            "model",
        )


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class Session:
    def __init__(self, body):
        self.body = body

    def post(self, url, **kwargs):
        assert url == "https://api.openai.com/v1/responses"
        return Response(self.body)


def result(text, search=True):
    items = [
        {
            "type": "message",
            "content": [{"type": "output_text", "text": json.dumps(text)}],
        }
    ]
    if search:
        items.insert(
            0,
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"sources": []},
            },
        )
    return {
        "status": "completed",
        "output": items,
        "id": "example",
        "usage": {"input_tokens": 100},
    }


ENV = {"OPENAI_API_KEY": "fake-test-key", "BIBCHECK_RESEARCH_MODEL": "model"}


def test_discovery_requires_actual_web_search_and_configured_credentials():
    values = {
        "landing_url": "https://example.org/a",
        "pdf_url": "https://example.org/a.pdf",
        "uncertainties": [],
    }
    finding = run(discovery(), Session(result(values)), ENV)
    assert finding["provider_trace"]["web_search_calls"] == 1
    with pytest.raises(ValueError):
        run(discovery(), Session(result(values, search=False)), ENV)
    with pytest.raises(ValueError):
        run(discovery(), Session(result(values)), {})
    with pytest.raises(ValueError):
        run(discovery(), Session({"status": "incomplete", "output": []}), ENV)


def test_extraction_has_page_quotes_and_rejects_duplicate_fields():
    payload = {
        "phase": "extract",
        "entry": {},
        "pages": [{"page": 1, "text": "A paper"}],
    }
    values = {
        "fields": [
            {"field": "title", "value": "A paper", "page": 1, "quote": "A paper"}
        ],
        "uncertainties": [],
    }
    finding = run(payload, Session(result(values, search=False)), ENV)
    assert finding["fields"]["title"]["quote"] == "A paper"
    values["fields"].append(dict(values["fields"][0]))
    with pytest.raises(ValueError):
        run(payload, Session(result(values, search=False)), ENV)


def test_batch_resume_and_edits_cannot_reuse_pdf_findings(tmp_path, monkeypatch):
    bib = tmp_path / "a.bib"
    bib.write_text("@book{A,title={One},year={2020}}\n@book{B,title={Two},year={2020}}")
    cache = Cache(tmp_path / "cache.sqlite3")
    for entry in load_entries(bib).values():
        cache.put(bib, entry, {"status": "needs_review"})
    calls = []

    def collect(entry, *args):
        calls.append(entry["key"])
        return {
            "fields": {
                "title": {
                    "value": entry["fields"]["title"],
                    "quote": entry["fields"]["title"],
                    "page": 1,
                }
            }
        }

    monkeypatch.setattr(research, "research_entry", collect)
    monkeypatch.setattr(research.time, "sleep", lambda _: None)
    assert (
        research.run_research_batch(bib, cache, "adapter", ["example.org"], limit=1)
        == 1
    )
    assert (
        research.run_research_batch(bib, cache, "adapter", ["example.org"], limit=1)
        == 1
    )
    assert (
        research.run_research_batch(bib, cache, "adapter", ["example.org"], limit=1)
        == 0
    )
    assert calls == ["A", "B"]
    assert all(
        cache.get(bib, e)["status"] == "needs_review"
        for e in load_entries(bib).values()
    )
    bib.write_text(bib.read_text().replace("One", "Changed"))
    assert cache.get(bib, load_entries(bib)["A"]) is None


def test_batch_stops_after_repeated_failures_and_saves_them(tmp_path, monkeypatch):
    bib = tmp_path / "a.bib"
    bib.write_text(
        "\n".join("@book{" + k + ",title={Test " + k + "},year={2020}}" for k in "ABCD")
    )
    cache = Cache(tmp_path / "cache.sqlite3")
    for entry in load_entries(bib).values():
        cache.put(bib, entry, {"status": "needs_review"})

    def fail(*args):
        raise ValueError("Test PDF unavailable")

    monkeypatch.setattr(research, "research_entry", fail)
    monkeypatch.setattr(research.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="Three consecutive"):
        research.run_research_batch(bib, cache, "adapter", ["example.org"])
    records = [cache.get(bib, e) for e in load_entries(bib).values()]
    assert sum(bool(r.get("research_attempt")) for r in records) == 3
    assert all(r["status"] == "needs_review" for r in records)


def test_unknown_research_keys_fail_before_adapter_call(tmp_path, monkeypatch):
    bib = tmp_path / "a.bib"
    bib.write_text("@book{A,title={Test},year={2020}}")
    cache = Cache(tmp_path / "cache.sqlite3")
    cache.put(bib, load_entries(bib)["A"], {"status": "needs_review"})

    def forbidden(*args):
        raise AssertionError("Adapter must not run for invalid key selection")

    monkeypatch.setattr(research, "research_entry", forbidden)
    for keys in ([], ["Unknown"]):
        with pytest.raises(ValueError, match="key list"):
            research.run_research_batch(
                bib, cache, "adapter", ["example.org"], keys=keys
            )
