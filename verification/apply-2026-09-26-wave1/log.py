"""Log the wave1 batch's key changes after it is applied (idempotent).

- verification/key-renames.json: every rename (old -> new) and the HealKaha14b -> HealKaha16
  replacement (kind "replacement"), in the existing format.
- verification/key-deletions.json: every removed key with its reason, decision source, date and,
  for a duplicate merge, the keeper key.
- library-changes.json (this folder): the cumulative removals and merged-PR additions read by
  .bibcheck/validate-current-checkpoint.py (stage 2C/2D's file plus this batch's removals).

    .venv/bin/python verification/apply-2026-09-26-wave1/log.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATE = "2026-09-26"
BATCH = "wave1"


def main():
    frozen = json.loads((HERE / f"{BATCH}-proposals.json").read_text())
    proposals = frozen["proposals"]

    renames_path = ROOT / "verification/key-renames.json"
    renames = [r for r in json.loads(renames_path.read_text()) if r.get("commit") != BATCH]
    for p in proposals:
        if p["kind"] == "replace":
            renames.append({"old_key": p["key"], "new_key": p["new_key"], "date": DATE, "kind": "replacement",
                            "reason": f"{BATCH}: {p['reason']}; DOI 10.1037/rev0000015", "commit": BATCH})
        elif p.get("rename"):
            renames.append({"old_key": p["key"], "new_key": p["rename"], "date": DATE,
                            "reason": f"{BATCH}: {p.get('rename_reason') or p['origin']} ({p['origin']})",
                            "commit": BATCH})
    renames_path.write_text(json.dumps(renames, indent=1, ensure_ascii=False) + "\n")

    deletions_path = ROOT / "verification/key-deletions.json"
    deletions = json.loads(deletions_path.read_text()) if deletions_path.exists() else []
    deletions = [d for d in deletions if d.get("batch") != BATCH]
    for p in proposals:
        if p["kind"] == "remove":
            deletions.append({"key": p["key"], "reason": p["reason"], "decision_source": p["decision"], "date": DATE,
                              **({"keeper": p["keeper"]} if p.get("keeper") else {}), "batch": BATCH})
    deletions_path.write_text(json.dumps(deletions, indent=1, ensure_ascii=False) + "\n")

    earlier = json.loads((ROOT / "verification/apply-2026-09-25f/library-changes.json").read_text())
    removed = sorted(set(earlier["removed"]) | {p["key"] for p in proposals if p["kind"] == "remove"})
    (HERE / "library-changes.json").write_text(json.dumps({
        "note": "Keys that left or joined cdl.bib outside key-renames.json, read by "
                ".bibcheck/validate-current-checkpoint.py. removed: user-approved removals (stage 2C's NetwLab25 "
                "plus this batch's, each logged in verification/key-deletions.json); added: entries added by merged "
                "pull requests (unchanged from ../apply-2026-09-25f/library-changes.json). Replacements and renames "
                "are in key-renames.json.",
        "removed": removed, "added": earlier["added"],
        "last_staged": f".bibcheck/{HERE.name}/{BATCH}-staged.bib"}, indent=1, ensure_ascii=False) + "\n")
    print(f"{sum(r.get('commit') == BATCH for r in renames)} renames/replacements logged; "
          f"{sum(d['batch'] == BATCH for d in deletions if 'batch' in d)} deletions logged; {len(removed)} removed in total")


if __name__ == "__main__":
    main()
