"""The approvals ledger (verification/approvals.jsonl): human approvals that travel with a send.

Real files, real SQLite databases and real git repositories in temporary folders; the real
gh where a login is needed (those tests skip, with the reason, where nobody is logged in or
the user has no fork). An approval "of another user" is one stored in a second database. No
mocks.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from cdlbib import api, publish
from cdlbib import verification as v
from cdlbib.errors import GateFailed, IdentityUnavailable, PublishRefused
from cdlbib.workspace import Workspace

from test_machinery_2026_09_25 import RAME72, ZOLL90
from test_publish import GIT_ENV, NOWHERE, TEST_BASE, clean_up, git, my_fork, open_prs, state

FIX = Path(__file__).resolve().parent / "fixtures" / "revocation"
LEDGER = "verification/approvals.jsonl"
REVIEW = {"reviewer": "@octocat", "source": "https://doi.org/10.1002/tea.3660271011",
          "note": "Compared every field with the printed article.", "github_login": "octocat", "github_id": 583231}
BAD = "@article{Bad,\n\tPages = {10--1}}\n"


@pytest.fixture(autouse=True)
def _the_librarys_own_ledgers(monkeypatch):
    # No patched ledger and none named by the environment: each library reads the ledgers in
    # its own verification/ folder, as it does outside the tests.
    monkeypatch.setattr(v, "REVOCATION_LEDGER", None)
    monkeypatch.setattr(api, "_identity", None)        # no test inherits who another test's gh call named
    monkeypatch.setenv("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")


def library(folder, text=ZOLL90 + "\n\n" + RAME72 % "1" + "\n"):
    folder.mkdir(parents=True)
    (folder / "verification").mkdir()
    (folder / "cdl.bib").write_text(text, encoding="utf-8")
    return Workspace(folder)


def fingerprint(ws, key):
    return v.load_entries(str(ws.bib))[key]["fingerprint"]


def approve(ws, key, database=None, **review):
    """A human approval stored as `approve` stores it, under the login in REVIEW."""
    cache = v.Cache(str(database or ws.database), ledger=ws.revocations)
    try:
        v.record_approval(cache, str(ws.bib), key, fingerprint(ws, key), dict(REVIEW, **review))
    finally:
        cache.close()


def results(ws, database):
    cache = v.Cache(str(database), ledger=ws.revocations)
    try:
        return v.current_results(str(ws.bib), cache)
    finally:
        cache.close()


def statuses(ws, database):
    return {key: result["status"] for key, result in results(ws, database).items()}


def share(ws, database=None):
    """What a send does with the approvals: the rows not yet in the ledger are appended."""
    rows = api.approvals_to_send(ws, database=database)
    v.append_approvals(ws.approvals, rows)
    return rows


def rows_of(ws):
    return [json.loads(line) for line in ws.approvals.read_text(encoding="utf-8").splitlines()]


# --- the ledger: written, read, validated ---------------------------------------------------------

def test_an_approval_under_a_login_becomes_one_ledger_row_and_approves_in_an_empty_database(tmp_path):
    ws = library(tmp_path / "lib")
    assert api.approvals_to_send(ws) == [] and not ws.work.exists()         # no database: nothing waits, nothing is made
    approve(ws, "Zoll90")
    stored = results(ws, ws.database)["Zoll90"]
    waiting = api.approvals_to_send(ws)
    assert not ws.approvals.exists()                                         # asking writes nothing
    assert waiting == [{"key": "Zoll90", "fingerprint": fingerprint(ws, "Zoll90"), "human_review": REVIEW,
                        "approval_digest": v.approval_digest(REVIEW), "approved_at": stored["checked_at"],
                        "policy": v.POLICY}]
    assert share(ws) == waiting
    line = ws.approvals.read_bytes()
    assert line == (v.dumps(waiting[0]) + "\n").encode("utf-8")              # one line, sorted keys, no spaces
    assert api.approvals_to_send(ws) == [] and share(ws) == [] and ws.approvals.read_bytes() == line   # never twice

    # Someone else's database, which never saw the approval: the ledger alone approves the entry.
    other = tmp_path / "other.sqlite3"
    found = results(ws, other)
    assert found["Zoll90"]["status"] == "human_verified" and found["Rame72"]["status"] == "pending"
    assert found["Zoll90"]["human_review"] == REVIEW and found["Zoll90"]["checked_at"] == stored["checked_at"]
    assert found["Zoll90"]["fingerprint"] == fingerprint(ws, "Zoll90")
    assert api.approvals_to_send(ws, database=other) == []                   # a ledger row is not an approval to send
    cache = v.Cache(str(other), ledger=ws.revocations)
    try:                                                                     # and nothing was stored for it
        assert cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0
    finally:
        cache.close()
    assert api.status(ws, database=str(other), report=str(tmp_path / "report.jsonl"), keys=None).counts == {
        "human_verified": 1, "pending": 1}
    # A snapshot written from that database carries the approval, as any current result.
    cache = v.Cache(str(other), ledger=ws.revocations)
    try:
        exported = v.export_snapshot(str(ws.bib), cache, str(tmp_path / "snapshot.jsonl.gz"))
    finally:
        cache.close()
    assert exported["Zoll90"]["status"] == "human_verified" and exported["Zoll90"]["human_review"] == REVIEW


def test_rows_are_appended_and_earlier_lines_are_never_rewritten(tmp_path):
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    share(ws)
    first = ws.approvals.read_bytes()
    approve(ws, "Rame72", source="https://doi.org/10.1016/S0146-664X(72)80017-0", note="Checked the volume in print.")
    added = share(ws)
    assert [row["key"] for row in added] == ["Rame72"]
    now = ws.approvals.read_bytes()
    assert now.startswith(first) and now[len(first):] == (v.dumps(added[0]) + "\n").encode("utf-8")
    assert statuses(ws, tmp_path / "other.sqlite3") == {"Zoll90": "human_verified", "Rame72": "human_verified"}
    # A ledger whose last line lost its newline (an editor) still gets whole lines.
    ws.approvals.write_bytes(first.rstrip(b"\n"))
    assert [row["key"] for row in share(ws)] == ["Rame72"]
    assert ws.approvals.read_bytes() == now


def test_an_approval_without_a_github_login_is_never_ledgered(tmp_path):
    """The three approvals of the frozen 7f3eead baseline carry a reviewer's name and no login."""
    ws = library(tmp_path / "lib", (FIX / "entries-7f3eead.bib").read_text(encoding="utf-8"))
    cache = v.Cache(str(ws.database), ledger=ws.revocations)
    try:
        assert v.import_snapshot(str(ws.bib), cache, str(FIX / "baseline-7f3eead-3-approvals.jsonl.gz")) == 3
    finally:
        cache.close()
    assert set(statuses(ws, ws.database).values()) == {"human_verified"}
    assert api.approvals_to_send(ws) == []
    approve(ws, "NastEtal20", note="Read again, under my own login.")       # a new approval of one of them, under a login
    assert [row["key"] for row in api.approvals_to_send(ws)] == ["NastEtal20"]


def test_a_row_approves_only_the_exact_text_it_was_made_for(tmp_path):
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    share(ws)
    other = tmp_path / "other.sqlite3"
    assert statuses(ws, other)["Zoll90"] == "human_verified"
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8").replace("Volume = {27}", "Volume = {28}"), encoding="utf-8")
    assert statuses(ws, other) == {"Zoll90": "pending", "Rame72": "pending"}
    assert statuses(ws, ws.database)["Zoll90"] == "pending" and api.approvals_to_send(ws) == []   # the approver's too


def test_a_row_under_another_policy_approves_nothing(tmp_path):
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    row = share(ws)[0]
    ws.approvals.write_text(v.dumps(dict(row, policy=v.POLICY + "-earlier")) + "\n", encoding="utf-8")
    assert statuses(ws, tmp_path / "other.sqlite3")["Zoll90"] == "pending"


def retyped(row, **review):
    """``row`` with its human_review changed and the digest computed again, as someone typing
    a row would write it."""
    changed = dict(row["human_review"], **review)
    return dict(row, human_review=changed, approval_digest=v.approval_digest(changed))


BAD_ROWS = {
    "a blank note": lambda row: retyped(row, note="  "),
    "no source": lambda row: retyped(row, source=""),
    "no reviewer": lambda row: retyped(row, reviewer=""),
    "no GitHub login": lambda row: dict(
        row, human_review={k: x for k, x in row["human_review"].items() if k != "github_login"},
        approval_digest=v.approval_digest({k: x for k, x in row["human_review"].items() if k != "github_login"})),
    "a login GitHub could not have issued": lambda row: retyped(row, github_login="octo cat/../x"),
    "a note that is not text": lambda row: retyped(row, note=["checked"]),
    "a github_id that is not a number": lambda row: retyped(row, github_id="583231"),
    "an unknown field in the review": lambda row: retyped(row, verified_by_machine=True),
    "a note longer than the limit": lambda row: retyped(row, note="x" * 8001),
    "a digest that is not the review's": lambda row: dict(row, human_review=dict(row["human_review"], note="Another note.")),
    "a digest of the wrong shape": lambda row: dict(row, approval_digest="abc"),
    "no time": lambda row: {k: x for k, x in row.items() if k != "approved_at"},
    "a time that is none": lambda row: dict(row, approved_at="yesterday"),
    "a date without a time": lambda row: dict(row, approved_at="2026-10-05"),
    "a time without a zone": lambda row: dict(row, approved_at="2026-10-05T12:00:00"),
    "no fingerprint": lambda row: dict(row, fingerprint=""),
    "a fingerprint of another format": lambda row: dict(row, fingerprint="0" * 64),
    "an unknown field in the row": lambda row: dict(row, status="human_verified"),
    "a policy that is not text": lambda row: dict(row, policy=2),
    "not an object": lambda row: "not a row",
    "a list": lambda row: [row],
}


