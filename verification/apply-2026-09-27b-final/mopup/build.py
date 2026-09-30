"""Build mopup-proposals.json: ../build.py's rules (resolution_quote on every set value, house form,
key plan, conflicts with batches 01-26) for the mop-up resolution batch
../../research-route-2026-09-27/batch-40.json, read as batch 40. ../build.py's OVERRIDE (ElliAshb88 keep)
is not applied: batch 40's ElliAshb88 row keeps the entry too, and applies the address and the new evidence.

    .venv/bin/python verification/apply-2026-09-27b-final/mopup/build.py mopup [--offline]
"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MOPUP = ROOT / "verification/research-route-2026-09-27/batch-40.json"
_spec = importlib.util.spec_from_file_location("final_build", HERE.parent / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
_rows_of = build.rows_of


def rows_of(n):
    if n == 40:
        return MOPUP, [dict(r, _batch="batch-40") for r in json.loads(MOPUP.read_text())]
    return _rows_of(n)


build.rows_of = rows_of
build.HERE = HERE
build.WORK = ROOT / ".bibcheck" / "mopup-2026-09-27"
build.BATCHES = {"mopup": (40,)}
build.ORDER = ("mopup",)
build.OVERRIDE = {}

if __name__ == "__main__":
    build.main()
