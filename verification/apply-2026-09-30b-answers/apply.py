"""Apply the user's 2026-09-30 review-page answers, sections A, B and D (batch answers0930b).

The page: https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM (source and build script in
verification/2026-09-30-user-review/page/), database collection "review0930". The answer
documents, read with the ArtifactData tool on 2026-09-30, are copied in answers/.
Section C (surnames) is not applied here.

Steps (runner: ../apply-2026-09-30-surnames/apply.py's chain, ../apply-2026-09-25e/apply.py):

1. preconditions: every answer document is the one frozen in answers/, and every entry
   has the fingerprint frozen in answers0930b-batch.json;
2. the key swap the user asked for (note-KahaEtal08b, "change"): the Psychological Review
   reply (doi 10.1037/a0013724, KahaEtal08b) becomes KahaEtal08a and the chapter
   (doi 10.1016/b978-012370509-9.00185-6, KahaEtal08a) becomes KahaEtal08b. Staged in a copy
   first: only the two cite keys change, every field and every content fingerprint is
   unchanged, the order is unchanged, helpers.check_bib is clean. Backup and snapshot under
   .bibcheck/apply-2026-09-30b-answers/. Logged in verification/key-renames.json (three rows
   through a temporary key, so research_route.rename_walk, which follows the log in order,
   maps each work's evidence to its new key) and CronEtal94's deletion gains confirmed_by
   in verification/key-deletions.json;
3. the production pipeline for the batch: the swapped pair, the entries the name-parsing
   fix can touch (parser_scan.py), the 7 entries the user approved and every entry not
   accepted; nothing accepted outside the batch may change;
4. the user's approvals: ``bibcheck.py crossref approve`` for Bart32, KahaEtal24, Mink15,
   Youn61 (section A) and ScotEtal07, KahaMill13, Hook69 (section D) on their current
   fingerprints; then negative controls: replaying each revoked approval is refused and
   every revocation still matches the approval it revoked;
5. a repeat of the pipeline: zero requests, zero review writes, results identical to the
   state after step 4 (the approvals stand);
6. verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz are exported.

    python verification/apply-2026-09-30b-answers/apply.py [--apply]
"""
from collections import Counter
import argparse
from datetime import datetime, timedelta, timezone
import gzip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("apply0925e", ROOT / "verification/apply-2026-09-25e/apply.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)  # chdir(ROOT), sys.path, patient routes
base = runner.base
WORK = ROOT / ".bibcheck" / HERE.name
base.HERE = runner.HERE = runner.runner.HERE = HERE
base.WORK = runner.WORK = runner.runner.WORK = WORK

from verification import (ACCEPTED, Cache, current_results, export_snapshot, load_entries,  # noqa: E402
                          read_revocation_ledger, revocation_matches, run_lock)
import research_route  # noqa: E402,F401  (registers the research approval validator)
from helpers import check_bib  # noqa: E402

BIB = base.BIB
PAGE = "https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM"
COLLECTION = "review0930"
REVIEWER = "Jeremy Manning"
FROZEN = json.loads((HERE / "answers0930b-batch.json").read_text())
SWAP = {"KahaEtal08a": "KahaEtal08b", "KahaEtal08b": "KahaEtal08a"}
SWAP_TEMP = "KahaEtal08-swap-2026-09-30"
# The user's page requests (research-pilot page) behind the section D items, verbatim.
PILOT_NOTES = {
    "ScotEtal07": "this is a book; shouldn't be a pages field",
    "KahaMill13": "add doi too",
    "Hook69": 'title should be "The posthumous works of Robert Hooke"',
}


def answer(doc):
    return json.loads((HERE / "answers" / f"{doc}.json").read_text())


def edt(utc):
    moment = datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=-4)))
    return moment.strftime("%Y-%m-%d %H:%M:%S EDT")


