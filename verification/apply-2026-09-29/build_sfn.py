"""Build sfn001-proposals.json: RamaEtal12b and SommEtal12 as resolved in
../research-pilot-2026-09-24/followup.json (SfN 2012 Neuroscience Meeting Planner; see
SFN-SOURCE.md there). They were held in pilot001 because the SfN route raised
KeyError 'accepted_doi' in osf_review.merge; that is fixed in 1b91591.

    .venv/bin/python verification/apply-2026-09-29/build_sfn.py
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import load_entries  # noqa: E402

KEYS = ("RamaEtal12b", "SommEtal12")


def main():
    entries = load_entries(ROOT / "cdl.bib")
    follow = {r["key"]: r for r in json.loads((ROOT / "verification/research-pilot-2026-09-24/followup.json").read_text())}
    proposals = []
    for key in KEYS:
        entry = entries[key]
        fields = entry["fields"]
        changes = {}
        for field, change in follow[key]["changes"].items():
            after = change.get("after")
            if field == "ENTRYTYPE":
                before = fields["ENTRYTYPE"]
            else:
                before = fields.get(field)
            if before == after:
                continue            # confirmed unchanged by the planner
            assert before == change.get("before"), (key, field, before, change.get("before"))
            changes[field] = {"before": before, "after": after, "evidence": change.get("evidence", [])}
        proposals.append({"key": key, "fingerprint": entry["fingerprint"], "kind": "edit",
                          "origin": "followup.json (SfN planner; user: keep, 2026-09-25)",
                          "notes": follow[key].get("notes"), "changes": changes})
    out = {"batch": "sfn001", "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(proposals),
           "proposals": proposals}
    (HERE / "sfn001-proposals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for p in proposals:
        print(p["key"], {f: c["after"] for f, c in p["changes"].items()})


if __name__ == "__main__":
    main()
