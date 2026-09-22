"""Audit cached approvals for the correction-notice precedence bug, offline."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock
from auto_review import reassess, secondary_notice_flags
from reassess import export_queue

HERE = Path(__file__).parent
WORK = ROOT / ".bibcheck" / HERE.name


def main():
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        with run_lock(cache):
            entries = load_entries("cdl.bib")
            before = current_results("cdl.bib", cache, entries)
            backup = WORK / "before-notice-audit.jsonl.gz"
            if not backup.exists():
                export_snapshot("cdl.bib", cache, backup)
            reopened = []
            for key, old in before.items():
                if old["status"] != "metadata_verified" or not secondary_notice_flags(old.get("candidates", [])):
                    continue
                reviewed = reassess(entries[key], old)
                if reviewed["status"] not in ACCEPTED:
                    cache.put("cdl.bib", entries[key], reviewed)
                    reopened.append({"key": key, "fingerprint": old["fingerprint"],
                                     "previous_checked_at": old["checked_at"], "issues": reviewed["issues"]})
            after = current_results("cdl.bib", cache, entries)
            assert all(after[k] == r for k, r in before.items() if k not in {r["key"] for r in reopened})
            assert not any(reassess(entries[k], r)["status"] not in ACCEPTED
                           for k, r in after.items() if r["status"] == "metadata_verified"
                           and secondary_notice_flags(r.get("candidates", [])))
            export_snapshot("cdl.bib", cache, ROOT / "verification/baseline.jsonl.gz")
            export_queue(entries, after)
            report = {"network_requests": 0, "reopened": reopened,
                      "unaffected_records_preserved": len(before) - len(reopened)}
            if reopened:
                (HERE / "notice-audit-results.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report), flush=True)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
