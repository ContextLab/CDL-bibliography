"""The managed library: the copy of the bibliography that cdlbib downloads and keeps for a
user who has named no library of their own. Nothing here prints or prompts."""
import contextlib
import datetime
import filecmp
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
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
# A backup is the folder <home>/backups/<UTC time>/ holding
#   files/        cdl.bib and the whole verification/ folder, exactly as on disk
#   ref.json      the branch, the commit, and what `git status` said about those two paths
#   changes.bundle  the commits that are not on the upstream's default branch, when there are any
#
# What restore() guarantees: afterwards the branch, the commit, and the bytes of every file
# under cdl.bib and verification/ are what they were when the backup was taken, and the same
# paths are reported as changed. What it does not preserve: whether a change was staged
# (changes come back unstaged; a file that was staged as new comes back untracked). ref.json
# keeps the original `git status --porcelain` text, so that information is not lost.
#
# Backup and restore themselves never copy, overwrite or delete a file outside those two
# paths, and never discard a local change to one. `.bibcheck/` is a rebuildable cache and is
# never backed up. The only git commands that change anything are: `git restore --source=<commit>
# --staged --worktree -- cdl.bib verification`, `git switch` (never forced), `git branch <name>
# <commit>` for a branch that no longer exists, `git update-ref <branch> <new> <old>` (which
# fails unless the branch is still at <old>), and `git fetch` from the backup's own bundle
# into a new private ref.

KEPT = ("cdl.bib", "verification")    # the only paths a backup holds and a restore writes
KEEP = 10                             # backups kept; older ones are deleted when one is made
UNDO = "cdlbib update --undo"
_STAMP = "%Y%m%dT%H%M%S.%fZ"
_STAMP_NAME = re.compile(r"\d{8}T\d{6}\.\d{6}Z")


@dataclass
class Backup:
    path: Path                     # <home>/backups/<UTC time>
    taken_at: datetime.datetime    # UTC
    branch: str | None             # None: the library was not on a branch
    commit: str
    changed: list                  # paths under cdl.bib and verification/ that git reported as changed or untracked
    has_bundle: bool               # local commits were saved in changes.bundle

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


def _status(root, *pathspec):
    """(the porcelain text, [(XY, path)]) of `git status` limited to ``pathspec``."""
    raw = _git(root, "status", "--porcelain", "-z", "--untracked-files=all", "--", *pathspec).stdout
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
                      changed=list(ref["changed"]), has_bundle=(folder / "changes.bundle").is_file())
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


def _prune(folder, protect=None):
    """Delete all but the KEEP newest backups: only folders directly inside <home>/backups
    whose names are the timestamps this code writes, and never ``protect``."""
    for name in _backup_names(folder)[:-KEEP]:
        if protect is None or folder / name != protect.path:
            shutil.rmtree(folder / name)


def _discard(backup):
    """Delete a backup this call has just made and not used (a timestamp folder in <home>/backups)."""
    folder = backups_folder()
    if backup.path.parent == folder and backup.path.name in _backup_names(folder):
        shutil.rmtree(backup.path)


def _backup(root, protect=None):
    folder = backups_folder()
    branch, commit = _head(root)
    raw, entries = _status(root, *KEPT)
    default = _git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False).stdout.strip()
    if default and _git(root, "rev-parse", "--verify", "--quiet", default + "^{commit}", check=False).returncode != 0:
        default = ""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        while True:
            taken = datetime.datetime.now(datetime.timezone.utc)
            final, partial = folder / taken.strftime(_STAMP), folder / (taken.strftime(_STAMP) + ".partial")
            if final.exists():
                continue
            try:
                partial.mkdir()
            except FileExistsError:
                continue
            break
    except OSError as exc:
        raise CdlbibError(f"No backup could be made in {folder} ({exc.strerror or exc}); nothing was changed.") from exc
    try:
        files, folders = _tree(root)
        (partial / "files").mkdir()
        for rel in folders.values():
            (partial / "files" / rel).mkdir(parents=True, exist_ok=True)
        for rel in files.values():
            _copy(root / rel, partial / "files" / rel)
        # Local commits: everything on HEAD that the upstream's default branch does not have
        # (the whole history when that branch is not known).
        span = f"{default}..HEAD" if default else "HEAD"
        bundled = int(_git(root, "rev-list", "--count", span).stdout) > 0
        if bundled:
            _git(root, "bundle", "create", "--quiet", str(partial / "changes.bundle"), span)
        ref = {"taken_at": taken.isoformat(), "branch": branch, "commit": commit,
               "changed": sorted({name for _, name in entries}),
               "untracked": sorted(name for state, name in entries if state == "??"),
               "status": raw, "upstream_branch": default or None, "bundle_ref": "HEAD" if bundled else None}
        (partial / "ref.json").write_text(json.dumps(ref, indent=1), encoding="utf-8")
        os.rename(partial, final)
    except BaseException as exc:
        shutil.rmtree(partial, ignore_errors=True)      # the folder this call made, and only that
        if isinstance(exc, OSError):
            raise CdlbibError(f"No backup could be made in {folder} ({exc.strerror or exc}); nothing was changed.") from exc
        raise
    _prune(folder, protect)
    made = _read(final)
    if made is None:
        raise CdlbibError(f"The backup just written to {final} cannot be read back; nothing was changed.")
    return made


