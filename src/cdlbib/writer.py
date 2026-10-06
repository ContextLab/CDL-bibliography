"""The one transactional writer of a library's own files (cdl.bib and the key-rename ledger).
``complete.apply`` and ``desk.save_edit`` plan their text and hand it here. Nothing here
prints or prompts; the caller holds the library's write lock (library.serialized).

Whole files are prepared beside their targets, flushed, and moved into place only when every
target still holds the bytes the caller planned from. Folders are opened once and held, and
every file is read, made, replaced and removed by name within a held folder, through one
descriptor, refusing links: nothing is checked by path and then used by path. A program that
ignores the lock and saves cdl.bib itself while a write is under way is not written over:
the file is exchanged with the prepared one in a single step after the backups are made, and
what it held at that step is compared with what the writer read; anything else is exchanged
back and the write refused; and a save the other program makes over the new text in the
instant after the exchange is left as it is (the check is two stat calls, made before the
folder is flushed to the disk: on Linux that flush takes long enough for another program's
save to land in it).

What is guaranteed against a program that swaps paths for links while a write runs, on macOS
and on Linux alike. Every name is changed by the C library's rename that takes flags, within
a folder held open: renameatx_np with RENAME_SWAP (exchange) or RENAME_EXCL (a name not in
use) on macOS, renameat2 with RENAME_EXCHANGE or RENAME_NOREPLACE on Linux. Where the system
or the file system has no such call, the write is refused with a message (NO_ATOMIC_RENAME)
and nothing is renamed any other way. (Run for real on APFS on macOS, and on overlayfs, tmpfs
and ext4 on Linux.)

- nothing outside the folders held open is read, written, replaced or removed: a link is
  never followed, whenever it is put in place;
- a name is taken for the file the writer made or read only while the writer holds that file
  open. (device, inode) alone does not say so: Linux file systems give a removed file's inode
  number to the next file or link made, so a link swapped in for a prepared file can carry
  the prepared file's number. macOS's APFS does not reuse numbers; the writer does not rely
  on that;
- a new file gets permission bits only (never set-user-ID, set-group-ID or sticky), read from
  the descriptor of the file it replaces and set on its own descriptor before it has a name
  anyone reads;
- after every rename the name is opened again without following a link and compared with the
  descriptor held on the file that was written; when it is anything else the rename is undone;
- a write returns as done only when the bibliography is the file the writer prepared. The
  system renames by name, so a link swapped in for the prepared file in the instant before
  the exchange can stand as the bibliography for the two stat calls that follow; it is found
  there, the file that was read is exchanged back, or, when that file was taken away
  meanwhile, its text is written again, and the write is refused. A write that is refused
  leaves an ordinary file holding what was read, never a link.

A program that can write in the library's folder can of course replace cdl.bib itself at any
time; no writer can prevent that, and the next write refuses a bibliography that is a link.

Before the first move:

- the managed library takes its command checkpoint (library.completion_checkpoint) and
  records the write as in progress (library._mark); a writer killed part-way is announced by
  every later command until `cdlbib update --undo` restores that backup;
- any other library gets a copy of cdl.bib as it was, <.bibcheck>/edits/<UTC stamp>-<name>
  (the newest KEEP_EDITS are kept), and a record of the write in progress beside it. A writer
  killed part-way is settled by the next write (``recover``): files the dead writer had
  already replaced are put back from those copies, so the library is whole again as it was.
"""
import contextlib
import ctypes
import datetime
import errno
import functools
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CdlbibError

EDITS = "edits"                      # under the library's .bibcheck/
KEEP_EDITS = 20                      # pre-write copies kept for a library cdlbib does not manage
PENDING = "write-in-progress.json"


@dataclass
class Written:
    backup: object = None            # managed library: the library.Backup taken before the write
    saved_copy: Path | None = None   # any other library: the copy of cdl.bib as it was
    notes: list = field(default_factory=list)


def require_protectable(ws):
    """A bibliography inside the managed library other than its cdl.bib is refused: the
    managed backup would not hold it."""
    from . import api, library
    if api.is_managed(ws) and ws.bib.resolve() != (library.path() / 'cdl.bib').resolve():
        raise CdlbibError('The managed backup cannot protect this named bibliography; use the managed cdl.bib')


def renames_recorded(ws, renamed, reason):
    """(the key-rename ledger, its bytes now or None, its bytes with ``renamed`` {old: new}
    appended): one record per rename, dated today, with no commit yet. ValueError when the
    ledger is not a list of records."""
    ledger = ws.key_renames
    original = ledger.read_bytes() if ledger.exists() else None
    records = json.loads(original) if original is not None else []
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError('The key rename ledger must be a list of records')
    records += [dict(old_key=old, new_key=new, date=datetime.date.today().isoformat(), reason=reason, commit=None)
                for old, new in renamed.items()]
    return ledger, original, (json.dumps(records, indent=1, ensure_ascii=False) + '\n').encode('utf-8')


