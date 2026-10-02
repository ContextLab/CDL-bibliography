"""Sending a change: the user's fork, a branch, a pull request (cdlbib.publish, api.send,
`cdlbib send`).

Real git against real local bare repositories; the real gh. The pull-request tests work
only inside the tester's own fork, on the branch cdlbib-test-base, and skip with their
reason where no user is logged in or the user has no fork. No mocks.
"""
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess

import pytest

from cdlbib import api, publish
from cdlbib.errors import GateFailed, IdentityUnavailable, PublishRefused
from cdlbib.workspace import Workspace

from test_machinery_2026_09_25 import CDLBIB, RAME72, ZOLL90, crossref_contact

GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
UPSTREAM = "ContextLab/CDL-bibliography"
TEST_BASE = "cdlbib-test-base"
# An upstream name that cannot exist: GitHub allows no "_" in an owner's name. A local test
# that got past its refusal would find no repository and no fork there, whatever the code.
NOWHERE = "no_such_owner/x"


@pytest.fixture(autouse=True)
def _git_environment(monkeypatch):
    # macOS: git needs the command-line tools named (as the other git tests pass it).
    monkeypatch.setenv("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")


def git(cwd, *args):
    run = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                         env=dict(os.environ, **GIT_ENV))
    assert run.returncode == 0, run.stderr
    return run.stdout.strip()


def state(root):
    """Everything a refused send must leave alone: the changes, the branch, the commit, the
    branches. (.bibcheck/ is the gate's own working folder, which the library ignores.)"""
    return (git(root, "status", "--porcelain", "--", ".", ":!.bibcheck"), git(root, "rev-parse", "--abbrev-ref", "HEAD"),
            git(root, "rev-parse", "HEAD"), git(root, "branch", "--list"))


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A real clone with a real bare remote standing in for the fork."""
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    remote = tmp_path / "fork.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "master", str(remote))
    work = tmp_path / "My Bibliothèque"                 # a space and a non-ASCII letter, on purpose
    git(tmp_path, "clone", "-q", str(remote), str(work))
    git(work, "checkout", "-q", "-B", "master")
    (work / "verification").mkdir()
    (work / "cdl.bib").write_text("% library\n", encoding="utf-8")
    (work / "verification" / "key-renames.json").write_text("{}\n", encoding="utf-8")
    (work / "README.md").write_text("readme\n", encoding="utf-8")
    git(work, "add", "-A"); git(work, "commit", "-q", "-m", "start"); git(work, "push", "-q", "origin", "HEAD:master")
    return Workspace(work), remote


def other_edits(root):
    """Three edits a send must leave alone: a tracked file modified, a new file staged by the
    user, a file untracked. Returns a function giving their bytes and their git state."""
    (root / "README.md").write_text("readme\nmy own edit, not for sending\n", encoding="utf-8")
    (root / "staged.txt").write_text("staged by me\n", encoding="utf-8")
    git(root, "add", "staged.txt")
    (root / "loose.txt").write_text("untracked\n", encoding="utf-8")
    names = ("README.md", "staged.txt", "loose.txt")

    def snapshot():
        run = subprocess.run(["git", "status", "--porcelain", "--", *names], cwd=root, capture_output=True, text=True,
                             check=True, env=dict(os.environ, **GIT_ENV))
        return [(root / name).read_bytes() for name in names], run.stdout
    assert snapshot()[1] == " M README.md\nA  staged.txt\n?? loose.txt\n"
    return snapshot


# A. cdlbib.publish, local ---------------------------------------------------------------

def origin_url(tmp_path, name, url):
    repo = tmp_path / name
    git(tmp_path, "init", "-q", str(repo)); git(repo, "remote", "add", "origin", url)
    return Workspace(repo)


def test_origin_urls_github_only(tmp_path):
    """Pure parsing of the checkout's origin; no network."""
    accepted = ("https://github.com/ContextLab/CDL-bibliography.git", "https://github.com/ContextLab/CDL-bibliography",
                "https://github.com/ContextLab/CDL-bibliography/", "http://github.com/ContextLab/CDL-bibliography.git",
                "https://someone@github.com/ContextLab/CDL-bibliography.git",
                "git@github.com:ContextLab/CDL-bibliography.git", "git@github.com:ContextLab/CDL-bibliography",
                "ssh://git@github.com/ContextLab/CDL-bibliography.git", "ssh://git@github.com:22/ContextLab/CDL-bibliography.git",
                "git://github.com/ContextLab/CDL-bibliography.git", "git://github.com/ContextLab/CDL-bibliography")
    refused = ("https://notgithub.com/ContextLab/CDL-bibliography.git", "https://github.com.evil.example/ContextLab/CDL-bibliography.git",
               "git@notgithub.com:ContextLab/CDL-bibliography.git", "git@github.com.evil.example:ContextLab/CDL-bibliography.git",
               "ssh://git@notgithub.com/ContextLab/CDL-bibliography.git", "git://notgithub.com/ContextLab/CDL-bibliography.git",
               "https://example.org/github.com/ContextLab/CDL-bibliography", "https://github.com@evil.example/ContextLab/CDL-bibliography.git",
               "https://github.com/ContextLab", "https://github.com/ContextLab/CDL-bibliography/tree/master",
               "ftp://github.com/ContextLab/CDL-bibliography.git")
    for number, url in enumerate(accepted):
        assert publish.upstream_of(origin_url(tmp_path, f"a{number}", url)) == "ContextLab/CDL-bibliography", url
    for number, url in enumerate(refused):
        with pytest.raises(PublishRefused, match="not a GitHub repository"):
            publish.upstream_of(origin_url(tmp_path, f"r{number}", url))