@pytest.mark.parametrize("what", sorted(BAD_ROWS))
def test_an_invalid_row_is_ignored_and_reported_and_the_rows_beside_it_still_count(tmp_path, what):
    """Three lines: a valid row for Rame72, the invalid row (for Zoll90), a valid row for
    Rame72 again. Nothing raises; Zoll90 is not approved; Rame72 is; the problem names line 2."""
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    approve(ws, "Rame72", note="Checked the volume in print.")
    zoll, rame = share(ws)
    changed = BAD_ROWS[what](zoll)
    assert v.shared_approval_problem(changed) and not v.valid_shared_approval(changed)
    ws.approvals.write_text("".join(v.dumps(row) + "\n" for row in (rame, changed, rame)), encoding="utf-8")
    other = tmp_path / "other.sqlite3"
    assert statuses(ws, other) == {"Zoll90": "pending", "Rame72": "human_verified"}
    rows, problems = v.scan_approval_ledger(ws.approvals)
    assert rows == [rame, rame] and len(problems) == 1
    assert problems[0].startswith(f"{ws.approvals}: line 2 ignored: ")
    assert api.approval_problems(ws) == problems
    with pytest.raises(ValueError, match="Invalid approval record"):         # and such a row is never written
        v.append_approvals(tmp_path / "elsewhere.jsonl", [changed])
    assert not (tmp_path / "elsewhere.jsonl").exists()


def test_lines_that_are_not_rows_at_all_are_ignored_and_reported(tmp_path):
    """What a merge conflict leaves, a field named twice, bytes that are not UTF-8, a line
    longer than the limit, deeply nested JSON: each is reported with its line number, none
    approves anything and none stops the rows around it from being read."""
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    approve(ws, "Rame72", note="Checked the volume in print.")
    zoll, rame = share(ws)
    good = (v.dumps(rame) + "\n").encode("utf-8")
    twice = v.dumps(zoll)[:-1] + ',"fingerprint":"' + zoll["fingerprint"] + '"}'      # the field appears twice
    assert json.loads(twice) == zoll                                         # a plain reader would take it
    huge = v.dumps(retyped(zoll, source="x" * 3999, note="y" * 7999))
    padded = v.dumps(zoll)[:-1] + "," + " " * v.APPROVAL_ROW_MAX_BYTES + '"x":1}'
    ws.approvals.write_bytes(b"<<<<<<< HEAD\n" + good + twice.encode() + b"\n" + b"\xff\xfe{}\n" + padded.encode() + b"\n"
                             + b"[" * 100000 + b"\n" + huge.encode() + b"\n" + good)
    rows, problems = v.scan_approval_ledger(ws.approvals)
    assert [row["key"] for row in rows] == ["Rame72", "Zoll90", "Rame72"]    # the long but valid row counts
    assert [problem.split(": ", 1)[1].split(": ")[0] for problem in problems] == [
        "line 1 ignored", "line 3 ignored", "line 4 ignored", "line 5 ignored", "line 6 ignored"]
    assert "appears twice" in problems[1] and "longer than" in problems[3]
    assert statuses(ws, tmp_path / "other.sqlite3") == {"Zoll90": "human_verified", "Rame72": "human_verified"}
    ws.approvals.write_bytes(b"<<<<<<< HEAD\n" + twice.encode() + b"\n")
    assert statuses(ws, tmp_path / "other.sqlite3")["Zoll90"] == "pending"   # the twice-named row alone approves nothing


