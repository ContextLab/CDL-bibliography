import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from dartmouth_models import PREFERRED_TEXT_MODEL, require_free, summarize_model
import dartmouth_research_adapter as adapter


def model(tags=(), input_cost=None, output_cost=None):
    return {
        "id": PREFERRED_TEXT_MODEL,
        "tags": [{"name": tag} for tag in tags],
        "info": {
            "meta": {
                "upstream_model_info": {
                    "model_info": {
                        "input_cost_per_token": input_cost,
                        "output_cost_per_token": output_cost,
                    }
                }
            }
        },
    }


def test_local_without_free_annotation_is_eligible():
    row = summarize_model(model(["Local", "Reasoning"]))
    assert require_free([row], PREFERRED_TEXT_MODEL) == row
    assert (
        adapter.configuration({"DARTMOUTH_CHAT_API_KEY": "fixture"})[1]
        == PREFERRED_TEXT_MODEL
    )


@pytest.mark.parametrize(
    "raw",
    [
        model(["Local"], 0.01, 0),
        model(["Free"], 0, 0.01),
        model(["Local"], "0.01", "0"),
        model(["Local"], "unknown", 0),
        model(["Free"], -1, 0),
        model(["Local"], float("nan"), 0),
        model([]),
    ],
)
def test_unknown_or_explicitly_paid_models_fail_closed(raw):
    with pytest.raises(ValueError, match="not confirmed free"):
        require_free([summarize_model(raw)], PREFERRED_TEXT_MODEL)


def test_sanitized_catalog_does_not_export_private_metadata():
    raw = model(["Local"], 0, 0)
    raw["info"]["user_id"] = "private-user-id"
    raw["info"]["meta"]["upstream_model_info"]["internal_key"] = "private-key"
    result = repr(summarize_model(raw))
    assert "private-user-id" not in result
    assert "private-key" not in result


def test_paid_model_is_rejected_before_inference():
    class Response:
        status_code = 200

        def json(self):
            return {"data": [model(["Local"], 0.01, 0.01)]}

    class Session:
        def get(self, *args, **kwargs):
            return Response()

        def post(self, *args, **kwargs):
            pytest.fail("Paid inference must never be called")

    with pytest.raises(ValueError, match="not confirmed free"):
        adapter.run(
            {"phase": "extract", "pages": []},
            Session(),
            {"DARTMOUTH_CHAT_API_KEY": "fixture"},
        )


def test_glm_request_uses_max_reasoning_and_checks_completion(monkeypatch):
    monkeypatch.setattr(adapter.time, "sleep", lambda _: None)

    class Response:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"uncertainties":[]}'},
                    }
                ]
            }

    class Session:
        def post(self, url, **kwargs):
            body = kwargs["json"]
            assert body["model"] == PREFERRED_TEXT_MODEL
            assert body["reasoning_effort"] == "max"
            assert body["chat_template_kwargs"]["clear_thinking"] is True
            assert body["max_tokens"] == 16000
            assert kwargs["timeout"][1] >= 240
            return Response()

    adapter.complete({}, {}, "Extract", Session(), "fixture", PREFERRED_TEXT_MODEL)
