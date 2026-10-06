"""Suite-wide guard: no test may depend on the live cdl.bib.

Approved research batches keep changing cdl.bib, and four times (Sept 2026) a test that
read it broke on a legitimate correction. Every test sees the library as frozen before the
research waves were applied; a test that needs other library content monkeypatches
correction_proposals.LIBRARY_BIB itself (that still wins, being applied later).
"""
import atexit
import os
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
FROZEN_LIBRARY = ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib"

# Tests that fetch live evidence (validate.py) write the bodies into a directory of this run,
# never into the clone's .bibcheck/research-pilot/. That directory is evidence the route
# validator reads during `crossref restore`: on 2026-09-30 a test run left 16 freshly fetched
# bodies there, three of them dynamic pages whose sha256 differed from the approvals', and the
# next restore rejected the whole snapshot. Set before any test module imports validate.py
# or research_route (both read BIBCHECK_RESEARCH_BODIES at import); subprocesses inherit it.
_BODIES = tempfile.mkdtemp(prefix="bibcheck-test-research-bodies-")
atexit.register(shutil.rmtree, _BODIES, True)
os.environ["BIBCHECK_RESEARCH_BODIES"] = _BODIES

# The managed library (cdlbib.library) is downloaded on first use into the per-user data
# folder. No test may reach GitHub for it or write into the real data folder: for the whole
# run the data folder is a directory of this run and the upstream is a small local bare
# repository built here. Set in os.environ at import, so subprocesses inherit both.
ZOLL90 = ("@article{Zoll90,\n\tAuthor = {U Zoller},\n\tDoi = {10.1002/tea.3660271011},\n"
          "\tJournal = {Journal of Research in Science Teaching},\n\tNumber = {10},\n\tPages = {1053--1065},\n"
          "\tTitle = {Students' misunderstandings and misconceptions in college freshman chemistry (general and "
          "organic)},\n\tVolume = {27},\n\tYear = {1990}}")  # the frozen entry of tests/test_machinery_2026_09_25.py


def _git(*args, cwd):
    import subprocess
    env = dict(os.environ, GIT_AUTHOR_NAME="cdlbib tests", GIT_AUTHOR_EMAIL="tests@cdlbib.invalid",
               GIT_COMMITTER_NAME="cdlbib tests", GIT_COMMITTER_EMAIL="tests@cdlbib.invalid",
               GIT_TERMINAL_PROMPT="0")
    if sys.platform == "darwin":
        env.setdefault("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)


def build_upstream(folder):
    """A real, tiny upstream at <folder>/upstream.git: one commit on master holding a valid
    library (cdl.bib with one entry, and verification/). Returns the bare repository's path."""
    folder = Path(folder)
    bare, work = folder / "upstream.git", folder / "upstream-work"
    bare.mkdir(parents=True)
    _git("init", "--quiet", "--bare", cwd=bare)
    _git("symbolic-ref", "HEAD", "refs/heads/master", cwd=bare)
    (work / "verification").mkdir(parents=True)
    _git("init", "--quiet", cwd=work)
    _git("symbolic-ref", "HEAD", "refs/heads/master", cwd=work)
    (work / "cdl.bib").write_text(ZOLL90 + "\n", encoding="utf-8")
    (work / "verification" / ".gitkeep").write_text("", encoding="utf-8")
    _git("add", "cdl.bib", "verification/.gitkeep", cwd=work)
    _git("commit", "--quiet", "-m", "A one-entry library for the tests", cwd=work)
    _git("push", "--quiet", str(bare), "master", cwd=work)
    return bare


def _real_data_folder():
    from cdlbib import library
    return library.home({k: v for k, v in os.environ.items() if k != "CDLBIB_HOME"})


_MANAGED = tempfile.mkdtemp(prefix="cdlbib-test-managed-")
atexit.register(shutil.rmtree, _MANAGED, True)
os.environ["CDLBIB_HOME"] = str(Path(_MANAGED) / "home")
os.environ["CDLBIB_UPSTREAM"] = str(build_upstream(_MANAGED))
_REAL_DATA_FOLDER = _real_data_folder()
_REAL_DATA_FOLDER_EXISTED = _REAL_DATA_FOLDER.exists()
_HASHED = ("state.json", "lock", "update-in-progress.json", "completion-undo", "tex-link.json")


def data_folder_state(folder):
    """What a run must leave alone in a data folder that exists: {relative name: what it is}.

    Every file, folder and link under it by kind, size and modification time (a link by its
    target), except inside the clone's .git, where only HEAD (its bytes), packed-refs and
    refs/ are recorded: git rewrites its index and objects when anything merely looks at the
    clone. The small files cdlbib steers by (state.json, the lock, the interrupted-update
    marker, the undo checkpoint, the TeX link record) and the library's cdl.bib are recorded
    by SHA-256 as well. Nothing is read beyond those; a whole clone takes well under a second."""
    import hashlib
    folder = Path(folder)
    state = {}

    def digest(path):
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            return f"unreadable ({type(exc).__name__})"

    for base, folders, files in os.walk(folder):
        relative = Path(base).relative_to(folder)
        if relative.parts[:2] == ("library", ".git"):
            inside = relative.parts[2:]
            if not inside:
                folders[:] = [name for name in folders if name == "refs"]
                files = [name for name in files if name in ("HEAD", "packed-refs")]
            elif inside[0] != "refs":
                folders[:], files = [], []
        for name in sorted(folders + files):
            path = Path(base) / name
            key = str(relative / name)
            try:
                found = path.lstat()
            except OSError as exc:
                state[key] = f"unreadable ({type(exc).__name__})"
                continue
            if path.is_symlink():
                state[key] = ("link", os.readlink(path))
            elif path.is_dir():
                state[key] = ("folder",)
            else:
                state[key] = ("file", found.st_size, found.st_mtime_ns)
                if key in _HASHED or key in ("library/cdl.bib", "library/.git/HEAD"):
                    state[key] += (digest(path),)
    return state


def data_folder_changes(before, after):
    """The names that differ between two data_folder_state results, each with how."""
    return [f"{name}: {'removed' if name not in after else 'added' if name not in before else 'changed'}"
            for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)]


