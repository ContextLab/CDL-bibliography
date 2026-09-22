"""Confirm the selected free model handles source-grounded JSON before scaling."""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bibcheck"))
from dartmouth_research_adapter import configuration, complete
from dartmouth_models import fetch_models, require_free
import requests


def main():
    key, model = configuration(os.environ)
    session = requests.Session()
    record = require_free(fetch_models(key, session), model)
    print("Confirmed free:", model, record["tags"], flush=True)
    data = {
        "source": "ARTICLE FRONT MATTER\nTitle: Memory and attention\nAuthors: Alice Smith; Bob Jones\nPublished: 2007\nReceived: 2005\nVolume: 12\nIssue: 4\nPages: 101-109\nREFERENCES\nJones B. Memory and attention. 1999."
    }
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "authors": {"type": "array", "items": {"type": "string"}},
            "year": {"type": "string"},
            "pages": {"type": "string"},
            "uncertainties": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "authors", "year", "pages", "uncertainties"],
        "additionalProperties": False,
    }
    start = time.monotonic()
    finding, trace = complete(
        data,
        schema,
        "Read only the source own article metadata. Do not use received dates or reference-list entries.",
        session,
        key,
        model,
        read_timeout=240,
    )
    result = {
        "finding": finding,
        "trace": trace,
        "seconds": round(time.monotonic() - start, 2),
    }
    Path(".bibcheck/pilot50/model-smoke.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result, indent=2), flush=True)
    assert finding == {
        "title": "Memory and attention",
        "authors": ["Alice Smith", "Bob Jones"],
        "year": "2007",
        "pages": "101-109",
        "uncertainties": [],
    }


if __name__ == "__main__":
    main()
