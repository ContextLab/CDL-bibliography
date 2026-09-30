"""Mop-up apply (run 2026-09-27): the research route's mop-up resolution batch
(../../research-route-2026-09-27/batch-40.json: ElliAshb88, Mann06), as one batch "mopup".

The runner is ../apply.py's (../../apply-2026-09-26-wave1/apply.py on ../../apply-2026-09-25f/apply.py and
../../apply-2026-09-25e/apply.py), pointed at this folder: frozen proposals with fingerprints
(mopup-proposals.json, built by build.py), a staging copy whose diff is limited to the batch,
helpers.check_bib, backup + snapshot under .bibcheck/mopup-2026-09-27/, apply, the production pipeline for
the batch keys, a repeat that must make zero requests and zero review writes, no change to any accepted
result outside the batch, then verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz.

    .venv/bin/python verification/apply-2026-09-27b-final/mopup/apply.py mopup [--apply]
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
_spec = importlib.util.spec_from_file_location("applywave1", ROOT / "verification/apply-2026-09-26-wave1/apply.py")
wave1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wave1)
runner = wave1.runner
stage2d = wave1.stage2d
base = runner.base
runner.HERE = runner.runner.HERE = base.HERE = stage2d.HERE = wave1.HERE = HERE
runner.WORK = runner.runner.WORK = base.WORK = stage2d.WORK = wave1.WORK = ROOT / ".bibcheck" / "mopup-2026-09-27"
runner.BATCHES = ("mopup",)
assert runner.stage is wave1.stage

if __name__ == "__main__":
    runner.main()
