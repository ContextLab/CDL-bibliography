"""What the web interface keeps between requests, under random ids: proposals, read PDFs,
candidate lists, edit previews, uploaded manuscripts, exports and pending questions. The
browser is given the ids and never the objects' authority: it sends an id back with a
decision. Uploaded files live in one private folder of this run, removed at exit, under names
made here."""
import re
import secrets
import shutil
import tempfile
import threading
from pathlib import Path

ID = re.compile(r"[A-Za-z0-9_-]{22}\Z")
KEPT = 2000              # objects kept; the oldest go first
MAX_UPLOAD = 50_000_000  # bytes of one uploaded file (intake.MAX_PDF_BYTES)
MAX_BUNDLE_FILES = 60
MANUSCRIPT_TYPES = (".tex", ".aux", ".bcf")
PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class Missing(KeyError):
    """No object of that kind under that id (never made, or dropped to make room)."""


class Store:
    def __init__(self):
        self.folder = Path(tempfile.mkdtemp(prefix="cdlbib-web-"))     # mode 0700
        self.items, self.lock = {}, threading.Lock()

    def close(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def put(self, kind, value):
        found = secrets.token_urlsafe(16)
        with self.lock:
            self.items[found] = (kind, value)
            for old in list(self.items)[:max(0, len(self.items) - KEPT)]:
                self._drop(old)
        return found

    def get(self, kind, found):
        with self.lock:
            item = self.items.get(found) if isinstance(found, str) and ID.match(found) else None
        if item is None or item[0] != kind:
            raise Missing(f"no {kind} with that id (it may have been closed); start that step again")
        return item[1]

    def drop(self, kind, found):
        with self.lock:
            if found in self.items and self.items[found][0] == kind:
                self._drop(found)

    def _drop(self, found):
        kind, value = self.items.pop(found)
        folder = value.get("folder") if isinstance(value, dict) else None
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)

    def new_folder(self):
        """A folder of its own inside the run's folder, named here."""
        folder = self.folder / secrets.token_urlsafe(16)
        folder.mkdir(mode=0o700)
        return folder

    def manuscript_name(self, folder, declared):
        """The name an uploaded manuscript file is stored under inside ``folder``: its own
        base name when that is plain letters, digits, '-' and '_' with a manuscript suffix
        (TeX's \\input and \\@input find files by name), otherwise a name made here. None when
        the suffix is not one of MANUSCRIPT_TYPES."""
        declared = str(declared or "")
        stem, dot, suffix = declared.rpartition(".")
        suffix = (dot + suffix).lower()
        if suffix not in MANUSCRIPT_TYPES:
            return None
        if not PLAIN_NAME.match(stem) or (folder / (stem + suffix)).exists():
            stem = "paper-" + secrets.token_hex(4)
        return stem + suffix
