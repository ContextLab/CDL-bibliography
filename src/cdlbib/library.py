"""The managed library: the copy of the bibliography that cdlbib downloads and keeps for a
user who has named no library of their own. Nothing here prints or prompts."""
import contextlib
import contextvars
import functools
import datetime
import filecmp
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CdlbibError, LibraryUnavailable, UpdateConflict, UpdateNeedsDecision
from .gitenv import git_env

UPSTREAM = "https://github.com/ContextLab/CDL-bibliography.git"
BIB_NAME = "cdl.bib"
INCOMPLETE = ".cdlbib-incomplete"   # a library folder holding this marker is not usable


def home(environ=None, platform=None):
    """The folder cdlbib keeps its own data in: CDLBIB_HOME, else the per-user data folder."""
    environ = os.environ if environ is None else environ
    if environ.get("CDLBIB_HOME"):
        return Path(environ["CDLBIB_HOME"]).expanduser()
    user = Path(environ["HOME"]) if environ.get("HOME") else Path.home()
    if (platform or sys.platform) == "darwin":
        return user / "Library" / "Application Support" / "cdlbib"
    data = environ.get("XDG_DATA_HOME")
    return (Path(data) if data else user / ".local" / "share") / "cdlbib"


def path(environ=None):
    return home(environ) / "library"


def upstream(environ=None):
    environ = os.environ if environ is None else environ
    return environ.get("CDLBIB_UPSTREAM") or UPSTREAM


@dataclass
class State:
    last_check: datetime.datetime | None   # when the upstream was last consulted successfully (UTC)
    upstream: str
    last_attempt: datetime.datetime | None = None   # when an automatic check last failed, if none succeeded since


def read_state():
    """state.json; a missing, empty or unreadable file is 'never checked'."""
    try:
        data = json.loads((home() / "state.json").read_text(encoding="utf-8"))
        when = datetime.datetime.fromisoformat(data["last_check"]) if data.get("last_check") else None
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        state = State(when, str(data["upstream"]))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return State(None, upstream())
    try:       # a file written before this field existed, or an unreadable value: no failed attempt
        tried = datetime.datetime.fromisoformat(data["last_attempt"]) if data.get("last_attempt") else None
        if tried is not None and tried.tzinfo is None:
            tried = tried.replace(tzinfo=datetime.timezone.utc)
        state.last_attempt = tried
    except (ValueError, TypeError, AttributeError):
        pass
    return state


def write_state(state):
    folder = home()
    folder.mkdir(parents=True, exist_ok=True)
    data = {"last_check": state.last_check.isoformat() if state.last_check else None, "upstream": state.upstream}
    if state.last_attempt:       # present only after an automatic check that failed
        data["last_attempt"] = state.last_attempt.isoformat()
    handle, temporary = tempfile.mkstemp(dir=folder, prefix="state.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out)
        os.replace(temporary, folder / "state.json")
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def exists():
    """Is the managed library there and whole: a git clone holding cdl.bib, not marked incomplete."""
    root = path()
    return (root / ".git").exists() and (root / BIB_NAME).is_file() and not (root / INCOMPLETE).exists()


CLONE_TIMEOUT = 600   # seconds a download may take before it is given up (the lock is held meanwhile)


def _same_source(recorded, wanted):
    """Do two upstream addresses name the same repository? (Equal text, or one local folder.)"""
    if recorded.rstrip("/") == wanted.rstrip("/"):
        return True
    try:
        return os.path.isdir(recorded) and os.path.isdir(wanted) and os.path.samefile(recorded, wanted)
    except OSError:
        return False


def _require_upstream(root, source):
    """A managed library cloned from somewhere other than the configured upstream is neither
    used nor replaced: the user is told, and decides."""
    try:
        asked = subprocess.run(["git", "config", "--get", "remote.origin.url"], cwd=root, capture_output=True,
                               text=True, stdin=subprocess.DEVNULL, env=git_env())
    except OSError:       # no git: nothing can be asked; the commands that need git say so themselves
        return
    origin = asked.stdout.strip()
    if _same_source(origin, source):
        return
    raise LibraryUnavailable(
        f"{root} is a copy of {origin or 'no upstream at all'}, but cdlbib is set to download from {source}. "
        "It was left as it is. Move that folder away to download a fresh copy, or pass --library PATH to work "
        "in the copy you have.")


@contextlib.contextmanager
def _locked(folder, progress=None, waiting="waiting for another cdlbib to finish downloading the bibliography ..."):
    """Hold <folder>/lock, so that two commands starting together do not both download.
    ``progress`` receives one line (``waiting``) when the lock is held by another command and
    this one waits."""
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "lock", "a") as handle:
        try:
            import fcntl
        except ImportError:   # no flock on this platform: no lock
            yield
            return
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:       # held by another command
            if progress:
                progress(waiting)
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# A transaction can call another managed operation in the same execution context.
# The PID prevents a forked child from inheriting ownership of its parent's flock.
_owner = contextvars.ContextVar("cdlbib_write_owner", default=())
WRITING = "waiting for another cdlbib to finish writing to this library ..."


