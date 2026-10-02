"""The managed library: where it lives, downloading it on first use, and the lookup that
falls back to it. Real git against local bare repositories; nothing here reaches GitHub."""
import datetime
import fcntl
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import conftest
from cdlbib import api, library, workspace
from cdlbib.errors import CdlbibError, LibraryUnavailable, WorkspaceNotFound
from cdlbib.workspace import Origin, Workspace

_SIBLING = Path(sys.executable).parent / "cdlbib"
CDLBIB = str(_SIBLING) if _SIBLING.exists() else shutil.which("cdlbib")


@pytest.fixture
def managed(tmp_path, monkeypatch):
    """A data folder (spaces and non-ASCII in its path) and an upstream of this test alone."""
    home = tmp_path / "Données de l'app – cdlbib"
    upstream = conftest.build_upstream(tmp_path / "up")
    monkeypatch.setenv("CDLBIB_HOME", str(home))
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(upstream))
    monkeypatch.delenv("CDLBIB_LIBRARY", raising=False)
    if sys.platform == "darwin":
        monkeypatch.setenv("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")
    workspace.select_library(None)
    yield home, upstream
    workspace.select_library(None)


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def own_library(folder):
    (folder / "verification").mkdir(parents=True)
    (folder / "cdl.bib").write_text(conftest.ZOLL90 + "\n", encoding="utf-8")
    return folder


def cdlbib(*args, cwd, **env):
    return subprocess.run([CDLBIB, *args], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, **env))


# --- the suite's own isolation ---------------------------------------------------------------

def test_the_suite_runs_against_a_local_upstream_and_a_temporary_data_folder():
    from test_machinery_2026_09_25 import ZOLL90
    assert conftest.ZOLL90 == ZOLL90
    home, upstream = Path(os.environ["CDLBIB_HOME"]), os.environ["CDLBIB_UPSTREAM"]
    assert Path(upstream).is_dir() and "://" not in upstream and "github" not in upstream
    assert Path(conftest._MANAGED) in home.parents and library.home() == home
    assert home != conftest._REAL_DATA_FOLDER
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=upstream) == "master"
    assert git("ls-tree", "-r", "--name-only", "master", cwd=upstream).split() == ["cdl.bib", "verification/.gitkeep"]
    conftest.no_real_library_touched()


# --- where it lives --------------------------------------------------------------------------

def test_home_per_platform():
    assert library.home({"HOME": "/Users/x"}, platform="darwin") == Path("/Users/x/Library/Application Support/cdlbib")
    assert library.home({"HOME": "/home/x"}, platform="linux") == Path("/home/x/.local/share/cdlbib")
    assert library.home({"HOME": "/home/x", "XDG_DATA_HOME": "/data"}, platform="linux") == Path("/data/cdlbib")
    assert library.home({"HOME": "/home/x", "XDG_DATA_HOME": ""}, platform="linux") == Path("/home/x/.local/share/cdlbib")


def test_cdlbib_home_replaces_the_data_folder(tmp_path):
    chosen = tmp_path / "Mes données – ü"
    for platform in ("darwin", "linux"):
        assert library.home({"HOME": "/Users/x", "CDLBIB_HOME": str(chosen)}, platform=platform) == chosen
    assert library.path({"CDLBIB_HOME": str(chosen)}) == chosen / "library"
    assert library.home({"HOME": "/Users/x", "CDLBIB_HOME": ""}, platform="darwin").name == "cdlbib"


def test_upstream_default_and_override():
    assert library.upstream({}) == "https://github.com/ContextLab/CDL-bibliography.git"
    assert library.upstream({"CDLBIB_UPSTREAM": "/somewhere/up.git"}) == "/somewhere/up.git"


# --- state.json ------------------------------------------------------------------------------

def test_read_state_of_a_missing_empty_or_garbage_file(managed):
    home, upstream = managed
    nothing = library.State(None, str(upstream))
    assert library.read_state() == nothing
    home.mkdir()
    for text in ("", "not json {", "[1, 2]", '{"last_check": "yesterday-ish"}', '{"last_check": 5}'):
        (home / "state.json").write_text(text, encoding="utf-8")
        assert library.read_state() == nothing, text


