"""Audit the pre-fix proposals (verification/apply-2026-09-23/measure-phase0/)
with the general principle: every after-value must be stated by a source
record for the proposal's DOI. Read-only (main cache ``mode=ro``; stored issue
lookups from lookups.json); no network. Writes baseline-audit.json.

    .venv/bin/python verification/fixes-2026-09-24/audit_baseline.py
"""
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bibcheck"))
os.chdir(ROOT)
from verification import Cache, load_entries  # noqa: E402
from auto_review import reassess  # noqa: E402
import correction_proposals as cp  # noqa: E402


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
    old = json.loads((ROOT / "verification/apply-2026-09-23/measure-phase0/proposals.json").read_text())["proposals"]
    lookups = json.loads((HERE / "lookups.json").read_text())["lookups"]
    entries = load_entries(ROOT / "cdl.bib")
    cache = ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
    rows, stale = [], 0
    for p in old:
        entry = entries.get(p["key"])
        if not entry or entry["fingerprint"] != p["fingerprint"]:
            stale += 1
            continue
        previous = reassess(entry, cache.get(ROOT / "cdl.bib", entry))
        stated_by, violations = cp.after_value_statements(entry, previous, p, lookups.get(p.get("doi")))
        fmt = {}
        after = (p["changes"].get("author") or {}).get("after")
        if after:
            # House form: every given-name token of the after-value is one capital initial.
            from bibtexparser.customization import splitname
            from verification import split_authors
            bad = [n for n in split_authors(after) if not n.startswith("{")
                   and any(len(t.strip("{}")) > 1 and "-" not in t for t in splitname(n, strict_mode=True)["first"])]
            if bad:
                fmt["author"] = "given names not in house form (initials): " + "; ".join(bad[:3])
        issue = None
        vol = p["changes"].get("volume", {})
        if "number" in p["changes"] or cp.cited_issue_label(vol.get("before")):
            issue = {"after": (p["changes"].get("number") or {}).get("after"), "stated_by": stated_by.get("number")}
        rows.append({"key": p["key"], "class": p["class"], "violations": violations, "format": fmt, "issue": issue})
    cache.close()
    out = {"proposals": len(old), "stale_fingerprints": stale,
           "principle_violations": [r for r in rows if r["violations"]],
           "author_format_defects": sum(1 for r in rows if r["format"]),
           "issue_rows": [r for r in rows if r["issue"]]}
    (HERE / "baseline-audit.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"proposals": len(old), "stale": stale, "violations": len(out["principle_violations"]),
                      "author_format_defects": out["author_format_defects"],
                      "issue_rows": len(out["issue_rows"]),
                      "issue_rows_unstated": sum(1 for r in out["issue_rows"] if not r["issue"]["stated_by"])}, indent=1))
    for r in out["principle_violations"]:
        print(r["key"], r["class"], r["violations"])


if __name__ == "__main__":
    main()
