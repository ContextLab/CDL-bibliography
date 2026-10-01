"""Sanitized Dartmouth model discovery and explicit free-model eligibility."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sys

import requests

PREFERRED_TEXT_MODEL = "zai-org.glm-5.3"


def summarize_model(model):
    meta = model.get("info", {}).get("meta", {})
    upstream = meta.get("upstream_model_info", {})
    info = upstream.get("model_info", {})
    tags = sorted(
        {
            tag["name"].lower()
            for tag in model.get("tags", []) + meta.get("tags", [])
            if isinstance(tag, dict) and isinstance(tag.get("name"), str)
        }
    )
    costs = [info.get("input_cost_per_token"), info.get("output_cost_per_token")]
    parsed = []
    invalid_cost = False
    for cost in costs:
        try:
            amount = None if cost is None else Decimal(str(cost))
            if amount is not None and (not amount.is_finite() or amount < 0):
                raise ValueError("Invalid cost")
            parsed.append(amount)
        except (InvalidOperation, ValueError):
            parsed.append(None)
            invalid_cost = True
    explicit_cost = any(cost is not None and cost > 0 for cost in parsed)
    free = (
        not invalid_cost
        and not explicit_cost
        and ("local" in tags or "free" in tags or parsed == [0, 0])
    )
    return {
        "id": model["id"],
        "name": model.get("name", model["id"]),
        "tags": tags,
        "free": free,
        "hidden": meta.get("hidden", False),
        "input_cost_per_token": costs[0],
        "output_cost_per_token": costs[1],
        "max_input_tokens": info.get("max_input_tokens"),
        "supports_reasoning": info.get("supports_reasoning"),
        "reported_vision": meta.get("capabilities", {}).get("vision"),
    }


def fetch_models(key, session=None):
    response = (session or requests.Session()).get(
        "https://chat.dartmouth.edu/api/models",
        headers={"Authorization": "Bearer " + key},
        timeout=(5, 30),
        allow_redirects=False,
    )
    if response.status_code != 200:
        raise ValueError(f"Dartmouth model lookup HTTP {response.status_code}")
    models = response.json().get("data")
    if not isinstance(models, list):
        raise ValueError("Malformed Dartmouth model catalog")
    return [summarize_model(model) for model in models]


def require_free(models, model_id):
    matches = [model for model in models if model["id"] == model_id]
    if len(matches) != 1 or not matches[0]["free"]:
        raise ValueError(
            "Configured model is absent or not confirmed free: " + model_id
        )
    return matches[0]


def main():
    from .dartmouth_research_adapter import configuration

    key, _ = configuration(os.environ)
    models = fetch_models(key)
    result = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "models": models}
    if len(sys.argv) == 2:
        output = Path(sys.argv[1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n")
    for model in models:
        if model["free"]:
            print(json.dumps(model))
    require_free(models, PREFERRED_TEXT_MODEL)
    print("Preferred text model: " + PREFERRED_TEXT_MODEL)


if __name__ == "__main__":
    main()