def test_write_state_round_trip(managed):
    home, _ = managed
    when = datetime.datetime(2026, 10, 2, 15, 30, 12, tzinfo=datetime.timezone.utc)
    library.write_state(library.State(when, "https://example.org/x.git"))   # creates the data folder
    assert library.read_state() == library.State(when, "https://example.org/x.git")
    assert sorted(p.name for p in home.iterdir()) == ["state.json"]          # no temporary file is left


# --- download --------------------------------------------------------------------------------

def test_download_makes_a_clone_of_the_upstream(managed):
    home, upstream = managed
    assert not library.exists()
    said = []
    before = datetime.datetime.now(datetime.timezone.utc)
    root = library.download(progress=said.append)
    assert root == home / "library" == library.path() and library.exists()
    assert said == [f"downloading the bibliography to {root} ..."]
    assert (root / "cdl.bib").read_text(encoding="utf-8") == conftest.ZOLL90 + "\n"
    assert git("remote", "get-url", "origin", cwd=root) == str(upstream)
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=root) == "master"
    assert git("rev-parse", "HEAD", cwd=root) == git("rev-parse", "master", cwd=upstream)
    assert not (home / "library.partial").exists()
    state = library.read_state()
    assert state.upstream == str(upstream) and before <= state.last_check <= datetime.datetime.now(datetime.timezone.utc)


def test_a_second_download_is_a_no_op(managed):
    home, upstream = managed
    root = library.download()
    (root / "cdl.bib").write_text("% my edit\n", encoding="utf-8")
    stamp = (home / "state.json").read_bytes()
    shutil.rmtree(upstream)                       # contacting the upstream now would fail
    said = []
    assert library.download(progress=said.append) == root and said == []
    assert (root / "cdl.bib").read_text(encoding="utf-8") == "% my edit\n"
    assert (home / "state.json").read_bytes() == stamp


def test_a_failing_upstream_raises_and_leaves_nothing(managed, monkeypatch):
    home, _ = managed
    missing = home.parent / "no such upstream.git"
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(missing))
    with pytest.raises(LibraryUnavailable) as err:
        library.download()
    assert isinstance(err.value, CdlbibError)
    message = str(err.value)
    assert "could not be downloaded" in message and str(missing) in message and "--library" in message
    assert not (home / "library").exists() and not (home / "library.partial").exists()
    assert not (home / "state.json").exists() and not library.exists()


def test_an_upstream_without_a_bibliography_is_refused_and_removed(managed, tmp_path, monkeypatch):
    home, _ = managed
    bare = tmp_path / "other.git"
    work = tmp_path / "other-work"
    for folder in (bare, work):
        folder.mkdir()
    conftest._git("init", "--quiet", "--bare", cwd=bare)
    conftest._git("symbolic-ref", "HEAD", "refs/heads/master", cwd=bare)
    conftest._git("init", "--quiet", cwd=work)
    conftest._git("symbolic-ref", "HEAD", "refs/heads/master", cwd=work)
    (work / "README").write_text("not a library\n", encoding="utf-8")
    conftest._git("add", "README", cwd=work)
    conftest._git("commit", "--quiet", "-m", "no bibliography here", cwd=work)
    conftest._git("push", "--quiet", str(bare), "master", cwd=work)
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(bare))
    with pytest.raises(LibraryUnavailable, match="cdl.bib"):
        library.download()
    assert not (home / "library").exists() and not (home / "library.partial").exists()


def test_git_missing_is_said_plainly(managed, monkeypatch, tmp_path):
    home, _ = managed
    empty = tmp_path / "no programs"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(LibraryUnavailable, match="git is required"):
        library.download()
    assert not (home / "library").exists() and not (home / "library.partial").exists()


def test_an_interrupted_download_is_not_a_library_and_is_replaced(managed):
    home, upstream = managed
    partial = home / "library.partial"
    (partial / ".git").mkdir(parents=True)                      # what a killed clone leaves behind
    (partial / "cdl.bib").write_text("half", encoding="utf-8")
    (partial / "leftover").write_text("x", encoding="utf-8")
    assert not library.exists() and not (home / "library").exists()
    root = library.download()
    assert library.exists() and not partial.exists() and not (root / "leftover").exists()
    assert (root / "cdl.bib").read_text(encoding="utf-8") == conftest.ZOLL90 + "\n"


