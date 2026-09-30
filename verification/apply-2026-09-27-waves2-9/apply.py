"""Stage 3 batches wave2 .. wave9 (2026-09-27): the ready rows and the
removals of research waves 2-9, one batch per wave.

The runner is ../apply-2026-09-26-wave1/apply.py (its stage, with the relaxation that a new key may be
a key the same batch removes), on ../apply-2026-09-25f/apply.py and ../apply-2026-09-25e/apply.py,
pointed at this folder. Same discipline: frozen proposals with fingerprints (<wave>-proposals.json,
built by build.py), a staging copy whose diff is limited to the batch, helpers.check_bib, backup +
snapshot under .bibcheck/apply-2026-09-27-waves2-9/, apply, the production pipeline for the batch keys,
a repeat that must make zero requests and zero review writes, no change to any accepted result outside
the batch, then verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz.

    .venv/bin/python verification/apply-2026-09-27-waves2-9/apply.py wave2 [--apply]
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("applywave1", ROOT / "verification/apply-2026-09-26-wave1/apply.py")
wave1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wave1)
runner = wave1.runner            # ../apply-2026-09-25e/apply.py, with stage = wave1.stage
stage2d = wave1.stage2d
base = runner.base
runner.HERE = runner.runner.HERE = base.HERE = stage2d.HERE = wave1.HERE = HERE
runner.WORK = runner.runner.WORK = base.WORK = stage2d.WORK = wave1.WORK = ROOT / ".bibcheck" / HERE.name
runner.BATCHES = ("wave2", "wave3", "wave4", "wave2to4") + tuple(f"wave{n}" for n in range(5, 10))  # wave2to4: the wave 2-4 rows left after the re-run post-check
assert runner.stage is wave1.stage

if __name__ == "__main__":
    runner.main()
