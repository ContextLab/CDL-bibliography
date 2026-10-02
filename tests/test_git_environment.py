"""No git command of cdlbib acts on the repository the environment names.

git reads GIT_DIR and GIT_WORK_TREE before it looks at the folder it is run in; they are
exported inside git hooks, `git rebase --exec` and some editor tooling. Here they point at
a second real clone, and everything cdlbib does must still happen in the library it was
asked about, with that other clone byte-for-byte as it was. Real git, real variables.
"""
import datetime
import os
import subprocess

import pytest

import conftest
from cdlbib import gitenv, library, publish
from cdlbib.workspace import Workspace
from test_update import (HOUR, advance, backup_names, cdlbib, checked, clone_of, empty_folder, git, hashes,  # noqa: F401
                         managed, snapshot, updated_line, write)


def everything(clone):
    """All of a clone that a stray git command could touch: HEAD, every ref, the index, the
    files of the working tree, and what git's own folder holds besides."""
    tops = sorted(p.name for p in clone.iterdir() if p.name != ".git")
    inside = sorted(p.relative_to(clone).as_posix() for p in (clone / ".git").rglob("*") if p.is_file())
    return {"head": (clone / ".git" / "HEAD").read_bytes(), "refs": git("for-each-ref", cwd=clone),
            "index": (clone / ".git" / "index").read_bytes(), "files": hashes(clone, tops), "git files": inside,
            "status": git("status", "--porcelain", "--untracked-files=all", cwd=clone)}


def pointing_at(clone):
    return {"GIT_DIR": str(clone / ".git"), "GIT_WORK_TREE": str(clone), "GIT_INDEX_FILE": str(clone / ".git" / "index")}


@pytest.fixture
def other(managed, tmp_path):
    """The user's own clone of the same upstream, with work of its own in it."""
    home, upstream, ws = managed
    clone = clone_of(upstream, tmp_path / "the user's own clone")
    write(clone, "cdl.bib", conftest.ZOLL90 + "\n% the user's own edit\n")
    write(clone, "verification/own.txt", "own\n")
    return clone


def test_git_env_drops_what_names_a_repository_and_keeps_the_rest():
    given = {"GIT_DIR": "/x/.git", "GIT_WORK_TREE": "/x", "GIT_INDEX_FILE": "/x/.git/index", "GIT_OBJECT_DIRECTORY": "/o",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/a", "GIT_COMMON_DIR": "/c", "GIT_NAMESPACE": "n", "GIT_PREFIX": "p/",
             "GIT_CEILING_DIRECTORIES": "/", "GIT_DISCOVERY_ACROSS_FILESYSTEM": "1",
             "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@x.invalid", "GIT_COMMITTER_NAME": "C",
             "GIT_COMMITTER_EMAIL": "c@x.invalid", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_SSH_COMMAND": "ssh -v", "GIT_SSH": "ssh", "GIT_ASKPASS": "ask", "GIT_ALLOW_PROTOCOL": "ext",
             "GIT_TERMINAL_PROMPT": "1", "PATH": "/bin", "HOME": "/h"}
    env = gitenv.git_env(given)
    assert sorted(set(given) - set(env)) == sorted(gitenv.REPOSITORY_VARIABLES)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert {k: v for k, v in env.items() if k != "GIT_TERMINAL_PROMPT"} == {
        k: v for k, v in given.items() if k not in gitenv.REPOSITORY_VARIABLES and k != "GIT_TERMINAL_PROMPT"}
    assert "GIT_DIR" in given                                         # the argument is not changed
    assert gitenv.git_env()["GIT_TERMINAL_PROMPT"] == "0"


def test_the_automatic_update_acts_on_the_managed_library_only(managed, other, tmp_path):
    home, upstream, ws = managed
    old = git("rev-parse", "HEAD", cwd=ws.root)
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n", "cdl.bib": conftest.ZOLL90 + "\n% upstream\n"})
    checked(home, 25 * HOUR)
    before = everything(other)

    out = cdlbib("where", cwd=empty_folder(tmp_path), **pointing_at(other))
    assert out.returncode == 0 and out.stderr == updated_line(1, home) + "\n", out.stderr
    assert everything(other) == before                               # refs, index, files: untouched
    assert "refs/cdlbib" not in git("for-each-ref", cwd=other)
    # and the managed library is updated whole: its branch, its index and its files agree
    assert git("rev-parse", "HEAD", cwd=ws.root) == new and git("symbolic-ref", "--short", "HEAD", cwd=ws.root) == "master"
    assert git("status", "--porcelain", "--untracked-files=all", cwd=ws.root) == ""
    assert (ws.root / "cdl.bib").read_text(encoding="utf-8").endswith("% upstream\n")
    saved = library.backups()
    assert len(saved) == 1 and saved[0].commit == old
    assert git("rev-parse", f"refs/cdlbib/backups/{saved[0].stamp}", cwd=ws.root) == old

    undone = cdlbib("update", "--undo", cwd=empty_folder(tmp_path), **pointing_at(other))   # the command, the same way
    assert undone.returncode == 0, undone.stderr
    assert git("rev-parse", "HEAD", cwd=ws.root) == old and git("status", "--porcelain", cwd=ws.root) == ""
    assert everything(other) == before


