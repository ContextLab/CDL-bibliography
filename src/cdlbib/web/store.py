"""What the web interface keeps between requests, under random ids: proposals, read PDFs,
candidate lists, edit previews, uploaded manuscripts, exports and pending questions. The
browser is given the ids and never the objects' authority: it sends an id back with a
decision. Uploaded files live in one private folder of this run, removed at exit, under names
made here.

Everything is bounded: a count per kind, bytes per kind and in total for what is on disk
(reserved before a request body is read), and expiry of what has not been used for EXPIRY
seconds. When room is needed, what has been idle for IDLE seconds goes first, oldest first;
what is in use is never dropped to make room (the upload is refused instead)."""
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path

ID = re.compile(r"[A-Za-z0-9_-]{22}\Z")
MAX_UPLOAD = 50_000_000  # bytes of one uploaded file (intake.MAX_PDF_BYTES)
MAX_BUNDLE_FILES = 60
MANUSCRIPT_TYPES = (".tex", ".aux", ".bcf")
PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
EXPIRY = 4 * 3600        # seconds an object is kept after its last use
IDLE = 300               # an object idle this long may be dropped to make room
COUNTS = {"proposal": 500, "search": 100, "preview": 100, "decision": 20, "pdf": 20, "bundle": 20, "export": 20}
BYTES = {"pdf": 200_000_000, "bundle": 60_000_000, "export": 100_000_000}     # on disk, per kind
TOTAL_BYTES = 300_000_000


class Missing(KeyError):
    """No object of that kind under that id (never made, or dropped to make room)."""


class Full(Exception):
    """No room for an upload (HTTP 413): the quota of its kind, or the total, is in use."""


class Store:
    def __init__(self):
        self.folder = Path(tempfile.mkdtemp(prefix="cdlbib-web-"))     # mode 0700
        self.items, self.lock = {}, threading.RLock()                  # id -> [kind, value, bytes, last use]
        self.reserved = {}                                             # kind -> bytes promised to requests being read
        self.closed = False

    def close(self):
        with self.lock:
            self.closed = True
            self.items.clear()
        shutil.rmtree(self.folder, ignore_errors=True)

    # --- room ---

    def used(self, kind=None):
        with self.lock:
            held = sum(item[2] for item in self.items.values() if kind in (None, item[0]))
            return held + sum(size for name, size in self.reserved.items() if kind in (None, name))

    def _sweep(self):
        now = time.monotonic()
        for found in [found for found, item in self.items.items() if now - item[3] > EXPIRY]:
            self._drop(found)

    def _make_room(self, kind, count=0, size=0):
        """Drop expired objects, then idle ones of this kind (oldest first), until ``count``
        more objects and ``size`` more bytes fit. False when they still do not."""
        self._sweep()
        now = time.monotonic()

        def fits():
            return (sum(1 for item in self.items.values() if item[0] == kind) + count <= COUNTS[kind]
                    and self.used(kind) + size <= BYTES.get(kind, TOTAL_BYTES) and self.used() + size <= TOTAL_BYTES)
        for found in [found for found, item in self.items.items() if item[0] == kind]:
            if fits():
                break
            item = self.items[found]
            if kind not in BYTES or now - item[3] > IDLE:      # things on disk are dropped only when idle
                self._drop(found)
        return fits()

    def reserve(self, kind, size):
        """Promise ``size`` bytes to an upload about to be read; Full when there is no room.
        Give them back with release() once the upload is stored or refused."""
        with self.lock:
            if self.closed or not self._make_room(kind, size=size):
                raise Full(f"There is no room for this upload: at most {BYTES[kind] // 1_000_000} MB of files of this "
                           f"kind and {TOTAL_BYTES // 1_000_000} MB in all are kept while cdlbib web runs. Files not "
                           f"used for {IDLE // 60} minutes make room for new ones.")
            self.reserved[kind] = self.reserved.get(kind, 0) + size

    def release(self, kind, size):
        with self.lock:
            self.reserved[kind] = max(0, self.reserved.get(kind, 0) - size)

    # --- objects ---

    def put(self, kind, value, size=0):
        found = secrets.token_urlsafe(16)
        with self.lock:
            if self.closed:
                raise Missing("the server is stopping")
            self._make_room(kind, count=1)
            self.items[found] = [kind, value, size, time.monotonic()]
        return found

    def get(self, kind, found):
        with self.lock:
            item = self.items.get(found) if isinstance(found, str) and ID.match(found) else None
            if item is not None and time.monotonic() - item[3] > EXPIRY:
                self._drop(found)
                item = None
            if item is None or item[0] != kind:
                raise Missing(f"no {kind} with that id (it may have been closed); start that step again")
            item[3] = time.monotonic()
            return item[1]

    def drop(self, kind, found):
        with self.lock:
            if found in self.items and self.items[found][0] == kind:
                self._drop(found)

    def _drop(self, found):
        kind, value, size, used = self.items.pop(found)
        folder = value.get("folder") if isinstance(value, dict) else None
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)

    # --- files ---

    def new_folder(self):
        """A folder of its own inside the run's folder, named here."""
        folder = self.folder / secrets.token_urlsafe(16)
        folder.mkdir(mode=0o700)
        return folder

    def add_pdf(self, body):
        with self.lock:
            folder = self.new_folder()
            (folder / "upload.pdf").write_bytes(body)
            return self.put("pdf", {"folder": folder, "path": folder / "upload.pdf", "intake": None}, size=len(body))

    def add_manuscript(self, bundle, declared, body):
        """Store one uploaded manuscript file in ``bundle`` (None: a new one), under the lock:
        the count is checked, the name is reserved by creating the file exclusively, and the
        bundle's list is extended, as one step. Returns (bundle id, the name, the names).
        ValueError when the suffix is not a manuscript's or the bundle is full."""
        declared = str(declared or "")
        stem, dot, suffix = declared.rpartition(".")
        suffix = (dot + suffix).lower()
        if suffix not in MANUSCRIPT_TYPES:
            raise ValueError("only " + ", ".join(MANUSCRIPT_TYPES) + " files are taken")
        with self.lock:
            if bundle is None:
                held = {"folder": self.new_folder(), "files": []}
                bundle = self.put("bundle", held)
            else:
                held = self.get("bundle", bundle)
            if len(held["files"]) >= MAX_BUNDLE_FILES:
                raise ValueError(f"At most {MAX_BUNDLE_FILES} files are taken for one export.")
            # Its own base name when that is plain letters, digits, '-' and '_' (TeX's \input and
            # \@input find files by name); otherwise, or when the name is taken, a name made here.
            names = ([stem] if PLAIN_NAME.match(stem) else []) + ["paper-" + secrets.token_hex(4) for _ in range(5)]
            for name in names:
                try:
                    handle = os.open(held["folder"] / (name + suffix), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    continue
                with os.fdopen(handle, "wb") as out:
                    out.write(body)
                held["files"].append(name + suffix)
                self.items[bundle][2] += len(body)
                return bundle, name + suffix, list(held["files"])
            raise ValueError("no name could be made for this file")