def test_upstream_refuses_a_checkout_that_is_not_from_github(checkout, tmp_path):
    ws, _ = checkout                                    # its origin is a local bare repository
    with pytest.raises(PublishRefused, match="not a GitHub repository"):
        publish.upstream_of(ws)
    with pytest.raises(PublishRefused):                 # not a git checkout at all
        publish.upstream_of(Workspace(tmp_path))


def origin_at(tmp_path, name, repository):
    return origin_url(tmp_path, name, f"https://github.com/{repository}.git")


def test_a_checkout_of_my_own_fork_sends_to_its_parent(tmp_path):
    """Read-only calls to GitHub: origin = the user's fork resolves to (parent, that fork);
    origin = the upstream resolves to (upstream, the user's fork)."""
    login, fork = my_fork()
    if login is None:
        pytest.skip(fork)
    assert publish.resolve(origin_at(tmp_path, "mine", fork), login) == (UPSTREAM, fork)
    assert publish.resolve(origin_at(tmp_path, "theirs", UPSTREAM), login) == (UPSTREAM, fork)
    assert publish.is_fork(fork) is True and publish.is_fork(UPSTREAM) is False
    with pytest.raises(PublishRefused, match="itself a fork"):       # refused before `gh repo fork` is run
        publish.create_fork(fork)


def test_an_unreachable_github_is_not_read_as_no_fork(monkeypatch, tmp_path):
    if not shutil.which("gh"):
        pytest.skip("gh is not installed")
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "empty-gh"))  # nobody logged in: every call fails, none is a 404
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(PublishRefused, match="GitHub could not be reached"):
        publish.find_fork(UPSTREAM, "no_such_owner")
    with pytest.raises(PublishRefused, match="GitHub could not be reached"):
        publish.resolve(origin_at(tmp_path, "r", UPSTREAM), "no_such_owner")


def test_a_missing_repository_is_a_plain_no(tmp_path):
    login, reason = gh_login()
    if login is None:
        pytest.skip(reason)
    # A login GitHub cannot have ("_"): a real 404 for its repository, then no fork of the upstream in its name.
    assert publish.find_fork(UPSTREAM, "no_such_owner") is None


def test_a_failed_push_says_where_things_stand_and_the_next_send_resumes(checkout, tmp_path):
    ws, remote = checkout
    branch = "cdlbib/test/2026-10-01-edit"
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    with pytest.raises(PublishRefused) as refused:
        publish.deliver(ws, branch, "edit", str(tmp_path / "no-such-remote.git"))
    message = str(refused.value)
    assert f"committed on branch {branch}" in message and "nothing was sent and no pull request was opened" in message
    assert "Run `cdlbib send` again to resume" in message and "To go back instead: git switch master" in message
    assert git(ws.root, "rev-parse", "--abbrev-ref", "HEAD") == branch and git(ws.root, "status", "--porcelain") == ""
    sha = git(ws.root, "rev-parse", "HEAD")
    assert git(ws.root, "rev-list", "--count", "master..HEAD") == "1"
    assert publish.deliver(ws, branch, "edit", str(remote)) == []    # nothing new to commit: the push alone
    assert git(remote, "rev-parse", branch) == sha and git(ws.root, "rev-parse", "HEAD") == sha


def test_nothing_pending_on_another_branch_is_refused_by_deliver(checkout):
    ws, remote = checkout
    before = state(ws.root)
    with pytest.raises(PublishRefused, match="no changes"):
        publish.deliver(ws, "cdlbib/test/2026-10-01-none", "none", str(remote))
    assert state(ws.root) == before


def test_a_commit_that_fails_puts_the_checkout_back(checkout):
    """A real failing commit (the repository's pre-commit hook says no): back on the branch
    the user was on, the same changes unstaged as before, no branch left behind."""
    ws, _ = checkout
    failing_hook(ws)
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    (ws.root / "verification" / "new.json").write_text("{}\n", encoding="utf-8")
    before = state(ws.root)
    with pytest.raises(PublishRefused) as refused:
        publish.commit_to_branch(ws, "cdlbib/test/2026-10-01-edit", "edit")
    message = str(refused.value)
    assert "nothing was committed and nothing was sent" in message and "back on branch master" in message
    assert "hook says no" in message
    assert state(ws.root) == before and "cdlbib/test" not in before[3]
    assert (ws.root / "cdl.bib").read_text(encoding="utf-8") == "% library\n% edit\n"


def failing_hook(ws):
    hook = ws.root / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\necho 'hook says no' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


def test_a_failed_commit_on_a_branch_that_already_existed_puts_the_checkout_back(checkout):
    """Same day, same summary: the branch exists with an earlier commit and the user is back
    on master. The commit fails for real (hook): back on master, the same status (one file
    was staged by the user beforehand and stays staged), the earlier branch untouched."""
    ws, _ = checkout
    branch = "cdlbib/test/2026-10-01-edit"
    (ws.root / "verification" / "earlier.json").write_text("{}\n", encoding="utf-8")
    earlier = publish.commit_to_branch(ws, branch, "earlier")
    git(ws.root, "switch", "-q", "master")
    failing_hook(ws)
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    (ws.root / "verification" / "key-renames.json").write_text('{"a": "b"}\n', encoding="utf-8")
    git(ws.root, "add", "verification/key-renames.json")            # staged by the user, not by cdlbib
    before = state(ws.root)
    # (the helper strips the output, so the first line has lost its leading space: " M" = changed, not staged)
    assert before[0].splitlines() == ["M cdl.bib", "M  verification/key-renames.json"] and before[1] == "master"
    with pytest.raises(PublishRefused) as refused:
        publish.commit_to_branch(ws, branch, "edit")
    message = str(refused.value)
    assert message.startswith("The commit could not be made, so nothing was committed and nothing was sent. "
                              "The checkout is back on branch master, with your changes in place.\n")
    assert "hook says no" in message
    assert state(ws.root) == before
    assert git(ws.root, "rev-parse", branch) == earlier              # still there, still at its commit