def test_a_ledger_larger_than_the_limit_is_ignored_whole_and_reported(tmp_path):
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    row = share(ws)[0]
    line = (v.dumps(row) + "\n").encode("utf-8")
    ws.approvals.write_bytes(line * (v.APPROVAL_LEDGER_MAX_BYTES // len(line) + 1))
    rows, problems = v.scan_approval_ledger(ws.approvals)
    assert rows == [] and problems == [f"{ws.approvals}: ignored whole: larger than {v.APPROVAL_LEDGER_MAX_BYTES} bytes"]
    assert statuses(ws, tmp_path / "other.sqlite3")["Zoll90"] == "pending"


def test_problems_in_the_ledger_are_shown_by_status_and_by_the_state_of_the_library(checkout):
    from typer.testing import CliRunner
    from cdlbib.verification_cli import app
    ws, _ = checkout
    ws.approvals.write_text("not a row\n", encoding="utf-8")
    problem = f"{ws.approvals}: line 1 ignored: not valid JSON"
    found = api.library_state(ws)
    assert [note for note in found.notes if note.startswith(problem)] and found.approvals == []
    run = CliRunner().invoke(app, ["status", str(ws.bib), "--database", str(ws.database),
                                                   "--report", str(ws.work / "report.jsonl")])
    assert run.exit_code == 1 and run.stdout.strip() == "2 entries: pending=2"      # counted, not crashed
    assert run.stderr.startswith(problem)



def test_restore_still_stores_the_snapshots_result_beside_a_ledger_row(tmp_path):
    """A ledger row is read, never stored: restoring the baseline into a database that sees
    the row stores the baseline's result (its evidence) for the same text."""
    ws = library(tmp_path / "lib", (FIX / "entries-7f3eead.bib").read_text(encoding="utf-8"))
    approve(ws, "NastEtal20", database=tmp_path / "approver.sqlite3")
    share(ws, database=tmp_path / "approver.sqlite3")
    cache = v.Cache(str(tmp_path / "other.sqlite3"), ledger=ws.revocations)
    try:
        entry = v.load_entries(str(ws.bib))["NastEtal20"]
        assert cache.stored(str(ws.bib), entry) is None and cache.get(str(ws.bib), entry)["status"] == "human_verified"
        assert v.import_snapshot(str(ws.bib), cache, str(FIX / "baseline-7f3eead-3-approvals.jsonl.gz")) == 3
        assert cache.stored(str(ws.bib), entry)["human_review"]["reviewer"] == "Jeremy Manning"
    finally:
        cache.close()


def test_a_cache_reads_the_ledger_it_is_given_and_no_environment_variable_names_one(tmp_path, monkeypatch):
    """A cache can be given the ledger to read (what `crossref verify --trusted-approvals`
    does with the base revision's copy). The environment names none: CDLBIB_APPROVAL_LEDGER,
    which an earlier version read, changes nothing."""
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    share(ws)
    base = tmp_path / "base-approvals.jsonl"
    base.write_bytes(b"")

    def status(approvals):
        cache = v.Cache(str(tmp_path / "other.sqlite3"), ledger=ws.revocations, approvals=approvals)
        try:
            return v.current_results(str(ws.bib), cache)["Zoll90"]["status"]
        finally:
            cache.close()
    assert status(None) == "human_verified"                                  # the library's own
    assert status(str(base)) == "pending" and status(False) == "pending"     # the one it is given; none at all
    base.write_bytes(ws.approvals.read_bytes())
    assert status(str(base)) == "human_verified"
    ws.approvals.unlink()
    monkeypatch.setenv("CDLBIB_APPROVAL_LEDGER", str(base))
    assert status(None) == "pending" and statuses(ws, tmp_path / "other.sqlite3")["Zoll90"] == "pending"


# --- revocation beats the approvals ledger --------------------------------------------------------

def revoke(ws, key, database):
    cache = v.Cache(str(database), ledger=ws.revocations)
    try:
        return v.record_revocation(cache, str(ws.bib), key, "Recorded in error.", "@hubot", ledger=ws.revocations)
    finally:
        cache.close()


def test_a_revocation_by_the_approver_wins_over_the_ledger_row_everywhere(tmp_path):
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    approve(ws, "Rame72", note="Checked the volume in print.")               # the negative control: never revoked
    share(ws)
    ledger = ws.approvals.read_bytes()
    records, status = revoke(ws, "Zoll90", ws.database)
    assert len(records) == 1 and status == "needs_review"
    assert ws.approvals.read_bytes() == ledger                               # the approvals ledger is not rewritten
    for database in (ws.database, tmp_path / "other.sqlite3"):               # the approver's, and an empty one
        found = results(ws, database)
        assert found["Zoll90"]["status"] != "human_verified" and found["Rame72"]["status"] == "human_verified"
    assert api.approvals_to_send(ws) == []                                   # a revoked approval is not sent again


def test_someone_who_only_has_the_ledger_row_can_revoke_it(tmp_path):
    ws = library(tmp_path / "lib")
    approver, other = tmp_path / "approver.sqlite3", tmp_path / "other.sqlite3"
    approve(ws, "Zoll90", database=approver)
    row = share(ws, database=approver)[0]
    assert statuses(ws, other)["Zoll90"] == "human_verified"
    records, status = revoke(ws, "Zoll90", other)                            # this database never stored the approval
    assert status == "needs_review" and len(records) == 1
    assert (records[0]["fingerprint"], records[0]["approval_digest"], records[0]["approval"],
            records[0]["approval_checked_at"]) == (row["fingerprint"], row["approval_digest"], REVIEW, row["approved_at"])
    assert json.loads(ws.revocations.read_text(encoding="utf-8")) == records[0]
    for database in (other, approver, tmp_path / "third.sqlite3"):           # the revocation ledger beats the approvals ledger
        assert statuses(ws, database)["Zoll90"] != "human_verified", database
    assert revoke(ws, "Zoll90", other) == ([], "needs_review")               # already revoked: nothing more is written

    # A new approval with a new note, made after the revocation, is a new decision; its row counts.
    with pytest.raises(ValueError, match="This exact approval was revoked"):
        approve(ws, "Zoll90", database=approver)
    approve(ws, "Zoll90", database=approver, note="Checked again against the publisher's page.")
    assert [r["human_review"]["note"] for r in share(ws, database=approver)] == ["Checked again against the publisher's page."]
    assert len(rows_of(ws)) == 2
    found = results(ws, tmp_path / "third.sqlite3")["Zoll90"]
    assert found["status"] == "human_verified" and found["human_review"]["note"].startswith("Checked again")


def test_a_row_dated_before_a_revocation_of_its_text_is_revoked_whatever_its_note(tmp_path):
    """The revocation rule that is not about the digest: an approval of the same text stored
    no later than the revocation is revoked too."""
    ws = library(tmp_path / "lib")
    approver = tmp_path / "approver.sqlite3"
    approve(ws, "Zoll90", database=approver)
    row = share(ws, database=approver)[0]
    revoke(ws, "Zoll90", approver)
    earlier = dict(REVIEW, note="The same check, worded differently.")
    forged = dict(row, human_review=earlier, approval_digest=v.approval_digest(earlier))
    assert v.valid_shared_approval(forged)
    with open(ws.approvals, "a", encoding="utf-8") as stream:
        stream.write(v.dumps(forged) + "\n")
    assert statuses(ws, tmp_path / "other.sqlite3")["Zoll90"] != "human_verified"


FORGERIES = {
    "the note with other spacing and case": lambda row, later: dict(
        retyped(row, note="  compared   EVERY field with the printed article. "), approved_at=later),
    "the same review at a later time": lambda row, later: dict(row, approved_at=later),
    "the same review under another login": lambda row, later: dict(
        retyped(row, reviewer="@hubot", github_login="hubot", github_id=480938), approved_at=later),
    "the same review with another id": lambda row, later: dict(retyped(row, github_id=1), approved_at=later),
    "the source with other spacing": lambda row, later: dict(
        retyped(row, source=row["human_review"]["source"] + " "), approved_at=later),
    "a new note dated before the revocation": lambda row, later: retyped(row, note="An entirely new check."),
}


@pytest.mark.parametrize("what", sorted(FORGERIES))
def test_a_typed_row_cannot_bring_a_revoked_approval_back(tmp_path, what):
    """An approval is ledgered, then revoked. A row typed afterwards that repeats the revoked
    review in another form (each has a digest the revocation does not name, and all but the
    last a time after the revocation) is a valid row and approves nothing."""
    ws = library(tmp_path / "lib")
    approver = tmp_path / "approver.sqlite3"
    approve(ws, "Zoll90", database=approver)
    row = share(ws, database=approver)[0]
    records, _ = revoke(ws, "Zoll90", approver)
    later = (datetime.datetime.fromisoformat(records[0]["revoked_at"]) + datetime.timedelta(seconds=2)).isoformat()
    forged = FORGERIES[what](row, later)
    assert v.valid_shared_approval(forged)
    assert v.approval_digest(forged["human_review"]) not in v.revoked_digests(records[0]) or forged["approved_at"] == later
    with open(ws.approvals, "a", encoding="utf-8") as stream:
        stream.write(v.dumps(forged) + "\n")
    assert v.scan_approval_ledger(ws.approvals) == ([row, forged], [])
    for database in (approver, tmp_path / "other.sqlite3"):
        assert statuses(ws, database)["Zoll90"] != "human_verified", database
    # The revocation ledger alone decides: a database that never held the revocation agrees.
    assert json.loads(ws.revocations.read_text(encoding="utf-8")) == records[0]

    # The negative control: a new note, dated after the revocation, is a new decision.
    fresh = dict(retyped(row, note="Checked again against the publisher's page."), approved_at=later)
    with open(ws.approvals, "a", encoding="utf-8") as stream:
        stream.write(v.dumps(fresh) + "\n")
    found = results(ws, tmp_path / "other.sqlite3")["Zoll90"]
    assert found["status"] == "human_verified" and found["human_review"] == fresh["human_review"]


def test_the_digest_written_in_a_row_is_never_what_is_compared(tmp_path):
    """A revoked row typed again with a digest of its own invention: the digest is computed
    from the review, the row is invalid, and it approves nothing."""
    ws = library(tmp_path / "lib")
    approver = tmp_path / "approver.sqlite3"
    approve(ws, "Zoll90", database=approver)
    row = share(ws, database=approver)[0]
    records, _ = revoke(ws, "Zoll90", approver)
    later = (datetime.datetime.fromisoformat(records[0]["revoked_at"]) + datetime.timedelta(seconds=2)).isoformat()
    with open(ws.approvals, "a", encoding="utf-8") as stream:
        stream.write(v.dumps(dict(row, approval_digest="f" * 64, approved_at=later)) + "\n")
    rows, problems = v.scan_approval_ledger(ws.approvals)
    assert rows == [row] and "line 2 ignored: approval_digest is not the digest of human_review" in problems[0]
    assert statuses(ws, tmp_path / "other.sqlite3")["Zoll90"] != "human_verified"


# --- which copy of the ledger a gate reads -----------------------------------------------------------

def closed_network(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")                       # nothing listens there
    monkeypatch.setenv("NO_PROXY", ""); monkeypatch.setenv("no_proxy", "")


@pytest.mark.parametrize("how", ["against a reference", "all entries", "chosen keys",
                                 "with CDLBIB_APPROVAL_LEDGER naming the working tree's file"])
def test_a_row_typed_into_the_working_tree_approves_nothing_in_the_gate(tmp_path, monkeypatch, how):
    """An entry is edited and a valid row approving the new text is typed into
    verification/approvals.jsonl; no database holds any approval. Read as the library's own
    ledger (status, the views) the row approves the entry. The gate of `verify` and `send`
    reads the reference's ledger, whichever entries it is asked about (the changed ones, all
    of them, chosen keys) and whatever the environment says: the entry is not approved
    there, so the gate goes to look it up (the network is closed) and does not pass.

    (Until 2026-10-05 this test asserted that CDLBIB_APPROVAL_LEDGER pointing at the working
    tree's file made the gate pass. That was the defect, not the rule; the variable is gone.)"""
    ws = library(tmp_path / "lib")
    base = tmp_path / "base.bib"
    base.write_bytes(ws.bib.read_bytes())
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8").replace("Volume = {27}", "Volume = {28}"), encoding="utf-8")
    row = {"key": "Zoll90", "fingerprint": fingerprint(ws, "Zoll90"), "human_review": REVIEW,
           "approval_digest": v.approval_digest(REVIEW), "approved_at": v.now(), "policy": v.POLICY}
    v.append_approvals(ws.approvals, [row])
    assert statuses(ws, ws.database)["Zoll90"] == "human_verified"           # the checkout's own ledger, outside a gate
    closed_network(monkeypatch)
    options = {"against a reference": dict(reference=str(base)), "all entries": dict(reference=str(base), all_entries=True),
               "chosen keys": dict(reference=str(base), keys=["Zoll90"]),
               "with CDLBIB_APPROVAL_LEDGER naming the working tree's file": dict(reference=str(base))}[how]
    if how.startswith("with CDLBIB"):
        monkeypatch.setenv("CDLBIB_APPROVAL_LEDGER", str(ws.approvals))
    lines = []
    try:
        check = api.check_citations(ws, None, mailto="valid@example.org", progress=lines.append, **options)
        passed, checked = check.ok, check.citations.checked
    except GateFailed as refused:
        passed, checked, lines = False, {}, lines + [str(refused)]
    assert not passed, lines
    assert checked.get("Zoll90", {}).get("status") != "human_verified"
    assert not any("human_verified=1" in line for line in lines)


def test_the_gate_with_the_github_reference_counts_no_working_tree_row_when_master_cannot_be_read(tmp_path, monkeypatch):
    """Chosen keys, the default reference (GitHub's master) and no network: the reference's
    ledger cannot be fetched, so no ledger row counts, and the gate says so."""
    ws = library(tmp_path / "lib")
    row = {"key": "Zoll90", "fingerprint": fingerprint(ws, "Zoll90"), "human_review": REVIEW,
           "approval_digest": v.approval_digest(REVIEW), "approved_at": v.now(), "policy": v.POLICY}
    v.append_approvals(ws.approvals, [row])
    closed_network(monkeypatch)
    lines = []
    try:
        check = api.check_citations(ws, None, keys=["Zoll90"], mailto="valid@example.org", progress=lines.append)
        passed = check.ok
    except GateFailed as refused:
        passed, lines = False, lines + [str(refused)]
    assert not passed and any("no row of verification/approvals.jsonl is counted in this check" in line for line in lines)


def test_crossref_verify_reads_the_trusted_ledgers_it_is_given(tmp_path, monkeypatch):
    """What verification/check_ci.py runs. The entry is edited and a typed row in the working
    tree approves the new text. With an empty trusted ledger the row does not count (the
    look-up then fails: the network is closed). With the row in the trusted ledger it counts
    and nothing is looked up. With the row trusted and a trusted revocation of it, while the
    checkout's own revocation ledger is empty, it does not count."""
    from typer.testing import CliRunner
    from cdlbib.verification_cli import app
    ws = library(tmp_path / "lib")
    base = tmp_path / "base.bib"
    base.write_bytes(ws.bib.read_bytes())
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8").replace("Volume = {27}", "Volume = {28}"), encoding="utf-8")
    row = {"key": "Zoll90", "fingerprint": fingerprint(ws, "Zoll90"), "human_review": REVIEW,
           "approval_digest": v.approval_digest(REVIEW), "approved_at": v.now(), "policy": v.POLICY}
    v.append_approvals(ws.approvals, [row])
    closed_network(monkeypatch)
    monkeypatch.setenv("CROSSREF_MAILTO", "valid@example.org")
    empty, trusted, revoked = tmp_path / "empty.jsonl", tmp_path / "trusted.jsonl", tmp_path / "revoked.jsonl"
    empty.write_bytes(b""); trusted.write_bytes(ws.approvals.read_bytes())
    revoked.write_text(v.dumps({"key": "Zoll90", "fingerprint": row["fingerprint"], "approval": REVIEW,
                                "approval_digest": row["approval_digest"], "approval_checked_at": row["approved_at"],
                                "revoked_at": v.now(), "revoked_by": "@hubot", "reason": "Recorded in error."}) + "\n",
                       encoding="utf-8")

    def verify(name, *more):
        return CliRunner().invoke(app, ["verify", str(ws.bib), "--against", str(base), "--database",
                                        str(tmp_path / f"{name}.sqlite3"), "--report", str(tmp_path / f"{name}.jsonl"), *more])
    assert verify("a", "--trusted-approvals", str(empty)).exit_code != 0
    run = verify("b", "--trusted-approvals", str(trusted))
    assert run.exit_code == 0, run.output
    assert verify("c", "--trusted-approvals", str(trusted), "--trusted-revocations", str(revoked)).exit_code != 0
    assert not ws.revocations.exists()


def test_the_gate_downloads_the_reference_ledger_from_the_master_branch(tmp_path):
    """The real download, as the gate of a send makes it: the master's
    verification/approvals.jsonl, or an empty file while the master has none. Whatever it
    holds is read with the same validation as any ledger."""
    from cdlbib.verification_cli import reference_approvals
    path = reference_approvals("github", tmp_path / "work")
    assert path == str(tmp_path / "work" / "reference-approvals.jsonl")
    rows, problems = v.scan_approval_ledger(path)
    assert problems == [] and all(v.valid_shared_approval(row) for row in rows)
    assert Path(reference_approvals(str(tmp_path / "any.bib"), tmp_path / "work")).read_bytes() == b""


# --- sending --------------------------------------------------------------------------------------

@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A real clone of a real bare repository (the fork's stand-in) holding a two-entry library."""
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    remote = tmp_path / "fork.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "master", str(remote))
    work = tmp_path / "library"
    git(tmp_path, "clone", "-q", str(remote), str(work))
    git(work, "checkout", "-q", "-B", "master")
    (work / "verification").mkdir()
    (work / "cdl.bib").write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n", encoding="utf-8")
    (work / "verification" / "key-renames.json").write_text("{}\n", encoding="utf-8")
    (work / ".gitignore").write_text(".bibcheck/\n", encoding="utf-8")
    git(work, "add", "-A"); git(work, "commit", "-q", "-m", "start"); git(work, "push", "-q", "origin", "HEAD:master")
    return Workspace(work), remote


def test_the_state_of_the_library_lists_the_approvals_a_send_would_add(checkout):
    ws, _ = checkout
    assert api.library_state(ws).approvals == [] and api.library_state(ws).pending == []
    approve(ws, "Zoll90")
    found = api.library_state(ws)
    assert found.approvals == [{"key": "Zoll90", "login": "octocat"}] and found.pending == [] and found.notes == []
    assert found.unsent_approvals == [] and found.login is None             # gh was not asked whose they are
    assert not ws.approvals.exists()                                         # looking adds nothing to the ledger
    share(ws)
    found = api.library_state(ws)
    assert found.approvals == [] and found.pending == [LEDGER]
    assert api.as_data(found)["approvals"] == []
    plain = library(ws.root.parent / "no checkout")                          # not a git checkout: nothing can be sent
    approve(plain, "Zoll90")
    assert api.library_state(plain).approvals is None and api.library_state(plain).pending is None


def logged_in():
    """The real GitHub user of the gh CLI (identity.Identity); a skip where nobody is logged in."""
    from cdlbib import identity
    try:
        return identity.current()
    except IdentityUnavailable as exc:
        pytest.skip(f"no GitHub user is logged in (expected in CI): {exc}")


def mine(me, **more):
    """A review as `approve` records it for the logged-in user."""
    return dict(reviewer=me.handle, github_login=me.login, github_id=me.id, **more)


def nobody_logged_in(monkeypatch, tmp_path):
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "empty-gh"))
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_only_the_senders_own_approvals_are_rows_to_send(tmp_path):
    """Whose an approval is: by the numeric id when the approval has one, else by the login
    whatever its case. The sender here is an Identity value; no one is asked."""
    from cdlbib.identity import Identity
    ws = library(tmp_path / "lib", ZOLL90 + "\n\n" + RAME72 % "1" + "\n\n" + (RAME72 % "2").replace("Rame72", "Rame72b") + "\n")
    approve(ws, "Zoll90")                                                    # @octocat, id 583231
    approve(ws, "Rame72", reviewer="@hubot", github_login="hubot", github_id=480938)
    cache = v.Cache(str(ws.database), ledger=ws.revocations)                 # one stored before `approve` checked rows
    try:
        cache.put(str(ws.bib), v.load_entries(str(ws.bib))["Rame72b"], dict(
            v.outcome("human_verified", []), human_review=dict(REVIEW, reviewer="@OctoCat", github_login="OctoCat", github_id=None)))
    finally:
        cache.close()
    rows, unsent = api.approvals_waiting(ws)
    assert [row["key"] for row in rows] == ["Zoll90", "Rame72"] and [item["key"] for item in unsent] == ["Rame72b"]
    assert "github_id is not an integer" in unsent[0]["why"]                 # a stored review that is no valid row
    octocat = Identity(login="octocat", id=583231)
    rows, unsent = api.approvals_waiting(ws, me=octocat)
    assert [row["key"] for row in rows] == ["Zoll90"]
    assert {item["key"]: item["why"] for item in unsent}["Rame72"] == "recorded under @hubot"
    assert api.unsent_line(unsent[0]) == "approval of Rame72 not sent: recorded under @hubot"
    assert api.approvals_to_send(ws, me=octocat) == rows
    # The login was renamed since: the id still says it is the same user. The same login
    # under another id is another user.
    assert [row["key"] for row in api.approvals_to_send(ws, me=Identity(login="octocat-renamed", id=583231))] == ["Zoll90"]
    assert api.approvals_to_send(ws, me=Identity(login="octocat", id=1)) == []
    assert [row["key"] for row in api.approvals_to_send(ws, me=Identity(login="HUBOT", id=480938))] == ["Rame72"]
    # An approval stored without an id is compared by login, whatever the case.
    plain = library(tmp_path / "plain")
    cache = v.Cache(str(plain.database), ledger=plain.revocations)
    try:
        v.record_approval(cache, str(plain.bib), "Zoll90", fingerprint(plain, "Zoll90"),
                          {k: x for k, x in REVIEW.items() if k != "github_id"})
    finally:
        cache.close()
    assert [row["key"] for row in api.approvals_to_send(plain, me=Identity(login="OctoCat", id=7))] == ["Zoll90"]
    assert api.approvals_to_send(plain, me=Identity(login="hubot", id=583231)) == []


def test_a_send_with_an_approval_waiting_and_nobody_logged_in_changes_nothing(checkout, monkeypatch, tmp_path):
    ws, _ = checkout
    with pytest.raises(PublishRefused, match="no changes to cdl.bib or verification/"):
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)   # nothing waits: gh is not asked
    approve(ws, "Zoll90")
    nobody_logged_in(monkeypatch, tmp_path)
    before, lines = state(ws.root), []
    with pytest.raises(IdentityUnavailable):                                 # whose approval it is cannot be told
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE, progress=lines.append)
    assert lines == [] and state(ws.root) == before and not ws.approvals.exists()
    assert [row["key"] for row in api.approvals_to_send(ws)] == ["Zoll90"]   # it still waits


