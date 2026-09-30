"""Library-wide offline check of the 2026-09-30 name-parsing fixes (no request, no write).

Every saved result is re-derived from its saved evidence as ``crossref verify
--recheck-cached`` does (``auto_review.reassess``; a route approval its own validator still
accepts is kept), with the checker code under CODE_ROOT, against the live cdl.bib and
database of the repository. Run once with the code before the fix (a detached worktree of
the parent commit) and once with the fixed code; the entries whose status or issues differ
between the two runs are the entries the fix changes.

    CODE_ROOT=<worktree> python parser_scan.py OUT.json
"""
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
CODE = Path(os.environ.get("CODE_ROOT", REPO)).resolve()
sys.path.insert(0, str(CODE / "bibcheck"))
os.chdir(REPO)
import verification  # noqa: E402
from verification import Cache, current_results, load_entries, route_approval_valid  # noqa: E402
from auto_review import reassess  # noqa: E402
import research_route  # noqa: E402,F401  (registers the research approval validator)

assert Path(verification.__file__).resolve().is_relative_to(CODE), verification.__file__


def main(out):
    cache = Cache(REPO / ".bibcheck/verification.sqlite3")
    try:
        entries = load_entries("cdl.bib")
        saved = current_results("cdl.bib", cache, entries)
        rows = {}
        for key, result in saved.items():
            if result["status"] not in ("metadata_verified", "needs_review"):
                rows[key] = {"status": result["status"], "issues": result.get("issues", []), "kept": True}
                continue
            try:
                new = reassess(entries[key], result)
            except Exception as exc:  # recorded, never hidden
                rows[key] = {"status": "error", "issues": [f"{type(exc).__name__}: {exc}"]}
                continue
            if result["status"] == "metadata_verified" and new.get("status") != "metadata_verified" \
                    and route_approval_valid(result):
                rows[key] = {"status": result["status"], "issues": result.get("issues", []), "kept": True}
                continue
            rows[key] = {"status": new.get("status"), "issues": new.get("issues", []),
                         "candidate_issues": sorted(i for c in new.get("candidates") or []
                                                    for i in c.get("issues") or [] if isinstance(i, str))}
        Path(out).write_text(json.dumps({"code": str(CODE), "rows": rows}, ensure_ascii=False, sort_keys=True))
        print(len(rows), "entries re-derived with", CODE)
    finally:
        cache.close()


if __name__ == "__main__":
    main(sys.argv[1])
