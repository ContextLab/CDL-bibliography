"""Suite-wide guard: no test may depend on the live cdl.bib.

Approved research batches keep changing cdl.bib, and four times (Sept 2026) a test that
read it broke on a legitimate correction. Every test sees the library as frozen before the
research waves were applied; a test that needs other library content monkeypatches
correction_proposals.LIBRARY_BIB itself (that still wins, being applied later).
"""
import atexit
import os
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
FROZEN_LIBRARY = ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib"

# Tests that fetch live evidence (validate.py) write the bodies into a directory of this run,
# never into the clone's .bibcheck/research-pilot/. That directory is evidence the route
# validator reads during `crossref restore`: on 2026-09-30 a test run left 16 freshly fetched
# bodies there, three of them dynamic pages whose sha256 differed from the approvals', and the
# next restore rejected the whole snapshot. Set before any test module imports validate.py
# or research_route (both read BIBCHECK_RESEARCH_BODIES at import); subprocesses inherit it.
_BODIES = tempfile.mkdtemp(prefix="bibcheck-test-research-bodies-")
atexit.register(shutil.rmtree, _BODIES, True)
os.environ["BIBCHECK_RESEARCH_BODIES"] = _BODIES


@pytest.fixture(autouse=True)
def _frozen_library(monkeypatch, tmp_path):
    # The committed revocation ledger is live data too: every test starts with an
    # empty ledger of its own (tests/test_revocation.py writes to it).
    from cdlbib import verification
    monkeypatch.setattr(verification, "REVOCATION_LEDGER", tmp_path / "revocations.jsonl")
    try:
        from cdlbib import correction_proposals as cp
    except Exception:  # a module that fails to import is reported by its own tests
        return
    monkeypatch.setattr(cp, "LIBRARY_BIB", FROZEN_LIBRARY)
