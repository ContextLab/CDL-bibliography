"""Apply a frozen source-audited edit batch, then use ordinary verification.

This is a dated audit runner, not an automatic PDF approval route. Each frozen
proposal names its documentary source audit. The source library is read-only.
"""
from collections import Counter
from copy import deepcopy
import argparse
import gzip
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock, run_verification
from correction_proposals import replace_field, replace_pagination
from pagination import earlier, WORK, HERE
from reassess import export_queue
from arxiv_review import run_arxiv_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch", choices=["documentary001", "documentary002", "documentary003", "documentary004", "documentary005", "documentary006", "arxivfix001"], default="documentary001")
    args = parser.parse_args()
    apply, batch = args.apply, args.batch
    proposals = json.loads((HERE / f"{batch}-proposals.json").read_text())
    expected = {"documentary001": {"Dijk59", "Sper60"},
                "documentary002": {"Brem78", "CraiLock72", "RobbMonr51", "StanEtal06", "CoheEtal16"},
                "documentary003": {"AlyEtal18", "BaldEtal18", "BornNorm17", "ColeEtal16", "HeusEtal21", "MannEtal18", "OwenMann24", "ShinEtal23"},
                "documentary004": {"ChurSejn88", "WorsEtal05", "Shap19", "ZadbEtal17", "ZimaEtal18", "WatrEtal13a", "XiaoEtal05", "WainJord08"},
                "documentary005": {"GeusEtal05", "LogoEtal01", "BoteEtal98", "MomeEtal17", "BaldEtal17"},
                "documentary006": {"BuzsEtal12", "FolkEtal18", "GrieEtal20"},
                "arxivfix001": {"ConnEtal18", "GongEtal25", "FangEtal24", "ReddEtal18"}}
    assert {p["key"] for p in proposals} == expected[batch]
    assert len(proposals) == len(expected[batch])
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        # Staging is read-only with respect to the main verification cache.
        backup = WORK / f"before-{batch}.bib"
        resuming = backup.exists()
        entries = load_entries(backup if resuming else "cdl.bib")
        original = (backup if resuming else Path("cdl.bib")).read_text()
        modified = original
        for p in proposals:
            entry = entries[p["key"]]
            assert entry["fingerprint"] == p["fingerprint"], p["key"]
            working = deepcopy(entry)
            for field, change in p["changes"].items():
                single = dict(p, changes={field: change})
                if field == "pages":
                    raw = replace_pagination(working["raw"], {p["key"]: working}, [single])
                else:
                    raw = replace_field(working["raw"], working, single)
                working["raw"] = raw
                working["fields"][field] = change["after"]
            modified = modified.replace(entry["raw"], working["raw"], 1)
        staging = WORK / f"{batch}-staged.bib"
        staging.write_text(modified)
        staged = load_entries(staging)
        keys = {p["key"] for p in proposals}
        assert set(staged) == set(entries)
        for key, entry in entries.items():
            if key not in keys:
                assert staged[key] == entry, key
            else:
                p = next(p for p in proposals if p["key"] == key)
                assert staged[key]["fields"] == dict(entry["fields"], **{
                    field: change["after"] for field, change in p["changes"].items()})
                assert staged[key]["fingerprint"] != entry["fingerprint"]
        from helpers import check_bib
        errors, _ = check_bib(str(staging))
        assert not errors, errors
        print(f"PASS: {len(proposals)} documentary edits staged; all other entries and keys unchanged", flush=True)
        if not apply:
            return
        with run_lock(cache):
            if resuming:
                assert Path("cdl.bib").read_text() == modified
                with gzip.open(WORK / f"before-{batch}.jsonl.gz", "rt") as source:
                    before = {r["key"]: r for r in map(json.loads, source) if "key" in r}
            else:
                assert Path("cdl.bib").read_text() == original
                before = current_results("cdl.bib", cache, entries)
                export_snapshot("cdl.bib", cache, WORK / f"before-{batch}.jsonl.gz")
                backup.write_text(original)
                Path("cdl.bib").write_text(modified)
        client = earlier.client_for(cache)
        stages = []
        for cycle in ("run", "repeat"):
            start, calls = time.monotonic(), client.requests
            count = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
            after = run_verification("cdl.bib", cache, client, WORK / f"{batch}-report.jsonl", keys=keys)
            # arXiv entries are approved only by the repository route, as in verify --auto-review.
            after = run_arxiv_review("cdl.bib", cache, client, WORK / f"{batch}-report.jsonl", keys=keys)
            assert all(after[k] == row for k, row in before.items() if row["status"] in ACCEPTED)
            stage = {"cycle": cycle, "seconds": round(time.monotonic()-start, 2),
                     "network_requests": client.requests-calls,
                     "added_review_records": cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]-count,
                     "batch_statuses": dict(Counter(after[k]["status"] for k in keys)),
                     "library_statuses": dict(Counter(row["status"] for row in after.values()))}
            if cycle == "repeat":
                assert after == first
                assert stage["network_requests"] == stage["added_review_records"] == 0
            first = after
            stages.append(stage)
            print(json.dumps(stage), flush=True)
            (HERE / f"{batch}-results.json").write_text(json.dumps({"stages": stages,
                "entries": {k: {"status": after[k]["status"], "fingerprint": after[k]["fingerprint"]} for k in sorted(keys)}}, indent=2)+"\n")
        assert all(after[k]["status"] in ACCEPTED for k in keys)
        export_snapshot("cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
        export_queue(load_entries("cdl.bib"), after)
        print("PASS: ordinary metadata verification passed; repeat zero requests/writes", flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
