"""Run the Phase-0 and catalogue measurements read-only, writing elsewhere.

The measurement scripts in verification/phase0-2026-09-22/ and
verification/catalogue-phase0-2026-09-22/ write their outputs next to
themselves. This wrapper imports them unchanged, points their output
directory (``HERE``) at ``--out`` and runs them, so the dated Phase-0 folders
are never overwritten. Both open the verification cache read-only (mode=ro)
and make no network request.

    measure_wrap.py phase0 --out DIR [--workers 8]
    measure_wrap.py catalogue --out DIR
    measure_wrap.py rows --out FILE [--workers 8]   # per-key Phase-0 rows only
"""
import argparse
import importlib.util
import json
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = {"phase0": ROOT / "verification/phase0-2026-09-22/measure.py",
           "catalogue": ROOT / "verification/catalogue-phase0-2026-09-22/measure.py"}


def load(which):
    spec = importlib.util.spec_from_file_location(f"measure_{which}", SCRIPTS[which])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # fork-pool workers resolve functions by module name
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("which", choices=["phase0", "catalogue", "rows"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    sys.argv = [sys.argv[0]]  # the measurement scripts parse their own argv
    if args.which == "rows":
        m = load("phase0")
        entries = m.load_entries(ROOT / "cdl.bib")
        cache = m.ReadOnlyCache(ROOT / ".bibcheck/verification.sqlite3")
        current = {k: cache.get(ROOT / "cdl.bib", e) or dict(m.outcome("pending", ["New"]), key=k)
                   for k, e in entries.items()}
        cache.close()
        m.ENTRIES, m.CURRENT = entries, current
        with multiprocessing.get_context("fork").Pool(args.workers) as pool:
            rows = pool.map(m.assess_one, list(entries), chunksize=8)
        out.write_text(json.dumps({r["key"]: r for r in rows}, ensure_ascii=False) + "\n")
        return
    out.mkdir(parents=True, exist_ok=True)
    m = load(args.which)
    m.HERE = out
    if args.which == "phase0":
        sys.argv += ["--workers", str(args.workers)]
    m.main()


if __name__ == "__main__":
    main()
