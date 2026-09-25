"""Build prfix002-proposals.json: pin the latest arXiv version of the two multi-version PR #87 preprints.

User rule (2026-09-24): preprints cite their latest version and pin it where the server supports
it. prfix001 set WangEtal24's year to the v2 date (2024) but left the arXiv id unpinned, so the
arXiv route compared the year with DataCite's publicationYear (2022) and held it. The house form
of a pinned id is ``Volume = {<id>v<N>}`` (e.g. ConnEtal17 1705.02364v5, GongEtal25 2410.17891v3).

    .venv/bin/python verification/apply-2026-09-28/build_prfix002.py
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import load_entries  # noqa: E402

AX = "https://export.arxiv.org/api/query?id_list="
PINS = {"WangEtal24": ("2212.03533", "2212.03533v2", "<id>http://arxiv.org/abs/2212.03533v2</id> <updated>2024-02-22T06:21:51Z</updated>"),
        "YangEtal25a": ("2510.00183", "2510.00183v2", "<id>http://arxiv.org/abs/2510.00183v2</id> <updated>2025-10-02T19:22:39Z</updated>")}


def main():
    entries = load_entries(ROOT / "cdl.bib")
    proposals = []
    for key, (before, after, quote) in PINS.items():
        entry = entries[key]
        assert entry["fields"]["volume"] == before, (key, entry["fields"]["volume"])
        proposals.append({"key": key, "fingerprint": entry["fingerprint"], "kind": "edit", "pr": "87",
                          "changes": {"volume": {"before": before, "after": after,
                                                 "evidence": [{"url": AX + before, "quote": quote}]}}})
    out = {"batch": "prfix002", "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(proposals),
           "skipped": {}, "proposals": proposals}
    (HERE / "prfix002-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(len(proposals), "proposals")


if __name__ == "__main__":
    main()
