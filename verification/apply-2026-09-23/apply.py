"""Apply the user-approved 2026-09-23 batches with ordinary production verification.

Batches (run in this order):

  reassess001  No BibTeX edit. Production offline reassessment (``auto-review
               --offline``) of every entry under resolver 28 / catalogue policy 7,
               then ``verify --recheck-cached`` for the stale approvals listed by
               verification/phase0-2026-09-22, followed by the ``--auto-review``
               source layers for those keys. A stale approval that the current
               pipeline rejects is reopened, never kept.
  droppub001   Drop ``publisher`` from every @article (user decision 2026-09-22).
  adddoi001    Add the accepted DOI to entries that are metadata_verified, lack a
               DOI, and whose accepted candidate is the cited work itself.

Edit batches freeze their proposals (key, fingerprint, before/after) in this
folder, stage a copy under .bibcheck/apply-2026-09-23/, assert that only the
batch's fields changed and every cite key is kept, run helpers.check_bib, then
apply and verify the edited fingerprints with the production pipeline:
verify, the --auto-review layers, expanded discovery, and the layers again.
A repeat of the whole pipeline must make zero network requests and add zero
review rows. Every accepted result outside the batch must be unchanged.

    .venv/bin/python verification/apply-2026-09-23/apply.py BATCH [--apply]
"""
from collections import Counter
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import os
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
WORK = ROOT / ".bibcheck" / HERE.name
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import (ACCEPTED, Cache, current_results, export_snapshot, load_entries,  # noqa: E402
                          normalize_doi, run_lock, run_verification, top_level_parts)
from auto_review import run_auto_review  # noqa: E402
from fulltext_review import run_fulltext_review  # noqa: E402
from pmc_metadata import run_pmc_metadata_review  # noqa: E402
from publisher_year_review import run_publisher_year_review  # noqa: E402
from catalogue_review import run_catalogue_review  # noqa: E402
from preprint_review import run_preprint_review  # noqa: E402
from arxiv_review import run_arxiv_review  # noqa: E402
from discovery_review import run_discovery_review  # noqa: E402

BIB = "cdl.bib"
STALE = ["Vand00", "MoruMago49", "Gold95", "HescEtal13b", "McAdMaun99", "GreeStil95", "JoEtal13",
         "VaidEtal02", "PoldEtal99", "DesbEtal04", "YordKole98", "SquiEtal04b"]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def client_for(cache):
    return load_module("earlier_run", ROOT / "verification/resolution-2026-09-15/run.py").client_for(cache)


def export_queue(results):
    sys.path.insert(0, str(ROOT / "verification/completion-2026-09-15"))
    module = load_module("completion_reassess", ROOT / "verification/completion-2026-09-15/reassess.py")
    return module.export_queue(load_entries(BIB), results)


def review_count(cache):
    return cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]


# ---------------------------------------------------------------- edits --

def field_parts(raw):
    prefix = re.match(r"@[A-Za-z]+\s*\{", raw)
    if not prefix or not raw.endswith("}"):
        raise ValueError("Unsupported entry delimiters")
    return prefix, top_level_parts(raw[prefix.end():-1])


def part_name(part):
    match = re.match(r"\s*([A-Za-z][A-Za-z0-9_-]*)\s*=", part)
    return match[1].lower() if match else None


def drop_field(raw, field, before):
    prefix, parts = field_parts(raw)
    matching = [i for i, part in enumerate(parts[1:], 1) if part_name(part) == field]
    if len(matching) != 1:
        raise ValueError(f"{field} is not a unique field")
    i = matching[0]
    value = re.match(r"\s*" + field + r"\s*=\s*\{(.*)\}\s*$", parts[i], re.I | re.S)
    if not value or value[1] != before:
        raise ValueError(f"{field} is not the expected simple braced value")
    del parts[i]
    return raw[:prefix.end()] + ",".join(parts) + "}"


def insert_doi(raw, doi):
    """Insert ``Doi = {..}`` at its alphabetical position (the house formatter's order)."""
    if not re.fullmatch(r"10\.\d{4,9}/[A-Za-z0-9._;()/:<>\[\]+-]+", doi) or doi != doi.lower():
        raise ValueError(f"DOI needs manual formatting: {doi}")
    prefix, parts = field_parts(raw)
    names = [part_name(p) for p in parts[1:]]
    if "doi" in names or None in names:
        raise ValueError("DOI exists or unparsable field")
    position = next((i for i, n in enumerate(names, 1) if n > "doi"), len(parts))
    new = "\n\tDoi = {" + doi + "}"
    if position == len(parts):
        parts.append(new)
    else:
        parts.insert(position, new)
    return raw[:prefix.end()] + ",".join(parts) + "}"


def apply_change(raw, field, change):
    if field == "publisher" and change["after"] is None:
        return drop_field(raw, "publisher", change["before"])
    if field == "doi" and change["before"] is None:
        return insert_doi(raw, change["after"])
    raise ValueError(f"Unsupported change: {field}")


