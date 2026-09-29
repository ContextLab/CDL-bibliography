"""Export verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz after the
research-approve step (the runner exports them before it), with the same functions the
runner uses.

    python verification/apply-2026-09-29-braces/export.py
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("applybraces", HERE / "apply.py")
apply = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply)
from verification import Cache, current_results, export_snapshot  # noqa: E402

if __name__ == "__main__":
    cache = Cache(ROOT / ".bibcheck/verification.sqlite3")
    try:
        export_snapshot(apply.base.BIB, cache, ROOT / "verification/baseline.jsonl.gz")
        results = current_results(apply.base.BIB, cache)
        print(apply.base.export_queue(results))
    finally:
        cache.close()
