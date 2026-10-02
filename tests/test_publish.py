"""Sending a change: the user's fork, a branch, a pull request (cdlbib.publish, api.send,
`cdlbib commit`).

Real git against real local bare repositories; the real gh. The pull-request tests work
only inside the tester's own fork, on the branch cdlbib-test-base, and skip with their
reason where no user is logged in or the user has no fork. No mocks.
"""
import datetime
import json
import os
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


# A. cdlbib.publish, local ---------------------------------------------------------------

def test_upstream_is_parsed_from_https_and_ssh(tmp_path):
    for number, url in enumerate(("https://github.com/ContextLab/CDL-bibliography.git",
                                  "git@github.com:ContextLab/CDL-bibliography.git",
                                  "https://github.com/ContextLab/CDL-bibliography",
                                  "ssh://git@github.com/ContextLab/CDL-bibliography.git")):
        repo = tmp_path / str(number)
        git(tmp_path, "init", "-q", str(repo)); git(repo, "remote", "add", "origin", url)
        assert publish.upstream_of(Workspace(repo)) == "ContextLab/CDL-bibliography"


def test_upstream_refuses_a_checkout_that_is_not_from_github(checkout, tmp_path):
    ws, _ = checkout                                    # its origin is a local bare repository
    with pytest.raises(PublishRefused, match="not a GitHub repository"):
        publish.upstream_of(ws)
    with pytest.raises(PublishRefused):                 # not a git checkout at all
        publish.upstream_of(Workspace(tmp_path))


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

def test_send_refuses_on_unrelated_changes_and_leaves_the_tree_alone(checkout):
    ws, _ = checkout
    (ws.root / "cdl.bib").write_text("% library\n% edit\n", encoding="utf-8")
    (ws.root / "README.md").write_text("changed\n", encoding="utf-8")
    before = state(ws.root)
    with pytest.raises(PublishRefused, match="README.md"):
        api.send(ws, summary="edit", reference=str(ws.bib), upstream="someone/x", base=TEST_BASE)
    assert state(ws.root) == before


def test_send_refuses_on_a_failed_gate_before_touching_git(checkout):
    ws, _ = checkout
    (ws.root / "cdl.bib").write_text("@article{Bad,\n\tPages = {10--1}}\n", encoding="utf-8")
    before = state(ws.root)
    with pytest.raises(GateFailed) as refused:
        api.send(ws, summary="bad", reference=str(ws.bib), upstream="someone/x", base=TEST_BASE)
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
        api.send(ws, summary="edit", reference=str(ws.bib), citations=False, upstream="someone/x", base=TEST_BASE)
    assert state(ws.root) == before


def test_send_outside_a_git_checkout_refuses(tmp_path):
    bib = tmp_path / "plain" / "cdl.bib"
    bib.parent.mkdir()
    bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    with pytest.raises(PublishRefused):
        api.send(Workspace(bib.parent), reference=str(bib), citations=False, upstream="someone/x", base=TEST_BASE)


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


def test_commit_command_reports_a_failed_gate_and_changes_nothing(checkout, tmp_path):
    ws = library_checkout(checkout, ZOLL90 + "\n")
    ws.bib.write_text(ZOLL90.replace("1053--1065", "1053--105") + "\n", encoding="utf-8")
    before = state(ws.root)
    run = cdlbib(ws.root, "commit", "--reference", str(ws.bib), "--database", str(tmp_path / "db.sqlite3"))
    assert run.returncode == 1, run.stdout + run.stderr
    assert run.stdout.endswith("not committed: fix the format errors and resolve every new/edited entry first "
                               "(see `cdlbib verify`).\n")
    assert "pull request" not in run.stdout and state(ws.root) == before


def test_commit_command_refuses_stray_files_on_stderr(checkout, tmp_path):
    ws = library_checkout(checkout, ZOLL90 + "\n")
    (ws.root / "README.md").write_text("changed\n", encoding="utf-8")
    before = state(ws.root)
    run = cdlbib(ws.root, "commit", "--reference", str(ws.bib), "--database", str(tmp_path / "db.sqlite3"))
    assert run.returncode == 1 and "README.md" in run.stderr and "Traceback" not in run.stderr, run.stdout + run.stderr
    assert state(ws.root) == before