def test_exists_needs_a_clone_with_a_bibliography_and_no_incomplete_marker(managed):
    home, _ = managed
    root = home / "library"
    root.mkdir(parents=True)
    assert not library.exists()
    (root / "cdl.bib").write_text("", encoding="utf-8")
    assert not library.exists()                                  # not a git clone
    (root / ".git").mkdir()
    assert library.exists()
    (root / ".cdlbib-incomplete").write_text("", encoding="utf-8")
    assert not library.exists()


def test_a_folder_in_the_way_is_never_deleted(managed):
    home, _ = managed
    root = home / "library"
    root.mkdir(parents=True)
    (root / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(LibraryUnavailable, match="not a complete copy"):
        library.download()
    assert (root / "notes.txt").read_text(encoding="utf-8") == "mine" and not (home / "library.partial").exists()


WAITER = "import sys; from cdlbib import library; print(library.download(progress=lambda line: print(line, file=sys.stderr)))"
RESOLVER = ("import sys; from cdlbib import workspace; "
            "print(workspace.resolve(managed=True, progress=lambda line: print(line, file=sys.stderr)).root)")


def test_the_lock_makes_a_second_download_wait(managed):
    """While the lock file is held (as a download in progress holds it), another process's
    download does not start cloning; once released it finds or makes the library."""
    home, _ = managed
    home.mkdir()
    with open(home / "lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        other = subprocess.Popen([sys.executable, "-c", WAITER], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(3)
        waiting = other.poll() is None
        untouched = not (home / "library").exists() and not (home / "library.partial").exists()
        fcntl.flock(held, fcntl.LOCK_UN)
    out, err = other.communicate(timeout=120)
    assert waiting and untouched
    assert other.returncode == 0 and out.strip() == str(home / "library"), err
    assert err.splitlines() == ["waiting for another cdlbib to finish downloading the bibliography ...",
                                f"downloading the bibliography to {home / 'library'} ..."]
    assert library.exists() and not (home / "library.partial").exists()


def test_two_commands_starting_together_make_one_library(managed):
    home, upstream = managed
    both = [subprocess.Popen([sys.executable, "-c", WAITER], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(2)]
    done = [p.communicate(timeout=120) + (p.returncode,) for p in both]
    for out, err, code in done:
        assert code == 0 and out.strip() == str(home / "library"), err
    said = sorted(line for _, err, _ in done for line in err.splitlines())
    assert said.count(f"downloading the bibliography to {home / 'library'} ...") == 1    # one download, not two
    assert set(said) <= {f"downloading the bibliography to {home / 'library'} ...",
                         "waiting for another cdlbib to finish downloading the bibliography ..."}
    assert library.exists() and not (home / "library.partial").exists()
    assert git("status", "--porcelain", cwd=home / "library") == ""
    assert git("rev-parse", "HEAD", cwd=home / "library") == git("rev-parse", "master", cwd=upstream)


# --- the lookup ------------------------------------------------------------------------------

def test_resolve_managed_downloads_once(managed, tmp_path, monkeypatch):
    home, upstream = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    said = []
    ws = workspace.resolve(managed=True, progress=said.append)
    assert ws.root == (home / "library").resolve() and ws.bib.is_file() and len(said) == 1
    assert workspace.default().root == ws.root        # the pure lookup of the same process agrees
    assert workspace.origin_of()[0].root == ws.root and workspace.origin_of()[1] == Origin.MANAGED
    upstream.rename(upstream.with_name("moved away.git"))        # a fetch or clone would now fail
    again = workspace.resolve(managed=True, progress=said.append)
    assert again.root == ws.root and len(said) == 1
    fresh = subprocess.run([sys.executable, "-c", RESOLVER], cwd=empty, capture_output=True, text=True)   # a new process
    assert (fresh.returncode, fresh.stdout.strip(), fresh.stderr) == (0, str(ws.root), "")
    assert sorted(p.name for p in home.iterdir()) == ["library", "lock", "state.json"]


def test_resolve_without_managed_never_downloads(managed, tmp_path, monkeypatch):
    home, _ = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    for lookup in (workspace.resolve, workspace.default, lambda: Workspace.find(None)):
        with pytest.raises(WorkspaceNotFound, match="No library found"):
            lookup()
    assert not home.exists()


def test_the_users_own_library_wins_and_nothing_is_downloaded(managed, tmp_path, monkeypatch):
    home, _ = managed
    option, variable, above = (own_library(tmp_path / name) for name in ("by option", "by variable", "above"))
    deep = above / "paper" / "sections"
    deep.mkdir(parents=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    refs = tmp_path / "paper refs" / "refs.bib"
    refs.parent.mkdir()
    refs.write_text("", encoding="utf-8")

    monkeypatch.chdir(deep)
    assert workspace.resolve(managed=True).root == above.resolve()
    assert workspace.origin_of()[1] == Origin.FOUND and workspace.origin_of()[0].root == above.resolve()

    monkeypatch.setenv("CDLBIB_LIBRARY", str(variable))
    assert workspace.resolve(managed=True).root == variable.resolve()
    assert workspace.origin_of()[1] == Origin.ENVIRONMENT

    workspace.select_library(str(option))
    assert workspace.resolve(managed=True).root == option.resolve()
    assert workspace.origin_of()[1] == Origin.OPTION

    named = workspace.resolve(str(refs), managed=True)
    assert named.bib == refs.resolve() and workspace.origin_of(str(refs))[1] == Origin.NAMED

    workspace.select_library(None)
    monkeypatch.delenv("CDLBIB_LIBRARY")
    monkeypatch.chdir(empty)
    assert workspace.resolve(str(refs), managed=True).bib == refs.resolve()
    assert not home.exists()


def test_a_named_library_that_is_missing_is_an_error_not_a_download(managed, tmp_path, monkeypatch):
    home, _ = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    workspace.select_library(str(empty))
    with pytest.raises(WorkspaceNotFound, match="--library points to"):
        workspace.resolve(managed=True)
    workspace.select_library(None)
    monkeypatch.setenv("CDLBIB_LIBRARY", str(empty))
    with pytest.raises(WorkspaceNotFound, match="CDLBIB_LIBRARY points to"):
        workspace.resolve(managed=True)
    assert not home.exists()


def test_in_one_process_the_users_own_library_wins_again_after_a_fallback(managed, tmp_path, monkeypatch):
    """A long-lived caller: the lookup is applied afresh on every call. Falling back to the
    managed library once does not make it the library of the rest of the process."""
    home, upstream = managed
    root = (home / "library").resolve()
    variable, here, option = (own_library(tmp_path / name) for name in ("by variable", "here", "by option"))
    empty = tmp_path / "empty"
    empty.mkdir()
    said = []

    def now(expected, origin):
        for lookup in (lambda: workspace.resolve(managed=True, progress=said.append), workspace.default,
                       lambda: workspace.origin_of()[0], api.ensure_library):
            assert lookup().root == expected
        assert workspace.origin_of()[1] == origin and api.where().origin == origin

    monkeypatch.chdir(empty)
    now(root, Origin.MANAGED)
    assert len(said) == 1 and said[0].startswith("downloading")
    upstream.rename(upstream.with_name("moved away.git"))        # from here on a download would fail

    monkeypatch.setenv("CDLBIB_LIBRARY", str(variable))
    now(variable.resolve(), Origin.ENVIRONMENT)
    monkeypatch.delenv("CDLBIB_LIBRARY")
    monkeypatch.chdir(here)
    now(here.resolve(), Origin.FOUND)
    monkeypatch.chdir(empty)
    now(root, Origin.MANAGED)                                    # managed again, and not downloaded again

    workspace.select_library(str(option))                        # --library given after the fallback
    now(option.resolve(), Origin.OPTION)
    monkeypatch.chdir(here)
    monkeypatch.setenv("CDLBIB_LIBRARY", str(variable))
    now(option.resolve(), Origin.OPTION)                         # ... and it outranks the other two
    workspace.select_library(None)
    monkeypatch.delenv("CDLBIB_LIBRARY")
    monkeypatch.chdir(empty)
    now(root, Origin.MANAGED)
    assert len(said) == 1


def test_a_library_option_given_before_the_fallback_is_never_replaced_by_it(managed, tmp_path, monkeypatch):
    home, _ = managed
    option = own_library(tmp_path / "by option")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    workspace.select_library(str(option))
    assert workspace.resolve(managed=True).root == option.resolve() and not home.exists()
    workspace.select_library(None)
    assert workspace.resolve(managed=True).root == (home / "library").resolve()
    workspace.select_library(str(option))
    assert workspace.resolve(managed=True).root == workspace.default().root == option.resolve()
    assert workspace.origin_of()[1] == Origin.OPTION


def test_default_finds_the_managed_library_only_after_a_fallback_in_this_process(managed, tmp_path, monkeypatch):
    home, _ = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    library.download()                                           # it is on disk, but no front end fell back to it
    with pytest.raises(WorkspaceNotFound, match="No library found"):
        workspace.default()
    ws = workspace.resolve(managed=True)
    assert workspace.default().root == ws.root
    monkeypatch.setenv("CDLBIB_HOME", str(tmp_path / "another data folder"))   # the fallback was to another place
    with pytest.raises(WorkspaceNotFound, match="No library found"):
        workspace.default()


def test_a_managed_library_that_disappears_mid_process_is_said_truthfully(managed, tmp_path, monkeypatch):
    home, _ = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    ws = workspace.resolve(managed=True)
    (home / "library").rename(home / "moved by the user")
    with pytest.raises(WorkspaceNotFound) as err:
        workspace.default()
    assert "--library points to" not in str(err.value)
    assert str(err.value).startswith(f"The library cdlbib downloaded to {home / 'library'} is no longer there.")
    said = []
    assert workspace.resolve(managed=True, progress=said.append).root == ws.root and len(said) == 1   # downloaded anew
    assert workspace.default().root == ws.root


# --- failures that are reported, not raised raw --------------------------------------------------

def test_a_state_file_that_cannot_be_written_does_not_fail_the_download(managed, tmp_path, monkeypatch):
    home, _ = managed
    (home / "state.json").mkdir(parents=True)                    # a folder where the file belongs: the write fails
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    said = []
    ws = workspace.resolve(managed=True, progress=said.append)
    assert ws.root == (home / "library").resolve() and library.exists()
    assert said == [f"downloading the bibliography to {home / 'library'} ...",
                    f"note: the bibliography was downloaded, but the time could not be recorded in "
                    f"{home / 'state.json'} (Is a directory)"]
    assert library.read_state() == library.State(None, os.environ["CDLBIB_UPSTREAM"])
    assert sorted(p.name for p in home.iterdir()) == ["library", "lock", "state.json"]   # no temporary file left


def test_a_command_still_works_when_the_state_file_cannot_be_written(managed, tmp_path):
    home, _ = managed
    (home / "state.json").mkdir(parents=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    out = cdlbib("verify", "--no-citations", cwd=empty)
    assert out.returncode == 0 and "looks good!" in out.stdout, out.stdout + out.stderr
    assert "Traceback" not in out.stderr and out.stderr.splitlines()[1] == (
        f"note: the bibliography was downloaded, but the time could not be recorded in {home / 'state.json'} "
        "(Is a directory)")
    out = cdlbib("where", cwd=empty)
    assert out.returncode == 0 and out.stdout.splitlines()[2] == "last update check: never", out.stdout + out.stderr


def test_an_upstream_beginning_with_a_dash_is_not_a_git_option(managed, tmp_path, monkeypatch):
    home, _ = managed
    monkeypatch.chdir(tmp_path)
    for value in ("--template=/nonexistent", "-u", "--upload-pack=touch pwned"):
        monkeypatch.setenv("CDLBIB_UPSTREAM", value)
        with pytest.raises(LibraryUnavailable, match="could not be downloaded from") as err:
            library.download()
        assert f"repository '{value}' does not exist" in str(err.value)      # git took it as a source, not an option
        assert not (home / "library").exists() and not (home / "library.partial").exists()
    assert not (tmp_path / "pwned").exists() and sorted(p.name for p in home.iterdir()) == ["lock"]


def test_a_stalled_download_times_out_and_leaves_nothing(managed, tmp_path, monkeypatch):
    """A real stall: git's ext transport runs `sleep` as the remote, which never answers.
    Only the time allowed is changed (a module constant)."""
    home, _ = managed
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "ext")
    monkeypatch.setenv("CDLBIB_UPSTREAM", "ext::sleep 60")
    monkeypatch.setattr(library, "CLONE_TIMEOUT", 2)
    started = time.monotonic()
    with pytest.raises(LibraryUnavailable) as err:
        library.download()
    assert time.monotonic() - started < 30
    assert "the download timed out (it did not finish within 2 seconds)" in str(err.value)
    assert not (home / "library").exists() and not (home / "library.partial").exists()
    time.sleep(0.5)
    left = subprocess.run(["pgrep", "-f", "^sleep 60$"], capture_output=True, text=True).stdout.split()
    assert left == [], "the stalled transport was left running"
    with open(home / "lock", "a") as lock:                       # and the lock is free again
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_a_library_cloned_from_another_upstream_is_reported_and_left_alone(managed, tmp_path, monkeypatch):
    home, upstream = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    root = library.download()
    (root / "cdl.bib").write_text("% my edit\n", encoding="utf-8")
    other = conftest.build_upstream(tmp_path / "other")
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(other))
    for attempt in (library.download, lambda: workspace.resolve(managed=True), api.ensure_library):
        with pytest.raises(LibraryUnavailable) as err:
            attempt()
        assert str(err.value) == (
            f"{root} is a copy of {upstream}, but cdlbib is set to download from {other}. It was left as it is. "
            "Move that folder away to download a fresh copy, or pass --library PATH to work in the copy you have.")
    assert (root / "cdl.bib").read_text(encoding="utf-8") == "% my edit\n"
    assert git("config", "--get", "remote.origin.url", cwd=root) == str(upstream)
    out = cdlbib("verify", "--no-citations", cwd=empty)
    assert out.returncode == 2 and "Traceback" not in out.stderr and "is a copy of" in out.stderr
    assert sorted(p.name for p in home.iterdir()) == ["library", "lock", "state.json"]
    # the same repository named another way is not 'another upstream'
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(upstream) + "/")
    assert library.download() == root
    link = tmp_path / "link to upstream"
    link.symlink_to(upstream)
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(link))
    assert library.download() == root
    # moved away, as the message says: a fresh copy of the configured upstream is downloaded
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(other))
    root.rename(home / "library kept by me")
    assert library.download() == root and git("config", "--get", "remote.origin.url", cwd=root) == str(other)
    assert (home / "library kept by me" / "cdl.bib").read_text(encoding="utf-8") == "% my edit\n"