def test_a_checkout_on_no_branch_is_refused_up_front(checkout):
    ws, _ = checkout
    git(ws.root, "switch", "-q", "--detach")
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    before = state(ws.root)
    for attempt in (lambda: api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE),
                    lambda: publish.commit_to_branch(ws, "cdlbib/test/2026-10-01-edit", "edit"),
                    lambda: publish.deliver(ws, "cdlbib/test/2026-10-01-edit", "edit", str(ws.root / "nowhere.git"))):
        with pytest.raises(PublishRefused) as refused:
            attempt()
        assert "not on a branch (detached HEAD)" in str(refused.value) and "git switch HEAD" not in str(refused.value)
        assert "git switch master" not in str(refused.value)         # no branch is suggested that nobody named
        assert state(ws.root) == before
    with pytest.raises(PublishRefused, match="git switch cdlbib-test-base"):     # send names the main branch it was given
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)
    with pytest.raises(PublishRefused) as refused:                   # called directly: no branch is known, none is named
        publish.commit_to_branch(ws, "cdlbib/test/2026-10-01-edit", "edit")
    assert str(refused.value).endswith("then run `cdlbib send` again.")


def test_push_hints_for_the_two_recognised_failures():
    """The wording git prints, as text: a push refused for want of permission cannot be
    produced here without pushing to someone else's repository."""
    denied = "remote: Permission to no_such_owner/CDL-bibliography.git denied to someone.\nfatal: unable to access: The requested URL returned error: 403"
    assert publish.push_hint(denied, "no_such_owner/CDL-bibliography") == (
        " The GitHub account git is signed in with lacks permission to push to no_such_owner/CDL-bibliography; check which "
        "account is logged in with `gh auth status`.")
    assert "gh auth setup-git" in publish.push_hint("fatal: could not read Username for 'https://github.com': terminal prompts disabled", "x")
    assert "gh auth setup-git" in publish.push_hint("fatal: Authentication failed for 'https://github.com/a/b.git/'", "x")
    assert publish.push_hint("fatal: '/tmp/none.git' does not appear to be a git repository", "x") == ""


def test_branch_name():
    name = publish.branch_name("octocat", "Add Smith & Jones (2024): fix pages!", datetime.date(2026, 10, 1))
    assert name == "cdlbib/octocat/2026-10-01-add-smith-jones-2024-fix-pages"
    assert publish.branch_name("octocat", "", datetime.date(2026, 10, 1)) == "cdlbib/octocat/2026-10-01-update"
    long = publish.branch_name("octocat", "added the following entries: " + ", ".join(["KeyEtal24"] * 40),
                               datetime.date(2026, 10, 1))
    assert len(long) <= len("cdlbib/octocat/2026-10-01-") + 50 and not long.endswith("-")


def test_unrelated_changes_are_listed(checkout):
    ws, _ = checkout
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    (ws.root / "verification" / "new file é.json").write_text("{}\n", encoding="utf-8")
    assert publish.unrelated_changes(ws) == []
    (ws.root / "README.md").write_text("changed\n", encoding="utf-8")
    (ws.root / "stray.txt").write_text("x\n", encoding="utf-8")
    (ws.root / ".bibcheck").mkdir()                     # the working folder is never a stray file
    (ws.root / ".bibcheck" / "report.jsonl").write_text("{}\n", encoding="utf-8")
    assert publish.unrelated_changes(ws) == ["README.md", "stray.txt"]


def test_a_file_moved_out_of_the_library_folders_is_unrelated(checkout):
    ws, _ = checkout
    git(ws.root, "mv", "verification/key-renames.json", "elsewhere.json")
    assert publish.unrelated_changes(ws) == ["elsewhere.json"]


def test_commit_and_push_only_the_library_files(checkout):
    ws, remote = checkout
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    (ws.root / "verification" / "key-renames.json").write_text('{"a": "b"}\n', encoding="utf-8")
    (ws.root / "verification" / "new file é.json").write_text("{}\n", encoding="utf-8")   # untracked
    sha = publish.commit_to_branch(ws, "cdlbib/test/2026-10-01-edit", "edit")
    publish.push(ws, str(remote), "cdlbib/test/2026-10-01-edit")
    assert git(remote, "rev-parse", "cdlbib/test/2026-10-01-edit") == sha
    assert sorted(git(remote, "-c", "core.quotepath=off", "show", "--name-only", "--format=", sha).splitlines()) == [
        "cdl.bib", "verification/key-renames.json", "verification/new file é.json"]
    assert git(remote, "rev-parse", "master") != sha            # master on the remote is untouched
    assert git(ws.root, "rev-parse", "master") != sha           # and so is the local master
    assert git(ws.root, "rev-parse", "--abbrev-ref", "HEAD") == "cdlbib/test/2026-10-01-edit"
    assert git(ws.root, "status", "--porcelain") == ""


def test_other_edits_are_left_exactly_as_they_were(checkout):
    """Only cdl.bib and verification/ are committed and pushed. A modified file, a file the
    user staged and an untracked file are byte-identical and in the same git state afterwards,
    and none of them is in the pushed commit."""
    ws, remote = checkout
    branch = "cdlbib/test/2026-10-01-edit"
    snapshot = other_edits(ws.root)
    before = snapshot()
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    (ws.root / "verification" / "new.json").write_text("{}\n", encoding="utf-8")
    (ws.root / ".bibcheck").mkdir()
    (ws.root / ".bibcheck" / "report.jsonl").write_text("{}\n", encoding="utf-8")
    assert publish.deliver(ws, branch, "edit", str(remote)) == ["cdl.bib", "verification/new.json"]
    assert snapshot() == before
    sha = git(remote, "rev-parse", branch)
    assert sorted(git(remote, "show", "--name-only", "--format=", sha).splitlines()) == ["cdl.bib", "verification/new.json"]
    assert git(ws.root, "status", "--porcelain", "--", "cdl.bib", "verification") == ""
    assert publish.unrelated_changes(ws) == ["README.md", "loose.txt", "staged.txt"]     # reported, .bibcheck/ never
    # A second change from the same branch: the same holds.
    (ws.root / "cdl.bib").write_text("% library\n% edit two\n", encoding="utf-8")
    assert publish.deliver(ws, branch, "edit two", str(remote)) == ["cdl.bib"]
    assert snapshot() == before
    assert git(remote, "show", "--name-only", "--format=", git(remote, "rev-parse", branch)) == "cdl.bib"


