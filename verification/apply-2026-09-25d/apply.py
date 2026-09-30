"""Stage 2B-ii batches (2026-09-25): suffix-strip, initials, formats, ordinals, adddoi002.

The runner is ../apply-2026-09-25b/apply.py (built on ../apply-2026-09-23/apply.py),
unchanged: frozen proposals with fingerprints (<batch>-proposals.json, built by build.py
or build_adddoi.py), a staging copy whose diff is limited to the batch, helpers.check_bib,
backup + snapshot under .bibcheck/apply-2026-09-25d/, apply, the production pipeline for
the batch keys, a repeat that must make zero requests and zero review writes, no change to
any accepted result outside the batch, then verification/baseline.jsonl.gz and
verification/review-queue.jsonl.gz.

    .venv/bin/python verification/apply-2026-09-25d/apply.py BATCH [--apply]
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
runner.BATCHES = ("suffix-strip", "initials", "formats", "ordinals", "adddoi002")

if __name__ == "__main__":
    runner.main()
