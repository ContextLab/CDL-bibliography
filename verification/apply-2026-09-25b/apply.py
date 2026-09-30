"""Stage 2A batches (2026-09-25): reassess002 and classes001.

Same discipline as ../apply-2026-09-23/apply.py (whose helpers this reuses) and
../apply-2026-09-25/apply.py: frozen proposals (or keys) with fingerprints, a
staging copy whose diff is limited to the batch, helpers.check_bib, backup +
snapshot under .bibcheck/apply-2026-09-25b/, apply, the production pipeline for
the batch keys, a repeat that must make zero requests and zero review writes,
no change to any accepted result outside the batch, then
verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz.

Batches:

  reassess002  No BibTeX edit. Every needs_review entry goes through the production
               ``verify --auto-review`` path (bibcheck/verification_cli.py): verify
               (recheck of saved approvals), the auto-review, full-text, PMC,
               publisher-year, catalogue, preprint and arXiv layers, then the four
               2026-09-25 routes (OSF, DataCite, ACL Anthology, SfN), under resolver 30.
               A final recheck adds the bookkeeping fields so the repeat writes nothing.
  classes001   The user-approved correction classes, restricted to regenerated
               proposals (proposals.json, catalogue-proposals.json in this folder)
               whose changes are identical to the approved and spot-checked
               fixes-2026-09-24 / catalogue-phase0-2026-09-22 versions; plus the two
               held year fixes with their key renames (GautEtal18 -> GautEtal19,
               HayeEtal14 -> HayeEtal16; user decision 2026-09-24 23:35 EDT). Built by
               select_classes.py into classes001-proposals.json.

    .venv/bin/python verification/apply-2026-09-25b/apply.py BATCH [--apply]
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
_spec = importlib.util.spec_from_file_location("apply0923", ROOT / "verification/apply-2026-09-23/apply.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)  # chdir(ROOT), sys.path, imports, route modules
base.HERE = HERE
base.WORK = WORK = ROOT / ".bibcheck" / HERE.name

from verification import (ACCEPTED, Cache, current_results, export_snapshot, load_entries,  # noqa: E402
                          run_lock, run_verification)
from auto_review import run_auto_review  # noqa: E402
from fulltext_review import run_fulltext_review  # noqa: E402
from pmc_metadata import run_pmc_metadata_review  # noqa: E402
from publisher_year_review import run_publisher_year_review  # noqa: E402
from catalogue_review import run_catalogue_review  # noqa: E402
from preprint_review import run_preprint_review  # noqa: E402
from arxiv_review import run_arxiv_review  # noqa: E402

BIB = base.BIB
# Batch names this runner accepts; ../apply-2026-09-25c/apply.py reuses main() for held001.
BATCHES = ("reassess002", "classes001")


def patient(route, attempts=6, wait=60):
    """Re-run a route after an HTTP 429 (e.g. OpenAlex: "Anonymous search is temporarily
    rate-limited ... retry in 38s"). Routes save each document as it arrives, so a re-run
    resumes; any other provider error still stops the batch."""
    from verification import ProviderError

    def run(*args, **kwargs):
        for attempt in range(attempts):
            try:
                return route(*args, **kwargs)
            except ProviderError as exc:
                if "HTTP 429" not in str(exc) or attempt == attempts - 1:
                    raise
                print(f"{route.__name__}: {exc}; retrying in {wait}s", flush=True)
                time.sleep(wait)
    run.__name__ = route.__name__
    return run


base.ROUTES = tuple(patient(route) for route in base.ROUTES)


def cli_pipeline(cache, client, keys, report):
    """bibcheck.py crossref verify --auto-review --keys KEYS (the CLI default, no --recheck-cached).

    A --recheck-cached pass is deliberately not run: verify_entry's recheck re-derives a
    saved approval from Crossref evidence only and reopens the 2026-09-25 route approvals
    (FranLiu18, osf-repository), which the OSF route then re-approves on every run, so the
    pipeline never reaches a fixed point (first reassess002 attempt: repeat added 2 rows)."""
    keys = sorted(keys)
    run_verification(BIB, cache, client, report, keys=keys)
    run_auto_review(BIB, cache, report, client, keys=keys)
    for layer in (run_fulltext_review, run_pmc_metadata_review, run_publisher_year_review,
                  run_catalogue_review, run_preprint_review, run_arxiv_review, *base.ROUTES):
        layer(BIB, cache, client, report, keys=keys)
    return current_results(BIB, cache)


# ------------------------------------------------------------ renames --

KEY_RE = re.compile(r"^(@[A-Za-z]+\s*\{)([^,\s]+)(\s*,)")


def rename_key(raw, old, new):
    match = KEY_RE.match(raw)
    if not match or match[2] != old:
        raise ValueError(f"entry does not start with key {old}")
    return match[1] + new + raw[match.end(2):]


def stage_classes(batch, entries, proposals):
    """Staging for an edit batch that may rename keys (only those listed in ``rename``)."""
    text = Path(BIB).read_text()
    modified = text
    renames = {p["key"]: p["rename"] for p in proposals if p.get("rename")}
    for old, new in renames.items():
        assert new not in entries, f"new key {new} already in cdl.bib"
        assert not re.search(r"\b" + re.escape(new) + r"\b", text), f"{new} occurs in cdl.bib"
    for p in proposals:
        entry = entries[p["key"]]
        assert entry["fingerprint"] == p["fingerprint"], f"stale proposal {p['key']}"
        raw = entry["raw"]
        assert modified.count(raw) == 1, f"raw entry not unique {p['key']}"
        new = raw
        for field, change in p["changes"].items():
            new = base.apply_change(new, field, change)
        if p.get("rename"):
            new = rename_key(new, p["key"], p["rename"])
        modified = modified.replace(raw, new, 1)
    staging = WORK / f"{batch}-staged.bib"
    staging.write_text(modified)
    staged = load_entries(staging)
    expected_keys = [renames.get(k, k) for k in entries]
    assert list(staged) == expected_keys, "cite keys or order changed beyond the approved renames"
    by_key = {p["key"]: p for p in proposals}
    for key, entry in entries.items():
        new_key = renames.get(key, key)
        if key not in by_key:
            assert staged[new_key] == entry, key
            continue
        expected = dict(entry["fields"])
        for field, change in by_key[key]["changes"].items():
            if change["after"] is None:
                expected.pop(field)
            else:
                expected[field] = change["after"]
        expected["ID"] = new_key
        assert staged[new_key]["fields"] == expected, key
        assert staged[new_key]["fingerprint"] != entry["fingerprint"], key
    # Byte-level: everything outside the edited entries is identical.
    delta = 0
    for p in proposals:
        raw = entries[p["key"]]["raw"]
        new = base.apply_change_all(raw, p)
        if p.get("rename"):
            new = rename_key(new, p["key"], p["rename"])
        delta += len(new) - len(raw)
    assert len(modified) - len(text) == delta
    from helpers import check_bib
    errors, _ = check_bib(str(staging), verbose=False)
    assert not errors, errors
    print(f"PASS: {len(proposals)} {batch} edits staged ({len(renames)} key renames: {renames}); all other "
          f"entries and cite keys unchanged; check_bib clean", flush=True)
    return text, modified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", choices=BATCHES)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    batch = args.batch
    edit = batch != "reassess002"
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
        elif edit:
            raise SystemExit(f"STOP: {proposals_path.name} is built by select_classes.py")
        else:
            keys = sorted(k for k, r in before.items() if r["status"] == "needs_review")
            frozen = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "batch": batch, "count": 0,
                      "proposals": [], "skipped": {},
                      "keys": [{"key": k, "fingerprint": entries[k]["fingerprint"],
                                "status_before": before[k]["status"]} for k in keys]}
            proposals_path.write_text(json.dumps(frozen, indent=1, ensure_ascii=False) + "\n")
        proposals = frozen["proposals"]
        renames = {p["key"]: p["rename"] for p in proposals if p.get("rename")}
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
            text, modified = stage_classes(batch, entries, proposals)
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
        # Renamed entries are compared under their new key.
        before = {renames.get(k, k): r for k, r in before.items()}
        keys = {renames.get(k, k) for k in keys}
        client = base.client_for(cache)
        run = cli_pipeline if batch == "reassess002" else base.pipeline
        stages = []
        for cycle in ("run", "repeat"):
            start, calls, count = time.monotonic(), client.requests, base.review_count(cache)
            after = run(cache, client, keys, report)
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
            print(json.dumps({k: (v if not isinstance(v, list) or len(v) < 60 else f"{len(v)} keys") for k, v in stage.items()}), flush=True)
            if cycle == "repeat":
                assert after == first, "repeat changed results"
                assert stage["network_requests"] == stage["added_review_records"] == 0, stage
            first = after
            stages.append(stage)
            shown = keys if edit else set(stage["batch_newly_verified"])
            (HERE / f"{batch}-results.json").write_text(json.dumps({
                "stages": stages,
                "entries": {k: {"status_before": before[k]["status"], "status": after[k]["status"],
                                "fingerprint_before": before[k]["fingerprint"], "fingerprint": after[k]["fingerprint"],
                                "accepted_doi": after[k].get("accepted_doi"),
                                "accepted_source": after[k].get("accepted_source"),
                                "issues": after[k].get("issues", [])[:3]}
                            for k in sorted(shown | set(stages[0]["newly_verified_outside_batch"]))}},
                indent=1, ensure_ascii=False) + "\n")
        export_snapshot(BIB, cache, ROOT / "verification/baseline.jsonl.gz")
        base.export_queue(after)
        print("PASS: production verification complete; repeat made zero requests and zero review writes; "
              "accepted results outside the batch unchanged", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