def _sha(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


# Every file below is reached by NAME from a folder held open, never again by its path: a
# folder is opened once (refusing a link), a file is opened once (refusing a link), checked
# and read through that one descriptor, and created, replaced and removed relative to the
# folder's descriptor. Swapping a path for a link between a check and a use therefore cannot
# send a write or a removal anywhere else.
#
# "Is this name still the file I made (or read)?" is asked by (device, inode, kind of file),
# and only while a descriptor on that file is held open. The descriptor is what makes the
# answer true: a file system may give the inode number of a removed file to the next thing
# made (ext4 and tmpfs on Linux do so at once; APFS on macOS does not reuse them), so a link
# put where a removed file stood can carry its number. A file with an open descriptor is not
# gone, and its number is nobody else's.

_OPEN = os.O_CLOEXEC | os.O_NOFOLLOW


class _Folder:
    """A folder opened once and held."""

    def __init__(self, path, fd):
        self.path, self.fd = Path(path), fd
        self._made = {}      # the name of a file made here: a descriptor held on it while the name is used

    @classmethod
    def at(cls, path):
        return cls(path, os.open(path, os.O_RDONLY | os.O_DIRECTORY | _OPEN))

    def sub(self, name, create=False):
        """The folder ``name`` in this one (made first with ``create``); None when it is not
        there. OSError when ``name`` is a link or not a folder."""
        if create:
            with contextlib.suppress(FileExistsError):
                os.mkdir(name, dir_fd=self.fd)
        try:
            return _Folder(self.path / name, os.open(name, os.O_RDONLY | os.O_DIRECTORY | _OPEN, dir_fd=self.fd))
        except FileNotFoundError:
            return None

    def close(self):
        for name in list(self._made):
            self._let_go(name)
        os.close(self.fd)

    def _let_go(self, name):
        fd = self._made.pop(name, None)
        if fd is not None:
            os.close(fd)

    def read(self, name):
        """(the bytes, the permission bits) of the ordinary file ``name``, through one
        descriptor; (None, None) when there is none. OSError when it is a link or anything
        but an ordinary file."""
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | _OPEN, dir_fd=self.fd)
        except FileNotFoundError:
            return None, None
        with os.fdopen(fd, 'rb') as stream:
            found = os.fstat(stream.fileno())
            if not stat.S_ISREG(found.st_mode):
                raise OSError(errno.EINVAL, 'not an ordinary file', str(self.path / name))
            return stream.read(), found.st_mode & 0o777

    def read_held(self, name, keep):
        """(the bytes, the stamp) of the ordinary file ``name``, read through one descriptor
        that stays open until ``keep`` (an ExitStack) closes, and that descriptor; (None,
        None, None) when there is none. While it is open, a name whose ``stamp`` is this one
        is this very file, not written since it was read. OSError when it is a link or not an
        ordinary file."""
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | _OPEN, dir_fd=self.fd)
        except FileNotFoundError:
            return None, None, None
        keep.callback(os.close, fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, 'not an ordinary file', str(self.path / name))
        data = b''
        while chunk := os.read(fd, 1 << 20):
            data += chunk
        found = os.fstat(fd)
        return data, (found.st_dev, found.st_ino, stat.S_IFMT(found.st_mode), found.st_mtime_ns, found.st_size), fd

    def identity(self, name):
        """(device, inode, kind of file) of what ``name`` is now (a link is itself); None when
        not there. It says which file a name is only while a descriptor is held on the file
        it is compared with (see above)."""
        try:
            found = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        return found.st_dev, found.st_ino, stat.S_IFMT(found.st_mode)

    def ordinary(self, name):
        """Is ``name`` an ordinary file now (not a link, a folder, or absent)?"""
        try:
            return stat.S_ISREG(os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_mode)
        except FileNotFoundError:
            return False

    def stamp(self, name):
        """(device, inode, kind of file, mtime_ns, size) of what ``name`` is now; None when
        not there. It changes when the file is replaced by another (as ``identity``), and
        when it is written in place."""
        try:
            found = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        return found.st_dev, found.st_ino, stat.S_IFMT(found.st_mode), found.st_mtime_ns, found.st_size

    def new(self, prefix, data, mode=None):
        """Make a file that was not there, write ``data`` to it and flush it to the disk.
        Returns (its name, its identity). A descriptor on the file is held until the name is
        moved or removed (or the folder closed), so that its identity is no other file's."""
        while True:
            name = prefix + secrets.token_hex(6)
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN, 0o600, dir_fd=self.fd)
                break
            except FileExistsError:
                continue
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                if mode is not None:                 # permission bits only: never set-user-ID, set-group-ID or sticky
                    os.fchmod(stream.fileno(), mode & 0o777)
                os.fsync(stream.fileno())
                found = os.fstat(stream.fileno())
                self._made[name] = os.dup(stream.fileno())
        except BaseException:
            self.remove(name)
            raise
        return name, (found.st_dev, found.st_ino, stat.S_IFMT(found.st_mode))

    def is_file_of(self, name, fd):
        """Is ``name`` now the very file that ``fd`` is open on? Asked of the file itself:
        ``name`` is opened here without following a link, and the two descriptors' (device,
        inode) are compared. Returns that file's stat result, or None (also when ``name`` is
        a link, not an ordinary file, or absent)."""
        if fd is None:
            return None
        try:
            probe = os.open(name, os.O_RDONLY | os.O_NONBLOCK | _OPEN, dir_fd=self.fd)
        except OSError:
            return None
        try:
            found, held = os.fstat(probe), os.fstat(fd)
        finally:
            os.close(probe)
        same = (found.st_dev, found.st_ino) == (held.st_dev, held.st_ino) and stat.S_ISREG(found.st_mode)
        return found if same else None

    def is_made(self, name, now=None):
        """Is ``now`` (default: ``name`` itself) the file made here as ``name``? (``is_file_of``
        the descriptor held on it since it was made.)"""
        return self.is_file_of(name if now is None else now, self._made.get(name)) is not None

    def move(self, name, onto, identity=None, replace=True):
        """Put the file made here as ``name`` in the place of ``onto``, both by name in this
        folder, in one step that follows no link and never falls back to a plain rename: the
        name is taken when nothing is there (FileExistsError without ``replace`` when
        something is), else the two are exchanged and what stood there is removed. Refused
        (OSError) when ``name`` is no longer that file, or the file system has no such step.
        Afterwards ``onto`` is opened and compared with the descriptor held on the file made:
        when it is something else, an exchange is undone (a link moved into an empty place is
        removed) and False is returned. ``identity`` is what ``new`` returned, checked too."""
        if not self.is_made(name) or (identity is not None and self.identity(name) != identity):
            raise OSError(errno.ESTALE, 'the prepared file was replaced by something else', str(self.path / name))
        try:
            self._rename(name, onto, 1)
            exchanged = False
        except FileExistsError:
            if not replace:
                raise
            self._rename(name, onto, 0)
            exchanged = True
        placed = self.is_made(name, onto)
        if exchanged and placed:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=self.fd)         # what stood there before
        elif exchanged:
            with contextlib.suppress(FileNotFoundError):
                self._rename(name, onto, 0)
        elif not placed and not self.ordinary(onto):
            with contextlib.suppress(FileNotFoundError, IsADirectoryError, PermissionError):
                os.unlink(onto, dir_fd=self.fd)
        self.flush()
        self._let_go(name)
        return placed

    def _rename(self, name, onto, which, flags=None):
        """The C library's atomic rename of ``name`` to ``onto`` within this folder: an
        exchange of the two (``which`` 0), or a move that takes no name already in use
        (``which`` 1: FileExistsError). OSError(ENOTSUP) where the system or the file system
        has neither: nothing is then done, and nothing is renamed any other way. (``flags``:
        the call's flags as given, for a test of a combination no system accepts.)"""
        calls = _exchange()
        if calls is not None:
            flags = calls[1 + which] if flags is None else flags
            if calls[0](self.fd, os.fsencode(name), self.fd, os.fsencode(onto), flags) == 0:
                return
            code = ctypes.get_errno()
            if code not in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
                raise OSError(code, os.strerror(code), str(self.path / onto))
        raise OSError(errno.ENOTSUP, NO_ATOMIC_RENAME, str(self.path / onto))

    def exchange(self, name, onto):
        """Exchange the two names in this folder in one step (each then names what the other
        named), so that what ``onto`` held can be looked at after the fact and put back.
        OSError(ENOTSUP), with nothing done, where the system or the file system has no such
        call. The folder is not flushed to the disk here (``flush``): the caller looks first."""
        self._rename(name, onto, 0)
        return True

    def flush(self):
        """Flush the folder's names to the disk (where the system does that for a folder)."""
        with contextlib.suppress(OSError):
            os.fsync(self.fd)

    def put(self, name, data, mode=None):
        """Replace ``name`` with ``data`` whole (None: remove it)."""
        if data is None:
            self.remove(name)
            return
        made, identity = self.new('.rollback-', data, mode)
        try:
            if not self.move(made, name, identity):
                raise OSError(errno.ESTALE, 'the file was replaced by something else while it was written',
                              str(self.path / name))
        except BaseException:
            self.remove(made)
            raise

    def remove(self, name):
        """Remove the name (a link itself, never what it points to)."""
        try:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=self.fd)
        finally:
            self._let_go(name)

    def names(self):
        return os.listdir(self.fd)