def test_backup_and_undo_act_on_the_managed_library_only(managed, other, monkeypatch):
    home, upstream, ws = managed
    write(ws.root, "cdl.bib", conftest.ZOLL90 + "\n% unsent, in the managed library\n")
    state, before = snapshot(ws.root), everything(other)
    with monkeypatch.context() as patch:
        for name, value in pointing_at(other).items():
            patch.setenv(name, value)
        made = library.backup(ws)
    assert made.commit == state["commit"] and made.changed == ["cdl.bib"]
    assert (made.path / "files" / "cdl.bib").read_text(encoding="utf-8").endswith("in the managed library\n")
    assert git("rev-parse", f"refs/cdlbib/backups/{made.stamp}", cwd=ws.root) == state["commit"]
    write(ws.root, "cdl.bib", conftest.ZOLL90 + "\n% something else\n")
    with monkeypatch.context() as patch:
        for name, value in pointing_at(other).items():
            patch.setenv(name, value)
        library.undo(ws)
    assert snapshot(ws.root) == state
    assert everything(other) == before and "refs/cdlbib" not in git("for-each-ref", cwd=other)


def test_download_makes_the_managed_library_whatever_the_environment_names(managed, other, tmp_path, monkeypatch):
    home, upstream, ws = managed
    before = everything(other)
    fresh = tmp_path / "a fresh data folder"
    monkeypatch.setenv("CDLBIB_HOME", str(fresh))
    with monkeypatch.context() as patch:
        for name, value in pointing_at(other).items():
            patch.setenv(name, value)
        root = library.download()
        assert library.exists()
    assert root == fresh / "library" and (root / ".git").is_dir() and (root / "cdl.bib").is_file()
    assert git("rev-parse", "HEAD", cwd=root) == git("rev-parse", "master", cwd=upstream)
    assert git("status", "--porcelain", cwd=root) == "" and git("config", "--get", "remote.origin.url", cwd=root) == str(upstream)
    assert everything(other) == before


def test_a_send_commits_and_pushes_from_the_checkout_it_was_given(tmp_path, monkeypatch):
    """publish.py's core path (deliver: commit on a branch, push it) against a local bare
    remote, with the environment naming another clone of the same remote."""
    monkeypatch.setenv("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")
    for name, value in {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}.items():
        monkeypatch.setenv(name, value)
    remote = conftest.build_upstream(tmp_path / "remote")
    work = clone_of(remote, tmp_path / "My Bibliothèque")
    elsewhere = clone_of(remote, tmp_path / "another clone")
    write(elsewhere, "cdl.bib", conftest.ZOLL90 + "\n% the other clone's own edit\n")
    write(work, "cdl.bib", conftest.ZOLL90 + "\n% the change to send\n")
    before, start = everything(elsewhere), git("rev-parse", "HEAD", cwd=work)
    branch = "cdlbib/test/2026-10-02-environment"
    with monkeypatch.context() as patch:
        for name, value in pointing_at(elsewhere).items():
            patch.setenv(name, value)
        files = publish.deliver(Workspace(work), branch, "A change", str(remote))
        assert publish.current_branch(Workspace(work)) == branch
    assert files == ["cdl.bib"]
    sent = git("rev-parse", "HEAD", cwd=work)
    assert sent != start and git("symbolic-ref", "--short", "HEAD", cwd=work) == branch
    assert git("show", "--name-only", "--format=", sent, cwd=work).split() == ["cdl.bib"]
    assert git("status", "--porcelain", cwd=work) == "" and git("rev-parse", "master", cwd=work) == start
    assert git("rev-parse", branch, cwd=remote) == sent and git("rev-parse", "master", cwd=remote) == start
    assert everything(elsewhere) == before
    assert branch not in git("for-each-ref", cwd=elsewhere)
