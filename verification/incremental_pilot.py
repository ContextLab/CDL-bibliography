"""One live DOI check, then unchanged/renamed/edited runs in an isolated cache.

Uses the real contact already recorded in the working Crossref response cache,
or CROSSREF_MAILTO. Never edits the shared bibliography or its review database.
"""

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from verification import Cache, PoliteClient, load_entries, run_verification


def main():
    contact = os.environ.get("CROSSREF_MAILTO")
    if not contact:
        db = sqlite3.connect("file:.bibcheck/verification.sqlite3?mode=ro", uri=True)
        try:
            for (body,) in db.execute("SELECT body FROM responses"):
                url = json.loads(body).get("url", "")
                if urlparse(url).hostname == "api.crossref.org":
                    values = parse_qs(urlparse(url).query).get("mailto", [])
                    if values:
                        contact = values[0]
                        break
        finally:
            db.close()
    if not contact:
        raise ValueError("Set CROSSREF_MAILTO to a real contact")
    entry = load_entries("cdl.bib")["Rame72"]
    work = Path(tempfile.mkdtemp(prefix="incremental-", dir=".bibcheck"))
    bib = work / "pilot.bib"
    bib.write_text(entry["raw"], encoding="utf-8")
    cache = Cache(work / "cache.sqlite3")
    client = PoliteClient(cache, contact)
    stages = []

    def run(stage, key):
        before = client.requests
        result = run_verification(bib, cache, client, work / "report.jsonl")[key]
        stages.append(
            {
                "stage": stage,
                "status": result["status"],
                "network_requests": client.requests - before,
                "fingerprint": result["fingerprint"],
                "checked_at": result.get("checked_at"),
            }
        )
        (work / "stages.json").write_text(json.dumps(stages, indent=2) + "\n")
        print(json.dumps(stages[-1]), flush=True)

    try:
        run("initial_live_doi", "Rame72")
        run("unchanged", "Rame72")
        renamed = entry["raw"].replace("Rame72", "RenamedPilot", 1)
        bib.write_text(renamed, encoding="utf-8")
        run("key_rename", "RenamedPilot")
        year = entry["fields"]["year"]
        bib.write_text(renamed.replace(year, "1900"), encoding="utf-8")
        run("wrong_year_cached_source", "RenamedPilot")
        assert [r["status"] for r in stages] == [
            "metadata_verified",
            "metadata_verified",
            "metadata_verified",
            "needs_review",
        ], stages
        assert [r["network_requests"] for r in stages] == [1, 0, 0, 0], stages
        assert len({r["checked_at"] for r in stages[:3]}) == 1
        assert stages[-1]["fingerprint"] != stages[0]["fingerprint"]
        print(
            f"PASS: live provider, unchanged, rename, and field-edit checks. Evidence: {work}"
        )
    finally:
        cache.close()


if __name__ == "__main__":
    main()