NO_ATOMIC_RENAME = ("this system or file system cannot exchange two names in one step (renameat2 on Linux, "
                    "renameatx_np on macOS), so cdlbib does not replace the file: it would have to rename it "
                    "blind. Nothing was written; keep the library on a local disk")


@functools.lru_cache(maxsize=1)
def _exchange():
    """(the C library's rename that takes flags, its flag for exchanging two names atomically,
    its flag for refusing a name in use): renameatx_np with RENAME_SWAP and RENAME_EXCL on
    macOS, renameat2 with RENAME_EXCHANGE and RENAME_NOREPLACE on Linux; None where there is
    none."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        call = getattr(libc, "renameatx_np" if sys.platform == "darwin" else "renameat2")
    except (OSError, AttributeError):
        return None
    call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    call.restype = ctypes.c_int
    return (call, 2, 4) if sys.platform == "darwin" else (call, 2, 1)


class _Changed(Exception):
    """A target held something other than what the caller planned from, found at the replacement."""


class _Held(contextlib.ExitStack):
    """The folders of one write, each opened once: the bibliography's, the ledger's, and
    <.bibcheck>/edits."""

    def __init__(self, ws):
        super().__init__()
        self.ws, self.found = ws, {}

    def _keep(self, name, folder):
        if folder is not None:
            self.callback(folder.close)
        self.found[name] = folder
        return folder

    def bib(self):
        if "bib" not in self.found:
            self._keep("bib", _Folder.at(self.ws.bib.parent))
        return self.found["bib"]

    def folder(self, target, create=False):
        """The held folder of ws.bib or ws.key_renames (None when the ledger's is not there
        and is not to be made). Any other file is not the writer's to touch."""
        if target == self.ws.bib:
            return self.bib()
        if target != self.ws.key_renames:
            raise CdlbibError("The writer replaces only the bibliography and the key-rename ledger; nothing was written")
        if self.found.get("renames") is None:
            if self.ws.root == self.ws.bib.parent:
                root = self.bib()
            elif "root" in self.found:
                root = self.found["root"]
            else:
                root = self._keep("root", _Folder.at(self.ws.root))
            self._keep("renames", root.sub(target.parent.name, create))
            if create and self.found["renames"] is None:
                raise OSError(errno.ENOENT, 'the folder was moved away while it was being used', str(target.parent))
        return self.found["renames"]

    def edits(self, create=False):
        """<.bibcheck>/edits, held (None when it is not there and is not to be made).
        CdlbibError when .bibcheck or edits is a link or not a folder: copies are never
        written, read or removed through a link."""
        if self.found.get("edits") is None:
            for name, parent, child in (("work", self.bib, self.ws.work.name), ("edits", lambda: self.found["work"], EDITS)):
                if self.found.get(name) is None:
                    try:
                        self._keep(name, parent().sub(child, create))
                    except OSError as exc:
                        if isinstance(exc, PermissionError):
                            raise
                        raise CdlbibError(f"{self.ws.work if name == 'work' else self.ws.work / EDITS} is not an "
                                          "ordinary folder, so cdlbib will not keep or remove copies there; nothing "
                                          "was changed.") from exc
                if self.found[name] is None:
                    if create:     # made and gone again before it could be opened: someone is moving it about
                        raise CdlbibError(f"{self.ws.work} was moved away while it was being used, so no copy "
                                          "could be kept there; nothing was changed.")
                    return None
        return self.found["edits"]


