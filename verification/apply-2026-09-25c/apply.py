"""Stage 2B-i batch held001: the 30 edits held in stage 2A, under the user's rules.

The runner is ../apply-2026-09-25b/apply.py (itself built on ../apply-2026-09-23/apply.py),
unchanged: frozen proposals with fingerprints (held001-proposals.json, built by
build_held.py), a staging copy whose diff is limited to the batch and its approved key
renames, helpers.check_bib, backup + snapshot under .bibcheck/apply-2026-09-25c/, apply,
the production pipeline for the batch keys (verify --recheck-cached now keeps valid route
approvals), a repeat that must make zero requests and zero review writes, no change to
any accepted result outside the batch, then verification/baseline.jsonl.gz and
verification/review-queue.jsonl.gz.

    .venv/bin/python verification/apply-2026-09-25c/apply.py held001 [--apply]
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("apply0926", ROOT / "verification/apply-2026-09-25b/apply.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)
runner.HERE = runner.base.HERE = HERE
runner.WORK = runner.base.WORK = ROOT / ".bibcheck" / HERE.name
runner.BATCHES = ("held001",)

if __name__ == "__main__":
    runner.main()