def test_origin_names_are_the_documented_strings():
    assert (Origin.NAMED, Origin.OPTION, Origin.ENVIRONMENT, Origin.FOUND, Origin.MANAGED) == (
        "named", "--library", "CDLBIB_LIBRARY", "found", "managed")


# --- the api ---------------------------------------------------------------------------------

def test_api_ensure_library_and_where(managed, tmp_path, monkeypatch, capsys):
    home, _ = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    before = api.where()                                  # pure: says what would be used, downloads nothing
    assert before == api.Where(root=(home / "library").resolve(), origin="managed", last_check=None)
    assert not home.exists()
    said = []
    ws = api.ensure_library(progress=said.append)
    assert ws.root == (home / "library").resolve() and len(said) == 1
    after = api.where()
    assert after.root == ws.root and after.origin == "managed" and after.last_check == library.read_state().last_check
    assert after.last_check is not None
    own = own_library(tmp_path / "own")
    monkeypatch.setenv("CDLBIB_LIBRARY", str(own))
    assert api.where() == api.Where(root=own.resolve(), origin="CDLBIB_LIBRARY", last_check=None)
    assert api.ensure_library().root == own.resolve()
    assert capsys.readouterr() == ("", "")                # the api never prints


# --- the command -----------------------------------------------------------------------------

