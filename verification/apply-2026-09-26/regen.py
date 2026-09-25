"""Regenerate the correction proposals over the current cdl.bib and cache (resolver 30).

Runs verification/fixes-2026-09-24/measure.py unchanged (house-form authors, stated
issues, after-value audit with ``stated_by``), with three redirections:

- output (proposals.json, groups.json, lookups.json, diff.json) goes to this folder;
- diff.json compares with verification/fixes-2026-09-24/proposals.json (the approved,
  spot-checked versions) instead of the older Phase 0 measurement;
- the issue-lookup cache is a copy, .bibcheck/apply-2026-09-26/issue-lookups.sqlite3,
  seeded from .bibcheck/fixes-2026-09-24.sqlite3, so that file is not written.

Then runs verification/catalogue-phase0-2026-09-22/measure.py unchanged, writing to
catalogue/ in this folder. Both open the main cache read-only (mode=ro).

    .venv/bin/python verification/apply-2026-09-26/regen.py [--offline] [--workers 8]
"""
import argparse
import importlib.util
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOOKUP_SRC = ROOT / ".bibcheck/fixes-2026-09-24.sqlite3"
LOOKUP = ROOT / ".bibcheck/apply-2026-09-26/issue-lookups.sqlite3"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # fork-pool workers resolve functions by module name
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("which", choices=["articles", "catalogue"])
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.which == "catalogue":
        out = HERE / "catalogue"
        out.mkdir(exist_ok=True)
        sys.argv = [sys.argv[0]]
        m = load("measure_catalogue", ROOT / "verification/catalogue-phase0-2026-09-22/measure.py")
        m.HERE = out
        m.main()
        return
    LOOKUP.parent.mkdir(parents=True, exist_ok=True)
    if not LOOKUP.exists():
        shutil.copyfile(LOOKUP_SRC, LOOKUP)
    fixes = load("fixes_measure", ROOT / "verification/fixes-2026-09-24/measure.py")
    fixes.HERE = HERE
    fixes.BASELINE = ROOT / "verification/fixes-2026-09-24/proposals.json"
    # Phase 0 measure copies non-Phase-0 modules from HEAD into a temporary folder, where
    # correction_proposals.LIBRARY_BIB (the surname-corroboration library, ../cdl.bib) does
    # not exist: the first run raised FileNotFoundError for 19 surname-change entries. Load
    # every module from the working tree instead, after checking bibcheck/ equals HEAD.
    import os
    import subprocess
    env = dict(os.environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools")
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "bibcheck"], cwd=ROOT, env=env,
                           check=True, capture_output=True, text=True).stdout
    if dirty.strip():
        raise SystemExit("bibcheck/ differs from HEAD; refusing to measure work in progress:\n" + dirty)

    def original_load():
        sys.argv = [sys.argv[0], "--working-tree"]
        spec = importlib.util.spec_from_file_location("measure_phase0", fixes.PHASE0)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def load_phase0():
        module = original_load()
        verification = sys.modules["verification"]
        base_cache = verification.Cache

        class RedirectedCache(base_cache):
            def __init__(self, path, *a, **k):
                if Path(path).resolve() == LOOKUP_SRC.resolve():
                    path = LOOKUP
                super().__init__(path, *a, **k)
        verification.Cache = RedirectedCache
        return module
    fixes.load_phase0 = load_phase0
    sys.argv = [sys.argv[0], "--workers", str(args.workers)] + (["--offline"] if args.offline else [])
    fixes.main()


if __name__ == "__main__":
    main()