def approvals():
    out = []
    for key in ("Bart32", "KahaEtal24", "Mink15", "Youn61"):
        doc = f"brace-{key}"
        a = answer(doc)
        assert (a["key"], a["section"], a["choice"]) == (key, "A", "approve"), a
        out.append({"key": key, "doc": doc, "answered": a["updatedAt"],
                    "source": f"review page {PAGE}, collection {COLLECTION}, doc {doc}, answered {a['updatedAt']}",
                    "note": "User approved the post-brace-cleanup text on the 2026-09-30 review page (choice: approve)."})
    for key in ("ScotEtal07", "KahaMill13", "Hook69"):
        doc = f"resolved-{key}"
        a = answer(doc)
        assert (a["key"], a["section"], a["choice"]) == (key, "D", "ok"), a
        out.append({"key": key, "doc": doc, "answered": a["updatedAt"],
                    "source": f"review page {PAGE}, collection {COLLECTION}, doc {doc}, answered {a['updatedAt']}",
                    "note": ("Resolved under the user's 2026-09-30 rule ('if you followed what i asked then mark "
                             f"as resolved'); the user's page request (“{PILOT_NOTES[key]}”) was followed; "
                             "confirmed 'ok' on the 2026-09-30 review page.")})
    return out


def stage_swap(entries, text):
    modified = text
    for old, new in SWAP.items():
        raw = entries[old]["raw"]
        header = raw.split("\n", 1)[0]
        assert header.endswith("{" + old + ","), header
        assert modified.count(header + "\n") == 1, header
        modified = modified.replace(header + "\n", header[: -len(old) - 1] + SWAP_TEMP + old[-1] + ",\n", 1)
    for old, new in SWAP.items():
        modified = modified.replace("{" + SWAP_TEMP + old[-1] + ",\n", "{" + new + ",\n", 1)
    assert SWAP_TEMP not in modified
    staging = WORK / "answers0930b-staged.bib"
    staging.write_text(modified)
    staged = load_entries(staging)
    assert list(staged) == [SWAP.get(k, k) for k in entries], "cite keys or order changed"
    for key, entry in entries.items():
        new = SWAP.get(key, key)
        if key not in SWAP:
            assert staged[key] == entry, key
            continue
        assert staged[new]["fingerprint"] == entry["fingerprint"], (key, "fingerprint is not key-independent")
        assert {k: v for k, v in staged[new]["fields"].items() if k != "ID"} == \
            {k: v for k, v in entry["fields"].items() if k != "ID"}, key
        assert staged[new]["fields"]["ID"] == new
    errors, _ = check_bib(str(staging), verbose=False)
    assert not errors, errors
    print(f"PASS: swap staged ({SWAP}); fields and content fingerprints unchanged; order unchanged; "
          "check_bib clean", flush=True)
    return text, modified


def log_renames_and_deletion():
    a = answer("note-KahaEtal08b")
    assert (a["section"], a["choice"]) == ("B", "change"), a
    decided = (f"user, review page {PAGE}, collection {COLLECTION}, doc note-KahaEtal08b, choice 'change', "
               f"answered {a['updatedAt']} ({edt(a['updatedAt'])})")
    common = {"date": "2026-09-30", "commit": "answers0930b", "user_note": a["note"], "decision_source": decided,
              "swap": "KahaEtal08a <-> KahaEtal08b (keys swapped; logged as three renames through a temporary "
                      "key so that key-renames.json, read in order, maps each work to its new key)"}
    rows = [
        dict(old_key="KahaEtal08a", new_key=SWAP_TEMP,
             reason="key swap, step 1 of 3: the chapter (doi 10.1016/b978-012370509-9.00185-6, 'Associative "
                    "retrieval processes in episodic memory', title kept as printed) leaves KahaEtal08a", **common),
        dict(old_key="KahaEtal08b", new_key="KahaEtal08a",
             reason="key swap, step 2 of 3: the Psychological Review reply (doi 10.1037/a0013724, 'Putting "
                    "short-term memory into context: reply to ...') becomes KahaEtal08a", **common),
        dict(old_key=SWAP_TEMP, new_key="KahaEtal08b",
             reason="key swap, step 3 of 3: the chapter becomes KahaEtal08b", **common),
    ]
    path = ROOT / "verification/key-renames.json"
    log = json.loads(path.read_text())
    if not any(r.get("commit") == "answers0930b" for r in log):
        log += rows
        path.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    c = answer("note-CronEtal94")
    assert (c["key"], c["section"], c["choice"]) == ("CronEtal94", "B", "drop"), c
    path = ROOT / "verification/key-deletions.json"
    deletions = json.loads(path.read_text())
    rows = [r for r in deletions if r["key"] == "CronEtal94"]
    assert len(rows) == 1
    rows[0]["confirmed_by"] = {
        "who": "user (Jeremy Manning)",
        "doc": f"review page {PAGE}, collection {COLLECTION}, doc note-CronEtal94",
        "choice": "drop (option text: 'Confirm the drop')",
        "answered": f"{c['updatedAt']} ({edt(c['updatedAt'])})",
    }
    path.write_text(json.dumps(deletions, indent=1, ensure_ascii=False) + "\n")


