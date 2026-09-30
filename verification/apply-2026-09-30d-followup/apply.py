"""Apply the user's answers to the three items left by batch surnames0930c (batch followup0930d).

The user's answer (2026-09-30, relayed verbatim by the orchestrating session):
"1. yes / 2. use D'Agata / 3. Re-confirm", to the questions (1) keep WatkPeyn83 as
Peynircio\\u{g}lu (\\dot is math-only; plain i is the dotted i)? (2) use "D'Agata" per the erratum
10.1007/s00426-016-0761-6? (3) re-approve FreuEtal09, whose erratum concerns only a Methods
sentence?

  1. WatkPeyn83: no change (the hold is withdrawn; the entry stays as it is).
  2. LatiEtal10 author 7 "F Dagata" -> "F D'Agata" (staged in a copy, check_bib clean).
  3. FreuEtal09: `crossref approve` (reviewer "Jeremy Manning") on its current fingerprint.

Then the production pipeline for the batch, the approvals (LatiEtal10 only if the pipeline does
not accept it), a negative control, a zero-request repeat and the exports.

    python verification/apply-2026-09-30d-followup/apply.py [--apply]
"""
from collections import Counter
import argparse
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

from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock  # noqa: E402
import research_route  # noqa: E402,F401
from helpers import check_bib  # noqa: E402

BIB = base.BIB
BATCH = "followup0930d"
REVIEWER = "Jeremy Manning"
USER_ANSWER = "1. yes / 2. use D'Agata / 3. Re-confirm"
ANSWER_SOURCE = ("user's answer in the orchestrating session (transcript 0ff7c242), 2026-09-30, relayed verbatim: "
                 f"\"{USER_ANSWER}\"")
ERRATUM = "10.1007/s00426-016-0761-6"
ERRATUM_QUOTE = ("Unfortunately, in the original publication, the name of the seventh author was incorrectly "
                 "published as Federico Dagata. However, the correct name should read as Federico D'Agata.")
FREU_ERRATUM = "10.1001/archneurol.2011.75"
LATI_BEFORE = ("L Latini-Corazzini and M P Nesa and M Ceccaldi and E Guedj and C Thinus-Blanc and F Cauda and "
               "F Dagata and P P{\\'e}ruch")
LATI_AFTER = LATI_BEFORE.replace("F Dagata", "F D'Agata")
APPROVALS = {
    "FreuEtal09": {
        "source": ANSWER_SOURCE + " (item 3, 'Re-confirm')",
        "note": (f"User re-confirmed 2026-09-30; the erratum ({FREU_ERRATUM}) corrects a Methods sentence, not "
                 "the citation."),
    },
    "LatiEtal10": {
        "source": (ANSWER_SOURCE + f" (item 2, 'use D'Agata'); erratum https://doi.org/{ERRATUM} (Crossref title "
                   "'Erratum to: Route and survey processing of topographical memory during navigation', "
                   "update-to 10.1007/s00426-010-0276-5)"),
        "note": (f"User chose D'Agata 2026-09-30 per the published erratum {ERRATUM}: \"{ERRATUM_QUOTE}\" "
                 "(https://link.springer.com/article/10.1007/s00426-016-0761-6); PubMed 20174930: "
                 "\"Dagata, Federico [corrected to D’Agata, Federico]\"."),
    },
}


def approve(key, fingerprint, source, note, expect_ok=True):
    cmd = [sys.executable, "bibcheck.py", "crossref", "approve", key, "--fingerprint", fingerprint,
           "--reviewer", REVIEWER, "--source", source, "--note", note]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=dict(os.environ))
    out = (done.stdout + done.stderr).strip()
    assert (done.returncode == 0) == expect_ok, (key, done.returncode, out)
    return out