def test_a_send_of_my_approval_alone_is_not_refused_as_nothing_to_send(checkout):
    """Nothing in cdl.bib or verification/ has changed; one approval under the real login
    waits, and one under another login. The send adds mine alone, passes the gate, and stops
    where GitHub is asked about a repository that cannot exist: the row is taken out again."""
    me = logged_in()
    ws, _ = checkout
    approve(ws, "Zoll90", **mine(me))
    approve(ws, "Rame72", note="Checked the volume in print.")               # @octocat's, restored or copied here
    assert publish.pending(ws) == []
    before, lines = state(ws.root), []
    with pytest.raises(PublishRefused) as refused:
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE, progress=lines.append)
    assert "no changes to cdl.bib" not in str(refused.value)
    assert lines[0] == "approval of Rame72 not sent: recorded under @octocat"
    assert lines[1] == f"approval of Zoll90 by @{me.login}: added to {LEDGER}"
    assert not any("Rame72" in line for line in lines[1:])
    assert "checks passed; generating commit message..." in lines           # the gate ran with the row in place
    assert lines[-1] == f"not sent: {LEDGER} is as it was before (the approvals stay in the local database)"
    assert state(ws.root) == before and not ws.approvals.exists()
    assert [row["key"] for row in api.approvals_to_send(ws, me=me)] == ["Zoll90"]