# The record of a write in progress is a file in a folder that other tools, a sync service or a
# cloned repository can put files in, so it is read as data about two fixed files and never as
# a list of paths: the files are ws.bib ("bib") and ws.key_renames ("renames"), their copies
# are <edits>/<stamp>-<file name>, and a prepared file is a name (never a path) of the exact
# form the writer makes, beside its target. Everything is checked (schema, names, ordinary
# files that are not links, sha256) before anything is restored or removed.

_STAMP = re.compile(r"\d{8}T\d{6}\.\d{6}Z")
_SHA = re.compile(r"[0-9a-f]{64}")


def _records(held, folder, create=False):
    """The held folder <.bibcheck>/<folder> (None when it is not there and is not to be made);
    CdlbibError when .bibcheck or it is a link or not a folder."""
    if not re.fullmatch(r"[a-z][a-z-]{0,40}", folder) or folder == EDITS:
        raise CdlbibError(f"{folder!r} is not a folder cdlbib keeps records in")
    try:
        work = held.bib().sub(held.ws.work.name, create)
        if work is None:
            return None
        held.callback(work.close)
        kept = work.sub(folder, create)
        if kept is not None:
            held.callback(kept.close)
        return kept
    except PermissionError:
        raise
    except OSError as exc:
        raise CdlbibError(f"{held.ws.work / folder} is not an ordinary folder, so cdlbib will not keep records "
                          "there; nothing was changed.") from exc


