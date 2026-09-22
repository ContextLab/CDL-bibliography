"""Recheck corrected/sample entries, then prove a repeat reuses verification.

Uses the working cache and its existing contact; exports a separate pilot report
and snapshot. No remote repository changes and no LLM approvals.
"""

from collections import Counter
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import (
    ACCEPTED,
    Cache,
    PoliteClient,
    current_results,
    export_snapshot,
    run_verification,
)
from auto_review import run_auto_review
from fulltext_review import run_fulltext_review
from publisher_year_review import run_publisher_year_review


def main():
    keys = {
        r["key"]
        for r in json.loads(Path(__file__).with_name("manifest.json").read_text())[
            "entries"
        ]
    }
    directory = ROOT / ".bibcheck/pilot50"
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        contact = os.environ.get("CROSSREF_MAILTO")
        if not contact:
            for (body,) in cache.db.execute("SELECT body FROM responses"):
                url = json.loads(body).get("url", "")
                if urlparse(url).hostname == "api.crossref.org":
                    values = parse_qs(urlparse(url).query).get("mailto", [])
                    if values:
                        contact = values[0]
                        break
        client = PoliteClient(cache, contact)
        before = current_results("cdl.bib", cache)
        report = directory / "verification-report.jsonl"
        stages = []
        for stage in ("corrected_and_new_resolver", "repeat"):
            requests_before = client.requests
            run_verification("cdl.bib", cache, client, report, keys=keys)
            run_auto_review("cdl.bib", cache, report, client, keys=keys)
            results = run_fulltext_review("cdl.bib", cache, client, report, keys=keys)
            results = run_publisher_year_review(
                "cdl.bib", cache, client, report, keys=keys
            )
            current = {k: results[k] for k in keys}
            stages.append(
                {
                    "stage": stage,
                    "network_requests": client.requests - requests_before,
                    "statuses": dict(Counter(r["status"] for r in current.values())),
                    "entries": {
                        k: {
                            "status": r["status"],
                            "checked_at": r.get("checked_at"),
                            "fingerprint": r["fingerprint"],
                        }
                        for k, r in current.items()
                    },
                }
            )
            print(
                json.dumps({k: v for k, v in stages[-1].items() if k != "entries"}),
                flush=True,
            )
            (directory / "verification-stages.json").write_text(
                json.dumps(stages, indent=2) + "\n"
            )
            for key, old in before.items():
                if old["status"] in ACCEPTED:
                    assert results[key] == old, (
                        "Previously approved entry changed: " + key
                    )
        assert stages[1]["network_requests"] == 0
        assert stages[0]["entries"] == stages[1]["entries"]
        export_snapshot("cdl.bib", cache, directory / "verification-snapshot.jsonl.gz")
        print("PASS: repeat uses cache; all prior approvals unchanged", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