def approve(row, fingerprint, expect_ok=True, note=None, source=None, reviewer=REVIEWER):
    cmd = [sys.executable, "bibcheck.py", "crossref", "approve", row["key"], "--fingerprint", fingerprint,
           "--reviewer", reviewer, "--source", source or row["source"], "--note", note or row["note"]]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=dict(os.environ))
    out = (done.stdout + done.stderr).strip()
    assert (done.returncode == 0) == expect_ok, (row["key"], done.returncode, out)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    report = WORK / "answers0930b-report.jsonl"
    try:
        entries = load_entries(BIB)
        backup = WORK / "before-answers0930b.bib"
        resuming = backup.exists()
        original = load_entries(backup) if resuming else entries
        for key, fp in FROZEN["fingerprints"].items():
            assert original[key]["fingerprint"] == fp, f"stale fingerprint {key}"
        for doc, updated in FROZEN["answers"].items():
            assert answer(doc)["updatedAt"] == updated, doc
        rows = approvals()
        text, modified = stage_swap(original, (backup if resuming else Path(BIB)).read_text())
        if resuming:
            with gzip.open(WORK / "before-answers0930b.jsonl.gz", "rt") as f:
                before = {r["key"]: r for r in map(json.loads, f) if "key" in r}
        else:
            before = current_results(BIB, cache, entries)
        print(json.dumps({"statuses": dict(Counter(r["status"] for r in before.values())),
                          "approvals": [r["key"] for r in rows]}), flush=True)
        if not args.apply:
            return
        with run_lock(cache):
            if resuming:
                assert Path(BIB).read_bytes() == (WORK / "answers0930b-staged.bib").read_bytes()
            else:
                export_snapshot(BIB, cache, WORK / "before-answers0930b.jsonl.gz")
                shutil.copyfile(BIB, backup)
                assert Path(BIB).read_text() == text
                Path(BIB).write_text(modified)
        log_renames_and_deletion()
        # compare under the new keys
        before = {SWAP.get(k, k): r for k, r in before.items()}
        keys = (set(SWAP) | set(FROZEN["parser_fix_keys"]) | {r["key"] for r in rows}
                | {k for k, r in before.items() if r["status"] not in ACCEPTED})
        client = base.client_for(cache)
        stages, first = [], None
        for cycle in ("run", "approve", "repeat"):
            start, calls, count = time.monotonic(), client.requests, base.review_count(cache)
            if cycle == "approve":
                entries = load_entries(BIB)
                messages = {}
                for row in rows:
                    held = cache.get(BIB, entries[row["key"]]) or {}
                    if held.get("status") == "human_verified" and held.get("human_review") == {
                            "reviewer": REVIEWER, "source": row["source"], "note": row["note"]}:
                        # resumed run: this exact approval is already the entry's current result
                        messages[row["key"]] = "already recorded (resumed run); not written again"
                        continue
                    messages[row["key"]] = approve(row, entries[row["key"]]["fingerprint"])
                # Negative controls: a revoked approval is never replayed and stays revoked.
                controls = {}
                ledger = read_revocation_ledger()
                for rev in ledger:
                    if rev["key"] not in {r["key"] for r in rows}:
                        continue
                    old = rev["approval"]
                    refused = approve({"key": rev["key"], "source": old["source"], "note": old["note"]},
                                      rev["fingerprint"], expect_ok=False, reviewer=old["reviewer"])
                    old_result = {"status": "human_verified", "human_review": old,
                                  "checked_at": rev["approval_checked_at"]}
                    assert revocation_matches(rev, rev["fingerprint"], old_result), rev["key"]
                    now = cache.get(BIB, entries[rev["key"]])
                    assert now["status"] == "human_verified" and now["human_review"]["source"].startswith(
                        "review page " + PAGE), rev["key"]
                    assert not revocation_matches(rev, entries[rev["key"]]["fingerprint"], now), rev["key"]
                    controls[rev["key"]] = {"revoked_fingerprint": rev["fingerprint"],
                                            "current_fingerprint": entries[rev["key"]]["fingerprint"],
                                            "old_approval_replay": refused,
                                            "revocation_still_matches_old_approval": True,
                                            "revocation_matches_new_approval": False}
                assert set(controls) == {"Mink15", "ScotEtal07", "KahaMill13", "Hook69"}, sorted(controls)
                after = current_results(BIB, cache)
                row = {"cycle": cycle, "network_requests": client.requests - calls,
                       "added_review_records": base.review_count(cache) - count,
                       "approved": {r["key"]: {"status": after[r["key"]]["status"],
                                               "fingerprint": after[r["key"]]["fingerprint"],
                                               "human_review": after[r["key"]]["human_review"],
                                               "cli": messages[r["key"]]} for r in rows},
                       "revocation_controls": controls,
                       "library_statuses": dict(Counter(r["status"] for r in after.values()))}
                assert all(v["status"] == "human_verified" for v in row["approved"].values())
                assert row["added_review_records"] == sum(not m.startswith("already recorded")
                                                          for m in messages.values()), row["added_review_records"]
                print(json.dumps({k: v for k, v in row.items() if k != "approved"}), flush=True)
                stages.append(row)
                first = after
                continue
            after = base.pipeline(cache, client, keys, report)
            assert set(after) == set(before), "library keys differ"
            changed_accepted = [k for k, r in before.items()
                                if r["status"] in ACCEPTED and k not in keys and after[k] != r]
            assert not changed_accepted, changed_accepted[:20]
            lost = sorted(k for k in after if before[k]["status"] in ACCEPTED and after[k]["status"] not in ACCEPTED)
            newly = sorted(k for k in after if before[k]["status"] not in ACCEPTED and after[k]["status"] in ACCEPTED)
            row = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                   "network_requests": client.requests - calls,
                   "added_review_records": base.review_count(cache) - count,
                   "batch": sorted(keys),
                   "batch_statuses_before": dict(Counter(before[k]["status"] for k in keys)),
                   "batch_statuses_after": dict(Counter(after[k]["status"] for k in keys)),
                   "previously_accepted_now_unresolved": lost, "newly_accepted": newly,
                   "swapped": {k: {"status_before": before[k]["status"], "status": after[k]["status"],
                                   "accepted_doi": after[k].get("accepted_doi"),
                                   "accepted_source": after[k].get("accepted_source"),
                                   "fingerprint": after[k]["fingerprint"]} for k in sorted(SWAP)},
                   "library_statuses_before": dict(Counter(r["status"] for r in before.values())),
                   "library_statuses": dict(Counter(r["status"] for r in after.values()))}
            print(json.dumps({k: v for k, v in row.items() if k != "batch"}), flush=True)
            assert not lost, lost
            for k in SWAP:  # verification carries over: the same work, the same accepted record
                assert after[k]["status"] == before[k]["status"] == "metadata_verified", k
                assert after[k]["accepted_doi"] == before[k]["accepted_doi"], k
                assert after[k]["fingerprint"] == before[k]["fingerprint"], k
            if cycle == "repeat":
                assert after == first, "repeat changed results"
                assert row["network_requests"] == row["added_review_records"] == 0, row
            stages.append(row)
            first = after
            (HERE / "answers0930b-results.json").write_text(json.dumps({
                "stages": stages,
                "entries": {k: {"status_before": before[k]["status"], "status": after[k]["status"],
                                "fingerprint": after[k]["fingerprint"],
                                "accepted_source": after[k].get("accepted_source"),
                                "accepted_doi": after[k].get("accepted_doi"),
                                "issues": after[k].get("issues", [])[:3]} for k in sorted(keys)}},
                indent=1, ensure_ascii=False) + "\n")
        export_snapshot(BIB, cache, ROOT / "verification/baseline.jsonl.gz")
        print(base.export_queue(first), flush=True)
        print("PASS: swap staged and applied; production pipeline for the batch; 7 approvals recorded and "
              "revoked approvals still refused; repeat made zero requests and zero review writes; accepted "
              "results outside the batch unchanged", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
