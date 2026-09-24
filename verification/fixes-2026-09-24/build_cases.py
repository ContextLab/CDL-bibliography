"""Freeze the real cached cases the 2026-09-24 fix tests use.

Reads cdl.bib and the latest current review rows from the main cache opened
read-only (``mode=ro``), plus the stored issue lookups (lookups.json, from
.bibcheck/fixes-2026-09-24.sqlite3). Rows and entries are copied unmodified.
Writes cases.json.gz next to this file; no network.

    .venv/bin/python verification/fixes-2026-09-24/build_cases.py
"""
import gzip
import json
import os
import re
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bibcheck"))
os.chdir(ROOT)
from verification import Cache, load_entries  # noqa: E402

KEYS = {
    # The five spot-check verdicts (2026-09-24).
    "AlyTurk16": "author house form; the kept issue 4 is stated by Crossref",
    "SmitHalg89": "author house form; 'add number (1)' (Crossref issue 1)",
    "Youn79": "full given name -> initials (D C Young)",
    "Murd71": "10(4-B) split; Crossref issue 4 (also Springer citation_issue 4)",
    "Hint03": "10(1) split; Crossref and PubMed issue 1 (also Springer citation_issue 1)",
    # Issue only in the citation: dropped after PubMed and publisher lookups.
    "ScudEtal14": "number 1 stated by no source (PubMed record has no issue; Elsevier API none)",
    "CohnEtal96": "number 1 stated by no source; publisher page unavailable",
    "EkstWatr14": "PubMed states issue '0 2': not a plain number, held",
    # Author negative controls.
    "PezzEtal17": "particle surname {van der Meer} kept verbatim",
    "delaEtal07": "particle surname {de la Rocha} kept; source accent added (Josic -> Josić)",
    "WillEtal05b": "citation {van Bruggen} kept against Crossref 'Van Bruggen'",
    "KotcEtal96": "all-capital Crossref surnames: held",
    "WuEtal01": "Crossref given 'R.Mark': held (no longer the garbled 'RMark')",
    "RacsEtal08": "LaTeX accents in the citation are not case-protecting braces",
    "RebeEtal02": "hyphenated given name M.-Marsel -> M-M",
    "GrifEtal11": "brace-led accented given name {\\'{E}}adaoin: never rewritten",
}


class ReadOnlyCache(Cache):
    def __init__(self, filename):
        self.path = Path(filename)
        self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)

    def store(self, *args, **kwargs):
        return True

    def put(self, bibliography, entry, result):
        return self.retain_notices(entry, result)

    def remember_notices(self, candidates):
        return None


def main():
    entries = load_entries(ROOT / "cdl.bib")
    cache = ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
    cases = {}
    for key, why in KEYS.items():
        cases[key] = {"why": why, "entry": entries[key], "previous": cache.get(ROOT / "cdl.bib", entries[key])}
    # A corporate byline under review with a Crossref record (first in file order).
    for key, entry in entries.items():
        names = [n.strip() for n in entry["fields"].get("author", "").split(" and ")]
        if entry["fields"].get("ENTRYTYPE") == "article" and any(
                n.startswith("{") and n.endswith("}") and "\\" not in n and " " in n for n in names):
            row = cache.get(ROOT / "cdl.bib", entry)
            if row and row.get("status") == "needs_review" and any(
                    c.get("source") == "crossref" for c in row.get("candidates", [])):
                cases[key] = {"why": "corporate byline: never rewritten", "entry": entry, "previous": row}
                break
    cache.close()
    lookups = json.loads((HERE / "lookups.json").read_text())["lookups"]
    # Stored responses of the issue-lookup cache for three DOIs, replayed by the
    # tests through the real lookup code with zero network requests: PubMed by
    # DOI + Springer page (Hint03), the Elsevier article API (ScudEtal14), and
    # ecitmatch + an unavailable page (CohnEtal96).
    replay_dois = ["10.3758/bf03196465", "10.1016/j.bandc.2014.03.016", "10.1613/jair.295"]
    fixes = sqlite3.connect(f"file:{ROOT / '.bibcheck/fixes-2026-09-24.sqlite3'}?mode=ro", uri=True)
    rows = [list(r) for r in fixes.execute("SELECT request, fetched, body FROM responses")]
    fixes.close()
    terms = set(replay_dois)
    for request, _, body in rows:  # PMIDs found by the DOI searches, and the ecitmatch queries
        if "esearch.fcgi" in request and any(d in request for d in replay_dois):
            terms.update((json.loads(body).get("body") or {}).get("esearchresult", {}).get("idlist", []))
    terms.update(v["pubmed"]["query"].split("ecitmatch ", 1)[1] for d, v in lookups.items()
                 if d in replay_dois and "ecitmatch " in (v["pubmed"].get("query") or ""))
    responses = [r for r in rows if any(t in r[0] for t in terms)
                 and ("eutils" in r[0] or "issue-head-v1:" in r[0] or "elsevier" in r[0])]
    if any("@" in r[0] or "mailto" in r[2] or "email=" in r[2] for r in responses):
        raise SystemExit("A stored response carries a contact address; not freezing it")
    data = {"cases": cases, "lookups": {d: v for d, v in lookups.items() if v.get("key") in cases},
            "replay": {"dois": replay_dois, "responses": responses}}
    # The polite-pool contact inside stored request URLs is not evidence; redact it.
    text = re.sub(r"mailto=[^&\"\s]+", "mailto=contact-redacted", json.dumps(data, ensure_ascii=False))
    with gzip.open(HERE / "cases.json.gz", "wt") as out:
        out.write(text)
    print(len(cases), "cases;", len(data["lookups"]), "lookups;", sorted(cases))


if __name__ == "__main__":
    main()