# ---------------------------------------------------------- proposals --

def propose_droppub(entries, results):
    rows = []
    for key, entry in entries.items():
        fields = entry["fields"]
        if fields.get("ENTRYTYPE") == "article" and "publisher" in fields:
            rows.append({"key": key, "fingerprint": entry["fingerprint"], "kind": "drop_publisher",
                         "rule": "P1", "status_before": results[key]["status"],
                         "changes": {"publisher": {"before": fields["publisher"], "after": None}}})
    return rows


def cited_work_doi(entry, result):
    """The accepted DOI, only when it is the cited work's own full-match record.

    Returns (doi, None) or (None, reason). Rejects notices, APA twins or other
    rivals that also fully match, non-journal records for @article, and any
    result whose accepted candidate is not a clean Crossref record of that DOI.
    """
    fields = entry["fields"]
    doi = result.get("accepted_doi")
    if result.get("status") != "metadata_verified" or fields.get("doi") or not doi:
        return None, "not eligible"
    try:
        doi = normalize_doi(doi)
    except ValueError:
        return None, "invalid DOI"
    crossref = [c for c in result.get("candidates", []) if c.get("source") == "crossref" and c.get("doi")]
    own = [c for c in crossref if normalize_doi(c["doi"]) == doi]
    if not own:
        return None, "accepted DOI has no Crossref record in the evidence"
    record = own[0].get("record") or {}
    title = " ".join(record.get("title") or [])
    if re.search(r"\b(erratum|errata|corrigendum|correction|retraction|retracted|expression of concern|withdrawn)\b",
                 title, re.I):
        return None, "accepted record looks like a notice"
    if record.get("relation", {}).get("is-correction-of") or record.get("update-to"):
        return None, "accepted record is an update/notice"
    kind = record.get("type")
    etype = fields.get("ENTRYTYPE")
    allowed = {"article": {"journal-article"}, "incollection": {"book-chapter", "book-section", "book-part"},
               "inbook": {"book-chapter", "book-section", "book-part"},
               "book": {"book", "monograph", "edited-book", "reference-book"},
               "inproceedings": {"proceedings-article"}}
    if kind not in allowed.get(etype, set()):
        return None, f"record type {kind} for @{etype}"
    title_author = [c for c in crossref if normalize_doi(c["doi"]) != doi
                    and c.get("evidence", {}).get("title", {}).get("match")
                    and c.get("evidence", {}).get("author", {}).get("match")]
    if title_author:
        return None, "another DOI also matches title and byline (twin/rival): " + ",".join(
            sorted({normalize_doi(c["doi"]) for c in title_author}))
    return doi, None


def propose_adddoi(entries, results):
    rows, skipped = [], Counter()
    for key, entry in entries.items():
        result = results[key]
        if result["status"] != "metadata_verified" or entry["fields"].get("doi") or not result.get("accepted_doi"):
            continue
        doi, reason = cited_work_doi(entry, result)
        if not doi:
            skipped[reason.split(":")[0]] += 1
            continue
        rows.append({"key": key, "fingerprint": entry["fingerprint"], "kind": "add_doi", "rule": "D1",
                     "accepted_source": result.get("accepted_source"), "status_before": result["status"],
                     "changes": {"doi": {"before": None, "after": doi}}})
    return rows, dict(skipped)


# ----------------------------------------------------------- pipeline --

def pipeline(cache, client, keys, report):
    """The production verify --auto-review sequence, expanded discovery, then the layers again."""
    keys = sorted(keys)
    run_verification(BIB, cache, client, report, keys=keys)
    layers = [
        lambda: run_auto_review(BIB, cache, report, client, keys=keys),
        lambda: run_fulltext_review(BIB, cache, client, report, keys=keys),
        lambda: run_pmc_metadata_review(BIB, cache, client, report, keys=keys),
        lambda: run_publisher_year_review(BIB, cache, client, report, keys=keys),
        lambda: run_catalogue_review(BIB, cache, client, report, keys=keys),
        lambda: run_preprint_review(BIB, cache, client, report, keys=keys),
        lambda: run_arxiv_review(BIB, cache, client, report, keys=keys),
    ]
    for layer in layers:
        layer()
    run_discovery_review(BIB, cache, client, report, limit=len(keys) + 1, keys=keys)
    for layer in layers:
        layer()
    return current_results(BIB, cache)


def reassess_pipeline(cache, client, keys, report):
    """Batch reassess001: production offline reassessment, then stale-approval recheck."""
    run_auto_review(BIB, cache, report, None)  # auto-review --offline, every entry
    run_verification(BIB, cache, client, report, keys=sorted(keys), recheck_cached=True)
    layers = [
        lambda: run_auto_review(BIB, cache, report, client, keys=sorted(keys)),
        lambda: run_fulltext_review(BIB, cache, client, report, keys=sorted(keys)),
        lambda: run_pmc_metadata_review(BIB, cache, client, report, keys=sorted(keys)),
        lambda: run_publisher_year_review(BIB, cache, client, report, keys=sorted(keys)),
    ]
    for layer in layers:
        layer()
    return current_results(BIB, cache)


