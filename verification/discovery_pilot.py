"""Run ten expanded searches using the contact already used for this bibliography."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.parse import parse_qs, urlparse


def main():
    env = dict(os.environ)
    if not env.get("CROSSREF_MAILTO"):
        db = sqlite3.connect("file:.bibcheck/verification.sqlite3?mode=ro", uri=True)
        try:
            for (body,) in db.execute("SELECT body FROM responses"):
                url = json.loads(body).get("url", "")
                mail = parse_qs(urlparse(url).query).get("mailto", [])
                if urlparse(url).hostname == "api.crossref.org" and mail:
                    env["CROSSREF_MAILTO"] = mail[0]
                    break
        finally:
            db.close()
    if not env.get("CROSSREF_MAILTO"):
        raise SystemExit("Set CROSSREF_MAILTO to a real contact before the pilot")
    keys = Path(__file__).resolve().parent / "benchmark" / "discovery-pilot-keys.txt"
    if not keys.is_file():
        raise SystemExit("The ten-key pilot manifest is missing")
    return subprocess.run(
        [
            sys.executable,
            "bibcheck.py",
            "crossref",
            "discover-review",
            "cdl.bib",
            "--keys",
            str(keys),
            "--limit",
            "10",
        ],
        env=env,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
