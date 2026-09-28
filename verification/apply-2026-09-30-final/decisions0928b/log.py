"""Log the decisions0928b batch's key changes after it is applied (idempotent).

- verification/key-renames.json: every rename (old -> new) of the batch, with commit = "decisions0928b".
- verification/key-deletions.json: the removed key with its reason, decision source, date and batch.
- library-changes.json (this folder): the batch's removals and (simultaneous) renames under the names the
  keys had just before it. .bibcheck/validate-current-checkpoint.py applies them after the
  organization-keys renames, the mop-up batch and decisions0928 (this batch ran after them).

    .venv/bin/python verification/apply-2026-09-30-final/decisions0928b/log.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATE = "2026-09-28"
BATCH = "decisions0928b"


def main():
    proposals = json.loads((HERE / f"{BATCH}-proposals.json").read_text())["proposals"]
    staged = ROOT / ".bibcheck" / "decisions0928b-2026-09-28" / f"{BATCH}-staged.bib"
    assert (ROOT / "cdl.bib").read_bytes() == staged.read_bytes(), "cdl.bib is not this batch's staged file"

    renames_path = ROOT / "verification/key-renames.json"
    renames = [r for r in json.loads(renames_path.read_text()) if r.get("commit") != BATCH]
    for p in proposals:
        if p.get("rename"):
            why = ("organization-author key rule, user 2026-09-28 (\"use as many organization 'words' as are "
                   "available, until 4 letters are achieved\")" if p.get("origin", "").startswith("resolution")
                   else "suffix rule: GrilEtal06b dropped (user 2026-09-28), so GrilEtal06a is the only "
                        "GrilEtal06 entry")
            renames.append({"old_key": p["key"], "new_key": p["rename"], "date": DATE, "reason": why,
                            "commit": BATCH})
    renames_path.write_text(json.dumps(renames, indent=1, ensure_ascii=False) + "\n")

    deletions_path = ROOT / "verification/key-deletions.json"
    deletions = [d for d in json.loads(deletions_path.read_text()) if d.get("batch") != BATCH]
    for p in proposals:
        if p["kind"] == "remove":
            deletions.append({"key": p["key"], "reason": p["reason"], "decision_source": p["decision"],
                              "date": DATE, "batch": BATCH})
    deletions_path.write_text(json.dumps(deletions, indent=1, ensure_ascii=False) + "\n")

    (HERE / "library-changes.json").write_text(json.dumps({
        "note": "The decisions0928b batch's removals and simultaneous renames (logged in key-deletions.json and "
                "key-renames.json), read by .bibcheck/validate-current-checkpoint.py after the organization-keys "
                "renames, the mop-up batch and decisions0928.",
        "batch": BATCH,
        "removed": sorted(p["key"] for p in proposals if p["kind"] == "remove"),
        "renames": {p["key"]: p["rename"] for p in proposals if p.get("rename")},
        "staged": str(staged.relative_to(ROOT))}, indent=1, ensure_ascii=False) + "\n")
    print(f"{sum(r.get('commit') == BATCH for r in renames)} renames logged; "
          f"{sum(d.get('batch') == BATCH for d in deletions)} deletions logged")


if __name__ == "__main__":
    main()
