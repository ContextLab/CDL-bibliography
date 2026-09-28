"""Apply the drops under the user's ambiguity rule of 2026-09-28 (batch-42.json here: BrinCrag72, SvenEtal24,
ChanEtal12), as one batch "decisions0928b".

The runner is ../apply.py's (../../apply-2026-09-28-wave1/apply.py on ../../apply-2026-09-29/apply.py and
../../apply-2026-09-28/apply.py), pointed at this folder: frozen proposals with fingerprints
(decisions0928b-proposals.json, built by build.py), a staging copy whose diff is limited to the batch,
helpers.check_bib, backup + snapshot under .bibcheck/decisions0928b-2026-09-28/, apply, the production
pipeline for the batch keys, a repeat that must make zero requests and zero review writes, no change to
any accepted result outside the batch, then verification/baseline.jsonl.gz and
verification/review-queue.jsonl.gz.

    .venv/bin/python verification/apply-2026-09-30-final/decisions0928b/apply.py decisions0928b [--apply]
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
_spec = importlib.util.spec_from_file_location("applywave1", ROOT / "verification/apply-2026-09-28-wave1/apply.py")
wave1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wave1)
runner = wave1.runner
stage2d = wave1.stage2d
base = runner.base
runner.HERE = runner.runner.HERE = base.HERE = stage2d.HERE = wave1.HERE = HERE
runner.WORK = runner.runner.WORK = base.WORK = stage2d.WORK = wave1.WORK = ROOT / ".bibcheck" / "decisions0928b-2026-09-28"
runner.BATCHES = ("decisions0928b",)
assert runner.stage is wave1.stage

# A removal-only batch leaves no batch key to review, and the review layers refuse an empty key list
# (publisher_year_review: "Publisher review keys must name existing citations"). With no keys, the
# pipeline step reads the library's current results only (no layer runs, so no request and no review
# write); the runner's checks (library keys, accepted results outside the batch unchanged, repeat with
# zero requests and zero writes) and the exports still run.
_pipeline = base.pipeline


def pipeline(cache, client, keys, report):
    if not keys:
        return base.current_results(base.BIB, cache)
    return _pipeline(cache, client, keys, report)


base.pipeline = pipeline

if __name__ == "__main__":
    runner.main()
