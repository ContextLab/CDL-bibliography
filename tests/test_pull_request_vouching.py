"""Who vouches for the approvals a pull request adds (verification/check_ci.py), and the
lines a pull request's check ends with (`crossref check-summary`).

A row a pull request adds to verification/approvals.jsonl counts in that pull request's own
check only when someone with write access to the repository vouches for it: the author, for
the rows the author recorded, or a reviewer whose approval stands for the present head
commit, for all of them. GitHub is asked; the row is not.

The decision is tested on answers api.github.com really gave (tests/fixtures/github_vouching,
whose README says what was recorded and which three cases are built from a recorded answer),
and once against GitHub itself. The summary is tested on real files with the real command.
"""
import copy
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cdlbib import verification as v
from cdlbib.verification_cli import app

from test_baseline_additions import KEYS, RESULTS, library, statuses, texts

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "github_vouching"
REPOSITORY = "ContextLab/CDL-bibliography"


@pytest.fixture(scope="module")
def ci():
    """verification/check_ci.py of this checkout, loaded as the module it is."""
    spec = importlib.util.spec_from_file_location("check_ci_under_test", ROOT / "verification" / "check_ci.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _the_librarys_own_ledgers(monkeypatch):
    monkeypatch.setattr(v, "REVOCATION_LEDGER", None)


def recorded(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def pull(number):
    facts = recorded(f"pull-{number}.json")
    return facts["author"], facts["head_sha"], recorded(f"reviews-pull-{number}.json")


def permissions(*logins):
    return {login.casefold(): recorded(f"permission-{login}.json") for login in logins}


# --- write access ---------------------------------------------------------------------------------


def test_write_access_is_what_github_says_of_the_account_asked_about(ci):
    assert ci.has_write_access(recorded("permission-jeremymanning.json"), "jeremymanning")     # admin
    assert ci.has_write_access(recorded("permission-jeremymanning.json"), "JeremyManning")     # logins have no case
    assert not ci.has_write_access(recorded("permission-octocat.json"), "octocat")             # read
    assert not ci.has_write_access(recorded("permission-paxtonfitzpatrick.json"), "paxtonfitzpatrick")
    # An answer about another account says nothing of this one.
    assert not ci.has_write_access(recorded("permission-jeremymanning.json"), "octocat")
    for permission, expected in (("admin", True), ("maintain", True), ("write", True), ("triage", False),
                                 ("read", False), ("none", False)):
        assert ci.has_write_access(dict(recorded("permission-octocat.json"), permission=permission), "octocat") is expected
    for unexpected in ([], None, {}, {"permission": "admin"}, {"permission": True, "user": {"login": "octocat"}},
                       {"message": "Bad credentials", "status": "401"}):
        with pytest.raises(ci.Unanswered):
            ci.has_write_access(unexpected, "octocat")


# --- approvals that stand ----------------------------------------------------------------------------


def test_an_approval_stands_for_the_commit_it_was_given_for(ci):
    author, head, reviews = pull(16)
    assert [review["state"] for review in reviews] == ["APPROVED"] and reviews[0]["commit_id"] == head
    assert ci.approving_accounts(reviews, head) == ["jeremymanning"]
    assert ci.approving_accounts(reviews, pull(14)[1]) == []            # another commit: the approval is not of it
    assert ci.approving_accounts(reviews, "") == []


def test_an_approval_after_a_request_for_changes_stands_and_one_of_an_older_head_does_not(ci):
    author, head, reviews = pull(14)
    states = [(review["user"]["login"], review["state"]) for review in reviews]
    assert states[0] == ("jeremymanning", "CHANGES_REQUESTED") and states[-1] == ("jeremymanning", "APPROVED")
    assert ci.approving_accounts(reviews, head) == ["jeremymanning"]
    older = reviews[0]["commit_id"]
    assert older != head
    assert ci.approving_accounts(reviews, older) == []                 # the head the approval was not given for
    assert ci.approving_accounts(reviews[:-1], older) == []            # before the approval: changes requested


def test_requests_for_changes_comments_and_no_reviews_approve_nothing(ci):
    for number in (51, 54, 107):
        author, head, reviews = pull(number)
        assert ci.approving_accounts(reviews, head) == [], number


def test_a_dismissed_approval_and_one_followed_by_a_request_for_changes_do_not_stand(ci):
    """Constructed from the recorded approval of pull request 16 (see the fixture's README)."""
    author, head, reviews = pull(16)
    dismissed = [dict(reviews[0], state="DISMISSED")]
    assert ci.approving_accounts(dismissed, head) == []
    later = dict(copy.deepcopy(reviews[0]), id=reviews[0]["id"] + 1, state="CHANGES_REQUESTED",
                 submitted_at="2019-02-09T01:37:28Z")
    assert ci.approving_accounts(reviews + [later], head) == []
    assert ci.approving_accounts([later] + reviews, head) == ["jeremymanning"]      # the approval is the later one
    # A comment decides nothing, and another account's request cancels only its own approval.
    comment = dict(later, state="COMMENTED")
    assert ci.approving_accounts(reviews + [comment], head) == ["jeremymanning"]
    someone = dict(later, user=recorded("permission-paxtonfitzpatrick.json")["user"])
    assert ci.approving_accounts(reviews + [someone], head) == ["jeremymanning"]
    assert ci.approving_accounts(reviews + [dict(later, user=None)], head) == ["jeremymanning"]   # a deleted account


def test_an_answer_that_is_not_a_list_of_reviews_is_no_answer(ci):
    author, head, reviews = pull(16)
    for unexpected in ({"message": "Not Found"}, None, [["APPROVED"]], [{"state": "APPROVED"}],
                       [dict(reviews[0], user={"id": 1})], [dict(reviews[0], state=None)]):
        with pytest.raises(ci.Unanswered):
            ci.approving_accounts(unexpected, head)


# --- who vouches ---------------------------------------------------------------------------------------


def test_a_reviewer_with_write_access_who_approved_the_head_vouches(ci):
    author, head, reviews = pull(16)
    assert author == "amartinez2020"
    assert ci.vouchers(author, head, reviews, permissions("jeremymanning")) == (None, ["jeremymanning"])
    assert ci.vouchers(author, head, reviews, {}) == (None, [])                     # nothing known of the approver
    assert ci.vouchers(author, pull(14)[1], reviews, permissions("jeremymanning")) == (None, [])   # an older approval
    # The approver without write access (constructed: the approval under another recorded account).
    theirs = [dict(reviews[0], user=recorded("permission-paxtonfitzpatrick.json")["user"])]
    assert ci.vouchers(author, head, theirs, permissions("paxtonfitzpatrick", "jeremymanning")) == (None, [])


def test_an_author_with_write_access_vouches_and_one_without_does_not(ci):
    author, head, reviews = pull(107)
    assert author == "jeremymanning" and reviews == []
    assert ci.vouchers(author, head, reviews, permissions("jeremymanning")) == ("jeremymanning", [])
    assert ci.vouchers("octocat", head, reviews, permissions("octocat", "jeremymanning")) == (None, [])
    assert ci.vouchers("paxtonfitzpatrick", *pull(54)[1:], permissions("paxtonfitzpatrick")) == (None, [])
    # The answer about the maintainer is not an answer about the author.
    assert ci.vouchers("octocat", head, reviews, {"octocat": recorded("permission-jeremymanning.json")}) == (None, [])


def row(login, key="Rame72"):
    review = {"reviewer": "@" + login, "source": "https://doi.org/10.1016/S0146-664X(72)80017-0",
              "note": "Compared every field with the article.", "github_login": login, "github_id": 1}
    return {"key": key, "fingerprint": "v2:" + "0" * 64, "human_review": review,
            "approval_digest": v.approval_digest(review), "approved_at": v.now(), "policy": v.POLICY}


def test_which_added_rows_count(ci):
    mine, theirs = row("jeremymanning"), row("octocat", "Schr00b")
    assert ci.rows_that_count([mine, theirs], None, []) == []
    assert ci.rows_that_count([mine, theirs], "jeremymanning", []) == [mine]      # rule 1: the author's own rows
    assert ci.rows_that_count([mine, theirs], "JeremyManning", []) == [mine]
    assert ci.rows_that_count([mine, theirs], None, ["jeremymanning"]) == [mine, theirs]   # rule 2: all of them
    assert ci.rows_that_count([mine, theirs], "jeremymanning", ["someone"]) == [mine, theirs]


def test_typing_a_maintainers_login_into_a_row_gains_nothing(ci):
    """The pull request of an account without write access adds a row that names a maintainer
    as its reviewer. Who vouches is the author GitHub names and the reviews GitHub lists: the
    author has no write access and nobody approved, so the row does not count."""
    typed = row("jeremymanning")
    head, reviews = pull(107)[1], []
    author, reviewers = ci.vouchers("octocat", head, reviews, permissions("octocat", "jeremymanning"))
    assert (author, reviewers) == (None, [])
    assert ci.rows_that_count([typed], author, reviewers) == []


def test_the_rows_a_pull_request_adds_are_the_lines_its_ledger_has_beyond_the_base(ci):
    held, mine, theirs = (v.dumps(row(login)).encode("utf-8") for login in ("hubot", "jeremymanning", "octocat"))
    base = held + b"\n"
    assert ci.added_rows(base, base) == []
    assert ci.added_rows(b"", b"") == []
    added = ci.added_rows(base, base + mine + b"\n" + theirs + b"\n")
    assert [line for line, _ in added] == [mine, theirs]
    assert [parsed["human_review"]["github_login"] for _, parsed in added] == ["jeremymanning", "octocat"]
    assert [line for line, _ in ci.added_rows(base, base + held + b"\n")] == [held]     # the same line a second time


@pytest.mark.parametrize("missing", ["GITHUB_TOKEN", "PR_AUTHOR", "PR_NUMBER", "PR_HEAD_SHA", "PR_REPOSITORY", "an ill-formed head"])
def test_without_a_fact_or_the_token_nobody_vouches_and_one_line_says_so(ci, capsys, missing):
    """Fail closed: the base's ledger alone is read (None), GitHub is not asked, and the line
    printed names what is missing and never the token."""
    author, head, _ = pull(107)
    environ = {"PR_AUTHOR": author, "PR_NUMBER": "107", "PR_HEAD_SHA": head, "PR_REPOSITORY": REPOSITORY,
               "GITHUB_TOKEN": "not-a-token-0123456789"}
    if missing == "an ill-formed head":
        environ["PR_HEAD_SHA"] = "HEAD"
    else:
        del environ[missing]
    mine = v.dumps(row("jeremymanning")).encode("utf-8") + b"\n"

    def never(path, token):
        raise AssertionError("GitHub was asked")
    assert ci.vouched_ledger(b"", mine, environ, ask=never) is None
    said = capsys.readouterr().out
    assert said.count("\n") == 1 and said.startswith("The 1 approval this pull request adds: not counted, since who "
                                                     "vouches for them could not be learned from GitHub (")
    assert ("no GITHUB_TOKEN was given" in said) == (missing == "GITHUB_TOKEN")
    assert "not-a-token" not in said
    # With nothing added there is nothing to vouch for, and nothing is said or asked.
    assert ci.vouched_ledger(mine, mine, environ, ask=never) is None and capsys.readouterr().out == ""


def test_a_token_github_refuses_fails_closed_without_showing_it(ci, capsys):
    """Asked for real with a token that is none: GitHub answers 401, nobody vouches."""
    author, head, _ = pull(107)
    token = "ghp_notatoken0123456789notatoken0123456789"
    environ = {"PR_AUTHOR": author, "PR_NUMBER": "107", "PR_HEAD_SHA": head, "PR_REPOSITORY": REPOSITORY,
               "GITHUB_TOKEN": token}
    mine = v.dumps(row("jeremymanning")).encode("utf-8") + b"\n"
    try:
        answer = ci.vouched_ledger(b"", mine, environ)
    except Exception as exc:  # pragma: no cover - the decision never raises for an unreachable GitHub
        raise AssertionError(f"raised instead of failing closed: {exc!r}")
    said = capsys.readouterr().out
    assert answer is None and "not counted" in said and token not in said
    if "HTTP 401" not in said:
        pytest.skip(f"api.github.com could not be reached from here: {said.strip()}")


def github_token():
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    if shutil.which("gh"):
        found = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    return None


def test_github_itself_answers_as_recorded_and_the_rule_is_decided_from_its_answers(ci, capsys):
    """Live: the permission endpoint and the reviews endpoint of api.github.com, asked as the
    check asks them, for two closed pull requests of this repository whose facts do not change:
    107 (written by an account with admin permission, never reviewed) and 16 (written by
    another account, approved at its head commit by the admin)."""
    token = github_token()
    if not token:
        pytest.skip("no GitHub token (GITHUB_TOKEN, GH_TOKEN or `gh auth login`)")
    try:
        answer = ci.ask_github(f"/repos/{REPOSITORY}/collaborators/jeremymanning/permission", token)
    except ci.Unanswered as exc:
        pytest.skip(f"api.github.com did not answer: {exc}")
    kept = recorded("permission-jeremymanning.json")
    assert answer["permission"] == kept["permission"] == "admin" and answer["user"]["login"] == "jeremymanning"
    assert set(kept) <= set(answer)                                        # the recorded form is still the form
    assert ci.has_write_access(answer, "jeremymanning")
    assert not ci.has_write_access(ci.ask_github(f"/repos/{REPOSITORY}/collaborators/octocat/permission", token), "octocat")

    def environ(number):
        author, head, _ = pull(number)
        return {"PR_AUTHOR": author, "PR_NUMBER": str(number), "PR_HEAD_SHA": head, "PR_REPOSITORY": REPOSITORY,
                "GITHUB_TOKEN": token}
    assert ci.ask_vouchers(environ(107)) == ("jeremymanning", [])          # rule 1
    assert ci.ask_vouchers(environ(16)) == (None, ["jeremymanning"])       # rule 2
    assert ci.ask_vouchers(dict(environ(16), PR_HEAD_SHA=pull(14)[1])) == (None, [])
    assert ci.ask_vouchers(environ(51)) == (None, [])
    # And the ledger the check would read for pull request 16, were these its rows.
    base = v.dumps(row("hubot")).encode("utf-8") + b"\n"
    mine, theirs = (v.dumps(row(login)).encode("utf-8") + b"\n" for login in ("jeremymanning", "octocat"))
    assert ci.vouched_ledger(base, base + mine + theirs, environ(16)) == base + mine + theirs
    assert "counted, on the approval of this head commit by @jeremymanning (write access)" in capsys.readouterr().out
    assert ci.vouched_ledger(base, base + mine + theirs, environ(107)) == base + mine
    assert "1 counted, recorded by the author @jeremymanning (write access); the others" in capsys.readouterr().out
    assert ci.vouched_ledger(base, base + mine + theirs, environ(51)) is None
    said = capsys.readouterr().out
    assert "not counted. Nobody with write access vouches for them" in said and token not in said


# --- the lines a pull request's check ends with ---------------------------------------------------------


def approval(ws, key, login="octocat"):
    entry = v.load_entries(str(ws.bib))[key]
    review = {"reviewer": "@" + login, "source": "https://doi.org/10.1016/S0146-664X(72)80017-0",
              "note": "Compared every field with the article.", "github_login": login, "github_id": 583231}
    made = {"key": key, "fingerprint": entry["fingerprint"], "human_review": review,
            "approval_digest": v.approval_digest(review), "approved_at": v.now(), "policy": v.POLICY}
    assert v.valid_shared_approval(made)
    return v.dumps(made) + "\n"


def summary(ws, base, database, *more):
    return CliRunner().invoke(app, ["check-summary", str(ws.bib), "--against", str(base), "--database", str(database), *more])


def test_the_summary_says_what_became_of_each_new_or_edited_entry(tmp_path):
    """A base of two entries; the change adds two entries that are verified (their saved
    results, restored), edits one into a text nobody verified, and edits another into a text
    that only an approval row of the change itself covers."""
    ws = library(tmp_path / "library", KEYS)
    base = tmp_path / "base.bib"
    every = texts()
    base.write_text(every["NguyEtal19"] + "\n\n" + every["Schr00b"] + "\n\n" + every["Rame72"] + "\n", encoding="utf-8")
    text = ws.bib.read_text(encoding="utf-8")
    ws.bib.write_text(text.replace("Volume = {1},", "Volume = {2},").replace("Volume = {92},", "Volume = {93},"),
                      encoding="utf-8")                                 # Rame72 and Schr00b edited
    database = tmp_path / "db.sqlite3"
    assert CliRunner().invoke(app, ["restore", str(RESULTS), "--fname", str(ws.bib), "--database", str(database)]).exit_code == 0
    assert statuses(ws, database) == {"AntoEtal24": "metadata_verified", "NguyEtal19": "metadata_verified",
                                      "Rame72": "pending", "Schr00b": "pending", "YeshEtal21": "metadata_verified"}
    empty, proposed = tmp_path / "base-approvals.jsonl", tmp_path / "proposed-approvals.jsonl"
    empty.write_text("", encoding="utf-8")
    proposed.write_text(approval(ws, "Rame72"), encoding="utf-8")
    done = summary(ws, base, database, "--trusted-approvals", str(empty), "--proposed-approvals", str(proposed))
    assert done.exit_code == 1, done.output
    assert done.output.splitlines() == [
        "2 entries verified against their sources: AntoEtal24, YeshEtal21",
        "1 entry needing a maintainer's approval (approve this pull request on GitHub, or record the approval "
        "as a maintainer): Rame72",
        "1 entry not verified: Schr00b (New, edited, or policy-invalidated entry)"]
    # Without the change's own ledger nothing is known to wait for an approval.
    done = summary(ws, base, database, "--trusted-approvals", str(empty))
    assert done.exit_code == 1 and "2 entries not verified: Rame72 (" in done.output and "needing" not in done.output
    # The row counts (someone vouched: it is in the ledger that is trusted): approved, by its reviewer.
    done = summary(ws, base, database, "--trusted-approvals", str(proposed), "--proposed-approvals", str(proposed))
    assert done.exit_code == 1
    assert done.output.splitlines() == [
        "2 entries verified against their sources: AntoEtal24, YeshEtal21",
        "1 entry approved by a person's review (@octocat): Rame72",
        "1 entry not verified: Schr00b (New, edited, or policy-invalidated entry)"]
    # A row for another text of the entry proposes nothing: the entry is simply not verified.
    stale = tmp_path / "stale.jsonl"
    stale.write_text(approval(ws, "Rame72").replace(v.load_entries(str(ws.bib))["Rame72"]["fingerprint"],
                                                    v.load_entries(str(base))["Rame72"]["fingerprint"]), encoding="utf-8")
    done = summary(ws, base, database, "--trusted-approvals", str(empty), "--proposed-approvals", str(stale))
    assert done.exit_code == 1 and "needing" not in done.output and "2 entries not verified" in done.output
    # Everything settled: exit 0.
    both = tmp_path / "both.jsonl"
    both.write_text(approval(ws, "Rame72") + approval(ws, "Schr00b", "hubot"), encoding="utf-8")
    done = summary(ws, base, database, "--trusted-approvals", str(both), "--proposed-approvals", str(both))
    assert done.exit_code == 0, done.output
    assert done.output.splitlines() == [
        "2 entries verified against their sources: AntoEtal24, YeshEtal21",
        "1 entry approved by a person's review (@hubot): Schr00b",
        "1 entry approved by a person's review (@octocat): Rame72"]


def test_the_summary_of_a_change_that_touches_no_entry(tmp_path):
    ws = library(tmp_path / "library", KEYS)
    database = tmp_path / "db.sqlite3"
    done = summary(ws, ws.bib.parent / "cdl.bib", database)
    assert done.exit_code == 0 and done.output == "No entry is new or edited: nothing to verify.\n"


def test_a_revoked_proposal_does_not_wait_for_approval(tmp_path):
    """A row of the change's own ledger whose approval was revoked proposes nothing."""
    ws = library(tmp_path / "library", ["NguyEtal19", "Rame72"])
    base = tmp_path / "base.bib"
    base.write_text(texts()["NguyEtal19"] + "\n", encoding="utf-8")
    database = tmp_path / "db.sqlite3"
    line = approval(ws, "Rame72")
    made = json.loads(line)
    proposed, empty = tmp_path / "proposed.jsonl", tmp_path / "empty.jsonl"
    proposed.write_text(line, encoding="utf-8")
    empty.write_text("", encoding="utf-8")
    done = summary(ws, base, database, "--trusted-approvals", str(empty), "--proposed-approvals", str(proposed))
    assert done.exit_code == 1 and "1 entry needing a maintainer's approval" in done.output
    revocation = {"key": "Rame72", "fingerprint": made["fingerprint"], "approval": made["human_review"],
                  "approval_digest": made["approval_digest"], "approval_checked_at": made["approved_at"],
                  "revoked_at": v.now(), "revoked_by": "@hubot", "reason": "Recorded in error."}
    assert v.valid_revocation(revocation)
    revocations = tmp_path / "base-revocations.jsonl"
    revocations.write_text(v.dumps(revocation) + "\n", encoding="utf-8")
    done = summary(ws, base, database, "--trusted-approvals", str(empty), "--proposed-approvals", str(proposed),
                   "--trusted-revocations", str(revocations))
    assert done.exit_code == 1 and "needing" not in done.output and "1 entry not verified: Rame72" in done.output
