"""Stage 1 batches after the 2026-09-24/25 spot-check decisions.

Same discipline as ../apply-2026-09-23/apply.py (whose helpers this reuses):
frozen proposals with fingerprints, a staging copy whose diff is limited to the
batch (cite keys and order kept), helpers.check_bib, backup + snapshot, apply,
the production verification pipeline for the batch keys, a repeat that must
make zero requests and zero review writes, and no change to any accepted result
outside the batch. Then verification/baseline.jsonl.gz and
verification/review-queue.jsonl.gz are exported.

Batches:

  revert-kounios     MeyeEtal88: put back "J Kounios". risky001 applied Crossref's
                     "Kounois"; five other cdl.bib entries spell J Kounios and none
                     spells Kounois (rule Claude adopted 2026-09-24, awaiting user confirmation).
  suffix-reassess    No BibTeX edit. The entries the comparator newly verifies now
                     that it ignores name suffixes (Jr, Sr, II, III, IV) on both
                     sides: BrodMurd77, CalvEtal73, RoedKarp06a, RoedKarp06b and any
                     other held entry measure.py attributes to that rule
                     (suffix-reassess-keys.json).
  publisher-variants No BibTeX edit. The entries that the same-firm catalogue
                     publisher rule newly verifies (keys frozen from an offline
                     measurement, publisher-variants-keys.json).

    .venv/bin/python verification/apply-2026-09-25/apply.py BATCH [--apply]
"""
from collections import Counter
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("apply0923", ROOT / "verification/apply-2026-09-23/apply.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)  # chdir(ROOT), sys.path, imports
base.HERE = HERE
base.WORK = WORK = ROOT / ".bibcheck" / HERE.name

from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock  # noqa: E402

BIB = base.BIB
KOUNIOS_BEFORE = "D E Meyer and D E Irwin and A M Osman and J Kounois"
KOUNIOS_AFTER = "D E Meyer and D E Irwin and A M Osman and J Kounios"
SUFFIX_KEYS = ["BrodMurd77", "CalvEtal73", "RoedKarp06a", "RoedKarp06b"]


def propose_kounios(entries, results):
    entry = entries["MeyeEtal88"]
    if entry["fields"].get("author") != KOUNIOS_BEFORE:
        raise SystemExit(f"STOP: MeyeEtal88 author is {entry['fields'].get('author')!r}")
    consensus = sorted(k for k, e in entries.items() if k != "MeyeEtal88"
                       and "Kounios" in (e["fields"].get("author") or ""))
    rivals = sorted(k for k, e in entries.items() if k != "MeyeEtal88"
                    and "Kounois" in (e["fields"].get("author") or ""))
    if len(consensus) < 1 or rivals:
        raise SystemExit(f"STOP: library consensus changed: {consensus} / {rivals}")
    return [{"key": "MeyeEtal88", "fingerprint": entry["fingerprint"], "kind": "revert_surname",
             "rule": "user-2026-09-25-revert-kounois", "status_before": results["MeyeEtal88"]["status"],
             "library_consensus": consensus,
             "changes": {"author": {"before": KOUNIOS_BEFORE, "after": KOUNIOS_AFTER}}}], {}


EDIT = {"revert-kounios": propose_kounios}


def noedit_keys(batch):
    """Keys frozen by the offline measurement (measure.py) for the rule."""
    keys = json.loads((HERE / f"{batch}-keys.json").read_text())["keys"]
    if batch == "suffix-reassess":
        assert set(SUFFIX_KEYS) <= set(keys), "the four spot-check keys must be newly verified offline"
    return keys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", choices=[*EDIT, "suffix-reassess", "publisher-variants"])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    batch, edit = args.batch, args.batch in EDIT
    WORK.mkdir(parents=True, exist_ok=True)
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    report = WORK / f"{batch}-report.jsonl"
    try:
        entries = load_entries(BIB)
        backup = WORK / f"before-{batch}.bib"
        resuming = backup.exists()
        proposals_path = HERE / f"{batch}-proposals.json"
        if resuming:
            with gzip.open(WORK / f"before-{batch}.jsonl.gz", "rt") as f:
                before = {r["key"]: r for r in map(json.loads, f) if "key" in r}
        else:
            before = current_results(BIB, cache, entries)
        if proposals_path.exists():
            frozen = json.loads(proposals_path.read_text())
        else:
            if edit:
                proposals, skipped = EDIT[batch](entries, before)
                frozen = {"batch": batch, "proposals": proposals, "skipped": skipped}
            else:
                keys = noedit_keys(batch)
                frozen = {"batch": batch, "proposals": [], "skipped": {},
                          "keys": [{"key": k, "fingerprint": entries[k]["fingerprint"],
                                    "status_before": before[k]["status"]} for k in keys]}
            frozen = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(frozen["proposals"]), **frozen}
            proposals_path.write_text(json.dumps(frozen, indent=1, ensure_ascii=False) + "\n")
        proposals = frozen["proposals"]
        if edit:
            keys = {p["key"] for p in proposals}
            assert len(keys) == len(proposals)
        else:
            keys = {row["key"] for row in frozen["keys"]}
            stale = [row["key"] for row in frozen["keys"] if entries[row["key"]]["fingerprint"] != row["fingerprint"]]
            assert not stale, f"STOP: frozen keys changed: {stale}"
        print(json.dumps({k: v for k, v in frozen.items() if k not in ("proposals", "keys")}), flush=True)
        if edit and not resuming:
            stale = [p["key"] for p in proposals if entries[p["key"]]["fingerprint"] != p["fingerprint"]]
            assert not stale, f"STOP: frozen proposals are stale: {stale}"
            text, modified = base.stage_batch(batch, entries, before, proposals)
        if not args.apply:
            return
        with run_lock(cache):
            if resuming:
                if edit:
                    assert Path(BIB).read_bytes() == (WORK / f"{batch}-staged.bib").read_bytes()
            else:
                export_snapshot(BIB, cache, WORK / f"before-{batch}.jsonl.gz")
                shutil.copyfile(BIB, backup)
                if edit:
                    assert Path(BIB).read_text() == text
                    Path(BIB).write_text(modified)
        client = base.client_for(cache)
        stages = []
        for cycle in ("run", "repeat"):
            start, calls, count = time.monotonic(), client.requests, base.review_count(cache)
            after = base.pipeline(cache, client, keys, report)
            changed_accepted = [k for k, r in before.items()
                                if r["status"] in ACCEPTED and k not in keys and after[k] != r]
            assert not changed_accepted, changed_accepted[:20]
            newly = sorted(k for k in after if k not in keys and before[k]["status"] not in ACCEPTED
                           and after[k]["status"] in ACCEPTED)
            lost = sorted(k for k in after if before[k]["status"] in ACCEPTED and after[k]["status"] not in ACCEPTED)
            stage = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                     "network_requests": client.requests - calls,
                     "added_review_records": base.review_count(cache) - count,
                     "batch_statuses_before": dict(Counter(before[k]["status"] for k in keys)),
                     "batch_statuses_after": dict(Counter(after[k]["status"] for k in keys)),
                     "batch_verified_before_and_after": sum(before[k]["status"] in ACCEPTED and after[k]["status"] in ACCEPTED for k in keys),
                     "batch_newly_verified": sorted(k for k in keys if before[k]["status"] not in ACCEPTED and after[k]["status"] in ACCEPTED),
                     "previously_accepted_now_unresolved": lost,
                     "newly_verified_outside_batch": newly,
                     "library_statuses_before": dict(Counter(r["status"] for r in before.values())),
                     "library_statuses": dict(Counter(r["status"] for r in after.values()))}
            print(json.dumps({k: (v if not isinstance(v, list) or len(v) < 30 else f"{len(v)} keys") for k, v in stage.items()}), flush=True)
            if cycle == "repeat":
                assert after == first, "repeat changed results"
                assert stage["network_requests"] == stage["added_review_records"] == 0, stage
            first = after
            stages.append(stage)
            (HERE / f"{batch}-results.json").write_text(json.dumps({
                "stages": stages,
                "entries": {k: {"status_before": before[k]["status"], "status": after[k]["status"],
                                "fingerprint_before": before[k]["fingerprint"], "fingerprint": after[k]["fingerprint"],
                                "accepted_doi": after[k].get("accepted_doi"),
                                "accepted_source": after[k].get("accepted_source"),
                                "issues": after[k].get("issues", [])[:3]}
                            for k in sorted(keys | set(stages[0]["newly_verified_outside_batch"]))}},
                indent=1, ensure_ascii=False) + "\n")
        export_snapshot(BIB, cache, ROOT / "verification/baseline.jsonl.gz")
        base.export_queue(after)
        print("PASS: production verification complete; repeat made zero requests and zero review writes; "
              "accepted results outside the batch unchanged", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