def test_a_branch_that_conflicts_with_my_other_edits_is_refused_whole(checkout):
    """The send branch already exists and differs in a file the user has changed: git cannot
    switch to it. That is the first write, and it is refused with nothing changed."""
    ws, remote = checkout
    branch = "cdlbib/test/2026-10-01-edit"
    git(ws.root, "switch", "-q", "-c", branch)
    (ws.root / "README.md").write_text("another readme on the send branch\n", encoding="utf-8")
    git(ws.root, "commit", "-q", "-m", "readme on the branch", "--", "README.md")
    git(ws.root, "switch", "-q", "master")
    snapshot = other_edits(ws.root)
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    before, edits = state(ws.root), snapshot()
    with pytest.raises(PublishRefused) as refused:
        publish.deliver(ws, branch, "edit", str(remote))
    message = str(refused.value)
    assert message.startswith(f"git could not switch to branch {branch}, which already exists and differs in files you have changed. Nothing was changed.")
    assert "README.md" in message and "different --summary" in message
    assert state(ws.root) == before and snapshot() == edits


def test_second_commit_reuses_the_branch(checkout):
    ws, remote = checkout
    branch = "cdlbib/test/2026-10-01-edit"
    (ws.root / "cdl.bib").write_text("% one\n", encoding="utf-8")
    first = publish.commit_to_branch(ws, branch, "one"); publish.push(ws, str(remote), branch)
    (ws.root / "cdl.bib").write_text("% two\n", encoding="utf-8")
    second = publish.commit_to_branch(ws, branch, "two"); publish.push(ws, str(remote), branch)
    assert git(remote, "rev-parse", branch) == second and git(remote, "rev-parse", branch + "~1") == first


def test_nothing_to_commit_is_refused(checkout):
    ws, _ = checkout
    before = state(ws.root)
    with pytest.raises(PublishRefused, match="no changes"):
        publish.commit_to_branch(ws, "cdlbib/test/2026-10-01-none", "none")
    assert state(ws.root) == before                     # no branch was made for nothing


def test_the_test_guard_fires():
    with pytest.raises(PublishRefused):
        publish.assert_safe_test_target("ContextLab/CDL-bibliography", "dev")
    with pytest.raises(PublishRefused):
        publish.assert_safe_test_target("contextlab/cdl-bibliography", TEST_BASE)
    with pytest.raises(PublishRefused):
        publish.assert_safe_test_target("someone/CDL-bibliography", "master")
    publish.assert_safe_test_target("someone/CDL-bibliography", TEST_BASE)


def test_approvals_note_lists_logins_and_keys(tmp_path):
    from cdlbib.verification import Cache, load_entries, record_approval, revocation_ledger
    bib = tmp_path / "lib.bib"; bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n", encoding="utf-8")
    ws = Workspace.for_bib(bib)
    assert api.approvals_note(ws) == ""                 # no database yet, nothing approved
    assert not ws.database.exists()                     # and asking creates nothing
    fp = load_entries(str(bib))["Zoll90"]["fingerprint"]
    ws.work.mkdir()
    cache = Cache(str(ws.database), ledger=revocation_ledger(str(bib), None))
    record_approval(cache, str(bib), "Zoll90", fp, {"reviewer": "@octocat", "source": "https://doi.org/10.1002/tea.3660271011",
                                                    "note": "checked", "github_login": "octocat", "github_id": 583231})
    cache.close()
    assert api.approvals_note(ws) == "\n\nApproved by @octocat: Zoll90"
    # Limited to the entries that differ from a reference: Zoll90 is unchanged there.
    assert api.approvals_note(ws, reference=str(bib)) == ""
    base = tmp_path / "base.bib"; base.write_text(RAME72 % "1" + "\n", encoding="utf-8")
    assert api.approvals_note(ws, reference=str(base)) == "\n\nApproved by @octocat: Zoll90"


# B. api.send refusals, local ------------------------------------------------------------

def test_send_refuses_on_a_failed_gate_before_touching_git(checkout):
    ws, _ = checkout
    (ws.root / "cdl.bib").write_text("@article{Bad,\n\tPages = {10--1}}\n", encoding="utf-8")
    before = state(ws.root)
    with pytest.raises(GateFailed) as refused:
        api.send(ws, summary="bad", reference=str(ws.bib), upstream=NOWHERE, base=TEST_BASE)
    assert refused.value.check is not None and not refused.value.check.ok
    assert state(ws.root) == before and before[1] == "master"


def test_send_without_a_login_refuses(checkout, monkeypatch, tmp_path):
    ws, _ = checkout
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "empty-gh"))
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    before = state(ws.root)
    with pytest.raises(IdentityUnavailable):
        api.send(ws, summary="edit", reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)
    assert state(ws.root) == before


def test_send_with_nothing_to_send_refuses_before_anything_outward(checkout):
    """No changes and allow_fork_creation=True: the refusal comes first. The committed library
    also fails the format check, so a send that skipped the refusal would stop at the gate
    (and fail this test) long before any fork could be looked up or created."""
    ws = library_checkout(checkout, "@article{Bad,\n\tPages = {10--1}}\n")
    assert publish.pending(ws) == []
    before = state(ws.root)
    with pytest.raises(PublishRefused, match="no changes to cdl.bib or verification/"):
        api.send(ws, reference=str(ws.bib), upstream=NOWHERE, base=TEST_BASE, allow_fork_creation=True)
    assert state(ws.root) == before


