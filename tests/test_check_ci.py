"""verification/check_ci.py, run for real in temporary clones of the repository.

A push whose previous commit is not in the history (force-push, rewritten history, new
branch) checks the whole library against its own committed baseline, offline. Pull
requests keep the trusted-base rule. No mocks: each case runs the script as CI does.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    repo = tmp_path_factory.mktemp("ci") / "repo"
    subprocess.run(["git", "clone", "-q", str(ROOT), str(repo)], check=True)
    for k, v in (("user.name", "check_ci test"), ("user.email", "check-ci-test@example.org")):
        subprocess.run(["git", "config", k, v], cwd=repo, check=True)
    return repo


def run_ci(repo, event, base):
    env = dict(os.environ, EVENT_NAME=event, BASE_REVISION=base,
               CROSSREF_MAILTO=os.environ.get("CROSSREF_MAILTO", "check-ci-test@example.org"))
    subprocess.run(["rm", "-rf", ".bibcheck"], cwd=repo, check=True)
    return subprocess.run([sys.executable, "verification/check_ci.py"], cwd=repo, env=env,
                          capture_output=True, text=True)


def head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


MISSING = "ab" * 20  # a well-formed SHA that is not in the history


def test_push_with_missing_base_checks_the_committed_library(clone):
    run = run_ci(clone, "push", MISSING)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "not in the history" in run.stdout
    assert "pending" not in run.stdout and "needs_review" not in run.stdout


def test_push_with_new_branch_base_checks_the_committed_library(clone):
    run = run_ci(clone, "push", "0" * 40)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "not in the history" in run.stdout


def test_push_with_missing_base_fails_an_edited_entry_without_its_result(clone):
    bib = clone / "cdl.bib"
    original = bib.read_text()
    # Negative control: change one entry's text without a matching saved result.
    edited = original.replace("Title = {A probabilistic distance measure for hidden {M}arkov models}",
                              "Title = {A probabilistic distance measure for hidden {M}arkov chains}", 1)
    assert edited != original
    bib.write_text(edited)
    try:
        run = run_ci(clone, "push", MISSING)
        assert run.returncode == 1, run.stdout + run.stderr
        assert "pending=1" in run.stdout
    finally:
        bib.write_text(original)


def test_pull_request_still_requires_a_base(clone):
    run = run_ci(clone, "pull_request", "0" * 40)
    assert run.returncode == 2
    assert "Missing base revision" in run.stderr


def test_push_with_reachable_base_and_no_change_selects_nothing(clone):
    run = run_ci(clone, "push", head(clone))
    assert run.returncode == 0, run.stdout + run.stderr
    assert "not in the history" not in run.stdout


def reported(repo, key):
    """The status the run's report (.bibcheck/report.jsonl) gives ``key``."""
    import json
    for line in (repo / ".bibcheck" / "report.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["key"] == key:
            return row["status"]
    raise AssertionError(f"{key} is not in the report")


def test_a_pull_request_reads_the_approvals_ledger_of_its_base_only(clone):
    """A commit adds a valid ledger row (verification/approvals.jsonl) approving Zoll90 as it
    stands. As a pull request against the commit before it, the row is the pull request's own
    and is not read: Zoll90 keeps the status of the base's baseline. Once the base holds the
    row (the push after the merge, or the committed library checked whole), it is read."""
    from cdlbib import verification as v
    key = "Zoll90"
    entry = v.load_entries(str(clone / "cdl.bib"))[key]
    review = {"reviewer": "@octocat", "source": "https://doi.org/10.1002/tea.3660271011",
              "note": "Compared every field with the printed article.", "github_login": "octocat", "github_id": 583231}
    row = {"key": key, "fingerprint": entry["fingerprint"], "human_review": review,
           "approval_digest": v.approval_digest(review), "approved_at": v.now(), "policy": v.POLICY}
    assert v.valid_shared_approval(row)
    start = head(clone)
    ledger = clone / "verification" / "approvals.jsonl"
    with open(ledger, "a", encoding="utf-8") as stream:
        stream.write(v.dumps(row) + "\n")
    subprocess.run(["git", "add", "verification/approvals.jsonl"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "an approval of Zoll90"], cwd=clone, check=True)
    try:
        run = run_ci(clone, "pull_request", start)
        assert run.returncode == 0, run.stdout + run.stderr                  # no entry changed: nothing is gated
        assert reported(clone, key) == "metadata_verified"                   # and the row approved nothing
        at_base = subprocess.run(["git", "show", f"{start}:verification/approvals.jsonl"], cwd=clone, capture_output=True)
        assert (clone / ".bibcheck" / "base-approvals.jsonl").read_bytes() == at_base.stdout
        run = run_ci(clone, "push", head(clone))                             # the base holds the row
        assert run.returncode == 0, run.stdout + run.stderr
        assert reported(clone, key) == "human_verified"
        run = run_ci(clone, "push", MISSING)                                 # the committed library, checked whole
        assert run.returncode == 0, run.stdout + run.stderr
        assert reported(clone, key) == "human_verified"
    finally:
        subprocess.run(["git", "reset", "-q", "--hard", start], cwd=clone, check=True)
