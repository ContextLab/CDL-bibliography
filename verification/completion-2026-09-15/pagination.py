"""Apply frozen, corroborated pagination fixes and reverify their fingerprints."""

from collections import Counter
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from correction_proposals import coordinate_proposal, field_proposal, issue_year_proposal, journal_history_proposal, pagination_proposal, publication_proposal, suffix_proposal, replace_coordinates, replace_field, replace_pagination, replace_publication
from publisher_corrections import publisher_field_proposal
from pmc_corrections import pmc_publisher_proposal, pmc_coordinate_proposal, replace_pmc_coordinates, replace_pmc_given_names
from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock, run_verification

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name
spec = importlib.util.spec_from_file_location("earlier", HERE.parent / "resolution-2026-09-15/run.py")
earlier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(earlier)


def regenerate(entry, previous, proposal):
    kind = proposal["kind"]
    if kind == "pmc_corroborated_publisher":
        return pmc_publisher_proposal(entry, previous)
    if kind == "pmc_corroborated_coordinates":
        return pmc_coordinate_proposal(entry, previous)
    if kind == "pmc_corroborated_given_names":
        return pmc_coordinate_proposal(entry, previous, include_authors=True)
    if kind.startswith("publisher_corroborated_"):
        return publisher_field_proposal(entry, previous, proposal["publisher_source"], next(iter(proposal["changes"])))
    if kind == "corroborated_pubmed_suffix":
        return suffix_proposal(entry, previous)
    if kind == "corroborated_issue_year":
        return issue_year_proposal(entry, previous)
    if kind == "documented_journal_history":
        return journal_history_proposal(entry, previous)
    if kind in {"corroborated_publication", "corroborated_combined"}:
        return publication_proposal(entry, previous, include_identity_fields=kind == "corroborated_combined")
    if kind == "corroborated_coordinates":
        return coordinate_proposal(entry, previous)
    if kind == "corroborated_pagination":
        return pagination_proposal(entry, previous)
    return field_proposal(entry, previous, next(iter(proposal["changes"])))


def replace_proposal(text, entry, proposal):
    kind = proposal["kind"]
    if kind == "pmc_corroborated_coordinates":
        return replace_pmc_coordinates(text, entry, proposal)
    if kind == "pmc_corroborated_given_names":
        return replace_pmc_given_names(text, entry, proposal)
    if kind in {"corroborated_publication", "corroborated_combined"}:
        return replace_publication(text, entry, proposal)
    if kind == "corroborated_coordinates":
        return replace_coordinates(text, entry, proposal)
    if kind == "corroborated_pagination":
        return replace_pagination(text, {entry["key"]: entry}, [proposal])
    return replace_field(text, entry, proposal)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", choices=["pagination", "field", "doi", "author", "journal", "coordinates", "publisher-title", "publisher-xml", "publication", "combined", "afterunicode", "postaliases", "suffix", "postsuffix", "jep", "suffixperiod", "suffixboth", "postcommentary", "issueyear", "pmccoordinates", "pmcgivennames", "pmccoordinates005", "pmcgivennames005", "frontierslocators", "pmcpublishers", "postdiscovery004", "postdiscovery005", "pdfbyline001", "postdiscovery006", "postsecondary006", "postdiscovery007"], default="pagination")
    batch = parser.parse_args().batch
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    proposals = json.loads((HERE / f"{batch}-proposals.json").read_text())
    keys = {p["key"] for p in proposals}
    assert len(keys) == len(proposals)
    try:
        with run_lock(cache):
            entries = load_entries("cdl.bib")
            before = current_results("cdl.bib", cache, entries)
            backup = WORK / f"before-{batch}.bib"
            if not backup.exists():
                for p in proposals:
                    proposed = regenerate(entries[p["key"]], before[p["key"]], p)
                    assert proposed == p, p["key"]
                text = Path("cdl.bib").read_text()
                modified = text
                for p in proposals:
                    modified = replace_proposal(modified, entries[p["key"]], p)
                staging = WORK / f"{batch}-staged.bib"
                staging.write_text(modified)
                staged = load_entries(staging)
                assert set(staged) == set(entries)
                for key, old in entries.items():
                    if key not in keys:
                        assert old == staged[key], key
                    else:
                        changes = next(p["changes"] for p in proposals if p["key"] == key)
                        assert staged[key]["fields"] == dict(old["fields"], **{f: c["after"] for f, c in changes.items()}), key
                        assert staged[key]["fingerprint"] != old["fingerprint"], key
                export_snapshot("cdl.bib", cache, WORK / f"before-{batch}.jsonl.gz")
                backup.write_text(text)
                Path("cdl.bib").write_text(modified)
                print(f"Applied {len(keys)} {batch} corrections; every other raw entry unchanged", flush=True)
            else:
                for p in proposals:
                    for field, change in p["changes"].items():
                        assert entries[p["key"]]["fields"][field] == change["after"]
                with gzip.open(WORK / f"before-{batch}.jsonl.gz", "rt") as f:
                    before = {r["key"]: r for r in map(json.loads, f) if "key" in r}
        client = earlier.client_for(cache)
        stages = []
        for cycle in ("run", "repeat"):
            start, calls = time.monotonic(), client.requests
            count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
            after = run_verification("cdl.bib", cache, client, WORK / f"{batch}-report.jsonl", keys=keys)
            if any(p["kind"] in {"corroborated_pubmed_suffix", "corroborated_issue_year", "pmc_corroborated_coordinates", "pmc_corroborated_given_names", "pmc_corroborated_publisher"} for p in proposals):
                from auto_review import run_auto_review
                after = run_auto_review("cdl.bib", cache, WORK / f"{batch}-report.jsonl", client, keys=keys)
            if any(p["kind"] in {"pmc_corroborated_coordinates", "pmc_corroborated_given_names", "pmc_corroborated_publisher"} for p in proposals):
                from fulltext_review import run_fulltext_review
                from pmc_metadata import run_pmc_metadata_review
                after = run_fulltext_review("cdl.bib", cache, client, WORK / f"{batch}-report.jsonl", keys=keys)
                after = run_pmc_metadata_review("cdl.bib", cache, client, WORK / f"{batch}-report.jsonl", keys=keys)
            assert all(after[k] == r for k, r in before.items() if r["status"] in ACCEPTED)
            stage = {"cycle": cycle, "seconds": round(time.monotonic() - start, 2),
                     "network_requests": client.requests - calls,
                     "added_review_records": cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] - count,
                     "batch_statuses": dict(Counter(after[k]["status"] for k in keys)),
                     "library_statuses": dict(Counter(r["status"] for r in after.values()))}
            print(json.dumps(stage), flush=True)
            if cycle == "repeat":
                assert after == first
                assert stage["network_requests"] == stage["added_review_records"] == 0
            first = after
            stages.append(stage)
            (HERE / f"{batch}-results.json").write_text(json.dumps({"stages": stages,
                "entries": {k: {"status": after[k]["status"], "fingerprint": after[k]["fingerprint"]} for k in sorted(keys)}}, indent=2) + "\n")
        assert all(after[k]["status"] in ACCEPTED for k in keys)
        export_snapshot("cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
        from reassess import export_queue
        export_queue(load_entries("cdl.bib"), after)
        print("PASS: all corrections verified; prior approvals intact; repeat zero requests and writes", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