def _record_name(name):
    if not re.fullmatch(r"[A-Za-z0-9_%+=@,~-][A-Za-z0-9_.%+=@,~-]{0,200}", name):
        raise CdlbibError(f"{name!r} is not a name a record can be kept under")
    return name


def keep_record(ws, folder, name, data):
    """Write ``data`` (bytes) as <.bibcheck>/<folder>/<name>, whole and flushed, readable by
    the user only. Folders are opened once, refusing links; the file is made new and moved
    into place by name (as every file this module writes)."""
    with _Held(ws) as held:
        _records(held, folder, create=True).put(_record_name(name), data)
    return ws.work / folder / name


def records(ws, folder):
    """{name: bytes} of the ordinary files in <.bibcheck>/<folder> ({} when there is none).
    Links and anything that is not an ordinary file are passed over."""
    found = {}
    if not os.path.lexists(ws.bib.parent):
        return found
    with _Held(ws) as held:
        kept = _records(held, folder)
        for name in sorted(kept.names()) if kept is not None else ():
            try:
                data = kept.read(name)[0]
            except OSError:
                continue
            if data is not None:
                found[name] = data
    return found


def drop_record(ws, folder, name):
    """Remove <.bibcheck>/<folder>/<name> (the name itself, never what a link points to), and
    the folder when that empties it."""
    with _Held(ws) as held:
        kept = _records(held, folder)
        if kept is None:
            return
        kept.remove(_record_name(name))
    with contextlib.suppress(OSError):
        os.rmdir(ws.work / folder)       # only ever an empty folder (a link in its place is not removed)


def _targets(ws):
    return {"bib": ws.bib, "renames": ws.key_renames}


def _record(ws, raw):
    """The record of the write in progress (``raw``: its bytes), checked: (stamp, {name:
    (before, after)}, {name: the prepared file's name}). ValueError when it is not exactly
    what _copies writes."""
    data = json.loads(raw.decode('utf-8'))
    known = _targets(ws)
    if not isinstance(data, dict) or set(data) != {"stamp", "targets", "staged"}:
        raise ValueError("unexpected contents")
    stamp, targets, staged = data["stamp"], data["targets"], data["staged"]
    if not isinstance(stamp, str) or not _STAMP.fullmatch(stamp):
        raise ValueError("the time stamp is not one")
    if (not isinstance(targets, dict) or not isinstance(staged, dict) or "bib" not in targets
            or not set(targets) <= set(known) or set(staged) != set(targets)):
        raise ValueError("it names files a write does not touch")
    found = {}
    for name, item in targets.items():
        if not isinstance(item, dict) or set(item) != {"before", "after"}:
            raise ValueError(f"unexpected contents for {name}")
        before, after = item["before"], item["after"]
        if not (before is None or (isinstance(before, str) and _SHA.fullmatch(before))) or not (
                isinstance(after, str) and _SHA.fullmatch(after)) or (name == "bib" and before is None):
            raise ValueError(f"the checksums of {name} are not checksums")
        prepared = staged[name]
        if not isinstance(prepared, str) or not re.fullmatch(
                r"\." + re.escape(known[name].name) + r"-[A-Za-z0-9_]{1,32}", prepared):
            raise ValueError(f"the prepared file of {name} does not have a name the writer gives")
        found[name] = (before, after)
    return stamp, found, staged


def interrupted(ws):
    """For a library cdlbib does not manage: the copy of cdl.bib taken before a write that
    did not finish ('' when the record of it cannot be read); None when there is none.
    Read-only. (The managed library's is library.interrupted.)"""
    if not os.path.lexists(ws.work / EDITS / PENDING):
        return None
    try:
        with _Held(ws) as held:
            raw = held.edits().read(PENDING)[0]
            return str(ws.work / EDITS / f"{_record(ws, raw)[0]}-{ws.bib.name}")
    except (OSError, ValueError, AttributeError, CdlbibError):
        return ""


