#!/usr/bin/env python3
"""Compatibility entry point for ``bibcheck.py crossref``.

The old fuzzy, parallel verifier has been replaced. See ``verify --help`` for
resumable verification and ``status --help`` for the offline accuracy gate.
"""

import sys
from pathlib import Path

from cdlbib.verification_cli import app

if __name__ == "__main__":
    app()
