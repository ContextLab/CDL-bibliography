"""Log one final-apply batch's key changes after it is applied (idempotent per batch).

- verification/key-renames.json: every rename (old -> new) of the batch, with commit = the batch name.
- verification/key-deletions.json: every removed key with its reason, decision source, date and batch.
- library-changes.json (this folder): ``steps`` lists this folder's applied batches in order, each with its
  removals and its (simultaneous) renames under the names the keys had just before that batch.
  .bibcheck/validate-current-checkpoint.py applies them after ../apply-2026-09-29-waves2-9/library-changes.json
  (its flat lists and its steps).

    .venv/bin/python verification/apply-2026-09-30-final/log.py res27
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATE = "2026-09-27"
BATCHES = ("res27", "res28to33", "res34to39")  # applied in this order


def main():
    batch = sys.argv[1]
    assert batch in BATCHES, batch
    frozen = json.loads((HERE / f"{batch}-proposals.json").read_text())
    proposals = frozen["proposals"]
    staged = ROOT / ".bibcheck" / HERE.name / f"{batch}-staged.bib"
    assert (ROOT / "cdl.bib").read_bytes() == staged.read_bytes(), "cdl.bib is not this batch's staged file"

    renames_path = ROOT / "verification/key-renames.json"
    renames = [r for r in json.loads(renames_path.read_text()) if r.get("commit") != batch]
    for p in proposals:
        if p.get("rename"):
            renames.append({"old_key": p["key"], "new_key": p["rename"], "date": DATE,
                            "reason": f"{batch}: {p.get('rename_reason') or p['origin']} ({p['origin']})",
                            "commit": batch})
    renames_path.write_text(json.dumps(renames, indent=1, ensure_ascii=False) + "\n")

    deletions_path = ROOT / "verification/key-deletions.json"
    deletions = [d for d in json.loads(deletions_path.read_text()) if d.get("batch") != batch]
    for p in proposals:
        if p["kind"] == "remove":
            deletions.append({"key": p["key"], "reason": p["reason"], "decision_source": p["decision"], "date": DATE,
                              **({"research_row": p["row_key"]} if p.get("row_key") else {}), "batch": batch})
    deletions_path.write_text(json.dumps(deletions, indent=1, ensure_ascii=False) + "\n")

    path = HERE / "library-changes.json"
    steps = json.loads(path.read_text())["steps"] if path.exists() else []
    steps = [s for s in steps if s["batch"] != batch]
    assert [s["batch"] for s in steps] == list(BATCHES[:BATCHES.index(batch)]), "batches out of order"
    steps.append({"batch": batch, "removed": sorted(p["key"] for p in proposals if p["kind"] == "remove"),
                  "renames": {p["key"]: p["rename"] for p in proposals if p.get("rename")}})
    path.write_text(json.dumps({
        "note": "This folder's batches in order, each with its removals and simultaneous renames (logged in "
                "key-deletions.json and key-renames.json), read by .bibcheck/validate-current-checkpoint.py after "
                "../apply-2026-09-29-waves2-9/library-changes.json.",
        "steps": steps, "last_staged": f".bibcheck/{HERE.name}/{batch}-staged.bib"}, indent=1, ensure_ascii=False) + "\n")
    print(f"{sum(r.get('commit') == batch for r in renames)} renames logged; "
          f"{sum(d.get('batch') == batch for d in deletions)} deletions logged; {len(steps)} steps")


if __name__ == "__main__":
    main()
