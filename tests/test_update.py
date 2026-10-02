"""Backups of the managed library, restoring one, `cdlbib update --list` / `--undo`, and the
daily check that brings the library up to date when a command runs.

Real git against a local bare upstream; every test has a data folder of its own. A restore
is data-safety code, so each restore test compares a snapshot taken before the backup with
one taken after the restore: the branch, the commit, the set of changed paths under cdl.bib
and verification/, and a hash of every file under them.
"""
import contextlib
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

import conftest
from cdlbib import api, cli, library, verification_cli, workspace
from cdlbib.errors import CdlbibError, UpdateConflict, UpdateNeedsDecision
from cdlbib.workspace import Workspace

_SIBLING = Path(sys.executable).parent / "cdlbib"
CDLBIB = str(_SIBLING) if _SIBLING.exists() else shutil.which("cdlbib")
KEPT = ("cdl.bib", "verification")
STAMP = re.compile(r"\d{8}T\d{6}\.\d{6}Z")


# --- helpers ---------------------------------------------------------------------------------

def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def changed_paths(root, *pathspec):
    """{path: XY} from `git status --porcelain -z`, limited to the given paths."""
    raw = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all", "--", *pathspec],
                         cwd=root, capture_output=True, text=True, check=True).stdout
    parts, found, at = raw.split("\0"), {}, 0
    while at < len(parts):
        item = parts[at]
        at += 1
        if not item:
            continue
        found[item[3:]] = item[:2]
        if "R" in item[:2]:
            found[parts[at]] = item[:2]
            at += 1
    return found


def digest(path):
    if os.path.islink(path):
        return "link:" + os.readlink(path)
    mode = "x" if os.stat(path).st_mode & stat.S_IXUSR else "-"
    return mode + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes(root, tops):
    found = {}
    for top in tops:
        start = Path(root) / top
        if start.is_file() or start.is_symlink():
            found[top] = digest(start)
        for folder, _dirs, names in os.walk(start):
            for name in names:
                full = Path(folder) / name
                found[full.relative_to(root).as_posix()] = digest(full)
    return found


def snapshot(root):
    """Everything a restore guarantees. Whether a change was staged is not part of it (the
    guarantee leaves that out); the paths that are changed, and every byte, are."""
    branch = subprocess.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=root, capture_output=True, text=True)
    return {"branch": branch.stdout.strip() or None, "commit": git("rev-parse", "HEAD", cwd=root),
            "branches": local_branches(root),          # every local branch, not only the one the library is on
            "changed": sorted(changed_paths(root, *KEPT)), "files": hashes(root, KEPT)}


def local_branches(root):
    lines = git("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads", cwd=root).splitlines()
    return dict(line.rsplit(" ", 1) for line in lines)


def outside(root):
    """Hashes of every file that is not cdl.bib, verification/ or git's own folder."""
    return hashes(root, sorted(p.name for p in Path(root).iterdir() if p.name not in KEPT + (".git",)))


def advance(upstream, message, **files):
    """A new commit on the upstream's master holding the given files ('a/b.txt'='text'; None deletes)."""
    work = Path(upstream).parent / "upstream-work"
    for name, text in files.items():
        target = work / name
        if text is None:
            conftest._git("rm", "--quiet", name, cwd=work)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        conftest._git("add", name, cwd=work)
    conftest._git("commit", "--quiet", "-m", message, cwd=work)
    conftest._git("push", "--quiet", str(upstream), "master", cwd=work)
    return git("rev-parse", "HEAD", cwd=work)


def fast_forward(root, commit="origin/master"):
    conftest._git("fetch", "--quiet", "origin", cwd=root)
    conftest._git("merge", "--quiet", "--ff-only", commit, cwd=root)


def write(root, name, text):
    target = Path(root) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@contextlib.contextmanager
def helpers_seen(pattern):
    """While the block runs, collect the PID of every process whose command line matches
    ``pattern`` (pgrep -f): the stalled transport and the git processes that started it."""
    import threading
    seen, stop = set(), threading.Event()

    def poll():
        while not stop.is_set():
            found = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
            seen.update(int(pid) for pid in found)
            stop.wait(0.2)

    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    try:
        yield seen
    finally:
        stop.set()
        thread.join()


def still_running(pids):
    alive = []
    for pid in pids:
        try:
            os.kill(pid, 0)
            alive.append(pid)
        except ProcessLookupError:
            pass
        except PermissionError:
            alive.append(pid)
    return alive


def cdlbib(*args, cwd, **env):
    """Run the command with no terminal (stdin is /dev/null, whatever pytest itself runs in)."""
    return subprocess.run([CDLBIB, *args], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, **env),
                          stdin=subprocess.DEVNULL)


@pytest.fixture
def managed(tmp_path, monkeypatch):
    """A downloaded managed library in a data folder of this test alone (spaces and non-ASCII
    in its path). Gives (home, upstream, the library's workspace)."""
    home = tmp_path / "Données de l'app – cdlbib"
    upstream = conftest.build_upstream(tmp_path / "up")
    monkeypatch.setenv("CDLBIB_HOME", str(home))
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(upstream))
    monkeypatch.delenv("CDLBIB_LIBRARY", raising=False)
    if sys.platform == "darwin":
        monkeypatch.setenv("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")
    workspace.select_library(None)
    root = library.download()
    yield home, upstream, Workspace(root)
    workspace.select_library(None)
    conftest.no_real_library_touched()


def unsent_work(root):
    """The state the brief names: one local commit, a modified cdl.bib, a new untracked file
    under verification/, and the rebuildable cache that is never backed up."""
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% committed locally\n")
    conftest._git("commit", "--quiet", "-m", "A local commit", "--", "cdl.bib", cwd=root)
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% committed locally\n% and edited since – é\n")
    write(root, "verification/notes/new entry.jsonl", '{"key": "Zoll90"}\n')
    write(root, ".bibcheck/verification.sqlite3", "a cache")


# --- the snapshot helper itself --------------------------------------------------------------

def test_the_snapshot_sees_branch_commit_changed_paths_and_every_byte(managed):
    _, _, ws = managed
    first = snapshot(ws.root)
    assert first["branch"] == "master" and first["changed"] == []
    assert sorted(first["files"]) == ["cdl.bib", "verification/.gitkeep"]
    write(ws.root, "verification/x.txt", "1")
    second = snapshot(ws.root)
    assert second["changed"] == ["verification/x.txt"] and second != first
    write(ws.root, "verification/x.txt", "2")
    assert snapshot(ws.root)["files"] != second["files"]              # one byte is a difference
    os.unlink(ws.root / "verification/x.txt")
    assert snapshot(ws.root) == first
    write(ws.root, "README", "outside")                               # outside the two paths: not in the snapshot
    assert snapshot(ws.root) == first and outside(ws.root) != {}


# --- backup ----------------------------------------------------------------------------------

def test_a_backup_holds_the_edit_the_untracked_file_and_the_local_commit(managed):
    home, _, ws = managed
    unsent_work(ws.root)
    write(ws.root, "README", "outside the two paths")
    local = git("rev-parse", "HEAD", cwd=ws.root)
    made = library.backup(ws)

    assert made.path.parent == home.resolve() / "backups" and STAMP.fullmatch(made.path.name)
    assert sorted(p.name for p in made.path.iterdir()) == ["changes.bundle", "files", "ref.json"]
    on_disk = hashes(ws.root, KEPT)
    # only what git cannot reproduce: the edited file and the untracked one, byte for byte; not the clean .gitkeep
    assert hashes(made.path / "files", KEPT) == {name: on_disk[name] for name in
                                                 ("cdl.bib", "verification/notes/new entry.jsonl")}
    assert sorted(p.name for p in (made.path / "files").iterdir()) == ["cdl.bib", "verification"]   # no .bibcheck, no README
    assert not [p for p in made.path.rglob("*") if ".bibcheck" in p.parts or p.name == "README"]

    ref = json.loads((made.path / "ref.json").read_text(encoding="utf-8"))
    assert ref["branch"] == "master" and ref["commit"] == local
    assert ref["changed"] == ["cdl.bib", "verification/notes/new entry.jsonl"]
    assert ref["untracked"] == ["verification/notes/new entry.jsonl"]
    assert ref["status"] == " M cdl.bib\0?? verification/notes/new entry.jsonl\0"
    assert ref["paths"] == {"cdl.bib": " M", "verification/notes/new entry.jsonl": "??"}
    assert ref["deleted"] == [] and ref["folders"] == ["verification", "verification/notes"]
    assert git("rev-parse", ref["pin"], cwd=ws.root) == local and ref["pin"] == "refs/cdlbib/backups/" + made.path.name
    assert made.stamp == made.path.name
    assert (made.branch, made.commit, made.changed, made.has_bundle) == ("master", local, ref["changed"], True)
    assert made.taken_at.strftime("%Y%m%dT%H%M%S.%fZ") == made.path.name and made.taken_at.tzinfo is not None
    assert local in git("bundle", "list-heads", str(made.path / "changes.bundle"), cwd=ws.root)
    assert library.backups() == [made]


def test_a_backup_without_local_commits_has_no_bundle(managed):
    _, _, ws = managed
    before = snapshot(ws.root)
    made = library.backup(ws)
    assert not made.has_bundle and made.changed == []
    assert sorted(p.name for p in made.path.iterdir()) == ["files", "ref.json"]
    assert snapshot(ws.root) == before                     # taking a backup changes nothing in the library


def test_a_backup_changes_nothing_in_the_library(managed):
    _, _, ws = managed
    unsent_work(ws.root)
    before, others, refs = snapshot(ws.root), outside(ws.root), git("for-each-ref", cwd=ws.root)
    made = library.backup(ws)
    assert (snapshot(ws.root), outside(ws.root)) == (before, others)
    # the one thing added to the clone: the private ref that keeps the recorded commit
    assert git("for-each-ref", cwd=ws.root).splitlines() == sorted(
        refs.splitlines() + [f"{made.commit} commit\trefs/cdlbib/backups/{made.stamp}"], key=lambda line: line.split("\t")[1])


def test_only_the_managed_library_is_backed_up(managed, tmp_path):
    home, _, ws = managed
    own = tmp_path / "own"
    shutil.copytree(ws.root, own)
    with pytest.raises(CdlbibError, match="only for the library cdlbib manages"):
        library.backup(Workspace(own))
    made = library.backup(ws)
    with pytest.raises(CdlbibError, match="only for the library cdlbib manages"):
        library.restore(made, Workspace(own))
    assert library.backups() == [made]


def test_eleven_backups_leave_the_ten_newest_and_nothing_else_is_deleted(managed):
    home, _, ws = managed
    folder = home / "backups"
    made = [library.backup(ws) for _ in range(3)]
    (folder / "my notes").mkdir()                                    # not a name the code writes: never pruned
    (folder / "my notes" / "keep.txt").write_text("mine", encoding="utf-8")
    (folder / "20200101T000000.000000Z.partial" / "files").mkdir(parents=True)   # left by a crash, long ago
    fresh = folder / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + ".partial")
    fresh.mkdir()                                                    # a backup another command is making right now
    (folder / "20200101T000000.000000Z.partial.txt").mkdir()         # not the code's own name: never removed
    (folder / "20200101T000000.000001Z").write_text("a file, not a backup folder", encoding="utf-8")
    (folder / "20200101T000000.000002Zx").mkdir()
    made += [library.backup(ws) for _ in range(8)]
    assert len(made) == 11 and len({b.path.name for b in made}) == 11
    kept = library.backups()
    assert [b.path.name for b in kept] == sorted((b.path.name for b in made[1:]), reverse=True)   # newest first
    assert not made[0].path.exists()
    assert (folder / "my notes" / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert not (folder / "20200101T000000.000000Z.partial").exists()          # over an hour old: swept
    assert fresh.is_dir() and (folder / "20200101T000000.000000Z.partial.txt").is_dir()
    assert (folder / "20200101T000000.000001Z").is_file() and (folder / "20200101T000000.000002Zx").is_dir()
    pins = git("for-each-ref", "--format=%(refname)", "refs/cdlbib", cwd=ws.root).splitlines()
    assert pins == sorted("refs/cdlbib/backups/" + b.path.name for b in made[1:])   # the pruned backup's ref went with it
    assert sorted(p.name for p in home.iterdir()) == ["backups", "library", "lock", "state.json"]


@pytest.mark.parametrize("place", ["/", "~", "one level"])
def test_a_dangerous_data_folder_is_refused_before_anything_is_written(monkeypatch, tmp_path, place):
    chosen = {"/": "/", "~": str(Path.home()), "one level": "/tmp"}[place]
    monkeypatch.setenv("CDLBIB_HOME", chosen)
    with pytest.raises(CdlbibError, match="will not keep or delete backups"):
        library.backups_folder()
    with pytest.raises(CdlbibError, match="will not keep or delete backups"):
        library.backups()
    assert not (Path(chosen) / "backups").exists()


# --- restore ---------------------------------------------------------------------------------

def test_restore_after_an_update_and_further_edits_returns_every_byte(managed):
    home, upstream, ws = managed
    root = ws.root
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% my unsent edit\n")
    write(root, "verification/mine.jsonl", "untracked work\n")
    write(root, "verification/deep/er/also mine.txt", "é\n")
    before = snapshot(root)
    made = library.backup(ws)

    newer = advance(upstream, "An update", **{"verification/from-update.txt": "upstream\n", "README": "new upstream file\n",
                                              "verification/.gitkeep": "changed upstream\n"})
    fast_forward(root)
    assert git("rev-parse", "HEAD", cwd=root) == newer != before["commit"]
    write(root, "cdl.bib", "% everything replaced\n")                 # the working tree changes after the update
    os.unlink(root / "verification/mine.jsonl")
    write(root, "verification/from-update.txt", "edited after the update\n")
    write(root, "verification/after.txt", "made after the backup\n")
    assert snapshot(root) != before

    library.restore(made, ws)
    assert snapshot(root) == before
    assert not (root / "README").exists()                             # git took the clean tracked file back with the commit
    assert changed_paths(root, ".") == {"cdl.bib": " M", "verification/deep/er/also mine.txt": "??",
                                        "verification/mine.jsonl": "??"}
    assert git("rev-parse", "origin/master", cwd=root) == newer       # the update is still there to take again


def test_a_file_that_is_not_in_the_backup_is_moved_into_the_pre_undo_backup_not_deleted(managed):
    """The rule: restore puts back exactly the backed-up file set under cdl.bib and
    verification/. Any other file found there is moved into the backup taken just before the
    restore; nothing the user could have written is deleted."""
    home, upstream, ws = managed
    root = ws.root
    with open(root / ".git" / "info" / "exclude", "a", encoding="utf-8") as out:
        out.write("verification/*.tmp\n")
    write(root, "verification/kept.tmp", "ignored by git, present at the backup\n")
    before = snapshot(root)
    made = library.backup(ws)
    advance(upstream, "An update that adds a file", **{"verification/added by update.jsonl": "upstream\n"})
    fast_forward(root)
    write(root, "verification/written later.txt", "untracked, after the backup\n")
    write(root, "verification/later.tmp", "ignored, after the backup\n")
    write(root, "verification/sub/dir/deep.txt", "deep\n")
    os.unlink(root / "verification/kept.tmp")

    library.restore(made, ws)
    assert snapshot(root) == before
    assert (root / "verification/kept.tmp").read_text(encoding="utf-8") == "ignored by git, present at the backup\n"
    for gone in ("written later.txt", "later.tmp", "sub", "added by update.jsonl"):
        assert not (root / "verification" / gone).exists()
    pre = library.backups()[0]
    assert pre != made and len(library.backups()) == 2
    saved = pre.path / "files" / "verification"
    assert (saved / "written later.txt").read_text(encoding="utf-8") == "untracked, after the backup\n"
    assert (saved / "later.tmp").read_text(encoding="utf-8") == "ignored, after the backup\n"
    assert (saved / "sub/dir/deep.txt").read_text(encoding="utf-8") == "deep\n"
    assert not (saved / "added by update.jsonl").exists()             # a clean file of the commit: git keeps it, not the backup

    library.restore(pre, ws)                                           # and the pre-undo backup brings them all back
    assert (root / "verification/written later.txt").read_text(encoding="utf-8") == "untracked, after the backup\n"
    assert (root / "verification/later.tmp").is_file() and (root / "verification/sub/dir/deep.txt").is_file()
    assert (root / "verification/added by update.jsonl").is_file() and not (root / "verification/kept.tmp").exists()


def test_a_deleted_tracked_file_a_symlink_and_an_executable_come_back_as_they_were(managed):
    _, upstream, ws = managed
    root = ws.root
    os.unlink(root / "verification/.gitkeep")
    write(root, "verification/run.sh", "#!/bin/sh\n")
    os.chmod(root / "verification/run.sh", 0o755)
    os.symlink("run.sh", root / "verification/link")
    before = snapshot(root)
    assert before["files"]["verification/link"] == "link:run.sh" and before["files"]["verification/run.sh"].startswith("x")
    made = library.backup(ws)
    advance(upstream, "An update", README="r\n")
    fast_forward(root)
    conftest._git("restore", "--", "verification/.gitkeep", cwd=root)
    os.unlink(root / "verification/link")
    os.chmod(root / "verification/run.sh", 0o644)
    library.restore(made, ws)
    assert snapshot(root) == before
    assert changed_paths(root, *KEPT)["verification/.gitkeep"] == " D"


def test_staged_changes_come_back_unstaged_with_identical_bytes(managed):
    """Documented limit: branch, commit and bytes are exact; whether a change was staged is
    not preserved. ref.json keeps the original status text."""
    _, upstream, ws = managed
    root = ws.root
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% staged edit\n")
    write(root, "verification/staged new.jsonl", "new\n")
    conftest._git("add", "cdl.bib", "verification/staged new.jsonl", cwd=root)
    assert changed_paths(root, *KEPT) == {"cdl.bib": "M ", "verification/staged new.jsonl": "A "}
    before = snapshot(root)
    made = library.backup(ws)
    ref = json.loads((made.path / "ref.json").read_text(encoding="utf-8"))
    assert ref["status"] == "M  cdl.bib\0A  verification/staged new.jsonl\0"
    advance(upstream, "An update", README="r\n")
    conftest._git("restore", "--staged", "--worktree", "--source=HEAD", "--", "cdl.bib", "verification", cwd=root)
    fast_forward(root)
    write(root, "cdl.bib", "% something else\n")
    library.restore(made, ws)
    assert snapshot(root) == before                                    # same changed paths, same bytes
    assert changed_paths(root, *KEPT) == {"cdl.bib": " M", "verification/staged new.jsonl": "??"}


@pytest.mark.parametrize("lost", ["branch", "branch and bundle", "branch and private ref", "branch, private ref and bundle"])
def test_a_backup_whose_branch_was_deleted_is_restored_onto_a_recreated_branch(managed, lost):
    """The recorded commit is kept twice: by the backup's private ref in the clone, and in its
    bundle. Either alone brings it back after the branch is deleted and git has pruned."""
    home, _, ws = managed
    root = ws.root
    conftest._git("switch", "--quiet", "-c", "cdlbib/someone/a-topic", cwd=root)
    unsent_work(root)
    before = snapshot(root)
    assert before["branch"] == "cdlbib/someone/a-topic"
    made = library.backup(ws)
    assert made.has_bundle

    conftest._git("restore", "--source=HEAD", "--staged", "--worktree", "--", "cdl.bib", cwd=root)
    conftest._git("switch", "--quiet", "master", cwd=root)
    conftest._git("branch", "--quiet", "-D", "cdlbib/someone/a-topic", cwd=root)
    if "private ref" in lost:
        conftest._git("update-ref", "-d", "refs/cdlbib/backups/" + made.stamp, cwd=root)
    if "bundle" in lost:
        os.unlink(made.path / "changes.bundle")
    conftest._git("reflog", "expire", "--expire=now", "--all", cwd=root)
    conftest._git("gc", "--quiet", "--prune=now", cwd=root)            # git discards whatever nothing keeps
    kept = subprocess.run(["git", "cat-file", "-e", before["commit"]], cwd=root, capture_output=True).returncode == 0
    assert kept == ("private ref" not in lost)        # the private ref alone keeps the commit through gc --prune=now

    if lost == "branch, private ref and bundle":
        now, others = snapshot(root), outside(root)
        with pytest.raises(CdlbibError) as err:
            library.restore(made, ws)
        assert f"commit {before['commit'][:8]} is no longer in the library" in str(err.value)
        assert "Nothing was changed" in str(err.value)
        assert (snapshot(root), outside(root)) == (now, others)
        assert [b.path for b in library.backups()] == [made.path]      # the copy taken for the attempt is not kept
        return
    library.restore(made, ws)
    assert snapshot(root) == before
    assert git("rev-parse", "refs/heads/cdlbib/someone/a-topic", cwd=root) == before["commit"]


def test_a_detached_head_is_restored_detached(managed):
    _, upstream, ws = managed
    root = ws.root
    conftest._git("switch", "--quiet", "--detach", "HEAD", cwd=root)
    write(root, "cdl.bib", "% detached edit\n")
    before = snapshot(root)
    assert before["branch"] is None
    made = library.backup(ws)
    conftest._git("restore", "--", "cdl.bib", cwd=root)
    conftest._git("switch", "--quiet", "master", cwd=root)
    advance(upstream, "An update", **{"cdl.bib": conftest.ZOLL90 + "\n% upstream\n"})
    fast_forward(root)
    updated = git("rev-parse", "master", cwd=root)
    library.restore(made, ws)
    # master was not the backup's branch and no undo had moved it: it stays where the update put it
    assert snapshot(root) == dict(before, branches={"master": updated}) and updated != before["commit"]


# --- files outside cdl.bib and verification/ -------------------------------------------------

def test_a_local_change_outside_the_two_paths_that_the_undo_would_overwrite_is_a_refusal(managed):
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "A README", README="first\n", **{"docs/guide.txt": "one\n"})
    fast_forward(root)
    made = library.backup(ws)
    advance(upstream, "README and guide change", README="second\n", **{"docs/guide.txt": "two\n"})
    fast_forward(root)
    write(root, "README", "second, and my own note\n")                # differs between the two commits AND edited here
    write(root, "docs/guide.txt", "two, edited\n")
    write(root, "cdl.bib", "% my edit\n")
    before, others, refs = snapshot(root), outside(root), git("for-each-ref", cwd=root)
    with pytest.raises(CdlbibError) as err:
        library.restore(made, ws)
    message = str(err.value)
    assert "would overwrite README, docs/guide.txt, which cdlbib does not back up" in message
    assert "Nothing was changed" in message
    assert (snapshot(root), outside(root), git("for-each-ref", cwd=root)) == (before, others, refs)
    assert changed_paths(root, ".") == {"README": " M", "docs/guide.txt": " M", "cdl.bib": " M"}
    assert library.backups() == [made]             # a refused restore leaves no backup: the newest is still the newest
    with pytest.raises(CdlbibError, match="README, docs/guide.txt"):
        api.undo_update()
    assert library.backups() == [made] and snapshot(root) == before
    conftest._git("restore", "--", "README", "docs/guide.txt", cwd=root)     # the user removes those changes
    assert api.undo_update() == made
    assert snapshot(root)["commit"] == made.commit and (root / "README").read_text(encoding="utf-8") == "first\n"
    assert hashes(library.backups()[0].path / "files", KEPT) == {"cdl.bib": before["files"]["cdl.bib"]}


def test_files_outside_the_two_paths_that_do_not_conflict_are_untouched_by_an_undo(managed):
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "A README", README="first\n")
    fast_forward(root)
    write(root, "cdl.bib", "% edit before the update\n")
    before = snapshot(root)
    library.backup(ws)
    conftest._git("restore", "--", "cdl.bib", cwd=root)
    advance(upstream, "An entry", **{"cdl.bib": conftest.ZOLL90 + "\n% upstream\n", "LICENSE": "added upstream\n"})
    fast_forward(root)
    write(root, "README", "first\nmy own line\n")                     # tracked, modified, the same in both commits
    write(root, "my notes.txt", "untracked, outside\n")
    write(root, ".bibcheck/verification.sqlite3", "cache")
    mine = {name: digest(root / name) for name in ("README", "my notes.txt", ".bibcheck/verification.sqlite3")}

    api.undo_update()
    assert snapshot(root) == before
    assert {name: digest(root / name) for name in mine} == mine       # byte-identical
    assert changed_paths(root, "README", "my notes.txt") == {"README": " M", "my notes.txt": "??"}
    assert not (root / "LICENSE").exists()                            # clean and tracked: git took it back with the commit
    for saved in library.backups():                                   # nothing from outside the two paths is in a backup
        assert sorted(p.name for p in saved.path.iterdir()) == ["files", "ref.json"]
        assert set(hashes(saved.path / "files", ["."])) <= {"cdl.bib"}


