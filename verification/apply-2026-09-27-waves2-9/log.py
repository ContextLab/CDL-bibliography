"""Log one wave batch's key changes after it is applied (idempotent per batch).

- verification/key-renames.json: every rename (old -> new) of the batch, with commit = the batch name.
- verification/key-deletions.json: every removed key with its reason, decision source, date and batch.
- library-changes.json (this folder): read by .bibcheck/validate-current-checkpoint.py.
  ``removed`` and ``added`` keep the flat lists of ../apply-2026-09-26-wave1/library-changes.json (keys
  as named before any of this folder's batches) plus this folder's removals; ``steps`` lists this
  folder's applied batches in order, each with its removals and its (simultaneous) renames under the
  names the keys had just before that batch. The renames of these batches chain (wave 1 renamed
  Frie08 -> Frie08a and Frie06 -> Frie08b; wave 8 renames Frie08a -> Frie12 and Frie08b -> Frie08), so
  the validator applies the steps in order rather than one flat old -> new map.

    .venv/bin/python verification/apply-2026-09-27-waves2-9/log.py wave2
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATE = "2026-09-26"
WAVES = ("wave2", "wave3", "wave4", "wave2to4") + tuple(f"wave{n}" for n in range(5, 10))  # applied in this order


def main():
    batch = sys.argv[1]
    assert batch in WAVES, batch
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

    wave1 = json.loads((ROOT / "verification/apply-2026-09-26-wave1/library-changes.json").read_text())
    path = HERE / "library-changes.json"
    steps = json.loads(path.read_text())["steps"] if path.exists() else []
    steps = [s for s in steps if s["batch"] != batch]
    assert [s["batch"] for s in steps] == list(WAVES[:WAVES.index(batch)]), "batches out of order"
    steps.append({"batch": batch, "removed": sorted(p["key"] for p in proposals if p["kind"] == "remove"),
                  "renames": {p["key"]: p["rename"] for p in proposals if p.get("rename")}})
    path.write_text(json.dumps({
        "note": "Keys that left or joined cdl.bib outside the flat key-renames.json map, read by "
                ".bibcheck/validate-current-checkpoint.py. removed/added: the wave-1 folder's lists (stage 2C's "
                "NetwLab25, the wave-1 removals, merged-PR additions), names as before this folder's batches. "
                "steps: this folder's batches in order, each with its removals and simultaneous renames (logged in "
                "key-deletions.json and key-renames.json), applied in order after the flat map.",
        "removed": wave1["removed"], "added": wave1["added"], "steps": steps,
        "last_staged": f".bibcheck/{HERE.name}/{batch}-staged.bib"}, indent=1, ensure_ascii=False) + "\n")
    print(f"{sum(r.get('commit') == batch for r in renames)} renames logged; "
          f"{sum(d.get('batch') == batch for d in deletions)} deletions logged; {len(steps)} steps")


if __name__ == "__main__":
    main()