def test_commit_command_refuses_an_unresolved_entry(checkout, tmp_path):
    """The gate reached through `commit`: a real Crossref check of a new entry whose volume is
    wrong (Crossref: 1). The entry is named, nothing is sent, the checkout is untouched."""
    ws = library_checkout(checkout, ZOLL90 + "\n")
    base = tmp_path / "base.bib"; base.write_text(ZOLL90 + "\n", encoding="utf-8")
    ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "2" + "\n", encoding="utf-8")
    before = state(ws.root)
    run = cdlbib(ws.root, "commit", "--reference", str(base), "--database", str(tmp_path / "db.sqlite3"),
                 CROSSREF_MAILTO=crossref_contact())
    assert run.returncode == 1 and "UNRESOLVED Rame72" in run.stdout and "not committed" in run.stdout, run.stdout + run.stderr
    assert "pull request" not in run.stdout and state(ws.root) == before


def test_magic_goes_through_the_same_send(checkout):
    ws = library_checkout(checkout, ZOLL90 + "\n")
    (ws.root / "README.md").write_text("changed\n", encoding="utf-8")
    before = state(ws.root)
    run = cdlbib(ws.root, "magic")
    assert run.returncode == 1 and "WARNING: potentially unsafe" in run.stdout, run.stdout + run.stderr
    assert "README.md" in run.stderr and "Traceback" not in run.stderr and not (ws.root / "cleaned.bib").exists()
    assert state(ws.root)[1:] == before[1:]             # magic rewrites cdl.bib in place; git is untouched


def gh_login():
    if not shutil.which("gh"):
        return None, "gh is not installed"
    who = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True)
    if who.returncode != 0 or not who.stdout.strip():
        return None, "no GitHub user is logged in (expected in CI)"
    return who.stdout.strip(), ""


def test_commit_command_never_creates_a_fork_unasked(checkout, tmp_path):
    """The gate passes, the user has no fork of the checkout's upstream, there is no terminal
    and no --yes: nothing is forked; the manual command is printed; exit 1."""
    login, reason = gh_login()
    if login is None:
        pytest.skip(reason)
    other = "cli/scoop-gh"                              # a small public repository standing in for an upstream
    if publish.find_fork(other, login):
        pytest.skip(f"@{login} has a fork of {other}, so the no-fork refusal cannot be shown")
    ws = library_checkout(checkout, ZOLL90 + "\n")      # nothing is changed: even a fork could send nothing
    git(ws.root, "remote", "set-url", "origin", f"https://github.com/{other}.git")
    before = state(ws.root)
    run = cdlbib(ws.root, "commit", "--reference", str(ws.bib), "--database", str(tmp_path / "db.sqlite3"))
    assert run.returncode == 1, run.stdout + run.stderr
    assert f"@{login} has no fork of {other}" in run.stderr
    assert f"gh repo fork {other} --clone=false" in run.stderr
    assert publish.find_fork(other, login) is None      # still none
    assert state(ws.root) == before


# C. The real pull request, inside the tester's own fork only ----------------------------

def my_fork():
    """(login, 'login/NAME') for the logged-in user's fork of the upstream repo, else a skip reason."""
    login, reason = gh_login()
    if login is None:
        return None, reason
    fork = publish.find_fork(UPSTREAM, login)
    return (login, fork) if fork else (None, f"@{login} has no fork of {UPSTREAM}; run `cdlbib commit` once or `gh repo fork`")


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
        subprocess.run(["gh", "pr", "close", url, "--delete-branch"], capture_output=True)
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
                   upstream=fork, base=TEST_BASE, fork=fork)
    summary = f"cdlbib test {os.getpid()}: please ignore"
    branch = publish.branch_name(login, summary, datetime.date.today())
    url, start = None, git(work, "rev-parse", "HEAD")
    try:
        ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n", encoding="utf-8")
        first = api.send(ws, summary=summary, **options)
        url = first.url
        assert url.startswith(f"https://github.com/{fork}/pull/")
        assert (first.branch, first.fork, first.created_fork) == (branch, fork, False)
        assert git(work, "rev-parse", "--abbrev-ref", "HEAD") == branch and git(work, "status", "--porcelain") == ""
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
    finally:
        clean_up(work, url, branch)