# --- a failure part-way ----------------------------------------------------------------------

def test_a_branch_that_moved_meanwhile_stops_the_restore_and_names_the_saved_copy(managed):
    """The branch is moved back by compare-and-swap. Here a real git hook moves the branch
    between the check and the swap: the restore stops, moves nothing else, and says where
    the user's files are; an undo then returns to exactly the state before the attempt."""
    home, upstream, ws = managed
    root = ws.root
    first = git("rev-parse", "HEAD", cwd=root)
    middle = advance(upstream, "Update one", README="one\n")
    fast_forward(root)
    made = library.backup(ws)                                           # master at `middle`
    last = advance(upstream, "Update two", README="two\n")
    fast_forward(root)
    write(root, "cdl.bib", "% unsent edit\n")
    write(root, "verification/unsent.txt", "unsent\n")
    before = snapshot(root)

    hook = root / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(exist_ok=True)
    # $3 is 1 when a branch or commit was checked out (not for `git restore` of files)
    hook.write_text(f'#!/bin/sh\nif [ "$3" = 1 ]; then git update-ref refs/heads/master {first}; fi\n', encoding="utf-8")
    os.chmod(hook, 0o755)
    with pytest.raises(CdlbibError) as err:
        library.restore(made, ws)
    os.unlink(hook)
    pre = library.backups()[0]
    message = str(err.value)
    assert f"branch master is no longer at {last[:8]}" in message
    assert str(pre.path) in message and f"`cdlbib update --undo {pre.stamp}` puts them back" in message
    assert git("rev-parse", "master", cwd=root) == first               # left where the other party put it
    assert git("rev-parse", "HEAD", cwd=root) == middle and snapshot(root)["branch"] is None
    assert hashes(pre.path / "files", KEPT) == {name: before["files"][name]      # the user's edits are in the named backup
                                                for name in ("cdl.bib", "verification/unsent.txt")}
    assert (pre.branch, pre.commit) == ("master", last)

    api.undo_update()                                                   # what the message says to do
    assert snapshot(root) == before


def test_an_untracked_folder_where_the_commit_has_a_file_is_a_refusal(managed):
    home, upstream, ws = managed
    root = ws.root
    older = library.backup(ws)
    advance(upstream, "Adds a file named extra", extra="a file upstream\n")
    fast_forward(root)
    newer = library.backup(ws)
    library.restore(older, ws)
    assert not (root / "extra").exists()
    write(root, "extra/mine.txt", "an untracked folder of my own\n")
    write(root, "cdl.bib", "% unsent edit\n")
    write(root, "verification/unsent.txt", "unsent\n")
    before, listed = whole_clone(root), [b.stamp for b in library.backups()]
    with pytest.raises(CdlbibError) as err:
        library.restore(newer, ws)
    assert "would overwrite extra/mine.txt" in str(err.value) and "Nothing was changed" in str(err.value)
    assert whole_clone(root) == before and [b.stamp for b in library.backups()] == listed
    assert changed_paths(root, *KEPT) == {"cdl.bib": " M", "verification/unsent.txt": "??"}


def test_a_restore_refuses_a_pre_undo_backup_that_does_not_hold_the_files_on_disk(managed):
    _, upstream, ws = managed
    root = ws.root
    made = library.backup(ws)
    stale = library.backup(ws)
    write(root, "cdl.bib", "% written after the pre-undo backup was taken\n")
    before = snapshot(root)
    with pytest.raises(CdlbibError, match="changed after its backup was taken"):
        library.restore(made, ws, into=stale)
    assert snapshot(root) == before


# --- undo ------------------------------------------------------------------------------------

def test_undo_twice_returns_to_the_state_before_the_first_undo(managed, capsys):
    home, upstream, ws = managed
    root = ws.root
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% unsent\n")
    write(root, "verification/unsent.jsonl", "{}\n")
    before_update = snapshot(root)
    made = library.backup(ws)
    advance(upstream, "An update", **{"verification/from-update.txt": "upstream\n"})
    fast_forward(root)
    write(root, "verification/after the update.txt", "later work\n")
    after_update = snapshot(root)

    assert api.backups() == [made]
    restored = api.undo_update()
    assert restored == made and snapshot(root) == before_update
    assert len(api.backups()) == 2 and api.backups()[1] == made

    again = api.undo_update()
    assert again == api.backups()[1] and again != made
    assert snapshot(root) == after_update                              # the undo was undone
    assert len(api.backups()) == 3
    api.undo_update()
    assert snapshot(root) == before_update
    assert capsys.readouterr() == ("", "")                             # the api never prints


def test_undo_with_no_backup_is_an_error_and_changes_nothing(managed):
    home, _, ws = managed
    write(ws.root, "cdl.bib", "% unsent\n")
    before, others = snapshot(ws.root), outside(ws.root)
    with pytest.raises(CdlbibError, match="No backup has been made yet"):
        api.undo_update()
    with pytest.raises(CdlbibError, match="No backup has been made yet"):
        library.restore(None, ws)
    assert (snapshot(ws.root), outside(ws.root)) == (before, others)
    assert api.backups() == [] and not (home / "backups").exists()


def test_update_conflict_is_a_cdlbib_error():
    assert issubclass(UpdateConflict, CdlbibError)


# --- the command -----------------------------------------------------------------------------

def test_update_undo_and_list_on_the_command_line(managed, tmp_path):
    home, upstream, ws = managed
    root = ws.root
    elsewhere = tmp_path / "some other folder"                          # the command acts on the managed library
    own = elsewhere / "own library"                                     # whatever folder it is run from
    (own / "verification").mkdir(parents=True)
    (own / "cdl.bib").write_text("% my own library\n", encoding="utf-8")

    none = cdlbib("update", "--list", cwd=own)
    assert (none.returncode, none.stdout, none.stderr) == (0, f"no backups of {root} yet\n", "")
    refused = cdlbib("update", "--undo", cwd=own)
    assert (refused.returncode, refused.stdout) == (1, "")
    assert refused.stderr == f"No backup has been made yet of {root}, so there is nothing to undo.\n"

    write(root, "cdl.bib", conftest.ZOLL90 + "\n% unsent\n")
    before = snapshot(root)
    made = library.backup(ws)
    advance(upstream, "An update", **{"verification/from-update.txt": "upstream\n"})
    fast_forward(root)
    after = snapshot(root)

    when = made.taken_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    listed = cdlbib("update", "--list", cwd=own)
    assert listed.returncode == 0 and listed.stderr == ""
    assert listed.stdout.splitlines() == [
        f"1 backup of {root}, newest first (kept in {home.resolve() / 'backups'}):",
        f"  {made.stamp}  {when}  branch master at {before['commit'][:8]}, 1 changed file",
        "`cdlbib update --undo` puts the library back as it was at the newest one; "
        "`cdlbib update --undo STAMP` at the one named."]

    undone = cdlbib("update", "--undo", cwd=own)
    pre = library.backups()[0]
    assert undone.returncode == 0 and undone.stderr == "", undone.stdout + undone.stderr
    assert undone.stdout.splitlines() == [
        f"restored backup {made.stamp} ({when}): branch master at {before['commit'][:8]}, 1 changed file",
        f"the library as it was just before is backup {pre.stamp}",
        "run `cdlbib update --undo` again to return to it"]
    assert snapshot(root) == before
    assert (own / "cdl.bib").read_text(encoding="utf-8") == "% my own library\n" and not (own / ".git").exists()

    assert cdlbib("update", "--undo", cwd=own).returncode == 0
    assert snapshot(root) == after
    assert len(cdlbib("update", "--list", cwd=own).stdout.splitlines()) == 5      # three backups now

    both = cdlbib("update", "--undo", "--list", cwd=own)
    assert both.returncode == 2 and "--list and --undo cannot be used together" in both.stderr
    assert snapshot(root) == after

    # a named backup: the oldest of the three, which is the state before the update
    named = cdlbib("update", "--undo", made.stamp, cwd=own)
    assert named.returncode == 0 and named.stdout.splitlines()[0].startswith(f"restored backup {made.stamp} ("), named.stderr
    assert snapshot(root) == before
    assert cdlbib("update", "--undo", cwd=own).returncode == 0          # and back
    assert snapshot(root) == after and len(library.backups()) == 5

    kept = [b.stamp for b in library.backups()]
    unknown = cdlbib("update", "--undo", "20000101T000000.000000Z", cwd=own)
    assert (unknown.returncode, unknown.stdout) == (1, "")
    assert unknown.stderr == (f"There is no backup 20000101T000000.000000Z of {root}; `cdlbib update --list` shows "
                              "the backups there are. Nothing was changed.\n")
    assert snapshot(root) == after and [b.stamp for b in library.backups()] == kept
    with pytest.raises(CdlbibError, match="There is no backup nonsense of"):
        api.undo_update("nonsense")
    stray = cdlbib("update", made.stamp, cwd=own)
    assert stray.returncode == 2 and "a backup is named only with --undo" in stray.stderr
    assert snapshot(root) == after and [b.stamp for b in library.backups()] == kept

    bare = cdlbib("update", cwd=own)                                    # nothing new upstream: nothing changes
    assert (bare.returncode, bare.stderr) == (0, "")
    assert bare.stdout == f"the bibliography in {root} is up to date\n"
    assert snapshot(root) == after and [b.stamp for b in library.backups()] == kept


def test_update_with_no_managed_library_says_so_and_creates_nothing(tmp_path, monkeypatch):
    home = tmp_path / "no library here"
    monkeypatch.setenv("CDLBIB_HOME", str(home))
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(tmp_path / "nowhere.git"))
    monkeypatch.delenv("CDLBIB_LIBRARY", raising=False)
    workspace.select_library(None)
    empty = tmp_path / "empty"
    empty.mkdir()
    for flag in ("--undo", "--list"):
        out = cdlbib("update", flag, cwd=empty)
        assert (out.returncode, out.stdout) == (1, ""), out.stdout + out.stderr
        assert out.stderr == (f"cdlbib has not downloaded a library yet (it would be at {home / 'library'}), "
                              "so there are no backups and nothing to undo.\n")
    bare = cdlbib("update", cwd=empty)
    assert (bare.returncode, bare.stdout) == (1, ""), bare.stdout + bare.stderr
    assert bare.stderr == (f"cdlbib has not downloaded a library yet (it would be at {home / 'library'}), "
                           "so there is nothing to update.\n")
    with pytest.raises(CdlbibError, match="so there is nothing to update"):
        api.update(force=True)
    for call in (api.backups, api.undo_update):
        with pytest.raises(CdlbibError, match="has not downloaded a library yet"):
            call()
    assert not home.exists()
    conftest.no_real_library_touched()


def test_update_help_touches_nothing(tmp_path):
    home = tmp_path / "home"
    out = cdlbib("update", "--help", cwd=tmp_path, CDLBIB_HOME=str(home), CDLBIB_UPSTREAM=str(tmp_path / "nowhere.git"))
    assert out.returncode == 0 and "--undo" in out.stdout and "--list" in out.stdout
    assert not home.exists()


# --- fix round 1 -----------------------------------------------------------------------------

def whole_clone(root):
    """Everything in the clone a refusal must leave alone: the two paths, every other file
    (ignored ones included), and every ref."""
    return snapshot(root), outside(root), git("for-each-ref", cwd=root), changed_paths(root, ".")


def test_an_ignored_file_of_the_users_is_never_overwritten_by_an_undo(managed):
    """The recorded commit tracks was-tracked.log; the update deletes it; *.log is ignored;
    the user then writes a file of their own by that name. git would overwrite an ignored
    file on a switch without being asked: the undo must refuse instead, before anything changes."""
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "A tracked log and an ignore rule", **{"was-tracked.log": "upstream's log\n", ".gitignore": "*.log\n"})
    fast_forward(root)
    made = library.backup(ws)
    advance(upstream, "The log is no longer tracked", **{"was-tracked.log": None})
    fast_forward(root)
    write(root, "was-tracked.log", "the user's own notes, ignored by git\n")
    write(root, "cdl.bib", "% unsent edit\n")
    assert changed_paths(root, ".") == {"cdl.bib": " M"}               # git status does not mention the ignored file
    before, listed = whole_clone(root), [b.path.name for b in library.backups()]

    refusal = ""
    try:
        api.undo_update()
    except CdlbibError as exc:
        refusal = str(exc)
    assert (root / "was-tracked.log").read_text(encoding="utf-8") == "the user's own notes, ignored by git\n"
    assert "was-tracked.log" in refusal and "Nothing was changed" in refusal
    assert whole_clone(root) == before
    assert [b.path.name for b in library.backups()] == listed == [made.path.name]


def test_ten_backups_and_a_refused_undo_leave_the_same_ten(managed):
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "A README", README="first\n")
    fast_forward(root)
    for _ in range(10):
        library.backup(ws)
    advance(upstream, "README changes", README="second\n")
    fast_forward(root)
    write(root, "README", "second, with my own note\n")
    ten = [b.stamp for b in library.backups()]
    pins = git("for-each-ref", "refs/cdlbib", cwd=root)
    before = whole_clone(root)
    assert len(ten) == 10
    for attempt in (api.undo_update, lambda: api.undo_update(ten[-1]), lambda: library.restore(library.backups()[-1], ws)):
        with pytest.raises(CdlbibError, match="would overwrite README"):
            attempt()
        assert [b.stamp for b in library.backups()] == ten              # none pruned, none added
        assert sorted(p.name for p in (home / "backups").iterdir()) == sorted(ten)
        assert whole_clone(root) == before and git("for-each-ref", "refs/cdlbib", cwd=root) == pins


def test_after_a_failure_that_was_put_back_the_next_undo_restores_the_backup_that_was_meant(managed):
    """The switch is refused for real: a hook writes an ignored file, at a path the recorded
    commit tracks, after the checks have passed. The library is put back and checked, the
    copy taken for the attempt is removed, and the next undo reaches the intended backup."""
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "A tracked log and an ignore rule", **{"was-tracked.log": "upstream's log\n", ".gitignore": "*.log\n"})
    fast_forward(root)
    made = library.backup(ws)
    advance(upstream, "The log is no longer tracked", **{"was-tracked.log": None})
    fast_forward(root)
    write(root, "cdl.bib", "% unsent edit\n")
    write(root, "verification/unsent.txt", "unsent\n")
    before = whole_clone(root)

    hook = root / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(exist_ok=True)
    # $3 is 0 when files were checked out (the `git restore` of step b), 1 for a switch
    hook.write_text('#!/bin/sh\nif [ "$3" = 0 ]; then printf "written meanwhile" > was-tracked.log; fi\n', encoding="utf-8")
    os.chmod(hook, 0o755)
    for _ in range(3):                                                  # however often it is tried
        with pytest.raises(CdlbibError) as err:
            api.undo_update()
        assert "The library is as it was" in str(err.value) and "was-tracked.log" in str(err.value)
        assert (root / "was-tracked.log").read_text(encoding="utf-8") == "written meanwhile"
        os.unlink(root / "was-tracked.log")
        assert whole_clone(root) == before
        assert [b.stamp for b in library.backups()] == [made.stamp]     # the newest is still the one that was meant
    os.unlink(hook)

    assert api.undo_update() == made
    assert snapshot(root)["commit"] == made.commit and (root / "was-tracked.log").read_text(encoding="utf-8") == "upstream's log\n"
    assert hashes(library.backups()[0].path / "files", KEPT) == {name: before[0]["files"][name]
                                                                 for name in ("cdl.bib", "verification/unsent.txt")}


def test_the_recovery_command_of_a_stopped_restore_works_when_the_branch_is_not_at_an_upstream_commit(managed, tmp_path):
    """The branch has a local commit, and is moved meanwhile to another commit that is on no
    branch at all. The restore stops; the command its message gives restores the user's
    files, branch and commit; and the commit the branch was moved to is not lost."""
    home, upstream, ws = managed
    root = ws.root
    made = library.backup(ws)                                           # master at the first commit
    conftest._git("switch", "--quiet", "-c", "elsewhere", cwd=root)
    write(root, "cdl.bib", "% a commit on no branch\n")
    conftest._git("commit", "--quiet", "-m", "Stray", "--", "cdl.bib", cwd=root)
    stray = git("rev-parse", "HEAD", cwd=root)
    conftest._git("switch", "--quiet", "master", cwd=root)
    conftest._git("branch", "--quiet", "-D", "elsewhere", cwd=root)
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% local commit\n")
    conftest._git("commit", "--quiet", "-m", "Local", "--", "cdl.bib", cwd=root)
    local = git("rev-parse", "HEAD", cwd=root)
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% local commit\n% and unsent\n")
    write(root, "verification/unsent.txt", "unsent\n")
    before = snapshot(root)
    assert not git("branch", "--remotes", "--contains", local, cwd=root)

    hook = root / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f'#!/bin/sh\nif [ "$3" = 1 ]; then git update-ref refs/heads/master {stray}; fi\n', encoding="utf-8")
    os.chmod(hook, 0o755)
    with pytest.raises(CdlbibError) as err:
        library.restore(made, ws)
    os.unlink(hook)
    message = str(err.value)
    pre = library.backups()[0]
    assert f"branch master is no longer at {local[:8]}" in message
    command = re.search(r"`(cdlbib update --undo \S+)` puts them back", message).group(1)
    assert command == f"cdlbib update --undo {pre.stamp}" and str(pre.path) in message
    assert not (root / "verification/unsent.txt").exists() and git("rev-parse", "master", cwd=root) == stray

    empty = tmp_path / "empty"
    empty.mkdir()
    done = cdlbib(*command.split()[1:], cwd=empty)                      # exactly what the message says to run
    assert done.returncode == 0, done.stdout + done.stderr
    assert snapshot(root) == before and git("rev-parse", "master", cwd=root) == local
    assert git("for-each-ref", "--contains", stray, cwd=root)          # still kept, by a private ref
    conftest._git("reflog", "expire", "--expire=now", "--all", cwd=root)
    conftest._git("gc", "--quiet", "--prune=now", cwd=root)
    assert git("cat-file", "-t", stray, cwd=root) == "commit"


def test_a_library_on_a_send_branch_is_restored_to_that_branch(managed):
    home, upstream, ws = managed
    root = ws.root
    conftest._git("switch", "--quiet", "-c", "cdlbib/a-login/fix-zoll90", cwd=root)
    unsent_work(root)
    before = snapshot(root)
    made = library.backup(ws)
    assert (made.branch, made.has_bundle) == ("cdlbib/a-login/fix-zoll90", True)
    # as after a merged pull request: back on master, updated, the send branch still there but moved on
    conftest._git("restore", "--source=HEAD", "--staged", "--worktree", "--", "cdl.bib", cwd=root)
    shutil.rmtree(root / "verification" / "notes")
    conftest._git("switch", "--quiet", "master", cwd=root)
    advance(upstream, "An update", **{"verification/from-update.txt": "upstream\n", "README": "r\n"})
    fast_forward(root)
    write(root, "cdl.bib", "% work on master after the update\n")
    on_master = snapshot(root)

    assert api.undo_update() == made
    # master is not the backup's branch and no undo had moved it: it stays where the update put it
    assert snapshot(root) == dict(before, branches=dict(before["branches"], master=on_master["commit"]))
    api.undo_update()
    assert snapshot(root) == on_master


ODD = ["verification/with a space.txt", "verification/ünïcödé – naïve.txt", "verification/-leading-dash.txt",
       "verification/--also", "verification/a\nnewline.txt", "verification/dir with space/-x/é.txt"]


def test_odd_file_names_and_a_symbolic_link(managed):
    home, upstream, ws = managed
    root = ws.root
    for at, name in enumerate(ODD[:3]):                                 # some tracked, then edited; the rest untracked
        write(root, name, f"tracked {at}\n")
    conftest._git("add", "--", *ODD[:3], cwd=root)
    conftest._git("commit", "--quiet", "-m", "Odd names", cwd=root)
    write(root, ODD[0], "edited\n")
    os.unlink(root / ODD[1])
    for name in ODD[3:]:
        write(root, name, "untracked: " + name)
    os.symlink("with a space.txt", root / "verification/a link")
    os.symlink("no such target", root / "verification/dangling link")
    before = snapshot(root)
    assert set(ODD) - {ODD[1]} <= set(before["files"]) and before["files"]["verification/a link"] == "link:with a space.txt"
    made = library.backup(ws)
    assert os.readlink(made.path / "files/verification/a link") == "with a space.txt"      # copied as a link
    assert os.readlink(made.path / "files/verification/dangling link") == "no such target"
    assert made.deleted == [ODD[1]]

    conftest._git("restore", "--source=HEAD", "--staged", "--worktree", "--", "cdl.bib", "verification", cwd=root)
    for name in ODD[3:] + ["verification/a link", "verification/dangling link"]:
        os.unlink(root / name)
    write(root, "verification/-another", "made later\n")
    advance(upstream, "An update", README="r\n")
    assert snapshot(root) != before
    library.restore(made, ws)
    assert snapshot(root) == before
    assert (library.backups()[0].path / "files/verification/-another").read_text(encoding="utf-8") == "made later\n"


def folder_size(folder):
    return sum(os.lstat(Path(base) / name).st_size for base, _dirs, names in os.walk(folder) for name in names)


def test_a_backup_of_a_clean_library_is_tiny_and_still_restores_the_exact_commit(managed):
    home, upstream, ws = managed
    root = ws.root
    big = "".join(f"@article{{Key{n},\n\tTitle = {{Entry number {n}}},\n\tYear = {{2000}}}}\n\n" for n in range(40000))
    advance(upstream, "A library of realistic size", **{"cdl.bib": big, "verification/baseline.jsonl": big})
    fast_forward(root)
    before = snapshot(root)
    made = library.backup(ws)
    size, bib = folder_size(made.path), os.path.getsize(root / "cdl.bib")
    assert bib > 2_000_000 and size < 1000 and size < bib / 1000, (size, bib)
    assert sorted(p.name for p in made.path.rglob("*")) == ["files", "ref.json"]

    advance(upstream, "An update", **{"cdl.bib": big + "% more\n", "verification/baseline.jsonl": "replaced\n",
                                      "verification/new.txt": "new\n"})
    fast_forward(root)
    write(root, "cdl.bib", "% and an edit after the update\n")
    api.undo_update()
    assert snapshot(root) == before and (root / "cdl.bib").read_text(encoding="utf-8") == big
    edited = library.backups()[0]                                       # the pre-undo backup holds just the edited file
    assert folder_size(edited.path / "files") == len("% and an edit after the update\n")


# --- the daily check and the clean fast-forward ----------------------------------------------
#
# The time of the last check is written by the test (state.json); the clock is never replaced.
# "No fetch happened" is proved by an upstream that is not there: the bare repository is
# renamed away, the command must still succeed, and state.json must be byte-for-byte unchanged.

UTC = datetime.timezone.utc
HOUR = datetime.timedelta(hours=1)
MINUTE = datetime.timedelta(minutes=1)
CHOSEN = "chosen by: no library named or found; this is the copy cdlbib downloads and manages"


def checked(home, ago, tried=None):
    """Record that the upstream was last consulted ``ago`` before now (and, with ``tried``, that
    an automatic check failed that long ago); returns state.json's bytes."""
    now = datetime.datetime.now(UTC)
    library.write_state(library.State(now - ago, os.environ["CDLBIB_UPSTREAM"], None if tried is None else now - tried))
    return (home / "state.json").read_bytes()


def backup_names(home):
    return sorted(p.name for p in (home / "backups").iterdir()) if (home / "backups").exists() else []


def refs(root):
    return git("for-each-ref", "--format=%(refname) %(objectname)", cwd=root)


