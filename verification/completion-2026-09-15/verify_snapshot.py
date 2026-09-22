"""Prove the exported baseline restores exact current results in a fresh cache."""

from collections import Counter
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from verification import Cache, current_results, import_snapshot


def main():
    live = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        before = current_results(ROOT / "cdl.bib", live)
    finally:
        live.close()
    with tempfile.TemporaryDirectory(prefix="bibcheck-restore-") as directory:
        fresh = Cache(Path(directory) / "cache.sqlite3")
        try:
            restored = import_snapshot(ROOT / "cdl.bib", fresh, ROOT / "verification/baseline.jsonl.gz")
            after = current_results(ROOT / "cdl.bib", fresh)
            assert after == before
            repeat = import_snapshot(ROOT / "cdl.bib", fresh, ROOT / "verification/baseline.jsonl.gz")
            assert repeat == 0
            assert current_results(ROOT / "cdl.bib", fresh) == after
            report = {"restored": restored, "statuses": dict(Counter(r["status"] for r in after.values())),
                      "repeat_imports": repeat,
                      "source_notices": fresh.db.execute("SELECT count(*) FROM source_notices").fetchone()[0],
                      "source_author_suffixes": fresh.db.execute("SELECT count(*) FROM source_author_suffixes").fetchone()[0],
                      "source_article_locators": fresh.db.execute("SELECT count(*) FROM source_article_locators").fetchone()[0],
                      "sqlite": fresh.db.execute("PRAGMA quick_check").fetchone()[0]}
            assert report["sqlite"] == "ok"
            (Path(__file__).parent / "restore-latest.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report), flush=True)
        finally:
            fresh.close()


if __name__ == "__main__":
    main()