def stage(entries, text):
    raw = entries["LatiEtal10"]["raw"]
    assert entries["LatiEtal10"]["fields"]["author"] == LATI_BEFORE
    new = runner.edit_raw(raw, {"key": "LatiEtal10",
                                "changes": {"author": {"before": LATI_BEFORE, "after": LATI_AFTER}}})
    assert text.count(raw) == 1
    modified = text.replace(raw, new, 1)
    staging = WORK / f"{BATCH}-staged.bib"
    staging.write_text(modified)
    staged = load_entries(staging)
    assert list(staged) == list(entries)
    for key, entry in entries.items():
        if key != "LatiEtal10":
            assert staged[key] == entry, key
    assert staged["LatiEtal10"]["fields"] == dict(entries["LatiEtal10"]["fields"], author=LATI_AFTER)
    errors, _ = check_bib(str(staging), verbose=False)
    assert not errors, errors
    print("PASS: LatiEtal10 author 7 staged as F D'Agata; every other entry unchanged; check_bib clean", flush=True)
    return modified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    report = WORK / f"{BATCH}-report.jsonl"
    try:
        backup = WORK / f"before-{BATCH}.bib"
        resuming = backup.exists()
        original = load_entries(backup if resuming else BIB)
        text = (backup if resuming else Path(BIB)).read_text()
        modified = stage(original, text)
        if resuming:
            with gzip.open(WORK / f"before-{BATCH}.jsonl.gz", "rt") as f:
                before = {r["key"]: r for r in map(json.loads, f) if "key" in r}
        else:
            before = current_results(BIB, cache, original)
        assert before["WatkPeyn83"]["status"] in ACCEPTED
        print(json.dumps({"statuses": dict(Counter(r["status"] for r in before.values()))}), flush=True)
        if not args.apply:
            return
        with run_lock(cache):
            if resuming:
                assert Path(BIB).read_bytes() == (WORK / f"{BATCH}-staged.bib").read_bytes()
            else:
                export_snapshot(BIB, cache, WORK / f"before-{BATCH}.jsonl.gz")
                shutil.copyfile(BIB, backup)
                assert Path(BIB).read_text() == text
                Path(BIB).write_text(modified)
        keys = {"LatiEtal10", "FreuEtal09"} | {k for k, r in before.items() if r["status"] not in ACCEPTED}
        client = base.client_for(cache)
        stages, first = [], None
        for cycle in ("run", "approve", "repeat"):
            start, calls, count = time.monotonic(), client.requests, base.review_count(cache)
            if cycle == "approve":
                entries = load_entries(BIB)
                now = current_results(BIB, cache)
                messages = {}
                for key, a in APPROVALS.items():
                    if now[key]["status"] == "metadata_verified":
                        messages[key] = f"verified by the pipeline ({now[key].get('accepted_source')}); no approval"
                        continue
                    hr = now[key].get("human_review") or {}
                    if now[key]["status"] == "human_verified" and hr == {"reviewer": REVIEWER, **a}:
                        messages[key] = "already recorded (resumed run); not written again"
                        continue
                    messages[key] = approve(key, entries[key]["fingerprint"], a["source"], a["note"])
                # Negative control: an approval of LatiEtal10's 'Dagata' text is refused.
                control = approve("LatiEtal10", original["LatiEtal10"]["fingerprint"], "negative control",
                                  "negative control", expect_ok=False)
                assert "Entry changed since review" in control, control
                after = current_results(BIB, cache)
                assert after["WatkPeyn83"] == before["WatkPeyn83"]
                row = {"cycle": cycle, "network_requests": client.requests - calls,
                       "added_review_records": base.review_count(cache) - count,
                       "messages": messages, "stale_fingerprint_control": control,
                       "statuses": {k: after[k]["status"] for k in APPROVALS},
                       "library_statuses": dict(Counter(r["status"] for r in after.values()))}
                assert all(after[k]["status"] in ACCEPTED for k in APPROVALS), row["statuses"]
                print(json.dumps(row, ensure_ascii=False), flush=True)
                stages.append(row)
                first = after
                continue
            after = base.pipeline(cache, client, keys, report)
            assert set(after) == set(before), "library keys differ"
            changed_accepted = [k for k, r in before.items()
                                if r["status"] in ACCEPTED and k not in keys and after[k] != r]
            assert not changed_accepted, changed_accepted[:20]
            row = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                   "network_requests": client.requests - calls,
                   "added_review_records": base.review_count(cache) - count,
                   "batch": sorted(keys),
                   "batch_statuses_after": {k: after[k]["status"] for k in sorted(keys)},
                   "library_statuses_before": dict(Counter(r["status"] for r in before.values())),
                   "library_statuses": dict(Counter(r["status"] for r in after.values()))}
            print(json.dumps(row), flush=True)
            if cycle == "repeat":
                assert after == first, "repeat changed results"
                assert row["network_requests"] == row["added_review_records"] == 0, row
            stages.append(row)
            first = after
            (HERE / f"{BATCH}-results.json").write_text(json.dumps({
                "stages": stages,
                "entries": {k: {"status_before": before[k]["status"], "status": after[k]["status"],
                                "fingerprint": after[k]["fingerprint"],
                                "accepted_source": after[k].get("accepted_source"),
                                "human_review": after[k].get("human_review"),
                                "issues": after[k].get("issues", [])[:3]}
                            for k in sorted(keys | {"WatkPeyn83"})}}, indent=1, ensure_ascii=False) + "\n")
        export_snapshot(BIB, cache, ROOT / "verification/baseline.jsonl.gz")
        print(base.export_queue(first), flush=True)
        print("PASS: LatiEtal10 edited; FreuEtal09 and LatiEtal10 accepted; stale approval refused; WatkPeyn83 "
              "unchanged; repeat made zero requests and zero review writes", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