def test_a_send_of_someone_elses_approval_alone_is_refused_and_says_why(checkout):
    """The only approval in the database is under another login. Nothing is added to the
    ledger, and the send is the refusal "no changes" with the approval and the reason named."""
    logged_in()
    ws, _ = checkout
    approve(ws, "Zoll90")
    before, lines = state(ws.root), []
    with pytest.raises(PublishRefused) as refused:
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE, progress=lines.append)
    assert str(refused.value) == (publish.NO_CHANGES + "\napproval of Zoll90 not sent: recorded under @octocat")
    assert lines == ["approval of Zoll90 not sent: recorded under @octocat"]
    assert state(ws.root) == before and not ws.approvals.exists()


def test_a_send_the_gate_refuses_leaves_the_ledger_byte_for_byte(checkout):
    """An earlier row is committed; a second approval, under the real login, waits; the edit
    to cdl.bib fails the format check. After the refusal the ledger holds the committed row
    and nothing else."""
    me = logged_in()
    ws, _ = checkout
    approve(ws, "Rame72", note="Checked the volume in print.")
    share(ws)
    git(ws.root, "add", LEDGER); git(ws.root, "commit", "-q", "-m", "an approval")
    committed = ws.approvals.read_bytes()
    approve(ws, "Zoll90", **mine(me))
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + "\n" + BAD, encoding="utf-8")
    assert [row["key"] for row in api.approvals_to_send(ws)] == ["Zoll90"]   # the edit is to another entry
    before, lines = state(ws.root), []
    with pytest.raises(GateFailed) as refused:
        api.send(ws, summary="bad", reference=str(ws.bib), upstream=NOWHERE, base=TEST_BASE, progress=lines.append)
    assert refused.value.check is not None and not refused.value.check.ok
    assert lines[0] == f"approval of Zoll90 by @{me.login}: added to {LEDGER}"
    assert lines[-1].startswith(f"not sent: {LEDGER} is as it was before")
    assert state(ws.root) == before and ws.approvals.read_bytes() == committed
    assert git(ws.root, "status", "--porcelain", "--", "verification") == ""


# --- an approval that could not be a row is refused when it is recorded, and named when it is stored ----

def test_approve_refuses_a_note_or_source_over_the_ledgers_limit_and_names_the_limit(tmp_path):
    ws = library(tmp_path / "lib")
    with pytest.raises(ValueError) as refused:
        approve(ws, "Zoll90", note="x" * 8001)
    assert str(refused.value) == ("The note is 8001 characters long; an approval's note can be at most 8000 "
                                  "characters. Nothing was recorded.")
    with pytest.raises(ValueError, match="The source is 4001 characters long; an approval's source can be at most 4000"):
        approve(ws, "Zoll90", source="x" * 4001)
    with pytest.raises(ValueError, match="The reviewer is 201 characters long; an approval's reviewer can be at most 200"):
        approve(ws, "Zoll90", reviewer="x" * 201)
    with pytest.raises(ValueError, match=r"could not be shared as a row of the approvals ledger \(human_review.github_id "
                                         r"is not an integer\)"):
        approve(ws, "Zoll90", github_id="583231")
    with pytest.raises(ValueError, match="github_login is not a GitHub login"):
        approve(ws, "Zoll90", github_login="octo cat")
    assert statuses(ws, ws.database) == {"Zoll90": "pending", "Rame72": "pending"}       # nothing was recorded
    approve(ws, "Zoll90", note="x" * 8000, source="y" * 4000)               # at the limit: recorded, and a valid row
    assert [row["key"] for row in share(ws)] == ["Zoll90"] and v.scan_approval_ledger(ws.approvals)[1] == []
    # A review that names no GitHub login (as the baseline's do) has the same limits.
    with pytest.raises(ValueError, match="at most 8000 characters"):
        approve(ws, "Rame72", reviewer="A Person", github_login=None, github_id=None, note="x" * 8001)


def test_the_approve_command_path_refuses_an_over_long_note_under_the_real_login(tmp_path):
    from cdlbib.errors import ApprovalRefused
    logged_in()
    ws = library(tmp_path / "lib")
    with pytest.raises(ApprovalRefused, match="an approval's note can be at most 8000 characters. Nothing was recorded."):
        api.approve(ws, "Zoll90", fingerprint(ws, "Zoll90"), REVIEW["source"], "x" * 8001)
    assert api.status(ws).counts == {"pending": 2}


def test_a_stored_approval_that_cannot_be_a_row_is_named_and_a_send_of_it_alone_is_refused(checkout):
    """An approval stored before the limit was checked at `approve` (written here as the
    cache stores a result): the state and the send name it and the limit; a send of it alone
    is refused, adds nothing to the ledger and changes nothing."""
    me = logged_in()
    ws, _ = checkout
    cache = v.Cache(str(ws.database), ledger=ws.revocations)
    try:
        entry = v.load_entries(str(ws.bib))["Zoll90"]
        cache.put(str(ws.bib), entry, dict(v.outcome("human_verified", []),
                                           human_review=mine(me, source=REVIEW["source"], note="x" * 9000)))
    finally:
        cache.close()
    assert statuses(ws, ws.database)["Zoll90"] == "human_verified"
    why = f"it cannot be written to {LEDGER}: human_review.note is 9000 characters long; the limit is 8000"
    assert api.approvals_waiting(ws, me=me) == ([], [{"key": "Zoll90", "login": me.login, "why": why}])
    found = api.library_state(ws)
    assert found.approvals == [] and found.unsent_approvals == [{"key": "Zoll90", "login": me.login, "why": why}]
    before, lines = state(ws.root), []
    with pytest.raises(PublishRefused) as refused:
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE, progress=lines.append)
    assert str(refused.value) == publish.NO_CHANGES + f"\napproval of Zoll90 not sent: {why}"
    assert lines == [f"approval of Zoll90 not sent: {why}"]
    assert state(ws.root) == before and not ws.approvals.exists()


def test_approve_refuses_a_revoked_review_in_another_form_as_the_ledger_does(tmp_path):
    """The rule `approve` and the ledger share: after a revocation, the same source and note
    (whatever the spacing, the case or the signer) is the revoked review; a new note is a new
    decision."""
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    approve(ws, "Rame72", note="Checked the volume in print.")               # the negative control: never revoked
    records, _ = revoke(ws, "Zoll90", ws.database)
    after_revocation = (datetime.datetime.fromisoformat(records[0]["revoked_at"]) + datetime.timedelta(seconds=2)).isoformat()
    for review in (dict(note="  compared   EVERY field with the printed article. "),
                   dict(source=REVIEW["source"] + "  "),
                   dict(reviewer="@hubot", github_login="hubot", github_id=480938),
                   dict(github_id=1), {}):
        with pytest.raises(ValueError, match="This exact approval was revoked"):
            approve(ws, "Zoll90", **review)
        row = {"key": "Zoll90", "fingerprint": fingerprint(ws, "Zoll90"), "human_review": dict(REVIEW, **review),
               "approval_digest": v.approval_digest(dict(REVIEW, **review)), "approved_at": after_revocation,
               "policy": v.POLICY}
        assert v.valid_shared_approval(row) and v.shared_revoked(v.read_revocation_ledger(ws.revocations)[0], row)
    assert statuses(ws, ws.database) == {"Zoll90": "needs_review", "Rame72": "human_verified"}
    approve(ws, "Rame72", note="  checked the VOLUME in print. ")            # not revoked: the same words may be recorded again
    approve(ws, "Zoll90", note="Checked again against the publisher's page.")
    assert statuses(ws, ws.database)["Zoll90"] == "human_verified"
    assert [row["key"] for row in api.approvals_to_send(ws)] == ["Zoll90", "Rame72"]


def record_of(ws):
    return ws.work / api.APPROVAL_SEND / api.APPROVAL_SEND_RECORD


def test_rows_a_send_added_are_settled_put_back_committed_or_reported(checkout, tmp_path):
    ws, remote = checkout
    approve(ws, "Zoll90")
    rows = api.approvals_to_send(ws)
    assert api.settle_approval_send(ws) == ([], None)                        # nothing to settle
    api._ledger_approvals(ws, rows)
    written = ws.approvals.read_bytes()
    assert record_of(ws).is_file()
    assert api.settle_approval_send(ws) == (
        [f"not sent: {LEDGER} is as it was before (the approvals stay in the local database)"], None)
    assert not ws.approvals.exists() and not record_of(ws).exists() and git(ws.root, "status", "--porcelain") == ""

    # Something else changed the file after the rows were added: it is not put back, nothing
    # is written to it, and that is said, with the rows named.
    api._ledger_approvals(ws, rows)
    with open(ws.approvals, "ab") as stream:
        stream.write(b"\n")
    lines, problem = api.settle_approval_send(ws)
    assert lines == [] and "was NOT put back as it was before the send" in problem
    assert "something else changed the file" in problem and "approval of Zoll90" in problem
    assert ws.approvals.read_bytes() == written + b"\n" and not record_of(ws).exists()
    ws.approvals.unlink()

    # A commit holds the rows: they are the branch's now, and only the record is dropped.
    from cdlbib import library as lib
    branch = "cdlbib/test/2026-10-05-approvals"
    with lib.transaction(ws):                                                # as a send holds the lock throughout
        api._ledger_approvals(ws, rows)
        with pytest.raises(PublishRefused, match=f"committed on branch {branch}"):
            publish.deliver(ws, branch, "approvals", str(tmp_path / "no-such-remote.git"))
        assert api.settle_approval_send(ws) == ([], None) and not record_of(ws).exists()
    assert ws.approvals.read_bytes() == written and git(ws.root, "status", "--porcelain") == ""
    assert git(ws.root, "show", "--name-only", "--format=", "HEAD").split() == [LEDGER]
    assert publish.deliver(ws, branch, "approvals", str(remote)) == []       # the resumed send: the push alone
    assert git(remote, "rev-parse", branch) == git(ws.root, "rev-parse", "HEAD")


