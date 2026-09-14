"""Optional real web/PDF research adapter for the OpenAI Responses API.

Requires OPENAI_API_KEY and BIBCHECK_RESEARCH_MODEL. Invoked only explicitly;
normal verification and free automatic review never call a commercial model.
"""

import json
import os
import sys

import requests

from research import INSTRUCTIONS


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def request_payload(payload, model):
    phase = payload.get("phase")
    if phase not in {"discover", "extract"}:
        raise ValueError("Unknown research phase")
    instructions = INSTRUCTIONS + (
        " Return the requested JSON only. Report uncertainty explicitly. Never "
        "claim a human reviewed this. A quotation must be exact text from the "
        "provided page, not a paraphrase. Never extract this article's metadata "
        "from its references to another work. Return null URLs if no actual cited "
        "source PDF is found, and an empty fields array if evidence is unavailable."
    )
    if phase == "discover":
        previous = payload.get("previous_evidence", {})
        data = {
            "entry": payload["entry"],
            "allowed_pdf_hosts": payload["allowed_pdf_hosts"],
            "candidates": [
                {k: c.get(k) for k in ("source", "doi", "url", "issues")}
                for c in previous.get("candidates", [])
            ],
        }
        schema = object_schema(
            {
                "landing_url": {"type": ["string", "null"]},
                "pdf_url": {"type": ["string", "null"]},
                "uncertainties": {"type": "array", "items": {"type": "string"}},
            }
        )
    else:
        data = {"entry": payload["entry"], "pages": payload["pages"]}
        field = object_schema(
            {
                "field": {
                    "type": "string",
                    "enum": [
                        "title",
                        "author",
                        "year",
                        "journal",
                        "booktitle",
                        "volume",
                        "number",
                        "pages",
                        "publisher",
                        "doi",
                        "isbn",
                        "issn",
                        "edition",
                        "ENTRYTYPE",
                    ],
                },
                "value": {"type": "string"},
                "page": {"type": "integer"},
                "quote": {"type": "string"},
            }
        )
        schema = object_schema(
            {
                "fields": {"type": "array", "items": field},
                "uncertainties": {"type": "array", "items": {"type": "string"}},
            }
        )
    serialized = json.dumps(data, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > 100_000:
        raise ValueError(
            "Research input exceeds 100 KB; select less source text explicitly"
        )
    result = {
        "model": model,
        "instructions": instructions,
        "input": serialized,
        "store": False,
        "max_output_tokens": 4000,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "citation_evidence",
                "strict": True,
                "schema": schema,
            }
        },
    }
    if phase == "discover":
        result.update(
            tools=[
                {
                    "type": "web_search",
                    "filters": {"allowed_domains": payload["allowed_pdf_hosts"]},
                }
            ],
            max_tool_calls=4,
            include=["web_search_call.action.sources"],
        )
    return result


def run(payload, session=None, environ=None):
    environ = os.environ if environ is None else environ
    key, model = environ.get("OPENAI_API_KEY"), environ.get("BIBCHECK_RESEARCH_MODEL")
    if not key or not model:
        raise ValueError(
            "Set OPENAI_API_KEY and BIBCHECK_RESEARCH_MODEL before research"
        )
    body = request_payload(payload, model)
    session = session or requests.Session()
    response = session.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": "Bearer " + key},
        json=body,
        timeout=(10, 150),
    )
    if response.status_code != 200:
        raise ValueError(
            f"Research provider HTTP {response.status_code}; no approval recorded"
        )
    result = response.json()
    if result.get("status") != "completed":
        raise ValueError("Research response incomplete/refused; no evidence inferred")
    output = result.get("output", [])
    searches = [
        item
        for item in output
        if item.get("type") == "web_search_call" and item.get("status") == "completed"
    ]
    if payload["phase"] == "discover" and not searches:
        raise ValueError("Discovery did not actually use web search")
    texts = [
        part["text"]
        for item in output
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    ]
    if len(texts) != 1:
        raise ValueError("Research must return exactly one structured result")
    finding = json.loads(texts[0])
    if payload["phase"] == "extract":
        fields = finding["fields"]
        if len({f["field"] for f in fields}) != len(fields):
            raise ValueError("Duplicate research field evidence")
        finding["fields"] = {
            f["field"]: {k: f[k] for k in ("value", "page", "quote")} for f in fields
        }
    finding["provider_trace"] = {
        "provider": "openai",
        "model": model,
        "response_id": result.get("id"),
        "usage": result.get("usage"),
        "web_search_calls": len(searches),
        "sources": [
            s for item in searches for s in item.get("action", {}).get("sources", [])
        ],
    }
    return finding


if __name__ == "__main__":
    try:
        print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
    except Exception as exc:
        # Never print request headers, credentials, or raw provider errors.
        print(f"Research adapter failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(2)