def recover(ws):
    """Settle a write to an unmanaged library that was killed part-way, with the lock held.
    Returns the lines saying what was done ([] when there was nothing to settle). Every file
    is compared with what the dead writer recorded: all as before, or all as it meant to
    leave them, needs nothing; some replaced and some not, and the replaced ones are put back
    from the copies it took. Only ws.bib, ws.key_renames, their copies in <.bibcheck>/edits
    and the writer's prepared files beside them are ever touched: the record names no path,
    and each is reached by its fixed name from a folder held open, read once, and restored
    from the bytes that were read and checked. A record that is not exactly what the writer
    writes, a file or folder that is a link, a file that is neither as before nor as planned
    (someone changed it since), or a copy or prepared file whose checksum is not the
    recorded one stops this with a CdlbibError before anything is touched. The managed
    library is not handled here: its lock refuses until the backup is restored."""
    from . import api
    marker = ws.work / EDITS / PENDING
    if api.is_managed(ws) or not os.path.lexists(ws.bib.parent):
        return []
    with _Held(ws) as held:
        edits = held.edits()
        if edits is None:
            return []
        try:
            raw = edits.read(PENDING)[0]
            if raw is None:
                return []
            stamp, recorded, staged = _record(ws, raw)
        except (OSError, ValueError) as exc:
            raise CdlbibError(f"An earlier write to {ws.bib} was interrupted and its record ({marker}) cannot be "
                              f"used ({exc}); nothing was changed. The copies taken before each write are in "
                              f"{ws.work / EDITS}.") from exc
        known = _targets(ws)
        copy = ws.work / EDITS / f"{stamp}-{ws.bib.name}"

        def refuse(why):
            return CdlbibError(f"An earlier write to {ws.bib} was interrupted, and {why}; nothing was changed now. "
                               f"The record of that write is {marker}; the bibliography as it was before it is {copy}.")

        # Read and check everything first; nothing is changed until all of it holds.
        folders, now, saved, prepared = {}, {}, {}, []
        for name, (before, after) in recorded.items():
            target = known[name]
            try:
                folders[name] = folder = held.folder(target)
                current = folder.read(target.name)[0] if folder is not None else None
            except OSError as exc:
                raise refuse(f"{target} is not an ordinary file in an ordinary folder") from exc
            now[name] = _sha(current)
            if now[name] not in (before, after):
                raise CdlbibError(f"An earlier write to {ws.bib} was interrupted, and the library was changed since; "
                                  f"nothing was changed now. The bibliography as it was before that write is {copy}. "
                                  f"Compare the two, then delete {marker}.")
            kept = f"{stamp}-{target.name}"
            try:
                held_copy = edits.read(kept)[0]
                waiting = folder.read(staged[name])[0] if folder is not None else None
            except OSError as exc:
                raise refuse(f"a copy or prepared file of {target} is not an ordinary file") from exc
            if held_copy is not None:
                if _sha(held_copy) != before:
                    raise refuse(f"the copy {ws.work / EDITS / kept} is not the file that write saved")
                saved[name] = held_copy
            if waiting is not None:
                if _sha(waiting) not in (before, after):      # the new file, or the old one it was exchanged with
                    raise refuse(f"the prepared file {target.parent / staged[name]} is not the one that write made")
                prepared.append((folder, staged[name]))
        replaced = [name for name, (before, after) in recorded.items() if now[name] == after and before != after]
        whole = not replaced or len(replaced) == len([1 for before, after in recorded.values() if before != after])
        if not whole:
            for name in replaced:
                if recorded[name][0] is not None and name not in saved:
                    raise refuse(f"the copy of {known[name]} from before it is missing")
            try:
                for name in replaced:      # from the bytes that were read and checked, by name in the held folder
                    folders[name].put(known[name].name, saved.get(name))
            except OSError as exc:
                raise refuse(f"the library could not be put back ({exc})") from exc
        for folder, name in prepared:
            folder.remove(name)
        for name in saved:
            if name != "bib":
                edits.remove(f"{stamp}-{known[name].name}")
        edits.remove(PENDING)
    if not whole:
        return [f"an earlier write to {ws.bib} was interrupted part-way; the library was put back as it was before "
                f"that write (the bibliography as it was is also in {copy})"]
    if replaced:
        return [f"an earlier write to {ws.bib} was interrupted just after it had written everything; nothing is missing"]
    return [f"an earlier write to {ws.bib} was interrupted before anything was written; the library is as it was"]


def _copies(held, staged, writes):
    """Copy what is about to be replaced into <.bibcheck>/edits and record the write as in
    progress (logical names, checksums and the prepared files' names: no path). Returns (the
    copy of the bibliography, the names of the copies only a recovery needs)."""
    ws = held.ws
    edits = held.edits(create=True)
    names = {path: name for name, path in _targets(ws).items()}
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    after = dict(writes)
    targets, prepared, copy, extra = {}, {}, None, []
    for target, _, temporary, _, previous in staged:
        if previous is not None:
            edits.put(f"{stamp}-{target.name}", previous)
            if target == ws.bib:
                copy = ws.work / EDITS / f"{stamp}-{target.name}"
            else:
                extra.append(f"{stamp}-{target.name}")
        targets[names[target]] = {"before": _sha(previous), "after": _sha(after[target])}
        prepared[names[target]] = temporary
    edits.put(PENDING, json.dumps({"stamp": stamp, "targets": targets, "staged": prepared}, indent=1).encode('utf-8'))
    return copy, extra


