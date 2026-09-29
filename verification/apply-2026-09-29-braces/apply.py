"""Apply the braces0929 batch (braces that protect nothing, removed; see build.py).

The runner is ../apply-2026-09-29-caps/apply.py's (../apply-2026-09-28-wave1/apply.py on
../apply-2026-09-29/apply.py and ../apply-2026-09-28/apply.py), pointed at this folder:
frozen proposals with fingerprints (braces0929-proposals.json), a staging copy whose diff
is limited to the batch, helpers.check_bib, backup + snapshot under
.bibcheck/braces0929-2026-09-29/, apply, the production pipeline for the batch keys, a
repeat that must make zero requests and zero review writes, no change to any accepted
result outside the batch, then verification/baseline.jsonl.gz and
verification/review-queue.jsonl.gz (this batch owns both).

    python verification/apply-2026-09-29-braces/apply.py braces0929 [--apply]
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("applywave1", ROOT / "verification/apply-2026-09-28-wave1/apply.py")
wave1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wave1)
runner = wave1.runner
stage2d = wave1.stage2d
base = runner.base
runner.HERE = runner.runner.HERE = base.HERE = stage2d.HERE = wave1.HERE = HERE
runner.WORK = runner.runner.WORK = base.WORK = stage2d.WORK = wave1.WORK = ROOT / ".bibcheck" / "braces0929-2026-09-29"
runner.BATCHES = ("braces0929",)
assert runner.stage is wave1.stage

if __name__ == "__main__":
    runner.main()
