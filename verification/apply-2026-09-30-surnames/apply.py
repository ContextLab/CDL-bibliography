"""Apply the user's surname rule of 2026-09-30 to the whole library (no cdl.bib edit).

The user's answer to verification/2026-09-29-user-review/CONFIRM.md question 5: "one source
is sufficient; manual entry is the weakest part. notify user if mismatch is found and ask
how they want to resolve it". The checker no longer resolves a surname mismatch on its
own (auto_review.registry_surname_mismatch, correction_proposals.surname_change_hold,
the research post-check); see README.md.

Steps, on the database restored from verification/baseline.jsonl.gz (``bibcheck.py
crossref restore``, run before this script):

1. a library-wide offline evaluation, with no write and no request: every saved result is
   re-derived from its saved evidence exactly as ``crossref verify --recheck-cached`` does
   (``auto_review.reassess``; a route approval its own validator still accepts is kept).
   An entry is affected by the new rule when its status changes, or when a candidate gains
   a "surname mismatch" finding. The status changes must be exactly the approvals made
   through the retired registry-surname-typo rule (listed from the restored baseline).
   Every other difference is recheck bookkeeping (``auto_review`` stamps, ``accepted_doi``
   filled in) that the previous code produces too; it is counted, not written;
2. the batch: the affected entries plus every entry already needs_review; the production
   pipeline for the batch, then a repeat that must make zero requests and zero review
   writes;
3. assertions: no accepted result outside the batch changed; the entries that lost their
   approval are exactly the retired rule's; nothing became newly accepted;
4. verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz are exported.

    python verification/apply-2026-09-30-surnames/apply.py [--apply]
"""
from collections import Counter
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("apply0928", ROOT / "verification/apply-2026-09-25e/apply.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)  # chdir(ROOT), sys.path, patient routes
base = runner.base
WORK = ROOT / ".bibcheck" / HERE.name
base.HERE = runner.HERE = runner.runner.HERE = HERE
base.WORK = runner.WORK = runner.runner.WORK = WORK

from verification import (ACCEPTED, Cache, current_results, export_snapshot, load_entries,  # noqa: E402
                          route_approval_valid, run_lock)
from auto_review import reassess  # noqa: E402
# The CLI registers the research route's approval validator (bibcheck/verification_cli.py);
# without it a recheck would reopen research-evidence approvals.
import research_route  # noqa: E402,F401

BIB = base.BIB
BASELINE = ROOT / "verification/baseline.jsonl.gz"
RETIRED_RULE = "registry-surname-typo"


def retired_rule_keys(snapshot):
    """Accepted entries whose saved evidence resolved a finding by the retired rule."""
    out = set()
    with gzip.open(snapshot, "rt") as f:
        for row in map(json.loads, f):
            if row.get("status") not in ACCEPTED:
                continue
            for c in row.get("candidates") or []:
                if any(isinstance(r, dict) and r.get("rule") == RETIRED_RULE
                       for r in c.get("resolved_findings") or []):
                    out.add(row["key"])
    return out


BOOKKEEPING = {"auto_review", "accepted_doi", "accepted_source", "fingerprint_migration", "path_migration",
               "revoked_approval"}


def mismatch_findings(result):
    return sorted(i for c in result.get("candidates") or [] for i in c.get("issues") or []
                  if isinstance(i, str) and i.startswith("author: surname mismatch"))


def offline_evaluation(results):
    """Re-derive every saved result from its saved evidence (the recheck), in memory."""
    entries = load_entries(BIB)
    affected, drift = {}, Counter()
    for key, saved in results.items():
        if saved["status"] not in ("metadata_verified", "needs_review"):
            continue
        new = reassess(entries[key], saved)
        if saved["status"] == "metadata_verified" and new.get("status") not in ACCEPTED \
                and route_approval_valid(saved):
            continue  # a route approval is kept, as run_verification's recheck does
        old = {k: v for k, v in saved.items() if k not in {"key", "fingerprint", "checked_at", "policy"}}
        if new == old:
            continue
        gained = sorted(set(mismatch_findings(new)) - set(mismatch_findings(old)))
        if new.get("status") != saved["status"] or gained:
            affected[key] = {"status_before": saved["status"], "status": new.get("status"),
                             "mismatch_findings": gained or mismatch_findings(new)}
        else:
            drift[",".join(sorted(k for k in set(new) | set(old) if new.get(k) != old.get(k)))] += 1
    return affected, drift


def summary(results, keys):
    return {k: {"status": results[k]["status"], "fingerprint": results[k]["fingerprint"],
                "accepted_source": results[k].get("accepted_source"),
                "accepted_doi": results[k].get("accepted_doi"),
                "issues": results[k].get("issues", [])[:3]} for k in sorted(keys)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", default=str(ROOT / ".bibcheck/verification.sqlite3"),
                        help="verification database (a copy for a dry run)")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    cache = Cache(Path(args.db))
    report = WORK / "surnames0930-report.jsonl"
    try:
        before = current_results(BIB, cache)
        retired = retired_rule_keys(BASELINE)
        print(json.dumps({"entries": len(before), "statuses": dict(Counter(r["status"] for r in before.values())),
                          "retired_rule_keys": sorted(retired)}), flush=True)
        if not args.apply:
            return
        client = base.client_for(cache)
        with run_lock(cache):
            export_snapshot(BIB, cache, WORK / "before-surnames0930.jsonl.gz")
        # 1. library-wide offline evaluation (no write, no request)
        start, calls, count = time.monotonic(), client.requests, base.review_count(cache)
        affected, drift = offline_evaluation(before)
        status_changed = {k for k, v in affected.items() if v["status"] != v["status_before"]}
        library_pass = {"cycle": "library-offline-evaluation", "seconds": round(time.monotonic() - start, 2),
                        "network_requests": client.requests - calls,
                        "added_review_records": base.review_count(cache) - count,
                        "affected": affected, "status_changed": sorted(status_changed),
                        "recheck_bookkeeping_not_written": dict(drift)}
        assert library_pass["network_requests"] == library_pass["added_review_records"] == 0, library_pass
        assert status_changed == retired, sorted(status_changed ^ retired)
        assert all(v["status"] == "needs_review" for k, v in affected.items() if k in status_changed)
        print(json.dumps({k: v for k, v in library_pass.items() if k != "affected"}), flush=True)
        # 2. the batch, through the production pipeline, then a repeat
        keys = set(affected) | {k for k, r in before.items() if r["status"] not in ACCEPTED}
        stages, first = [library_pass], None
        for cycle in ("run", "repeat"):
            start, calls, count = time.monotonic(), client.requests, base.review_count(cache)
            after = base.pipeline(cache, client, keys, report)
            assert set(after) == set(before), "library keys changed"
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
                   "previously_accepted_now_unresolved": lost,
                   "newly_accepted": newly,
                   "library_statuses_before": dict(Counter(r["status"] for r in before.values())),
                   "library_statuses": dict(Counter(r["status"] for r in after.values()))}
            print(json.dumps(row), flush=True)
            # 3. only the retired rule's approvals are lost; nothing is newly accepted
            assert set(lost) == retired, (sorted(set(lost) ^ retired))
            assert not newly, newly
            if cycle == "repeat":
                assert after == first, "repeat changed results"
                assert row["network_requests"] == row["added_review_records"] == 0, row
            first = after
            stages.append(row)
            (HERE / "surnames0930-results.json").write_text(json.dumps({
                "stages": stages,
                "entries": {k: dict(summary(after, [k])[k], status_before=before[k]["status"])
                            for k in sorted(keys)}}, indent=1, ensure_ascii=False) + "\n")
        # 4. export (the live database only)
        if Path(args.db).resolve() == (ROOT / ".bibcheck/verification.sqlite3").resolve():
            export_snapshot(BIB, cache, BASELINE)
            print(base.export_queue(after), flush=True)
        print("PASS: offline library pass made zero requests; production pipeline for the batch; "
              "repeat made zero requests and zero review writes; accepted results outside the batch "
              "unchanged; only the retired rule's approvals lost", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
