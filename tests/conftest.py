"""Suite-wide guard: no test may depend on the live cdl.bib.

Approved research batches keep changing cdl.bib, and four times (Sept 2026) a test that
read it broke on a legitimate correction. Every test sees the library as frozen before the
research waves were applied; a test that needs other library content monkeypatches
correction_proposals.LIBRARY_BIB itself (that still wins, being applied later).
"""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
FROZEN_LIBRARY = ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib"


@pytest.fixture(autouse=True)
def _frozen_library(monkeypatch):
    if str(ROOT / "bibcheck") not in sys.path:
        sys.path.insert(0, str(ROOT / "bibcheck"))
    try:
        import correction_proposals as cp
    except Exception:  # a module that fails to import is reported by its own tests
        return
    monkeypatch.setattr(cp, "LIBRARY_BIB", FROZEN_LIBRARY)