def _prune(held):
    """Keep the copies of the newest KEEP_EDITS writes. Only ordinary files in the held edits
    folder whose names are exactly <stamp>-<a file the writer copies> are ever removed."""
    edits = held.edits()
    copied = "|".join(re.escape(path.name) for path in _targets(held.ws).values())
    named = {name: match[1] for name in edits.names()
             if (match := re.fullmatch(r"(\d{8}T\d{6}\.\d{6}Z)-(?:" + copied + ")", name))}
    old = sorted(set(named.values()), reverse=True)[KEEP_EDITS:]
    for name, stamp in named.items():
        if stamp in old:
            with contextlib.suppress(OSError):
                if stat.S_ISREG(os.stat(name, dir_fd=edits.fd, follow_symlinks=False).st_mode):
                    edits.remove(name)


def _put_back(folder, target, previous, mode):
    """Make ``target`` hold ``previous`` again (an ordinary file with the permission bits
    ``mode``) where a link or nothing was left in its place. CdlbibError when even that is
    undone as it is made."""
    try:
        folder.put(target.name, previous, mode)
    except OSError as exc:
        raise CdlbibError(f"{target} was swapped for something that is not a file while it was being written, and "
                          f"could not be put back ({exc.strerror or exc}); look at it before anything else is done. "
                          "Its text from before this write is in the copy taken for it.") from exc


def _confirm(folder, target, name, identity, seen, read_fd, previous):
    """Straight after ``name`` (the prepared file, of ``identity``) and ``target`` were
    exchanged: look at what the two names are now. The file that came out must be the very
    file that was read (``seen``: its stamp, ``read_fd``: the descriptor still held on it),
    and the target the prepared file. That takes two stat calls, so the new text stands
    unconfirmed for an instant only (the folder is flushed to the disk after this, not
    before). Returns when the write stands; otherwise leaves the newest save of anyone else
    in place, or the text that was read, and raises _Changed:

    - something else came out (another program saved between the reading and the exchange):
      the two are exchanged back, so that save stays; and should the other program have
      saved once more over the new text in that instant, its newest save is the one left;
    - the target is no longer the prepared file though the file that was read came out:
      another program saved over the new text in that instant, and its save (an ordinary
      file) is left as it is: exchanging back would discard it;
    - the target is a link, or nothing: the prepared name was swapped for it just before the
      exchange (it is exchanged back), or the file that stood aside was taken away before it
      could come back (its text, ``previous``, is written again). No save of anyone leaves a
      link or nothing, so neither is kept."""
    # Both questions are asked of the files themselves: each name is opened without following
    # a link and compared with the descriptor held on the file prepared, and on the file read.
    made = folder._made.get(name)
    placed = folder.is_file_of(target.name, made) is not None
    out = folder.is_file_of(name, read_fd)
    unwritten = out is not None and (out.st_mtime_ns, out.st_size) == seen[3:]
    if placed and out is None and folder.identity(name) is None:
        # What came out was removed at once by something else. When the file that was read is
        # the one now without a name, and it was not written, nothing was lost.
        left = os.fstat(read_fd)
        unwritten = left.st_nlink == 0 and (left.st_mtime_ns, left.st_size) == seen[3:]
    if placed and unwritten:
        folder.flush()
        return
    try:
        if placed or not folder.ordinary(target.name):
            try:
                folder.exchange(name, target.name)
            except FileNotFoundError:
                came_back = False
            else:
                came_back = True
                # The new text was in place and is not what came back: the other program saved
                # once more over it, and that newest save (an ordinary file) is the one to leave.
                if placed and folder.is_file_of(name, made) is None and folder.ordinary(name):
                    folder.exchange(name, target.name)
            if not came_back or not folder.ordinary(target.name):
                _put_back(folder, target, previous, os.fstat(read_fd).st_mode & 0o777)
    finally:
        folder.flush()
    raise _Changed(target)