def test_send_never_pushes_to_the_upstream(checkout):
    """The change also fails the format check, so a send that missed this refusal stops at
    the gate (and fails this test) instead of going anywhere."""
    ws, _ = checkout
    (ws.root / "cdl.bib").write_text("@article{Bad,\n\tPages = {10--1}}\n", encoding="utf-8")
    before = state(ws.root)
    with pytest.raises(PublishRefused, match="never pushed to the upstream"):
        api.send(ws, reference=str(ws.bib), citations=False, upstream="no_such_owner/Library", fork="No_Such_Owner/library", base=TEST_BASE)
    assert state(ws.root) == before


def test_send_without_a_git_identity_refuses_and_changes_nothing(checkout, monkeypatch, tmp_path):
    """git cannot name the author: no global or system configuration, no name in the
    repository, none in the environment. (user.useConfigOnly makes that hold on machines
    where git would otherwise make up an address from the host name.)"""
    ws, _ = checkout
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    git(ws.root, "config", "user.useConfigOnly", "true")
    before = state(ws.root)
    home = tmp_path / "empty-home"; home.mkdir()
    for name in GIT_ENV:
        monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    with pytest.raises(PublishRefused) as refused:
        api.send(ws, summary="edit", reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)
    assert 'git config --global user.name "Your Name"' in str(refused.value)
    assert 'git config --global user.email "you@example.org"' in str(refused.value)
    assert state(ws.root) == before


def test_send_outside_a_git_checkout_refuses(tmp_path):
    bib = tmp_path / "plain" / "cdl.bib"
    bib.parent.mkdir()
    bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    with pytest.raises(PublishRefused):
        api.send(Workspace(bib.parent), reference=str(bib), citations=False, upstream=NOWHERE, base=TEST_BASE)


# The command ----------------------------------------------------------------------------

def cdlbib(cwd, *args, **env):
    return subprocess.run([CDLBIB, *args], cwd=cwd, capture_output=True, text=True, timeout=1800,
                          stdin=subprocess.DEVNULL, env=dict(os.environ, **GIT_ENV, **env))


def library_checkout(checkout, text):
    """The checkout with a real entry as its committed library."""
    ws, remote = checkout
    ws.bib.write_text(text, encoding="utf-8")
    git(ws.root, "commit", "-q", "-m", "library", "--", "cdl.bib")
    return ws


def test_send_command_reports_a_failed_gate_and_changes_nothing(checkout, tmp_path):
    ws = library_checkout(checkout, ZOLL90 + "\n")
    ws.bib.write_text(ZOLL90.replace("1053--1065", "1053--105") + "\n", encoding="utf-8")
    before = state(ws.root)
    run = cdlbib(ws.root, "send", "--reference", str(ws.bib), "--database", str(tmp_path / "db.sqlite3"))
    assert run.returncode == 1, run.stdout + run.stderr
    assert run.stdout.endswith("not sent: fix the format errors and resolve every new/edited entry first "
                               "(see `cdlbib verify`).\n")
    assert "pull request" not in run.stdout and state(ws.root) == before


def test_send_command_does_not_refuse_for_other_edits(checkout, tmp_path):
    """Other edited files are no reason to refuse: the gate runs and passes. (The send then
    stops because this scratch checkout's origin is a local folder, or nobody is logged in;
    the other edits are as they were.)"""
    ws = library_checkout(checkout, ZOLL90 + "\n")
    snapshot = other_edits(ws.root)
    ws.bib.write_text(ZOLL90 + "\n\n% a note\n", encoding="utf-8")
    before, edits = state(ws.root), snapshot()
    run = cdlbib(ws.root, "send", "--reference", str(ws.bib), "--database", str(tmp_path / "db.sqlite3"))
    assert "checks passed; generating commit message..." in run.stdout, run.stdout + run.stderr
    assert run.returncode == 1 and "Traceback" not in run.stderr and "README.md" not in run.stderr
    assert state(ws.root) == before and snapshot() == edits


def test_send_command_refuses_an_unresolved_entry(checkout, tmp_path):
    """The gate reached through `send`: a real Crossref check of a new entry whose volume is
    wrong (Crossref: 1). The entry is named, nothing is sent, the checkout is untouched."""
    ws = library_checkout(checkout, ZOLL90 + "\n")
    base = tmp_path / "base.bib"; base.write_text(ZOLL90 + "\n", encoding="utf-8")
    ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "2" + "\n", encoding="utf-8")
    before = state(ws.root)
    run = cdlbib(ws.root, "send", "--reference", str(base), "--database", str(tmp_path / "db.sqlite3"),
                 CROSSREF_MAILTO=crossref_contact())
    assert run.returncode == 1 and "UNRESOLVED Rame72" in run.stdout and "not sent" in run.stdout, run.stdout + run.stderr
    assert "pull request" not in run.stdout and state(ws.root) == before


def test_the_command_is_send_and_commit_is_gone(tmp_path):
    listing = cdlbib(tmp_path, "--help", COLUMNS="200")
    assert listing.returncode == 0 and re.search(r"^.\s+send\s", listing.stdout, re.M), listing.stdout
    assert not re.search(r"^.\s+commit\s", listing.stdout, re.M)
    gone = cdlbib(tmp_path, "commit", "--help")
    assert gone.returncode == 2 and "No such command" in gone.stderr
    options = cdlbib(tmp_path, "send", "--help", COLUMNS="200").stdout
    for name in ("--fname", "--reference", "--verbose", "--outfile", "--summary", "--database", "--mailto"):
        assert name in options, name


def gh_login():
    if not shutil.which("gh"):
        return None, "gh is not installed"
    who = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True)
    if who.returncode != 0 or not who.stdout.strip():
        return None, "no GitHub user is logged in (expected in CI)"
    return who.stdout.strip(), ""