@contextlib.contextmanager
def _own_lock(folder, progress=None):
    """Hold <folder>/lock, for a library cdlbib does not manage (``folder`` is its .bibcheck).
    Unlike the data folder's lock, this one is in a folder of the user's, so nothing is left
    behind: on release the file is removed, and the folder too when this call made it and it
    holds nothing else (a checkout that does not ignore .bibcheck/ stays clean). A waiter that
    gets a file which is no longer the one at that name takes the new one instead.

    The library's folder is opened once; .bibcheck and the lock are made, opened, compared and
    removed by name from the held folders, refusing links (OSError), so a .bibcheck swapped
    for a link cannot send the lock file, or its removal, anywhere else."""
    try:
        import fcntl
    except ImportError:   # no flock on this platform: no lock
        yield
        return
    here = os.O_CLOEXEC | os.O_NOFOLLOW
    parent = os.open(folder.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    made, waited, work, handle = False, False, None, None
    try:
        while True:
            try:
                os.mkdir(folder.name, dir_fd=parent)
                made = True
            except FileExistsError:
                pass
            try:
                work = os.open(folder.name, os.O_RDONLY | os.O_DIRECTORY | here, dir_fd=parent)
            except FileNotFoundError:      # removed by the holder that made it: again
                continue
            try:
                handle = os.open("lock", os.O_WRONLY | os.O_CREAT | os.O_APPEND | here, 0o644, dir_fd=work)
            except FileNotFoundError:
                os.close(work)
                work = None
                continue
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:            # held by another command
                if progress and not waited:
                    progress(WRITING)
                waited = True
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:                       # still the file at that name, in the folder at that name?
                current = (os.fstat(handle).st_ino == os.stat("lock", dir_fd=work, follow_symlinks=False).st_ino
                           and os.fstat(work).st_ino == os.stat(folder.name, dir_fd=parent, follow_symlinks=False).st_ino)
            except FileNotFoundError:
                current = False
            if current:
                break
            os.close(handle)
            os.close(work)
            work = handle = None
        try:
            yield
        finally:
            with contextlib.suppress(OSError):     # removed while still held: no one else can hold this file
                os.unlink("lock", dir_fd=work)
            os.close(handle)                       # releases the lock
            handle = None
            if made:
                with contextlib.suppress(OSError):
                    os.rmdir(folder.name, dir_fd=parent)
    finally:
        for descriptor in (handle, work, parent):
            if descriptor is not None:
                with contextlib.suppress(OSError):
                    os.close(descriptor)


@contextlib.contextmanager
def transaction(ws, *, recovery=False, progress=None):
    """Hold the write lock of the library ``ws`` is. The managed library's is the lock of the
    data folder, and an unfinished update refuses (unless ``recovery``). Any other library's
    is <its .bibcheck>/lock, held for the time of the write and then removed. A library whose
    folder cannot be written at all (or is not there) has nothing to protect and is not
    locked. Re-entered freely by the holder."""
    from .api import is_managed
    managed = is_managed(ws)
    folder = home() if managed else Path(ws.work)
    owner = (os.getpid(), str(folder.resolve()))
    if owner in _owner.get():
        yield
        return
    if managed:
        lock = _locked(folder, progress, WAITING)
        lock.__enter__()
    elif not os.path.isdir(folder.parent):
        lock = contextlib.nullcontext()
    else:
        try:
            lock = _own_lock(folder, progress)
            lock.__enter__()
        except OSError as exc:
            if os.path.isdir(folder.parent) and os.access(folder.parent, os.W_OK):
                raise CdlbibError(f"{folder} cannot be written ({exc.strerror or exc}), so the library cannot be "
                                  "locked; nothing was changed.") from exc
            lock = contextlib.nullcontext()
            lock.__enter__()
    try:
        if managed and not recovery and _marked()[0]:
            raise CdlbibError(_interrupted_line(ws.root, _marked()[1]))
        token = _owner.set(_owner.get() + (owner,))
        try:
            if not managed and not isinstance(lock, contextlib.nullcontext):
                # A write to this library that was killed part-way is settled before anything
                # else is done under the lock (a send, an approval, another write): the library
                # is put back whole, or this refuses, naming the record (writer.recover).
                from . import writer
                try:
                    said = writer.recover(ws)
                except OSError as exc:
                    raise CdlbibError(f"An earlier write to {ws.bib} was interrupted and could not be settled "
                                      f"({exc.strerror or exc}); nothing was changed. The record of it is "
                                      f"{ws.work / writer.EDITS / writer.PENDING}; api.recover_interrupted tries "
                                      "again.") from exc
                # What this taking of the lock settled, for this library only (never what an
                # earlier call settled and nobody asked about).
                _settled.set({**(_settled.get() or {}), owner[1]: said})
            if not isinstance(lock, contextlib.nullcontext) and os.path.lexists(
                    Path(ws.work) / "approval-send" / "pending.json"):
                # Rows a send added to the approvals ledger and never committed (the send was
                # killed): the ledger is put back, or what could not be put back is said.
                from .api import settle_approval_send
                lines, problem = settle_approval_send(ws)
                name = str(Path(ws.work).resolve())
                held = dict(_settled.get() or {})
                held[name] = list(held.get(name, [])) + lines + ([problem] if problem else [])
                _settled.set(held)
            yield
        finally:
            _owner.reset(token)
    finally:
        lock.__exit__(None, None, None)


_settled = contextvars.ContextVar("cdlbib_settled_writes", default=None)


def settled(ws):
    """The lines saying which interrupted write to the library ``ws`` was settled when its
    lock was last taken (transaction); asking empties the list."""
    held = dict(_settled.get() or {})
    said = held.pop(str(Path(ws.work).resolve()), [])
    _settled.set(held)
    return list(said)


def serialized(function):
    @functools.wraps(function)
    def wrapped(ws, *args, **kwargs):
        with transaction(ws):
            return function(ws, *args, **kwargs)
    return wrapped


@dataclass
class CompletionBatch:
    checkpoint: object = None


_batch_owner = contextvars.ContextVar("cdlbib_completion_batch", default=None)


@contextlib.contextmanager
def completion_batch(ws):
    owner = (os.getpid(), str(ws.root))
    active = _batch_owner.get()
    if active is not None and active[0] == owner:
        yield active[1]
        return
    batch = CompletionBatch()
    token = _batch_owner.set((owner, batch))
    try:
        yield batch
    finally:
        _batch_owner.reset(token)
        if batch.checkpoint is not None:
            with transaction(ws, recovery=True):
                (home() / "completion-batches" / batch.checkpoint.stamp).unlink(missing_ok=True)


def batch_command(function):
    @functools.wraps(function)
    def wrapped(ws, *args, **kwargs):
        with completion_batch(ws):
            return function(ws, *args, **kwargs)
    return wrapped


def _completion_target():
    try:
        stamp = json.loads((home() / "completion-undo").read_text())
        if not isinstance(stamp, str) or not _STAMP_NAME.fullmatch(stamp):
            raise CdlbibError("The completion undo checkpoint cannot be read; use cdlbib update --list and choose an explicit backup stamp.")
        return stamp
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise CdlbibError("The completion undo checkpoint cannot be read; restore the printed batch backup with cdlbib update --undo STAMP.") from exc


def completion_checkpoint(ws, batch=None):
    """Called under transaction; checkpoint once, retain through every acceptance."""
    root = _managed_root(ws)
    made = batch.checkpoint if batch is not None else None
    if made is None:
        made = _backup(root)
        if batch is not None:
            batch.checkpoint = made
            folder = home() / "completion-batches"
            folder.mkdir(exist_ok=True)
            _write_json(folder / made.stamp, made.stamp)
    _write_json(home() / "completion-undo", made.stamp)
    return made


def _clone(source, partial, timeout):
    """git clone into ``partial``; (exit status, stderr). On a timeout, or when interrupted,
    git and its helpers are stopped first. The clone runs as a process group of its own so
    that a stalled transport helper can be stopped with it."""
    clone = subprocess.Popen(["git", "clone", "--quiet", "--", source, str(partial)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                             env=git_env(), start_new_session=True)
    try:
        _, errors = clone.communicate(timeout=timeout)
    except BaseException:
        import signal
        try:
            os.killpg(clone.pid, signal.SIGKILL)
        except (OSError, AttributeError):
            clone.kill()
        clone.wait()
        raise
    return clone.returncode, errors


def download(progress=None):
    """Make the managed library if it is not there, and return its folder.

    The upstream is cloned into <home>/library.partial, which becomes <home>/library by one
    rename, so no other command ever sees a half-made library. Any failure removes the
    partial folder and raises LibraryUnavailable; a clone that takes longer than CLONE_TIMEOUT
    seconds is such a failure. A library that is there but was cloned from another upstream
    than the configured one is refused (LibraryUnavailable) and left untouched.

    ``progress`` receives a line when a download starts, a line when this command has to wait
    for another one's download, and a line when the library was downloaded but the time of
    the download could not be recorded (that is not a failure: the library is usable).
    """
    folder, root, source = home(), path(), upstream()
    if exists():
        _require_upstream(root, source)
        return root
    partial = folder / "library.partial"

    def unavailable(reason):
        return LibraryUnavailable(f"The bibliography could not be downloaded from {source}: {reason}. "
                                  "If you already have a copy, pass --library PATH or set CDLBIB_LIBRARY.")

    try:
        lock = _locked(folder, progress)
        lock.__enter__()
    except OSError as exc:
        raise unavailable(f"{folder} cannot be written ({exc.strerror or exc})") from exc
    try:
        if exists():          # another command made it while this one waited
            _require_upstream(root, source)
            return root
        if root.exists():
            raise LibraryUnavailable(
                f"{root} exists but is not a complete copy of the bibliography, and cdlbib will not delete it. "
                "Move or remove that folder and run the command again, or pass --library PATH.")
        if progress:
            progress(f"downloading the bibliography to {root} ...")
        try:
            if partial.exists():   # left by an interrupted download
                shutil.rmtree(partial)
            status, errors = _clone(source, partial, CLONE_TIMEOUT)
            if status != 0:
                lines = [line.strip() for line in errors.splitlines() if line.strip()]
                raise unavailable((lines[-1] if lines else f"git clone exited with status {status}").rstrip("."))
            if not (partial / BIB_NAME).is_file():
                raise unavailable(f"it has no {BIB_NAME}")
            os.rename(partial, root)
        except subprocess.TimeoutExpired as exc:
            shutil.rmtree(partial, ignore_errors=True)
            raise unavailable(f"the download timed out (it did not finish within {CLONE_TIMEOUT} seconds)") from exc
        except FileNotFoundError as exc:
            shutil.rmtree(partial, ignore_errors=True)
            if exc.filename == "git":
                raise unavailable("git is required and was not found") from exc
            raise unavailable(str(exc)) from exc
        except OSError as exc:
            shutil.rmtree(partial, ignore_errors=True)
            raise unavailable(str(exc)) from exc
        except BaseException:      # LibraryUnavailable, Ctrl-C: nothing half-made stays behind
            shutil.rmtree(partial, ignore_errors=True)
            raise
        try:
            write_state(State(datetime.datetime.now(datetime.timezone.utc), source))
        except OSError as exc:     # the library is in place and usable; read_state() then says 'never checked'
            if progress:
                progress(f"note: the bibliography was downloaded, but the time could not be recorded in "
                         f"{folder / 'state.json'} ({exc.strerror or exc})")
        return root
    finally:
        lock.__exit__(None, None, None)


# --- backups: every change cdlbib makes to the managed library is reversible ------------------
#
# A backup is the folder <home>/backups/<UTC time>/ holding only what git cannot reproduce:
#   files/          the files under cdl.bib and verification/ whose bytes differ from the
#                   recorded commit: modified tracked files, untracked files, ignored files
#   ref.json        the branch, the commit, what `git status` said about those two paths (per
#                   path and as the original text), the tracked files that were deleted in
#                   the working tree, the folders that were there, and (in a backup taken
#                   just before an undo) every branch that undo moved, with the commit it
#                   was on, so that undoing the undo puts each branch back
#   changes.bundle  the commits that are on no branch of the upstream, when there are any
#   moved-<n>.bundle  the commits of the n-th moved branch that are on no branch of the upstream
# and, in the library itself, the private refs refs/cdlbib/backups/<UTC time> on the recorded
# commit and refs/cdlbib/backups/<UTC time>-moved-<n> on each moved branch's commit, so that
# git never discards them while the backup exists. They are deleted with the backup, and
# only then: a commit is kept for as long as a listed backup records it, and no longer.
#
# What restore() guarantees: afterwards the branch, the commit, and the bytes of every file
# under cdl.bib and verification/ are what they were when the backup was taken, and the same
# paths are reported as changed. What it does not preserve: whether a change was staged
# (changes come back unstaged; a file that was staged as new comes back untracked). ref.json
# keeps the original `git status --porcelain` text, so that information is not lost.
#
# Backup and restore themselves never copy, overwrite or delete a file outside those two
# paths, and never discard a local change to one, ignored files included. `.bibcheck/` is a
# rebuildable cache and is never backed up. The only git commands that change anything are:
# `git restore --source=<commit> --staged --worktree -- cdl.bib verification`, `git switch
# --no-overwrite-ignore` (never forced), `git branch <name> <commit>` for a branch that no
# longer exists, `git update-ref <ref> <new> <old>` (which fails unless the ref is still at
# <old>), `git update-ref -d` of a private ref of a backup being removed, and `git fetch`
# from the backup's own bundle into its private ref.

KEPT = ("cdl.bib", "verification")    # the only paths a backup holds and a restore writes
KEEP = 10                             # backups kept; older ones are deleted after one is made
UNDO = "cdlbib update --undo"
_STAMP = "%Y%m%dT%H%M%S.%fZ"
_STAMP_NAME = re.compile(r"\d{8}T\d{6}\.\d{6}Z")
_PARTIAL_NAME = re.compile(r"(\d{8}T\d{6}\.\d{6}Z)\.partial")
_STALE = datetime.timedelta(hours=1)  # a .partial folder older than this was left by a crash
_PINS = "refs/cdlbib/backups/"


@dataclass
class Backup:
    path: Path                     # <home>/backups/<UTC time>
    taken_at: datetime.datetime    # UTC
    branch: str | None             # None: the library was not on a branch
    commit: str
    changed: list                  # paths under cdl.bib and verification/ that git reported as changed or untracked
    has_bundle: bool               # local commits were saved in changes.bundle
    deleted: list = field(default_factory=list)   # tracked files that were not on disk
    folders: list = field(default_factory=list)   # the folders that were on disk under the two paths
    moved: list = field(default_factory=list)     # (branch, commit) of each branch the undo this backup preceded moved

    @property
    def stamp(self):
        """The backup's name, as `cdlbib update --list` shows it and `--undo STAMP` takes it."""
        return self.path.name

    @property
    def when(self):
        return self.taken_at.strftime("%Y-%m-%d %H:%M:%S UTC")


def backups_folder():
    """<home>/backups. Refused when the data folder is a place cdlbib must never delete in."""
    folder = Path(os.path.abspath(home()))
    if len(folder.parts) < 3 or folder == Path(os.path.abspath(Path.home())):
        raise CdlbibError(f"The data folder is set to {folder}; cdlbib will not keep or delete backups there. "
                          "Set CDLBIB_HOME to a folder of its own.")
    return folder / "backups"


def _git(root, *args, check=True):
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="surrogateescape", stdin=subprocess.DEVNULL,
                              env=git_env())
    except FileNotFoundError as exc:
        raise CdlbibError("git is required and was not found") from exc
    if check and done.returncode != 0:
        lines = [line.strip() for line in done.stderr.splitlines() if line.strip()]
        raise CdlbibError(f"git {args[0]} failed: " + (" ".join(lines) if lines else f"status {done.returncode}"))
    return done


def _listed(text):
    return [name for name in text.split("\0") if name]


def _same_name(name):
    return unicodedata.normalize("NFC", name)


def _managed_root(ws):
    """The managed library's folder, when ``ws`` is it and it is a git clone of its own."""
    root = Path(ws.root).resolve()
    if root != path().resolve() or not exists():
        raise CdlbibError(f"Backups are kept only for the library cdlbib manages ({path()}); {ws.root} is not it.")
    top = _git(root, "rev-parse", "--show-toplevel").stdout.strip()
    if Path(top).resolve() != root:
        raise CdlbibError(f"{root} is not a git clone of its own, so it cannot be backed up or restored.")
    return root


def _head(root):
    """(branch or None, commit) the library is on."""
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip() or None
    return branch, _git(root, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()


def _status(root, *pathspec, ignored=False):
    """(the porcelain text, [(XY, path)]) of `git status` limited to ``pathspec``; with
    ``ignored``, the files git ignores are listed too (as '!!')."""
    raw = _git(root, "status", "--porcelain", "-z", "--untracked-files=all", *(["--ignored"] if ignored else []),
               "--", *pathspec).stdout
    parts, entries, at = raw.split("\0"), [], 0
    while at < len(parts):
        item = parts[at]
        at += 1
        if len(item) < 4:
            continue
        entries.append((item[:2], item[3:]))
        if "R" in item[:2] or "C" in item[:2]:      # followed by the path it was renamed or copied from
            if "R" in item[:2] and at < len(parts):
                entries.append((item[:2], parts[at]))
            at += 1
    return raw, entries


_ELSEWHERE = (".", *(f":(exclude){top}" for top in KEPT))   # every path but the two


def _tree(base):
    """({name: path}, {name: path}) of the files and the folders under cdl.bib and
    verification/ in ``base``, as paths relative to it. Symbolic links are files and are
    never followed. Names are keyed in one Unicode form, so that what git lists and what
    the disk lists compare equal."""
    files, folders = {}, {}

    def walk(rel):
        mode = os.lstat(base / rel).st_mode
        if stat.S_ISDIR(mode):
            folders[_same_name(rel)] = rel
            for name in sorted(os.listdir(base / rel)):
                walk(f"{rel}/{name}")
        elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            files[_same_name(rel)] = rel
        else:
            raise CdlbibError(f"{base / rel} is neither a file nor a folder; it cannot be backed up.")

    for top in KEPT:
        if os.path.lexists(base / top):
            walk(top)
    return files, folders


def _commit_files(root, commit):
    """{name: (path, kind, blob id)} of the files of ``commit`` under the two paths; kind is
    'l' for a symbolic link, 'x' for an executable file, '-' for any other file."""
    found = {}
    for entry in _listed(_git(root, "ls-tree", "-r", "-z", commit, "--", *KEPT).stdout):
        described, _, name = entry.partition("\t")
        mode, kind, blob = described.split()
        if kind == "blob":
            found[_same_name(name)] = (name, {"120000": "l", "100755": "x"}.get(mode, "-"), blob)
    return found


def _unlike(file, entry):
    """Does the file on disk differ from the commit's ``entry`` for it (a value of
    _commit_files, or None when the commit has no such file)? Compared as git stores it: the
    raw bytes (or the link's target), and whether it is executable."""
    if entry is None:
        return True
    _, kind, blob = entry
    status = os.lstat(file)
    digest = hashlib.new("sha1" if len(blob) == 40 else "sha256")
    if stat.S_ISLNK(status.st_mode):
        target = os.fsencode(os.readlink(file))
        digest.update(b"blob %d\0" % len(target) + target)
        return (kind, blob) != ("l", digest.hexdigest())
    if kind != ("x" if status.st_mode & 0o100 else "-"):
        return True
    with open(file, "rb") as handle:
        digest.update(b"blob %d\0" % os.fstat(handle.fileno()).st_size)
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest() != blob


def _same(one, other):
    """Are two files the same: both links to the same target, or both regular files with the
    same bytes and the same executable bit."""
    if not (os.path.lexists(one) and os.path.lexists(other)):
        return False
    first, second = os.lstat(one), os.lstat(other)
    if stat.S_ISLNK(first.st_mode) or stat.S_ISLNK(second.st_mode):
        return stat.S_ISLNK(first.st_mode) and stat.S_ISLNK(second.st_mode) and os.readlink(one) == os.readlink(other)
    if not (stat.S_ISREG(first.st_mode) and stat.S_ISREG(second.st_mode)):
        return False
    return (first.st_mode & 0o111) == (second.st_mode & 0o111) and filecmp.cmp(one, other, shallow=False)


def _copy(source, target):
    """Make ``target`` the same file as ``source``, written beside it and moved into place."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _same(source, target):
        return
    # The copy is written in <home>/work and moved into place, so that a command that is killed
    # leaves nothing half-written in the library; beside the target only when that folder is
    # on another file system (a move from there would not be one step).
    try:
        beside = _work()
        if os.stat(beside).st_dev != os.stat(target.parent).st_dev:
            beside = target.parent
    except OSError:
        beside = target.parent
    handle, temporary = tempfile.mkstemp(dir=beside, prefix=".cdlbib-", suffix=".tmp")
    os.close(handle)
    try:
        if os.path.islink(source):
            os.unlink(temporary)
            os.symlink(os.readlink(source), temporary)
        else:
            shutil.copy2(source, temporary)
        os.replace(temporary, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


# --- an update that did not finish ------------------------------------------------------------
#
# An update that sets the user's edits aside (the decisions "update" and "discard", and the
# return from a send branch) takes several steps. Before the first of them it writes
# <home>/update-in-progress.json, naming the backup it took and the operation, flushed to the
# disk; the file is removed as the last step (or once the library was put back and checked).
# A command that finds the file, with the lock held (so the update is not still running in
# another process), was preceded by an update that was killed part-way: the library may be on
# the new version without the user's edits. Nothing is then updated and no backup is deleted;
# the command says so and names the backup, and `cdlbib update --undo` restores that backup
# and removes the file. The copies an update works on are in <home>/work, and are removed
# with the file.

MARKER = "update-in-progress.json"


def _work():
    """<home>/work: where an update's working copies are made (never in the library)."""
    folder = home() / "work"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _marked():
    """(is an unfinished update recorded, the stamp of the backup it took or None when the
    record cannot be read)."""
    file = home() / MARKER
    try:
        stamp = json.loads(file.read_text(encoding="utf-8"))["backup"]
    except FileNotFoundError:
        return False, None
    except (OSError, ValueError, KeyError, TypeError):
        return True, None
    return True, stamp if isinstance(stamp, str) and _STAMP_NAME.fullmatch(stamp) else None


def interrupted():
    """The stamp of the backup taken before an update that did not finish ('' when the record
    of it cannot be read); None when no update is unfinished."""
    standing, stamp = _marked()
    return (stamp or "") if standing else None


def _mark(backup, operation):
    """Record, durably, that an update is changing the library and which backup precedes it."""
    _write_json(home() / MARKER, {"backup": backup.stamp, "operation": operation,
                                  "started": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    with contextlib.suppress(OSError, AttributeError):       # the folder's entry too
        folder = os.open(home(), os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)


def _unmark():
    """The update is over (finished, or put back and checked): remove the record, and the
    working copies any update left in <home>/work."""
    with contextlib.suppress(FileNotFoundError):
        os.unlink(home() / MARKER)
    work = home() / "work"
    with contextlib.suppress(OSError):
        for name in os.listdir(work):
            if os.path.isdir(work / name) and not os.path.islink(work / name):
                shutil.rmtree(work / name, ignore_errors=True)
            else:
                with contextlib.suppress(OSError):
                    os.unlink(work / name)


def _interrupted_operation():
    operation = "update"
    try:
        named = json.loads((home() / MARKER).read_text())["operation"]
        if named in ("entry completion", "entry edit"):
            operation = named
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return operation


def _interrupted_line(root, stamp):
    operation = _interrupted_operation()
    return (f"an earlier {operation} of the bibliography in {root} was interrupted before it finished, so the library may "
            "be missing your changes; nothing was changed now. "
            + (f"Run `{UNDO} {stamp}` to put the library back as it was before that {operation} (backup {stamp})."
               if stamp else
               f"Run `cdlbib update --list` to see the backups, and `{UNDO} STAMP` to put the library back as it was "
               f"at the one taken before that {operation}."))


def _read(folder):
    """The Backup in ``folder``, or None when it is not a complete backup."""
    try:
        ref = json.loads((folder / "ref.json").read_text(encoding="utf-8"))
        taken = _stamp_time(folder.name)
        if taken is None or not (ref["branch"] is None or isinstance(ref["branch"], str)):
            return None
        return Backup(path=folder, taken_at=taken, branch=ref["branch"], commit=str(ref["commit"]),
                      changed=list(ref["changed"]), has_bundle=(folder / "changes.bundle").is_file(),
                      deleted=list(ref["deleted"]), folders=list(ref["folders"]),
                      moved=[(str(entry["branch"]), str(entry["commit"])) for entry in ref.get("moved", [])])
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _write_json(file, data):
    """Write ``data`` to ``file`` whole or not at all: a temporary file beside it, flushed to
    the disk, then moved into place. A crash leaves the old file or the new one, never a
    torn one."""
    handle, temporary = tempfile.mkstemp(dir=Path(file).parent, prefix="ref.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=1)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, file)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _unreadable(folder):
    """Why the folder of a backup cannot be read as one ('' when it can)."""
    if _read(folder) is not None:
        return ""
    try:
        ref = json.loads((folder / "ref.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "it has no ref.json"
    except OSError as exc:
        return f"ref.json cannot be read: {exc.strerror or exc}"
    except ValueError:
        return "ref.json is empty" if not (folder / "ref.json").stat().st_size else "ref.json is not complete"
    return "ref.json does not describe a backup" if isinstance(ref, dict) else "ref.json is not a backup's"


def unreadable_backups():
    """[(stamp, reason)] of the folders in <home>/backups that are named as backups are and
    cannot be read as one, newest first. They are never restored and never deleted."""
    folder = backups_folder()
    found = ((name, _unreadable(folder / name)) for name in reversed(_backup_names(folder)))
    return [(name, reason) for name, reason in found if reason]


def _stamp_time(name):
    """The UTC time a backup folder's name states, or None when the name is not a real time
    (99999999T999999.999999Z fits the pattern and is no time: such a folder is not ours)."""
    try:
        return datetime.datetime.strptime(name, _STAMP).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _backup_names(folder):
    """The names in ``folder`` that are backups this code wrote: real folders named by time."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(name for name in names if _STAMP_NAME.fullmatch(name) and _stamp_time(name) is not None
                  and (folder / name).is_dir() and not (folder / name).is_symlink())


def backups():
    """The backups, newest first."""
    folder = backups_folder()
    found = (_read(folder / name) for name in reversed(_backup_names(folder)))
    return [backup for backup in found if backup is not None]


def _drop(folder, name, root):
    """Delete one backup: the folder <home>/backups/<name>, whose name is a timestamp this
    code wrote, and the private refs that go with it."""
    if name in _backup_names(folder):
        shutil.rmtree(folder / name)
        pins = _git(root, "for-each-ref", "--format=%(refname)", _PINS, check=False).stdout.splitlines()
        for pin in pins:       # its own ref, and those of the branches recorded in it
            if pin == _PINS + name or pin.startswith(_PINS + name + "-moved-"):
                _git(root, "update-ref", "-d", pin, check=False)


def _kept_nowhere(root, commit):
    """Does no local branch and no branch of the upstream lead to ``commit``? When git cannot
    say, the answer is yes."""
    if not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", commit):
        return True
    held = _git(root, "for-each-ref", "--count=1", "--format=%(refname)", "--contains", commit,
                "refs/heads", "refs/remotes/origin", check=False)
    return held.returncode != 0 or not held.stdout.strip()


def _only_copy(root, backup):
    """Does ``backup`` record a commit (its own, or that of a branch an undo moved) that no
    local branch and no branch of the upstream leads to? Then the backup is what keeps that
    commit."""
    return any(_kept_nowhere(root, commit) for commit in [backup.commit] + [commit for _, commit in backup.moved])


def taken_off(backup):
    """[(branch, commit)] of the branches that the undo ``backup`` preceded took off a commit
    which no local branch and no branch of the upstream leads to now: the branch the library
    was on, and the others that undo moved. The backup keeps each commit, and restoring it
    puts each branch back."""
    if not exists():
        return []
    root, backup = path().resolve(), _read(Path(backup.path)) or backup
    recorded = ([(backup.branch, backup.commit)] if backup.branch else []) + list(backup.moved)
    return [(branch, commit) for branch, commit in recorded if _kept_nowhere(root, commit)]


def holds_only_copy(backup):
    """Is ``backup`` the only thing keeping a commit (see _only_copy)? Such a backup is never
    deleted to make room and does not count toward the KEEP that are kept."""
    return exists() and _only_copy(path().resolve(), backup)


def _prune(folder, root, notes=None):
    """Delete all but the KEEP newest backups. A backup that alone keeps a commit, and a
    folder that cannot be read as a backup (it may hold the only copy of something), are
    never deleted and are not counted. Called only after an operation has succeeded, and
    never undoes or fails it: an old backup that cannot be removed stays, and ``notes`` (a
    list, when given) receives one line naming its folder."""
    notes = [] if notes is None else notes
    if _marked()[0]:       # an update did not finish: until it is undone, no backup is deleted
        return
    try:
        ordinary = []
        for name in _backup_names(folder):
            made = _read(folder / name)
            if (made is not None and name != _completion_target()
                    and not (home() / "completion-batches" / name).exists()
                    and not _only_copy(root, made)):
                ordinary.append(name)
    except (OSError, CdlbibError) as exc:
        notes.append(f"note: the old backups in {folder} could not be looked through ({_why(exc)}); none was removed")
        return
    for name in ordinary[:-KEEP]:
        try:
            _drop(folder, name, root)
        except (OSError, CdlbibError) as exc:
            notes.append(f"note: the old backup {folder / name} could not be removed ({_why(exc)}); it was left there")


def _sweep(folder, root, now):
    """Remove what a crashed backup left: folders directly in <home>/backups named
    <timestamp>.partial whose timestamp is over an hour old (a backup being made right now
    is never that old), and the private ref of each when no finished backup has that name."""
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        named = _PARTIAL_NAME.fullmatch(name)
        if not named or not (folder / name).is_dir() or (folder / name).is_symlink():
            continue
        started = _stamp_time(named.group(1))
        if started is not None and now - started > _STALE:
            shutil.rmtree(folder / name)
            if not os.path.lexists(folder / named.group(1)):
                _git(root, "update-ref", "-d", _PINS + named.group(1), check=False)


def _backup(root):
    """Make a backup and return it. Nothing is pruned here: the caller prunes once its own
    operation has succeeded."""
    folder = backups_folder()
    branch, commit = _head(root)
    raw, entries = _status(root, *KEPT)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _sweep(folder, root, datetime.datetime.now(datetime.timezone.utc))
        while True:
            taken = datetime.datetime.now(datetime.timezone.utc)
            final, partial = folder / taken.strftime(_STAMP), folder / (taken.strftime(_STAMP) + ".partial")
            if os.path.lexists(final):
                continue
            try:
                partial.mkdir()
            except FileExistsError:
                continue
            break
    except OSError as exc:
        raise CdlbibError(f"No backup could be made in {folder} ({exc.strerror or exc}); nothing was changed.") from exc
    pin, pinned = _PINS + final.name, False
    try:
        files, folders = _tree(root)
        tracked = _commit_files(root, commit)
        (partial / "files").mkdir()
        for key, rel in files.items():          # only what the commit cannot give back
            if _unlike(root / rel, tracked.get(key)):
                _copy(root / rel, partial / "files" / rel)
        # Local commits: everything on HEAD that no branch of the upstream has.
        span = ("HEAD", "--not", "--remotes=origin")
        bundled = int(_git(root, "rev-list", "--count", *span).stdout) > 0
        if bundled:
            _git(root, "bundle", "create", "--quiet", str(partial / "changes.bundle"), *span)
        ref = {"taken_at": taken.isoformat(), "branch": branch, "commit": commit,
               "changed": sorted({name for _, name in entries}),
               "untracked": sorted(name for state, name in entries if state == "??"),
               "paths": {name: state for state, name in entries}, "status": raw,
               "deleted": sorted(rel for key, (rel, _, _) in tracked.items() if key not in files),
               "folders": sorted(folders.values()), "pin": pin, "bundle_ref": "HEAD" if bundled else None}
        _write_json(partial / "ref.json", ref)
        _git(root, "update-ref", "-m", "cdlbib backup", pin, commit, "")     # a new ref: fails if it exists
        pinned = True
        os.rename(partial, final)
    except BaseException as exc:
        shutil.rmtree(partial, ignore_errors=True)      # the folder this call made, and only that
        if pinned:
            _git(root, "update-ref", "-d", pin, check=False)
        if isinstance(exc, OSError):
            raise CdlbibError(f"No backup could be made in {folder} ({exc.strerror or exc}); nothing was changed.") from exc
        raise
    active = _batch_owner.get()
    if active is None or active[0][0] != os.getpid() or active[1].checkpoint is None:
        (home() / "completion-undo").unlink(missing_ok=True)
    made = _read(final)
    if made is None:
        raise CdlbibError(f"The backup just written to {final} cannot be read back; nothing was changed.")
    return made


def backup(ws, notes=None):
    """Save the state of the managed library and return the Backup: the files under cdl.bib
    and verification/ that differ from the commit it is on (modified, untracked and ignored
    files), the tracked files that are deleted, the branch and commit, what git reported as
    changed, a private ref that keeps the commit, and a bundle of the commits the upstream
    does not have. No file of the library is changed. Afterwards the KEEP newest backups
    are kept; an older one that cannot be removed is not a failure (``notes``, a list,
    receives a line naming it)."""
    root = _managed_root(ws)
    with transaction(ws, recovery=True):
        made = _backup(root)
        _prune(backups_folder(), root, notes)
        return made


def _saved(backup):
    """{name: path} of the files a backup holds."""
    return _tree(backup.path / "files")[0]


def _describes(root, backup):
    """The paths under cdl.bib and verification/ that are NOT as ``backup`` recorded them
    ([] when the files on disk are exactly the backup's: its saved files byte for byte,
    every other file as in its commit, its deleted files absent, and nothing else)."""
    tracked, saved, files = _commit_files(root, backup.commit), _saved(backup), _tree(root)[0]
    deleted = {_same_name(name) for name in backup.deleted}
    wrong = []
    for key, rel in files.items():
        if key in saved:
            good = _same(root / rel, backup.path / "files" / saved[key])
        else:
            good = key in tracked and key not in deleted and not _unlike(root / rel, tracked[key])
        if not good:
            wrong.append(rel)
    wrong += [rel for key, rel in saved.items() if key not in files]
    wrong += [rel for key, (rel, _, _) in tracked.items() if key not in files and key not in deleted and key not in saved]
    return sorted(wrong)


def _git_restore(root, commit):
    """Make the index and the tracked files under the two paths match ``commit``. Only the
    paths git knows, in the index or in the commit, are named (it refuses any other)."""
    specs = [top for top in KEPT
             if _git(root, "ls-files", "-z", "--", top).stdout
             or _git(root, "ls-tree", "-r", "-z", "--name-only", commit, "--", top).stdout]
    if specs:
        _git(root, "restore", f"--source={commit}", "--staged", "--worktree", "--", *specs)


def _set_aside(root, rel, into):
    """Move a file out of the library into the backup ``into`` (never delete it). It goes
    where the backup holds that path; if the backup already holds something different
    there, it goes under displaced/ instead, so nothing saved is overwritten."""
    source, target = root / rel, into.path / "files" / rel
    if os.path.lexists(target) and not _same(source, target):
        target, count = into.path / "displaced" / rel, 0
        while os.path.lexists(target):
            count += 1
            target = into.path / "displaced" / f"{rel}.{count}"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except OSError:                     # another filesystem
        shutil.move(str(source), str(target))


def _clear(root, into, commit):
    """Step b: leave under the two paths only the files of the current commit, unmodified.
    Changes to tracked files are in ``into`` already (checked by the caller); files the
    commit does not have are moved into it."""
    _git_restore(root, commit)
    tracked = _commit_files(root, commit)
    for key, rel in _tree(root)[0].items():
        if key not in tracked:
            _set_aside(root, rel, into)


def _put(root, backup, into):
    """Step e: with the library on the backup's commit, make the files under the two paths
    exactly what the backup recorded, and check that they are. A file the backup recorded as
    deleted is removed once git has made it the commit's own content (the commit keeps it);
    any other file that is not the backup's is moved into ``into``."""
    _git_restore(root, backup.commit)
    tracked, saved = _commit_files(root, backup.commit), _saved(backup)
    deleted = {_same_name(name) for name in backup.deleted}
    recorded = {_same_name(name) for name in backup.folders}
    files, folders = _tree(root)
    for key, rel in files.items():
        if key in saved or (key in tracked and key not in deleted):
            continue
        if key in tracked and not _unlike(root / rel, tracked[key]):
            os.unlink(root / rel)
        else:
            _set_aside(root, rel, into)
    for key in sorted(folders, key=len, reverse=True):           # deepest first; only empty folders go
        if key not in recorded:
            with contextlib.suppress(OSError):
                os.rmdir(root / folders[key])
    for rel in list(backup.folders) + list(saved.values()):
        _inside(rel)
        above = [root.joinpath(*rel.split("/")[:count]) for count in range(1, len(rel.split("/")))]
        linked = [str(one) for one in above if one.is_symlink()]
        if linked:      # never write through a link: it may lead out of the library
            raise CdlbibError(f"{linked[0]} is a link, and {rel} lies beneath it")
    for rel in backup.folders:
        (root / rel).mkdir(parents=True, exist_ok=True)
    for rel in saved.values():
        _copy(backup.path / "files" / rel, root / rel)
    wrong = _describes(root, backup)
    if wrong:
        raise CdlbibError(f"these files are not as the backup recorded them: {', '.join(wrong[:5])}"
                          + (", ..." if len(wrong) > 5 else ""))


_COMMIT_NAME = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
# Names that git reads as HEAD or as one of its own pseudo-refs (FETCH_HEAD, ORIG_HEAD, ...)
# before it reads them as a branch: a backup naming one as its branch was not written here.
_PSEUDO_REF = re.compile(r"@|HEAD|AUTO_MERGE|[A-Z_]+_HEAD")


def _inside(rel):
    """``rel`` when it is a plain relative path under cdl.bib or verification/; CdlbibError
    for anything else (absolute, a '..' or empty part, another top folder)."""
    parts = rel.split("/") if isinstance(rel, str) else []
    if (not parts or parts[0] not in KEPT or any(part in ("", ".", "..") for part in parts) or "\0" in rel
            or os.path.isabs(rel) or (os.name == "nt" and ("\\" in rel or ":" in rel))):
        raise CdlbibError(f"the path {rel!r} is not under {' or '.join(KEPT)}")
    return rel


def _trusted(root, backup, tree=False):
    """Refuse a backup whose recorded names could lead a restore outside the library's two
    paths or to something that is not a branch or a commit: every path read from it must be a
    plain path under cdl.bib or verification/, every branch a valid branch name, every commit
    a full hash. With ``tree`` (the commit must be in the library), also: no file or folder
    of the backup lies beneath a file or link of the backup or of its commit."""
    try:
        if not tree:
            for rel in list(backup.folders) + list(backup.deleted):
                _inside(rel)
            for branch, commit in [(backup.branch, backup.commit)] + list(backup.moved):
                if not _COMMIT_NAME.fullmatch(commit):
                    raise CdlbibError(f"{commit!r} is not a commit")
                if branch is not None and (
                        branch.startswith("-") or _PSEUDO_REF.fullmatch(branch)
                        or _git(root, "check-ref-format", "refs/heads/" + branch, check=False).returncode != 0
                        or _git(root, "check-ref-format", "--branch", branch, check=False).stdout.strip() != branch):
                    raise CdlbibError(f"{branch!r} is not a branch name")
            return
        tracked, saved = _commit_files(root, backup.commit), _saved(backup)
        deleted = {_same_name(name) for name in backup.deleted}
        holders = set(saved) | {key for key in tracked if key not in deleted}
        for rel in list(saved.values()) + list(backup.folders):
            parts = _inside(rel).split("/")
            above = [_same_name("/".join(parts[:count])) for count in range(1, len(parts) + (rel in backup.folders))]
            beneath = [name for name in above if name in holders]
            if beneath:
                raise CdlbibError(f"{rel} lies beneath or in place of the file {beneath[0]}")
    except CdlbibError as exc:
        raise CdlbibError(f"{backup.path} is not a backup cdlbib wrote ({exc}), so it was not restored. "
                          "Nothing was changed.") from exc


def _record_moves(root, into, displaced):
    """Record in the backup ``into`` each (branch, commit) an undo is about to move a branch
    off, and keep each commit for as long as that backup exists: a private ref, and a bundle
    when the commit is on no branch of the upstream. Restoring ``into`` puts each back."""
    file = into.path / "ref.json"
    ref = json.loads(file.read_text(encoding="utf-8"))
    moved = list(ref.get("moved", []))
    for branch, commit in displaced:
        if any(entry["branch"] == branch for entry in moved):
            if any(entry["branch"] == branch and entry["commit"] == commit for entry in moved):
                continue
            raise CdlbibError(f"{into.path} already records another commit for branch {branch}")
        number = len(moved)
        pin = f"{_PINS}{into.stamp}-moved-{number}"
        _git(root, "update-ref", "-m", "cdlbib undo", pin, commit, "")       # a new ref: fails if it exists
        bundle = None
        if int(_git(root, "rev-list", "--count", commit, "--not", "--remotes=origin").stdout) > 0:
            bundle = f"moved-{number}.bundle"
            _git(root, "bundle", "create", "--quiet", str(into.path / bundle), "refs/heads/" + branch,
                 "--not", "--remotes=origin")
        moved.append({"branch": branch, "commit": commit, "pin": pin, "bundle": bundle})
    ref["moved"] = moved
    _write_json(file, ref)


def _has_commit(root, commit):
    return _git(root, "cat-file", "-e", commit + "^{commit}", check=False).returncode == 0


def _clashes(mine, differs):
    """The paths in ``mine`` (the user's changed, untracked and ignored files outside the
    two paths; a folder ends in '/') that a move between two commits would write over:
    one of the paths the commits differ in, or a folder of one, or inside one."""
    found = set()
    for own in mine:
        bare = _same_name(own.rstrip("/"))
        for path_ in differs:
            other = _same_name(path_)
            if other == bare or bare.startswith(other + "/") or other.startswith(bare + "/"):
                found.add(own)
                break
    return sorted(found)


def _restore(root, backup, into, notes=None):
    """restore(), with the lock held. Returns the backup of the state before it."""
    folder = backups_folder()
    if backup is None or _read(Path(backup.path)) is None or Path(backup.path).parent != folder:
        raise CdlbibError(f"No backup has been made yet of {root}, so there is nothing to undo." if backup is None
                          else f"{backup.path} is not a backup in {folder}; nothing was changed.")
    _trusted(root, backup)
    own = into is None
    if own:
        into = _backup(root)
    elif _read(Path(into.path)) is None or Path(into.path).parent != folder or into.path == backup.path:
        raise CdlbibError(f"{into.path} is not a backup of the current state in {folder}; nothing was changed.")
    what = f"The backup of {backup.when}"
    target = backup.commit
    try:
        # a. Everything that can be checked before anything is changed.
        if not _has_commit(root, target):
            bundle = backup.path / "changes.bundle"
            if bundle.is_file() and _git(root, "bundle", "verify", "--quiet", str(bundle), check=False).returncode == 0:
                _git(root, "fetch", "--quiet", "--no-tags", str(bundle), f"HEAD:{_PINS}{backup.stamp}", check=False)
            if not _has_commit(root, target):
                raise CdlbibError(f"{what} cannot be restored: its commit {target[:8]} is no longer in the library"
                                  + (" and could not be read from the backup's bundle" if bundle.is_file() else
                                     ", and the backup holds no bundle of it") + ". Nothing was changed.")
        for number, (branch, commit) in enumerate(backup.moved):     # the branches a restore of this backup puts back
            if not _has_commit(root, commit):
                bundle = backup.path / f"moved-{number}.bundle"
                if bundle.is_file() and _git(root, "bundle", "verify", "--quiet", str(bundle), check=False).returncode == 0:
                    _git(root, "fetch", "--quiet", "--no-tags", str(bundle),
                         f"refs/heads/{branch}:{_PINS}{backup.stamp}-moved-{number}", check=False)
                if not _has_commit(root, commit):
                    raise CdlbibError(f"{what} cannot be restored: commit {commit[:8]} of branch {branch} is no "
                                      "longer in the library and could not be read from the backup. Nothing was changed.")
        _trusted(root, backup, tree=True)
        current, head = _head(root)
        in_place = current == backup.branch and head == target
        # Every branch this restore puts on a commit: the backup's own, then those an undo had
        # moved (recorded in the backup). (branch, where it is now or None, where it goes)
        plan = ([(backup.branch, target)] if backup.branch else []) + [
            (branch, commit) for branch, commit in backup.moved if branch != backup.branch]
        moves = [(branch, _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}",
                               check=False).stdout.strip() or None, commit) for branch, commit in plan]
        elsewhere = _status(root, *_ELSEWHERE)[0]
        if head != target:
            # git moves the clean tracked files outside the two paths with the commit. Anything
            # of the user's that this would write over is a refusal: changed and untracked
            # files, and ignored ones (git does not protect those unless told to).
            mine = [name for _, name in _status(root, *_ELSEWHERE, ignored=True)[1]]
            differs = _listed(_git(root, "diff", "--name-only", "--no-renames", "-z", head, target).stdout)
            clash = _clashes(mine, differs)
            if clash:
                raise CdlbibError(f"{what} cannot be restored: it would overwrite {', '.join(clash)}, which "
                                  "cdlbib does not back up. Commit, move or remove "
                                  f"{'that file' if len(clash) == 1 else 'those files'} and try again. "
                                  "Nothing was changed.")
        wrong = _describes(root, into) if into.commit == head else ["the commit"]
        if wrong:
            raise CdlbibError(f"The library changed after its backup was taken ({', '.join(wrong[:5])}"
                              f"{', ...' if len(wrong) > 5 else ''}), so nothing was restored. Nothing was changed.")
        # A branch that is about to leave a commit is recorded in `into` first, with that commit
        # kept by it, so that restoring `into` puts the branch back. (The branch the library is
        # on needs no entry: `into` records it as its own branch and commit.)
        displaced = [(branch, now) for branch, now, to in moves if now and now != to and branch != current]
        if displaced:
            _record_moves(root, into, displaced)
    except (CdlbibError, OSError) as exc:
        if own:      # nothing was changed: the copy just taken is not kept, so the newest backup stays the newest
            _drop(folder, into.stamp, root)
        if isinstance(exc, OSError):
            raise CdlbibError(f"{what} could not be checked ({exc.strerror or exc}"
                              f"{': ' + str(exc.filename) if exc.filename else ''}). Nothing was changed.") from exc
        raise
    saved = f"Your files as they were are saved in {into.path}; `{UNDO} {into.stamp}` puts them back."

    # b, c. Set the current files aside (they are in `into`) and move to the recorded commit.
    try:
        _clear(root, into, head)
        if not in_place:
            _git(root, "switch", "--quiet", "--no-overwrite-ignore", "--detach", target)
    except (CdlbibError, OSError) as exc:
        try:
            if _head(root) != (current, head):     # git moved although it reported a failure
                raise CdlbibError("the library is no longer on the commit it was on")
            _put(root, into, into)                 # puts the files back and checks every one of them
            if _status(root, *_ELSEWHERE)[0] != elsewhere:
                raise CdlbibError("files outside cdl.bib and verification/ are not as they were")
        except (CdlbibError, OSError) as second:
            raise CdlbibError(f"{what} could not be restored ({exc}), and the library could not be put back "
                              f"as it was ({second}). {saved}") from exc
        if own:      # checked: the library is as it was, so this copy of it is not kept either
            _drop(folder, into.stamp, root)
        raise CdlbibError(f"{what} could not be restored: {exc}. The library is as it was "
                          "(changes that were staged are now unstaged).") from exc

    # d, e. Put the branch on that commit, then the saved files.
    try:
        for branch, now, to in moves:
            if now is None:
                _git(root, "branch", "--quiet", branch, to)
            elif now != to:
                swap = _git(root, "update-ref", "-m", "cdlbib undo", f"refs/heads/{branch}", to, now, check=False)
                if swap.returncode != 0:
                    raise CdlbibError(f"branch {branch} is no longer at {now[:8]}, where it was a moment ago, "
                                      f"so it was not moved to {to[:8]}")
        if not in_place and backup.branch:
            _git(root, "switch", "--quiet", "--no-overwrite-ignore", backup.branch)
        _put(root, backup, into)
        if _head(root) != (backup.branch, target):
            raise CdlbibError("the library is not on the recorded branch and commit")
    except (CdlbibError, OSError) as exc:
        raise CdlbibError(f"{what} was only partly restored: {exc}. {saved}") from exc
    _prune(folder, root, notes)        # the restore is done: an old backup that stays is a note
    return into


def restore(backup, ws, into=None, notes=None):
    """Put the managed library back as it was when ``backup`` was taken: the branch (made
    again if it no longer exists), the commit (read from the backup's bundle if the library
    no longer has it), and the bytes of every file under cdl.bib and verification/. Whether
    a change was staged is not preserved: changes come back unstaged.

    ``into`` is a backup of the current state, taken just before; without one, restore takes
    it itself, and removes it again when nothing was changed (a refusal, or a failure after
    which the library was put back and checked). A file under the two paths that is not in
    ``backup`` is moved into ``into``, never deleted. A branch the restore moves off a commit
    is recorded in ``into`` with that commit, which ``into`` keeps; restoring ``into`` puts every
    such branch back, so undo followed by undo leaves every local branch where it was. Clean tracked files elsewhere follow the
    commit, as git moves them; any file elsewhere that this would overwrite (changed,
    untracked or ignored) is a refusal, before anything changes. Old backups are pruned only
    after a restore that succeeded, and one that cannot be removed does not fail it
    (``notes``, a list, receives a line naming it). Raises CdlbibError; when the user's files
    are then only in ``into``, the message names it and the command that restores it.
    Returns ``into``."""
    root = _managed_root(ws)
    with transaction(ws, recovery=True):
        return _restore(root, backup, into, notes)


def undo(ws, stamp=None, notes=None):
    """Restore the command checkpoint (otherwise newest), or ``stamp`` (Backup.stamp). The list of
    backups is read with the lock held. Returns (the backup restored, the backup of the
    state before it). ``notes`` (a list) receives non-fatal lines."""
    root = _managed_root(ws)
    with transaction(ws, recovery=True):
        saved = backups()
        standing, marked = _marked()
        named_recovery = stamp is not None
        if stamp is None and marked and any(one.stamp == marked for one in saved):
            stamp = marked       # an update did not finish: the backup to restore is the one it took
            if notes is not None:
                notes.append(f"note: backup {marked} is the one taken before the {_interrupted_operation()} that was interrupted; "
                             "it is the one restored")
        if stamp is None and _completion_target() is not None:
            stamp = _completion_target()
        if stamp is None:
            names = _backup_names(backups_folder())
            if names and _read(backups_folder() / names[-1]) is None:
                raise CdlbibError(
                    f"The newest backup, {backups_folder() / names[-1]}, cannot be read "
                    f"({_unreadable(backups_folder() / names[-1])}), so nothing was restored. Nothing was changed. "
                    f"`{UNDO} STAMP` restores a specific older backup; `cdlbib update --list` shows them.")
            if not saved:
                raise CdlbibError(f"No backup has been made yet of {root}, so there is nothing to undo.")
            chosen = saved[0]
        else:
            named = [one for one in saved if one.stamp == stamp.strip()]
            if not named and stamp.strip() in _backup_names(backups_folder()):
                there = backups_folder() / stamp.strip()
                raise CdlbibError(f"The backup {stamp.strip()} is there ({there}) but cannot be read "
                                  f"({_unreadable(there)}), so it was not restored. Nothing was changed. "
                                  f"`cdlbib update --list` shows the backups; `{UNDO} STAMP` restores another one.")
            if not named:
                raise CdlbibError(f"There is no backup {stamp.strip()} of {root}; `cdlbib update --list` shows "
                                  "the backups there are. Nothing was changed.")
            chosen = named[0]
        before = _restore(root, chosen, None, notes)
        if standing and (chosen.stamp == marked or (marked is None and named_recovery)):
            # _restore checked every file: a named restore also resolves an unreadable marker.
            _unmark()
            _prune(backups_folder(), root, notes)
        return chosen, before


# --- staying current: at most once a day, when a command runs ---------------------------------
#
# There is no scheduler. update() is called by a front end before a command's own work, and
# only for the managed library. Called by a command (not ``force``) it is the automatic
# check: it fetches when the last successful check is a day old, gives the upstream
# AUTO_FETCH_TIMEOUT seconds, and after an attempt that failed makes no other for RETRY_AFTER
# seconds. `cdlbib update` (``force``) ignores both rules and waits FETCH_TIMEOUT seconds.
# Without a decision the library is changed in one case only: it is on the upstream's default
# branch, has no commits of its own and no changes under cdl.bib or verification/, and the
# upstream has new commits. Then a backup is taken and the branch is fast-forwarded. The git
# commands that runs, and why none of them can lose work:
#   git fetch --quiet origin        writes remote-tracking refs and objects only
#   git merge --ff-only --no-overwrite-ignore --no-autostash --quiet <commit>
#                                   moves the branch forward along the upstream's own history
#                                   or does nothing; it refuses (changing nothing) when a
#                                   changed, untracked or ignored file would be written over
# and, read-only: config --get, rev-parse, symbolic-ref, rev-list --count, status, diff
# --name-only, for-each-ref (plus what _backup() and _prune() run).
#
# A library on the default branch that holds unsent work (changed or untracked files under the
# two paths, or commits the upstream does not have) is never updated without the user's
# decision: update() raises UpdateNeedsDecision and changes nothing. The front end asks, with
# the lock released, and calls update() again with the decision; everything is then checked
# afresh under the lock. "update" (keep my changes) and "discard" both begin with a backup,
# and what they run in addition to the above is:
#   git restore --source=<commit> --staged --worktree -- cdl.bib verification
#                                   only after the backup holds every changed file (checked)
#   moving an untracked file into the backup (never deleting one)
#   git cat-file blob, git merge-file on copies outside the library ("update": the merge is
#                                   worked out before the library is touched, and a collision
#                                   stops there, with nothing changed)
#   git switch --no-overwrite-ignore [--detach], git update-ref <branch> <new> <old>
#                                   ("discard" of local commits, which the backup has pinned
#                                   and bundled; the ref moves only if it is still at <old>)
# No stash is ever made, so none can be left behind. Every other state is reported and left
# alone.

FETCH_TIMEOUT = 120       # seconds `cdlbib update` gives a fetch (the lock is held meanwhile)
AUTO_FETCH_TIMEOUT = 15   # seconds the automatic check gives it: a command is waiting
RETRY_AFTER = 3600        # seconds after a failed automatic check before the next automatic one
WAITING = "waiting for another cdlbib to finish checking the bibliography for updates ..."
_DAY = datetime.timedelta(hours=24)
_ORIGIN = "refs/remotes/origin/"


@dataclass
class UpdateResult:
    action: str                    # not_due | skipped_offline | up_to_date | updated | left_alone | returned_to_main
                                   # | interrupted (an earlier update did not finish; nothing is done until it is undone)
    new_commits: int = 0           # commits the upstream has that the library did not
    backup: Backup | None = None   # taken before the library was changed
    message: str = ""              # one line for the user ("" for not_due)
    notes: list = field(default_factory=list)   # non-fatal lines (a time not recorded, an old backup not removed)


def _utc(now):
    if now is None:
        return datetime.datetime.now(datetime.timezone.utc)
    return now.replace(tzinfo=datetime.timezone.utc) if now.tzinfo is None else now


def check_due(now=None):
    """Is the daily check due: never checked (or state.json unreadable), last checked 24 hours
    ago or more, or last checked at a time that is still in the future."""
    last, now = read_state().last_check, _utc(now)
    return last is None or last > now or now - last >= _DAY


def _wanted(force, now):
    """Is a check to be made now: always when forced; else when the daily check is due and no
    automatic attempt failed within the last RETRY_AFTER seconds."""
    if force:
        return True
    if not check_due(now):
        return False
    tried = read_state().last_attempt
    return tried is None or not datetime.timedelta(0) <= _utc(now) - tried < datetime.timedelta(seconds=RETRY_AFTER)


def _fetch(root, timeout):
    """git fetch origin; (exit status, stderr). As _clone: a process group of its own, stopped
    with its helpers on a timeout or an interruption."""
    fetch = subprocess.Popen(["git", "-C", str(root), "fetch", "--quiet", "origin"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, errors="replace",
                             env=git_env(), start_new_session=True)
    try:
        _, errors = fetch.communicate(timeout=timeout)
    except BaseException:
        import signal
        try:
            os.killpg(fetch.pid, signal.SIGKILL)
        except (OSError, AttributeError):
            fetch.kill()
        fetch.wait()
        raise
    return fetch.returncode, errors


def _default_branch(root):
    """The upstream's default branch as the clone recorded it; master when it did not."""
    named = _git(root, "symbolic-ref", "--quiet", _ORIGIN + "HEAD", check=False).stdout.strip()
    return named[len(_ORIGIN):] if named.startswith(_ORIGIN) and len(named) > len(_ORIGIN) else "master"


def _count(number, noun):
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _some(names):
    return ", ".join(names[:5]) + (", ..." if len(names) > 5 else "")


def _why(exc):
    if isinstance(exc, OSError):
        return f"{exc.strerror or exc}" + (f": {exc.filename}" if exc.filename else "")
    return str(exc)


def _in_the_way(root, mine, differs):
    """The paths in ``mine`` that a move across ``differs`` would write over (see _clashes).
    Where the file system does not tell upper case from lower (git's core.ignorecase), names
    that differ only in case are the same file."""
    if _git(root, "config", "--type=bool", "--get", "core.ignorecase", check=False).stdout.strip() != "true":
        return _clashes(mine, differs)
    folded = {}
    for own in mine:
        folded.setdefault(_same_name(own).casefold(), own)
    return sorted(folded[name] for name in _clashes(list(folded), [_same_name(name).casefold() for name in differs]))


def _under_kept(name):
    return any(name == top or name.startswith(top + "/") for top in KEPT)


def _seen(root, branch, commit, target, edits):
    """A name for the state a decision is about: the branch, the commit, the upstream's commit,
    and the bytes of every changed file. A decision is applied only to the state it names."""
    digest = hashlib.sha256()
    for part in (branch or "", commit, target):
        digest.update(part.encode() + b"\0")
    for name in edits:
        file = root / name
        digest.update(os.fsencode(name) + b"\0")
        try:
            status = os.lstat(file)
        except OSError:
            digest.update(b"absent\0")
            continue
        if stat.S_ISLNK(status.st_mode):
            digest.update(b"link" + os.fsencode(os.readlink(file)))
        elif stat.S_ISREG(status.st_mode):
            digest.update(b"file%d:" % (status.st_mode & 0o111))
            with open(file, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _blob_into(root, blob, file):
    """Write a blob of the library's repository to ``file``, byte for byte."""
    Path(file).parent.mkdir(parents=True, exist_ok=True)
    with open(file, "wb") as out:
        done = subprocess.run(["git", "-C", str(root), "cat-file", "blob", blob], stdout=out, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, env=git_env())
    if done.returncode != 0:
        raise CdlbibError(f"git cat-file failed: {done.stderr.decode(errors='replace').strip() or done.returncode}")


_ENTRY = re.compile(rb"(?m)^[ \t]*@[ \t]*(\w+)[ \t]*[{(][ \t]*([^,\s{}()]+)[ \t]*,")


def _entries(data):
    """{citation key: [the text of each entry with that key]} of a BibTeX file, by its text
    alone (it need not be valid): an entry runs from its '@' to the last closing brace before
    the next entry."""
    found, starts = {}, list(_ENTRY.finditer(data))
    for at, match in enumerate(starts):
        if match.group(1).lower() in (b"comment", b"string", b"preamble"):
            continue
        chunk = data[match.start():starts[at + 1].start() if at + 1 < len(starts) else len(data)]
        end = chunk.rfind(b"}")
        found.setdefault(match.group(2).decode("utf-8", "replace"), []).append(chunk[:end + 1] if end >= 0 else chunk)
    return found


def _collisions(base, mine, theirs):
    """The citation keys whose entry the user changed and the upstream changed, differently."""
    was, here, there = _entries(base), _entries(mine), _entries(theirs)
    return sorted(key for key in set(was) | set(here) | set(there)
                  if was.get(key) != here.get(key) != there.get(key) != was.get(key))


def _carry(root, backup, commit, target, scratch):
    """Work out, without touching the library, what each file the user changed must hold once
    the library is on ``target`` for the user's changes to be kept on top of it. Returns
    [(path, file holding the content, or None for a file the user deleted)]. The user's
    files are read from ``backup`` (which holds them: checked by the caller); merges are made
    on copies in ``scratch``. Raises UpdateConflict when a change of the user's and a change of
    the upstream's collide: the same entry of cdl.bib changed differently by both (even where
    the lines would merge: no entry is ever made that neither wrote), or lines of a file that
    cannot be merged, or a file one deleted or replaced and the other changed."""
    base, theirs, saved = _commit_files(root, commit), _commit_files(root, target), _saved(backup)
    deleted = {_same_name(name) for name in backup.deleted}
    plan, files, keys, twice, binary = [], [], [], [], []
    for number, name in enumerate(backup.changed):
        key = _same_name(name)
        was, new = base.get(key), theirs.get(key)
        mine = backup.path / "files" / saved[key] if key in saved else None
        if mine is None and key not in deleted:
            continue                              # reported by git, yet the bytes are the commit's: no change to keep
        rel = saved[key] if key in saved else base[key][0]
        if mine is not None and any(other.startswith(key + "/") or key.startswith(other + "/") for other in theirs):
            files.append(rel)                     # a file here where the new version has a folder, or the reverse
        elif (was and was[1:]) == (new and new[1:]):
            plan.append((rel, mine))              # the upstream did not touch it
        elif mine is None:
            if new is not None:                   # deleted here, changed there
                files.append(rel)
        elif new is not None and not _unlike(mine, new):
            continue                              # the same change on both sides: the upstream's file is the user's
        elif was is None or new is None or "l" in (was[1], new[1]) or os.path.islink(mine):
            files.append(rel)                     # added by both, or changed here and deleted there, or a link
        else:
            folder = scratch / str(number)
            _blob_into(root, was[2], folder / "base")
            _blob_into(root, new[2], folder / "theirs")
            shutil.copy2(mine, folder / "merged")
            if rel == BIB_NAME:
                keys = _collisions((folder / "base").read_bytes(), (folder / "merged").read_bytes(),
                                   (folder / "theirs").read_bytes())
                if keys:
                    files.append(rel)
                    continue
            if any(b"\0" in (folder / name).read_bytes() for name in ("base", "merged", "theirs")):
                binary.append(rel)                # git does not merge such a file line by line
                files.append(rel)
                continue
            mine_was = (folder / "merged").read_bytes()
            merged = _git(root, "merge-file", "--quiet", str(folder / "merged"), str(folder / "base"),
                          str(folder / "theirs"), check=False)
            if merged.returncode != 0:            # > 0: that many conflicts; 255: not mergeable (binary)
                files.append(rel)
                continue
            if rel == BIB_NAME:                   # lines that merge can still give an entry twice
                here, there = _entries(mine_was), _entries((folder / "theirs").read_bytes())
                twice = sorted(key for key, texts in _entries((folder / "merged").read_bytes()).items()
                               if len(texts) > max(len(here.get(key, [])), len(there.get(key, []))))
                if twice:
                    files.append(rel)
                    continue
            plan.append((rel, folder / "merged"))
    if files:
        said = []
        if keys:
            said.append(f"{'this entry was' if len(keys) == 1 else 'these entries were'} changed both by you and in the "
                        f"new version: {', '.join(keys[:20])}{', ...' if len(keys) > 20 else ''}")
        if twice:
            said.append(f"{'this entry' if len(twice) == 1 else 'these entries'} would be in {BIB_NAME} twice, added "
                        f"both by you and in the new version: {', '.join(twice[:20])}{', ...' if len(twice) > 20 else ''}")
        others = [name for name in files if name not in binary and not (name == BIB_NAME and (keys or twice))]
        if others:
            said.append(f"your changes to {_some(others)} collide with the new version's")
        if binary:
            said.append(f"{_some(binary)} cannot be merged automatically because "
                        f"{'it contains' if len(binary) == 1 else 'they contain'} binary data")
        raise UpdateConflict(f"The bibliography was not updated: {'; and '.join(said)}. Nothing was changed: your "
                             "files are exactly as they were. Run `cdlbib send` to send your changes, or `cdlbib "
                             "update` to choose again.", entries=keys + twice, files=files)
    return plan


def _untracked(backup):
    """The untracked files a backup recorded (they are in it)."""
    listed = json.loads((backup.path / "ref.json").read_text(encoding="utf-8")).get("untracked", [])
    return [_inside(name) for name in listed]


def _set_edits_aside(root, backup, commit):
    """Leave the tracked files under the two paths as ``commit`` has them and no untracked file
    there: `git restore` from the commit, then each untracked file is moved into ``backup``
    (which already holds a copy of it), and the folders that leaves empty are removed.
    Ignored files are not touched."""
    _git_restore(root, commit)
    for rel in _untracked(backup):
        if os.path.lexists(root / rel):
            _set_aside(root, rel, backup)
            for above in list(Path(rel).parents)[:-2]:     # the folders below cdl.bib / verification
                with contextlib.suppress(OSError):
                    os.rmdir(root / above)                 # only an empty folder goes
    left = sorted({name for _, name in _status(root, *KEPT)[1]})
    if left:
        raise CdlbibError(f"these files still have changes: {_some(left)}")


def _fast_forward(root, target):
    merged = _git(root, "merge", "--ff-only", "--no-overwrite-ignore", "--no-autostash", "--quiet", target, check=False)
    lines = [line.strip() for line in merged.stderr.splitlines() if line.strip()]
    return merged.returncode, " ".join(lines) if lines else f"git merge exited with status {merged.returncode}"


def _apply_carried_plan(root, plan, backup):
    """Apply carried files, verify bytes and dirty paths, and name the backup on failure."""
    try:
        for rel, source in plan:
            if source is None:
                if os.path.lexists(root / rel):
                    os.unlink(root / rel)
            else:
                _copy(source, root / rel)
        bad = [rel for rel, source in plan
               if (os.path.lexists(root / rel) if source is None else not _same(source, root / rel))]
        kept = {_same_name(rel) for rel, _ in plan}
        bad += [name for _, name in _status(root, *KEPT)[1] if _same_name(name) not in kept]
        if bad:
            raise CdlbibError(f"these files are not as they should be: {_some(sorted(set(bad)))}")
    except (CdlbibError, OSError) as exc:
        raise CdlbibError(f"The update of {root} stopped part-way ({_why(exc)}). The library as it was is saved "
                          f"in {backup.path}; `{UNDO} {backup.stamp}` puts it back.") from exc


def _with_edits(root, decision, branch, commit, target, ahead, backup):
    """The decisions "update" (keep my changes on top of the new version) and "discard", with
    the lock held and ``backup`` just taken. Returns the files whose changes were carried over
    ("update") or [] ("discard"). Each step, and what is left if it fails:

    1. The backup must describe the files on disk exactly, or nothing is done (UpdateConflict
       and CdlbibError from here on mean: nothing was changed, unless they say otherwise).
    2. "update": the merge of every changed file is worked out on copies (_carry); a collision
       raises UpdateConflict with the library untouched.
    3. The edits are set aside (_set_edits_aside): the library's files are then the commit's.
    4. The branch is moved to the upstream's commit: a fast-forward, or for a library with
       commits of its own (discard only) `switch --detach`, a compare-and-swap of the branch,
       `switch` back.
    5. "update": each carried file is written (beside its place, then moved in) and checked.
    A failure in 3 or 4 that leaves the library on its commit is undone from the backup and
    checked (_put; nothing is done when the files are still exactly the backup's); any other
    failure names the backup and the command that restores it."""
    scratch = Path(tempfile.mkdtemp(prefix="update-", dir=_work()))
    try:
        wrong = _describes(root, backup)
        if wrong:
            raise _Untouched(f"these files changed while the backup was being taken: {_some(wrong)}")
        plan = _carry(root, backup, commit, target, scratch) if decision == "update" else []
        _mark(backup, decision)                    # from here until _unmark(), a kill is announced by the next command
        try:
            _set_edits_aside(root, backup, commit)
            if ahead:
                _git(root, "switch", "--quiet", "--no-overwrite-ignore", "--detach", target)
                swap = _git(root, "update-ref", "-m", "cdlbib update", f"refs/heads/{branch}", target, commit, check=False)
                if swap.returncode != 0:
                    raise CdlbibError(f"branch {branch} is no longer at {commit[:8]}, where it was a moment ago")
                _git(root, "switch", "--quiet", "--no-overwrite-ignore", branch)
            else:
                status, said = _fast_forward(root, target)
                if status != 0:
                    raise CdlbibError(f"git could not fast-forward the library ({said})")
            if _head(root) != (branch, target):
                raise CdlbibError("the library is not on the upstream's commit")
        except (CdlbibError, OSError) as exc:
            saved = f"The library as it was is saved in {backup.path}; `{UNDO} {backup.stamp}` puts it back."
            try:
                if _head(root) == (None, target) and _git(root, "rev-parse", "--verify", "--quiet",
                                                          f"refs/heads/{branch}", check=False).stdout.strip() == commit:
                    _git(root, "switch", "--quiet", "--no-overwrite-ignore", branch)     # step 4 stopped before the swap
                if _head(root) != (branch, commit):
                    raise CdlbibError("the library is no longer on the commit it was on")
                if _describes(root, backup):           # something was changed:
                    _put(root, backup, backup)         # put the files back, and check every one of them
            except (CdlbibError, OSError) as second:
                raise CdlbibError(f"The update of {root} stopped part-way ({_why(exc)}), and the library could not "
                                  f"be put back as it was ({_why(second)}). {saved}") from exc
            _unmark()                                  # put back, and checked
            raise CdlbibError(f"The bibliography was not updated: {_why(exc)}. The library is as it was (changes that "
                              f"were staged may now be unstaged); a copy of it is backup {backup.stamp}.") from exc
        _apply_carried_plan(root, plan, backup)
        _unmark()                                      # the last step: the update is whole
        return [rel for rel, _ in plan]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


class _Untouched(CdlbibError):
    """Raised inside update() when nothing was changed and the backup just taken is not needed."""


def _entry_count(root, commit, target, start=None):
    """How many entries of the working cdl.bib differ from the upstream's version the library
    started from, or from the commit ``start`` when one is named; None when that cannot be
    told (no such version, or a file that is not text). The entries are compared as text, key
    by key (_entries): no file is parsed, so this takes a fraction of a second on the whole
    bibliography."""
    try:
        start = start or _git(root, "merge-base", commit, target, check=False).stdout.strip()
        if not start:
            return None
        was = subprocess.run(["git", "-C", str(root), "cat-file", "blob", f"{start}:{BIB_NAME}"], capture_output=True,
                             stdin=subprocess.DEVNULL, env=git_env())
        now = (root / BIB_NAME).read_bytes()
        if was.returncode != 0 or b"\0" in now:
            return None
        now.decode("utf-8")
        before, after = _entries(was.stdout), _entries(now)
        return sum(1 for key in set(before) | set(after) if before.get(key) != after.get(key))
    except (OSError, ValueError, CdlbibError):      # no such file, not text, no git: the files are listed without a count
        return None


def _was_upstream(root, default, commit, earlier=""):
    """Is ``commit`` in a history the upstream's default branch once had: an ancestor of a
    value git recorded for origin/<default> (its reflog), or of ``earlier`` (its value before
    this fetch)? Then the library holds no commit of the user's. False when git cannot say."""
    listed = _git(root, "reflog", "show", "--format=%H", f"{_ORIGIN}{default}", check=False).stdout.split()[:200]
    if listed:       # and the value the oldest entry replaced (a clone records none for its first value)
        listed.append(_git(root, "rev-parse", "--verify", "--quiet", f"{_ORIGIN}{default}@{{{len(listed)}}}",
                           check=False).stdout.strip())
    for value in dict.fromkeys([earlier] * bool(earlier) + listed):
        if _COMMIT_NAME.fullmatch(value) and _has_commit(root, value) and _is_ancestor(root, commit, value):
            return True
    return False


CHOICES = ("keep", "update", "send", "discard")


# --- after a send -----------------------------------------------------------------------------
#
# `cdlbib send` leaves the library on a branch cdlbib/<login>/<topic>. At a check, such a
# branch is handled by what GitHub says about ITS pull request (the one from the logged-in
# user's branch of that name into the repository the library's origin sends to), and by what
# the branch holds locally. The branch's commits are the user's work until GitHub says the
# pull request was merged AND the branch's commit is the pull request's head, an ancestor of
# it, or already in the upstream's default branch. The branch's name alone decides nothing.
#
#   open                  nothing is changed; one line with the pull request's URL
#   no pull request       nothing is changed; one line
#   the lookup failed     nothing is changed; one line with the reason; like a failed fetch,
#                         the next automatic attempt is made after RETRY_AFTER seconds
#   merged, nothing else on the branch (no changed or untracked file under the two paths,
#   no commit that was not in the pull request)
#                         a backup; `git switch --no-overwrite-ignore <default>`; `git merge
#                         --ff-only --no-overwrite-ignore --no-autostash <upstream>`; `git
#                         branch -d <branch>` (never -D: git deletes the branch only when its
#                         commit is in the default branch; after a squash merge it is not,
#                         and the branch is kept); ``returned_to_main``
#   closed without being merged, or anything else on the branch
#                         UpdateNeedsDecision. "keep" changes nothing. "update" and "discard"
#                         begin with a backup and return to the default branch as above;
#                         "update" carries the changed files over, merged with the new
#                         version (worked out on copies first; a collision changes nothing),
#                         and is not offered when the branch has commits the upstream lacks.
#
# No branch is ever moved or deleted by force. The backup records the branch and its commit
# (and keeps the commit by a private ref, and in a bundle), and the default branch with the
# commit it was on, so `cdlbib update --undo` puts the library back on the send branch, makes
# that branch again if git deleted it, and puts the default branch back where it was. A
# backup that alone keeps a commit is never deleted to make room (_only_copy).
# The GitHub calls (who is logged in, the repository the origin sends to, the pull requests
# from the branch) are read-only, are made only for a library whose origin is a GitHub
# repository and that is on a branch cdlbib/..., only when a check is being made anyway, and
# together are given the time a fetch is given (AUTO_FETCH_TIMEOUT for the automatic check).

SEND_BRANCHES = "cdlbib/"


def _github_origin(root):
    """'OWNER/NAME' when the library's origin is a GitHub repository, else None. No network."""
    from . import publish
    named = publish.GITHUB_URL.match(_git(root, "config", "--get", "remote.origin.url", check=False).stdout.strip())
    return f"{named.group(1)}/{named.group(2)}" if named else None


def _look_up(origin, branch, timeout):
    """(the repository pull requests go to, this branch's pull request or None), asked of
    GitHub through gh; None when ``branch`` is not a send branch of the logged-in user's.
    The calls together are given ``timeout`` seconds. Raises CdlbibError (IdentityUnavailable,
    PublishRefused) when nobody is logged in or GitHub does not answer."""
    from . import identity, publish
    until = time.monotonic() + timeout

    def left():
        return max(until - time.monotonic(), 1.0)

    me = identity.current(timeout=left())
    if not branch.startswith(publish.branch_prefix(me.login)):
        return None
    upstream_name = publish.upstream_repository(origin, timeout=left())
    return upstream_name, publish.pull_request(upstream_name, f"{me.login}:{branch}", timeout=left())


def _is_ancestor(root, commit, of):
    return _git(root, "merge-base", "--is-ancestor", commit, of, check=False).returncode == 0


def _branch_commit(root, branch):
    return _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}", check=False).stdout.strip()


def _return_to_main(root, decision, branch, commit, default, base, target, backup, edits):
    """Leave the send branch ``branch`` (at ``commit``) for the default branch (at ``base``),
    fast-forwarded to the upstream's ``target``, with the lock held and ``backup`` just taken.
    ``decision`` "update" carries the changed files (``edits``) over; otherwise they stay
    behind, in the backup. Returns the files carried over. Each step, and what is left when
    it fails:

    1. The backup must describe the files on disk exactly, or nothing is done (_Untouched).
    2. "update": the merge of every changed file is worked out on copies (_carry); a collision
       raises UpdateConflict with the library untouched.
    3. With edits: they are set aside (_set_edits_aside); the files are then the commit's.
    4. `git switch --no-overwrite-ignore <default>`, then the fast-forward. git makes a switch
       whole or not at all. A failure here puts the library back: on the send branch again
       when the switch was made and the fast-forward was not, and the files from the backup,
       each one checked. Without edits that is _Untouched (nothing was changed, and the caller
       drops the backup); with edits a CdlbibError that names the backup.
    5. "update": each carried file is written (beside its place, then moved in) and checked.
    A failure that could not be put back names the backup and the command that restores it.
    The send branch itself is never moved here."""
    scratch = Path(tempfile.mkdtemp(prefix="update-", dir=_work()))
    try:
        wrong = _describes(root, backup)
        if wrong:
            raise _Untouched(f"these files changed while the backup was being taken: {_some(wrong)}")
        plan = _carry(root, backup, commit, target, scratch) if decision == "update" else []
        _mark(backup, f"return to {default}")      # from here until _unmark(), a kill is announced by the next command
        try:
            if edits:
                _set_edits_aside(root, backup, commit)
            _git(root, "switch", "--quiet", "--no-overwrite-ignore", default)
            if base != target:
                status, said = _fast_forward(root, target)
                if status != 0:
                    raise CdlbibError(f"git could not fast-forward branch {default} ({said})")
            if _head(root) != (default, target):
                raise CdlbibError(f"the library is not on branch {default} at the upstream's commit")
        except (CdlbibError, OSError) as exc:
            saved = f"The library as it was is saved in {backup.path}; `{UNDO} {backup.stamp}` puts it back."
            try:
                if _head(root) == (default, base) and _branch_commit(root, branch) == commit:
                    _git(root, "switch", "--quiet", "--no-overwrite-ignore", branch)    # switched, not fast-forwarded
                if _head(root) != (branch, commit) or _branch_commit(root, default) != base:
                    raise CdlbibError("the library is no longer on the branch and commit it was on")
                if _describes(root, backup):           # something was changed:
                    _put(root, backup, backup)         # put the files back, and check every one of them
            except (CdlbibError, OSError) as second:
                raise CdlbibError(f"The update of {root} stopped part-way ({_why(exc)}), and the library could not "
                                  f"be put back as it was ({_why(second)}). {saved}") from exc
            _unmark()                                  # put back, and checked
            if not edits:                              # checked: on its branch and commit, every file the backup's
                raise _Untouched(_why(exc)) from exc
            raise CdlbibError(f"The bibliography was not updated: {_why(exc)}. The library is as it was (changes that "
                              f"were staged may now be unstaged); a copy of it is backup {backup.stamp}.") from exc
        _apply_carried_plan(root, plan, backup)
        _unmark()                                      # the library is whole, on the default branch
        return [rel for rel, _ in plan]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _on_send_branch(root, branch, commit, default, target, new, found, decision, seen, force, timeout, record, notes,
                    made):
    """The check, for a library on a branch a send made (see the comment above), with the lock
    held and the upstream fetched. ``found`` is (the repository's name, the branch's pull
    request or None) when the caller knows it; None means: ask GitHub. Returns the
    UpdateResult, or None when the branch is not a send branch of the logged-in user's (the
    caller then treats it as any other branch). Raises UpdateNeedsDecision, UpdateConflict."""
    def result(message, checked=True):
        record(checked)
        return UpdateResult("left_alone", new_commits=new, notes=notes, message=message)

    if found is None:
        try:
            found = _look_up(_github_origin(root), branch, timeout)
        except CdlbibError as exc:       # nobody logged in, no gh, GitHub out of reach or too slow
            why = " ".join(str(exc).split())
            return result(f"the library is on branch {branch}, and its pull request could not be looked up "
                          f"({why if len(why) <= 300 else why[:300] + ' ...'}); nothing was changed. "
                          + ("Run `cdlbib update` to try again." if force else
                             "It will be tried again automatically in about an hour; `cdlbib update` tries now."),
                          checked=False)
        if found is None:
            return None
    where, pr = found
    if pr is None:
        return result(f"the library is on branch {branch}, which has no pull request in {where}; nothing was "
                      f"changed. Run `cdlbib send` to send it, or `git -C {shlex.quote(str(root))} switch {default}` "
                      "to leave the branch.")
    if pr.state == "open":
        return result(f"your pull request is still open: {pr.url}"
                      + (f" (one of {pr.matching} from branch {branch})" if pr.matching > 1 else "")
                      + "; nothing was changed")
    merged = pr.state == "merged"
    said = f"your pull request {pr.url} was {'merged' if merged else 'closed without being merged'}"

    def left(why, then, checked=True):
        return result(f"{said}, but {why}; nothing was changed. {then}", checked)

    # What the branch holds that was not sent. A commit is the pull request's only when it is
    # the head GitHub records for it or an ancestor of that head; or it is in the upstream's
    # default branch already.
    head = pr.head if _COMMIT_NAME.fullmatch(pr.head or "") else ""
    known = bool(head) and (head == commit or _has_commit(root, head))
    if _is_ancestor(root, commit, target) or (merged and known and (head == commit or _is_ancestor(root, commit, head))):
        extra = 0
    else:
        since = head if merged and known and _is_ancestor(root, head, commit) else target
        extra = int(_git(root, "rev-list", "--count", f"{since}..{commit}").stdout)
    edits = sorted({name for _, name in _status(root, *KEPT)[1]})
    token = _seen(root, branch, commit, f"{target} {pr.state} {head}", edits)
    if decision in ("update", "discard") and seen is not None and seen != token:
        return left("the library or the upstream changed after you were asked what to do",
                    "Run `cdlbib update` to be asked again.", checked=None)

    # Where the library would return to: the local default branch, which must be the upstream's
    # own history (it is only ever fast-forwarded).
    base = _branch_commit(root, default)
    if not base or not _is_ancestor(root, base, target):
        return left(f"the library could not be put back on branch {default} ("
                    + (f"there is no local branch {default}" if not base else
                       "it has commits that the upstream does not have") + ")",
                    f"To update, run `git -C {shlex.quote(str(root))} switch {default}`, then `cdlbib update`.")
    # Files git would write over on the way (to the default branch, then forward): a refusal
    # before anything is backed up, as in _update.
    mine = [name for state, name in _status(root, ".", ignored=True)[1] if state == "!!" or not _under_kept(name)]
    differs = set()
    for one, other in ((commit, base), (base, target)):
        differs.update(_listed(_git(root, "diff", "--name-only", "--no-renames", "-z", one, other).stdout))
    clash = _in_the_way(root, mine, sorted(differs))
    if clash:
        return left(f"returning to branch {default} would overwrite your own {_some(clash)}",
                    f"Move {'that file' if len(clash) == 1 else 'those files'} out of the way, then run `cdlbib update`.")

    if not merged or extra or edits:
        choices = tuple(choice for choice in CHOICES
                        if not (choice == "update" and (extra or not edits))
                        and not (choice == "send" and (extra or not edits or not merged)))
        if decision is None:
            raise UpdateNeedsDecision(
                (f"Your pull request {pr.url} was merged, and branch {branch} of the library in {root} has changes "
                 "that have not been sent. Nothing was changed." if merged else
                 f"Your pull request {pr.url} was closed without being merged. Branch {branch} of the library in "
                 f"{root} is still selected. Nothing was changed."),
                changed=edits, new_commits=new, local_commits=extra, choices=choices, seen=token, branch=branch,
                pull_request=pr.url, state=pr.state, default=default)
        if decision == "update" and extra:
            return left(f"branch {branch} has {_count(extra, 'commit')} that the upstream does not have, which cannot "
                        "be kept on top of the new version", "Run `cdlbib update` and choose again.", checked=None)
    backup = _backup(root)
    made.append(backup)
    try:
        if base != target:       # the backup records where the default branch was: an undo puts it back there
            try:
                _record_moves(root, backup, [(default, base)])
            except (CdlbibError, OSError) as exc:
                raise _Untouched(_why(exc)) from exc
        carried = _return_to_main(root, decision, branch, commit, default, base, target, backup, edits)
    except (_Untouched, UpdateConflict) as exc:
        if (_head(root) == (branch, commit) and _branch_commit(root, default) == base
                and not _describes(root, backup)):
            _drop(backups_folder(), backup.stamp, root)      # checked: nothing was changed, so the copy is not kept
            made.clear()
        if isinstance(exc, UpdateConflict):                  # (its advice to run `cdlbib send` is for the default branch)
            raise UpdateConflict(str(exc).replace("Run `cdlbib send` to send your changes, or `cdlbib update` to "
                                                  "choose again.", "Run `cdlbib update` to choose again."),
                                 entries=exc.entries, files=exc.files) from exc
        return left(str(exc), "Run `cdlbib update` to try again.", checked=None if decision else False)
    backup = _read(backup.path) or backup
    made[:] = [backup]
    # The library is on the default branch. git deletes the send branch only when its commit
    # is in that branch; refusing (after a squash merge, or with unsent commits) is not a failure.
    _git(root, "branch", "--quiet", "-d", branch, check=False)
    if not _branch_commit(root, branch):
        note = f"branch {branch} was deleted"
    elif extra:
        note = f"branch {branch} was kept: it holds {_count(extra, 'commit')} that the upstream does not have"
    elif merged and head == commit:
        note = (f"branch {branch} was kept (git does not count a squash-merged branch as merged); everything on it is "
                "in the merged pull request, so it is safe to delete")
    else:
        note = f"branch {branch} was kept (git did not delete it)"
    record(True)
    _prune(backups_folder(), root, notes)          # the return is done; an old backup that stays is a note
    message = (f"{said}: the library is back on branch {default}, up to date with the upstream"
               + (f" ({_count(new, 'new commit')})" if new else ""))
    if edits and decision == "update":
        message += ", with your changes kept" + (f" ({_some(carried)})" if carried else "")
    elif edits:
        message += f"; discarded your changes to {_some(edits)}"
    return UpdateResult("returned_to_main", new_commits=new, backup=backup, notes=notes,
                        message=f"{message}; {note} (the library as it was is backup {backup.stamp}; "
                                f"`{UNDO} {backup.stamp}` puts it back)")


@dataclass
class Behind:
    """Where the managed library stands against its upstream, from the refs git has now."""
    branch: str | None             # None: the library is not on a branch
    commit: str
    default: str                   # the upstream's default branch
    target: str                    # the upstream's commit on it ("" when it has no such branch)
    new_commits: int = 0           # commits the upstream has that the library does not
    local_commits: int = 0         # commits the library has that the upstream does not
    new_entries: int | None = None # keys of the upstream's cdl.bib that the library's commit lacks (behind() only)
    fetched: bool = False          # the upstream was asked just now
    problem: str = ""              # why it could not be asked, when a fetch was wanted and failed


def _behind(root):
    """The one count of how far ``root`` is behind (and ahead of) its upstream's default branch,
    as last fetched. Read-only: symbolic-ref, rev-parse, rev-list --count."""
    branch, commit = _head(root)
    default = _default_branch(root)
    target = _git(root, "rev-parse", "--verify", "--quiet", f"{_ORIGIN}{default}^{{commit}}", check=False).stdout.strip()
    if not target:
        return Behind(branch, commit, default, "")
    return Behind(branch, commit, default, target,
                  new_commits=int(_git(root, "rev-list", "--count", f"{commit}..{target}").stdout),
                  local_commits=int(_git(root, "rev-list", "--count", f"{target}..{commit}").stdout))


def _blob_entries(root, commit):
    """{key: text} of cdl.bib at ``commit`` (_entries); None when it has none or git cannot say."""
    try:
        was = subprocess.run(["git", "-C", str(root), "cat-file", "blob", f"{commit}:{BIB_NAME}"], capture_output=True,
                             stdin=subprocess.DEVNULL, env=git_env())
    except OSError:
        return None
    return _entries(was.stdout) if was.returncode == 0 else None


def behind(ws, fetch=False, progress=None):
    """How far the managed library is behind its upstream: a Behind. Nothing in the library's
    files, its branch or the record of the daily check is changed. With ``fetch`` the upstream
    is asked first, as the daily check asks it (git fetch, AUTO_FETCH_TIMEOUT seconds, under
    the lock: it writes remote-tracking refs and objects only); when that fails the counts
    are those of the last fetch and ``problem`` says why. update() counts with the same
    helper. Any other library than the managed one is a CdlbibError."""
    root = Path(ws.root).resolve()
    if root != path().resolve() or not exists():
        raise CdlbibError(f"Only the library cdlbib manages ({path()}) has an upstream to compare with; "
                          f"{ws.root} is not it.")
    problem, fetched = "", False
    if fetch:
        try:
            with transaction(ws, recovery=True, progress=progress):
                status, errors = _fetch(root, AUTO_FETCH_TIMEOUT)
            lines = [line.strip() for line in errors.splitlines() if line.strip()]
            fetched = status == 0
            problem = "" if fetched else f"git fetch failed ({lines[-1] if lines else f'status {status}'})"
        except subprocess.TimeoutExpired:
            problem = f"the upstream did not answer within {AUTO_FETCH_TIMEOUT} seconds"
        except OSError as exc:
            problem = _why(exc)
    at = _behind(root)
    at.fetched, at.problem = fetched, problem
    if at.target:
        mine, theirs = _blob_entries(root, at.commit), _blob_entries(root, at.target)
        at.new_entries = None if mine is None or theirs is None else len(set(theirs) - set(mine))
    return at


def _update(root, force, now, made, decision=None, seen=None, found=None):
    """update(), with the lock held. ``made`` receives the backup, once one is taken.
    ``found``: the pull request of the send branch the library is on, when the caller knows
    it (see _after_send); None means it is looked up."""
    standing, stamp = _marked()
    if standing:          # an earlier update was killed part-way (it is not running: the lock is held here)
        return UpdateResult("interrupted", message=_interrupted_line(root, stamp))
    if decision is None and not _wanted(force, now):      # another command checked, or tried, while this one waited
        return UpdateResult("not_due")
    when = _utc(now)
    if Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip()).resolve() != root:
        raise CdlbibError(f"{root} is not a git clone of its own, so it cannot be updated.")
    _require_upstream(root, upstream())
    origin = _git(root, "config", "--get", "remote.origin.url", check=False).stdout.strip() or "origin"
    timeout = FETCH_TIMEOUT if force else AUTO_FETCH_TIMEOUT
    notes = []

    def record(checked):
        """A completed check sets last_check. A failed automatic attempt sets last_attempt and
        leaves last_check; a failed `cdlbib update` records nothing, and None records nothing."""
        if checked is None or (not checked and force):
            return
        before = read_state()
        state = State(when, upstream()) if checked else State(before.last_check, before.upstream, when)
        try:
            write_state(state)
        except OSError as exc:      # not fatal: the check then runs again with the next command
            notes.append(f"note: the time of the update check could not be recorded in {home() / 'state.json'} "
                         f"({exc.strerror or exc}); the check will run again with the next command")

    def skipped(reason):
        record(False)
        then = ("Run `cdlbib update` to try again." if force else
                "It will be tried again automatically in about an hour; `cdlbib update` tries now.")
        return UpdateResult("skipped_offline", notes=notes,
                            message=f"update check skipped: {reason}; working with the copy in {root}. {then}")

    if decision in ("keep", "send"):
        # Nothing is changed and nothing need be fetched: the time is recorded, so the question
        # is not asked again until the next day's check. ("send": the front end runs the send.)
        record(True)
        return UpdateResult("left_alone", notes=notes, message=(
            "the bibliography was not updated and your changes are as they were; nothing was changed. "
            "You will be asked again tomorrow; `cdlbib update` asks now." if decision == "keep" else
            "the bibliography was not updated: your changes are sent first (`cdlbib send`)"))

    earlier = _git(root, "rev-parse", "--verify", "--quiet", f"{_ORIGIN}{_default_branch(root)}^{{commit}}",
                   check=False).stdout.strip()       # where the upstream was when this library last heard from it
    try:
        status, errors = _fetch(root, timeout)
    except subprocess.TimeoutExpired:
        return skipped(f"{origin} did not answer within {timeout} seconds")
    except FileNotFoundError:
        return skipped("git is required and was not found")
    except OSError as exc:
        return skipped(_why(exc))
    if status != 0:
        lines = [line.strip() for line in errors.splitlines() if line.strip()]
        fatal = [line for line in lines if line.startswith("fatal:")]
        said = (fatal[0][len("fatal:"):].strip() if fatal else lines[-1] if lines else f"status {status}").rstrip(".")
        return skipped(f"git fetch from {origin} failed ({said})")

    at = _behind(root)
    branch, commit, default, target = at.branch, at.commit, at.default, at.target
    again = "Run `cdlbib update` to check again."
    if not target:
        record(True)
        return UpdateResult("left_alone", notes=notes,
                            message=f"the upstream has no branch {default}, so the bibliography in {root} was not "
                                    f"updated; nothing was changed. {again}")
    new = at.new_commits
    if found is not None and not (branch and branch.startswith(SEND_BRANCHES)):
        raise CdlbibError(f"{root} is not on a branch a send made (it is on {branch or 'no branch'}); nothing was changed.")
    if branch and branch.startswith(SEND_BRANCHES) and (found is not None or _github_origin(root)):
        outcome = _on_send_branch(root, branch, commit, default, target, new, found, decision, seen, force, timeout,
                                  record, notes, made)
        if outcome is not None:
            return outcome
    if new == 0:
        if decision in ("update", "discard") and seen is not None:      # the question was about a newer version
            return UpdateResult("left_alone", notes=notes,
                                message="the library or the upstream changed after you were asked what to do; nothing "
                                        "was changed. Run `cdlbib update` to be asked again.")
        record(True)
        return UpdateResult("up_to_date", message=f"the bibliography in {root} is up to date", notes=notes)

    def left(why, then, checked=True):
        record(checked)
        return UpdateResult("left_alone", new_commits=new, notes=notes,
                            message=f"a newer version of the bibliography is available ({_count(new, 'new commit')}), "
                                    f"but {why}; nothing was changed. {then}")

    if branch != default:
        return left(f"the library is on branch {branch}, not {default}" if branch else "the library is not on a branch",
                    f"To update, run `git -C {shlex.quote(str(root))} switch {default}`, then `cdlbib update`.")
    ahead = at.local_commits
    edits = sorted({name for _, name in _status(root, *KEPT)[1]})
    token = _seen(root, branch, commit, target, edits)
    if decision in ("update", "discard") and seen is not None and seen != token:
        return left("the library or the upstream changed after you were asked what to do",
                    "Run `cdlbib update` to be asked again.", checked=None)
    # Files git would write over without asking are a refusal before anything is backed up:
    # the user's changed, untracked and ignored files that the new commits touch. (Changed and
    # untracked files under the two paths are the unsent work a decision is asked about.)
    mine = [name for state, name in _status(root, ".", ignored=True)[1] if state == "!!" or not _under_kept(name)]
    differs = _listed(_git(root, "diff", "--name-only", "--no-renames", "-z", commit, target).stdout)
    clash = _in_the_way(root, mine, differs)
    if clash:
        return left(f"updating would overwrite your own {_some(clash)}",
                    f"Move {'that file' if len(clash) == 1 else 'those files'} out of the way, then run `cdlbib update`.")
    # Commits the upstream does not have, and yet no work of the user's: the upstream's history
    # was rewritten, and the library's commit is one the upstream itself once had.
    rewritten = bool(ahead) and not edits and _was_upstream(root, default, commit, earlier)
    if ahead or edits:
        choices = tuple(choice for choice in CHOICES
                        if not (choice == "update" and ahead) and not (choice == "send" and not edits))
        if decision is None and rewritten:
            raise UpdateNeedsDecision(
                f"The history of the bibliography's upstream was changed, and the library in {root} matches an older "
                "version of it. Nothing was changed.",
                changed=[], new_commits=new, local_commits=ahead, choices=choices, seen=token, rewritten=True)
        if decision is None:
            raise UpdateNeedsDecision(
                f"A newer version of the bibliography is available ({_count(new, 'new commit')}), and the library in "
                f"{root} has changes that have not been sent. Nothing was changed.",
                changed=edits, new_commits=new, local_commits=ahead, choices=choices, seen=token)
        if decision == "update" and ahead:
            return left(f"the library has {_count(ahead, 'commit')} that the upstream does not have, which cannot be "
                        "kept on top of the new version", "Run `cdlbib update` and choose again.", checked=None)
        backup = _backup(root)
        made.append(backup)
        try:
            carried = _with_edits(root, decision, branch, commit, target, ahead, backup)
        except (_Untouched, UpdateConflict) as exc:
            if _head(root) == (branch, commit) and not _describes(root, backup):
                _drop(backups_folder(), backup.stamp, root)      # checked: nothing was changed, so the copy is not kept
                made.clear()
            if isinstance(exc, UpdateConflict):
                raise
            return left(str(exc), "Run `cdlbib update` to try again.", checked=None)
        record(True)
        _prune(backups_folder(), root, notes)      # the update is done; an old backup that stays is a note
        if decision == "update":
            message = (f"updated the bibliography: {_count(new, 'new commit')}, with your changes kept"
                       + (f" ({_some(carried)})" if carried else "")
                       + f" (the library as it was is backup {backup.stamp}; `{UNDO} {backup.stamp}` puts it back)")
        elif rewritten:
            message = (f"moved the bibliography to the upstream's new history ({_count(new, 'new commit')}; the library "
                       f"as it was is backup {backup.stamp}; `{UNDO} {backup.stamp}` puts it back)")
        else:
            gone = ([_count(ahead, "commit")] if ahead else []) + ([f"your changes to {_some(edits)}"] if edits else [])
            message = (f"updated the bibliography: {_count(new, 'new commit')}; discarded {' and '.join(gone)} "
                       f"(saved in backup {backup.stamp}; `{UNDO} {backup.stamp}` brings them back)")
        return UpdateResult("updated", new_commits=new, backup=backup, notes=notes, message=message)

    backup = _backup(root)
    made.append(backup)
    merged = _git(root, "merge", "--ff-only", "--no-overwrite-ignore", "--no-autostash", "--quiet", target, check=False)
    if merged.returncode != 0 or _head(root) != (branch, target):
        lines = [line.strip() for line in merged.stderr.splitlines() if line.strip()]
        said = " ".join(lines) if lines else f"git merge exited with status {merged.returncode}"
        if _head(root) == (branch, commit) and not _describes(root, backup):
            _drop(backups_folder(), backup.stamp, root)      # checked: nothing was changed, so the copy is not kept
            made.clear()
            # Not a completed check: it is tried again after RETRY_AFTER, not after a day.
            return left(f"git could not fast-forward the library ({said})", "Run `cdlbib update` to try again.",
                        checked=False)
        raise CdlbibError(f"The update of {root} stopped part-way ({said}). The library as it was is saved in "
                          f"{backup.path}; `{UNDO} {backup.stamp}` puts it back.")
    record(True)
    _prune(backups_folder(), root, notes)          # the update is done; an old backup that stays is a note
    return UpdateResult("updated", new_commits=new, backup=backup, notes=notes,
                        message=f"updated the bibliography: {_count(new, 'new commit')} (the library as it was is "
                                f"backup {backup.stamp}; `{UNDO}` puts it back)")


def _after_send(ws, state, url="", head="", matching=1, **options):
    """update(), for a library on a send branch whose pull request is known to the caller:
    ``state`` is "open", "merged" or "closed" (None: there is no pull request), ``url`` its
    address, ``head`` the commit GitHub records as its head, ``matching`` how many pull
    requests there are from the branch. GitHub is not asked. ``options`` are update()'s
    (``force`` is True unless given: the caller asked for this). A library that is not on a
    branch cdlbib/... is a CdlbibError, with nothing changed."""
    from . import publish
    known = publish.PullRequest(url=url, state=state, head=head or "", matching=matching) if state else None
    return update(ws, **dict({"force": True}, **options), _found=("the upstream", known))


def update(ws, force=False, decision=None, now=None, progress=None, seen=None, _found=None):
    """Bring the managed library up to date.

    Without ``force`` this is the automatic check a command makes: nothing is fetched when the
    last successful check is under 24 hours old, or when an automatic attempt failed within
    the last RETRY_AFTER seconds (``not_due``; the lock is not even taken). Otherwise the
    upstream is fetched, with AUTO_FETCH_TIMEOUT seconds to answer. A fetch that fails or
    times out changes nothing (``skipped_offline``); the time of the attempt is recorded, so
    the next automatic attempt is made an hour later. With ``force`` (`cdlbib update`) both
    rules are ignored, the fetch has FETCH_TIMEOUT seconds, and a failure records nothing.

    After a fetch the time is recorded as the last check. Nothing new: ``up_to_date``. New
    commits, and the library is on the default branch with no commits of its own and no
    changes under cdl.bib or verification/: a backup is taken, the branch is fast-forwarded,
    ``updated``. A fast-forward that git refuses changes nothing, keeps no backup, and counts
    as a failed attempt. ``result.notes`` holds non-fatal remarks.

    New commits, and the library is on the default branch with unsent work (changed or
    untracked files under the two paths, or commits the upstream does not have): nothing is
    changed, no time is recorded, and UpdateNeedsDecision is raised once the lock has been
    released. It carries what changed, the decisions this state takes (``choices``) and a name
    for the state (``seen``). The front end asks and calls update() again with ``decision``
    and ``seen``; the state is then read afresh under the lock, and a decision whose ``seen``
    no longer names it changes nothing (``left_alone``). Without ``seen`` a decision is
    applied to the state that is found. The decisions:

    ``"keep"``     nothing is changed; the time is recorded, so the question is not asked again
                   until the next day's check. (A front end that cannot ask passes this too.)
    ``"send"``     as "keep": the front end then runs the send.
    ``"update"``   a backup is taken; the new version is brought in underneath the user's
                   changes, which are kept as they are (a file both changed is merged). When
                   a change of the user's collides with one of the upstream's, UpdateConflict
                   names the entries and NOTHING is changed: the merge is worked out on
                   copies before the library is touched. Not taken by a library with commits
                   of its own (``left_alone``).
    ``"discard"``  a backup is taken; the library is made equal to the upstream; ``updated``,
                   and the message names the backup and the command that brings the changes
                   back (changed and untracked files, and local commits).
    Changes that were staged are unstaged by "update" (as by a restore). In every other
    state (another branch, no branch, a file of the user's in the way) nothing is changed and
    ``left_alone`` says why and what can be done.

    On a branch a send made (cdlbib/<login>/..., of the logged-in user, in a library whose
    origin is a GitHub repository) the branch's pull request decides, whether or not the
    upstream has anything new. Open, or none: ``left_alone``, with one line. Merged, and the
    branch holds nothing else: a backup, then the library is switched to the default branch,
    fast-forwarded, and the send branch is deleted when git agrees that it is merged (else it
    is kept, and the line says so): ``returned_to_main``. Closed without being merged, or
    changes on the branch that were not in the pull request: UpdateNeedsDecision (its
    ``branch`` is set); "update" and "discard" then return to the default branch
    (``returned_to_main``), with or without the changed files. When GitHub cannot be asked
    (no login, no answer): ``left_alone`` with the reason, and like a failed fetch it is tried
    again an hour later. ``_found`` is for _after_send only.

    ``now`` is the current time (UTC), for callers that fix it; ``progress`` receives one line
    when another command holds the lock and this one waits.

    Only the managed library is ever updated: any other ``ws`` is a CdlbibError. Everything
    runs under the lock of the data folder, so of two commands starting together one fetches
    and the other finds the check done. Every failure is a CdlbibError; one after a backup
    was taken names the backup and the command that restores it."""
    root = Path(ws.root).resolve()
    if root != path().resolve() or not exists():
        raise CdlbibError(f"Only the library cdlbib manages ({path()}) is updated; {ws.root} is not it.")
    if decision is not None and decision not in CHOICES:
        raise CdlbibError(f"{decision!r} is not a decision an update takes ({', '.join(CHOICES)}).")
    if decision is None and not _wanted(force, now) and not _marked()[0]:
        return UpdateResult("not_due")
    try:
        lock = transaction(ws, recovery=True, progress=progress)
        lock.__enter__()
    except OSError as exc:
        raise CdlbibError(f"{home()} cannot be written ({exc.strerror or exc}), so the library was not "
                          "checked for updates.") from exc
    made, asked = [], None
    try:
        return _update(root, force, now, made, decision, seen, _found)
    except UpdateNeedsDecision as exc:
        asked = exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise CdlbibError(f"The update check of {root} failed ({_why(exc)}). " + (
            f"A backup was taken first, in {made[0].path}; `{UNDO} {made[0].stamp}` puts the library back as it was."
            if made else "The library's files were not changed.")) from exc
    finally:
        lock.__exit__(None, None, None)
    # The lock is released: the count for the question is made (it reads files only), and the
    # front end asks. Nothing was changed, and no time was recorded.
    if (BIB_NAME in asked.changed or asked.local_commits) and not asked.rewritten:
        branch, commit = _head(root)
        target = _git(root, "rev-parse", "--verify", "--quiet", f"{_ORIGIN}{_default_branch(root)}^{{commit}}",
                      check=False).stdout.strip()
        # On a send branch with no commits of its own left to send: counted from the branch's commit.
        start = commit if asked.branch and not asked.local_commits else None
        asked.entries_changed = _entry_count(root, commit, target, start) if target else None
    raise asked