def commit(ws, writes, expected, *, batch=None, operation="entry completion"):
    """Install ``writes`` ([(path, bytes)], the bibliography first; only ws.bib and
    ws.key_renames are taken) and return a Written. ``expected`` gives, for each path, the
    bytes the caller read and planned from (None: the file was not there); a file that holds
    anything else by now, read through one descriptor just before the replacements, refuses
    the whole write with a CdlbibError ("changed while applying") and nothing is replaced.
    ``batch`` is the managed command's library.CompletionBatch, ``operation`` the name an
    interrupted write is announced by. Each file is prepared as a new file beside its target,
    flushed to the disk, and moved onto the target by name within the folder held open; a
    prepared file or target that turns out to be something else, or a move that fails, puts
    back the files already moved and raises OSError."""
    from . import api, library
    done, staged = Written(), []
    with _Held(ws) as held:
        try:
            # Prepare every file before replacing either, so permission/disk failures
            # during preparation leave both originals intact.
            for target, data in writes:
                folder = held.folder(target, create=True)
                name, identity = folder.new('.' + target.name + '-', data, folder.read(target.name)[1])
                staged.append((target, folder, name, identity, expected[target]))
            for target, folder, _, _, previous in staged:
                if folder.read(target.name)[0] != previous:
                    raise CdlbibError(f'{target} changed while applying; nothing was written')
            managed, extra = api.is_managed(ws), []
            if managed:
                done.backup = library.completion_checkpoint(ws, batch)
                library._mark(done.backup, operation)
            else:
                done.saved_copy, extra = _copies(held, staged, writes)
            installed = []
            try:
                # The backups are made; only now is each file read again and compared with what
                # the caller planned from, and replaced. A file that is there is exchanged with
                # the prepared one in one step, and what came out is checked to be the file that
                # was just read: when it is not (something saved it meanwhile, however late),
                # the two are exchanged back, so that save stays, and the write is refused.
                # A file that is not there yet takes its name only while the name is free.
                for target, folder, name, identity, previous in staged:
                    # The replacement is made by name within the held folder, so an auditor
                    # sees names only; the full paths are announced under the same event.
                    sys.audit("os.rename", str(target.parent / name), str(target), -1, -1)
                    if not folder.is_made(name) or folder.identity(name) != identity:
                        raise OSError(errno.ESTALE, 'the prepared file was replaced by something else',
                                      str(target.parent / name))
                    with contextlib.ExitStack() as reading:
                        # The file read stays open until the exchange has been looked at, so
                        # "the very file just read" below cannot be another with its number.
                        current, seen, read_fd = folder.read_held(target.name, reading)
                        if current != previous:
                            raise _Changed(target)
                        if previous is not None and folder.exchange(name, target.name):
                            _confirm(folder, target, name, identity, seen, read_fd, previous)
                            installed.append((target, folder, previous))
                            continue
                    try:        # nothing was there: the name is taken only if it is still free
                        intact = folder.move(name, target.name, identity, replace=False)
                    except FileExistsError:
                        raise _Changed(target) from None
                    installed.append((target, folder, previous))
                    if not intact:
                        raise OSError(errno.ESTALE, 'the file was replaced by something else while it was written',
                                      str(target))
            except (OSError, _Changed) as stopped:
                # Taking back what was installed: only a file that still holds exactly what
                # this write put there is put back. One that something else has changed since
                # is left as it is, the record of this write stays, and the conflict is said.
                written, conflicts = dict(writes), []
                for target, folder, previous in reversed(installed):
                    try:
                        untouched = folder.read(target.name)[0] == written[target]
                    except OSError:
                        # A link (or anything that is no file) where this write put a file: the
                        # prepared name was swapped for it as it was moved. Not anyone's save.
                        untouched = not folder.ordinary(target.name)
                    try:
                        if not untouched:
                            raise OSError(errno.EBUSY, 'changed by something else', str(target))
                        folder.put(target.name, previous)
                    except OSError:
                        conflicts.append(target)
                if conflicts:
                    from .errors import WriteConflict
                    kept = done.saved_copy or (done.backup.path if done.backup is not None else None)
                    raise WriteConflict(
                        "The write could not be finished and was being taken back, but "
                        + ", ".join(str(target) for target in conflicts) + " was changed by something else in the "
                        "meantime; it was left as it is now. What it held before this write is in " + str(kept)
                        + ". Compare the two" + ("" if managed else f", then delete {ws.work / EDITS / PENDING}") + ".",
                        files=conflicts) from None
                if not managed:
                    edits = held.edits()
                    edits.remove(PENDING)
                    for name in extra:
                        edits.remove(name)
                if isinstance(stopped, _Changed):      # everything is as it was found: no write is in progress
                    if managed:
                        library._unmark()
                    raise CdlbibError(f'{stopped.args[0]} changed while applying; nothing was written') from None
                raise
            if managed:
                library._unmark()
                library._prune(library.backups_folder(), ws.root)
            else:
                edits = held.edits()
                edits.remove(PENDING)
                for name in extra:
                    edits.remove(name)
                _prune(held)
            return done
        finally:
            for _, folder, name, _, _ in staged:
                folder.remove(name)
