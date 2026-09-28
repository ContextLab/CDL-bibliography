"""Build decisions0928b-proposals.json: ../build.py's rules for the drops under the user's ambiguity rule of
2026-09-28 (batch-42.json here, read as batch 42): BrinCrag72, SvenEtal24 and ChanEtal12 dropped ("ok, if
ambiguous, drop-- we can always add back if needed later"). ../build.py's OVERRIDE is not applied.

../build.py names every drop's decision source as a resolution-2026-09-26 batch file; this batch's file is
here, so each removal's ``decision`` is rewritten to name it after the build.

    .venv/bin/python verification/apply-2026-09-30-final/decisions0928b/build.py decisions0928b [--offline]
"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BATCH = HERE / "batch-42.json"
_spec = importlib.util.spec_from_file_location("final_build", HERE.parent / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
_rows_of = build.rows_of


def rows_of(n):
    if n == 42:
        return BATCH, [dict(r, _batch="batch-42") for r in json.loads(BATCH.read_text())]
    return _rows_of(n)


build.rows_of = rows_of
build.HERE = HERE
build.WORK = ROOT / ".bibcheck" / "decisions0928b-2026-09-28"
build.BATCHES = {"decisions0928b": (42,)}
build.ORDER = ("decisions0928b",)
build.OVERRIDE = {}

if __name__ == "__main__":
    build.main()
    path = HERE / "decisions0928b-proposals.json"
    out = json.loads(path.read_text())
    rel = str(BATCH.relative_to(ROOT))
    for p in out["proposals"]:
        if p["kind"] == "remove":
            prefix = "verification/resolution-2026-09-26/batch-42.json (drop): "
            assert p["decision"].startswith(prefix), p["decision"]
            p["decision"] = f"{rel} (drop): " + p["decision"][len(prefix):]
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
