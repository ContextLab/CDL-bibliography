"""Apply the caps0929 batch (acronyms, "\\&" compounds, state abbreviations; see build.py).

The runner is ../apply-2026-09-30-final/mopup/apply.py's (../apply-2026-09-28-wave1/apply.py on
../apply-2026-09-29/apply.py and ../apply-2026-09-28/apply.py), pointed at this folder: frozen proposals
with fingerprints (caps0929-proposals.json), a staging copy whose diff is limited to the batch,
helpers.check_bib, backup + snapshot under .bibcheck/caps0929-2026-09-29/, apply, the production pipeline
for the batch keys, a repeat that must make zero requests and zero review writes, and no change to any
accepted result outside the batch.

One difference: the snapshot and review-queue exports are written to this folder (baseline.jsonl.gz,
review-queue.jsonl.gz) instead of verification/baseline.jsonl.gz and verification/review-queue.jsonl.gz,
which this batch's owner did not own.

    python verification/apply-2026-09-29-caps/apply.py caps0929 [--apply]
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
runner.WORK = runner.runner.WORK = base.WORK = stage2d.WORK = wave1.WORK = ROOT / ".bibcheck" / "caps0929-2026-09-29"
runner.BATCHES = ("caps0929",)
assert runner.stage is wave1.stage

_export_snapshot = runner.export_snapshot


def export_snapshot(bib, cache, path):
    if Path(path) == ROOT / "verification/baseline.jsonl.gz":
        path = HERE / "baseline.jsonl.gz"
    return _export_snapshot(bib, cache, path)


def export_queue(results):
    import gzip
    import json
    import shutil
    queue = ROOT / "verification/review-queue.jsonl.gz"
    saved = queue.read_bytes()
    try:
        out = base.__dict__["_export_queue"](results)
        shutil.copyfile(queue, HERE / "review-queue.jsonl.gz")
    finally:
        queue.write_bytes(saved)
    return out


runner.export_snapshot = export_snapshot
base._export_queue = base.export_queue
base.export_queue = export_queue

if __name__ == "__main__":
    runner.main()
