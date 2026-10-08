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


# The most entries of the committed cdl.bib that may be without a saved result in the committed
# snapshot (verification/baseline.jsonl.gz). Some always are: a pull request that adds a
# reference, or edits one, is checked before anything is saved for the new text, and what it
# adds stays without a saved result until the snapshot is next saved. Were most of the library
# without one, the tests below would no longer be checking the library.
MOST_WITHOUT_A_SAVED_RESULT = 200


@pytest.fixture(scope="module", autouse=True)
def one_parse_of_each_text():
    """The tests read the clone's bibliography themselves, for an entry's text and fingerprint
    (seven times, six seconds each): within this module it is parsed once for each text the
    file has, told by the file's bytes (verification.read_once). The script's own runs are
    other processes and read it for themselves."""
    from cdlbib import verification
    with verification.read_once(by_content=True):
        yield


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    repo = tmp_path_factory.mktemp("ci") / "repo"
    subprocess.run(["git", "clone", "-q", str(ROOT), str(repo)], check=True)
    for k, v in (("user.name", "check_ci test"), ("user.email", "check-ci-test@example.org")):
        subprocess.run(["git", "config", k, v], cwd=repo, check=True)
    # The saved results are a snapshot: entries added to cdl.bib since it was last saved (a
    # pull request that only adds references) have none yet. These tests are about what the
    # script does with a library and the results saved for it, so the clone's cdl.bib holds
    # exactly the entries whose present text has a saved result in the committed snapshot.
    # (Read from the snapshot itself, not from the history: actions/checkout fetches one
    # commit, and there the commit that last saved the snapshot cannot be asked for.)
    # The snapshot is restored by the command the script itself runs, then asked entry by entry.
    import shutil
    from cdlbib import verification
    from cdlbib.workspace import Workspace
    bib = repo / "cdl.bib"
    sibling = Path(sys.executable).parent / "cdlbib"
    subprocess.run([str(sibling) if sibling.exists() else shutil.which("cdlbib"), "crossref", "restore",
                    "verification/baseline.jsonl.gz"], cwd=repo, check=True, capture_output=True)
    cache = verification.Cache(Workspace.for_bib(str(bib)).database, approvals=False)
    try:
        entries = verification.load_entries(str(bib))
        saved = {key: cache.stored(str(bib), entry) for key, entry in entries.items()}
    finally:
        cache.close()
    without = sorted(key for key, result in saved.items() if result is None or result["status"] == "pending")
    # These tests are about the script and a library with its saved results, so the entries
    # that have none are taken out of the clone's library, whichever they are: a pull request
    # that adds a reference must not fail them. They are few; were they many, the saved
    # results would be out of step with the library, and that fails here.
    assert len(without) <= MOST_WITHOUT_A_SAVED_RESULT and len(without) * 20 <= len(entries), (
        f"{len(without)} of {len(entries)} entries of the committed cdl.bib have no saved result in "
        f"verification/baseline.jsonl.gz, among them {without[:10]}. Save the results again "
        "(cdlbib crossref snapshot, after verifying the entries).")
    if without:
        text = bib.read_bytes().decode("utf-8")
        for key in without:
            raw = entries[key]["raw"]
            assert text.count(raw) == 1, key
            text = text.replace(raw, "")
        bib.write_bytes(text.encode("utf-8"))
        kept = verification.load_entries(str(bib))
        assert set(kept) == set(entries) - set(without)
        assert all(kept[key]["fingerprint"] == entries[key]["fingerprint"] for key in kept)
        subprocess.run(["git", "commit", "-q", "-m", "cdl.bib: the entries the saved results are for", "cdl.bib"],
                       cwd=repo, check=True)
    return repo