def test_a_send_that_is_killed_is_settled_when_the_lock_is_next_taken(checkout, tmp_path):
    """A real process adds the rows as a send does and is killed (SIGKILL) before anything
    else. The row is in the working tree. The next command that takes the library's lock
    puts the ledger back and says so."""
    import sys
    import textwrap
    from cdlbib import library as lib
    ws, _ = checkout
    approve(ws, "Zoll90")
    script = tmp_path / "killed.py"
    script.write_text(textwrap.dedent("""
        import os, signal, sys
        from cdlbib import api, verification
        from cdlbib.workspace import Workspace
        verification.REVOCATION_LEDGER = None
        ws = Workspace(sys.argv[1])
        api._ledger_approvals(ws, api.approvals_to_send(ws))
        os.kill(os.getpid(), signal.SIGKILL)
    """), encoding="utf-8")
    run = subprocess.run([sys.executable, str(script), str(ws.root)], capture_output=True, text=True)
    assert run.returncode == -9, run.stderr
    assert [row["key"] for row in rows_of(ws)] == ["Zoll90"] and record_of(ws).is_file()
    assert git(ws.root, "status", "--porcelain") == f"?? {LEDGER}"
    with lib.transaction(ws):
        assert not ws.approvals.exists()                                     # settled as the lock was taken
    assert lib.settled(ws) == [f"not sent: {LEDGER} is as it was before (the approvals stay in the local database)"]
    assert not record_of(ws).exists() and git(ws.root, "status", "--porcelain") == ""
    assert [row["key"] for row in api.approvals_to_send(ws)] == ["Zoll90"]   # it still waits


def test_a_progress_callback_that_raises_leaves_no_row_behind(checkout):
    me = logged_in()
    ws, _ = checkout
    approve(ws, "Zoll90", **mine(me))
    before = state(ws.root)

    def progress(line):
        if "added to" in line:
            raise RuntimeError("the front end went away")
    with pytest.raises(RuntimeError, match="the front end went away"):
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE, progress=progress)
    assert state(ws.root) == before and not ws.approvals.exists() and not record_of(ws).exists()


def test_a_send_whose_rows_cannot_be_taken_out_again_says_so(checkout):
    """Another program writes to the ledger while the send runs (here: the progress callback,
    at the gate). The send fails further on; the file is not put back, nothing is written to
    it, and the refusal says so instead of promising it is as it was."""
    me = logged_in()
    ws, _ = checkout
    approve(ws, "Zoll90", **mine(me))
    lines = []

    def progress(line):
        lines.append(line)
        if line.startswith("checks passed"):
            with open(ws.approvals, "ab") as stream:
                stream.write(b"\n")
    with pytest.raises(PublishRefused) as refused:
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE, progress=progress)
    message = str(refused.value)
    assert f"{LEDGER} was NOT put back as it was before the send" in message and "approval of Zoll90" in message
    assert not any(line.startswith(f"not sent: {LEDGER} is as it was before") for line in lines)
    assert ws.approvals.read_bytes().endswith(b"}\n\n")                      # the row and the other program's byte: untouched
    assert not record_of(ws).exists()


def test_a_failed_commit_leaves_the_index_entry_of_the_ledger_as_it_was(checkout):
    """The user had staged the ledger (an earlier row of their own). The send adds a row, the
    commit fails for real (a hook), and git's index then holds the file with the new row.
    Settling puts the file and the index entry back."""
    from test_publish import failing_hook
    ws, _ = checkout
    approve(ws, "Rame72", note="Checked the volume in print.")
    share(ws)
    git(ws.root, "add", LEDGER)                                              # staged by the user, not by cdlbib
    staged, file_before, before = git(ws.root, "ls-files", "-s", "--", LEDGER), ws.approvals.read_bytes(), state(ws.root)
    approve(ws, "Zoll90")
    api._ledger_approvals(ws, [row for row in api.approvals_to_send(ws)])
    failing_hook(ws)
    with pytest.raises(PublishRefused, match="hook says no"):
        publish.commit_to_branch(ws, "cdlbib/test/2026-10-05-approvals", "approvals")
    assert git(ws.root, "ls-files", "-s", "--", LEDGER) != staged            # the failed commit staged the new row
    lines, problem = api.settle_approval_send(ws)
    assert problem is None and lines
    assert ws.approvals.read_bytes() == file_before and git(ws.root, "ls-files", "-s", "--", LEDGER) == staged
    assert state(ws.root) == before


# --- whose rows a send may carry ---------------------------------------------------------------------

def test_a_send_refuses_an_uncommitted_row_that_is_not_the_senders(checkout):
    """A valid row for another login is already in the working tree's ledger, uncommitted
    (typed, or left by a clean-up that failed). Nothing waits in the database; cdl.bib has an
    ordinary edit. The send is refused before anything is written."""
    me = logged_in()
    ws, _ = checkout
    row = {"key": "Zoll90", "fingerprint": fingerprint(ws, "Zoll90"), "human_review": REVIEW,
           "approval_digest": v.approval_digest(REVIEW), "approved_at": v.now(), "policy": v.POLICY}
    v.append_approvals(ws.approvals, [row])
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + "\n% an edit\n", encoding="utf-8")
    before, ledger = state(ws.root), ws.approvals.read_bytes()
    with pytest.raises(PublishRefused) as refused:
        api.send(ws, summary="edit", reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)
    assert f"holds a row not yet committed that {me.handle} did not record: Zoll90 (recorded under @octocat)" in str(refused.value)
    assert state(ws.root) == before and ws.approvals.read_bytes() == ledger

    # The sender's own uncommitted row is no refusal of this kind (the send goes on to GitHub).
    ws.approvals.unlink()
    own = dict(row, human_review=mine(me, source=REVIEW["source"], note=REVIEW["note"]))
    own["approval_digest"] = v.approval_digest(own["human_review"])
    v.append_approvals(ws.approvals, [own])
    with pytest.raises(PublishRefused) as refused:
        api.send(ws, summary="edit", reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)
    assert "did not record" not in str(refused.value)


def test_a_send_refuses_a_ledger_whose_committed_lines_changed_or_that_gained_a_line_that_is_no_row(checkout):
    ws, _ = checkout
    approve(ws, "Rame72", note="Checked the volume in print.")
    share(ws)
    git(ws.root, "add", LEDGER); git(ws.root, "commit", "-q", "-m", "an approval")
    committed = ws.approvals.read_bytes()
    for changed, said in ((b"", "a line was removed or changed"),
                          (committed.replace(b"Checked", b"checked"), "a line was removed or changed"),
                          (committed + b"not a row\n", "holds a new line that is not a valid approval row"),
                          (committed + committed.replace(b'"note":"Checked', b'"note":"x'), "approval_digest is not the digest")):
        ws.approvals.write_bytes(changed)
        before = state(ws.root)
        with pytest.raises(PublishRefused, match=said):
            api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)
        assert state(ws.root) == before and ws.approvals.read_bytes() == changed


def test_a_send_is_refused_when_the_github_login_changes_during_the_gate(checkout, monkeypatch, tmp_path):
    """The approvals are chosen by who is logged in before the gate. During the gate the
    login goes away (gh is pointed at an empty configuration by the progress callback, as a
    switch of account in another terminal would change it). The send asks again after the
    gate, is refused, and the row is taken out."""
    me = logged_in()
    ws, _ = checkout
    approve(ws, "Zoll90", **mine(me))
    before, lines = state(ws.root), []

    def progress(line):
        lines.append(line)
        if line.startswith("checks passed"):
            nobody_logged_in(monkeypatch, tmp_path)
    with pytest.raises(PublishRefused, match=f"The GitHub login changed during the send: it was @{me.login}"):
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE, progress=progress)
    assert f"approval of Zoll90 by @{me.login}: added to {LEDGER}" in lines
    assert state(ws.root) == before and not ws.approvals.exists()


# --- links, sizes, outputs -------------------------------------------------------------------------

@pytest.mark.parametrize("what", ["the ledger is a link", "the verification folder is a link"])
def test_nothing_is_read_or_written_through_a_link_in_the_ledgers_place(checkout, tmp_path, what):
    ws, _ = checkout
    approve(ws, "Zoll90")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "approvals.jsonl"
    target.write_bytes(b"someone else's file\n")
    if what == "the ledger is a link":
        ws.approvals.symlink_to(target)
    else:
        shutil.move(str(ws.root / "verification"), str(outside / "moved"))
        (ws.root / "verification").symlink_to(outside)
    kept = {path: path.read_bytes() for path in outside.rglob("*") if path.is_file()}
    row = api.approvals_to_send(library(tmp_path / "plain"))                 # [] : just to have the helpers warm
    assert row == []
    with pytest.raises(ValueError, match="is a link or not an ordinary"):
        v.append_approvals(ws.approvals, [])
    with pytest.raises(Exception, match="is a link or not an ordinary") as refused:
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)
    assert isinstance(refused.value, (PublishRefused, api.CdlbibError))
    assert {path: path.read_bytes() for path in outside.rglob("*") if path.is_file()} == kept
    assert not record_of(ws).exists()
    found = api.library_state(ws)
    assert found.approvals is None and any("is a link or not an ordinary" in note for note in found.notes)


