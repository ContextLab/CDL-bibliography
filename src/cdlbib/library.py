"""The managed library: the copy of the bibliography that cdlbib downloads and keeps for a
user who has named no library of their own. Nothing here prints or prompts."""
import contextlib
import datetime
import filecmp
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CdlbibError, LibraryUnavailable

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
    last_check: datetime.datetime | None   # when the upstream was last consulted (UTC)
    upstream: str


def read_state():
    """state.json; a missing, empty or unreadable file is 'never checked'."""
    try:
        data = json.loads((home() / "state.json").read_text(encoding="utf-8"))
        when = datetime.datetime.fromisoformat(data["last_check"]) if data.get("last_check") else None
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        return State(when, str(data["upstream"]))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return State(None, upstream())


def write_state(state):
    folder = home()
    folder.mkdir(parents=True, exist_ok=True)
    data = {"last_check": state.last_check.isoformat() if state.last_check else None, "upstream": state.upstream}
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
                               text=True, stdin=subprocess.DEVNULL)
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
def _locked(folder, progress=None):
    """Hold <folder>/lock, so that two commands starting together do not both download.
    ``progress`` receives one line when the lock is held by another command and this one waits."""
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
                progress("waiting for another cdlbib to finish downloading the bibliography ...")
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _clone(source, partial, timeout):
    """git clone into ``partial``; (exit status, stderr). On a timeout, or when interrupted,
    git and its helpers are stopped first. The clone runs as a process group of its own so
    that a stalled transport helper can be stopped with it."""
    clone = subprocess.Popen(["git", "clone", "--quiet", "--", source, str(partial)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                             env=dict(os.environ, GIT_TERMINAL_PROMPT="0"), start_new_session=True)
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
#                   the working tree, and the folders that were there
#   changes.bundle  the commits that are on no branch of the upstream, when there are any
# and, in the library itself, the private ref refs/cdlbib/backups/<UTC time> on the recorded
# commit, so that git never discards it while the backup exists.
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
                              env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
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
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".cdlbib-", suffix=".tmp")
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