def test_a_command_outside_any_library_downloads_and_works_on_the_managed_one(managed, tmp_path):
    home, upstream = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    out = cdlbib("verify", "--no-citations", cwd=empty)
    root = (home / "library").resolve()
    assert out.returncode == 0 and "looks good!" in out.stdout, out.stdout + out.stderr
    assert f"loading {root / 'cdl.bib'}...done" in out.stdout
    assert out.stderr.splitlines()[0] == f"downloading the bibliography to {home / 'library'} ..."
    assert library.exists()
    upstream.rename(upstream.with_name("gone.git"))
    again = cdlbib("crossref", "status", cwd=empty)      # a second command: no download, same library
    assert again.returncode == 1 and "1 entries: pending=1" in again.stdout, again.stdout + again.stderr
    assert "downloading" not in again.stdout + again.stderr
    assert (root / ".bibcheck" / "verification.sqlite3").is_file()


def test_where_says_which_library_and_why(managed, tmp_path):
    home, _ = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    own = own_library(tmp_path / "own lib")
    (own / "sub").mkdir()
    refs = tmp_path / "refs.bib"
    refs.write_text("", encoding="utf-8")

    def lines(*args, cwd, **env):
        out = cdlbib(*args, cwd=cwd, **env)
        assert out.returncode == 0, out.stdout + out.stderr
        return out.stdout.splitlines()

    assert lines("where", cwd=own / "sub") == [str(own.resolve()), "chosen by: cdl.bib found in or above the current folder"]
    assert lines("where", cwd=empty, CDLBIB_LIBRARY=str(own)) == [str(own.resolve()), "chosen by: CDLBIB_LIBRARY"]
    assert lines("--library", str(own), "where", cwd=empty) == [str(own.resolve()), "chosen by: --library"]
    assert lines("where", "--fname", str(refs), cwd=own) == [str(refs.resolve()), "chosen by: the file you named"]
    assert not home.exists()

    out = cdlbib("where", cwd=empty)
    assert out.returncode == 0, out.stdout + out.stderr
    stamp = library.read_state().last_check.strftime("%Y-%m-%d %H:%M UTC")
    assert out.stdout.splitlines() == [str((home / "library").resolve()),
                                       "chosen by: no library named or found; this is the copy cdlbib downloads and manages",
                                       f"last update check: {stamp}"]
    assert out.stderr == f"downloading the bibliography to {home / 'library'} ...\n"
    assert cdlbib("where", cwd=empty).stderr == ""