def test_limits_are_those_of_the_row_as_written_in_bytes(tmp_path):
    """8,000 characters of a four-byte letter are within the note's limit in characters and
    make a line a reader would ignore: `approve` refuses, naming the limit in bytes."""
    ws = library(tmp_path / "lib")
    with pytest.raises(ValueError) as refused:
        approve(ws, "Zoll90", note="\U0001F600" * 8000, source="y" * 4000)
    assert re.fullmatch(r"This approval would be a line of \d+ bytes in the approvals ledger; a line longer than "
                        r"32768 bytes is not read\. Shorten the note or the source\. Nothing was recorded\.",
                        str(refused.value))
    assert statuses(ws, ws.database)["Zoll90"] == "pending"
    approve(ws, "Zoll90", note="\U0001F600" * 7000)                          # under the limit as written
    [row] = share(ws)
    assert len(ws.approvals.read_bytes()) <= v.APPROVAL_ROW_MAX_BYTES and v.scan_approval_ledger(ws.approvals) == ([row], [])
    # A row that is valid in every field and too long as written is no valid row, and is not written.
    long = retyped(row, note="\U0001F600" * 8000, source="y" * 4000)
    assert "bytes as written" in v.shared_approval_problem(long)
    with pytest.raises(ValueError, match="bytes as written"):
        v.append_approvals(tmp_path / "x" / "approvals.jsonl", [long])


def test_an_approval_that_would_take_the_ledger_over_its_size_is_refused_and_the_ledger_untouched(checkout):
    ws, _ = checkout
    approve(ws, "Rame72", note="Checked the volume in print.")
    [row] = share(ws)
    line = ws.approvals.read_bytes()
    full = line * ((v.APPROVAL_LEDGER_MAX_BYTES - 200) // len(line))         # valid, and within 200 bytes of the limit
    ws.approvals.write_bytes(full)
    assert v.scan_approval_ledger(ws.approvals)[1] == []
    with pytest.raises(ValueError, match=r"a ledger larger than 8388608 bytes is not read\. Nothing was recorded\."):
        approve(ws, "Zoll90")
    assert ws.approvals.read_bytes() == full and statuses(ws, ws.database)["Zoll90"] == "pending"
    # One stored before the ledger grew: the send's own append refuses, writes nothing, keeps no record.
    ws.approvals.write_bytes(line)
    approve(ws, "Zoll90")
    ws.approvals.write_bytes(full)
    rows = api.approvals_to_send(ws)
    assert [r["key"] for r in rows] == ["Zoll90"]
    with pytest.raises(api.CdlbibError, match="a ledger larger than 8388608 bytes is not read"):
        api._ledger_approvals(ws, rows)
    assert ws.approvals.read_bytes() == full and not record_of(ws).exists()


def test_a_time_without_a_zone_is_no_valid_row(tmp_path):
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    [row] = share(ws)
    assert v.shared_approval_problem(dict(row, approved_at="2026-10-05T12:00:00")) == "approved_at is not a time with a zone"
    assert v.valid_shared_approval(dict(row, approved_at="2026-10-05T12:00:00Z"))
    assert v.valid_shared_approval(dict(row, approved_at="2026-10-05T12:00:00+00:00"))


@pytest.mark.parametrize("target", ["approvals", "revocations", "a link to the approvals", "another name of the approvals"])
def test_a_report_or_snapshot_cannot_be_written_over_a_ledger(tmp_path, target):
    from typer.testing import CliRunner
    from cdlbib.verification_cli import app
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    share(ws)
    revoke(ws, "Zoll90", ws.database)
    output = {"approvals": ws.approvals, "revocations": ws.revocations,
              "a link to the approvals": tmp_path / "link.jsonl", "another name of the approvals": tmp_path / "hard.jsonl"}[target]
    if target == "a link to the approvals":
        output.symlink_to(ws.approvals)
    elif target == "another name of the approvals":
        os.link(ws.approvals, output)
    kept = (ws.approvals.read_bytes(), ws.revocations.read_bytes())
    run = CliRunner().invoke(app, ["status", str(ws.bib), "--database", str(ws.database), "--report", str(output)])
    assert run.exit_code == 2 and "Output path would overwrite a ledger of approvals or revocations" in run.output
    run = CliRunner().invoke(app, ["snapshot", str(output), "--fname", str(ws.bib), "--database", str(ws.database)])
    assert run.exit_code == 2 and "Output path would overwrite a ledger of approvals or revocations" in run.output
    with pytest.raises(api.GateFailed, match="would overwrite a ledger"):
        api.status(ws, report=str(output))
    assert (ws.approvals.read_bytes(), ws.revocations.read_bytes()) == kept


# --- a later machine result for the same text ---------------------------------------------------------

def stored_after(ws, database, key, status, issues):
    """A result stored for ``key`` now, as a check stores it (`verify --refresh`, a review layer)."""
    cache = v.Cache(str(database), ledger=ws.revocations)
    try:
        cache.put(str(ws.bib), v.load_entries(str(ws.bib))[key], v.outcome(status, issues))
    finally:
        cache.close()


@pytest.mark.parametrize("status", ["needs_review", "provider_error", "metadata_verified"])
def test_a_result_stored_after_the_approval_outranks_a_ledger_row_as_it_does_a_local_approval(tmp_path, status):
    """Parity of the two paths. Zoll90's approval is only in the local database; Rame72's is
    only a ledger row (the database that reads it never stored it). A result is then stored
    for each text, whatever it says: each entry has that result's status. A new approval
    recorded after it counts again on both paths."""
    ws = library(tmp_path / "lib")
    reader, approver = tmp_path / "reader.sqlite3", tmp_path / "approver.sqlite3"
    approve(ws, "Zoll90", database=reader)                                   # local only
    approve(ws, "Rame72", database=approver, note="Checked the volume in print.")
    v.append_approvals(ws.approvals, [row for row in api.approvals_to_send(ws, database=approver)])   # a ledger row only
    assert statuses(ws, reader) == {"Zoll90": "human_verified", "Rame72": "human_verified"}
    for key in ("Zoll90", "Rame72"):
        stored_after(ws, reader, key, status, ["Stored by a later check"])
    assert statuses(ws, reader) == {"Zoll90": status, "Rame72": status}
    assert statuses(ws, tmp_path / "empty.sqlite3")["Rame72"] == "human_verified"      # where nothing later is stored

    approve(ws, "Zoll90", database=reader, note="Looked again after the later check.")           # a new local approval
    approve(ws, "Rame72", database=approver, note="Looked again after the later check.")         # a new ledger row
    v.append_approvals(ws.approvals, [row for row in api.approvals_to_send(ws, database=approver)])
    assert len(rows_of(ws)) == 2
    assert statuses(ws, reader) == {"Zoll90": "human_verified", "Rame72": "human_verified"}
    assert results(ws, reader)["Rame72"]["human_review"]["note"] == "Looked again after the later check."


def test_a_result_stored_before_the_approval_does_not_outrank_it_on_either_path(tmp_path):
    """The other order in time: the check's result is stored first, the approval is made
    afterwards. Both the local approval and the ledger row count, and the row's view keeps
    the stored result's findings."""
    ws = library(tmp_path / "lib")
    reader, approver = tmp_path / "reader.sqlite3", tmp_path / "approver.sqlite3"
    for key in ("Zoll90", "Rame72"):
        stored_after(ws, reader, key, "needs_review", ["Found by the earlier check"])
    assert statuses(ws, reader) == {"Zoll90": "needs_review", "Rame72": "needs_review"}
    approve(ws, "Zoll90", database=reader)
    approve(ws, "Rame72", database=approver, note="Checked the volume in print.")
    v.append_approvals(ws.approvals, [row for row in api.approvals_to_send(ws, database=approver)])
    found = results(ws, reader)
    assert {key: result["status"] for key, result in found.items()} == {"Zoll90": "human_verified", "Rame72": "human_verified"}
    assert found["Rame72"]["issues"] == ["Found by the earlier check"] == found["Zoll90"]["issues"]


def test_a_row_and_a_stored_result_of_the_same_instant_and_a_stored_time_that_cannot_be_read(tmp_path):
    """Strictly later outranks: a result stored at exactly the row's time does not. A stored
    result whose time cannot be read is taken as later."""
    ws = library(tmp_path / "lib")
    approver = tmp_path / "approver.sqlite3"
    approve(ws, "Zoll90", database=approver)
    [row] = api.approvals_to_send(ws, database=approver)
    v.append_approvals(ws.approvals, [row])
    entry = v.load_entries(str(ws.bib))["Zoll90"]
    at = datetime.datetime.fromisoformat(row["approved_at"])
    other_zone = at.astimezone(datetime.timezone(datetime.timedelta(hours=-7)))          # the same instant, written otherwise
    earlier_but_sorts_later = (at - datetime.timedelta(hours=1)).astimezone(datetime.timezone(datetime.timedelta(hours=9)))
    assert earlier_but_sorts_later.isoformat() > row["approved_at"]                       # as text it would look later
    for name, when, expected in (("same", row["approved_at"], "human_verified"),
                                 ("same instant in another zone", other_zone.isoformat(), "human_verified"),
                                 ("an hour earlier in a zone that sorts later", earlier_but_sorts_later.isoformat(), "human_verified"),
                                 ("a second later", (at + datetime.timedelta(seconds=1)).isoformat(), "needs_review"),
                                 ("unreadable", "some time ago", "needs_review"),
                                 ("missing", None, "needs_review")):
        cache = v.Cache(str(tmp_path / f"{name}.sqlite3"), ledger=ws.revocations)
        try:
            stored = dict(v.outcome("needs_review", []), key="Zoll90", checked_at=when,
                          fingerprint=entry["fingerprint"], policy=v.POLICY)
            if when is None:
                del stored["checked_at"]
            cache.store(str(ws.bib), entry, stored)
            assert cache.get(str(ws.bib), entry)["status"] == expected, name
        finally:
            cache.close()


def test_a_row_dated_in_the_future_counts_nowhere_is_reported_and_is_never_written_or_sent(checkout, tmp_path):
    """`approved_at` is typed text. A row dated ahead of the clock (beyond five minutes) is no
    valid row: it approves nothing in an empty database, does not outrank a failed check
    stored today or escape a revocation made today, is reported with its line number, cannot
    be appended, and a send refuses to carry it. A row two minutes ahead (a clock that
    differs a little) is a row like any other."""
    ws, _ = checkout
    approver = tmp_path / "approver.sqlite3"
    approve(ws, "Zoll90", database=approver)
    [row] = api.approvals_to_send(ws, database=approver)
    now = datetime.datetime.now(datetime.timezone.utc)
    for when in ("2099-01-01T00:00:00+00:00", (now + datetime.timedelta(minutes=6)).isoformat(),
                 (now + datetime.timedelta(hours=1)).astimezone(datetime.timezone(datetime.timedelta(hours=-11))).isoformat()):
        future = dict(row, approved_at=when)
        assert "is later than the present time" in v.shared_approval_problem(future), when
        with pytest.raises(ValueError, match="a row dated in the future is not counted"):
            v.append_approvals(tmp_path / "elsewhere" / "approvals.jsonl", [future])
        ws.approvals.write_text(v.dumps(future) + "\n", encoding="utf-8")
        assert statuses(ws, tmp_path / "empty.sqlite3")["Zoll90"] == "pending", when
        rows, problems = v.scan_approval_ledger(ws.approvals)
        assert rows == [] and "line 1 ignored: approved_at" in problems[0] and api.approval_problems(ws) == problems
    assert not (tmp_path / "elsewhere" / "approvals.jsonl").exists()
    # A failed check stored today, and a revocation made today, are not beaten by the year 2099.
    ws.approvals.write_text(v.dumps(dict(row, approved_at="2099-01-01T00:00:00+00:00")) + "\n", encoding="utf-8")
    stored_after(ws, tmp_path / "checked.sqlite3", "Zoll90", "needs_review", ["Found today"])
    assert statuses(ws, tmp_path / "checked.sqlite3")["Zoll90"] == "needs_review"
    revoke(ws, "Zoll90", approver)
    assert statuses(ws, approver)["Zoll90"] == "needs_review" and statuses(ws, tmp_path / "empty.sqlite3")["Zoll90"] == "pending"
    ws.revocations.unlink()
    # A send does not carry it: refused before anything is written, whoever is logged in.
    before, ledger = state(ws.root), ws.approvals.read_bytes()
    with pytest.raises(PublishRefused, match="holds a new line that is not a valid approval row .approved_at .*is later than"):
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)
    assert state(ws.root) == before and ws.approvals.read_bytes() == ledger
    # Within the allowance: a row.
    near = dict(row, approved_at=(now + datetime.timedelta(minutes=2)).isoformat())
    ws.approvals.write_text(v.dumps(near) + "\n", encoding="utf-8")
    assert v.valid_shared_approval(near) and statuses(ws, tmp_path / "empty.sqlite3")["Zoll90"] == "human_verified"