def newest_repositories():
    """The names of the tester's five most recently created repositories (a read-only call)."""
    run = subprocess.run(["gh", "api", "user/repos?affiliation=owner&sort=created&direction=desc&per_page=5",
                          "--jq", ".[].full_name"], capture_output=True, text=True, check=True)
    return run.stdout.split()


def test_no_fork_is_reported_and_never_created_unasked(checkout, tmp_path):
    """The gate passes and the user has no fork of the upstream: the api, called without
    allow_fork_creation (its default; the command asks for creation itself, unless --ask), only
    reports it. The command's decision is tested in test_cli_entry.py without any call to GitHub.

    The upstream here is the tester's own fork: nobody has a fork of it, and nothing outside
    the tester's account is named. Why the test cannot create anything, whatever the code
    does: (1) fork creation is off; (2) the upstream is itself a fork, and create_fork refuses
    a fork before it runs `gh repo fork`; (3) a push needs a fork to push to, and there is
    none; (4) the pull request base is the test base, never master. The tester's newest
    repositories are compared before and after."""
    login, fork = my_fork()
    if login is None:
        pytest.skip(fork)
    upstream = fork
    publish.assert_safe_test_target(upstream, TEST_BASE)
    assert publish.is_fork(upstream) and publish.find_fork(upstream, login) is None
    had = newest_repositories()
    try:
        ws = library_checkout(checkout, ZOLL90 + "\n")
        ws.bib.write_text(ZOLL90 + "\n\n% a note\n", encoding="utf-8")
        base = tmp_path / "base.bib"; base.write_text(ZOLL90 + "\n", encoding="utf-8")
        before = state(ws.root)
        with pytest.raises(PublishRefused) as refused:
            api.send(ws, reference=str(base), citations=False, upstream=upstream, base=TEST_BASE, allow_fork_creation=False)
        assert refused.value.needs_fork and refused.value.upstream == upstream
        assert str(refused.value) == f"@{login} has no fork of {upstream}."
        assert publish.find_fork(upstream, login) is None   # still none
        assert state(ws.root) == before
    finally:
        assert newest_repositories() == had                 # the account gained no repository


def test_send_keeps_outfile_and_its_messages(checkout, tmp_path):
    ws = library_checkout(checkout, ZOLL90 + "\n")
    help_text = cdlbib(ws.root, "send", "--help", COLUMNS="200").stdout
    assert "--outfile" in help_text and "--summary" in help_text
    ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n", encoding="utf-8")
    base = tmp_path / "base.bib"; base.write_text(ZOLL90 + "\n", encoding="utf-8")
    out = tmp_path / "changes.txt"
    before = state(ws.root)
    run = cdlbib(ws.root, "send", "--reference", str(base), "--database", str(tmp_path / "db.sqlite3"),
                 "--outfile", str(out), CROSSREF_MAILTO=crossref_contact())
    # The gate passes and the comparison is written; the send then stops (this checkout's
    # origin is a local folder, or nobody is logged in), with nothing changed.
    assert run.returncode == 1 and "Traceback" not in run.stderr, run.stdout + run.stderr
    assert "checks passed; generating commit message..." in run.stdout
    assert out.read_text(encoding="utf-8").strip() == "added the following entries: Rame72"
    assert state(ws.root) == before


# C. The real pull request, inside the tester's own fork only ----------------------------

def my_fork():
    """(login, 'login/NAME') for the logged-in user's fork of the upstream repo, else a skip reason."""
    login, reason = gh_login()
    if login is None:
        return None, reason
    fork = publish.find_fork(UPSTREAM, login)
    return (login, fork) if fork else (None, f"@{login} has no fork of {UPSTREAM}; run `cdlbib send` once or `gh repo fork`")


def fork_clone(tmp_path, monkeypatch, fork):
    """A scratch clone of the tester's fork, with the test base branch pushed inside that fork."""
    publish.assert_safe_test_target(fork, TEST_BASE)                 # never ContextLab, never master
    work = tmp_path / "clone"
    subprocess.run(["gh", "repo", "clone", fork, str(work), "--", "--depth", "1", "-q"], check=True)
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    assert git(work, "remote", "get-url", "origin").rstrip("/").removesuffix(".git").lower().endswith(fork.lower())
    git(work, "push", "-q", "origin", f"HEAD:refs/heads/{TEST_BASE}", "--force")   # test base inside the fork
    return work


def open_prs(fork, branch):
    listed = subprocess.run(["gh", "pr", "list", "--repo", fork, "--head", branch, "--state", "open",
                             "--json", "url,title,body,baseRefName"], capture_output=True, text=True, check=True)
    return json.loads(listed.stdout)


def clean_up(work, url, branch):
    if url:
        subprocess.run(["gh", "pr", "close", url, "--delete-branch"], cwd=work, capture_output=True)
    subprocess.run(["git", "push", "-q", "origin", "--delete", branch], cwd=work, capture_output=True)


def test_pull_request_inside_my_own_fork(tmp_path, monkeypatch):
    login, fork = my_fork()
    if login is None:
        pytest.skip(fork)
    work = fork_clone(tmp_path, monkeypatch, fork)
    ws = Workspace(work)
    branch = f"cdlbib/{login}/test-{os.getpid()}"
    url = None
    try:
        ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + "\n% cdlbib test edit\n", encoding="utf-8")
        publish.commit_to_branch(ws, branch, "cdlbib test: please ignore")
        publish.push(ws, f"https://github.com/{fork}.git", branch)
        url = publish.open_or_update_pr(fork, TEST_BASE, branch, "cdlbib test: please ignore", "Automated test; closed immediately.")
        assert url.startswith(f"https://github.com/{fork}/pull/")
        again = publish.open_or_update_pr(fork, TEST_BASE, branch, "cdlbib test: please ignore (updated)", "Automated test.")
        assert again == url                                          # second send updates, never duplicates
        found = open_prs(fork, branch)
        assert [p["url"] for p in found] == [url]
        assert found[0]["title"] == "cdlbib test: please ignore (updated)" and found[0]["baseRefName"] == TEST_BASE
    finally:
        clean_up(work, url, branch)