def test_an_unreachable_upstream_is_one_message_and_exit_2(managed, tmp_path):
    home, _ = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    missing = tmp_path / "nowhere.git"
    for args in (("verify", "--no-citations"), ("crossref", "status"), ("where",)):
        out = cdlbib(*args, cwd=empty, CDLBIB_UPSTREAM=str(missing))
        assert out.returncode == 2 and "Traceback" not in out.stderr, out.stdout + out.stderr
        assert out.stderr.splitlines()[0] == f"downloading the bibliography to {home / 'library'} ..."
        assert f"The bibliography could not be downloaded from {missing}" in out.stderr
        assert "pass --library PATH or set CDLBIB_LIBRARY" in out.stderr
        assert not (home / "library").exists() and not (home / "library.partial").exists()


def test_help_and_version_create_nothing_and_contact_nothing(managed, tmp_path):
    home, _ = managed
    empty = tmp_path / "empty"
    empty.mkdir()
    for args in (("--help",), ("--version",), ("verify", "--help"), ("where", "--help"), ("crossref", "--help"),
                 ("crossref", "status", "--help")):
        out = cdlbib(*args, cwd=empty, CDLBIB_UPSTREAM=str(tmp_path / "nowhere.git"))
        assert out.returncode == 0 and "downloading" not in out.stdout + out.stderr, out.stdout + out.stderr
    assert not home.exists()
