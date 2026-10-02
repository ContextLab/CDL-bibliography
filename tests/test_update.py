"""Backups of the managed library, restoring one, and `cdlbib update --list` / `--undo`.

Real git against a local bare upstream; every test has a data folder of its own. A restore
is data-safety code, so each restore test compares a snapshot taken before the backup with
one taken after the restore: the branch, the commit, the set of changed paths under cdl.bib
and verification/, and a hash of every file under them.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import conftest
from cdlbib import api, library, workspace
from cdlbib.errors import CdlbibError, UpdateConflict
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
            "changed": sorted(changed_paths(root, *KEPT)), "files": hashes(root, KEPT)}


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


def cdlbib(*args, cwd, **env):
    return subprocess.run([CDLBIB, *args], cwd=cwd, capture_output=True, text=True, env=dict(os.environ, **env))


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
    library.restore(made, ws)
    assert snapshot(root) == before
    assert git("rev-parse", "master", cwd=root) != before["commit"]    # master was not the backup's branch: left alone


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

    bare = cdlbib("update", cwd=own)
    assert (bare.returncode, bare.stderr) == (0, "")
    assert bare.stdout == ("updating the library is not available yet; `cdlbib update --list` shows the backups "
                           "and `cdlbib update --undo` restores the newest\n")
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
    assert bare.returncode == 0 and "not available yet" in bare.stdout
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
    assert snapshot(root) == before
    assert git("rev-parse", "master", cwd=root) == on_master["commit"]  # master is not the backup's branch: left alone
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
