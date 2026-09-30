"""Build decisions0928-proposals.json: ../build.py's rules (resolution_quote on every set value, house form,
key plan, conflicts with batches 01-26) for the user answers of 2026-09-28 (batch-41.json here, read as
batch 41): R12's author as printed and the organization-key rule of 2026-09-28 (R12 -> RCor12,
MorrRNS11 -> MorrRNSS11, US20a/b -> USFo20a/b), and GrilEtal06b dropped. ../build.py's OVERRIDE
(ElliAshb88) does not concern these keys and is not applied.

../build.py names every drop's decision source as a resolution-2026-09-26 batch file; this batch's file is
here, so the removal's ``decision`` is rewritten to name it after the build.

    .venv/bin/python verification/apply-2026-09-27b-final/decisions0928/build.py decisions0928 [--offline]
"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BATCH = HERE / "batch-41.json"
_spec = importlib.util.spec_from_file_location("final_build", HERE.parent / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
_rows_of = build.rows_of


def rows_of(n):
    if n == 41:
        return BATCH, [dict(r, _batch="batch-41") for r in json.loads(BATCH.read_text())]
    return _rows_of(n)


build.rows_of = rows_of
build.HERE = HERE
build.WORK = ROOT / ".bibcheck" / "decisions0928-2026-09-28"
build.BATCHES = {"decisions0928": (41,)}
build.ORDER = ("decisions0928",)
build.OVERRIDE = {}

if __name__ == "__main__":
    build.main()
    path = HERE / "decisions0928-proposals.json"
    out = json.loads(path.read_text())
    rel = str(BATCH.relative_to(ROOT))
    for p in out["proposals"]:
        if p["kind"] == "remove":
            prefix = "verification/resolution-2026-09-26/batch-41.json (drop): "
            assert p["decision"].startswith(prefix), p["decision"]
            p["decision"] = f"{rel} (drop): " + p["decision"][len(prefix):]
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
