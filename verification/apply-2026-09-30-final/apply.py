"""Final apply (2026-09-30-final folder, run 2026-09-27): resolution batches 27-39 and the held forms of
waves 2-9, in three batches (res27, res28to33, res34to39).

The runner is ../apply-2026-09-28-wave1/apply.py (its stage, with the relaxation that a new key may be a
key the same batch removes), on ../apply-2026-09-29/apply.py and ../apply-2026-09-28/apply.py, pointed at
this folder, exactly as ../apply-2026-09-29-waves2-9/apply.py: frozen proposals with fingerprints
(<batch>-proposals.json, built by build.py), a staging copy whose diff is limited to the batch,
helpers.check_bib, backup + snapshot under .bibcheck/apply-2026-09-30-final/, apply, the production
pipeline for the batch keys, a repeat that must make zero requests and zero review writes, no change to
any accepted result outside the batch, then verification/baseline.jsonl.gz and
verification/review-queue.jsonl.gz.

    .venv/bin/python verification/apply-2026-09-30-final/apply.py res27 [--apply]
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("applywave1", ROOT / "verification/apply-2026-09-28-wave1/apply.py")
wave1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wave1)
runner = wave1.runner            # ../apply-2026-09-28/apply.py, with stage = wave1.stage
stage2d = wave1.stage2d
base = runner.base
runner.HERE = runner.runner.HERE = base.HERE = stage2d.HERE = wave1.HERE = HERE
runner.WORK = runner.runner.WORK = base.WORK = stage2d.WORK = wave1.WORK = ROOT / ".bibcheck" / HERE.name
runner.BATCHES = ("res27", "res28to33", "res34to39")
assert runner.stage is wave1.stage

if __name__ == "__main__":
    runner.main()
