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


class Origin:
    """How the library of a command was chosen."""
    NAMED = "named"                    # a file the user named
    OPTION = "--library"
    ENVIRONMENT = "CDLBIB_LIBRARY"
    FOUND = "found"                    # cdl.bib in the current folder or above it
    MANAGED = "managed"                # none of those: the copy cdlbib downloads and keeps


_library = None   # the front end's --library choice, or the managed library once a command fell back to it
_managed = False  # True when _library was recorded by resolve(managed=True), not given by the user


def select_library(path):
    """Record the front end's --library (None clears it)."""
    global _library, _managed
    _library, _managed = path, False


def resolve(fname=None, managed=False, progress=None):
    """The one rule for which library a command works on: a file the user named, else
    --library, else CDLBIB_LIBRARY, else the nearest cdl.bib from the current folder up.

    Front ends pass ``managed=True``: when none of those gives a library, the managed one is
    used, downloaded first if it is not there (``progress`` receives the one line saying so),
    and recorded, so that default() agrees for the rest of the process. Without it this is a
    pure lookup that raises WorkspaceNotFound. A library the user chose is never downloaded:
    --library or CDLBIB_LIBRARY pointing at a folder with no cdl.bib stays an error.
    """
    global _library, _managed
    if fname is not None:
        return Workspace.for_bib(fname)
    try:
        return Workspace.find(_library)
    except WorkspaceNotFound:
        if not managed or _library or os.environ.get("CDLBIB_LIBRARY"):
            raise
    from . import library
    root = library.download(progress)
    _library, _managed = str(root), True
    return Workspace(root)


def origin_of(fname=None):
    """(workspace, Origin) for what resolve() gives, without downloading anything: when
    nothing is named or found, the managed library's place, whether or not it is there yet."""
    if fname is not None:
        return Workspace.for_bib(fname), Origin.NAMED
    if _library:
        return Workspace.find(_library), Origin.MANAGED if _managed else Origin.OPTION
    if os.environ.get("CDLBIB_LIBRARY"):
        return Workspace.find(None), Origin.ENVIRONMENT
    try:
        return Workspace.find(None), Origin.FOUND
    except WorkspaceNotFound:
        from . import library
        return Workspace(library.path()), Origin.MANAGED


def default():
    return resolve()