_REAL_DATA_FOLDER_STATE = data_folder_state(_REAL_DATA_FOLDER) if _REAL_DATA_FOLDER_EXISTED else None


def real_data_folder_problem():
    """Why this run failed to leave the real data folder alone; None when it did. A folder
    that was not there must still not be there; one that was must be exactly as it was."""
    if not _REAL_DATA_FOLDER_EXISTED:
        return f"this run created {_REAL_DATA_FOLDER}" if _REAL_DATA_FOLDER.exists() else None
    if not _REAL_DATA_FOLDER.exists():
        return f"this run removed {_REAL_DATA_FOLDER}"
    changed = data_folder_changes(_REAL_DATA_FOLDER_STATE, data_folder_state(_REAL_DATA_FOLDER))
    if changed:
        return (f"{_REAL_DATA_FOLDER} changed during this run (" + "; ".join(changed[:10])
                + (f"; and {len(changed) - 10} more" if len(changed) > 10 else "")
                + "). If nothing but the tests used cdlbib meanwhile, a test wrote there")
    return None


def no_real_library_touched():
    """The real data folder is as this run found it: absent still, or unchanged."""
    problem = real_data_folder_problem()
    assert problem is None, f"{problem}: the managed library must only be written under CDLBIB_HOME"


def pytest_sessionfinish(session, exitstatus):
    problem = real_data_folder_problem()
    if problem:
        sys.stderr.write(f"\nERROR: {problem}; tests must never write there.\n")
        session.exitstatus = 1


@pytest.fixture(autouse=True)
def _frozen_library(monkeypatch, tmp_path):
    # The committed revocation ledger is live data too: every test starts with an
    # empty ledger of its own (tests/test_revocation.py writes to it).
    from cdlbib import verification
    monkeypatch.setattr(verification, "REVOCATION_LEDGER", tmp_path / "revocations.jsonl")
    try:
        from cdlbib import correction_proposals as cp
    except Exception:  # a module that fails to import is reported by its own tests
        return
    monkeypatch.setattr(cp, "LIBRARY_BIB", FROZEN_LIBRARY)


def plain_output(result):
    """Compare visible CLI wording even when CI forces ANSI terminal styling."""
    import re
    styling = re.compile(r"\x1b\[[0-9;]*m")
    result.stdout = styling.sub("", result.stdout)
    result.stderr = styling.sub("", result.stderr)
    return result


def keychain_problem():
    """Why no usable keychain exists under the current environment, or None when there is one.

    Non-interactive and read-only: it never writes to a keychain, so it cannot open a macOS
    dialog. On macOS `security default-keychain` exits 1 ("A default keychain could not be
    found") when HOME has no login keychain, as under a substituted HOME; elsewhere the
    keyring backend must be a real one (not the fail or null backend).
    """
    if sys.platform == "darwin":
        import subprocess
        try:
            done = subprocess.run(["security", "default-keychain"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"the security command did not answer ({type(exc).__name__})"
        path = done.stdout.strip().strip('"')
        if done.returncode != 0 or not path or not Path(path).exists():
            return "no default keychain exists under HOME=" + os.environ.get("HOME", "")
        return None
    import keyring
    backend = keyring.get_keyring()
    if getattr(backend, "priority", 0) <= 0:
        return f"no usable keyring backend ({type(backend).__name__})"
    return None


@pytest.fixture
def usable_keychain():
    """Skip, before any keychain write, when this environment has no usable keychain."""
    problem = keychain_problem()
    if problem:
        pytest.skip("no system keychain is available: " + problem)


# The tests that call a live model service run only when asked for: the service's answer time
# varies from under a minute to no answer within the adapter's limit, which is no finding
# about this code. A recorded real answer is replayed by tests/test_intake_model.py always.
live_model = pytest.mark.skipif(os.environ.get("CDLBIB_TEST_LIVE_MODEL") != "1",
                                reason="calls the live Dartmouth Chat service (minutes; it can time out); set CDLBIB_TEST_LIVE_MODEL=1 to run")