def backup(ws, protect=None):
    """Save the managed library as it is on disk and return the Backup: cdl.bib and all of
    verification/ (uncommitted, untracked and ignored files included), the branch and commit,
    what git reported as changed, and a bundle of the commits the upstream does not have.
    Nothing in the library is changed. The KEEP newest backups are kept; ``protect`` (a
    Backup) is never deleted."""
    root = _managed_root(ws)
    with _locked(home()):
        return _backup(root, protect)


def _pathspecs(root, commit):
    """Those of cdl.bib and verification that git knows, in the index or in ``commit``
    (git refuses a path it has never heard of)."""
    return [top for top in KEPT
            if _git(root, "ls-files", "-z", "--", top).stdout
            or _git(root, "ls-tree", "-r", "-z", "--name-only", commit, "--", top).stdout]


def _git_restore(root, commit):
    """Make the index and the tracked files under the two paths match ``commit``."""
    specs = _pathspecs(root, commit)
    if specs:
        _git(root, "restore", f"--source={commit}", "--staged", "--worktree", "--", *specs)


def _tracked(root):
    return {_same_name(name) for name in _listed(_git(root, "ls-files", "-z", "--", *KEPT).stdout)}


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


def _check_saved(root, into):
    """Refuse unless ``into`` holds every file now on disk under the two paths, byte for
    byte: only then may those files be replaced."""
    files, _ = _tree(root)
    saved, _ = _tree(into.path / "files")
    differ = sorted(rel for key, rel in files.items()
                    if key not in saved or not _same(root / rel, into.path / "files" / saved[key]))
    differ += sorted(rel for key, rel in saved.items() if key not in files)
    if differ:
        raise CdlbibError(f"The library changed after its backup was taken ({', '.join(differ[:5])}"
                          f"{', ...' if len(differ) > 5 else ''}), so nothing was restored. Nothing was changed.")


def _clear(root, into):
    """Step b: leave under the two paths only the files of the current commit, unmodified.
    Changes to tracked files are in ``into`` already (checked by the caller); files git does
    not track are moved into it."""
    _git_restore(root, "HEAD")
    tracked = _tracked(root)
    for key, rel in _tree(root)[0].items():
        if key not in tracked:
            _set_aside(root, rel, into)


def _put(root, backup, into):
    """Step e: with the library on the backup's commit, make the files under the two paths
    exactly the backup's. A file that is not in the backup is removed when it is a tracked
    file of that commit (it was deleted when the backup was taken, and the commit holds
    it); any other is moved into ``into``."""
    _git_restore(root, backup.commit)
    saved, saved_folders = _tree(backup.path / "files")
    tracked = _tracked(root)
    files, folders = _tree(root)
    for key, rel in files.items():
        if key in saved:
            continue
        if key in tracked:
            os.unlink(root / rel)
        else:
            _set_aside(root, rel, into)
    for key in sorted(folders, key=len, reverse=True):           # deepest first; only empty folders go
        if key not in saved_folders:
            with contextlib.suppress(OSError):
                os.rmdir(root / folders[key])
    for rel in saved_folders.values():
        (root / rel).mkdir(parents=True, exist_ok=True)
    for rel in saved.values():
        _copy(backup.path / "files" / rel, root / rel)


def _has_commit(root, commit):
    return _git(root, "cat-file", "-e", commit + "^{commit}", check=False).returncode == 0