def _read(folder):
    """The Backup in ``folder``, or None when it is not a complete backup."""
    try:
        ref = json.loads((folder / "ref.json").read_text(encoding="utf-8"))
        taken = datetime.datetime.strptime(folder.name, _STAMP).replace(tzinfo=datetime.timezone.utc)
        return Backup(path=folder, taken_at=taken, branch=ref["branch"], commit=str(ref["commit"]),
                      changed=list(ref["changed"]), has_bundle=(folder / "changes.bundle").is_file(),
                      deleted=list(ref["deleted"]), folders=list(ref["folders"]))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _backup_names(folder):
    """The names in ``folder`` that are backups this code wrote: real folders named by time."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(name for name in names if _STAMP_NAME.fullmatch(name)
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
        for pin in (_PINS + name, _PINS + name + "-moved"):
            _git(root, "update-ref", "-d", pin, check=False)


def _prune(folder, root):
    """Delete all but the KEEP newest backups. Called only after an operation has succeeded."""
    for name in _backup_names(folder)[:-KEEP]:
        _drop(folder, name, root)


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
        started = datetime.datetime.strptime(named.group(1), _STAMP).replace(tzinfo=datetime.timezone.utc)
        if now - started > _STALE:
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
        (partial / "ref.json").write_text(json.dumps(ref, indent=1), encoding="utf-8")
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
    made = _read(final)
    if made is None:
        raise CdlbibError(f"The backup just written to {final} cannot be read back; nothing was changed.")
    return made


def backup(ws):
    """Save the state of the managed library and return the Backup: the files under cdl.bib
    and verification/ that differ from the commit it is on (modified, untracked and ignored
    files), the tracked files that are deleted, the branch and commit, what git reported as
    changed, a private ref that keeps the commit, and a bundle of the commits the upstream
    does not have. No file of the library is changed. Afterwards the KEEP newest backups
    are kept."""
    root = _managed_root(ws)
    with _locked(home()):
        made = _backup(root)
        _prune(backups_folder(), root)
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
    for rel in backup.folders:
        (root / rel).mkdir(parents=True, exist_ok=True)
    for rel in saved.values():
        _copy(backup.path / "files" / rel, root / rel)
    wrong = _describes(root, backup)
    if wrong:
        raise CdlbibError(f"these files are not as the backup recorded them: {', '.join(wrong[:5])}"
                          + (", ..." if len(wrong) > 5 else ""))


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


def _restore(root, backup, into):
    """restore(), with the lock held. Returns the backup of the state before it."""
    folder = backups_folder()
    if backup is None or _read(Path(backup.path)) is None or Path(backup.path).parent != folder:
        raise CdlbibError(f"No backup has been made yet of {root}, so there is nothing to undo." if backup is None
                          else f"{backup.path} is not a backup in {folder}; nothing was changed.")
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
        current, head = _head(root)
        in_place = current == backup.branch and head == target
        moved = None            # where the backup's branch is now, when it exists
        if backup.branch:
            moved = _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{backup.branch}^{{commit}}",
                         check=False).stdout.strip() or None
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
    except CdlbibError:
        if own:      # nothing was changed: the copy just taken is not kept, so the newest backup stays the newest
            _drop(folder, into.stamp, root)
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
        if not in_place and backup.branch:
            if moved is None:
                _git(root, "branch", "--quiet", backup.branch, target)
            elif moved != target:
                if moved != head:
                    # The branch leaves a commit that is not the one `into` recorded: keep it
                    # under a private ref of `into`, so that no commit is ever lost by an undo.
                    keep = _PINS + into.stamp + "-moved"
                    _git(root, "update-ref", "-m", "cdlbib undo", keep, moved, "", check=False)
                    if _git(root, "rev-parse", "--verify", "--quiet", keep, check=False).stdout.strip() != moved:
                        raise CdlbibError(f"commit {moved[:8]} of branch {backup.branch} could not be kept")
                swap = _git(root, "update-ref", "-m", "cdlbib undo", f"refs/heads/{backup.branch}", target, moved,
                            check=False)
                if swap.returncode != 0:
                    raise CdlbibError(f"branch {backup.branch} is no longer at {moved[:8]}, where it was a moment "
                                      "ago, so it was not moved")
            _git(root, "switch", "--quiet", "--no-overwrite-ignore", backup.branch)
        _put(root, backup, into)
        if _head(root) != (backup.branch, target):
            raise CdlbibError("the library is not on the recorded branch and commit")
    except (CdlbibError, OSError) as exc:
        raise CdlbibError(f"{what} was only partly restored: {exc}. {saved}") from exc
    _prune(folder, root)
    return into


def restore(backup, ws, into=None):
    """Put the managed library back as it was when ``backup`` was taken: the branch (made
    again if it no longer exists), the commit (read from the backup's bundle if the library
    no longer has it), and the bytes of every file under cdl.bib and verification/. Whether
    a change was staged is not preserved: changes come back unstaged.

    ``into`` is a backup of the current state, taken just before; without one, restore takes
    it itself, and removes it again when nothing was changed (a refusal, or a failure after
    which the library was put back and checked). A file under the two paths that is not in
    ``backup`` is moved into ``into``, never deleted. Clean tracked files elsewhere follow the
    commit, as git moves them; any file elsewhere that this would overwrite (changed,
    untracked or ignored) is a refusal, before anything changes. Old backups are pruned only
    after a restore that succeeded. Raises CdlbibError; when the user's files are then only
    in ``into``, the message names it and the command that restores it. Returns ``into``."""
    root = _managed_root(ws)
    with _locked(home()):
        return _restore(root, backup, into)


def undo(ws, stamp=None):
    """Restore the newest backup, or the one named ``stamp`` (Backup.stamp). The list of
    backups is read with the lock held. Returns (the backup restored, the backup of the
    state before it)."""
    root = _managed_root(ws)
    with _locked(home()):
        saved = backups()
        if stamp is None:
            if not saved:
                raise CdlbibError(f"No backup has been made yet of {root}, so there is nothing to undo.")
            chosen = saved[0]
        else:
            named = [one for one in saved if one.stamp == stamp.strip()]
            if not named:
                raise CdlbibError(f"There is no backup {stamp.strip()} of {root}; `cdlbib update --list` shows "
                                  "the backups there are. Nothing was changed.")
            chosen = named[0]
        return chosen, _restore(root, chosen, None)