def test_send_end_to_end_inside_my_own_fork(tmp_path, monkeypatch):
    """api.send as a whole: the gate (a real Crossref check of a new entry), the branch, the
    push to the fork, the pull request; a second send from that branch updates the same one."""
    login, fork = my_fork()
    if login is None:
        pytest.skip(fork)
    work = fork_clone(tmp_path, monkeypatch, fork)
    ws = Workspace(work)
    base_bib = tmp_path / "base.bib"; base_bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    options = dict(reference=str(base_bib), mailto=crossref_contact(), database=str(tmp_path / "db.sqlite3"),
                   upstream=fork, base=TEST_BASE, fork=fork, _test_inside_own_fork=True)
    summary = f"cdlbib test {os.getpid()}: please ignore"
    branch = publish.branch_name(login, summary, datetime.date.today())
    url, start = None, git(work, "rev-parse", "HEAD")
    try:
        snapshot = other_edits(work)                                 # three edits of my own, not for sending
        edits = snapshot()
        ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n", encoding="utf-8")
        # A push that fails for real (a local path where there is no repository; no host is
        # contacted): the change is committed on the branch and not sent.
        with pytest.raises(PublishRefused, match=f"committed on branch {branch}"):
            publish.deliver(ws, branch, "added the following entries: Rame72", str(tmp_path / "no-such-remote.git"))
        assert git(work, "rev-parse", "--abbrev-ref", "HEAD") == branch and git(work, "rev-list", "--count", f"{start}..HEAD") == "1"
        assert open_prs(fork, branch) == [] and publish.earlier_pr(fork, f"{login}:{branch}") is None

        first = api.send(ws, summary=summary, **options)             # resumes: pushes the commit, opens the pull request
        url = first.url
        with pytest.raises(PublishRefused, match="never pushed to the upstream"):   # without the test flag: refused
            api.send(ws, summary=summary, **dict(options, _test_inside_own_fork=False))
        assert publish.is_own_fork(fork, login) and not publish.is_own_fork(UPSTREAM, login)   # what the flag requires; read-only
        assert first.files == [] and git(work, "rev-list", "--count", f"{start}..HEAD") == "1"
        assert url.startswith(f"https://github.com/{fork}/pull/")
        assert (first.branch, first.fork, first.created_fork) == (branch, fork, False)
        assert git(work, "rev-parse", "--abbrev-ref", "HEAD") == branch
        assert git(work, "status", "--porcelain", "--", "cdl.bib", "verification") == "" and snapshot() == edits
        assert first.left == ["README.md", "loose.txt", "staged.txt"]
        found = open_prs(fork, branch)
        assert [p["url"] for p in found] == [url]
        assert found[0]["title"] == summary and found[0]["body"] == "added the following entries: Rame72"
        assert found[0]["baseRefName"] == TEST_BASE

        ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n\n% a second edit\n", encoding="utf-8")
        second = api.send(ws, **options)                             # no summary: still the same branch
        assert (second.url, second.branch) == (url, branch)
        found = open_prs(fork, branch)
        assert [p["url"] for p in found] == [url]                    # updated, never duplicated
        assert found[0]["title"] == summary                          # and it keeps the title it was given
        remote_head = git(work, "ls-remote", f"https://github.com/{fork}.git", f"refs/heads/{branch}").split()[0]
        assert remote_head == git(work, "rev-parse", "HEAD") and git(work, "rev-list", "--count", f"{start}..HEAD") == "2"

        third = api.send(ws, **options)                              # nothing new: the same pull request again
        assert third.url == url and git(work, "rev-list", "--count", f"{start}..HEAD") == "2"
        assert snapshot() == edits                                   # my other edits: same bytes, same git state
        assert set(git(work, "log", "--name-only", "--format=", f"{start}..HEAD").split()) == {"cdl.bib"}   # all that was sent
        assert second.files == ["cdl.bib"] and publish.earlier_pr(fork, f"{login}:{branch}") is None   # it is open

        # The pull request is closed; a further send from its branch is refused before git is written to.
        subprocess.run(["gh", "pr", "close", url], cwd=work, capture_output=True, check=True)
        assert publish.earlier_pr(fork, f"{login}:{branch}") == (url, "closed")
        ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n\n% a third edit\n", encoding="utf-8")
        before, remote_head = state(work), git(work, "ls-remote", f"https://github.com/{fork}.git", f"refs/heads/{branch}")
        with pytest.raises(PublishRefused) as refused:
            api.send(ws, **options)
        message = str(refused.value)
        assert f"pull request {url} is closed" in message
        assert f"  git switch {TEST_BASE}\n  git pull https://github.com/{fork}.git {TEST_BASE}\n  cdlbib send\n" in message
        assert "carried along by `git switch`" in message
        assert state(work) == before
        assert git(work, "ls-remote", f"https://github.com/{fork}.git", f"refs/heads/{branch}") == remote_head
        assert open_prs(fork, branch) == []

        # Back on the default branch, the same summary on the same day names that finished branch again: refused too.
        ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n\n% a second edit\n", encoding="utf-8")   # as committed
        git(work, "switch", "-q", "-")
        ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n", encoding="utf-8")
        before = state(work)
        assert before[1] != branch
        with pytest.raises(PublishRefused) as refused:
            api.send(ws, summary=summary, **options)
        assert f"Branch {branch} was already used for pull request {url}, which is closed" in str(refused.value)
        assert "different --summary" in str(refused.value)
        assert state(work) == before
        assert git(work, "ls-remote", f"https://github.com/{fork}.git", f"refs/heads/{branch}") == remote_head
    finally:
        clean_up(work, url, branch)


