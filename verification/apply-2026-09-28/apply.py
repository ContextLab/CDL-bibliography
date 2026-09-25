"""Stage 2C batches (2026-09-28): pilot001 and the PR #87/#88 entry fixes.

Same discipline as ../apply-2026-09-27/apply.py (runner ../apply-2026-09-26/apply.py on
../apply-2026-09-23/apply.py): frozen proposals with fingerprints (<batch>-proposals.json),
a staging copy whose diff is limited to the batch, helpers.check_bib, backup + snapshot
under .bibcheck/apply-2026-09-28/, apply, the production pipeline for the batch keys, a
repeat that must make zero requests and zero review writes, no change to any accepted
result outside the batch, then verification/baseline.jsonl.gz and
verification/review-queue.jsonl.gz.

Additions over the 2026-09-27 runner (each asserted in staging):

  kind "edit"     field changes; ``ENTRYTYPE`` changes rewrite the ``@type{`` prefix;
                  ``rename`` renames the key (logged in verification/key-renames.json).
  kind "replace"  the entry is replaced by ``raw`` under ``new_key`` at the same position
                  (user-approved replacement; logged in key-renames.json as a replacement).
  kind "remove"   the entry is deleted (user-approved removals only).
  ``verify_keys`` extra keys (unchanged entries) that the pipeline verifies with the batch,
                  e.g. every entry a merged pull request added.

    .venv/bin/python verification/apply-2026-09-28/apply.py BATCH [--apply]
"""
from collections import Counter
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import re
import shutil
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("apply0926", ROOT / "verification/apply-2026-09-26/apply.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)  # chdir(ROOT), sys.path, patient routes
base = runner.base
base.HERE = runner.HERE = HERE
base.WORK = runner.WORK = WORK = ROOT / ".bibcheck" / HERE.name

from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock  # noqa: E402

BIB = base.BIB
BATCHES = ("pilot001", "prfix001", "prfix002")
TYPE_RE = re.compile(r"^@([A-Za-z]+)(\s*\{)")


def edit_raw(raw, p):
    changes = dict(p.get("changes", {}))
    etype = changes.pop("ENTRYTYPE", None)
    new = raw
    for field, change in changes.items():
        new = base.apply_change(new, field, change)
    if etype:
        match = TYPE_RE.match(new)
        assert match and match[1].lower() == etype["before"], (p["key"], match and match[1])
        new = "@" + etype["after"] + new[match.end(1):]
    if p.get("rename"):
        new = runner.rename_key(new, p["key"], p["rename"])
    return new


def new_key_of(p):
    return p.get("rename") or p.get("new_key") or p["key"]


def stage(batch, entries, proposals):
    text = Path(BIB).read_text()
    modified = text
    by_key = {p["key"]: p for p in proposals}
    removed = {p["key"] for p in proposals if p["kind"] == "remove"}
    renames = {p["key"]: new_key_of(p) for p in proposals if p["kind"] != "remove" and new_key_of(p) != p["key"]}
    for new in renames.values():
        assert new not in entries, f"new key {new} already in cdl.bib"
        assert not re.search(r"\b" + re.escape(new) + r"\b", text), f"{new} occurs in cdl.bib"
    for p in proposals:
        entry = entries[p["key"]]
        assert entry["fingerprint"] == p["fingerprint"], f"stale proposal {p['key']}"
        raw = entry["raw"]
        assert modified.count(raw) == 1, f"raw entry not unique {p['key']}"
        if p["kind"] == "remove":
            target = raw + "\n\n" if modified.count(raw + "\n\n") == 1 else "\n\n" + raw
            assert modified.count(target) == 1, p["key"]
            modified = modified.replace(target, "", 1)
        elif p["kind"] == "replace":
            modified = modified.replace(raw, p["raw"], 1)
        else:
            modified = modified.replace(raw, edit_raw(raw, p), 1)
    staging = WORK / f"{batch}-staged.bib"
    staging.write_text(modified)
    staged = load_entries(staging)
    expected_keys = [renames.get(k, k) for k in entries if k not in removed]
    assert list(staged) == expected_keys, "cite keys or order changed beyond the approved renames/removals"
    for key, entry in entries.items():
        if key in removed:
            continue
        new_key = renames.get(key, key)
        p = by_key.get(key)
        if p is None:
            assert staged[new_key] == entry, key
            continue
        if p["kind"] == "replace":
            assert staged[new_key]["raw"] == p["raw"], key
            continue
        expected = dict(entry["fields"])
        for field, change in p["changes"].items():
            if change["after"] is None:
                expected.pop(field)
            else:
                expected[field] = change["after"]
        expected["ID"] = new_key
        assert staged[new_key]["fields"] == expected, (key, staged[new_key]["fields"], expected)
        assert staged[new_key]["fingerprint"] != entry["fingerprint"], key
    from helpers import check_bib
    errors, _ = check_bib(str(staging), verbose=False)
    assert not errors, errors
    print(f"PASS: {len(proposals)} {batch} proposals staged ({len(renames)} key renames/replacements: {renames}; "
          f"removed: {sorted(removed)}); all other entries and cite keys unchanged; check_bib clean", flush=True)
    return text, modified, renames, removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", choices=BATCHES)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    batch = args.batch
    WORK.mkdir(parents=True, exist_ok=True)
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    report = WORK / f"{batch}-report.jsonl"
    try:
        entries = load_entries(BIB)
        backup = WORK / f"before-{batch}.bib"
        resuming = backup.exists()
        frozen = json.loads((HERE / f"{batch}-proposals.json").read_text())
        proposals = frozen["proposals"]
        assert len({p["key"] for p in proposals}) == len(proposals)
        if resuming:
            with gzip.open(WORK / f"before-{batch}.jsonl.gz", "rt") as f:
                before = {r["key"]: r for r in map(json.loads, f) if "key" in r}
            original = load_entries(backup)
        else:
            before = current_results(BIB, cache, entries)
            original = entries
        text, modified, renames, removed = stage(batch, original, proposals)
        extra = [row["key"] for row in frozen.get("verify_keys", [])]
        for row in frozen.get("verify_keys", []):
            assert original[row["key"]]["fingerprint"] == row["fingerprint"], f"stale verify key {row['key']}"
        print(json.dumps({k: v for k, v in frozen.items() if k not in ("proposals", "verify_keys")}), flush=True)
        if not args.apply:
            return
        with run_lock(cache):
            if resuming:
                assert Path(BIB).read_bytes() == (WORK / f"{batch}-staged.bib").read_bytes()
            else:
                export_snapshot(BIB, cache, WORK / f"before-{batch}.jsonl.gz")
                shutil.copyfile(BIB, backup)
                assert Path(BIB).read_text() == text
                Path(BIB).write_text(modified)
        # Renamed/replaced entries are compared under their new key; removed ones drop out.
        before = {renames.get(k, k): r for k, r in before.items() if k not in removed}
        keys = {renames.get(p["key"], p["key"]) for p in proposals if p["key"] not in removed} | set(extra)
        client = base.client_for(cache)
        stages = []
        for cycle in ("run", "repeat"):
            start, calls, count = time.monotonic(), client.requests, base.review_count(cache)
            after = base.pipeline(cache, client, keys, report)
            assert set(after) == set(before), "library keys differ from the staged keys"
            changed_accepted = [k for k, r in before.items()
                                if r["status"] in ACCEPTED and k not in keys and after[k] != r]
            assert not changed_accepted, changed_accepted[:20]
            newly = sorted(k for k in after if k not in keys and before[k]["status"] not in ACCEPTED
                           and after[k]["status"] in ACCEPTED)
            lost = sorted(k for k in after if before[k]["status"] in ACCEPTED and after[k]["status"] not in ACCEPTED)
            stage_row = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                         "network_requests": client.requests - calls,
                         "added_review_records": base.review_count(cache) - count,
                         "batch_statuses_before": dict(Counter(before[k]["status"] for k in keys)),
                         "batch_statuses_after": dict(Counter(after[k]["status"] for k in keys)),
                         "batch_verified_before_and_after": sum(before[k]["status"] in ACCEPTED and after[k]["status"] in ACCEPTED for k in keys),
                         "batch_newly_verified": sorted(k for k in keys if before[k]["status"] not in ACCEPTED and after[k]["status"] in ACCEPTED),
                         "previously_accepted_now_unresolved": lost,
                         "newly_verified_outside_batch": newly,
                         "removed": sorted(removed),
                         "library_statuses_before": dict(Counter(r["status"] for r in before.values())),
                         "library_statuses": dict(Counter(r["status"] for r in after.values()))}
            print(json.dumps({k: (v if not isinstance(v, list) or len(v) < 60 else f"{len(v)} keys")
                              for k, v in stage_row.items()}), flush=True)
            if cycle == "repeat":
                assert after == first, "repeat changed results"
                assert stage_row["network_requests"] == stage_row["added_review_records"] == 0, stage_row
            first = after
            stages.append(stage_row)
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
