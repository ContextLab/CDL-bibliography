"""Where a library checkout lives, and every data path derived from it."""
import os
from pathlib import Path

from .errors import WorkspaceNotFound

BIB_NAME = "cdl.bib"


class Workspace:
    def __init__(self, root, bib=None):
        self.root = Path(root).resolve()
        self.bib = Path(bib).resolve() if bib is not None else self.root / BIB_NAME

    def __repr__(self):
        return f"Workspace({str(self.root)!r})"

    @property
    def work(self):
        return self.bib.parent / ".bibcheck"

    @property
    def database(self):
        return self.work / "verification.sqlite3"

    @property
    def report(self):
        return self.work / "report.jsonl"

    @property
    def baseline(self):
        return self.root / "verification" / "baseline.jsonl.gz"

    @property
    def revocations(self):
        return self.root / "verification" / "revocations.jsonl"

    @property
    def key_renames(self):
        return self.root / "verification" / "key-renames.json"

    @property
    def key_deletions(self):
        return self.root / "verification" / "key-deletions.json"

    def research_bodies_for(self, environ):
        override = environ.get("BIBCHECK_RESEARCH_BODIES")
        return Path(override) if override else self.work / "research-pilot"

    @property
    def research_bodies(self):
        return self.research_bodies_for(os.environ)

    @classmethod
    def for_bib(cls, fname):
        fname = Path(fname).resolve()
        return cls(fname.parent, bib=fname)

    @classmethod
    def find(cls, explicit=None, environ=None, cwd=None):
        environ = os.environ if environ is None else environ
        for source, value in (("--library", explicit), ("CDLBIB_LIBRARY", environ.get("CDLBIB_LIBRARY"))):
            if value:
                root = Path(value).expanduser()
                if not (root / BIB_NAME).is_file():
                    raise WorkspaceNotFound(f"{source} points to {root}, which has no {BIB_NAME}")
                return cls(root)
        here = Path(cwd) if cwd is not None else Path.cwd()
        for folder in (here, *here.resolve().parents):
            if (folder / BIB_NAME).is_file():
                return cls(folder)
        raise WorkspaceNotFound(
            f"No library found. Run inside a checkout that contains {BIB_NAME}, "
            "pass --library PATH, or set CDLBIB_LIBRARY.")


_library = None  # the front end's --library choice; the only place it is kept


def select_library(path):
    """Record the front end's --library (None clears it)."""
    global _library
    _library = path


def resolve(fname=None):
    """The one rule for which library a command works on: a file the user named, else
    --library, else CDLBIB_LIBRARY, else the nearest cdl.bib from the current folder up."""
    return Workspace.for_bib(fname) if fname is not None else Workspace.find(_library)


def default():
    return resolve()