def test_after_a_send_the_update_reads_the_pull_request_inside_my_own_fork(tmp_path, monkeypatch):
    """The state of a real pull request, as publish.pull_request reads it from GitHub, and what
    the managed library's update does with it: open, then closed. The managed library here is a
    scratch clone of the tester's fork in a data folder of this test; the pull request is opened
    inside that fork, on the test base, and closed and deleted at the end. The merged case is not
    run against GitHub (nothing is ever merged by a test): tests/test_update.py covers it with
    the state given as an argument.

    The update's own lookup is also run for real, read-only: the library's origin is a fork, so
    it asks the fork's parent for pull requests from this branch, and there are none."""
    from cdlbib import library, workspace
    from cdlbib.errors import UpdateNeedsDecision
    from test_update import backup_names, whole_clone
    login, fork = my_fork()
    if login is None:
        pytest.skip(fork)
    home = tmp_path / "home"
    home.mkdir()
    root = home / "library"
    fork_clone(home, monkeypatch, fork).rename(root)                  # the guarded fixture, unchanged
    monkeypatch.setenv("CDLBIB_HOME", str(home))
    monkeypatch.setenv("CDLBIB_UPSTREAM", git(root, "remote", "get-url", "origin"))
    monkeypatch.delenv("CDLBIB_LIBRARY", raising=False)
    workspace.select_library(None)
    ws = Workspace(root)
    branch, url = f"cdlbib/{login}/test-{os.getpid()}-after-send", None
    head = f"{login}:{branch}"
    try:
        assert api.is_managed(ws) and git(root, "rev-parse", "--abbrev-ref", "HEAD") != branch
        assert publish.pull_request(fork, head) is None and publish.pull_request_state(fork, head) is None
        ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + "\n% cdlbib test edit\n", encoding="utf-8")
        tip = publish.commit_to_branch(ws, branch, "cdlbib test: please ignore")
        publish.push(ws, f"https://github.com/{fork}.git", branch)
        url = publish.open_or_update_pr(fork, TEST_BASE, branch, "cdlbib test: please ignore", "Automated test; closed immediately.")
        before = whole_clone(root)

        found = publish.pull_request(fork, head)                      # open
        assert found == publish.PullRequest(url=url, state="open", head=tip, matching=1)
        assert publish.pull_request_state(fork, head) == "open" and publish.earlier_pr(fork, head) is None
        result = library._after_send(ws, found.state, url=found.url, head=found.head)
        assert (result.action, result.message) == ("left_alone", f"your pull request is still open: {url}; nothing was changed")
        assert whole_clone(root) == before and backup_names(home) == []

        result = library.update(ws, force=True)                       # the real lookup, in the fork's parent: read-only
        assert (result.action, result.backup) == ("left_alone", None)
        assert result.message == (f"the library is on branch {branch}, which has no pull request in {UPSTREAM}; nothing "
                                  f"was changed. Run `cdlbib send` to send it, or `git -C {shlex.quote(str(root))} switch "
                                  f"{git(root, 'rev-parse', '--abbrev-ref', 'origin/HEAD').split('/', 1)[1]}` to leave the branch.")
        assert whole_clone(root) == before and backup_names(home) == []

        subprocess.run(["gh", "pr", "close", url], cwd=root, capture_output=True, check=True)
        found = publish.pull_request(fork, head)                      # closed, not merged
        assert found == publish.PullRequest(url=url, state="closed", head=tip, matching=1)
        assert publish.pull_request_state(fork, head) == "closed" and publish.earlier_pr(fork, head) == (url, "closed")
        with pytest.raises(UpdateNeedsDecision) as raised:
            library._after_send(ws, found.state, url=found.url, head=found.head)
        asked = raised.value
        assert (asked.branch, asked.pull_request, asked.state, asked.local_commits) == (branch, url, "closed", 1)
        assert asked.choices == ("keep", "discard") and asked.changed == []
        assert whole_clone(root) == before and backup_names(home) == []
        assert open_prs(fork, branch) == []
    finally:
        clean_up(root, url, branch)
        workspace.select_library(None)


def test_a_push_that_cannot_sign_in_names_gh_auth_setup_git(tmp_path, monkeypatch):
    """A real https push with no credentials at all (no global or system git configuration,
    so no credential helper; git may not prompt). The target is the tester's own fork and a
    cdlbib/<login>/test-* branch, so a push that did get through would land in the guarded
    fixture and be deleted."""
    login, fork = my_fork()
    if login is None:
        pytest.skip(fork)
    work = fork_clone(tmp_path, monkeypatch, fork)
    ws = Workspace(work)
    branch = f"cdlbib/{login}/test-{os.getpid()}-signin"
    try:
        ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + "\n% cdlbib test edit\n", encoding="utf-8")
        home = tmp_path / "empty-home"; home.mkdir()
        with monkeypatch.context() as patch:
            patch.setenv("HOME", str(home))
            patch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
            patch.setenv("GIT_CONFIG_NOSYSTEM", "1")
            for name in ("GIT_ASKPASS", "SSH_ASKPASS", "GH_TOKEN", "GITHUB_TOKEN"):
                patch.delenv(name, raising=False)
            with pytest.raises(PublishRefused) as refused:
                publish.deliver(ws, branch, "cdlbib test: please ignore", f"https://github.com/{fork}.git", target=fork)
        message = str(refused.value)
        assert f"committed on branch {branch}" in message
        assert "run `gh auth setup-git` (it makes git use gh's login). Run `cdlbib send` again to resume" in message
        assert message.count("`cdlbib send` again") == 1
        assert git(work, "ls-remote", f"https://github.com/{fork}.git", f"refs/heads/{branch}") == ""   # nothing arrived
    finally:
        clean_up(work, None, branch)
