"""signoff001: record the user's research-pilot verdicts (2026-09-25) as named-human approvals.

User decision ("Sign-off of pilot verdicts", ../resolution-plan-2026-09-22/README.md): the
research-pilot entries the user marked Correct, or marked wrong with a fix the user specified
(applied in pilot001), that no automated source verifies are recorded with
``bibcheck.py crossref approve``, reviewer Jeremy Manning, bound to each entry's current
fingerprint. PR #87/#88 entries are excluded (not reviewed by the user), and so are keys
outside the two lists below (Beaz96, RamaEtal12b, SommEtal12, NetwLab25).

Only entries whose current status is needs_review are approved. Each approval goes through
the CLI (the production path). Afterwards verification/baseline.jsonl.gz and
verification/review-queue.jsonl.gz are exported.

    .venv/bin/python verification/apply-2026-09-29/signoff.py [--apply]
"""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("apply0929", HERE / "apply.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)  # chdir(ROOT), sys.path
base = mod.base

from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries  # noqa: E402

CORRECT = ("AndeEtal66 Arch11a Bart32 BiddMarl87 CalvEtal97 Curr04 EichMaca06 Gaut08 GelmEtal13 HowaEtal08b "
           "Hume07 KahaEtal24 Kais90 LeVaEtal10 LegeEtal69 McCrGrac07 NastEtal20 NilsEtal75 Pach74 PhelEtal18 "
           "PiefEtal03 RaypWall67 RosePaul90 RovaVirs79 SchwHump73 Shan20 SilbEtal01 Unde48a Weiz66 Youn61 "
           "ZrenEtal11").split()
FIXED = ("BiswEtal95 HogeEtal99 PuceEtal99 LiEtal19 ParaEtal04 vanEEtal18 KahaMill13 ZimaEtal23 AndeEtal66 "
         "MikoEtal13b XiaoEtal10 ScotEtal07 Hook69 Jame90 Mink15 Palm78").split()
PILOT_KEY = {"KahaEtal24": "KahaEtal22", "Mink15": "Mink07"}   # key on the pilot page
PILOT = "verification/research-pilot-2026-09-24"
APPLIED = "verification/apply-2026-09-28/pilot001-proposals.json"
REVIEWER = "Jeremy Manning"


def evidence(key):
    """The first source URL behind the entry's current text, and the evidence files."""
    old = PILOT_KEY.get(key, key)
    applied = {p["key"]: p for p in json.loads((ROOT / APPLIED).read_text())["proposals"]}
    pilot = {p["key"]: p for p in json.loads((ROOT / PILOT / "pilot-proposals.json").read_text())}
    follow = {r["key"]: r for r in json.loads((ROOT / PILOT / "followup.json").read_text())}
    fixed = key in FIXED
    files = [f"{PILOT}/{'followup.json' if fixed and old in follow else 'pilot-proposals.json'}"]
    urls = []
    rows = [applied.get(old), follow.get(old) if fixed else None, pilot.get(old)]
    for row in rows:
        for change in ((row or {}).get("changes") or {}).values():
            for ev in change.get("evidence", []) if isinstance(change, dict) else []:
                if ev.get("url"):
                    urls.append(ev["url"])
    if old in applied:
        files.append(APPLIED)
    return (urls[0] if urls else None), files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    keys = sorted(set(CORRECT) | set(FIXED))
    assert len(keys) == 46, len(keys)
    entries = load_entries(base.BIB)
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        results = current_results(base.BIB, cache, {k: entries[k] for k in keys})
    finally:
        cache.close()
    plan, skipped = [], {}
    for key in keys:
        status = results[key]["status"]
        if status != "needs_review":
            skipped[key] = status
            continue
        url, files = evidence(key)
        # Corrected 2026-09-29 (attribution audit): the notes this script wrote said the fix as applied
        # was "user-approved" and that Palm78's "resolution is to keep the entry unchanged". Neither was
        # the user's; those twelve approvals were revoked (verification/revocations.jsonl).
        verdict = ("marked wrong on the research-pilot page with a fix the user requested; the user did not see "
                   "the fix as applied (pilot001, commit 689de07)" if key in FIXED
                   else "marked Correct on the research-pilot page")
        if key == "Palm78":
            verdict = ("marked wrong on the research-pilot page with the note 'again, add DOI'; keeping the "
                       "entry unchanged (no DOI for the cited 1978 Erlbaum edition) was Claude's choice")
        if key in FIXED and key in CORRECT:
            verdict = "marked Correct with a user correction (number 3--4) on the research-pilot page, applied in pilot001"
        if key in PILOT_KEY:
            verdict += f" (pilot key {PILOT_KEY[key]}, renamed per the key rule)"
        note = (f"Research-pilot verdict by Jeremy Manning, 2026-09-25: {verdict}. Approval bound to the entry's "
                f"current text. Evidence: {', '.join(files)}. No automated route verifies it "
                f"(closest-source issue: {'; '.join(results[key].get('issues', [])[:1]) or 'none recorded'}).")
        source = url or f"research-pilot review page ({PILOT}/review.html) and {files[0]}"
        plan.append({"key": key, "fingerprint": entries[key]["fingerprint"], "reviewer": REVIEWER,
                     "source": source, "note": note})
    out = {"batch": "signoff001", "approvals": plan, "not_needs_review": skipped}
    (HERE / "signoff001-plan.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(plan)} to approve; already accepted/other: {skipped}")
    if not args.apply:
        return
    for row in plan:
        subprocess.run([sys.executable, "bibcheck.py", "crossref", "approve", row["key"],
                        "--fingerprint", row["fingerprint"], "--reviewer", row["reviewer"],
                        "--source", row["source"], "--note", row["note"]], check=True)
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        after = current_results(base.BIB, cache)
        assert all(after[r["key"]]["status"] == "human_verified" for r in plan)
        export_snapshot(base.BIB, cache, ROOT / "verification/baseline.jsonl.gz")
        base.export_queue(after)
    finally:
        cache.close()
    (HERE / "signoff001-results.json").write_text(json.dumps(
        {"approved": [r["key"] for r in plan],
         "statuses": {k: after[k]["status"] for k in keys}}, indent=1) + "\n")
    print("PASS: approvals recorded; baseline and review queue exported")


if __name__ == "__main__":
    main()