def test_after_the_merge_another_clone_sees_the_entry_approved_with_no_command(checkout, tmp_path):
    """The approvals-only branch is merged in the shared repository; a second clone, with no
    verification database at all, reads the entry as human_verified."""
    ws, remote = checkout
    approve(ws, "Zoll90")
    share(ws)
    assert publish.pending(ws) == [LEDGER]
    branch = "cdlbib/test/2026-10-05-approvals"
    assert publish.deliver(ws, branch, "approvals", str(remote)) == [LEDGER]
    git(remote, "update-ref", "refs/heads/master", f"refs/heads/{branch}")   # the pull request is merged
    theirs = tmp_path / "their clone"
    git(tmp_path, "clone", "-q", str(remote), str(theirs))
    other = Workspace(theirs)
    assert not other.work.exists()
    found = {entry.key: entry.status for entry in api.entries(other)}
    assert found == {"Zoll90": "human_verified", "Rame72": "pending"}
    assert api.entry(other, "Zoll90").status == "human_verified"
    assert [entry.key for entry in api.review_queue(other, reference=str(other.bib), all_entries=True)] == ["Rame72"]
    assert not other.work.exists()                                           # reading created no database
    assert api.status(other).counts == {"human_verified": 1, "pending": 1}
    assert api.library_state(other).approvals == []


def test_the_pull_request_text_names_an_approval_of_an_unchanged_entry(checkout):
    ws, _ = checkout
    approve(ws, "Zoll90")
    start = git(ws.root, "rev-parse", "HEAD")
    assert api.approvals_note(ws, reference=str(ws.bib)) == ""               # no entry differs from the reference
    assert api._ledger_rows_since(ws, start) == []
    rows = share(ws)
    assert api._ledger_rows_since(ws, start) == rows
    assert api.approvals_note(ws, reference=str(ws.bib), ledgered=rows) == "\n\nApproved by @octocat: Zoll90"
    # Read from the ledger alone (no database), as on a branch that is sent again from another computer.
    assert api.approvals_note(ws, reference=str(ws.bib), database=str(ws.root / "none.sqlite3"),
                              ledgered=rows) == "\n\nApproved by @octocat: Zoll90"
    # Once the base holds the row, it is no longer something this pull request adds.
    git(ws.root, "add", LEDGER); git(ws.root, "commit", "-q", "-m", "an approval")
    assert api._ledger_rows_since(ws, git(ws.root, "rev-parse", "HEAD")) == []
    # A revoked approval is not named, whatever the ledger holds.
    revoke(ws, "Zoll90", ws.database)
    assert api.approvals_note(ws, reference=str(ws.bib), ledgered=rows) == ""


# --- the whole send, inside the tester's own fork only --------------------------------------------

def test_send_of_an_approval_alone_end_to_end_inside_my_own_fork(tmp_path, monkeypatch):
    """`api.approve` under the real login, then `api.send` with nothing else changed: the
    ledger row is the commit, the pull request names the approval, and a fresh clone of the
    branch reads the entry as human_verified. The pull request is opened inside the tester's
    own fork against the test base branch, and closed."""
    login, fork = my_fork()
    if login is None:
        pytest.skip(fork)
    publish.assert_safe_test_target(fork, TEST_BASE)                         # never ContextLab, never master
    work = tmp_path / "clone"
    subprocess.run(["gh", "repo", "clone", fork, str(work), "--", "--depth", "1", "-q"], check=True)
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    ws = Workspace(work)
    # The test base inside the fork: a two-entry library with no approvals ledger.
    ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n", encoding="utf-8")
    if ws.approvals.exists():
        ws.approvals.unlink()
    git(work, "add", "-A", "--", "cdl.bib", "verification")
    git(work, "commit", "-q", "-m", "cdlbib test base: please ignore")
    git(work, "push", "-q", "origin", f"HEAD:refs/heads/{TEST_BASE}", "--force")
    start = git(work, "rev-parse", "HEAD")
    database = tmp_path / "db.sqlite3"
    summary = f"cdlbib test {os.getpid()} approval: please ignore"
    branch = publish.branch_name(login, summary, datetime.date.today())
    options = dict(reference=str(ws.bib), citations=False, database=str(database), upstream=fork, base=TEST_BASE,
                   fork=fork, _test_inside_own_fork=True)
    url = None
    try:
        with pytest.raises(PublishRefused, match="no changes to cdl.bib or verification/"):
            api.send(ws, summary=summary, **options)
        api.approve(ws, "Zoll90", fingerprint(ws, "Zoll90"), REVIEW["source"], REVIEW["note"], database=str(database))
        assert api.library_state(ws).pending == [] and publish.pending(ws) == []
        waiting = api.approvals_to_send(ws, database=str(database))
        assert [(row["key"], row["human_review"]["github_login"]) for row in waiting] == [("Zoll90", login)]
        lines = []
        sent = api.send(ws, summary=summary, progress=lines.append, **options)
        url = sent.url
        assert f"approval of Zoll90 by @{login}: added to {LEDGER}" in lines
        assert sent.files == [LEDGER] and sent.approvals == ["Zoll90"] and sent.branch == branch
        assert git(work, "show", "--name-only", "--format=", "HEAD").split() == [LEDGER]
        assert git(work, "rev-list", "--count", f"{start}..HEAD") == "1" and git(work, "status", "--porcelain") == ""
        assert rows_of(ws) == waiting
        found = open_prs(fork, branch)
        assert [p["url"] for p in found] == [url] and found[0]["baseRefName"] == TEST_BASE
        assert found[0]["body"].endswith(f"\n\nApproved by @{login}: Zoll90")

        again = api.send(ws, **options)                                      # nothing new: the same pull request,
        assert again.url == url and again.files == [] and again.approvals == []
        assert open_prs(fork, branch)[0]["body"].endswith(f"\n\nApproved by @{login}: Zoll90")   # which still names it
        assert rows_of(ws) == waiting

        # Someone else: a fresh clone of the pushed branch, no database.
        theirs = tmp_path / "theirs"
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", branch, f"https://github.com/{fork}.git",
                        str(theirs)], check=True)
        assert {e.key: e.status for e in api.entries(Workspace(theirs))} == {"Zoll90": "human_verified", "Rame72": "pending"}
    finally:
        clean_up(work, url, branch)