def run_ci(repo, event, base, keep=False, python=None, path=None):
    """One run of the script. ``keep``: the results of the run before stay (.bibcheck), as the
    workflow's cache keeps them from one run on a branch to the next; otherwise the run
    starts with none. ``python``: the interpreter that runs the script (this one, which has
    the package, unless given); ``path``: a folder put first on its PATH."""
    env = dict(os.environ, EVENT_NAME=event, BASE_REVISION=base,
               CROSSREF_MAILTO=os.environ.get("CROSSREF_MAILTO", "check-ci-test@example.org"))
    if path:
        env["PATH"] = str(path) + os.pathsep + env.get("PATH", "")
    if not keep:
        subprocess.run(["rm", "-rf", ".bibcheck"], cwd=repo, check=True)
    return subprocess.run([str(python or sys.executable), "verification/check_ci.py"], cwd=repo, env=env,
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


def test_a_push_reads_the_approvals_the_pushed_commit_brings_for_the_entries_it_changes(clone):
    """One commit edits an entry so that it needs a person's review and adds a valid ledger row
    approving that exact text (an edit and its approval merged together). As a pull request
    against the commit before it, the row is the pull request's own: the entry needs review and
    the check fails. As the push of that same commit, the row is already merged and counts:
    the entry is human_verified and the check passes. A row for another text of the entry
    does not count on a push either."""
    from cdlbib import verification as v
    key = "Zoll90"
    start = head(clone)
    bib = clone / "cdl.bib"
    before = v.load_entries(str(bib))[key]
    assert before["raw"].count("1990") >= 1
    edited = before["raw"].replace("1990", "1890")                           # no source gives this year
    text = bib.read_bytes().decode("utf-8")
    assert edited != before["raw"] and text.count(before["raw"]) == 1
    bib.write_bytes(text.replace(before["raw"], edited).encode("utf-8"))
    entry = v.load_entries(str(bib))[key]
    assert entry["fingerprint"] != before["fingerprint"]
    review = {"reviewer": "@octocat", "source": "https://doi.org/10.1002/tea.3660271011",
              "note": "Fixture: an edit and its approval in one commit.", "github_login": "octocat", "github_id": 583231}

    def commit(fingerprint, message):
        row = {"key": key, "fingerprint": fingerprint, "human_review": review,
               "approval_digest": v.approval_digest(review), "approved_at": v.now(), "policy": v.POLICY}
        assert v.valid_shared_approval(row)
        with open(clone / "verification" / "approvals.jsonl", "a", encoding="utf-8") as stream:
            stream.write(v.dumps(row) + "\n")
        subprocess.run(["git", "add", "cdl.bib", "verification/approvals.jsonl"], cwd=clone, check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=clone, check=True)

    # The edited text is checked against its sources once (the pull request run): the push
    # run before it reads the row and checks nothing, and the push run after it finds the
    # result the pull request run stored, as a run on a branch finds the results of the run
    # before it in the workflow's cache.
    try:
        commit(entry["fingerprint"], "Zoll90 edited, with its approval")
        run = run_ci(clone, "push", start)
        assert run.returncode == 0, run.stdout + run.stderr                  # merged: the row counts
        assert reported(clone, key) == "human_verified"
        assert (clone / ".bibcheck" / "pushed-approvals.jsonl").read_bytes() == (clone / "verification" / "approvals.jsonl").read_bytes()
        run = run_ci(clone, "pull_request", start)
        assert run.returncode == 1, run.stdout + run.stderr                  # the pull request's own row is not read
        assert reported(clone, key) == "needs_review"
        assert (clone / ".bibcheck" / "base-approvals.jsonl").read_bytes() == subprocess.run(
            ["git", "show", f"{start}:verification/approvals.jsonl"], cwd=clone, capture_output=True).stdout
    finally:
        subprocess.run(["git", "reset", "-q", "--hard", start], cwd=clone, check=True)
    try:                                                                     # the edit alone: no row for this text
        bib.write_bytes(text.replace(before["raw"], edited).encode("utf-8"))
        subprocess.run(["git", "commit", "-q", "-m", "Zoll90 edited, no approval", "cdl.bib"], cwd=clone, check=True)
        run = run_ci(clone, "push", start, keep=True)
        assert run.returncode == 1, run.stdout + run.stderr
        assert reported(clone, key) == "needs_review"
        assert (clone / ".bibcheck" / "pushed-approvals.jsonl").read_bytes() == subprocess.run(
            ["git", "show", f"{start}:verification/approvals.jsonl"], cwd=clone, capture_output=True).stdout
    finally:
        subprocess.run(["git", "reset", "-q", "--hard", start], cwd=clone, check=True)


def test_a_pull_request_that_deletes_a_revocation_does_not_revive_the_base_approval(clone):
    """The base holds a ledger approval of Zoll90 and, in verification/revocations.jsonl only,
    its revocation. The pull request deletes that revocation line. The check honours the base
    revision's revocations together with the pull request's: the approval stays revoked.
    Control: with the revocation never made, the same approval counts."""
    from cdlbib import verification as v
    key = "Zoll90"
    entry = v.load_entries(str(clone / "cdl.bib"))[key]
    review = {"reviewer": "@octocat", "source": "https://doi.org/10.1002/tea.3660271011",
              "note": "Compared every field with the printed article.", "github_login": "octocat", "github_id": 583231}
    row = {"key": key, "fingerprint": entry["fingerprint"], "human_review": review,
           "approval_digest": v.approval_digest(review), "approved_at": v.now(), "policy": v.POLICY}
    revocation = {"key": key, "fingerprint": row["fingerprint"], "approval": review, "approval_digest": row["approval_digest"],
                  "approval_checked_at": row["approved_at"], "revoked_at": v.now(), "revoked_by": "@hubot",
                  "reason": "Recorded in error."}
    assert v.valid_shared_approval(row) and v.valid_revocation(revocation)
    start = head(clone)
    revocations = clone / "verification" / "revocations.jsonl"
    kept = revocations.read_bytes()

    def commit(message):
        subprocess.run(["git", "add", "verification"], cwd=clone, check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=clone, check=True)
        return head(clone)
    try:
        with open(clone / "verification" / "approvals.jsonl", "a", encoding="utf-8") as stream:
            stream.write(v.dumps(row) + "\n")
        approved = commit("an approval of Zoll90")
        run = run_ci(clone, "push", approved)                                # control: approved, not revoked
        assert run.returncode == 0 and reported(clone, key) == "human_verified", run.stdout + run.stderr
        revocations.write_bytes(kept + (v.dumps(revocation) + "\n").encode("utf-8"))
        base = commit("its revocation")
        run = run_ci(clone, "push", base)
        assert run.returncode == 0 and reported(clone, key) == "metadata_verified", run.stdout + run.stderr
        revocations.write_bytes(kept)                                        # the pull request: the line is gone
        commit("delete the revocation")
        run = run_ci(clone, "pull_request", base)
        assert run.returncode == 0, run.stdout + run.stderr
        assert (clone / ".bibcheck" / "base-revocations.jsonl").read_bytes().endswith((v.dumps(revocation) + "\n").encode("utf-8"))
        assert reported(clone, key) == "metadata_verified"                   # still revoked
    finally:
        subprocess.run(["git", "reset", "-q", "--hard", start], cwd=clone, check=True)


def test_a_pull_request_that_adds_a_row_that_is_no_valid_row_today_fails_the_check(clone):
    """Rows are validated when they enter. A pull request adds a ledger row dated in the
    future (which no reader counts today and which would start counting when its date came):
    the check fails, naming the line, before anything is verified. So does one that alters a
    line the base already holds. A valid row added passes this step (the tests above)."""
    from cdlbib import verification as v
    entry = v.load_entries(str(clone / "cdl.bib"))["Zoll90"]
    review = {"reviewer": "@octocat", "source": "https://doi.org/10.1002/tea.3660271011",
              "note": "Compared every field with the printed article.", "github_login": "octocat", "github_id": 583231}
    row = {"key": "Zoll90", "fingerprint": entry["fingerprint"], "human_review": review,
           "approval_digest": v.approval_digest(review), "approved_at": v.now(), "policy": v.POLICY}
    start = head(clone)
    ledger = clone / "verification" / "approvals.jsonl"
    kept = ledger.read_bytes() if ledger.exists() else b""

    def commit(data, message):
        ledger.write_bytes(data)
        subprocess.run(["git", "add", "verification/approvals.jsonl"], cwd=clone, check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=clone, check=True)
        return head(clone)
    try:
        future = dict(row, approved_at="2099-01-01T00:00:00+00:00")
        commit(kept + (v.dumps(future) + "\n").encode("utf-8"), "a row dated 2099")
        run = run_ci(clone, "pull_request", start)
        assert run.returncode == 1, run.stdout + run.stderr
        assert "is not a valid approval row: approved_at (2099-01-01T00:00:00+00:00) is later than the present time" in run.stdout
        assert "Restored" not in run.stdout                                  # it stopped before the baseline was read
        base = commit(kept + (v.dumps(row) + "\n").encode("utf-8"), "a valid row instead")
        commit(kept + (v.dumps(row) + "\n").encode("utf-8").replace(b"Compared", b"compared"), "the row altered")
        run = run_ci(clone, "pull_request", base)
        assert run.returncode == 1 and "already held was removed or changed" in run.stdout, run.stdout + run.stderr
    finally:
        subprocess.run(["git", "reset", "-q", "--hard", start], cwd=clone, check=True)


def test_a_python_without_the_package_runs_the_installed_command_with_the_same_outcome(clone, tmp_path):
    """The script runs its `cdlbib crossref` commands in its own process when the package is
    installed for the Python that runs it (every test above), and otherwise as the installed
    command, a process each (here: found on PATH). The same check gives the same status and
    prints the same either way: a pull request that adds a ledger row dated in the future
    fails, naming the line, before the baseline is read."""
    from cdlbib import verification as v
    bare = tmp_path / "bare"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(bare)], check=True, capture_output=True)
    python = bare / "bin" / "python"
    missing = subprocess.run([str(python), "-c", "import cdlbib"], capture_output=True, text=True)
    assert missing.returncode != 0 and "No module named 'cdlbib'" in missing.stderr     # it has no package
    assert not (bare / "bin" / "cdlbib").exists()                                       # nor the command beside it
    installed = Path(sys.executable).parent                                             # where this Python's command is
    assert (installed / "cdlbib").exists()
    entry = v.load_entries(str(clone / "cdl.bib"))["Zoll90"]
    review = {"reviewer": "@octocat", "source": "https://doi.org/10.1002/tea.3660271011",
              "note": "Compared every field with the printed article.", "github_login": "octocat", "github_id": 583231}
    row = {"key": "Zoll90", "fingerprint": entry["fingerprint"], "human_review": review,
           "approval_digest": v.approval_digest(review), "approved_at": "2099-01-01T00:00:00+00:00", "policy": v.POLICY}
    start = head(clone)
    refused = "is not a valid approval row: approved_at (2099-01-01T00:00:00+00:00) is later than the present time"
    try:
        with open(clone / "verification" / "approvals.jsonl", "a", encoding="utf-8") as stream:
            stream.write(v.dumps(row) + "\n")
        subprocess.run(["git", "add", "verification/approvals.jsonl"], cwd=clone, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "a row dated 2099"], cwd=clone, check=True)
        own = run_ci(clone, "pull_request", start)                                      # in this Python's process
        other = run_ci(clone, "pull_request", start, python=python, path=installed)     # as the command on PATH
        for run in (own, other):
            assert run.returncode == 1, run.stdout + run.stderr
            assert refused in run.stdout and "Restored" not in run.stdout
        assert own.stdout == other.stdout
    finally:
        subprocess.run(["git", "reset", "-q", "--hard", start], cwd=clone, check=True)