# --------------------------------------------------------------- main --

def stage_batch(batch, entries, results, proposals):
    text = Path(BIB).read_text()
    modified = text
    keys = {p["key"] for p in proposals}
    for p in proposals:
        entry = entries[p["key"]]
        assert entry["fingerprint"] == p["fingerprint"], f"stale proposal {p['key']}"
        raw = entry["raw"]
        assert modified.count(raw) == 1, f"raw entry not unique {p['key']}"
        new = raw
        for field, change in p["changes"].items():
            new = apply_change(new, field, change)
        modified = modified.replace(raw, new, 1)
    staging = WORK / f"{batch}-staged.bib"
    staging.write_text(modified)
    staged = load_entries(staging)
    assert list(staged) == list(entries), "cite keys or order changed"
    for key, entry in entries.items():
        if key not in keys:
            assert staged[key] == entry, key
            continue
        p = next(p for p in proposals if p["key"] == key)
        expected = dict(entry["fields"])
        for field, change in p["changes"].items():
            if change["after"] is None:
                expected.pop(field)
            else:
                expected[field] = change["after"]
        assert staged[key]["fields"] == expected, key
        assert staged[key]["fingerprint"] != entry["fingerprint"], key
    # Byte-level: everything outside the edited entries is identical.
    assert len(modified) - len(text) == sum(
        len(apply_change_all(entries[p["key"]]["raw"], p)) - len(entries[p["key"]]["raw"]) for p in proposals)
    from helpers import check_bib
    errors, _ = check_bib(str(staging), verbose=False)
    assert not errors, errors
    print(f"PASS: {len(proposals)} {batch} edits staged; all other entries and every cite key unchanged; "
          f"check_bib clean", flush=True)
    return text, modified


def apply_change_all(raw, p):
    for field, change in p["changes"].items():
        raw = apply_change(raw, field, change)
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", choices=["reassess001", "droppub001", "adddoi001"])
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
        proposals_path = HERE / f"{batch}-proposals.json"
        if resuming:
            with gzip.open(WORK / f"before-{batch}.jsonl.gz", "rt") as f:
                before = {r["key"]: r for r in map(json.loads, f) if "key" in r}
            original_entries = load_entries(backup)
        else:
            before = current_results(BIB, cache, entries)
            original_entries = entries
        if batch == "reassess001":
            keys = set(STALE)
            proposals = []
            assert all(before[k]["status"] == "metadata_verified" for k in STALE) or resuming
        else:
            if proposals_path.exists():
                frozen = json.loads(proposals_path.read_text())
                proposals = frozen["proposals"]
            else:
                if batch == "droppub001":
                    proposals, skipped = propose_droppub(entries, before), {}
                else:
                    proposals, skipped = propose_adddoi(entries, before)
                frozen = {"batch": batch, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "count": len(proposals), "status_before": dict(Counter(p["status_before"] for p in proposals)),
                          "skipped": skipped, "proposals": proposals}
                proposals_path.write_text(json.dumps(frozen, indent=1, ensure_ascii=False) + "\n")
            keys = {p["key"] for p in proposals}
            assert len(keys) == len(proposals)
            print(json.dumps({k: v for k, v in frozen.items() if k != "proposals"}), flush=True)
            if not resuming:
                text, modified = stage_batch(batch, entries, before, proposals)
        if not args.apply:
            return
        with run_lock(cache):
            if resuming:
                if batch != "reassess001":
                    assert Path(BIB).read_bytes() == (WORK / f"{batch}-staged.bib").read_bytes()
            else:
                export_snapshot(BIB, cache, WORK / f"before-{batch}.jsonl.gz")
                shutil.copyfile(BIB, backup)
                if batch != "reassess001":
                    assert Path(BIB).read_text() == text
                    Path(BIB).write_text(modified)
        client = client_for(cache)
        stages = []
        for cycle in ("run", "repeat"):
            start, calls, count = time.monotonic(), client.requests, review_count(cache)
            if batch == "reassess001":
                after = reassess_pipeline(cache, client, keys, report)
            else:
                after = pipeline(cache, client, keys, report)
            # Every accepted result outside the batch is unchanged.
            changed_accepted = [k for k, r in before.items()
                                if r["status"] in ACCEPTED and k not in keys and after[k] != r]
            assert not changed_accepted, changed_accepted[:20]
            newly = sorted(k for k in after if k not in keys and before[k]["status"] not in ACCEPTED
                           and after[k]["status"] in ACCEPTED)
            lost = sorted(k for k in after if before[k]["status"] in ACCEPTED and after[k]["status"] not in ACCEPTED)
            stage = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                     "network_requests": client.requests - calls,
                     "added_review_records": review_count(cache) - count,
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
        export_queue(after)
        print("PASS: production verification complete; repeat made zero requests and zero review writes; "
              "accepted results outside the batch unchanged", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
