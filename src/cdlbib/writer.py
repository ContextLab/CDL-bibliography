"""The one transactional writer of a library's own files (cdl.bib and the key-rename ledger).
``complete.apply`` and ``desk.save_edit`` plan their text and hand it here. Nothing here
prints or prompts; the caller holds the library's write lock (library.serialized).

Whole files are prepared beside their targets, flushed, and put in place only when every
target still holds the bytes the caller planned from. Folders are opened once and held, and
every file is read, made and moved by name within a held folder, through one descriptor,
refusing links: nothing is checked by path and then used by path.

HOW A FILE IS REPLACED. The system has no "replace this name if it still holds that": a name
can only be exchanged and looked at afterwards. So the prepared file and the library file
are exchanged in one step (renameatx_np with RENAME_SWAP on macOS, renameat2 with
RENAME_EXCHANGE on Linux, within held folders; a name that is free is taken with RENAME_EXCL
/ RENAME_NOREPLACE; where the system or the file system has no such call the write is refused
with NO_ATOMIC_RENAME, and nothing is renamed any other way). What came out is then looked
at: first whether it is the very file that was read (one descriptor comparison), and then its
content, read through its own descriptor. When it is not what was read, the two are
exchanged back at once and the write is refused.

WHAT IS KEPT, AND FOR HOW LONG. Whatever stood under a library name (cdl.bib, the key-rename
ledger, the approvals ledger), at any instant, is not unlinked when it is replaced, on any
path: not the file a write replaced, not a link or a folder found in a file's place, and not
the writer's own new file once it has stood under the name. Each is moved, by the same
flagged rename from one held folder into another, to one of these places beside the library.
The first two are bounded (a file there is removed when it is KEEP_EDITS writes old, which
is the one way a file that once was a library file is ever removed); the third is not:

- <.bibcheck>/edits/<UTC stamp>-<file name>: the file a successful write replaced IS that
  write's copy (the copy made before the write is exchanged for it). The copies of the
  newest KEEP_EDITS writes are kept; an older one is removed by a later successful write.
  Settling a killed write (``recover``) leaves them where they are, the ledger's too.
- <.bibcheck>/replaced/<UTC stamp>-<file name>: the same for the managed library, which
  keeps no copies in edits (its backup is the command's checkpoint): the files its newest
  KEEP_EDITS writes replaced.
- <.bibcheck>/kept/<UTC stamp>-<random>/: the private folder of one write (made with an
  exclusive mkdir, for the user only, before anything is replaced; removed again when the
  write leaves it empty). In it stay, under names that say what they were: the writer's
  own file that was exchanged back out (<name>.not-installed), the file a write replaced
  when the write was then taken back (<name>.was), and anything unexpected that came out of
  a library name (<name>.found: another program's superseded save, a link, a folder). They
  are named in the error, or in the notes of a write that succeeded, or by the command that
  settles a killed write. cdlbib never removes them and sets no limit on them: each
  conflict and each settled write can leave whole files there, so <.bibcheck>/kept grows
  until the user, having looked, deletes the folders in it (any of them, at any time:
  nothing reads them again once the write they belong to has been settled).

Otherwise only files that never stood under a library name are removed: a prepared file
that was never exchanged in (after it was moved into the private folder and found there to
be that file), and cdlbib's own records under .bibcheck. The record of a write names its
private folder by its stamp, so the command that settles a killed write finds what that
write had kept aside, and says it.

WHAT IS GUARANTEED against a program that ignores the lock, and what is not:

- A program that saves by rename (writes a new file and renames it over cdl.bib, as editors
  do): its save is never deleted. One that lands before the exchange comes out of it and is
  exchanged back; one that lands on the new text just after is left in place.
- A program that overwrites cdl.bib in place: what it writes is never deleted either. Written
  before the exchange, it is found by content and exchanged back. Written after (through a
  descriptor it still holds on the file that was replaced), it is in that write's copy in
  <.bibcheck>/edits (<.bibcheck>/replaced in the managed library), the very file it has
  open, or in the write's private folder; until that copy is KEEP_EDITS writes old.
- NOT guaranteed: which of two saves made at the same moment ends up as the library file.
  For the instant between the exchange and the look at what came out (one open and one
  descriptor comparison when the other save was made by rename; the reading of the file
  when it is the same file), the new text stands under the name unconfirmed. A program that
  READS the bibliography in that instant reads a text that may be exchanged back out; if it
  then saves what it read, with its own change, by rename, it replaces the other program's
  save itself (seen once in about a hundred runs of the test that hammers the file from a
  second process, on a loaded machine). And a program that keeps writing through a
  descriptor on a file that has been replaced is writing into a copy, not into the library.
- A write returns as done only when the library file is the file the writer prepared. When
  it cannot be established what state a file is in (no descriptors left to open it, an
  input/output error, a rename that fails), nothing is claimed: the record of the write in
  progress stays, the error says the file may hold the new text, and the next command
  settles it from that record (``recover``). The record also stays whenever something
  unexpected had to be kept (a <name>.found), until the next command has looked.
- Links: nothing outside the folders held open is read, written, replaced or removed, and a
  link is never followed, whenever it is put in place. A name is taken for the file the
  writer made or read only while the writer holds that file open ((device, inode) alone does
  not say so: Linux gives a removed file's inode number to the next file or link made).
- A new file gets permission bits only (never set-user-ID, set-group-ID or sticky), read
  from the descriptor of the file it replaces and set on its own descriptor before it has a
  name anyone reads; taking a write back and settling a killed one keep them too. A copy in
  <.bibcheck>/edits is readable by the user only.

What is trusted: the folders ABOVE the library's folder. The library's folder is opened once,
by the path the workspace was resolved to, refusing a link as its last name only; a program
that can swap one of the folders above it for a link, between that resolution and that
opening, is not defended against (it owns the place the library is in). And a program that
can write in the library's folder can replace cdl.bib itself at any time; no writer can
prevent that. (Run for real on APFS on macOS, and on overlayfs, tmpfs and ext4 on Linux.)

What is flushed: every folder a name was changed in, after the change; a folder that is made,
with the name it was given in the folder above. An error of such a flush (an input/output
error, a full disk) is raised, before any library file is replaced when it concerns the
copies and the record; only "a folder cannot be flushed here" is passed over
(_NO_FOLDER_FSYNC).

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
REPLACED = "replaced"                # under the managed library's .bibcheck/: the files its newest writes replaced
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
    try:                                 # by name from the folders held open, never through a link
        with _Held(ws) as held:
            folder = held.folder(ledger) if os.path.lexists(ws.bib.parent) else None
            original = folder.read(ledger.name)[0] if folder is not None else None
    except OSError as exc:
        raise CdlbibError(f"{ledger} is a link, or not an ordinary file in an ordinary folder "
                          f"({exc.strerror or exc}); the key-rename ledger is not read through it. Nothing was "
                          "changed.") from exc
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
        self.exposed = set()  # prepared names that were exchanged with a library name (what they hold is not ours to remove)

    @classmethod
    def at(cls, path):
        return cls(path, os.open(path, os.O_RDONLY | os.O_DIRECTORY | _OPEN))

    def sub(self, name, create=False):
        """The folder ``name`` in this one (made first with ``create``); None when it is not
        there. OSError when ``name`` is a link or not a folder. A folder made here is flushed
        to the disk with its name (this folder's entry for it), so that what is then put in it
        does not hang from a name the disk does not hold yet."""
        made = False
        if create:
            try:
                os.mkdir(name, dir_fd=self.fd)
                made = True
            except FileExistsError:
                pass
        try:
            found = _Folder(self.path / name, os.open(name, os.O_RDONLY | os.O_DIRECTORY | _OPEN, dir_fd=self.fd))
        except FileNotFoundError:
            return None
        if made:
            try:
                found.flush()
                self.flush()
            except BaseException:
                found.close()
                raise
        return found

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
        None, None) when there is none. The file's times and size are taken before the read
        and after it: a file written while it was read is not taken for either state
        (_Changed). OSError when it is a link or not an ordinary file."""
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | _OPEN, dir_fd=self.fd)
        except FileNotFoundError:
            return None, None, None
        keep.callback(os.close, fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, 'not an ordinary file', str(self.path / name))
        data, stable, found = _read_fd(fd)
        if not stable:
            raise _Changed(self.path / name)
        return data, (found.st_dev, found.st_ino, stat.S_IFMT(found.st_mode), found.st_mtime_ns, found.st_size), fd

    def look(self, name):
        """What ``name`` is now, asked of the thing itself: ("file", a descriptor on it, opened
        without following a link, for the caller to close), or ("absent", None), ("link",
        None), ("other", None) for a folder, a pipe, a socket or a device. Only the errors
        that mean one of those are answers. Any other failure to open it (no descriptors left,
        an input/output error, no permission) says nothing about what is there and is raised.
        No descriptor is left open when this raises or answers anything but "file"."""
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | _OPEN, dir_fd=self.fd)
        except FileNotFoundError:
            return "absent", None
        except OSError as exc:
            if exc.errno not in _NOT_OPENED_AS_A_FILE:
                raise
            try:
                found = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            except FileNotFoundError:
                return "absent", None
            return ("link" if stat.S_ISLNK(found.st_mode) else "other"), None
        try:
            regular = stat.S_ISREG(os.fstat(fd).st_mode)
        except BaseException:
            os.close(fd)
            raise
        if not regular:
            os.close(fd)
            return "other", None
        return "file", fd

    def kind(self, name):
        """``look`` without keeping the descriptor."""
        kind, fd = self.look(name)
        if fd is not None:
            os.close(fd)
        return kind

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
        inode) are compared. Returns that file's stat result, or None when ``name`` is a
        link, not an ordinary file, absent, or another file. OSError when it cannot be opened
        for a reason that does not say which (``look``)."""
        if fd is None:
            return None
        kind, probe = self.look(name)
        if kind != "file":
            return None
        try:
            found, held = os.fstat(probe), os.fstat(fd)
        finally:
            os.close(probe)
        return found if (found.st_dev, found.st_ino) == (held.st_dev, held.st_ino) else None

    def is_made(self, name, now=None):
        """Is ``now`` (default: ``name`` itself) the file made here as ``name``? (``is_file_of``
        the descriptor held on it since it was made.)"""
        return self.is_file_of(name if now is None else now, self._made.get(name)) is not None

    def install(self, made, onto, expected, aside, read_fd=None):
        """Put the file made here as ``made`` under the library name ``onto`` (both names in
        this folder), where ``onto`` is expected to hold ``expected``: bytes (a file with
        exactly them), None (nothing: the name is taken only while it is free,
        FileExistsError otherwise), ANY_FILE (any ordinary file) or A_LINK (a link, which is
        nobody's save: it is kept aside and replaced, without the name ever being free).

        Nothing that stands under a library name, or ever stood under one, is removed here:
        not what the exchange pushed aside, not a link or a folder found in its place, and not
        the file made once it has stood under the name (another program may have written into
        it there). Each is MOVED, by the same flagged rename, into ``aside`` (an _Aside: the
        private folder of this write), where it stays under a name that says what it was.

        The two names are exchanged in one step, and then looked at, each opened without
        following a link. First the quick question, whether what came out is another file
        than the one that was read (``read_fd``), so that another program's save goes back at
        once; then its CONTENT, read through its own descriptor (times and sizes do not say
        what a file holds). Returns the name, in ``aside``, of the file that was replaced and
        found to be what was expected (None when nothing was there). Otherwise:

        - what came out is something else (another program's save, a folder): the two are
          exchanged back, so it stays under its name; the file made, having stood there, is
          kept aside;
        - ``onto`` is no longer the file made, but an ordinary file: another program saved
          over it in that instant, and its save stays; what came out is kept aside;
        - in both cases _Changed is raised: the file made is not at ``onto``.

        OSError when that could not be established: the prepared name was not the file made,
        the exchange back failed (what came out is then kept aside, and named), a link stands
        at ``onto``, or a file could not be opened or read to be looked at. The caller then
        has to look at ``onto`` again (commit's taking back does)."""
        fd = self._made.get(made)
        if fd is None or self.is_file_of(made, fd) is None:
            raise OSError(errno.ESTALE, 'the prepared file was replaced by something else', str(self.path / made))
        if expected is None:
            self._rename(made, onto, 1)
            self.exposed.add(made)
            if self.is_file_of(onto, fd) is None:        # a link swapped in for the prepared name was moved
                aside.take(self, onto, onto + ".found", foreign=True)
                raise OSError(errno.ESTALE, 'the prepared file was replaced by something else as it was moved',
                              str(self.path / onto))
            self.flush()
            self._let_go(made)
            return None
        self.exposed.add(made)               # from the next line on, the name ``made`` holds what stood at ``onto``
        self._rename(made, onto, 0)
        kind, out = self.look(made)
        try:
            another = (kind == "file" and read_fd is not None
                       and (os.fstat(out).st_dev, os.fstat(out).st_ino)
                       != (os.fstat(read_fd).st_dev, os.fstat(read_fd).st_ino))
            placed = self.is_file_of(onto, fd) is not None
            if another:
                good = False
            elif kind == "file" and expected is ANY_FILE:
                good = True
            elif kind == "file" and isinstance(expected, bytes):
                data, stable, _ = _read_fd(out)
                good = stable and data == expected
            elif kind == "link":
                good = expected is A_LINK        # nobody's save: it is kept aside as something found, and replaced
            elif kind == "absent" and placed and read_fd is not None and isinstance(expected, bytes):
                data, stable, left = _read_fd(read_fd)   # removed at once by something else: was it the file read?
                good = left.st_nlink == 0 and stable and data == expected
            else:
                good = False
            if placed and good:
                if kind == "link":
                    aside.take(self, made, onto + ".found", foreign=True)
                    was = None
                else:
                    was = aside.take(self, made, onto + ".was", foreign=False) if kind != "absent" else None
                self.flush()
                self._let_go(made)
                return was
            if placed:
                # What came out is not what was to be replaced: it goes back under its name.
                try:
                    self._rename(made, onto, 0)
                except FileNotFoundError:
                    raise OSError(errno.ESTALE, 'what the file replaced was removed before it could be looked at',
                                  str(self.path / onto)) from None
                except OSError:
                    aside.take(self, made, onto + ".found", foreign=True)    # it could not go back: kept, and named
                    raise
                if self.is_file_of(made, fd) is None and self.kind(made) == "file":
                    # Not the file made that came back: the other program saved once more over
                    # it in that instant. That newest save is the one to stand; the earlier one
                    # is kept aside.
                    self._rename(made, onto, 0)
                    aside.take(self, made, onto + ".found", foreign=True)
                elif self.is_file_of(made, fd) is None:
                    aside.take(self, made, onto + ".found", foreign=True)
                else:               # the file made: it stood under the name for an instant, so it is kept
                    aside.take(self, made, onto + ".not-installed", foreign=False)
                self._let_go(made)
                self.flush()
                raise _Changed(self.path / onto)
            if self.kind(onto) == "file":
                # Another program saved over the file made (or the prepared name was swapped for
                # a file just before the exchange): that file stays, and what came out is kept.
                aside.take(self, made, onto + (".was" if good else ".found"), foreign=not good)
                self._let_go(made)
                self.flush()
                raise _Changed(self.path / onto)
            # A link, a folder or nothing stands at ``onto``: what came out goes back, and what
            # stood there instead is kept aside.
            try:
                self._rename(made, onto, 0)
            except FileNotFoundError:
                pass
            except OSError:
                aside.take(self, made, onto + ".found", foreign=True)
                raise
            else:
                aside.take(self, made, onto + ".found", foreign=True)
            self._let_go(made)
            self.flush()
            if self.kind(onto) == "file":
                raise _Changed(self.path / onto)
            raise OSError(errno.ESTALE, 'the file was swapped for something that is not a file as it was written',
                          str(self.path / onto))
        finally:
            if out is not None:
                os.close(out)

    def move(self, name, onto, identity=None, replace=True):
        """For a folder of cdlbib's own (.bibcheck and below), where nothing is a library
        file: put the file made here as ``name`` in the place of ``onto``. The name is taken
        when nothing is there (FileExistsError without ``replace`` when something is), else
        the two are exchanged, and an ordinary file that came out (an earlier record or copy
        of cdlbib's) is removed. A folder, a link or anything else that came out is exchanged
        back and False is returned; so it is when ``onto`` is not the file made afterwards.
        ``identity`` is what ``new`` returned, checked too."""
        fd = self._made.get(name)
        if fd is None or self.is_file_of(name, fd) is None or (
                identity is not None and self.identity(name) != identity):
            raise OSError(errno.ESTALE, 'the prepared file was replaced by something else', str(self.path / name))
        try:
            self._rename(name, onto, 1)
        except FileExistsError:
            if not replace:
                raise
            self._rename(name, onto, 0)
            placed, came_out = self.is_file_of(onto, fd) is not None, self.kind(name)
            if not placed or came_out != "file":
                with contextlib.suppress(FileNotFoundError):
                    self._rename(name, onto, 0)
                self.flush()
                return False
            os.unlink(name, dir_fd=self.fd)
            self.flush()
            self._let_go(name)
            return True
        placed = self.is_file_of(onto, fd) is not None
        self.flush()
        if placed:
            self._let_go(name)
        return placed

    def _rename(self, name, onto, which, flags=None, to=None):
        """The C library's atomic rename of ``name`` to ``onto`` within this folder: an
        exchange of the two (``which`` 0), or a move that takes no name already in use
        (``which`` 1: FileExistsError). OSError(ENOTSUP) where the system or the file system
        has neither: nothing is then done, and nothing is renamed any other way. A call that
        a signal interrupted before it did anything (EINTR) is made again. (``flags``: the
        call's flags as given, for a test of a combination no system accepts. ``to``: the
        held folder ``onto`` is a name in, when it is another one of the same file system.)"""
        to = self if to is None else to
        # The same event os.rename raises (names and folder descriptors): the C library is
        # called directly, and an auditor of the interpreter is to see these renames too.
        sys.audit("os.rename", name, onto, self.fd, to.fd)
        calls = _exchange()
        if calls is not None:
            flags = calls[1 + which] if flags is None else flags
            while True:
                if calls[0](self.fd, os.fsencode(name), to.fd, os.fsencode(onto), flags) == 0:
                    return
                code = ctypes.get_errno()
                if code != errno.EINTR:
                    break
            if code not in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
                raise OSError(code, os.strerror(code), str(to.path / onto))
        raise OSError(errno.ENOTSUP, NO_ATOMIC_RENAME, str(to.path / onto))

    def exchange(self, name, onto):
        """Exchange the two names in this folder in one step (each then names what the other
        named), so that what ``onto`` held can be looked at after the fact and put back.
        OSError(ENOTSUP), with nothing done, where the system or the file system has no such
        call. The folder is not flushed to the disk here (``flush``): the caller looks first."""
        self._rename(name, onto, 0)
        return True

    def flush(self):
        """Flush the folder's names to the disk. An error is raised: a name the disk does not
        hold is not one to build on. Only the answers that mean "a folder cannot be flushed
        here" are passed over (_NO_FOLDER_FSYNC)."""
        try:
            os.fsync(self.fd)
        except OSError as exc:
            if exc.errno not in _NO_FOLDER_FSYNC:
                raise

    def put(self, name, data, mode=None):
        """For a folder of cdlbib's own (.bibcheck and below): make ``name`` hold ``data``
        whole (None: remove it), by ``move``. A folder or a link in its place is left where
        it is (OSError)."""
        if data is None:
            self.remove(name)
            return
        made, identity = self.new('.rollback-', data, mode)
        try:
            if not self.move(made, name, identity):
                raise OSError(errno.ESTALE, 'the file was replaced by something else while it was written',
                              str(self.path / name))
        finally:
            fd = self._made.get(made)
            try:
                if fd is not None and self.is_file_of(made, fd) is not None:
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(made, dir_fd=self.fd)
            finally:
                self._let_go(made)

    def clear(self, name, aside):
        """Take away the prepared name ``name``, without removing anything in this folder:
        what it holds is moved into ``aside``. There, the file made here that never stood
        under a library name is removed (it is nobody's but this write's); anything else is
        kept and named."""
        fd = self._made.get(name)
        try:
            if self.identity(name) is None:
                return
            if name in self.exposed:
                aside.take(self, name, name.lstrip('.') + ".found", foreign=True)
                return
            try:
                aside.discard(self, name, fd)
            except OSError:
                # No private folder can be had (the folder it is made in is being moved about).
                # The file made here never stood under a library name: it is removed where it
                # is, when the name is still that file.
                if fd is None or self.is_file_of(name, fd) is None:
                    raise
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(name, dir_fd=self.fd)
        finally:
            self._let_go(name)

    def remove(self, name):
        """Remove the name (a link itself, never what it points to)."""
        try:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=self.fd)
        finally:
            self._let_go(name)

    def names(self):
        return os.listdir(self.fd)


ANY_FILE, A_LINK = object(), object()        # what ``install`` may find in the place it writes to

# open(O_NOFOLLOW | O_NONBLOCK) of something that is not an ordinary file: ELOOP for a link (Linux,
# macOS; EMLINK and EFTYPE on BSDs), ENXIO for a socket or a pipe nobody reads (Linux),
# EOPNOTSUPP for a socket (macOS). What the thing is, is then asked with lstat.
_NOT_OPENED_AS_A_FILE = {errno.ELOOP, errno.EMLINK, errno.ENXIO, errno.EOPNOTSUPP, errno.ENOTSUP,
                         getattr(errno, "EFTYPE", errno.ELOOP)}

# fsync of a folder's descriptor where a folder cannot be flushed: EINVAL (Linux: "fd is bound
# to a special file which does not support synchronization", as on some FUSE and network file
# systems; macOS says the same for a file type that does not support it) and ENOTSUP /
# EOPNOTSUPP (macOS on SMB and some other network file systems). Every other error (EIO,
# ENOSPC, EDQUOT, EBADF) is a failure of the storage or of this program, and is raised.
_NO_FOLDER_FSYNC = {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}


def _read_fd(fd):
    """(the bytes of the file ``fd`` is open on, read from its start; whether it was the same
    before the read and after it; its stat result after the read). At most the size it had at
    the start, and one byte, are read: a file that is being appended to is "not the same"
    after that, however fast it grows, and is not read on. The same means: times and size
    as before, and exactly that many bytes read."""
    before, data, offset = os.fstat(fd), bytearray(), 0
    limit = before.st_size + 1
    while offset < limit:
        chunk = os.pread(fd, min(1 << 20, limit - offset), offset)
        if not chunk:
            break
        data += chunk
        offset += len(chunk)
    after = os.fstat(fd)
    stable = ((before.st_mtime_ns, before.st_ctime_ns, before.st_size)
              == (after.st_mtime_ns, after.st_ctime_ns, after.st_size) and len(data) == before.st_size)
    return bytes(data), stable, after


KEPT = "kept"                        # under the library's .bibcheck/: one private folder for each write that kept something


class _Aside:
    """The private folder of one write: <.bibcheck>/kept/<UTC stamp>-<random>, made with an
    exclusive mkdir, for the user only (0700), the first time something has to be moved out
    of a library name. Everything is moved into it by the flagged rename, from one held
    folder into this one, and nothing that was moved in is removed here except a file this
    write made itself that never stood under a library name (``discard``). ``items`` is what
    it holds: (its name here, whether it is something unexpected, the path it came from).
    When the write ends with the folder empty, the folder is removed."""

    def __init__(self, work, held):
        self.work = work                     # gives the held folder .bibcheck (made if need be); it is not closed here
        self.held = held                     # the stack of the write: this folder is closed before the ones it is in
        self.items, self.notes, self._folders, self.name = [], [], [], None

    def folder(self):
        if not self._folders:
            work = self.work()
            kept = work.sub(KEPT, create=True)
            if kept is None:
                raise OSError(errno.ENOENT, 'the folder was moved away while it was being used', str(work.path / KEPT))
            try:
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
                while True:
                    name = f"{stamp}-{secrets.token_hex(6)}"
                    try:
                        os.mkdir(name, 0o700, dir_fd=kept.fd)
                        break
                    except FileExistsError:
                        continue
                own = kept.sub(name)
                if own is None:
                    raise OSError(errno.ENOENT, 'the folder was moved away while it was being used', str(kept.path / name))
                try:
                    own.flush()
                    kept.flush()
                except BaseException:
                    own.close()
                    raise
            except BaseException:
                kept.close()
                raise
            self._folders, self.name = [work, kept, own], name      # all three, or none
            self.held.callback(self.close)
        return self._folders[2]

    @property
    def path(self):
        return self._folders[2].path if len(self._folders) == 3 else None

    def take(self, source, name, label, foreign):
        """Move ``name`` of the held folder ``source`` in here as ``label`` (numbered when
        that is taken). Returns its name here; None when nothing was under ``name``."""
        folder, number = self.folder(), 0
        while True:
            unique = label if not number else f"{label}.{number}"
            try:
                source._rename(name, unique, 1, to=folder)
                break
            except FileExistsError:
                number += 1
            except FileNotFoundError:
                return None
        self.items.append((unique, foreign, str(source.path / name)))
        folder.flush()
        return unique

    def discard(self, source, name, fd):
        """A prepared file of this write that never stood under a library name: moved in here
        from ``source`` and, when it is still that file (``fd``: the descriptor held on it
        since it was made), removed here. Anything else found under the name is kept."""
        label = self.take(source, name, name.lstrip('.') + ".found", foreign=True)
        if label is not None and fd is not None and self.folder().is_file_of(label, fd) is not None:
            os.unlink(label, dir_fd=self.folder().fd)
            self.items = [item for item in self.items if item[0] != label]

    def forget(self, label):
        self.items = [item for item in self.items if item[0] != label]

    def paths(self, foreign=None):
        return [str(self.path / label) for label, unexpected, _ in self.items if foreign in (None, unexpected)]

    def said(self):
        """One sentence naming what was kept, for an error message ('' when nothing was)."""
        parts = []
        if self.paths(foreign=True):
            parts.append("What stood in a library file's place and was not what was expected is kept as "
                         + ", ".join(self.paths(foreign=True)) + ".")
        if self.paths(foreign=False):
            parts.append("Kept from this write (the text it replaced, or its own that was not installed): "
                         + ", ".join(self.paths(foreign=False)) + ".")
        return " ".join(parts + self.notes)

    def close(self):
        folders, self._folders = self._folders, []
        if len(folders) == 3:
            with contextlib.suppress(OSError):               # only ever an empty folder
                os.rmdir(self.name, dir_fd=folders[1].fd)
            with contextlib.suppress(OSError):
                os.rmdir(KEPT, dir_fd=folders[0].fd)
        for folder in reversed(folders[1:]):
            with contextlib.suppress(OSError):
                folder.close()


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
_KEPT_NAME = re.compile(r"\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{12}")


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
    what _copies writes. (The stamp also names the write's private folder: <.bibcheck>/kept/
    <stamp>-<random>, where what the write kept aside is found by a later command.)"""
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
        folders, now, saved, prepared, holds, modes = {}, {}, {}, [], {}, {}
        for name, (before, after) in recorded.items():
            target = known[name]
            try:
                folders[name] = folder = held.folder(target)
                current, modes[name] = folder.read(target.name) if folder is not None else (None, None)
                holds[name] = current
            except OSError as exc:
                raise refuse(f"{target} is not an ordinary file in an ordinary folder") from exc
            now[name] = _sha(current)
            if now[name] not in (before, after):
                raise CdlbibError(f"An earlier write to {ws.bib} was interrupted, and the library was changed since; "
                                  f"nothing was changed now. The bibliography as it was before that write is {copy}. "
                                  f"Compare the two, then delete {marker}.")
        replaced = [name for name, (before, after) in recorded.items() if now[name] == after and before != after]
        whole = not replaced or len(replaced) == len([1 for before, after in recorded.values() if before != after])
        for name, (before, after) in recorded.items():
            target, folder = known[name], folders[name]
            if folder is None:
                continue
            if whole:                    # nothing has to be put back: the copies and prepared files are not needed, nor read
                if folder.identity(staged[name]) is not None:
                    prepared.append((folder, staged[name], None))
                continue
            kept = f"{stamp}-{target.name}"
            try:
                held_copy = edits.read(kept)[0]
                waiting = folder.read(staged[name])[0]
            except OSError as exc:
                raise refuse(f"a copy or prepared file of {target} is not an ordinary file") from exc
            if held_copy is not None:
                if _sha(held_copy) != before:
                    raise refuse(f"the copy {ws.work / EDITS / kept} is not the file that write saved")
                saved[name] = held_copy
            if waiting is not None:
                if _sha(waiting) not in (before, after):      # the new file, or the old one it was exchanged with
                    raise refuse(f"the prepared file {target.parent / staged[name]} is not the one that write made")
                prepared.append((folder, staged[name], waiting))
        if not whole:
            for name in replaced:
                if recorded[name][0] is not None and name not in saved:
                    raise refuse(f"the copy of {known[name]} from before it is missing")
        aside = _Aside(lambda: held.found["work"], held)
        if not whole:
            try:
                # From the bytes that were read and checked, by name in the held folder, with the
                # permission bits of the file replaced; and only a file that still holds what
                # was read here is replaced (_restore): a save made meanwhile stays.
                for name in replaced:
                    if not _restore(folders[name], known[name], saved.get(name), modes[name], holds[name], aside):
                        raise refuse(f"{known[name]} was changed by something else while the library was being "
                                     "put back; it was left as it is now. " + aside.said())
            except OSError as exc:
                raise refuse(f"the library could not be put back ({exc}). " + aside.said()) from exc
        try:
            for folder, name, waiting in prepared:      # what the dead writer left beside the file: kept, not removed
                aside.take(folder, name, name.lstrip('.') + (".prepared" if waiting is not None else ".found"),
                           foreign=waiting is None)
        except OSError as exc:
            raise refuse(f"what that write left beside the library could not be moved aside ({exc})") from exc
        # The copies stay, also the ledger's: since a write's copy is the very file it replaced,
        # one may be a file another program still has open. They go the way of all copies
        # (the newest KEEP_EDITS writes are kept).
        # What that write itself had to keep aside as unexpected is said now, before its record goes.
        found_then = []
        try:
            then = held.found["work"].sub(KEPT)
            if then is not None:
                held.callback(then.close)
                for kept_name in sorted(name for name in then.names()
                                        if name.startswith(stamp + "-") and _KEPT_NAME.fullmatch(name)):
                    own = then.sub(kept_name)
                    if own is not None:
                        held.callback(own.close)
                        found_then += [str(ws.work / KEPT / kept_name / name) for name in sorted(own.names())
                                       if ".found" in name]
        except OSError as exc:
            raise refuse(f"what that write kept aside (in {ws.work / KEPT}) could not be looked at "
                         f"({exc.strerror or exc})") from exc
        edits.remove(PENDING)
        said_kept = ""
        if found_then:
            said_kept += ("; during that write something stood in a library file's place that was not what was "
                          "expected, and is kept as " + ", ".join(found_then))
        if aside.items:
            said_kept += "; " + aside.said()
    if not whole:
        return [f"an earlier write to {ws.bib} was interrupted part-way; the library was put back as it was before "
                f"that write (the bibliography as it was is also in {copy})" + said_kept]
    if replaced:
        return [f"an earlier write to {ws.bib} was interrupted just after it had written everything; nothing is "
                "missing" + said_kept]
    return [f"an earlier write to {ws.bib} was interrupted before anything was written; the library is as it was"
            + said_kept]


def _copies(held, staged, writes, stamp=None):
    """Copy what is about to be replaced into <.bibcheck>/edits and record the write as in
    progress (logical names, checksums and the prepared files' names: no path). Returns (the
    copy of the bibliography, the names of the copies only a recovery needs)."""
    ws = held.ws
    edits = held.edits(create=True)
    names = {path: name for name, path in _targets(ws).items()}
    # The stamp of the write: its private folder's (see _record), so that a later command finds it.
    stamp = stamp or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
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


def _prune(edits, names):
    """Keep the copies of the newest KEEP_EDITS writes in the held folder ``edits``. Only
    ordinary files there whose names are exactly <stamp>-<one of ``names``> are ever removed.
    (Such a copy is the file a write replaced, or a copy made of it: this is the one place
    where a file that once was a library file is removed, KEEP_EDITS writes later.)"""
    copied = "|".join(re.escape(name) for name in names)
    named = {name: match[1] for name in edits.names()
             if (match := re.fullmatch(r"(\d{8}T\d{6}\.\d{6}Z)-(?:" + copied + ")", name))}
    old = sorted(set(named.values()), reverse=True)[KEEP_EDITS:]
    for name, stamp in named.items():
        if stamp in old:
            with contextlib.suppress(OSError):
                if stat.S_ISREG(os.stat(name, dir_fd=edits.fd, follow_symlinks=False).st_mode):
                    edits.remove(name)


def _file_as_copy(aside, edits, was, copy):
    """The file a write replaced (``was``: its name in ``aside``) becomes that write's copy,
    ``copy`` in the held folder ``edits``, readable by the user only as every copy is: nothing
    a program may still be writing into is removed. Where a copy was made beforehand, the two
    are exchanged, and the copy made beforehand (bytes of this write's own, which never were
    a library file) is removed in the private folder."""
    folder = aside.folder()
    kind, fd = folder.look(was)
    if fd is not None:
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
    try:
        folder._rename(was, copy, 1, to=edits)
    except FileExistsError:
        folder._rename(was, copy, 0, to=edits)
        os.unlink(was, dir_fd=folder.fd)
    aside.forget(was)
    edits.flush()


def _restore(folder, target, previous, mode, ours, aside):
    """Make ``target`` hold ``previous`` again (None: not be there), with the permission bits
    ``mode``, where this write put ``ours`` (bytes). What is there is looked at first, by
    its content read through its own descriptor, and is replaced only by ``_Folder.install``
    (exchanged, looked at again); whatever comes out is kept in ``aside``, never removed.
    Returns True when ``target`` is as it was before the write (also when it already was),
    and False when it holds something else, a save of another program, which is left as it
    is. A link found there, or nothing, is not this write's doing either: the link is kept
    aside, the text is written again, and what was found is said (``aside.notes``). OSError
    when that cannot be told or done (a file that cannot be opened or read, a rename that
    fails, a folder in its place): the caller keeps its record of the write."""
    kind, fd = folder.look(target.name)
    if kind == "file":
        try:
            data, stable, _ = _read_fd(fd)
        finally:
            os.close(fd)
        if stable and data == previous:
            folder.flush()               # as it was, and that is on the disk too (an error here is raised)
            return True
        if not (stable and data == ours):
            return False
        if previous is None:             # this write made the file: it is moved aside, and looked at again there
            label = aside.take(folder, target.name, target.name + ".not-installed", foreign=False)
            if label is not None:
                kind, fd = aside.folder().look(label)
                try:
                    same = kind == "file" and _read_fd(fd)[:2] == (ours, True)
                finally:
                    if fd is not None:
                        os.close(fd)
                if not same:
                    aside.items = [(name, True if name == label else foreign, source)
                                   for name, foreign, source in aside.items]
                    return False
            folder.flush()
            return True
        expected = ours
    elif kind == "absent":
        if previous is None:
            return True
        aside.notes.append(f"{target} was removed by something else while it was being written; the text from "
                           "before the write was written again.")
        expected = None
    elif kind == "link":
        aside.notes.append(f"A link stood in the place of {target} while it was being written; it is kept aside"
                           + ("" if previous is None else ", and the text from before the write was written again") + ".")
        if previous is None:
            aside.take(folder, target.name, target.name + ".found", foreign=True)
            folder.flush()
            return True
        expected = A_LINK
    else:
        raise OSError(errno.EISDIR, 'something that is neither a file nor a link stands in its place', str(target))
    made, _ = folder.new('.rollback-', previous, mode)
    try:
        folder.install(made, target.name, expected, aside)
    except (_Changed, FileExistsError):
        return False
    finally:
        folder.clear(made, aside)
    return True


def replace_library_file(path, data, mode=None):
    """Make the library file ``path`` (one that is not written by ``commit``: the approvals
    ledger) hold ``data`` whole (None: not be there), by the same step as ``commit``'s: by
    name within its folder held open, refusing links, exchanged with a prepared file; and
    the file that was there is kept, as <.bibcheck>/edits/<stamp>-<its name> beside the
    library (the newest KEEP_EDITS are kept), never removed. OSError when it cannot be."""
    path = Path(path)
    with contextlib.ExitStack() as held:
        above = _Folder.at(path.parent.parent)
        held.callback(above.close)
        folder = above.sub(path.parent.name, create=data is not None)
        if folder is None:
            return
        held.callback(folder.close)
        def work():
            found = above.sub(".bibcheck", create=True)
            if found is None:
                raise OSError(errno.ENOENT, 'the folder was moved away while it was being used', str(above.path / ".bibcheck"))
            held.callback(found.close)
            return found
        aside = _Aside(work, held)
        if data is None:
            was = aside.take(folder, path.name, path.name + ".was", foreign=False)
            folder.flush()
        else:
            made, _ = folder.new('.' + path.name + '-', data, mode)
            try:
                try:
                    was = folder.install(made, path.name, None, aside)
                except FileExistsError:
                    was = folder.install(made, path.name, ANY_FILE, aside)
            except _Changed:
                raise OSError(errno.ESTALE, 'the file was replaced by something else while it was written. '
                              + aside.said(), str(path)) from None
            finally:
                folder.clear(made, aside)
        if was is not None:
            edits = aside._folders[0].sub(EDITS, create=True)
            held.callback(edits.close)
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            _file_as_copy(aside, edits, was, f"{stamp}-{path.name}")
            _prune(edits, [path.name])


def commit(ws, writes, expected, *, batch=None, operation="entry completion"):
    """Install ``writes`` ([(path, bytes)], the bibliography first; only ws.bib and
    ws.key_renames are taken) and return a Written. ``expected`` gives, for each path, the
    bytes the caller read and planned from (None: the file was not there); a file that holds
    anything else by now, read through one descriptor just before the replacements, refuses
    the whole write with a CdlbibError ("changed while applying") and nothing is replaced.
    ``batch`` is the managed command's library.CompletionBatch, ``operation`` the name an
    interrupted write is announced by. Each file is prepared as a new file beside its target,
    with the target's permission bits, flushed to the disk, and put in the target's place by
    ``_Folder.install``; the file it replaced becomes this write's copy in <.bibcheck>/edits.
    When one of them cannot be, those already in place are taken back (``_restore``). Nothing
    that stood under a library name is removed on any of these paths: it is in the library,
    or it is the copy, or it is kept in the write's private folder (<.bibcheck>/kept/...),
    and the error says where. The record of the write in progress (the managed library's
    mark) is removed only when the library is established to be as it was, with nothing
    unexpected kept; otherwise it stays for the next command to settle (``recover``), and
    that is said (WriteConflict). Anything raised while files are being replaced, also what
    is not an OSError (an interruption, an error of an audit hook), takes the same way back."""
    from . import api, library
    from .errors import WriteConflict
    done, staged, modes = Written(), [], {}
    with _Held(ws) as held:
        def work():
            if held.found.get("work") is None:
                found = held.bib().sub(ws.work.name, create=True)
                if found is None:
                    raise OSError(errno.ENOENT, 'the folder was moved away while it was being used', str(ws.work))
                held._keep("work", found)
            return held.found["work"]
        aside = _Aside(work, held)
        try:
            # The private folder of this write is made and held before anything else (a write
            # that has nowhere to keep what it pushes aside does not start), and the record of
            # the write names it by its stamp. It comes before the files are prepared, so that
            # they stand beside the library, under names of their own, as briefly as can be.
            aside.folder()
            # Prepare every file before replacing either, so permission/disk failures
            # during preparation leave both originals intact.
            for target, data in writes:
                folder = held.folder(target, create=True)
                modes[target] = folder.read(target.name)[1]
                name, identity = folder.new('.' + target.name + '-', data, modes[target])
                staged.append((target, folder, name, identity, expected[target]))
            for target, folder, _, _, previous in staged:
                if folder.read(target.name)[0] != previous:
                    raise CdlbibError(f'{target} changed while applying; nothing was written')
            managed, extra = api.is_managed(ws), []
            if managed:
                done.backup = library.completion_checkpoint(ws, batch)
                library._mark(done.backup, operation)
            else:
                done.saved_copy, extra = _copies(held, staged, writes, aside.name.rsplit("-", 1)[0])
            installed, replaced = [], []
            try:
                # The backups are made; only now is each file read again and compared with what
                # the caller planned from, and replaced: exchanged with the prepared file in
                # one step, after which what came out is checked, by its content, to be what
                # was read (_Folder.install). A file that is not there yet takes its name only
                # while the name is free. A target is listed as (perhaps) replaced BEFORE the
                # rename, and taken off the list only when it is established that this write's
                # file is not in its place: whatever else goes wrong, it is looked at again.
                for target, folder, name, identity, previous in staged:
                    # The replacement is made by name within the held folder, so an auditor
                    # sees names only; the full paths are announced under the same event.
                    sys.audit("os.rename", str(target.parent / name), str(target), -1, -1)
                    if not folder.is_made(name) or folder.identity(name) != identity:
                        raise OSError(errno.ESTALE, 'the prepared file was replaced by something else',
                                      str(target.parent / name))
                    with contextlib.ExitStack() as reading:
                        try:
                            current, _, read_fd = folder.read_held(target.name, reading)
                        except _Changed:
                            raise _Changed(target) from None
                        if current != previous:
                            raise _Changed(target)
                        entry = (target, folder, previous)
                        installed.append(entry)
                        try:
                            was = folder.install(name, target.name, previous, aside, read_fd)
                        except (_Changed, FileExistsError):
                            installed.remove(entry)
                            raise _Changed(target) from None
                        replaced.append((target, was))
            except BaseException as stopped:
                # Taking back what was (or may have been) put in place: only a file that still
                # holds exactly what this write put there is replaced, and what comes out is
                # kept (_restore). One that something else has changed since is left as it is.
                # The record of this write stays unless the library is established to be as it
                # was AND nothing unexpected had to be kept: a conflict, something that could
                # not be looked at or put back, a link or a folder found in a file's place.
                written, conflicts, unknown = dict(writes), [], []
                for target, folder, previous in reversed(installed):
                    try:
                        if not _restore(folder, target, previous, modes[target], written[target], aside):
                            conflicts.append(target)
                    except OSError as exc:
                        unknown.append((target, exc))
                for _, folder, name, _, _ in staged:
                    try:
                        folder.clear(name, aside)
                    except OSError as exc:
                        unknown.append((folder.path / name, exc))
                kept = done.saved_copy or (done.backup.path if done.backup is not None else None)
                beside = (" " + aside.said()) if aside.said() else ""
                settle = ("" if managed else f" The record of this write is {ws.work / EDITS / PENDING}: the next "
                          "cdlbib command that writes settles it, or says what it found.")
                if unknown:
                    raise WriteConflict(
                        f"The write could not be finished ({stopped}), and it could not be established that "
                        + ", ".join(f"{target} is as it was ({exc.strerror or exc})" for target, exc in unknown)
                        + ": it may hold the new text. What it held before this write is in " + str(kept) + "."
                        + settle + beside, files=[target for target, _ in unknown] + conflicts) from None
                if conflicts:
                    raise WriteConflict(
                        "The write could not be finished and was being taken back, but "
                        + ", ".join(str(target) for target in conflicts) + " was changed by something else in the "
                        "meantime; it was left as it is now. What it held before this write is in " + str(kept)
                        + ". Compare the two" + ("" if managed else f", then delete {ws.work / EDITS / PENDING}") + "."
                        + beside, files=conflicts) from None
                if aside.paths(foreign=True) and not isinstance(stopped, (OSError, _Changed)):
                    raise                # the record stays, as below; the error is the one that was raised
                if aside.paths(foreign=True):
                    raise WriteConflict(
                        f"Nothing was written: something else changed the library's files while {ws.bib} was being "
                        f"written ({stopped if isinstance(stopped, OSError) else 'changed while applying'}). The "
                        "library holds what it held before, or what the other program saved." + beside + settle,
                        files=[target for target, _ in writes]) from None
                if not managed:
                    edits = held.edits()
                    edits.remove(PENDING)
                    for name in extra:
                        edits.remove(name)
                if isinstance(stopped, _Changed):      # everything is as it was found: no write is in progress
                    if managed:
                        library._unmark()
                    raise CdlbibError(f'{stopped.args[0]} changed while applying; nothing was written'
                                      + ("." + beside if beside else "")) from None
                raise
            # Done. The file each replaced becomes the copy of this write (so a program that
            # still has it open writes into a file that is kept, not into nothing).
            if managed:
                # The managed library's backup is the command's checkpoint, and it keeps no
                # copies in edits. The files its writes replaced are kept all the same (a
                # program may still have one open): in <.bibcheck>/replaced, the newest
                # KEEP_EDITS writes'.
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
                with contextlib.suppress(OSError, AttributeError):   # they then stay in the private folder, which is named
                    kept_files = work().sub(REPLACED, create=True)
                    held.callback(kept_files.close)
                    for target, was in replaced:
                        if was is not None:
                            _file_as_copy(aside, kept_files, was, f"{stamp}-{target.name}")
                    _prune(kept_files, [path.name for path in _targets(ws).values()])
                library._unmark()
                library._prune(library.backups_folder(), ws.root)
            else:
                edits = held.edits()
                stamp = (done.saved_copy.name[:-len(ws.bib.name) - 1] if done.saved_copy is not None
                         else datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"))
                for target, was in replaced:
                    if was is not None:
                        with contextlib.suppress(OSError):      # it then stays in the private folder, which is named
                            _file_as_copy(aside, edits, was, f"{stamp}-{target.name}")
                edits.remove(PENDING)
                _prune(edits, [path.name for path in _targets(ws).values()])
            if aside.items:
                done.notes.append(aside.said())
            return done
        finally:
            for _, folder, name, _, _ in staged:
                with contextlib.suppress(OSError):
                    folder.clear(name, aside)