def _restore(root, backup, into):
    folder = backups_folder()
    if backup is None or _read(Path(backup.path)) is None or Path(backup.path).parent != folder:
        raise CdlbibError(f"No backup has been made yet of {root}, so there is nothing to undo." if backup is None
                          else f"{backup.path} is not a backup in {folder}; nothing was changed.")
    own = into is None
    if own:
        into = _backup(root, protect=backup)
    elif _read(Path(into.path)) is None or Path(into.path).parent != folder or into.path == backup.path:
        raise CdlbibError(f"{into.path} is not a backup of the current state in {folder}; nothing was changed.")
    what = f"The backup of {backup.when}"
    target = backup.commit
    try:
        # a. Everything that can be checked before anything is changed.
        if not _has_commit(root, target):
            bundle = backup.path / "changes.bundle"
            if bundle.is_file() and _git(root, "bundle", "verify", "--quiet", str(bundle), check=False).returncode == 0:
                _git(root, "fetch", "--quiet", "--no-tags", str(bundle),
                     f"HEAD:refs/cdlbib/backups/{backup.path.name}", check=False)
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
        if head != target:
            mine = {_same_name(name) for _, name in _status(root, ".", *(f":(exclude){top}" for top in KEPT))[1]}
            differs = _listed(_git(root, "diff", "--name-only", "--no-renames", "-z", head, target).stdout)
            clash = sorted(name for name in differs if _same_name(name) in mine)
            if clash:
                raise CdlbibError(f"{what} cannot be restored: it would overwrite your changes to {', '.join(clash)}, "
                                  "which cdlbib does not back up. Commit, move or remove those changes and try again. "
                                  "Nothing was changed.")
        if moved and moved != target and current != backup.branch:
            # The branch would be moved while another is checked out: only if its commit stays reachable.
            kept = any(_git(root, "merge-base", "--is-ancestor", moved, other, check=False).returncode == 0
                       for other in (head, target))
            if not kept and not _git(root, "branch", "--remotes", "--contains", moved, check=False).stdout.strip():
                raise CdlbibError(f"{what} cannot be restored: branch {backup.branch} has commits ({moved[:8]}) that are "
                                  "in no backup and not on the upstream. Switch to that branch and try again. "
                                  "Nothing was changed.")
        _check_saved(root, into)
    except CdlbibError:
        if own:      # nothing was changed: the copy just taken is not kept, so the newest backup stays the newest
            _discard(into)
        raise
    saved = f"Your files as they were are saved in {into.path}; `{UNDO}` puts them back."

    # b, c. Set the current files aside (they are in `into`) and move to the recorded commit.
    try:
        _clear(root, into)
        if not in_place:
            _git(root, "switch", "--quiet", "--detach", target)
    except (CdlbibError, OSError) as exc:
        if _head(root) != (current, head):     # git moved although it reported a failure
            raise CdlbibError(f"{what} was only partly restored: {exc}. {saved}") from exc
        try:
            _put(root, into, into)
        except (CdlbibError, OSError) as second:
            raise CdlbibError(f"{what} could not be restored ({exc}), and the library could not be put back "
                              f"({second}). {saved}") from exc
        raise CdlbibError(f"{what} could not be restored: {exc}. The library is as it was "
                          "(changes that were staged are now unstaged).") from exc

    # d, e. Put the branch on that commit, then the saved files.
    try:
        if not in_place and backup.branch:
            if moved is None:
                _git(root, "branch", "--quiet", backup.branch, target)
            elif moved != target:
                swap = _git(root, "update-ref", "-m", "cdlbib undo", f"refs/heads/{backup.branch}", target, moved,
                            check=False)
                if swap.returncode != 0:
                    raise CdlbibError(f"branch {backup.branch} is no longer at {moved[:8]}, where it was a moment "
                                      "ago, so it was not moved")
            _git(root, "switch", "--quiet", backup.branch)
        _put(root, backup, into)
    except (CdlbibError, OSError) as exc:
        raise CdlbibError(f"{what} was only partly restored: {exc}. {saved}") from exc


def restore(backup, ws, into=None):
    """Put the managed library back as it was when ``backup`` was taken: the branch (made
    again if it no longer exists), the commit (read from the backup's bundle if the library
    no longer has it), and the bytes of every file under cdl.bib and verification/. Whether
    a change was staged is not preserved: changes come back unstaged.

    ``into`` is a backup of the current state, taken just before; without one, restore takes
    it itself (and removes it again when it refuses before changing anything). A file under the two paths that is not in ``backup`` is moved into ``into``,
    never deleted. Clean tracked files elsewhere follow the commit, as git moves them; a
    local change elsewhere that this would overwrite is a refusal, before anything changes.
    Raises CdlbibError; when the user's files are then only in ``into``, the message names it."""
    root = _managed_root(ws)
    with _locked(home()):
        _restore(root, backup, into)