def empty_folder(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir(exist_ok=True)
    return folder


def updated_line(count, home):
    stamp = backup_names(home)[-1]
    return (f"updated the bibliography: {count} new commit{'' if count == 1 else 's'} (the library as it was is "
            f"backup {stamp}; `cdlbib update --undo` puts it back)")


def test_check_due_is_never_checked_a_day_or_more_or_a_time_in_the_future(managed):
    home, upstream, ws = managed
    now = datetime.datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

    def due(last):
        library.write_state(library.State(last, str(upstream)))
        return library.check_due(now)

    assert due(None) is True
    assert due(now - datetime.timedelta(hours=23, minutes=59)) is False
    assert due(now - datetime.timedelta(hours=24)) is True
    assert due(now - datetime.timedelta(days=30)) is True
    assert due(now + datetime.timedelta(minutes=5)) is True          # a clock that was wrong: check again
    assert due(now) is False
    (home / "state.json").write_text("{not json", encoding="utf-8")
    assert library.check_due(now) is True                            # corrupt: as never checked
    (home / "state.json").unlink()
    assert library.check_due(now) is True
    assert library.check_due() is True                               # the real clock, by default
    library.write_state(library.State(datetime.datetime.now(UTC), str(upstream)))
    assert library.check_due() is False


def test_checked_an_hour_ago_a_command_does_not_fetch(managed, tmp_path):
    home, upstream, ws = managed
    advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    state, before, known = checked(home, HOUR), snapshot(ws.root), refs(ws.root)
    upstream.rename(upstream.with_name("gone.git"))                  # contacting the upstream would fail
    for args in (("verify", "--no-citations"), ("where",), ("crossref", "status")):
        out = cdlbib(*args, cwd=empty_folder(tmp_path))
        assert "Traceback" not in out.stderr and "update" not in out.stderr, out.stderr
        assert out.returncode == (1 if args[0] == "crossref" else 0), out.stdout + out.stderr
    assert (home / "state.json").read_bytes() == state
    assert snapshot(ws.root) == before and refs(ws.root) == known and backup_names(home) == []
    assert library.update(ws) == library.UpdateResult("not_due")
    assert (home / "state.json").read_bytes() == state


def test_checked_25_hours_ago_a_command_fast_forwards_after_a_backup(managed, tmp_path):
    home, upstream, ws = managed
    root, old = ws.root, git("rev-parse", "HEAD", cwd=ws.root)
    advance(upstream, "First", **{"verification/new.txt": "new\n"})
    new = advance(upstream, "Second", **{"cdl.bib": conftest.ZOLL90 + "\n% from upstream\n"})
    before, started = snapshot(root), datetime.datetime.now(UTC)
    checked(home, 25 * HOUR)

    out = cdlbib("verify", "--no-citations", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and "looks good!" in out.stdout, out.stdout + out.stderr
    assert out.stderr.splitlines()[0] == updated_line(2, home)       # said before the command's own work
    assert "update" not in out.stdout
    assert git("rev-parse", "HEAD", cwd=root) == new and git("symbolic-ref", "--short", "HEAD", cwd=root) == "master"
    assert (root / "cdl.bib").read_text(encoding="utf-8").endswith("% from upstream\n")
    assert changed_paths(root, ".") == {}                            # a clean fast-forward
    saved = library.backups()
    assert len(saved) == 1 and (saved[0].branch, saved[0].commit, saved[0].changed) == ("master", old, [])
    assert started <= library.read_state().last_check <= datetime.datetime.now(UTC)

    again = cdlbib("where", cwd=empty_folder(tmp_path))                # checked a moment ago: nothing more happens
    assert (again.returncode, again.stderr) == (0, "") and len(library.backups()) == 1

    undone = cdlbib("update", "--undo", cwd=empty_folder(tmp_path))    # and the update is reversible
    assert undone.returncode == 0, undone.stderr
    assert snapshot(root) == before


def test_update_returns_what_it_did_and_never_prints(managed, capsys):
    home, upstream, ws = managed
    old = git("rev-parse", "HEAD", cwd=ws.root)
    new = advance(upstream, "One", **{"verification/new.txt": "new\n"})
    now = datetime.datetime(2031, 5, 6, 7, 8, 9, tzinfo=UTC)         # the time is the caller's
    checked(home, 25 * HOUR)
    result = library.update(ws, now=now)
    assert result.action == "updated" and result.new_commits == 1 and result.notes == []
    assert result.backup.commit == old and result.backup.stamp == backup_names(home)[0]
    assert result.message == updated_line(1, home)
    assert library.read_state() == library.State(now, str(upstream))
    assert git("rev-parse", "HEAD", cwd=ws.root) == new

    assert library.update(ws, now=now + 23 * HOUR).action == "not_due"
    nothing = library.update(ws, now=now + 24 * HOUR)
    assert nothing == library.UpdateResult("up_to_date", message=f"the bibliography in {ws.root} is up to date")
    assert library.read_state().last_check == now + 24 * HOUR and len(backup_names(home)) == 1

    forced = api.update(ws, force=True)                              # the front-end boundary; force ignores the day
    assert forced.action == "up_to_date" and len(backup_names(home)) == 1
    assert api.update(ws).action == "not_due"
    assert api.update().action == "not_due"                          # no workspace: the managed library
    assert capsys.readouterr() == ("", "")


def test_nothing_new_upstream_records_the_time_and_makes_no_backup(managed, tmp_path):
    home, upstream, ws = managed
    before, known, started = snapshot(ws.root), refs(ws.root), datetime.datetime.now(UTC)
    checked(home, 25 * HOUR)
    out = cdlbib("where", cwd=empty_folder(tmp_path))
    last = library.read_state().last_check
    assert (out.returncode, out.stderr) == (0, ""), out.stderr      # up to date is not worth a line
    assert out.stdout.splitlines() == [str(ws.root), CHOSEN, f"last update check: {last.strftime('%Y-%m-%d %H:%M UTC')}"]
    assert started <= last <= datetime.datetime.now(UTC)             # a fetch happened
    assert snapshot(ws.root) == before and refs(ws.root) == known and backup_names(home) == []


def test_offline_the_check_is_skipped_once_then_left_for_an_hour(managed, tmp_path):
    home, upstream, ws = managed
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    checked(home, 25 * HOUR)
    last, before = library.read_state().last_check, snapshot(ws.root)
    gone = upstream.with_name("gone.git")
    upstream.rename(gone)
    failed = (f"update check skipped: git fetch from {upstream} failed ('{upstream}' does not appear to be a git "
              f"repository); working with the copy in {ws.root}.")
    skipped = failed + " It will be tried again automatically in about an hour; `cdlbib update` tries now."

    started = datetime.datetime.now(UTC)
    out = cdlbib("verify", "--no-citations", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and "looks good!" in out.stdout, out.stdout + out.stderr
    assert out.stderr.splitlines()[0] == skipped
    assert [line for line in out.stderr.splitlines() if "update" in line] == [skipped]
    state = library.read_state()                                     # the attempt is recorded; the last check is not moved
    assert state.last_check == last and started <= state.last_attempt <= datetime.datetime.now(UTC)
    recorded = (home / "state.json").read_bytes()
    assert sorted(json.loads(recorded)) == ["last_attempt", "last_check", "upstream"]

    for _ in range(2):                                               # within the hour: no attempt, no line
        out = cdlbib("where", cwd=empty_folder(tmp_path))
        assert (out.returncode, out.stderr) == (0, ""), out.stderr
        assert (home / "state.json").read_bytes() == recorded
    assert library.update(ws) == library.UpdateResult("not_due")
    assert snapshot(ws.root) == before and backup_names(home) == []

    asked = cdlbib("update", cwd=empty_folder(tmp_path))               # asked for: tried whatever the hour says
    assert (asked.returncode, asked.stdout, asked.stderr) == (1, "", failed + " Run `cdlbib update` to try again.\n")
    assert (home / "state.json").read_bytes() == recorded            # a failed `cdlbib update` records nothing

    checked(home, 25 * HOUR, tried=61 * MINUTE)                      # an hour and a minute after the failed attempt
    out = cdlbib("where", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and out.stderr == skipped + "\n"
    assert library.read_state().last_attempt >= started

    gone.rename(upstream)                                            # back online, still within the hour:
    out = cdlbib("where", cwd=empty_folder(tmp_path))                  # the automatic check waits,
    assert (out.returncode, out.stderr) == (0, "") and snapshot(ws.root) == before
    asked = cdlbib("update", cwd=empty_folder(tmp_path))               # `cdlbib update` does not
    assert (asked.returncode, asked.stdout, asked.stderr) == (0, updated_line(1, home) + "\n", "")
    assert git("rev-parse", "HEAD", cwd=ws.root) == new
    assert sorted(json.loads((home / "state.json").read_text(encoding="utf-8"))) == ["last_check", "upstream"]


def test_a_state_file_from_before_the_attempt_field_reads_as_no_failed_attempt(managed):
    home, upstream, ws = managed
    when = datetime.datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
    for extra in ("", ', "last_attempt": null', ', "last_attempt": "soon"', ', "last_attempt": 7'):
        (home / "state.json").write_text('{"last_check": "%s", "upstream": "%s"%s}' % (when.isoformat(), upstream, extra),
                                         encoding="utf-8")
        assert library.read_state() == library.State(when, str(upstream), None), extra
    tried = when + 3 * HOUR
    library.write_state(library.State(when, str(upstream), tried))
    assert library.read_state() == library.State(when, str(upstream), tried)
    now = when + 26 * HOUR                                           # due by the day; the hour decides
    library.write_state(library.State(when, str(upstream), now - 59 * MINUTE))
    assert library.check_due(now) is True and library.update(ws, now=now).action == "not_due"
    library.write_state(library.State(when, str(upstream), now - 60 * MINUTE))
    assert library.update(ws, now=now).action == "up_to_date"
    library.write_state(library.State(when, str(upstream), now + 5 * MINUTE))   # an attempt "in the future": try
    assert library.update(ws, now=now).action == "up_to_date"
    assert library.read_state() == library.State(now, str(upstream), None)


def test_a_stalling_upstream_costs_a_command_the_short_timeout_once(managed, tmp_path):
    """A real stall: git's ext transport runs `sleep` as the remote, which never answers
    (enabled in these commands' environment only). The first command gives it 15 seconds;
    the next one does not try."""
    home, upstream, ws = managed
    checked(home, 25 * HOUR)
    conftest._git("config", "remote.origin.url", "ext::sleep 62", cwd=ws.root)
    env = {"GIT_ALLOW_PROTOCOL": "ext", "CDLBIB_UPSTREAM": "ext::sleep 62"}
    assert library.AUTO_FETCH_TIMEOUT == 15 and library.RETRY_AFTER == 3600 and library.FETCH_TIMEOUT == 120
    started = time.monotonic()
    with helpers_seen("sleep 62$") as helpers:
        out = cdlbib("where", cwd=empty_folder(tmp_path), **env)
    took = time.monotonic() - started
    assert out.returncode == 0 and out.stderr == (
        f"update check skipped: ext::sleep 62 did not answer within 15 seconds; working with the copy in {ws.root}. "
        "It will be tried again automatically in about an hour; `cdlbib update` tries now.\n")
    assert 15 <= took < 40, took
    recorded = (home / "state.json").read_bytes()
    started = time.monotonic()
    out = cdlbib("where", cwd=empty_folder(tmp_path), **env)
    assert (out.returncode, out.stderr) == (0, "") and time.monotonic() - started < 10
    assert (home / "state.json").read_bytes() == recorded
    time.sleep(0.5)
    assert helpers, "the stalled transport was never seen running: this guard would prove nothing"
    assert still_running(helpers) == [], "the stalled transport was left running"


def test_a_corrupt_state_file_is_never_checked_so_the_command_checks(managed, tmp_path):
    home, upstream, ws = managed
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    (home / "state.json").write_text('{"last_check": "yesterday-ish", "upstream"', encoding="utf-8")
    out = cdlbib("where", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and out.stderr == updated_line(1, home) + "\n", out.stderr
    assert git("rev-parse", "HEAD", cwd=ws.root) == new
    state = json.loads((home / "state.json").read_text(encoding="utf-8"))
    assert state["upstream"] == str(upstream) and datetime.datetime.fromisoformat(state["last_check"])


def test_a_last_check_in_the_future_is_checked_again(managed, tmp_path):
    home, upstream, ws = managed
    checked(home, -72 * HOUR)
    out = cdlbib("where", cwd=empty_folder(tmp_path))
    assert (out.returncode, out.stderr) == (0, "")
    assert library.read_state().last_check <= datetime.datetime.now(UTC)


def test_two_commands_starting_together_make_one_update(managed, tmp_path):
    home, upstream, ws = managed
    old = git("rev-parse", "HEAD", cwd=ws.root)
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    checked(home, 25 * HOUR)
    empty = empty_folder(tmp_path)
    both = [subprocess.Popen([CDLBIB, "where"], cwd=empty, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(4)]
    done = [p.communicate(timeout=120) + (p.returncode,) for p in both]
    for out, err, code in done:
        assert code == 0 and out.splitlines()[:2] == [str(ws.root), CHOSEN], out + err
    said = [line for _, err, _ in done for line in err.splitlines()]
    assert [line for line in said if line != library.WAITING] == [updated_line(1, home)]   # one command updated;
    assert said.count(library.WAITING) <= 3                          # the others at most said that they waited
    saved = library.backups()
    assert len(saved) == 1 and saved[0].commit == old                # one backup, of the state before
    assert git("rev-parse", "HEAD", cwd=ws.root) == new and changed_paths(ws.root, ".") == {}
    assert git("reflog", "--format=%gs", "HEAD", cwd=ws.root).splitlines()[0].endswith(": Fast-forward")
    assert sum(line.endswith(": Fast-forward") for line in git("reflog", "--format=%gs", "HEAD", cwd=ws.root).splitlines()) == 1
    state = json.loads((home / "state.json").read_text(encoding="utf-8"))   # whole, valid, and no temporary file left
    assert sorted(state) == ["last_check", "upstream"] and datetime.datetime.fromisoformat(state["last_check"])
    assert sorted(p.name for p in home.iterdir()) == ["backups", "library", "lock", "state.json"]


def test_a_command_that_waited_for_the_lock_sees_the_fresh_check_and_does_not_fetch(managed, tmp_path):
    """The second of two commands: it found the check due, waited for the lock, and by then
    the first had recorded its check. It must not contact the upstream (which is gone)."""
    import fcntl
    home, upstream, ws = managed
    checked(home, 25 * HOUR)
    with open(home / "lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        other = subprocess.Popen([CDLBIB, "where"], cwd=empty_folder(tmp_path), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        time.sleep(4)
        waiting = other.poll() is None
        state = checked(home, 0 * HOUR)                              # what the first command recorded
        upstream.rename(upstream.with_name("gone.git"))
        fcntl.flock(held, fcntl.LOCK_UN)
    out, err = other.communicate(timeout=120)
    assert waiting, "the command did not wait for the lock"
    assert other.returncode == 0 and err == library.WAITING + "\n", err      # it said that it was waiting
    assert library.WAITING == "waiting for another cdlbib to finish checking the bibliography for updates ..."
    assert (home / "state.json").read_bytes() == state and backup_names(home) == []


def clone_of(upstream, folder):
    conftest._git("clone", "--quiet", str(upstream), str(folder), cwd=upstream.parent)
    return folder


@pytest.mark.parametrize("how", ["--library", "CDLBIB_LIBRARY", "the current folder", "a folder below it", "a named file"])
def test_the_users_own_library_is_never_fetched_backed_up_or_recorded(managed, tmp_path, how):
    """The managed library exists, its check is long overdue and both upstreams have something
    new; a command on the user's own clone contacts nothing and writes nothing."""
    home, upstream, ws = managed
    theirs = conftest.build_upstream(tmp_path / "their upstream")
    own = clone_of(theirs, tmp_path / "own clone")
    (own / "sub").mkdir()
    for bare in (upstream, theirs):
        advance(bare, "Something new", **{"verification/new.txt": "new\n"})
    state = checked(home, 30 * 24 * HOUR)
    before = (snapshot(own), refs(own), snapshot(ws.root), refs(ws.root))
    for bare in (upstream, theirs):
        bare.rename(bare.with_name("gone.git"))
    args, cwd, env = ("where",), empty_folder(tmp_path), {}
    if how == "--library":
        args = ("--library", str(own), "where")
    elif how == "CDLBIB_LIBRARY":
        env = {"CDLBIB_LIBRARY": str(own)}
    elif how == "the current folder":
        cwd = own
    elif how == "a folder below it":
        cwd = own / "sub"
    else:
        args = ("where", "--fname", str(own / "cdl.bib"))
    for command in (args, tuple(a if a != "where" else "verify" for a in args) + ("--no-citations",)):
        out = cdlbib(*command, cwd=cwd, **env)
        assert out.returncode == 0, out.stdout + out.stderr
        assert not [word for word in ("update", "skipped", "note:", "Traceback") if word in out.stderr], out.stderr
        assert str(ws.root) not in out.stdout and (command[-1] == "--no-citations" or str(own.resolve()) in out.stdout)
    assert (snapshot(own), refs(own), snapshot(ws.root), refs(ws.root)) == before
    assert (home / "state.json").read_bytes() == state and backup_names(home) == []
    assert not (own / ".git" / "FETCH_HEAD").exists() and not (ws.root / ".git" / "FETCH_HEAD").exists()
    with pytest.raises(CdlbibError, match="Only the library cdlbib manages"):
        api.update(Workspace(own), force=True)
    assert refs(own) == before[1] and (home / "state.json").read_bytes() == state


def test_help_and_version_never_check(managed, tmp_path):
    home, upstream, ws = managed
    state, known = checked(home, 25 * HOUR), refs(ws.root)
    upstream.rename(upstream.with_name("gone.git"))
    for args in (("--help",), ("--version",), ("verify", "--help"), ("where", "--help"), ("update", "--help"),
                 ("crossref", "--help"), ("crossref", "status", "--help"), ("update", "--list")):
        out = cdlbib(*args, cwd=empty_folder(tmp_path))
        assert (out.returncode, out.stderr) == (0, ""), out.stdout + out.stderr
    assert (home / "state.json").read_bytes() == state and refs(ws.root) == known and backup_names(home) == []
    assert not (ws.root / ".git" / "FETCH_HEAD").exists()


def left_alone(count, why, then):
    return (f"a newer version of the bibliography is available ({count} new commit{'' if count == 1 else 's'}), "
            f"but {why}; nothing was changed. {then}")


@pytest.mark.parametrize("state", ["an edit", "an untracked file", "a staged edit", "a local commit", "a send branch",
                                   "no branch", "an ignored file in the way", "a changed file in the way",
                                   "an ignored file under verification in the way"])
def test_anything_but_a_clean_default_branch_is_left_alone_with_a_line(managed, tmp_path, state):
    home, upstream, ws = managed
    root = ws.root
    (root / ".git" / "info" / "exclude").write_text("notes.txt\nverification/local.txt\n", encoding="utf-8")
    advance(upstream, "Four files", **{"verification/new.txt": "new\n", "notes.txt": "upstream's notes\n",
                                       "README.md": "upstream's readme\n", "verification/local.txt": "upstream's\n"})
    send, switch = "Run `cdlbib update` in a terminal to choose what to do.", f"To update, run `git -C {shlex.quote(str(root))} switch master`, then `cdlbib update`."
    asks = state in ("an edit", "an untracked file", "a staged edit", "a local commit")     # unsent work: the user decides
    move = "Move that file out of the way, then run `cdlbib update`."
    count = 1
    if state == "an edit":
        write(root, "cdl.bib", conftest.ZOLL90 + "\n% mine\n")
        why, then = "these files have changes that have not been sent: cdl.bib", send
    elif state == "an untracked file":
        write(root, "verification/mine.txt", "mine\n")
        why, then = "these files have changes that have not been sent: verification/mine.txt", send
    elif state == "a staged edit":
        write(root, "cdl.bib", conftest.ZOLL90 + "\n% mine\n")
        conftest._git("add", "cdl.bib", cwd=root)
        why, then = "these files have changes that have not been sent: cdl.bib", send
    elif state == "a local commit":
        write(root, "cdl.bib", conftest.ZOLL90 + "\n% mine\n")
        conftest._git("commit", "--quiet", "-am", "Mine", cwd=root)
        why, then = "the library has 1 commit that the upstream does not have", send
    elif state == "a send branch":
        conftest._git("switch", "--quiet", "-c", "cdlbib/someone/a-change", cwd=root)
        why, then = "the library is on branch cdlbib/someone/a-change, not master", switch
    elif state == "no branch":
        conftest._git("switch", "--quiet", "--detach", cwd=root)
        why, then = "the library is not on a branch", switch
    elif state == "an ignored file in the way":
        write(root, "notes.txt", "MY NOTES\n")
        why, then = "updating would overwrite your own notes.txt", move
    elif state == "a changed file in the way":
        write(root, "README.md", "MY README\n")
        why, then = "updating would overwrite your own README.md", move
    else:
        write(root, "verification/local.txt", "MINE, AND IGNORED\n")     # a backup would hold it; git would overwrite it
        why, then = "updating would overwrite your own verification/local.txt", move
    def everything():       # every file (ignored ones too), what git calls changed, and the refs that are the user's
        return snapshot(root), outside(root), changed_paths(root, "."), git("for-each-ref", "refs/heads", "refs/cdlbib", cwd=root)

    before, started = everything(), datetime.datetime.now(UTC)
    checked(home, 25 * HOUR)

    out = cdlbib("where", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and out.stderr == left_alone(count, why, then) + "\n", out.stderr
    assert everything() == before and backup_names(home) == []
    assert started <= library.read_state().last_check                # checked: not asked again until tomorrow
    assert cdlbib("where", cwd=empty_folder(tmp_path)).stderr == ""

    asked = cdlbib("update", cwd=empty_folder(tmp_path))               # asked for: said again, still nothing changed
    if asks:                                                          # and nobody can be asked what to do: exit 1
        assert (asked.returncode, asked.stdout, asked.stderr) == (1, "", left_alone(count, why, then) + "\n")
        with pytest.raises(UpdateNeedsDecision):
            library.update(ws, force=True)
    else:
        assert (asked.returncode, asked.stdout, asked.stderr) == (0, left_alone(count, why, then) + "\n", "")
        result = library.update(ws, force=True)
        assert (result.action, result.new_commits, result.backup, result.message) == ("left_alone", 1, None, left_alone(1, why, then))
    assert everything() == before and backup_names(home) == []


def test_a_fast_forward_that_git_refuses_changes_nothing_and_keeps_no_backup(managed, tmp_path):
    """git itself says no after the backup was taken (another git command holds the index):
    the library is checked to be as it was, the backup of it is not kept, and it is said."""
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    before = snapshot(root), outside(root), git("for-each-ref", "refs/heads", "refs/cdlbib", cwd=root)
    checked(home, 25 * HOUR)
    (root / ".git" / "index.lock").write_text("", encoding="utf-8")
    result = library.update(ws)
    (root / ".git" / "index.lock").unlink()
    assert result.action == "left_alone" and result.backup is None and result.new_commits == 1
    assert result.message.startswith("a newer version of the bibliography is available (1 new commit), but git could "
                                     "not fast-forward the library (")
    assert "index.lock" in result.message
    assert result.message.endswith("; nothing was changed. Run `cdlbib update` to try again.")
    state = library.read_state()             # a failed attempt, not a completed check: tried again in an hour, not a day
    assert datetime.datetime.now(UTC) - state.last_check > 24 * HOUR and state.last_attempt is not None
    assert library.update(ws).action == "not_due"
    assert (snapshot(root), outside(root), git("for-each-ref", "refs/heads", "refs/cdlbib", cwd=root)) == before
    assert backup_names(home) == [] and changed_paths(root, ".") == {}
    assert library.update(ws, now=datetime.datetime.now(UTC) + 61 * MINUTE).action == "updated"   # an hour later it goes through
    assert library.read_state().last_attempt is None


def test_files_of_the_users_that_the_update_does_not_touch_stay_as_they_are(managed, tmp_path):
    home, upstream, ws = managed
    root = ws.root
    (root / ".git" / "info" / "exclude").write_text("notes.txt\n.bibcheck/\n", encoding="utf-8")
    write(root, "notes.txt", "MY NOTES\n")                            # ignored, outside the two paths
    write(root, "scratch/todo.txt", "untracked\n")                    # untracked, outside the two paths
    write(root, ".bibcheck/cache.txt", "cache\n")
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    mine = outside(root)
    checked(home, 25 * HOUR)
    out = cdlbib("where", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and out.stderr == updated_line(1, home) + "\n", out.stderr
    assert git("rev-parse", "HEAD", cwd=root) == new and outside(root) == mine


def test_cdlbib_update_checks_now_and_always_says_what_happened(managed, tmp_path):
    home, upstream, ws = managed
    root = ws.root
    own = tmp_path / "own library"                                   # run from the user's own library:
    (own / "verification").mkdir(parents=True)                        # it is the managed one that is updated
    (own / "cdl.bib").write_text("% my own library\n", encoding="utf-8")
    state = checked(home, HOUR)                                      # checked an hour ago: `update` checks anyway

    out = cdlbib("update", cwd=own)
    assert (out.returncode, out.stdout, out.stderr) == (0, f"the bibliography in {root} is up to date\n", "")
    assert (home / "state.json").read_bytes() != state and backup_names(home) == []

    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    before = snapshot(root)
    out = cdlbib("update", cwd=own)
    assert (out.returncode, out.stdout, out.stderr) == (0, updated_line(1, home) + "\n", "")
    assert git("rev-parse", "HEAD", cwd=root) == new and len(backup_names(home)) == 1

    state = (home / "state.json").read_bytes()
    gone = upstream.with_name("gone.git")
    upstream.rename(gone)
    out = cdlbib("update", cwd=own)                                   # asked for and not possible: exit 1
    assert (out.returncode, out.stdout) == (1, "")
    assert out.stderr == (f"update check skipped: git fetch from {upstream} failed ('{upstream}' does not appear to "
                          f"be a git repository); working with the copy in {root}. Run `cdlbib update` to try again.\n")
    assert (home / "state.json").read_bytes() == state and len(backup_names(home)) == 1
    gone.rename(upstream)

    assert cdlbib("update", "--undo", cwd=own).returncode == 0
    assert snapshot(root) == before
    assert (own / "cdl.bib").read_text(encoding="utf-8") == "% my own library\n" and not (own / ".git").exists()


def test_a_state_file_that_cannot_be_written_is_a_note_and_the_check_runs_with_every_command(managed, tmp_path):
    home, upstream, ws = managed
    (home / "state.json").unlink()
    (home / "state.json").mkdir()                                     # a folder where the file belongs
    note = (f"note: the time of the update check could not be recorded in {home / 'state.json'} (Is a directory); "
            "the check will run again with the next command")
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    out = cdlbib("verify", "--no-citations", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and "looks good!" in out.stdout, out.stdout + out.stderr
    assert out.stderr.splitlines()[:2] == [note, updated_line(1, home)]
    assert git("rev-parse", "HEAD", cwd=ws.root) == new

    newer = advance(upstream, "More", **{"verification/more.txt": "more\n"})
    out = cdlbib("where", cwd=empty_folder(tmp_path))                 # the very next command checks again
    assert out.returncode == 0 and out.stderr.splitlines() == [note, updated_line(1, home)]
    assert out.stdout.splitlines()[2] == "last update check: never"
    assert git("rev-parse", "HEAD", cwd=ws.root) == newer and len(backup_names(home)) == 2
    out = cdlbib("where", cwd=empty_folder(tmp_path))                 # nothing new: only the note
    assert out.returncode == 0 and out.stderr.splitlines() == [note]
    assert sorted(p.name for p in home.iterdir()) == ["backups", "library", "lock", "state.json"]


def test_a_stalled_fetch_times_out_and_the_check_is_skipped(managed, monkeypatch):
    """In process, with only the times allowed changed (module constants): the automatic check
    uses the short one, `cdlbib update` the long one."""
    import fcntl
    home, upstream, ws = managed
    checked(home, 25 * HOUR)
    last, before = library.read_state().last_check, snapshot(ws.root)
    conftest._git("config", "remote.origin.url", "ext::sleep 61", cwd=ws.root)
    monkeypatch.setenv("CDLBIB_UPSTREAM", "ext::sleep 61")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "ext")
    monkeypatch.setattr(library, "AUTO_FETCH_TIMEOUT", 2)
    monkeypatch.setattr(library, "FETCH_TIMEOUT", 4)
    started = time.monotonic()
    with helpers_seen("sleep 61$") as helpers:
        result = library.update(ws)
    assert time.monotonic() - started < 30
    assert result.action == "skipped_offline" and result.message == (
        f"update check skipped: ext::sleep 61 did not answer within 2 seconds; working with the copy in {ws.root}. "
        "It will be tried again automatically in about an hour; `cdlbib update` tries now.")
    state = library.read_state()
    assert state.last_check == last and state.last_attempt is not None
    recorded = (home / "state.json").read_bytes()
    with helpers_seen("sleep 61$") as more:
        forced = library.update(ws, force=True)
    helpers |= more
    assert forced.action == "skipped_offline" and forced.message == (
        f"update check skipped: ext::sleep 61 did not answer within 4 seconds; working with the copy in {ws.root}. "
        "Run `cdlbib update` to try again.")
    assert (home / "state.json").read_bytes() == recorded
    assert snapshot(ws.root) == before and backup_names(home) == []
    time.sleep(0.5)
    assert helpers, "the stalled transport was never seen running: this guard would prove nothing"
    assert still_running(helpers) == [], "the stalled transport was left running"
    with open(home / "lock", "a") as lock:                           # and the lock is free again
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_the_update_needs_no_git_identity_and_ignores_the_users_git_settings(managed, tmp_path):
    """An empty HOME with no git identity, and a global git config that asks for merge
    commits, autostash and rebasing pulls: the update is still one fast-forward."""
    home, upstream, ws = managed
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    checked(home, 25 * HOUR)
    bare_home = tmp_path / "bare home"
    bare_home.mkdir()
    (bare_home / ".gitconfig").write_text("[merge]\n\tff = false\n\tautoStash = true\n[pull]\n\trebase = true\n"
                                          "[rebase]\n\tautoStash = true\n[fetch]\n\tprune = true\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in ("EMAIL", "XDG_CONFIG_HOME")}
    env.update(HOME=str(bare_home), GIT_CONFIG_NOSYSTEM="1")
    out = subprocess.run([CDLBIB, "where"], cwd=empty_folder(tmp_path), capture_output=True, text=True, env=env)
    assert out.returncode == 0 and out.stderr == updated_line(1, home) + "\n", out.stderr
    assert git("rev-parse", "HEAD", cwd=ws.root) == new               # the upstream's own commit: no merge commit
    assert git("reflog", "--format=%gs", "-1", "HEAD", cwd=ws.root).endswith(": Fast-forward")
    assert git("stash", "list", cwd=ws.root) == ""


def test_the_git_commands_of_an_update_are_the_ones_that_cannot_lose_work(managed, tmp_path, monkeypatch):
    """Every git command an update runs, as git itself traces them."""
    home, upstream, ws = managed
    advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    checked(home, 25 * HOUR)
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv("GIT_TRACE", str(trace))
    assert library.update(ws).action == "updated"
    monkeypatch.delenv("GIT_TRACE")
    ran = [line.split("built-in: git ", 1)[1] for line in trace.read_text(encoding="utf-8").splitlines()
           if "built-in: git " in line]
    verbs = {command.split()[0] for command in ran}
    assert {"fetch", "merge"} <= verbs
    assert not verbs & {"reset", "clean", "stash", "pull", "checkout", "rebase", "push", "commit", "switch", "restore", "gc"}
    assert not [command for command in ran if "--force" in command or " -f" in command or " +" in command]
    merges = [command for command in ran if command.split()[0] == "merge"]
    assert len(merges) == 1 and merges[0].startswith("merge --ff-only --no-overwrite-ignore --no-autostash --quiet ")
    assert [command for command in ran if command.split()[0] == "fetch"] == ["fetch --quiet origin"]


# --- fix round 2 -----------------------------------------------------------------------------

def moved_branch_scenario(root, ws):
    """The reviewer's scenario: the newest backup has master at X; master then gains a local
    commit Z that no backup records; the user works on another branch. Gives (the backup,
    X, Z, the snapshot before any undo)."""
    made = library.backup(ws)
    x = git("rev-parse", "HEAD", cwd=root)
    write(root, "cdl.bib", "% local commit Z on master, recorded in no backup\n")
    conftest._git("commit", "--quiet", "-m", "Z", "--", "cdl.bib", cwd=root)
    z = git("rev-parse", "HEAD", cwd=root)
    conftest._git("switch", "--quiet", "-c", "cdlbib/me/topic", "origin/master", cwd=root)
    write(root, "verification/topic.txt", "topic work\n")
    return made, x, z, snapshot(root)


def expire_and_collect(root):
    conftest._git("reflog", "expire", "--expire=now", "--all", cwd=root)
    conftest._git("gc", "--quiet", "--prune=now", cwd=root)


def test_a_branch_an_undo_moves_is_put_back_by_undoing_the_undo(managed):
    home, upstream, ws = managed
    root = ws.root
    made, x, z, before = moved_branch_scenario(root, ws)
    refs = git("for-each-ref", "refs/heads", "refs/remotes", cwd=root)
    assert before["branches"] == {"master": z, "cdlbib/me/topic": x}

    assert api.undo_update() == made
    pre = library.backups()[0]
    assert snapshot(root)["branches"] == {"master": x, "cdlbib/me/topic": x} and snapshot(root)["branch"] == "master"
    expire_and_collect(root)                                           # nothing but the backup keeps Z now

    assert api.undo_update() == pre
    assert snapshot(root) == before                                    # master is back on Z
    assert git("for-each-ref", "refs/heads", "refs/remotes", cwd=root) == refs
    ref = json.loads((pre.path / "ref.json").read_text(encoding="utf-8"))
    assert [(m["branch"], m["commit"]) for m in ref["moved"]] == [("master", z)]       # recorded in the pre-undo backup
    assert pre.moved == [("master", z)]
    assert git("rev-parse", ref["moved"][0]["pin"], cwd=root) == z and ref["moved"][0]["pin"].startswith(
        "refs/cdlbib/backups/" + pre.stamp)


def test_the_moved_branch_is_restorable_for_as_long_as_its_backup_is_listed(managed):
    home, upstream, ws = managed
    root = ws.root
    made, x, z, before = moved_branch_scenario(root, ws)
    api.undo_update()
    pre = library.backups()[0]
    after_first = snapshot(root)
    for _ in range(8):
        library.backup(ws)
    assert len(library.backups()) == 10 and pre.stamp in [b.stamp for b in library.backups()]
    expire_and_collect(root)
    for name in ("changes.bundle", "moved-0.bundle"):                  # the private refs alone must be enough
        if (pre.path / name).exists():
            os.unlink(pre.path / name)
    expire_and_collect(root)
    assert api.undo_update(pre.stamp) == pre
    assert snapshot(root) == before


def test_the_pre_undo_backup_that_alone_keeps_a_commit_outlives_eleven_backups(managed, tmp_path):
    """The reviewer's scenario: master holds a local commit Z, the user is on cdlbib/me/topic,
    and an undo moves master off Z. The undo says so; the backup taken before it is what
    keeps Z, so it is never pruned, and Z can be put back through it however many backups
    follow."""
    home, upstream, ws = managed
    root = ws.root
    made, x, z, before = moved_branch_scenario(root, ws)
    out = cdlbib("update", "--undo", cwd=tmp_path)
    pre = library.backups()[0]
    assert out.returncode == 0 and out.stderr == "", out.stderr
    assert out.stdout.splitlines()[1:] == [
        f"the library as it was just before is backup {pre.stamp}",
        "run `cdlbib update --undo` again to return to it",
        f"branch master was on commit {z[:8]}, which is on no other branch and not in the upstream; backup "
        f"{pre.stamp} keeps it, and `cdlbib update --undo {pre.stamp}` puts the branch back on it"]
    assert pre.moved == [("master", z)] and snapshot(root)["branches"]["master"] == x
    assert library.taken_off(pre) == [("master", z)] and library.holds_only_copy(pre)
    for _ in range(11):
        library.backup(ws)
    listed = library.backups()
    assert pre.stamp in [b.stamp for b in listed] and len(listed) == 11          # ten, and the one that keeps Z
    pins = git("for-each-ref", "--format=%(refname)", "refs/cdlbib", cwd=root).splitlines()
    assert sorted(pins) == sorted(["refs/cdlbib/backups/" + b.stamp for b in listed]
                                  + [f"refs/cdlbib/backups/{pre.stamp}-moved-0"])  # no pin outlives its backup
    expire_and_collect(root)
    assert git("cat-file", "-t", z, cwd=root) == "commit"
    back = api.undo(pre.stamp)                                                    # Z is restorable through it
    assert back.restored == pre and back.taken_off == []
    assert snapshot(root) == before and snapshot(root)["branches"]["master"] == z


def test_an_undo_that_takes_no_branch_off_unsent_commits_says_nothing_more(managed, tmp_path):
    home, upstream, ws = managed
    library.backup(ws)
    advance(upstream, "An update", **{"verification/from-update.txt": "upstream\n"})
    fast_forward(ws.root)
    out = cdlbib("update", "--undo", cwd=tmp_path)
    assert out.returncode == 0 and len(out.stdout.splitlines()) == 3 and "which is on no other branch" not in out.stdout
    assert api.undo().taken_off == []


def torn(folder, text):
    (folder / "ref.json").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("damage, reason", [('{"taken_at": "2026-10-02T12:00', "ref.json is not complete"),
                                            ("", "ref.json is empty"), (None, "it has no ref.json"),
                                            ('{"branch": "master"}', "ref.json does not describe a backup")])
def test_an_unreadable_backup_is_named_never_skipped_and_never_pruned(managed, tmp_path, damage, reason):
    home, upstream, ws = managed
    root = ws.root
    older = library.backup(ws)                                        # a readable backup of the clean library
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% unsent\n")
    newest = library.backup(ws)
    if damage is None:
        (newest.path / "ref.json").unlink()
    else:
        torn(newest.path, damage)
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% later work\n")
    before, held = whole_clone(root), sorted(p.name for p in (home / "backups").iterdir())

    listed = cdlbib("update", "--list", cwd=tmp_path)
    assert listed.returncode == 0 and listed.stderr == ""
    assert listed.stdout.splitlines()[:3] == [
        f"1 readable backup of {root} and 1 unreadable, newest first (kept in {home.resolve() / 'backups'}):",
        f"  {newest.stamp}: unreadable ({reason})",
        f"  {older.stamp}  {older.when}  branch master at {older.commit[:8]}, 0 changed files"]
    assert library.unreadable_backups() == api.unreadable_backups() == [(newest.stamp, reason)]

    bare = cdlbib("update", "--undo", cwd=tmp_path)                    # never the next newest in silence
    assert (bare.returncode, bare.stdout) == (1, "")
    assert bare.stderr == (f"The newest backup, {home.resolve() / 'backups' / newest.stamp}, cannot be read ({reason}), so "
                           "nothing was restored. Nothing was changed. `cdlbib update --undo STAMP` restores a specific "
                           "older backup; `cdlbib update --list` shows them.\n")
    assert whole_clone(root) == before and sorted(p.name for p in (home / "backups").iterdir()) == held

    by_name = cdlbib("update", "--undo", newest.stamp, cwd=tmp_path)   # named: it is there, and it cannot be read
    assert (by_name.returncode, by_name.stdout) == (1, "")
    assert by_name.stderr == (f"The backup {newest.stamp} is there ({home.resolve() / 'backups' / newest.stamp}) but "
                              f"cannot be read ({reason}), so it was not restored. Nothing was changed. `cdlbib update "
                              "--list` shows the backups; `cdlbib update --undo STAMP` restores another one.\n")
    assert whole_clone(root) == before and sorted(p.name for p in (home / "backups").iterdir()) == held

    for _ in range(library.KEEP + 1):                                 # pruning leaves it alone and does not count it
        library.backup(ws)
    names = sorted(p.name for p in (home / "backups").iterdir())
    assert newest.stamp in names and len(names) == library.KEEP + 1 and len(library.backups()) == library.KEEP
    assert sorted(p.name for p in newest.path.iterdir()) == sorted(["files"] + (["ref.json"] if damage is not None else []))

    library.backup(ws)
    kept = library.backups()[-1]                                      # naming a readable one still works
    named = cdlbib("update", "--undo", kept.stamp, cwd=tmp_path)
    assert named.returncode == 0 and named.stdout.startswith(f"restored backup {kept.stamp} ("), named.stderr
    assert (root / "cdl.bib").read_text(encoding="utf-8").endswith("% later work\n")


def test_ref_json_is_written_whole_with_no_temporary_file_left(managed):
    home, upstream, ws = managed
    made = library.backup(ws)
    assert sorted(p.name for p in made.path.iterdir()) == ["files", "ref.json"]
    assert json.loads((made.path / "ref.json").read_text(encoding="utf-8"))["commit"] == made.commit


@pytest.mark.parametrize("name", ["HEAD", "@{-1}", "-x", "a..b", "refs/heads/master/", "@", "FETCH_HEAD", "ORIG_HEAD",
                                  "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_HEAD", "AUTO_MERGE",
                                  "SOME_OTHER_HEAD"])
def test_a_backup_naming_something_that_is_not_a_branch_is_refused_with_nothing_changed(managed, name):
    home, upstream, ws = managed
    root = ws.root
    made = library.backup(ws)
    advance(upstream, "An update", **{"verification/from-update.txt": "upstream\n"})
    fast_forward(root)
    ref = json.loads((made.path / "ref.json").read_text(encoding="utf-8"))
    ref["branch"] = name
    torn(made.path, json.dumps(ref))
    before, held = whole_clone(root), backup_names(home)
    with pytest.raises(CdlbibError, match="is not a backup cdlbib wrote") as err:
        api.undo_update()
    assert "is not a branch name" in str(err.value) and "Nothing was changed" in str(err.value)
    assert whole_clone(root) == before and backup_names(home) == held
    assert git("symbolic-ref", "--short", "HEAD", cwd=root) == "master"
    assert sorted(local_branches(root)) == ["master"]                 # no stray branch of that name was made
    out = cdlbib("update", "--undo", cwd=root.parent)                  # and the command says the same, with no traceback
    assert out.returncode == 1 and "is not a branch name" in out.stderr and "Traceback" not in out.stderr
    assert whole_clone(root) == before and backup_names(home) == held


def test_a_moved_branch_that_cannot_be_put_back_stops_the_undo_and_keeps_everything(managed, tmp_path):
    home, upstream, ws = managed
    root = ws.root
    made, x, z, before = moved_branch_scenario(root, ws)
    conftest._git("switch", "--quiet", "--detach", cwd=root)           # a commit on no branch, for the hook to use
    write(root, "cdl.bib", "% stray\n")
    conftest._git("commit", "--quiet", "-m", "Stray", "--", "cdl.bib", cwd=root)
    stray = git("rev-parse", "HEAD", cwd=root)
    conftest._git("switch", "--quiet", "cdlbib/me/topic", cwd=root)
    before = snapshot(root)
    api.undo_update()
    pre = library.backups()[0]
    after_first = snapshot(root)

    hook = root / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f'#!/bin/sh\nif [ "$3" = 1 ]; then git update-ref refs/heads/master {stray}; fi\n', encoding="utf-8")
    os.chmod(hook, 0o755)
    with pytest.raises(CdlbibError) as err:
        api.undo_update()
    os.unlink(hook)
    message, second = str(err.value), library.backups()[0]
    assert f"branch master is no longer at {x[:8]}" in message and f"so it was not moved to {z[:8]}" in message
    assert f"`cdlbib update --undo {second.stamp}` puts them back" in message
    assert git("rev-parse", "refs/cdlbib/backups/" + pre.stamp + "-moved-0", cwd=root) == z      # the pin is not dropped
    assert [b.stamp for b in library.backups()][:2] == [second.stamp, pre.stamp]

    empty = tmp_path / "empty"
    empty.mkdir()
    assert cdlbib("update", "--undo", second.stamp, cwd=empty).returncode == 0     # the command the message gives
    assert snapshot(root) == after_first
    expire_and_collect(root)
    assert git("cat-file", "-t", stray, cwd=root) == "commit"          # where the hook had put master: kept too
    assert cdlbib("update", "--undo", pre.stamp, cwd=empty).returncode == 0
    assert snapshot(root) == before


def test_a_folder_named_like_an_impossible_time_is_left_alone(managed):
    home, _, ws = managed
    folder = home / "backups"
    folder.mkdir()
    odd = [folder / "99999999T999999.999999Z.partial", folder / "99999999T999999.999999Z"]
    for one in odd:
        (one / "files").mkdir(parents=True)
    made = library.backup(ws)
    for _ in range(11):
        library.backup(ws)
    assert all((one / "files").is_dir() for one in odd)                # never deleted, never counted
    assert len(library.backups()) == 10 and made.stamp not in [b.stamp for b in library.backups()]
    write(ws.root, "cdl.bib", "% edit\n")
    api.undo_update()
    assert all((one / "files").is_dir() for one in odd)


def crafted(made, **changes):
    ref = json.loads((made.path / "ref.json").read_text(encoding="utf-8"))
    ref.update(changes)
    (made.path / "ref.json").write_text(json.dumps(ref), encoding="utf-8")


@pytest.mark.parametrize("field, value", [
    ("folders", ["verification", "../../made-outside"]),
    ("folders", ["verification/../../made-outside"]),
    ("folders", ["ABSOLUTE"]),
    ("folders", ["docs/made-outside-the-two-paths"]),
    ("folders", ["verification/a\\..\\b/../../../made-outside"]),
    ("deleted", ["../../victim.txt"]),
    ("deleted", ["README"]),
    ("deleted", ["ABSOLUTE"]),
    ("branch", "master..oops"),
    ("branch", "-D"),
    ("branch", "refs/heads/../../config"),
    ("commit", "HEAD~1"),
    ("commit", "--help"),
    ("moved", [{"branch": "-f", "commit": "0" * 40}]),
    ("moved", [{"branch": "master", "commit": "master"}]),
    ("moved", "not a list"),
])
def test_a_backup_whose_recorded_paths_or_names_escape_is_refused_before_anything_changes(managed, tmp_path, field, value):
    home, upstream, ws = managed
    root = ws.root
    victim = home.parent / "victim.txt"
    victim.write_text("not cdlbib's", encoding="utf-8")
    write(root, "README", "mine\n")
    made = library.backup(ws)
    absolute = tmp_path / "made-absolute"
    if value == ["ABSOLUTE"]:
        value = [str(absolute)]
    crafted(made, **{field: value})
    write(root, "cdl.bib", "% unsent\n")
    before, listed = whole_clone(root), sorted(p.name for p in (home / "backups").iterdir())
    around = sorted(p.name for p in home.parent.iterdir()), sorted(p.name for p in home.iterdir())
    hand_made = library.backups()
    if hand_made:                                                       # still readable as a backup: restoring it is refused
        with pytest.raises(CdlbibError) as err:
            library.restore(hand_made[0], ws)
        assert "is not a backup cdlbib wrote" in str(err.value) and "Nothing was changed" in str(err.value)
    with pytest.raises(CdlbibError):                                    # unreadable ones are simply not backups
        api.undo_update()
    assert whole_clone(root) == before and victim.read_text(encoding="utf-8") == "not cdlbib's"
    assert sorted(p.name for p in (home / "backups").iterdir()) == listed
    assert (sorted(p.name for p in home.parent.iterdir()), sorted(p.name for p in home.iterdir())) == around
    assert not absolute.exists() and not (home / "made-outside").exists() and not (root / "docs").exists()


def test_a_backup_that_would_write_through_a_link_out_of_the_library_is_refused(managed, tmp_path):
    home, upstream, ws = managed
    root = ws.root
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, root / "verification/out")
    conftest._git("add", "--", "verification/out", cwd=root)
    conftest._git("commit", "--quiet", "-m", "A link out of the library", cwd=root)
    made = library.backup(ws)
    (made.path / "files/verification/out").mkdir(parents=True)          # hand-made: a file beneath the link
    (made.path / "files/verification/out/planted.txt").write_text("planted", encoding="utf-8")
    before, listed = whole_clone(root), [b.stamp for b in library.backups()]
    with pytest.raises(CdlbibError) as err:
        api.undo_update()
    assert "is not a backup cdlbib wrote" in str(err.value) and "verification/out" in str(err.value)
    assert list(elsewhere.iterdir()) == [] and whole_clone(root) == before
    assert [b.stamp for b in library.backups()] == listed


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs file permissions that bind")
def test_a_file_error_while_checking_is_a_refusal_that_leaves_no_backup_behind(managed):
    home, upstream, ws = managed
    root = ws.root
    write(root, "verification/mine.txt", "mine\n")
    made = library.backup(ws)
    write(root, "cdl.bib", "% unsent\n")
    before, listed = whole_clone(root), [b.stamp for b in library.backups()]
    os.chmod(made.path / "files/verification", 0)                       # the backup's files cannot be listed
    try:
        with pytest.raises(CdlbibError) as err:
            api.undo_update()
    finally:
        os.chmod(made.path / "files/verification", 0o755)
    assert isinstance(err.value.__cause__, OSError) and "Nothing was changed" in str(err.value)
    assert whole_clone(root) == before and [b.stamp for b in library.backups()] == listed


# --- rows of the reviewer's matrix that had no test ------------------------------------------

def test_a_tracked_file_edited_locally_and_deleted_by_the_update_comes_back_edited(managed):
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "A tracked file", **{"verification/old.txt": "old\n"})
    fast_forward(root)
    write(root, "verification/old.txt", "old, but MODIFIED by me\n")
    before = snapshot(root)
    library.backup(ws)
    conftest._git("restore", "--", "verification/old.txt", cwd=root)    # as an update that discards, then fast-forwards
    advance(upstream, "The file is deleted upstream", **{"verification/old.txt": None})
    fast_forward(root)
    assert not (root / "verification/old.txt").exists()
    after = snapshot(root)
    api.undo_update()
    assert snapshot(root) == before and (root / "verification/old.txt").read_text(encoding="utf-8") == "old, but MODIFIED by me\n"
    api.undo_update()
    assert snapshot(root) == after


def test_edits_made_after_the_backup_to_a_file_it_did_not_save_survive_two_undos(managed):
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "A tracked file", **{"verification/keep.txt": "as committed\n"})
    fast_forward(root)
    first = snapshot(root)
    made = library.backup(ws)
    assert not (made.path / "files/verification/keep.txt").exists()     # clean: left to git
    advance(upstream, "An update", **{"verification/keep.txt": "as updated\n"})
    fast_forward(root)
    write(root, "verification/keep.txt", "as updated\nLATER EDITS\n")
    second = snapshot(root)
    api.undo_update()
    assert snapshot(root) == first and (root / "verification/keep.txt").read_text(encoding="utf-8") == "as committed\n"
    held = library.backups()[0].path / "files/verification/keep.txt"
    assert held.read_text(encoding="utf-8") == "as updated\nLATER EDITS\n"
    api.undo_update()
    assert snapshot(root) == second
    api.undo_update()
    assert snapshot(root) == first


def test_an_untracked_file_where_the_recorded_commit_has_one_is_a_refusal(managed):
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "A plain tracked file", **{"plain.txt": "tracked at first\n"})
    fast_forward(root)
    library.backup(ws)
    advance(upstream, "No longer tracked", **{"plain.txt": None})
    fast_forward(root)
    write(root, "plain.txt", "my own untracked file\n")
    write(root, "cdl.bib", "% unsent\n")
    before, listed = whole_clone(root), [b.stamp for b in library.backups()]
    with pytest.raises(CdlbibError, match="would overwrite plain.txt"):
        api.undo_update()
    assert whole_clone(root) == before and [b.stamp for b in library.backups()] == listed
    assert (root / "plain.txt").read_text(encoding="utf-8") == "my own untracked file\n"


def test_a_file_replaced_by_a_folder_a_folder_by_a_file_and_an_empty_folder(managed):
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "A file and a folder", **{"verification/was-file": "a file\n", "verification/was-folder/inner.txt": "inner\n"})
    fast_forward(root)
    os.unlink(root / "verification/was-file")                           # the tracked file becomes a folder
    write(root, "verification/was-file/now inside.txt", "inside\n")
    shutil.rmtree(root / "verification/was-folder")                     # the tracked folder becomes a file
    write(root, "verification/was-folder", "now a file\n")
    (root / "verification/empty/nested").mkdir(parents=True)            # and folders with nothing in them
    first = snapshot(root)
    made = library.backup(ws)
    assert sorted(made.deleted) == ["verification/was-file", "verification/was-folder/inner.txt"]

    shutil.rmtree(root / "verification/was-file")
    os.unlink(root / "verification/was-folder")
    shutil.rmtree(root / "verification/empty")
    conftest._git("restore", "--", "verification", cwd=root)
    advance(upstream, "An update", **{"verification/new.txt": "new\n"})
    fast_forward(root)
    (root / "verification/another empty").mkdir()
    second = snapshot(root)

    api.undo_update()
    assert snapshot(root) == first
    assert (root / "verification/was-file/now inside.txt").read_text(encoding="utf-8") == "inside\n"
    assert (root / "verification/was-folder").read_text(encoding="utf-8") == "now a file\n"
    assert (root / "verification/empty/nested").is_dir() and not (root / "verification/another empty").exists()
    api.undo_update()
    assert snapshot(root) == second
    assert (root / "verification/another empty").is_dir() and not (root / "verification/empty").exists()


# --- fix round 1 of the daily check -----------------------------------------------------------

def test_an_old_backup_that_cannot_be_removed_is_a_note_and_the_update_stands(managed, tmp_path):
    home, upstream, ws = managed
    for _ in range(library.KEEP):
        library.backup(ws)
    oldest = home / "backups" / backup_names(home)[0]
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    checked(home, 25 * HOUR)
    oldest.chmod(0o500)                                               # nothing in it can be deleted
    try:
        out = cdlbib("verify", "--no-citations", cwd=empty_folder(tmp_path))
    finally:
        oldest.chmod(0o700)
    assert out.returncode == 0 and "looks good!" in out.stdout and "Traceback" not in out.stderr, out.stdout + out.stderr
    lines = out.stderr.splitlines()[:2]
    assert lines[0].startswith(f"note: the old backup {oldest} could not be removed (Permission denied")
    assert lines[0].endswith("); it was left there") and "Traceback" not in out.stderr
    assert lines[1] == updated_line(1, home)
    assert git("rev-parse", "HEAD", cwd=ws.root) == new
    assert len(library.backups()) == library.KEEP + 1 and library.backups()[-1].stamp == oldest.name   # still whole
    assert datetime.datetime.now(UTC) - library.read_state().last_check < HOUR


def test_a_backup_that_alone_keeps_a_commit_is_never_pruned_and_is_marked(managed, tmp_path):
    home, upstream, ws = managed
    root = ws.root
    first = library.backup(ws)                                        # the clean library
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% my work\n")
    conftest._git("commit", "--quiet", "-am", "My work", cwd=root)
    mine = git("rev-parse", "HEAD", cwd=root)
    restored, keeper = library.undo(ws, first.stamp)                  # the undo moves master off my commit
    assert git("rev-parse", "master", cwd=root) == first.commit != mine and keeper.commit == mine
    assert git("for-each-ref", "--contains", mine, "refs/heads", "refs/remotes", cwd=root) == ""
    assert library.holds_only_copy(keeper) and not library.holds_only_copy(first)

    for _ in range(library.KEEP + 1):                                 # eleven further backups
        library.backup(ws)
    stamps = [b.stamp for b in library.backups()]
    assert keeper.stamp in stamps and first.stamp not in stamps      # the ordinary ones were pruned,
    assert len(stamps) == library.KEEP + 1                            # to ten, not counting the keeper
    assert git("rev-parse", f"refs/cdlbib/backups/{keeper.stamp}", cwd=root) == mine

    listed = cdlbib("update", "--list", cwd=tmp_path).stdout.splitlines()
    marked = [line for line in listed if "holds commits kept nowhere else" in line]
    assert len(marked) == 1 and marked[0].startswith(f"  {keeper.stamp}  ")
    assert marked[0].endswith(f"branch master at {mine[:8]}, 0 changed files, local commits saved, "
                              "holds commits kept nowhere else")

    undone = cdlbib("update", "--undo", keeper.stamp, cwd=tmp_path)
    assert undone.returncode == 0, undone.stderr
    assert git("rev-parse", "master", cwd=root) == mine and git("symbolic-ref", "--short", "HEAD", cwd=root) == "master"
    assert (root / "cdl.bib").read_text(encoding="utf-8").endswith("% my work\n")
    assert not library.holds_only_copy(keeper)                        # master leads to the commit again:
    for _ in range(library.KEEP):                                     # now it is an ordinary backup and ages out
        library.backup(ws)
    assert keeper.stamp not in [b.stamp for b in library.backups()] and len(library.backups()) == library.KEEP
    assert git("rev-parse", "master", cwd=root) == mine


REWRITTEN_NOTICE = ("the history of the bibliography's upstream was changed, and the copy here matches an older version "
                    "of it; nothing was changed. Run `cdlbib update` in a terminal to choose what to do.\n")
REWRITTEN_QUESTION = ("The history of the bibliography's upstream was changed, and the copy here matches an older "
                      "version of it (it holds no changes of yours).\n"
                      "What would you like to do?\n"
                      "  [k] Keep working with the copy here (ask again tomorrow)\n"
                      "  [m] Move to the new version (the copy here is saved first; `cdlbib update --undo` brings it back)")


def test_a_rewritten_upstream_is_left_alone(managed, tmp_path):
    """The upstream's history was replaced (a forced push there): the library's commit is no
    longer in it, a fast-forward is impossible, and nothing is changed."""
    home, upstream, ws = managed
    root, work = ws.root, upstream.parent / "upstream-work"
    conftest._git("commit", "--quiet", "--amend", "-m", "The same library, rewritten", cwd=work)
    conftest._git("push", "--quiet", "--force", str(upstream), "master", cwd=work)
    before = snapshot(root), outside(root)
    checked(home, 25 * HOUR)
    out = cdlbib("where", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and out.stderr == REWRITTEN_NOTICE
    assert (snapshot(root), outside(root)) == before and backup_names(home) == []
    assert git("rev-parse", "origin/master", cwd=root) == git("rev-parse", "master", cwd=upstream) != before[0]["commit"]


@pytest.mark.parametrize("kind", ["untracked", "ignored"])
def test_a_file_whose_name_differs_only_in_case_is_never_overwritten(managed, tmp_path, kind):
    home, upstream, ws = managed
    root = ws.root
    (tmp_path / "Probe").write_text("", encoding="utf-8")
    folds = (tmp_path / "probe").exists()                             # does this file system fold case?
    if kind == "ignored":
        (root / ".git" / "info" / "exclude").write_text("Notes.md\n", encoding="utf-8")
    write(root, "Notes.md", "MY NOTES\n")
    new = advance(upstream, "Notes", **{"notes.md": "upstream's notes\n"})
    old = git("rev-parse", "HEAD", cwd=root)
    checked(home, 25 * HOUR)
    out = cdlbib("where", cwd=empty_folder(tmp_path))
    assert out.returncode == 0, out.stderr
    assert (root / "Notes.md").read_text(encoding="utf-8") == "MY NOTES\n"
    if folds:
        assert out.stderr == left_alone(1, "updating would overwrite your own Notes.md",
                                        "Move that file out of the way, then run `cdlbib update`.") + "\n"
        assert git("rev-parse", "HEAD", cwd=root) == old and backup_names(home) == []
        assert sorted(p.name for p in root.iterdir() if p.name.lower() == "notes.md") == ["Notes.md"]
    else:
        assert out.stderr == updated_line(1, home) + "\n" and git("rev-parse", "HEAD", cwd=root) == new
        assert (root / "notes.md").read_text(encoding="utf-8") == "upstream's notes\n"


@pytest.mark.parametrize("where", ["the library's folder", "a folder inside it"])
def test_a_command_run_inside_the_managed_library_keeps_it_current_too(managed, tmp_path, where):
    home, upstream, ws = managed
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    checked(home, 25 * HOUR)
    out = cdlbib("where", cwd=ws.root if where == "the library's folder" else ws.root / "verification")
    assert out.returncode == 0 and out.stderr == updated_line(1, home) + "\n", out.stderr
    assert out.stdout.splitlines() == [str(ws.root), "chosen by: cdl.bib found in or above the current folder"]
    assert git("rev-parse", "HEAD", cwd=ws.root) == new


# --- unsent edits: the user decides ------------------------------------------------------------
#
# An update is available and the managed library holds work that has not been sent. The core
# raises UpdateNeedsDecision and changes nothing; the command line asks. Every test compares
# everything() before and after: the snapshot (every local branch, HEAD, the changed paths, a
# hash of every file under the two paths), every other file, the stash list, and the files
# that hold a conflict marker.

MINE = ("\n@article{Mine26,\n\tAuthor = {A Person},\n\tJournal = {Journal of Tests},\n\tTitle = {My own entry},\n"
        "\tYear = {2026}}\n")
BASE = conftest.ZOLL90 + "\n"
THEIRS = BASE.replace("U Zoller", "Uri Zoller")                       # the upstream edits line 2 of the entry
IDENTITY = dict(GIT_AUTHOR_NAME="cdlbib tests", GIT_AUTHOR_EMAIL="tests@cdlbib.invalid",
                GIT_COMMITTER_NAME="cdlbib tests", GIT_COMMITTER_EMAIL="tests@cdlbib.invalid")


def markers(root):
    found = []
    for name in hashes(root, KEPT):
        file = Path(root) / name
        if not file.is_symlink() and any(mark in file.read_bytes() for mark in (b"<<<<<<<", b">>>>>>>", b"|||||||")):
            found.append(name)
    return found


def everything(root):
    return {"snapshot": snapshot(root), "outside": outside(root), "stash": git("stash", "list", cwd=root),
            "markers": markers(root), "refs": git("for-each-ref", "refs/heads", "refs/stash", cwd=root)}


def unsent(managed, mine=BASE + MINE, theirs=THEIRS):
    """The managed library with an edited cdl.bib, an edited tracked file and an untracked one,
    and an upstream that has moved on (two commits). Gives (home, upstream, ws, the upstream's
    new commit)."""
    home, upstream, ws = managed
    advance(upstream, "A tracked file", **{"verification/tracked.txt": "as the upstream has it\n"})
    fast_forward(ws.root)
    write(ws.root, "cdl.bib", mine)
    write(ws.root, "verification/tracked.txt", "as the upstream has it\nand a line of mine – é\n")
    write(ws.root, "verification/notes/my new file.jsonl", '{"key": "Mine26"}\n')
    advance(upstream, "A new file", **{"verification/new.txt": "new\n"})
    new = advance(upstream, "An edit to the entry", **{"cdl.bib": theirs})
    checked(home, 25 * HOUR)
    return home, upstream, ws, new


def lock_is_free(home):
    import fcntl
    with open(home / "lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)             # raises when another holder has it
        fcntl.flock(lock, fcntl.LOCK_UN)
    return True


def test_with_unsent_edits_the_core_asks_and_changes_nothing(managed, capsys):
    home, upstream, ws, new = unsent(managed)
    before, state = everything(ws.root), (home / "state.json").read_bytes()
    with pytest.raises(UpdateNeedsDecision) as raised:
        library.update(ws)
    asked = raised.value
    assert isinstance(asked, CdlbibError)
    assert asked.changed == ["cdl.bib", "verification/notes/my new file.jsonl", "verification/tracked.txt"]
    assert (asked.entries_changed, asked.new_commits, asked.local_commits) == (1, 2, 0)
    assert asked.choices == ("keep", "update", "send", "discard") and asked.seen
    assert str(asked) == (f"A newer version of the bibliography is available (2 new commits), and the library in "
                          f"{ws.root} has changes that have not been sent. Nothing was changed.")
    assert everything(ws.root) == before and backup_names(home) == []
    assert (home / "state.json").read_bytes() == state               # no time recorded: asked again after a crash
    assert lock_is_free(home)                                         # and the lock is not held while the user thinks
    with pytest.raises(UpdateNeedsDecision) as again:
        api.update(ws)
    assert again.value.seen == asked.seen                             # the same state has the same name
    assert capsys.readouterr() == ("", "")                            # the core never prints or asks
    with pytest.raises(CdlbibError, match="'yes' is not a decision an update takes"):
        library.update(ws, decision="yes")
    assert everything(ws.root) == before and backup_names(home) == []


def test_an_entry_count_that_cannot_be_made_is_none_and_the_files_are_still_listed(managed):
    home, upstream, ws, new = unsent(managed)
    (ws.root / "cdl.bib").write_bytes(b"\xff\xfe not text that can be read as a bibliography \xff")
    before = everything(ws.root)
    with pytest.raises(UpdateNeedsDecision) as raised:
        library.update(ws)
    assert raised.value.entries_changed is None and raised.value.changed[0] == "cdl.bib"
    assert everything(ws.root) == before
    out = cdlbib("update", cwd=ws.root.parent)
    assert out.returncode == 1 and out.stderr == NOTICE.replace("cdl.bib (1 entry changed)", "cdl.bib")
    assert everything(ws.root) == before


def test_keep_changes_nothing_and_is_not_asked_again_for_a_day(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    before, started = everything(ws.root), datetime.datetime.now(UTC)
    result = library.update(ws, decision="keep")
    assert (result.action, result.backup) == ("left_alone", None)
    assert result.message == ("the bibliography was not updated and your changes are as they were; nothing was "
                              "changed. You will be asked again tomorrow; `cdlbib update` asks now.")
    assert everything(ws.root) == before and backup_names(home) == []
    assert started <= library.read_state().last_check <= datetime.datetime.now(UTC)
    assert library.update(ws) == library.UpdateResult("not_due")     # no question for the next 24 hours
    out = cdlbib("where", cwd=empty_folder(tmp_path))
    assert (out.returncode, out.stderr) == (0, "")
    tomorrow = datetime.datetime.now(UTC) + 24 * HOUR + MINUTE
    with pytest.raises(UpdateNeedsDecision):                          # the next day's check asks again
        library.update(ws, now=tomorrow)
    assert everything(ws.root) == before


def test_update_and_keep_brings_the_new_version_in_under_the_edits(managed):
    home, upstream, ws, new = unsent(managed)
    root, old = ws.root, git("rev-parse", "HEAD", cwd=ws.root)
    conftest._git("add", "cdl.bib", cwd=root)                         # a staged change is a change like any other
    before = everything(root)
    seen = pytest.raises(UpdateNeedsDecision, library.update, ws).value.seen
    result = library.update(ws, decision="update", seen=seen)
    assert result.action == "updated" and result.new_commits == 2
    stamp = result.backup.stamp
    assert result.message == (
        "updated the bibliography: 2 new commits, with your changes kept (cdl.bib, verification/notes/my new "
        f"file.jsonl, verification/tracked.txt) (the library as it was is backup {stamp}; `cdlbib update --undo "
        f"{stamp}` puts it back)")
    assert git("rev-parse", "HEAD", cwd=root) == new and git("symbolic-ref", "--short", "HEAD", cwd=root) == "master"
    # The edits, byte for byte, on top of the new version: the upstream's change to the entry AND my new entry.
    assert (root / "cdl.bib").read_bytes() == (THEIRS + MINE).encode()
    assert (root / "verification/tracked.txt").read_bytes() == "as the upstream has it\nand a line of mine – é\n".encode()
    assert (root / "verification/notes/my new file.jsonl").read_bytes() == b'{"key": "Mine26"}\n'
    assert (root / "verification/new.txt").read_text() == "new\n"     # and what the upstream added
    assert sorted(changed_paths(root, ".")) == ["cdl.bib", "verification/notes/my new file.jsonl", "verification/tracked.txt"]
    now = everything(root)
    assert (now["stash"], now["markers"], now["outside"]) == ("", [], before["outside"])
    assert (result.backup.branch, result.backup.commit) == ("master", old) and backup_names(home) == [stamp]
    assert library.read_state().last_check > datetime.datetime.now(UTC) - HOUR
    api.undo_update(stamp)                                            # reversible: exactly the state before
    assert everything(root) == before


def test_update_and_keep_carries_a_deleted_file_and_an_edit_the_upstream_also_made(managed):
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "Two files", **{"verification/gone.txt": "to be deleted here\n", "verification/both.txt": "old\n"})
    fast_forward(root)
    os.unlink(root / "verification/gone.txt")                         # deleted here, untouched there: stays deleted
    write(root, "verification/both.txt", "new\n")                     # the same edit on both sides: no change left
    write(root, "verification/same.txt", "added by both\n")           # added by both with the same bytes
    new = advance(upstream, "The same edits", **{"verification/both.txt": "new\n", "verification/same.txt": "added by both\n"})
    checked(home, 25 * HOUR)
    before = everything(root)
    result = library.update(ws, decision="update")
    assert result.action == "updated" and git("rev-parse", "HEAD", cwd=root) == new
    assert changed_paths(root, ".") == {"verification/gone.txt": " D"}
    assert (root / "verification/both.txt").read_text() == "new\n" and not (root / "verification/gone.txt").exists()
    assert (everything(root)["stash"], everything(root)["markers"]) == ("", [])
    api.undo_update()
    assert everything(root) == before


@pytest.mark.parametrize("case", ["the same lines", "the same entry, lines that would merge", "an entry added by both",
                                  "a verification file", "edited here and deleted there", "a binary file",
                                  "a file where the new version has a folder"])
def test_update_and_keep_with_a_collision_changes_nothing_and_names_the_entries(managed, case):
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "Files", **{"verification/list.txt": "one\n", "verification/blob.bin": "\0base\0"})
    fast_forward(root)
    entries, files = [], []
    if case == "the same lines":
        write(root, "cdl.bib", BASE.replace("{1990}", "{1991}"))
        theirs, entries, files = {"cdl.bib": BASE.replace("{1990}", "{1989}")}, ["Zoll90"], ["cdl.bib"]
    elif case == "the same entry, lines that would merge":
        write(root, "cdl.bib", BASE.replace("{1990}", "{1991}") + MINE)       # line 9 here, line 2 there
        theirs, entries, files = {"cdl.bib": THEIRS}, ["Zoll90"], ["cdl.bib"]
    elif case == "an entry added by both":
        write(root, "cdl.bib", BASE + MINE)
        theirs, entries, files = {"cdl.bib": BASE + MINE.replace("A Person", "Another Person")}, ["Mine26"], ["cdl.bib"]
    elif case == "a verification file":
        write(root, "verification/list.txt", "one, mine\n")
        theirs, files = {"verification/list.txt": "one, theirs\n"}, ["verification/list.txt"]
    elif case == "edited here and deleted there":
        write(root, "verification/list.txt", "one\ntwo of mine\n")
        theirs, files = {"verification/list.txt": None, "verification/other.txt": "x\n"}, ["verification/list.txt"]
    elif case == "a binary file":
        write(root, "verification/blob.bin", "\0mine\0")
        theirs, files = {"verification/blob.bin": "\0theirs\0"}, ["verification/blob.bin"]
    else:
        write(root, "verification/place", "my file\n")
        theirs, files = {"verification/place/inside.txt": "their folder\n"}, ["verification/place"]
    write(root, "verification/untracked.txt", "mine\n")
    advance(upstream, "The upstream's change", **theirs)
    state = checked(home, 25 * HOUR)
    before = everything(root)
    seen = pytest.raises(UpdateNeedsDecision, library.update, ws).value.seen
    with pytest.raises(UpdateConflict) as raised:
        library.update(ws, decision="update", seen=seen)
    assert (raised.value.entries, raised.value.files) == (entries, files)
    what = (f"this entry was changed both by you and in the new version: {entries[0]}" if entries
            else f"{files[0]} cannot be merged automatically because it contains binary data" if case == "a binary file"
            else f"your changes to {files[0]} collide with the new version's")
    assert str(raised.value) == (f"The bibliography was not updated: {what}. Nothing was changed: your files are "
                                 "exactly as they were. Run `cdlbib send` to send your changes, or `cdlbib update` "
                                 "to choose again.")
    after = everything(root)
    assert after == before                                            # byte for byte the state before
    assert (after["stash"], after["markers"]) == ("", [])             # no stash left, no conflict marker anywhere
    assert backup_names(home) == [] and git("for-each-ref", "refs/cdlbib", cwd=root) == ""
    assert (home / "state.json").read_bytes() == state and lock_is_free(home)
    assert not list((home / "work").iterdir())                        # the copies are gone (this test's data folder only)


def test_discard_makes_the_library_the_upstreams_and_undo_brings_every_edit_back(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    root, old = ws.root, git("rev-parse", "HEAD", cwd=ws.root)
    write(root, ".bibcheck/verification.sqlite3", "a cache")           # not part of the library: untouched
    before = everything(root)
    seen = pytest.raises(UpdateNeedsDecision, library.update, ws).value.seen
    result = library.update(ws, decision="discard", seen=seen)
    stamp = result.backup.stamp
    assert result.action == "updated" and result.new_commits == 2
    assert result.message == (
        "updated the bibliography: 2 new commits; discarded your changes to cdl.bib, verification/notes/my new "
        f"file.jsonl, verification/tracked.txt (saved in backup {stamp}; `cdlbib update --undo {stamp}` brings them back)")
    assert git("rev-parse", "HEAD", cwd=root) == new and git("symbolic-ref", "--short", "HEAD", cwd=root) == "master"
    assert changed_paths(root, "cdl.bib", "verification") == {}       # the library equals the upstream
    assert (root / "cdl.bib").read_text(encoding="utf-8") == THEIRS
    assert sorted(hashes(root, KEPT)) == ["cdl.bib", "verification/.gitkeep", "verification/new.txt", "verification/tracked.txt"]
    assert not (root / "verification/notes").exists()                 # the folder the untracked file was alone in
    now = everything(root)
    assert (now["stash"], now["markers"], now["outside"]) == ("", [], before["outside"])
    saved = result.backup.path / "files"                              # nothing was deleted: every edit is in the backup
    assert (saved / "verification/notes/my new file.jsonl").read_bytes() == b'{"key": "Mine26"}\n'
    assert (saved / "cdl.bib").read_bytes() == (BASE + MINE).encode()
    assert (result.backup.branch, result.backup.commit) == ("master", old)

    undone = cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path))     # the command the message names
    assert undone.returncode == 0, undone.stderr
    assert everything(root) == before


def test_discard_of_local_commits_moves_the_branch_and_undo_puts_them_back(managed):
    home, upstream, ws = managed
    root = ws.root
    unsent_work(root)                                                 # a local commit, an edit on top, an untracked file
    mine = git("rev-parse", "HEAD", cwd=root)
    new = advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    checked(home, 25 * HOUR)
    before = everything(root)
    asked = pytest.raises(UpdateNeedsDecision, library.update, ws).value
    assert asked.local_commits == 1 and asked.choices == ("keep", "send", "discard")     # no "update and keep"
    assert asked.changed == ["cdl.bib", "verification/notes/new entry.jsonl"]

    refused = library.update(ws, decision="update", seen=asked.seen)   # asked for anyway: nothing is changed
    assert refused.action == "left_alone" and refused.backup is None and refused.message == (
        "a newer version of the bibliography is available (1 new commit), but the library has 1 commit that the "
        "upstream does not have, which cannot be kept on top of the new version; nothing was changed. "
        "Run `cdlbib update` and choose again.")
    assert everything(root) == before and backup_names(home) == []

    result = library.update(ws, decision="discard", seen=asked.seen)
    stamp = result.backup.stamp
    assert result.message == (
        "updated the bibliography: 1 new commit; discarded 1 commit and your changes to cdl.bib, "
        f"verification/notes/new entry.jsonl (saved in backup {stamp}; `cdlbib update --undo {stamp}` brings them back)")
    assert git("rev-parse", "HEAD", cwd=root) == new == git("rev-parse", "master", cwd=root)
    assert git("symbolic-ref", "--short", "HEAD", cwd=root) == "master" and changed_paths(root, *KEPT) == {}
    assert result.backup.has_bundle and git("rev-parse", f"refs/cdlbib/backups/{stamp}", cwd=root) == mine
    assert library.holds_only_copy(result.backup)                     # the backup is what keeps the commit: never pruned
    assert everything(root)["stash"] == ""
    api.undo_update(stamp)
    assert everything(root) == before and git("rev-parse", "HEAD", cwd=root) == mine


def test_only_local_commits_offer_no_send_and_a_rewritten_upstream_can_be_discarded(managed):
    """The upstream's history was replaced: the library's commit is not in it. Nothing is
    changed without a decision, and discard leaves the library on the upstream's commit."""
    home, upstream, ws = managed
    root, work = ws.root, upstream.parent / "upstream-work"
    conftest._git("commit", "--quiet", "--amend", "-m", "The same library, rewritten", cwd=work)
    conftest._git("push", "--quiet", "--force", str(upstream), "master", cwd=work)
    new = git("rev-parse", "master", cwd=upstream)
    checked(home, 25 * HOUR)
    before = everything(root)
    asked = pytest.raises(UpdateNeedsDecision, library.update, ws).value
    assert (asked.changed, asked.local_commits, asked.choices) == ([], 1, ("keep", "discard"))
    assert asked.rewritten and asked.entries_changed is None      # the commit is the upstream's own, not the user's
    assert str(asked) == (f"The history of the bibliography's upstream was changed, and the library in {root} matches "
                          "an older version of it. Nothing was changed.")
    assert cli.unsent_question(asked) == REWRITTEN_QUESTION
    assert verification_cli.unsent_line(asked) + "\n" == REWRITTEN_NOTICE
    assert everything(root) == before
    result = library.update(ws, decision="discard", seen=asked.seen)
    stamp = backup_names(home)[0]
    assert result.message == (f"moved the bibliography to the upstream's new history (1 new commit; the library as it "
                              f"was is backup {stamp}; `cdlbib update --undo {stamp}` puts it back)")
    assert git("rev-parse", "HEAD", cwd=root) == new and changed_paths(root, ".") == {}
    api.undo_update()
    assert everything(root) == before


@pytest.mark.parametrize("change", ["another edit", "the upstream moved again", "the edits are gone"])
@pytest.mark.parametrize("decision", ["update", "discard"])
def test_a_decision_is_not_applied_to_a_state_the_user_was_not_shown(managed, decision, change):
    home, upstream, ws, new = unsent(managed)
    root = ws.root
    asked = pytest.raises(UpdateNeedsDecision, library.update, ws).value
    if change == "another edit":                                      # while the question was open
        write(root, "verification/tracked.txt", "edited again, after the question\n")
    elif change == "the upstream moved again":
        advance(upstream, "One more", **{"verification/more.txt": "more\n"})
    else:
        conftest._git("restore", "--", "cdl.bib", "verification/tracked.txt", cwd=root)
        shutil.rmtree(root / "verification/notes")
    before, state = everything(root), (home / "state.json").read_bytes()
    result = library.update(ws, decision=decision, seen=asked.seen)
    assert result.action == "left_alone" and result.backup is None
    count = "3 new commits" if change == "the upstream moved again" else "2 new commits"
    assert result.message == (f"a newer version of the bibliography is available ({count}), but the library or the "
                              "upstream changed after you were asked what to do; nothing was changed. Run `cdlbib "
                              "update` to be asked again.")
    assert everything(root) == before and backup_names(home) == []
    assert (home / "state.json").read_bytes() == state               # nothing recorded: the next command asks


@pytest.mark.parametrize("decision", ["update", "discard"])
def test_a_git_command_that_cannot_start_changes_nothing(managed, decision):
    """Another git command holds the index: git refuses before it changes anything. The
    library is checked to be as it was; the backup stays and is named."""
    home, upstream, ws, new = unsent(managed)
    root, before = ws.root, everything(ws.root)
    (root / ".git" / "index.lock").write_text("", encoding="utf-8")
    with pytest.raises(CdlbibError) as raised:
        library.update(ws, decision=decision)
    (root / ".git" / "index.lock").unlink()
    stamp = backup_names(home)[-1]
    assert not isinstance(raised.value, UpdateConflict)
    assert str(raised.value).startswith("The bibliography was not updated: git restore failed: ")
    assert str(raised.value).endswith("The library is as it was (changes that were staged may now be unstaged); "
                                      f"a copy of it is backup {stamp}.")
    assert everything(root) == before and lock_is_free(home)


REFUSE_MASTER = ('#!/bin/sh\n[ "$1" = prepared ] || exit 0\nwhile read old new ref; do\n'
                 '  [ "$ref" = refs/heads/master ] && exit 1\ndone\nexit 0\n')


@pytest.mark.parametrize("decision, local_commit", [("update", False), ("discard", False), ("discard", True)])
def test_a_failure_after_the_edits_were_set_aside_puts_every_one_back(managed, decision, local_commit):
    """git itself refuses to move the branch (a hook of the repository says no) after the edits
    were set aside and, for a fast-forward, after the files were already the new version's.
    Every file is put back from the backup and checked."""
    home, upstream, ws, new = unsent(managed)
    root = ws.root
    if local_commit:
        conftest._git("commit", "--quiet", "-m", "Mine", "--", "cdl.bib", cwd=root)
    before = everything(root)
    hook = root / ".git" / "hooks" / "reference-transaction"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(REFUSE_MASTER, encoding="utf-8")
    hook.chmod(0o755)
    with pytest.raises(CdlbibError) as raised:
        library.update(ws, decision=decision)
    hook.unlink()
    stamp = backup_names(home)[-1]
    assert str(raised.value).startswith("The bibliography was not updated: ")
    assert str(raised.value).endswith("The library is as it was (changes that were staged may now be unstaged); "
                                      f"a copy of it is backup {stamp}.")
    assert everything(root) == before and lock_is_free(home)
    assert library.update(ws, decision=decision).action == "updated"   # and without the hook it goes through
    api.undo_update()
    assert everything(root) == before


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs file permissions that bind")
@pytest.mark.parametrize("decision", ["update", "discard"])
def test_a_failure_that_cannot_be_put_back_names_the_backup_and_its_undo_works(managed, tmp_path, decision):
    """verification/ cannot be written: git puts cdl.bib back to the commit and then fails, and
    the put-back fails the same way. The message names the backup; once the folder can be
    written again, the command it names returns every byte."""
    home, upstream, ws, new = unsent(managed)
    root, before = ws.root, everything(ws.root)
    os.chmod(root / "verification", 0o555)
    try:
        with pytest.raises(CdlbibError) as raised:
            library.update(ws, decision=decision)
    finally:
        os.chmod(root / "verification", 0o755)
    stamp = backup_names(home)[0]
    assert f"`cdlbib update --undo {stamp}` puts it back." in str(raised.value)
    assert "could not be put back as it was" in str(raised.value)
    assert (root / "cdl.bib").read_text(encoding="utf-8") == BASE     # this is the state the message is about
    undone = cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path))
    assert undone.returncode == 0, undone.stderr
    assert everything(root) == before


@pytest.mark.parametrize("decision, local_commit", [("update", False), ("discard", False), ("discard", True)])
def test_the_git_commands_of_update_and_keep_and_of_discard_cannot_lose_work(managed, tmp_path, monkeypatch,
                                                                             decision, local_commit):
    """Every git command the two decisions run, as git itself traces them."""
    home, upstream, ws, new = unsent(managed)
    if local_commit:
        conftest._git("commit", "--quiet", "-m", "Mine", "--", "cdl.bib", cwd=ws.root)
    old = git("rev-parse", "HEAD", cwd=ws.root)
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv("GIT_TRACE", str(trace))
    assert library.update(ws, decision=decision).action == "updated"
    monkeypatch.delenv("GIT_TRACE")
    ran = [line.split("built-in: git ", 1)[1] for line in trace.read_text(encoding="utf-8").splitlines()
           if "built-in: git " in line]
    verbs = {command.split()[0] for command in ran}
    assert not verbs & {"reset", "clean", "stash", "pull", "checkout", "rebase", "push", "commit", "gc", "add", "rm"}
    assert not [c for c in ran if "--force" in c or " -f" in c or " +" in c or " -D" in c or "--hard" in c]
    changing = verbs & {"restore", "merge", "switch", "update-ref", "branch", "fetch", "merge-file", "bundle"}
    if local_commit:
        assert changing == {"bundle", "fetch", "restore", "switch", "update-ref"}
    else:
        assert changing == {"fetch", "merge", "restore", "update-ref"} | ({"merge-file"} if decision == "update" else set())
    assert [c for c in ran if c.split()[0] == "restore"] == [
        f"restore --source={old} --staged --worktree -- cdl.bib verification"]
    for command in ran:
        if command.split()[0] == "merge":
            assert command.startswith("merge --ff-only --no-overwrite-ignore --no-autostash --quiet ")
        if command.split()[0] == "switch":
            assert command.startswith("switch --quiet --no-overwrite-ignore ")
        if command.split()[0] == "update-ref" and "refs/heads/" in command:      # a compare-and-swap: new, then old
            assert command == f"update-ref -m 'cdlbib update' refs/heads/master {new} {old}"
    assert git("stash", "list", cwd=ws.root) == ""


# --- the question, on the command line -------------------------------------------------------

LISTED = "  cdl.bib (1 entry changed)\n  verification/notes/my new file.jsonl\n  verification/tracked.txt\n"
QUESTION = ("A newer version of the bibliography is available (2 new commits), and you have changes that have not "
            "been sent:\n" + LISTED + "What would you like to do?\n"
            "  [k] Keep working without updating (ask again tomorrow)\n"
            "  [u] Update and keep my changes\n"
            "  [s] Send my changes first (runs `cdlbib send`)\n"
            "  [d] Discard my changes and update (they are saved first; `cdlbib update --undo` brings them back)\n"
            "Your choice [k/u/s/d]: ")
NOTICE = ("a newer version of the bibliography is available (2 new commits), but these files have changes that have "
          "not been sent: cdl.bib (1 entry changed), verification/notes/my new file.jsonl, verification/tracked.txt; "
          "nothing was changed. Run `cdlbib update` in a terminal to choose what to do.\n")


def at_a_terminal(*args, cwd, answers, during=None, interrupt=False, **env):
    """Run the command with a real pseudo-terminal as its stdin and stderr. ``answers`` are
    typed once the question is on the screen (after ``during()``, when given). Returns (exit
    code, stdout, everything the terminal showed)."""
    import pty
    import threading
    leader, follower = pty.openpty()
    shown = bytearray()

    def read():
        while True:
            try:
                data = os.read(leader, 4096)
            except OSError:                                           # the terminal was closed (Linux says so this way)
                return
            if not data:
                return
            shown.extend(data)

    run = subprocess.Popen([CDLBIB, *args], cwd=cwd, stdin=follower, stderr=follower, stdout=subprocess.PIPE,
                           env=dict(os.environ, **env))
    os.close(follower)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 120
        while b"Your choice" not in shown and run.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert b"Your choice" in shown, f"no question was asked: {bytes(shown)!r}"
        if during:
            during()
        if interrupt:
            import signal
            time.sleep(0.5)                                           # the prompt is out; the command is reading
            run.send_signal(signal.SIGINT)                            # what Ctrl-C sends
        os.write(leader, answers)
        out = run.communicate(timeout=300)[0]
    finally:
        if run.poll() is None:
            run.kill()
            run.wait()
        reader.join(timeout=30)
        os.close(leader)
    return run.returncode, out.decode(), bytes(shown).decode().replace("\r\n", "\n")


def test_no_terminal_nothing_is_asked_or_changed_and_the_command_runs(managed, tmp_path):
    home, upstream, ws, new = unsent(managed, mine=BASE + "% a note of mine\n")
    before, started = everything(ws.root), datetime.datetime.now(UTC)
    notice = NOTICE.replace("cdl.bib (1 entry changed)", "cdl.bib")       # a comment line: no entry changed
    out = cdlbib("verify", "--no-citations", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and "looks good!" in out.stdout, out.stdout + out.stderr       # the exit code is the command's
    assert out.stderr.splitlines(keepends=True)[0] == notice and "What would you like" not in out.stdout + out.stderr
    assert everything(ws.root) == before and backup_names(home) == []
    assert started <= library.read_state().last_check                # said once a day, not with every command
    again = cdlbib("where", cwd=empty_folder(tmp_path))
    assert (again.returncode, again.stderr) == (0, "")
    checked(home, 25 * HOUR)                                          # the next day: said again, still nothing changed
    assert cdlbib("where", cwd=empty_folder(tmp_path)).stderr == notice
    assert everything(ws.root) == before and backup_names(home) == []


def test_no_option_answers_the_question(managed, tmp_path):
    """--ask is about installs and the fork; --yes does not exist. Neither chooses what
    happens to someone's edits."""
    home, upstream, ws, new = unsent(managed)
    before = everything(ws.root)
    out = cdlbib("--ask", "where", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and out.stderr == NOTICE
    checked(home, 25 * HOUR)
    out = cdlbib("--yes", "where", cwd=empty_folder(tmp_path))
    assert out.returncode == 2 and "No such option" in out.stderr
    out = cdlbib("update", "--yes", cwd=empty_folder(tmp_path))
    assert out.returncode == 2 and "No such option" in out.stderr
    assert everything(ws.root) == before and backup_names(home) == []


def test_cdlbib_update_with_no_terminal_changes_nothing_and_exits_1(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    before, state = everything(ws.root), (home / "state.json").read_bytes()
    out = cdlbib("update", cwd=empty_folder(tmp_path))
    assert (out.returncode, out.stdout, out.stderr) == (1, "", NOTICE)   # asked to update, and it could not
    assert everything(ws.root) == before and backup_names(home) == []
    assert (home / "state.json").read_bytes() == state               # a `cdlbib update` that did nothing records nothing


def test_at_a_terminal_k_keeps_working(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    before = everything(ws.root)
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"k\n")
    assert code == 0 and out.splitlines()[0] == str(ws.root)          # the command ran, on the copy on disk
    assert shown == (QUESTION + "k\nthe bibliography was not updated and your changes are as they were; nothing was "
                     "changed. You will be asked again tomorrow; `cdlbib update` asks now.\n")
    assert everything(ws.root) == before and backup_names(home) == []
    again = cdlbib("where", cwd=empty_folder(tmp_path))                # not asked again today
    assert (again.returncode, again.stderr) == (0, "")
    code, out, shown = at_a_terminal("update", cwd=empty_folder(tmp_path), answers=b"K\n")   # `cdlbib update` asks now
    assert code == 0 and shown.startswith(QUESTION) and "nothing was changed" in out
    assert everything(ws.root) == before


def test_at_a_terminal_u_updates_and_keeps_the_changes(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    root, before = ws.root, everything(ws.root)
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"u\n")
    stamp = backup_names(home)[0]
    assert code == 0 and shown == (
        QUESTION + "u\nupdated the bibliography: 2 new commits, with your changes kept (cdl.bib, verification/notes/my "
        f"new file.jsonl, verification/tracked.txt) (the library as it was is backup {stamp}; `cdlbib update --undo "
        f"{stamp}` puts it back)\n")
    assert git("rev-parse", "HEAD", cwd=root) == new and (root / "cdl.bib").read_bytes() == (THEIRS + MINE).encode()
    assert (everything(root)["stash"], everything(root)["markers"]) == ("", [])
    assert cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before


def test_at_a_terminal_u_with_a_collision_says_which_entry_and_the_command_carries_on(managed, tmp_path):
    home, upstream, ws, new = unsent(managed, mine=BASE.replace("{1990}", "{1991}"))
    before = everything(ws.root)
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"u\n")
    assert code == 0 and out.splitlines()[0] == str(ws.root)
    assert shown.endswith(
        "Your choice [k/u/s/d]: u\nThe bibliography was not updated: this entry was changed both by you and in the "
        "new version: Zoll90. Nothing was changed: your files are exactly as they were. Run `cdlbib send` to send "
        "your changes, or `cdlbib update` to choose again.\n")
    assert everything(ws.root) == before and backup_names(home) == []
    code, out, shown = at_a_terminal("update", cwd=empty_folder(tmp_path), answers=b"u\n")   # asked for: exit 1
    assert code == 1 and out == "" and "changed both by you and in the new version: Zoll90" in shown
    assert everything(ws.root) == before and backup_names(home) == []


def test_at_a_terminal_d_discards_and_names_the_backup_and_the_undo_command(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    root, before = ws.root, everything(ws.root)
    code, out, shown = at_a_terminal("update", cwd=empty_folder(tmp_path), answers=b"d\n")
    stamp = backup_names(home)[0]
    assert code == 0 and shown == QUESTION + "d\n"
    assert out == ("updated the bibliography: 2 new commits; discarded your changes to cdl.bib, verification/notes/my "
                   f"new file.jsonl, verification/tracked.txt (saved in backup {stamp}; `cdlbib update --undo {stamp}` "
                   "brings them back)\n")
    assert git("rev-parse", "HEAD", cwd=root) == new and changed_paths(root, ".") == {}
    assert cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before


def test_an_unknown_answer_asks_again(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    before = everything(ws.root)
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"yes\n\nx\nk\n")
    assert code == 0
    assert shown.count("What would you like to do?") == 1 and shown.count("Please answer k, u, s or d.\n") == 3
    assert shown.count("Your choice [k/u/s/d]: ") == 4
    assert everything(ws.root) == before and backup_names(home) == []


def test_end_of_input_at_the_question_aborts_with_nothing_changed(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    before, state = everything(ws.root), (home / "state.json").read_bytes()
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"\x04")
    assert code == 1 and out == "" and shown.endswith("Aborted.\n") and "Traceback" not in shown
    assert everything(ws.root) == before and backup_names(home) == []
    assert (home / "state.json").read_bytes() == state               # no answer was given: the next command asks again


def test_while_the_question_is_open_other_commands_are_not_blocked(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    before, took = everything(ws.root), []

    def meanwhile():
        started = time.monotonic()
        assert lock_is_free(home)
        listed = cdlbib("update", "--list", cwd=empty_folder(tmp_path))       # another cdlbib command runs at once
        took.append((time.monotonic() - started, listed.returncode))

    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"k\n", during=meanwhile)
    assert code == 0 and took[0][1] == 0 and took[0][0] < 30
    assert everything(ws.root) == before


def test_at_a_terminal_s_runs_the_send_and_updates_nothing(managed, tmp_path):
    """The send is the existing `cdlbib send`. Here it stops at its own gate (the new entry does
    not pass the format check), before any login, fork or push: the library's origin is a
    local folder, so no part of this test can reach GitHub."""
    home, upstream, ws, new = unsent(managed)
    root, before = ws.root, everything(ws.root)
    assert git("config", "--get", "remote.origin.url", cwd=root) == str(upstream)        # a local path, not GitHub
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"s\n", **IDENTITY)
    assert code == 1, out + shown
    assert shown.startswith(QUESTION + "s\nthe bibliography was not updated: your changes are sent first (`cdlbib send`)\n")
    assert "errors found" in out and "not sent: fix the format errors" in out
    assert str(ws.root) not in out.splitlines()[:1]                   # the send was the command: `where` did not run
    assert "pull request" not in out + shown and "fork" not in out + shown
    assert everything(root) == before and backup_names(home) == []    # not updated, every edit intact, on master
    again = cdlbib("where", cwd=empty_folder(tmp_path))                # the choice was recorded: not asked again today
    assert (again.returncode, again.stderr) == (0, "")


def test_the_question_for_local_commits_offers_what_can_be_done(managed, tmp_path):
    home, upstream, ws = managed
    unsent_work(ws.root)
    advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    checked(home, 25 * HOUR)
    before = everything(ws.root)
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"u\nk\n")
    assert code == 0 and shown.startswith(
        "A newer version of the bibliography is available (1 new commit), and you have changes that have not been sent:\n"
        "  1 commit that the upstream does not have\n"
        "  cdl.bib\n"
        "  verification/notes/new entry.jsonl\n"
        "What would you like to do?\n"
        "  [k] Keep working without updating (ask again tomorrow)\n"
        "  [s] Send my changes first (runs `cdlbib send`)\n"
        "  [d] Discard my changes and update (they are saved first; `cdlbib update --undo` brings them back)\n"
        "  (Updating and keeping your changes is not offered: the library has commits that the upstream does not have.)\n"
        "Your choice [k/s/d]: ")
    assert shown.count("Please answer k, s or d.\n") == 1             # "u" is not an answer here
    assert everything(ws.root) == before and backup_names(home) == []


# --- follow-ups from the re-review of the daily check ----------------------------------------

@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs file permissions that bind")
def test_an_old_backup_that_cannot_be_removed_is_a_note_and_the_undo_stands(managed, tmp_path):
    """The restore is done before old backups are pruned: a backup that cannot be deleted must
    not turn a completed restore into a traceback."""
    home, upstream, ws = managed
    root = ws.root
    clean = snapshot(root)
    for _ in range(library.KEEP):
        library.backup(ws)
    oldest, newest = home / "backups" / backup_names(home)[0], backup_names(home)[-1]
    write(root, "cdl.bib", conftest.ZOLL90 + "\n% work since the backup\n")
    oldest.chmod(0o500)                                               # nothing in it can be deleted
    try:
        out = cdlbib("update", "--undo", cwd=empty_folder(tmp_path))
        notes = []
        made = library.backup(ws, notes)                              # a plain backup: made, and the same note
    finally:
        oldest.chmod(0o700)
    note = f"note: the old backup {oldest} could not be removed (Permission denied"
    assert out.returncode == 0 and "Traceback" not in out.stderr, out.stdout + out.stderr
    assert out.stdout.splitlines()[0].startswith(f"restored backup {newest} (")
    assert out.stdout.splitlines()[2] == "run `cdlbib update --undo` again to return to it"
    assert out.stderr.startswith(note) and out.stderr.endswith("); it was left there\n") and out.stderr.count("\n") == 1
    assert snapshot(root) == clean                                    # the restore completed: the backup's state
    assert made.stamp == backup_names(home)[-1] and len(notes) == 1 and notes[0].startswith(note)
    assert oldest.name in backup_names(home) and (oldest / "ref.json").is_file()   # still whole
    api.undo(backup_names(home)[-2])                                  # with the folder deletable again: no note
    assert api.undo(backup_names(home)[-2]).notes == []


def test_a_list_of_only_unreadable_backups_does_not_call_them_backups_to_restore(managed, tmp_path):
    home, upstream, ws = managed
    only = library.backup(ws)
    (only.path / "ref.json").unlink()
    listed = cdlbib("update", "--list", cwd=tmp_path)
    assert (listed.returncode, listed.stderr) == (0, "")
    assert listed.stdout.splitlines() == [
        f"0 readable backups of {ws.root} and 1 unreadable, newest first (kept in {home.resolve() / 'backups'}):",
        f"  {only.stamp}: unreadable (it has no ref.json)"]
    missing = cdlbib("update", "--undo", "20200101T000000.000000Z", cwd=tmp_path)    # no such folder: still "no backup"
    assert missing.returncode == 1 and missing.stderr.startswith("There is no backup 20200101T000000.000000Z of ")



# --- after a send -----------------------------------------------------------------------------
#
# `cdlbib send` leaves the library on a branch cdlbib/<login>/<topic>. What the update does
# there depends on that branch's pull request. Here the pull request's state is given to
# library._after_send as plain arguments (no GitHub call); the branches, the upstream and
# every git command are real. The upstream "merges" the way GitHub does: by a squash (a new
# commit with the same content, so the branch's own commit is on no branch of the upstream)
# or by taking the branch's commit itself.

SENT = "cdlbib/tester/2026-10-02-my-own-entry"
PR = "https://github.com/an-owner/a-library/pull/7"
LATER = "\n@article{Later26,\n\tAuthor = {B Person},\n\tJournal = {Journal of Tests},\n\tTitle = {A later entry},\n\tYear = {2026}}\n"


def sent(managed, merged="squash"):
    """The managed library as a send leaves it: on SENT, with one commit of its own (cdl.bib
    gains an entry). The upstream then merges it ("squash" or "merge"; None: it does not) and
    gains one more commit. Gives (home, upstream, ws, the branch's commit, the upstream's)."""
    home, upstream, ws = managed
    root, work = ws.root, upstream.parent / "upstream-work"
    conftest._git("switch", "--quiet", "-c", SENT, cwd=root)
    write(root, "cdl.bib", BASE + MINE)
    conftest._git("commit", "--quiet", "-m", "My own entry", "--", "cdl.bib", cwd=root)
    tip = git("rev-parse", "HEAD", cwd=root)
    if merged == "merge":
        conftest._git("fetch", "--quiet", str(root), SENT, cwd=work)
        conftest._git("merge", "--quiet", "--ff-only", "FETCH_HEAD", cwd=work)
        conftest._git("push", "--quiet", str(upstream), "master", cwd=work)
    elif merged == "squash":
        advance(upstream, "My own entry (#7)", **{"cdl.bib": BASE + MINE})
    new = advance(upstream, "Something else", **{"verification/new.txt": "new\n"})
    conftest._git("fetch", "--quiet", "origin", cwd=root)       # the refs a test compares do not move with the update's fetch
    checked(home, 25 * HOUR)
    return home, upstream, ws, tip, new


def after_send(ws, state, head, **options):
    return library._after_send(ws, state, url=PR, head=head, **options)


def back_line(count, note, stamp, middle=""):
    return (f"your pull request {PR} was merged: the library is back on branch master, up to date with the upstream "
            f"({count} new commit{'' if count == 1 else 's'}){middle}; {note} (the library as it was is backup {stamp}; "
            f"`cdlbib update --undo {stamp}` puts it back)")


def test_merged_by_a_squash_the_library_returns_to_main_and_the_branch_is_kept(managed, tmp_path, capsys):
    home, upstream, ws, tip, new = sent(managed, "squash")
    root, before, started = ws.root, everything(ws.root), datetime.datetime.now(UTC)
    old_master = before["snapshot"]["branches"]["master"]
    result = after_send(ws, "merged", tip)
    stamp = backup_names(home)[0]
    assert (result.action, result.new_commits, result.backup.stamp) == ("returned_to_main", 2, stamp)
    assert result.message == back_line(2, f"branch {SENT} was kept (git does not count a squash-merged branch as "
                                          "merged); everything on it is in the merged pull request, so it is safe to "
                                          "delete", stamp)
    assert capsys.readouterr() == ("", "")
    after = snapshot(root)
    assert (after["branch"], after["commit"], after["changed"]) == ("master", new, [])
    assert after["branches"] == {"master": new, SENT: tip}            # the squash-merged branch is still there, untouched
    assert (root / "cdl.bib").read_text(encoding="utf-8") == BASE + MINE and (root / "verification/new.txt").is_file()
    assert (result.backup.branch, result.backup.commit, result.backup.moved) == (SENT, tip, [("master", old_master)])
    assert git("rev-parse", f"refs/cdlbib/backups/{stamp}", cwd=root) == tip       # the backup keeps the branch's commit
    assert started <= library.read_state().last_check and git("stash", "list", cwd=root) == ""
    undone = cdlbib("update", "--undo", cwd=empty_folder(tmp_path))
    assert undone.returncode == 0, undone.stderr
    assert everything(root) == before                                 # the branch it was on, master where it was, every byte


def test_merged_with_its_own_commit_the_branch_is_deleted_and_undo_brings_it_back(managed, tmp_path):
    home, upstream, ws, tip, new = sent(managed, "merge")
    root, before = ws.root, everything(ws.root)
    result = after_send(ws, "merged", tip)
    stamp = backup_names(home)[0]
    assert result.action == "returned_to_main" and result.message == back_line(1, f"branch {SENT} was deleted", stamp)
    assert snapshot(root)["branches"] == {"master": new} and snapshot(root)["branch"] == "master"
    assert git("merge-base", "--is-ancestor", tip, "master", cwd=root) == ""      # nothing of the branch is lost
    assert cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before                                 # the send branch exists again, on its commit


def test_a_branch_behind_the_pull_requests_head_is_returned_too(managed):
    """Someone pushed a further commit to the pull request before it was merged: the local
    branch is an ancestor of the pull request's head, so it holds nothing that was not merged."""
    home, upstream, ws, tip, new = sent(managed, "merge")
    result = after_send(ws, "merged", git("rev-parse", "origin/master", cwd=ws.root))
    assert result.action == "returned_to_main" and snapshot(ws.root)["branches"] == {"master": new}


def test_an_open_pull_request_changes_nothing_and_says_where_it_is(managed, tmp_path):
    home, upstream, ws, tip, new = sent(managed, None)
    before, started = whole_clone(ws.root), datetime.datetime.now(UTC)
    result = after_send(ws, "open", tip)
    assert (result.action, result.backup, result.new_commits) == ("left_alone", None, 1)
    assert result.message == f"your pull request is still open: {PR}; nothing was changed"
    assert whole_clone(ws.root) == before and backup_names(home) == []
    assert started <= library.read_state().last_check                # said once a day
    write(ws.root, "cdl.bib", BASE + MINE + LATER)                    # further edits: still nothing to decide (send adds them)
    before = whole_clone(ws.root)
    several = after_send(ws, "open", tip, matching=3)
    assert several.message == f"your pull request is still open: {PR} (one of 3 from branch {SENT}); nothing was changed"
    assert whole_clone(ws.root) == before and backup_names(home) == []


def test_a_branch_that_was_never_sent_is_left_alone(managed):
    home, upstream, ws, tip, new = sent(managed, None)
    before = whole_clone(ws.root)
    result = library._after_send(ws, None)
    assert result.action == "left_alone" and result.message == (
        f"the library is on branch {SENT}, which has no pull request in the upstream; nothing was changed. Run "
        f"`cdlbib send` to send it, or `git -C {shlex.quote(str(ws.root))} switch master` to leave the branch.")
    assert whole_clone(ws.root) == before and backup_names(home) == []


def test_a_closed_pull_request_asks_and_changes_nothing(managed, tmp_path):
    home, upstream, ws, tip, new = sent(managed, None)
    root, before, state = ws.root, whole_clone(ws.root), (home / "state.json").read_bytes()
    with pytest.raises(UpdateNeedsDecision) as raised:
        after_send(ws, "closed", tip)
    asked = raised.value
    assert (asked.branch, asked.pull_request, asked.state, asked.default) == (SENT, PR, "closed", "master")
    assert (asked.changed, asked.local_commits, asked.new_commits, asked.entries_changed) == ([], 1, 1, 1)
    assert asked.choices == ("keep", "discard") and asked.seen
    assert str(asked) == (f"Your pull request {PR} was closed without being merged, so the changes on branch {SENT} "
                          f"of the library in {root} are not in the bibliography. Nothing was changed.")
    assert whole_clone(root) == before and backup_names(home) == []
    assert (home / "state.json").read_bytes() == state and lock_is_free(home)
    assert cli.unsent_question(asked) == (
        f"Your pull request {PR} was closed without being merged, so your changes on branch {SENT} are not in the "
        "bibliography:\n"
        "  1 commit that the upstream does not have (1 entry of cdl.bib changed)\n"
        "What would you like to do?\n"
        "  [k] Keep working without updating (ask again tomorrow)\n"
        "  [d] Discard my changes and update (they are saved first; `cdlbib update --undo` brings them back)\n"
        "  (Updating and keeping your changes is not offered: the branch has commits that the upstream does not have.)\n"
        "  (Sending is not offered: the pull request was closed, and a new change needs a new branch.)\n"
        "  (Updating or discarding puts the library back on branch master; your changes are saved in a backup first.)")
    assert verification_cli.unsent_line(asked) == (
        f"your pull request {PR} was closed without being merged, so the library stays on branch {SENT} (1 commit "
        "that the upstream does not have); nothing was changed. Run `cdlbib update` in a terminal to choose what to do.")

    kept = after_send(ws, "closed", tip, decision="keep", seen=asked.seen)
    assert kept.action == "left_alone" and whole_clone(root) == before and backup_names(home) == []
    assert library.update(ws) == library.UpdateResult("not_due")     # not asked again today

    before = everything(root)
    done = after_send(ws, "closed", tip, decision="discard", seen=asked.seen)
    stamp = backup_names(home)[0]
    assert done.action == "returned_to_main" and done.message == (
        f"your pull request {PR} was closed without being merged: the library is back on branch master, up to date "
        f"with the upstream (1 new commit); branch {SENT} was kept: it holds 1 commit that the upstream does not have "
        f"(the library as it was is backup {stamp}; `cdlbib update --undo {stamp}` puts it back)")
    assert snapshot(root)["branches"] == {"master": new, SENT: tip} and snapshot(root)["branch"] == "master"
    assert (root / "cdl.bib").read_text(encoding="utf-8") == BASE     # the upstream's, without the unmerged entry
    assert cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before


@pytest.mark.parametrize("more", ["an edit", "an untracked file", "a staged edit"])
def test_merged_with_further_edits_asks_and_update_carries_them_to_main(managed, tmp_path, more):
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    if more == "an untracked file":
        write(root, "verification/notes/my new file.jsonl", '{"key": "Later26"}\n')
        changed = ["verification/notes/my new file.jsonl"]
    else:
        write(root, "cdl.bib", BASE + MINE + LATER)
        changed = ["cdl.bib"]
        if more == "a staged edit":
            conftest._git("add", "cdl.bib", cwd=root)
    before, clone, state = everything(root), whole_clone(root), (home / "state.json").read_bytes()
    with pytest.raises(UpdateNeedsDecision) as raised:
        after_send(ws, "merged", tip)
    asked = raised.value
    assert (asked.branch, asked.state, asked.changed, asked.local_commits, asked.new_commits) == (SENT, "merged", changed, 0, 2)
    assert asked.entries_changed == (None if more == "an untracked file" else 1)     # counted from the branch's commit
    assert asked.choices == ("keep", "update", "send", "discard")
    assert whole_clone(root) == clone and backup_names(home) == [] and (home / "state.json").read_bytes() == state
    listed = "  verification/notes/my new file.jsonl\n" if more == "an untracked file" else "  cdl.bib (1 entry changed)\n"
    assert cli.unsent_question(asked) == (
        f"Your pull request {PR} was merged, and you have changes on branch {SENT} that have not been sent:\n" + listed
        + "What would you like to do?\n"
        "  [k] Keep working without updating (ask again tomorrow)\n"
        "  [u] Update and keep my changes\n"
        "  [s] Send my changes first (runs `cdlbib send`)\n"
        "  [d] Discard my changes and update (they are saved first; `cdlbib update --undo` brings them back)\n"
        "  (Updating or discarding puts the library back on branch master; your changes are saved in a backup first.)")
    assert verification_cli.unsent_line(asked) == (
        f"your pull request {PR} was merged, but branch {SENT} has changes that have not been sent (these files have "
        f"changes that have not been sent: {listed.strip()}); nothing was changed. Run `cdlbib update` in a terminal "
        "to choose what to do.")

    done = after_send(ws, "merged", tip, decision="update", seen=asked.seen)
    stamp = backup_names(home)[0]
    assert done.action == "returned_to_main" and done.message == back_line(
        2, f"branch {SENT} was kept (git does not count a squash-merged branch as merged); everything on it is in the "
           "merged pull request, so it is safe to delete", stamp, middle=f", with your changes kept ({changed[0]})")
    after = snapshot(root)
    assert (after["branch"], after["commit"], after["changed"], after["branches"]) == ("master", new, changed, {"master": new, SENT: tip})
    if more == "an untracked file":
        assert (root / changed[0]).read_text(encoding="utf-8") == '{"key": "Later26"}\n'
    else:
        assert (root / "cdl.bib").read_text(encoding="utf-8") == BASE + MINE + LATER      # the edit, on the new version
    assert (root / "verification/new.txt").is_file() and markers(root) == [] and git("stash", "list", cwd=root) == ""
    assert cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before


def test_merged_with_further_edits_discard_returns_without_them_and_undo_brings_them_back(managed, tmp_path):
    home, upstream, ws, tip, new = sent(managed, "merge")
    root = ws.root
    write(root, "cdl.bib", BASE + MINE + LATER)
    write(root, "verification/notes/my new file.jsonl", '{"key": "Later26"}\n')
    before = everything(root)
    done = after_send(ws, "merged", tip, decision="discard")
    stamp = backup_names(home)[0]
    assert done.action == "returned_to_main" and done.message == back_line(
        1, f"branch {SENT} was deleted", stamp,
        middle="; discarded your changes to cdl.bib, verification/notes/my new file.jsonl")
    after = snapshot(root)
    assert (after["branch"], after["commit"], after["changed"], after["branches"]) == ("master", new, [], {"master": new})
    assert not (root / "verification/notes").exists()
    assert cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before


def test_a_commit_made_after_the_pull_requests_head_is_never_treated_as_merged(managed, tmp_path):
    """GitHub says merged, but the branch holds a commit the pull request never had: that is
    the person's work. Nothing is done without a decision, 'update' is not offered, and a
    discard keeps the branch (and the backup keeps the commit)."""
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    write(root, "cdl.bib", BASE + MINE + LATER)
    conftest._git("commit", "--quiet", "-m", "A later entry", "--", "cdl.bib", cwd=root)
    later = git("rev-parse", "HEAD", cwd=root)
    conftest._git("fetch", "--quiet", "origin", cwd=root)
    before, clone = everything(root), whole_clone(root)
    with pytest.raises(UpdateNeedsDecision) as raised:
        after_send(ws, "merged", tip)                                 # the pull request's head is the earlier commit
    asked = raised.value
    assert (asked.state, asked.changed, asked.local_commits, asked.choices) == ("merged", [], 1, ("keep", "discard"))
    assert whole_clone(root) == clone and backup_names(home) == []
    assert "  (Sending is not offered: the branch has commits that the upstream does not have.)" in cli.unsent_question(asked)
    assert verification_cli.unsent_line(asked) == (
        f"your pull request {PR} was merged, but branch {SENT} has changes that have not been sent (1 commit that the "
        "upstream does not have); nothing was changed. Run `cdlbib update` in a terminal to choose what to do.")
    refused = after_send(ws, "merged", tip, decision="update")
    assert refused.action == "left_alone" and refused.message == (
        f"your pull request {PR} was merged, but branch {SENT} has 1 commit that the upstream does not have, which "
        "cannot be kept on top of the new version; nothing was changed. Run `cdlbib update` and choose again.")
    assert whole_clone(root) == clone and backup_names(home) == []
    with pytest.raises(UpdateNeedsDecision):                          # a head that is not a commit at all decides nothing
        after_send(ws, "merged", "")
    assert whole_clone(root) == clone and backup_names(home) == []

    done = after_send(ws, "merged", tip, decision="discard", seen=asked.seen)
    stamp = backup_names(home)[0]
    assert done.action == "returned_to_main" and f"branch {SENT} was kept: it holds 1 commit that the upstream does not have" in done.message
    assert snapshot(root)["branches"] == {"master": new, SENT: later}
    assert git("rev-parse", f"refs/cdlbib/backups/{stamp}", cwd=root) == later
    assert cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before


def test_an_edit_that_collides_with_the_new_version_changes_nothing(managed):
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    advance(upstream, "An edit to the entry", **{"cdl.bib": (BASE + MINE).replace("My own entry", "My own entry, retitled")})
    conftest._git("fetch", "--quiet", "origin", cwd=root)
    write(root, "cdl.bib", (BASE + MINE).replace("My own entry", "My entry, renamed by me"))
    before = whole_clone(root)
    with pytest.raises(UpdateConflict) as raised:
        after_send(ws, "merged", tip, decision="update")
    assert raised.value.entries == ["Mine26"] and str(raised.value) == (
        "The bibliography was not updated: this entry was changed both by you and in the new version: Mine26. Nothing "
        "was changed: your files are exactly as they were. Run `cdlbib update` to choose again.")
    assert whole_clone(root) == before and backup_names(home) == [] and markers(root) == []


@pytest.mark.parametrize("change", ["another edit", "the upstream moved again", "a new commit on the branch"])
def test_a_decision_about_a_send_branch_is_not_applied_to_a_state_the_user_was_not_shown(managed, change):
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    write(root, "cdl.bib", BASE + MINE + LATER)
    with pytest.raises(UpdateNeedsDecision) as raised:
        after_send(ws, "merged", tip)
    if change == "another edit":
        write(root, "cdl.bib", BASE + MINE + LATER + "% one more line\n")
    elif change == "the upstream moved again":
        advance(upstream, "Yet another", **{"verification/more.txt": "more\n"})
    else:
        conftest._git("commit", "--quiet", "-m", "A later entry", "--", "cdl.bib", cwd=root)
    before = everything(root)
    for decision in ("update", "discard"):
        result = after_send(ws, "merged", tip, decision=decision, seen=raised.value.seen)
        assert result.action == "left_alone" and result.message == (
            f"your pull request {PR} was merged, but the library or the upstream changed after you were asked what to "
            "do; nothing was changed. Run `cdlbib update` to be asked again.")
        assert everything(root) == before and backup_names(home) == []


def test_a_file_of_the_users_in_the_way_of_the_return_is_a_refusal_before_any_backup(managed):
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    advance(upstream, "A readme", **{"notes.txt": "the upstream's notes\n"})
    conftest._git("fetch", "--quiet", "origin", cwd=root)
    write(root, "notes.txt", "MY NOTES\n")                            # untracked, and the new version has a file there
    before = whole_clone(root)
    result = after_send(ws, "merged", tip)
    assert result.action == "left_alone" and result.message == (
        f"your pull request {PR} was merged, but returning to branch master would overwrite your own notes.txt; nothing "
        "was changed. Move that file out of the way, then run `cdlbib update`.")
    assert whole_clone(root) == before and backup_names(home) == []
    assert (root / "notes.txt").read_text(encoding="utf-8") == "MY NOTES\n"


def test_a_switch_that_git_refuses_changes_nothing_and_keeps_no_backup(managed, tmp_path):
    """master is checked out in another worktree of the library, so git will not switch to
    it: the library stays on the send branch, exactly as it was, and the line says why."""
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    conftest._git("worktree", "add", "--quiet", str(tmp_path / "elsewhere"), "master", cwd=root)
    before = whole_clone(root)
    result = after_send(ws, "merged", tip)
    assert result.action == "left_alone" and result.backup is None
    assert result.message.startswith(f"your pull request {PR} was merged, but git switch failed: ")
    assert result.message.endswith("; nothing was changed. Run `cdlbib update` to try again.")
    assert whole_clone(root) == before and backup_names(home) == []   # no backup, and no private ref, is left
    write(root, "cdl.bib", BASE + MINE + LATER)                       # with edits set aside first: they are put back
    before = everything(root)
    with pytest.raises(CdlbibError, match="The bibliography was not updated: git switch failed: .* The library is as it was"):
        after_send(ws, "merged", tip, decision="update")
    assert everything(root) == before and (root / "cdl.bib").read_text(encoding="utf-8") == BASE + MINE + LATER


@pytest.mark.parametrize("state", ["commits of its own", "no such branch"])
def test_a_main_branch_that_cannot_be_fast_forwarded_is_left_alone(managed, state):
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    if state == "commits of its own":
        conftest._git("switch", "--quiet", "master", cwd=root)
        write(root, "verification/mine.txt", "mine\n")
        conftest._git("add", "verification/mine.txt", cwd=root)
        conftest._git("commit", "--quiet", "-m", "Mine, on master", cwd=root)
        conftest._git("switch", "--quiet", SENT, cwd=root)
        why = "it has commits that the upstream does not have"
    else:
        conftest._git("branch", "--quiet", "-m", "master", "kept-aside", cwd=root)
        why = "there is no local branch master"
    before = whole_clone(root)
    result = after_send(ws, "merged", tip)
    assert result.action == "left_alone" and result.message == (
        f"your pull request {PR} was merged, but the library could not be put back on branch master ({why}); nothing "
        f"was changed. To update, run `git -C {shlex.quote(str(root))} switch master`, then `cdlbib update`.")
    assert whole_clone(root) == before and backup_names(home) == []


def test_the_git_commands_of_a_return_to_main_cannot_lose_work(managed, tmp_path, monkeypatch):
    """Every git command the return runs, as git itself traces them: with edits kept
    (the most there is to run) on a squash-merged branch."""
    home, upstream, ws, tip, new = sent(managed, "squash")
    write(ws.root, "cdl.bib", BASE + MINE + LATER)
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv("GIT_TRACE", str(trace))
    assert after_send(ws, "merged", tip, decision="update").action == "returned_to_main"
    monkeypatch.delenv("GIT_TRACE")
    ran = [line.split("built-in: git ", 1)[1] for line in trace.read_text(encoding="utf-8").splitlines()
           if "built-in: git " in line]
    verbs = {command.split()[0] for command in ran}
    assert not verbs & {"reset", "clean", "stash", "pull", "checkout", "rebase", "push", "commit", "gc", "add", "rm"}
    assert not [c for c in ran if "--force" in c or " -f" in c or " +" in c or " -D" in c or "--hard" in c or " -C" in c
                or " -M" in c]
    assert verbs & {"restore", "merge", "switch", "update-ref", "branch", "fetch", "merge-file", "bundle"} == {
        "branch", "bundle", "fetch", "merge", "restore", "switch", "update-ref"}
    assert [c for c in ran if c.split()[0] == "switch"] == ["switch --quiet --no-overwrite-ignore master"]
    assert [c for c in ran if c.split()[0] == "merge"] == [f"merge --ff-only --no-overwrite-ignore --no-autostash --quiet {new}"]
    assert [c for c in ran if c.split()[0] == "branch"] == [f"branch --quiet -d {SENT}"]
    assert [c for c in ran if c.split()[0] == "restore"] == [f"restore --source={tip} --staged --worktree -- cdl.bib verification"]
    assert not [c for c in ran if c.split()[0] == "update-ref" and "refs/heads/" in c]      # only the backup's private refs
    assert [c for c in ran if c.split()[0] == "fetch"] == ["fetch --quiet origin"]


def test_only_the_managed_library_is_returned_and_only_from_a_send_branch(managed, tmp_path):
    home, upstream, ws = managed
    other = Workspace(clone_of(upstream, tmp_path / "mine"))
    conftest._git("switch", "--quiet", "-c", SENT, cwd=other.root)
    before = whole_clone(other.root)
    with pytest.raises(CdlbibError, match="Only the library cdlbib manages"):
        library._after_send(other, "merged", url=PR, head=git("rev-parse", "HEAD", cwd=other.root))
    assert whole_clone(other.root) == before and backup_names(home) == []
    advance(upstream, "Something new", **{"verification/new.txt": "new\n"})
    with pytest.raises(CdlbibError, match="is not on a branch a send made"):      # on master: nothing of this applies
        library._after_send(ws, "merged", url=PR, head=git("rev-parse", "HEAD", cwd=ws.root))
    assert backup_names(home) == [] and snapshot(ws.root)["branch"] == "master"


# The lookup itself, as far as it goes without GitHub: the library's origin is named as a
# GitHub repository that cannot exist (no owner's name has a "_"), and git is told to fetch it
# from the local upstream instead.

def named_on_github(managed, monkeypatch):
    home, upstream, ws = managed
    url = "https://github.com/no_such_owner/x.git"
    conftest._git("config", f"url.{upstream}.insteadOf", url, cwd=ws.root)
    conftest._git("remote", "set-url", "origin", url, cwd=ws.root)
    monkeypatch.setenv("CDLBIB_UPSTREAM", url)


def only_git_on_the_path(tmp_path):
    folder = tmp_path / "only-git"
    folder.mkdir()
    (folder / "git").symlink_to(shutil.which("git"))
    return str(folder)


def test_with_no_gh_the_library_is_left_alone_with_the_reason_and_the_command_runs(managed, tmp_path, monkeypatch):
    home, upstream, ws, tip, new = sent(managed, "squash")
    named_on_github(managed, monkeypatch)
    root, before = ws.root, whole_clone(ws.root)
    path = only_git_on_the_path(tmp_path)
    why = ("the GitHub CLI (gh) was not found. Install the GitHub CLI (https://cli.github.com) and run: gh auth login")
    line = f"the library is on branch {SENT}, and its pull request could not be looked up (The GitHub CLI (gh) was not " \
           "found. Install the GitHub CLI (https://cli.github.com) and run: gh auth login); nothing was changed. "
    out = cdlbib("where", cwd=empty_folder(tmp_path), PATH=path)
    assert out.returncode == 0 and out.stdout.splitlines()[0] == str(root), out.stderr       # the command ran
    assert out.stderr == line + "It will be tried again automatically in about an hour; `cdlbib update` tries now.\n"
    assert whole_clone(root) == before and backup_names(home) == []
    state = library.read_state()
    assert state.last_attempt is not None and datetime.datetime.now(UTC) - state.last_check > 24 * HOUR
    again = cdlbib("where", cwd=empty_folder(tmp_path), PATH=path)     # the existing back-off: not with every command
    assert (again.returncode, again.stderr) == (0, "")
    asked = cdlbib("update", cwd=empty_folder(tmp_path), PATH=path)    # asked for: tried now, said again
    assert (asked.returncode, asked.stdout, asked.stderr) == (0, line + "Run `cdlbib update` to try again.\n", "")
    assert whole_clone(root) == before and backup_names(home) == [] and why


def test_a_cdlbib_branch_of_another_login_or_of_a_library_not_from_github_is_not_looked_up(managed, tmp_path, monkeypatch):
    """Not from GitHub: no pull request can exist, and no gh is run (there is none on the PATH)."""
    home, upstream, ws, tip, new = sent(managed, "squash")
    monkeypatch.setenv("PATH", only_git_on_the_path(tmp_path))
    before = whole_clone(ws.root)
    result = library.update(ws, force=True)
    assert result.action == "left_alone" and result.message == left_alone(
        2, f"the library is on branch {SENT}, not master",
        f"To update, run `git -C {shlex.quote(str(ws.root))} switch master`, then `cdlbib update`.")
    assert whole_clone(ws.root) == before and backup_names(home) == []


def test_an_unreachable_github_is_the_offline_case(managed, tmp_path, monkeypatch):
    """gh cannot connect (its proxy is a closed local port): one line, nothing changed."""
    if not shutil.which("gh"):
        pytest.skip("gh is not installed")
    home, upstream, ws, tip, new = sent(managed, "squash")
    named_on_github(managed, monkeypatch)
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    before = whole_clone(ws.root)
    result = library.update(ws)
    assert result.action == "left_alone" and result.backup is None
    assert result.message.startswith(f"the library is on branch {SENT}, and its pull request could not be looked up (")
    assert result.message.endswith("); nothing was changed. It will be tried again automatically in about an hour; "
                                   "`cdlbib update` tries now.")
    assert "\n" not in result.message
    assert whole_clone(ws.root) == before and backup_names(home) == []
    assert library.update(ws) == library.UpdateResult("not_due")     # backed off for an hour


def test_a_github_that_does_not_answer_costs_a_command_the_short_timeout(managed, tmp_path, monkeypatch):
    """gh's proxy accepts the connection and never answers: the lookup is given up after the
    automatic check's timeout, and the library is as it was."""
    import socket
    if not shutil.which("gh"):
        pytest.skip("gh is not installed")
    home, upstream, ws, tip, new = sent(managed, "squash")
    named_on_github(managed, monkeypatch)
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(8)
    try:
        for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
            monkeypatch.setenv(name, f"http://127.0.0.1:{silent.getsockname()[1]}")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.setattr(library, "AUTO_FETCH_TIMEOUT", 3)
        before, started = whole_clone(ws.root), time.monotonic()
        result = library.update(ws)
        took = time.monotonic() - started
    finally:
        silent.close()
    assert result.action == "left_alone" and "could not be looked up (" in result.message
    assert 2.5 < took < 20, took
    assert whole_clone(ws.root) == before and backup_names(home) == []


# `cdlbib send` from the managed library's old send branch, once GitHub says its pull request is
# merged: api.send calls api._back_to_main with the pull request it looked up, then goes on.

def merged_pr(tip):
    from cdlbib import publish
    return publish.PullRequest(url=PR, state="merged", head=tip)


def test_a_send_after_a_merge_first_returns_the_library_to_main_with_the_changes_kept(managed, tmp_path, capsys):
    from cdlbib import publish
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    write(root, "cdl.bib", BASE + MINE + LATER)                       # the change that is to be sent next
    before, lines = everything(root), []
    said = api._back_to_main(ws, merged_pr(tip), lines.append)
    stamp = backup_names(home)[0]
    line = back_line(2, f"branch {SENT} was kept (git does not count a squash-merged branch as merged); everything on "
                        "it is in the merged pull request, so it is safe to delete", stamp,
                     middle=", with your changes kept (cdl.bib)")
    assert lines == [line] and said == "Y" + line[1:] + "." and capsys.readouterr() == ("", "")
    after = snapshot(root)
    assert (after["branch"], after["commit"], after["changed"]) == ("master", new, ["cdl.bib"])
    assert (root / "cdl.bib").read_text(encoding="utf-8") == BASE + MINE + LATER and publish.pending(ws) == ["cdl.bib"]
    assert publish.require_branch(ws, "master") == "master"           # the send goes on from here, on a new branch
    assert cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before


def test_a_send_after_a_merge_with_nothing_new_returns_the_library_and_says_so(managed):
    from cdlbib.errors import PublishRefused
    home, upstream, ws, tip, new = sent(managed, "merge")
    with pytest.raises(PublishRefused) as refused:
        api._back_to_main(ws, merged_pr(tip))
    stamp = backup_names(home)[0]
    assert str(refused.value) == ("There are no changes to cdl.bib or verification/ to send. Y"
                                  + back_line(1, f"branch {SENT} was deleted", stamp)[1:] + ".")
    assert snapshot(ws.root)["branches"] == {"master": new} and snapshot(ws.root)["changed"] == []


@pytest.mark.parametrize("pending", [True, False])
def test_a_send_after_a_merge_refuses_when_the_branch_holds_commits_that_were_never_sent(managed, pending):
    from cdlbib.errors import PublishRefused
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    write(root, "cdl.bib", BASE + MINE + LATER)
    conftest._git("commit", "--quiet", "-m", "A later entry", "--", "cdl.bib", cwd=root)
    if pending:
        write(root, "cdl.bib", BASE + MINE + LATER + "% and one more line\n")
    before = whole_clone(root)
    with pytest.raises(PublishRefused) as refused:
        api._back_to_main(ws, merged_pr(tip))
    assert str(refused.value) == (
        f"not sent: your pull request {PR} was merged, but branch {SENT} has 1 commit that the upstream does not have, "
        "which cannot be kept on top of the new version; nothing was changed. Run `cdlbib update` and choose again."
        if pending else
        f"not sent: your pull request {PR} was merged, and branch {SENT} of the library in {root} has changes that "
        "have not been sent. Nothing was changed. Run `cdlbib update` to choose what to do with them.")
    assert whole_clone(root) == before and backup_names(home) == []


def test_a_send_after_a_merge_whose_changes_collide_changes_nothing(managed):
    home, upstream, ws, tip, new = sent(managed, "squash")
    root = ws.root
    advance(upstream, "An edit to the entry", **{"cdl.bib": (BASE + MINE).replace("My own entry", "My own entry, retitled")})
    conftest._git("fetch", "--quiet", "origin", cwd=root)
    write(root, "cdl.bib", (BASE + MINE).replace("My own entry", "My entry, renamed by me"))
    before = whole_clone(root)
    with pytest.raises(UpdateConflict, match="changed both by you and in the new version: Mine26"):
        api._back_to_main(ws, merged_pr(tip))
    assert whole_clone(root) == before and backup_names(home) == []


# --- follow-ups from the review of the unsent-edits question ----------------------------------

NO_IDENTITY = dict(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")


def test_a_send_chosen_at_the_question_that_fails_ends_the_command_as_cdlbib_send_does(managed, tmp_path):
    """The send stops before any network use (git has no author). It is the command from then
    on: its message, its exit code, and the command that was typed does not run."""
    home, upstream, ws, new = unsent(managed)
    root = ws.root
    conftest._git("config", "user.useConfigOnly", "true", cwd=root)
    nobody = tmp_path / "nobody"
    nobody.mkdir()
    env = dict(NO_IDENTITY, HOME=str(nobody))
    before = everything(root)
    by_hand = cdlbib("send", cwd=empty_folder(tmp_path), **env)       # typed by hand (no terminal: the notice comes first)
    refusal = by_hand.stderr[len(NOTICE):]
    assert by_hand.returncode == 1 and by_hand.stderr.startswith(NOTICE)
    assert refusal.startswith("git does not know your name and email") and by_hand.stdout == ""
    checked(home, 25 * HOUR)
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"s\n", **env)
    assert code == 1, out + shown                                     # the send's exit code
    assert shown == (QUESTION + "s\nthe bibliography was not updated: your changes are sent first (`cdlbib send`)\n"
                     + refusal)                                       # the send's own message, as typed by hand
    assert out == ""                                                  # `where` did not run
    assert everything(root) == before and backup_names(home) == []
    code, out, shown = at_a_terminal("update", cwd=empty_folder(tmp_path), answers=b"s\n", **env)   # and from `cdlbib update`
    assert code == 1 and out == "" and shown.endswith(refusal)
    assert everything(root) == before and backup_names(home) == []


def interrupted_line(root, stamp):
    return (f"an earlier update of the bibliography in {root} was interrupted before it finished, so the library may be "
            f"missing your changes; nothing was changed now. Run `cdlbib update --undo {stamp}` to put the library "
            f"back as it was before that update (backup {stamp}).\n")


@pytest.mark.parametrize("decision, hook", [("update", "post-merge"), ("discard", "post-checkout")])
def test_an_update_that_is_killed_part_way_is_announced_and_undone_exactly(managed, tmp_path, decision, hook):
    """A real kill, with no hook in the product: git itself runs the library's own hook script
    after the fast-forward ("update": the edits are set aside, the new version is in, the edits
    are not back yet) or after the switch off the branch ("discard" of a local commit: the
    edits are set aside, the branch is not moved yet); the script reports and waits, and the
    whole process group is killed there."""
    import signal
    home, upstream, ws, new = unsent(managed)
    root = ws.root
    if decision == "discard":
        conftest._git("commit", "--quiet", "-m", "Mine", "--", "cdl.bib", cwd=root)
    before = everything(root)
    reached, script = tmp_path / "reached", root / ".git" / "hooks" / hook
    script.parent.mkdir(exist_ok=True)
    script.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(reached))}\nexec sleep 600\n", encoding="utf-8")
    script.chmod(0o755)
    code = ("import sys; from cdlbib import library; from cdlbib.workspace import Workspace; "
            "library.update(Workspace(sys.argv[1]), decision=sys.argv[2])")
    run = subprocess.Popen([sys.executable, "-c", code, str(root), decision], start_new_session=True,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 120
        while not reached.exists() and run.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert reached.exists(), run.stderr.read().decode()
    finally:
        os.killpg(run.pid, signal.SIGKILL)
        run.wait()
        run.stderr.close()
    script.unlink()
    stamp = backup_names(home)[0]
    assert library.interrupted() == stamp and lock_is_free(home)
    killed = everything(root)
    assert killed != before                                           # the library is part-way: the edits are not in it
    if decision == "update":                                          # (git runs post-checkout after its restore too:
        assert not (root / "verification/notes/my new file.jsonl").exists()      # "discard" stops earlier still)
        assert git("rev-parse", "HEAD", cwd=root) == new and (root / "cdl.bib").read_text(encoding="utf-8") == THEIRS

    line = interrupted_line(root, stamp)
    for _ in range(2):                                                # said with every command, and nothing is changed
        out = cdlbib("where", cwd=empty_folder(tmp_path))
        assert (out.returncode, out.stderr) == (0, line) and out.stdout.splitlines()[0] == str(root)
        assert everything(root) == killed and backup_names(home) == [stamp]
    asked = cdlbib("update", cwd=empty_folder(tmp_path))
    assert (asked.returncode, asked.stdout, asked.stderr) == (1, "", line)
    result = library.update(ws, force=True, decision="discard")       # no decision is applied either
    assert (result.action, result.message + "\n") == ("interrupted", line)
    assert everything(root) == killed and backup_names(home) == [stamp]
    assert not [p.name for p in root.iterdir() if p.name.startswith(".cdlbib-")]      # nothing half-written in the library

    for _ in range(library.KEEP + 1):                                 # eleven further backups: the one it names stays
        library.backup(ws)
    assert stamp in backup_names(home) and len(backup_names(home)) == library.KEEP + 2

    undone = cdlbib("update", "--undo", cwd=empty_folder(tmp_path))    # bare: the interrupted update's backup, not the newest
    assert undone.returncode == 0, undone.stderr
    assert undone.stdout.splitlines()[0].startswith(f"restored backup {stamp} (")
    assert undone.stderr.splitlines()[0] == (f"note: backup {stamp} is the one taken before the update that was "
                                             "interrupted; it is the one restored")
    assert everything(root) == before                                 # exactly the library before that update
    assert library.interrupted() is None and not list((home / "work").iterdir())
    assert len(backup_names(home)) <= library.KEEP + 1                # pruning is back (the copy just taken included)
    assert "interrupted" not in cdlbib("where", cwd=empty_folder(tmp_path)).stderr


def test_a_marker_whose_update_is_still_running_is_not_taken_for_a_dead_one(managed, tmp_path):
    """The marker is read with the lock held: while an update runs, another command waits for
    the lock and then finds the update finished."""
    home, upstream, ws, new = unsent(managed)
    assert library.interrupted() is None
    assert library.update(ws, decision="update").action == "updated"
    assert library.interrupted() is None and not list((home / "work").iterdir())
    library._mark(library.backups()[0], "update")                     # as an update writes it
    assert library.interrupted() == library.backups()[0].stamp
    unreadable = home / library.MARKER
    unreadable.write_text("{", encoding="utf-8")                      # a record that cannot be read still stands
    assert library.interrupted() == ""
    out = cdlbib("where", cwd=empty_folder(tmp_path))
    assert out.returncode == 0 and out.stderr == (
        f"an earlier update of the bibliography in {ws.root} was interrupted before it finished, so the library may be "
        "missing your changes; nothing was changed now. Run `cdlbib update --list` to see the backups, and `cdlbib "
        "update --undo STAMP` to put the library back as it was at the one taken before that update.\n")


def test_the_same_new_entry_added_by_both_at_different_places_is_refused(managed):
    """The lines merge, and the result would hold the key twice."""
    home, upstream, ws, new = unsent(managed, mine=BASE + MINE, theirs=MINE.lstrip("\n") + "\n" + BASE)
    before = everything(ws.root)
    with pytest.raises(UpdateConflict) as raised:
        library.update(ws, decision="update")
    assert (raised.value.entries, raised.value.files) == (["Mine26"], ["cdl.bib"])
    assert str(raised.value) == (
        "The bibliography was not updated: this entry would be in cdl.bib twice, added both by you and in the new "
        "version: Mine26. Nothing was changed: your files are exactly as they were. Run `cdlbib send` to send your "
        "changes, or `cdlbib update` to choose again.")
    assert everything(ws.root) == before and backup_names(home) == [] and library.interrupted() is None


def test_a_nul_byte_in_the_bibliography_is_called_binary_data_not_a_collision(managed):
    home, upstream, ws, new = unsent(managed, mine=BASE + MINE + "\0\n")
    before = everything(ws.root)
    with pytest.raises(UpdateConflict) as raised:
        library.update(ws, decision="update")
    assert (raised.value.entries, raised.value.files) == ([], ["cdl.bib"])
    assert str(raised.value).startswith("The bibliography was not updated: cdl.bib cannot be merged automatically "
                                        "because it contains binary data. Nothing was changed: ")
    assert everything(ws.root) == before and backup_names(home) == []


def test_changes_to_adjacent_entries_merge(managed):
    """The last line of one entry here, the second line of the next one there."""
    home, upstream, ws = managed
    root = ws.root
    advance(upstream, "Two entries", **{"cdl.bib": BASE + MINE})
    fast_forward(root)
    write(root, "cdl.bib", BASE.replace("{1990}}", "{1991}}") + MINE)
    new = advance(upstream, "The next entry's author", **{"cdl.bib": BASE + MINE.replace("A Person", "Another Person")})
    checked(home, 25 * HOUR)
    assert library.update(ws, decision="update").action == "updated"
    assert git("rev-parse", "HEAD", cwd=root) == new
    assert (root / "cdl.bib").read_text(encoding="utf-8") == (BASE.replace("{1990}}", "{1991}}")
                                                              + MINE.replace("A Person", "Another Person"))
    assert markers(root) == []


def test_crlf_lines_and_a_very_long_line_come_through_update_and_keep_byte_for_byte(managed, tmp_path):
    mine = BASE.encode() + MINE.replace("\n", "\r\n").encode() + b"% " + b"x" * 200_000 + b"\r\n% no newline at the end"
    home, upstream, ws, new = unsent(managed)
    root = ws.root
    (root / "cdl.bib").write_bytes(mine)
    before = everything(root)
    assert library.update(ws, decision="update").action == "updated"
    assert (root / "cdl.bib").read_bytes() == THEIRS.encode() + mine[len(BASE.encode()):]      # their edit, my bytes
    assert cdlbib("update", "--undo", cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before and (root / "cdl.bib").read_bytes() == mine


def test_the_count_of_changed_entries_is_made_from_the_text_in_well_under_a_second(managed):
    """The whole bibliography as it was frozen for the tests (6,000 entries and more), with
    three entries changed: one edited, one removed, one added."""
    home, upstream, ws = managed
    root = ws.root
    full = conftest.FROZEN_LIBRARY.read_text(encoding="utf-8")
    advance(upstream, "The whole bibliography", **{"cdl.bib": full})
    fast_forward(root)
    keys = re.findall(r"(?m)^@\w+\{([^,\s]+),", full)
    assert len(keys) > 6000
    first = re.search(r"(?m)^@\w+\{" + re.escape(keys[10]) + r",.*?(?=^@)", full, re.S)
    gone = re.search(r"(?m)^@\w+\{" + re.escape(keys[2000]) + r",.*?(?=^@)", full, re.S)
    edited = full.replace(first.group(0), first.group(0).replace("}", " (edited)}", 1), 1).replace(gone.group(0), "", 1)
    write(root, "cdl.bib", edited + MINE)
    advance(upstream, "Something else", **{"verification/new.txt": "new\n"})
    checked(home, 25 * HOUR)
    commit, target = git("rev-parse", "HEAD", cwd=root), None
    conftest._git("fetch", "--quiet", "origin", cwd=root)
    target = git("rev-parse", "origin/master", cwd=root)
    started = time.perf_counter()
    count = library._entry_count(root, commit, target)
    took = time.perf_counter() - started
    print(f"\n_entry_count on the full library: {took:.3f} s")
    assert count == 3 and took < 2.0, took
    started = time.perf_counter()
    with pytest.raises(UpdateNeedsDecision) as raised:
        library.update(ws)
    assert raised.value.entries_changed == 3 and time.perf_counter() - started < 10


def test_the_loser_of_two_answers_is_told_the_state_changed_not_that_it_is_up_to_date(managed):
    home, upstream, ws, new = unsent(managed)
    asked = pytest.raises(UpdateNeedsDecision, library.update, ws).value
    assert library.update(ws, decision="discard", seen=asked.seen).action == "updated"     # one terminal answers
    before = everything(ws.root)
    for decision in ("update", "discard"):                            # the other answers the question it was shown
        late = library.update(ws, decision=decision, seen=asked.seen)
        assert (late.action, late.message) == ("left_alone", "the library or the upstream changed after you were asked "
                                               "what to do; nothing was changed. Run `cdlbib update` to be asked again.")
    assert everything(ws.root) == before and len(backup_names(home)) == 1


def test_the_whole_word_is_an_answer_too(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    before = everything(ws.root)
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"Keep\n")
    assert code == 0 and shown.startswith(QUESTION + "Keep\nthe bibliography was not updated and your changes are as they were")
    assert "Please answer" not in shown and everything(ws.root) == before
    checked(home, 25 * HOUR)
    code, out, shown = at_a_terminal("update", cwd=empty_folder(tmp_path), answers=b"discard\n")
    assert code == 0 and out.startswith("updated the bibliography: 2 new commits; discarded your changes to ")


def test_at_a_terminal_the_rewritten_upstream_is_asked_about_truthfully_and_m_moves(managed, tmp_path):
    home, upstream, ws = managed
    root, work = ws.root, upstream.parent / "upstream-work"
    conftest._git("commit", "--quiet", "--amend", "-m", "The same library, rewritten", cwd=work)
    conftest._git("push", "--quiet", "--force", str(upstream), "master", cwd=work)
    new = git("rev-parse", "master", cwd=upstream)
    checked(home, 25 * HOUR)
    before = everything(root)
    code, out, shown = at_a_terminal("update", cwd=empty_folder(tmp_path), answers=b"d\nm\n")
    stamp = backup_names(home)[0]
    assert code == 0 and shown.startswith(REWRITTEN_QUESTION + "\nYour choice [k/m]: ")
    assert shown.count("Please answer k or m.\n") == 1 and shown.count("Your choice [k/m]: ") == 2   # "d" is no answer here
    assert out == (f"moved the bibliography to the upstream's new history (1 new commit; the library as it was is "
                   f"backup {stamp}; `cdlbib update --undo {stamp}` puts it back)\n")
    assert git("rev-parse", "HEAD", cwd=root) == new
    assert cdlbib("update", "--undo", stamp, cwd=empty_folder(tmp_path)).returncode == 0
    assert everything(root) == before


def test_a_local_commit_of_the_users_keeps_the_cautious_wording_when_the_upstream_was_rewritten(managed):
    """The library's commit was never the upstream's: it is work, and is called that."""
    home, upstream, ws = managed
    root, work = ws.root, upstream.parent / "upstream-work"
    write(root, "cdl.bib", BASE + MINE)
    conftest._git("commit", "--quiet", "-m", "Mine", "--", "cdl.bib", cwd=root)
    conftest._git("commit", "--quiet", "--amend", "-m", "The same library, rewritten", cwd=work)
    conftest._git("push", "--quiet", "--force", str(upstream), "master", cwd=work)
    checked(home, 25 * HOUR)
    asked = pytest.raises(UpdateNeedsDecision, library.update, ws).value
    assert not asked.rewritten and asked.local_commits == 2
    assert "you have changes that have not been sent" in cli.unsent_question(asked)
    assert "[d] Discard my changes and update" in cli.unsent_question(asked)


def test_with_stderr_redirected_nothing_is_asked_and_nothing_is_changed(managed, tmp_path):
    """`cdlbib where 2> file` at a terminal: the question would go where nobody reads it."""
    import pty
    home, upstream, ws, new = unsent(managed)
    before = everything(ws.root)
    leader, follower = pty.openpty()
    try:
        with open(tmp_path / "errors.txt", "wb") as errors:
            run = subprocess.run([CDLBIB, "where"], cwd=empty_folder(tmp_path), stdin=follower, stderr=errors,
                                 stdout=subprocess.PIPE, timeout=300)
    finally:
        os.close(follower)
        os.close(leader)
    assert run.returncode == 0 and run.stdout.decode().splitlines()[0] == str(ws.root)
    assert (tmp_path / "errors.txt").read_text(encoding="utf-8") == NOTICE
    assert everything(ws.root) == before and backup_names(home) == []


def test_ctrl_c_at_the_question_aborts_with_nothing_changed(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    before, state = everything(ws.root), (home / "state.json").read_bytes()
    code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"", interrupt=True)
    assert code == 1 and out == "" and shown.endswith("Aborted.\n") and "Traceback" not in shown
    assert everything(ws.root) == before and backup_names(home) == []
    assert (home / "state.json").read_bytes() == state
