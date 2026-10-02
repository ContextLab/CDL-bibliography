"""The managed library: the copy of the bibliography that cdlbib downloads and keeps for a
user who has named no library of their own. Nothing here prints or prompts."""
import contextlib
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import LibraryUnavailable

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


@contextlib.contextmanager
def _locked(folder):
    """Hold <folder>/lock, so that two commands starting together do not both download."""
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "lock", "a") as handle:
        try:
            import fcntl
        except ImportError:   # no flock on this platform: no lock
            yield
            return
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def download(progress=None):
    """Make the managed library if it is not there, and return its folder.

    The upstream is cloned into <home>/library.partial, which becomes <home>/library by one
    rename, so no other command ever sees a half-made library. Any failure removes the
    partial folder and raises LibraryUnavailable. ``progress`` receives one line, only when
    a download starts.
    """
    if exists():
        return path()
    folder, root, source = home(), path(), upstream()
    partial = folder / "library.partial"

    def unavailable(reason):
        return LibraryUnavailable(f"The bibliography could not be downloaded from {source}: {reason}. "
                                  "If you already have a copy, pass --library PATH or set CDLBIB_LIBRARY.")

    try:
        lock = _locked(folder)
        lock.__enter__()
    except OSError as exc:
        raise unavailable(f"{folder} cannot be written ({exc.strerror or exc})") from exc
    try:
        if exists():          # another command made it while this one waited
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
            done = subprocess.run(["git", "clone", "--quiet", source, str(partial)], capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
            if done.returncode != 0:
                lines = [line.strip() for line in done.stderr.splitlines() if line.strip()]
                raise unavailable((lines[-1] if lines else f"git clone exited with status {done.returncode}").rstrip("."))
            if not (partial / BIB_NAME).is_file():
                raise unavailable(f"it has no {BIB_NAME}")
            os.rename(partial, root)
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
        write_state(State(datetime.datetime.now(datetime.timezone.utc), source))
        return root
    finally:
        lock.__exit__(None, None, None)
