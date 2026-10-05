"""The one transactional writer of a library's own files (cdl.bib and the key-rename ledger).
``complete.apply`` and ``desk.save_edit`` plan their text and hand it here. Nothing here
prints or prompts; the caller holds the library's write lock (library.serialized).

Whole files are prepared beside their targets, flushed, and moved into place only when every
target still holds the bytes the caller planned from. Folders are opened once and held, and
every file is read, made, replaced and removed by name within a held folder, through one
descriptor, refusing links: nothing is checked by path and then used by path. What stays
possible is a program that ignores the lock and saves cdl.bib itself in the instant between
the last comparison and the replacement; anything saved before that comparison refuses the
write, and the copy or backup taken first holds what the writer read. Before the first move:

- the managed library takes its command checkpoint (library.completion_checkpoint) and
  records the write as in progress (library._mark); a writer killed part-way is announced by
  every later command until `cdlbib update --undo` restores that backup;
- any other library gets a copy of cdl.bib as it was, <.bibcheck>/edits/<UTC stamp>-<name>
  (the newest KEEP_EDITS are kept), and a record of the write in progress beside it. A writer
  killed part-way is settled by the next write (``recover``): files the dead writer had
  already replaced are put back from those copies, so the library is whole again as it was.
"""
import contextlib
import datetime
import errno
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

_OPEN = os.O_CLOEXEC | os.O_NOFOLLOW


class _Folder:
    """A folder opened once and held."""

    def __init__(self, path, fd):
        self.path, self.fd = Path(path), fd

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
        os.close(self.fd)

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

    def identity(self, name):
        """(device, inode) of what ``name`` is now (a link is itself); None when not there."""
        try:
            found = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        return found.st_dev, found.st_ino

    def new(self, prefix, data, mode=None):
        """Make a file that was not there, write ``data`` to it and flush it to the disk.
        Returns (its name, its identity)."""
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
                if mode is not None:
                    os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
                found = os.fstat(stream.fileno())
        except BaseException:
            self.remove(name)
            raise
        return name, (found.st_dev, found.st_ino)

    def move(self, name, onto, identity):
        """Put the file made here as ``name`` in the place of ``onto``, both by name in this
        folder. Refused (OSError) when ``name`` is no longer that file. Returns whether
        ``onto`` is that file afterwards."""
        if self.identity(name) != identity:
            raise OSError(errno.ESTALE, 'the prepared file was replaced by something else', str(self.path / name))
        os.replace(name, onto, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        with contextlib.suppress(OSError):
            os.fsync(self.fd)
        return self.identity(onto) == identity

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
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name, dir_fd=self.fd)

    def names(self):
        return os.listdir(self.fd)


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
                if _sha(waiting) != after:
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
                for target, folder, name, identity, previous in staged:
                    # The replacement is made by name within the held folder, so an auditor
                    # sees names only; the full paths are announced under the same event.
                    sys.audit("os.rename", str(target.parent / name), str(target), -1, -1)
                    intact = folder.move(name, target.name, identity)
                    installed.append((target, folder, previous))
                    if not intact:
                        raise OSError(errno.ESTALE, 'the file was replaced by something else while it was written',
                                      str(target))
            except OSError:
                for target, folder, previous in reversed(installed):
                    folder.put(target.name, previous)
                if not managed:
                    held.edits().remove(PENDING)
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
