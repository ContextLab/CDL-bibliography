"""The terminal interface of cdlbib (``cdlbib tui``). Needs the optional package textual."""
from .app import CdlbibApp, KEYS, run

__all__ = ["CdlbibApp", "KEYS", "run"]
