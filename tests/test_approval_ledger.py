"""The approvals ledger (verification/approvals.jsonl): human approvals that travel with a send.

Real files, real SQLite databases and real git repositories in temporary folders; the real
gh where a login is needed (those tests skip, with the reason, where nobody is logged in or
the user has no fork). An approval "of another user" is one stored in a second database. No
mocks.
"""
import datetime
import json
import os
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
    monkeypatch.delenv(v.APPROVAL_LEDGER_ENV, raising=False)
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


def test_the_environment_can_name_the_ledger_that_is_read(tmp_path, monkeypatch):
    """What verification/check_ci.py does with the base revision's copy."""
    ws = library(tmp_path / "lib")
    approve(ws, "Zoll90")
    share(ws)
    other = tmp_path / "other.sqlite3"
    assert statuses(ws, other)["Zoll90"] == "human_verified"
    base = tmp_path / "base-approvals.jsonl"
    base.write_bytes(b"")
    monkeypatch.setenv(v.APPROVAL_LEDGER_ENV, str(base))
    assert statuses(ws, other)["Zoll90"] == "pending"                        # the library's own rows are not read
    base.write_bytes(ws.approvals.read_bytes())
    assert statuses(ws, other)["Zoll90"] == "human_verified"


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
    later = (datetime.datetime.fromisoformat(records[0]["revoked_at"]) + datetime.timedelta(days=1)).isoformat()
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
    later = (datetime.datetime.fromisoformat(records[0]["revoked_at"]) + datetime.timedelta(days=1)).isoformat()
    with open(ws.approvals, "a", encoding="utf-8") as stream:
        stream.write(v.dumps(dict(row, approval_digest="f" * 64, approved_at=later)) + "\n")
    rows, problems = v.scan_approval_ledger(ws.approvals)
    assert rows == [row] and "line 2 ignored: approval_digest is not the digest of human_review" in problems[0]
    assert statuses(ws, tmp_path / "other.sqlite3")["Zoll90"] != "human_verified"


# --- which copy of the ledger a gate reads -----------------------------------------------------------

def test_a_row_typed_into_the_working_tree_approves_nothing_in_the_gate(tmp_path, monkeypatch):
    """An entry is edited and a valid row approving the new text is typed into
    verification/approvals.jsonl; no database holds any approval. Read as the library's own
    ledger (status, the views) the row approves the entry. The gate of `verify` and `send`
    compares with a reference and reads the reference's ledger, here an empty one: the entry
    is not approved there, so the gate goes to look it up (the network is closed, so the
    look-up fails) and does not pass."""
    ws = library(tmp_path / "lib")
    base = tmp_path / "base.bib"
    base.write_bytes(ws.bib.read_bytes())
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8").replace("Volume = {27}", "Volume = {28}"), encoding="utf-8")
    row = {"key": "Zoll90", "fingerprint": fingerprint(ws, "Zoll90"), "human_review": REVIEW,
           "approval_digest": v.approval_digest(REVIEW), "approved_at": v.now(), "policy": v.POLICY}
    v.append_approvals(ws.approvals, [row])
    assert statuses(ws, ws.database)["Zoll90"] == "human_verified"           # the checkout's own ledger, outside a gate
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")                       # nothing listens there
    monkeypatch.setenv("NO_PROXY", ""); monkeypatch.setenv("no_proxy", "")
    lines = []
    try:
        passed = api.check_citations(ws, None, reference=str(base), mailto="valid@example.org", progress=lines.append).ok
    except GateFailed as refused:
        passed, lines = False, lines + [str(refused)]
    assert not passed, lines
    assert (ws.work / "reference-approvals.jsonl").read_bytes() == b""
    assert not any("human_verified=1" in line for line in lines)
    # With the same row in the reference's ledger the gate reads it: this is the base-branch case.
    monkeypatch.setenv(v.APPROVAL_LEDGER_ENV, str(ws.approvals))
    check = api.check_citations(ws, None, reference=str(base), mailto="valid@example.org")
    assert check.ok and check.citations.checked["Zoll90"]["status"] == "human_verified"


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
    assert not ws.approvals.exists()                                         # looking adds nothing to the ledger
    share(ws)
    found = api.library_state(ws)
    assert found.approvals == [] and found.pending == [LEDGER]
    assert api.as_data(found)["approvals"] == []
    plain = library(ws.root.parent / "no checkout")                          # not a git checkout: nothing can be sent
    approve(plain, "Zoll90")
    assert api.library_state(plain).approvals is None and api.library_state(plain).pending is None


def test_a_send_of_approvals_alone_is_not_refused_as_nothing_to_send(checkout, monkeypatch, tmp_path):
    """Nothing in cdl.bib or verification/ has changed; one approval waits. The send goes past
    "nothing to send" and past the gate, and stops where it asks who is logged in (nobody is,
    here): the row it had added is taken out again and the checkout is as it was."""
    ws, _ = checkout
    with pytest.raises(PublishRefused, match="no changes to cdl.bib or verification/"):
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE)
    approve(ws, "Zoll90")
    assert publish.pending(ws) == []
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "empty-gh"))
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    before, lines = state(ws.root), []
    with pytest.raises(IdentityUnavailable):
        api.send(ws, reference=str(ws.bib), citations=False, upstream=NOWHERE, base=TEST_BASE, progress=lines.append)
    assert f"approval of Zoll90 by @octocat: added to {LEDGER}" in lines
    assert "checks passed; generating commit message..." in lines           # the gate ran with the row in place
    assert lines[-1] == f"not sent: {LEDGER} is as it was before (the approvals stay in the local database)"
    assert state(ws.root) == before and not ws.approvals.exists()
    assert [row["key"] for row in api.approvals_to_send(ws)] == ["Zoll90"]   # it still waits


def test_a_send_the_gate_refuses_leaves_the_ledger_byte_for_byte(checkout):
    """An earlier row is committed; a second approval waits; the edit to cdl.bib fails the
    format check. After the refusal the ledger holds the committed row and nothing else."""
    ws, _ = checkout
    approve(ws, "Rame72", note="Checked the volume in print.")
    share(ws)
    git(ws.root, "add", LEDGER); git(ws.root, "commit", "-q", "-m", "an approval")
    committed = ws.approvals.read_bytes()
    approve(ws, "Zoll90")
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + "\n" + BAD, encoding="utf-8")
    assert [row["key"] for row in api.approvals_to_send(ws)] == ["Zoll90"]   # the edit is to another entry
    before, lines = state(ws.root), []
    with pytest.raises(GateFailed) as refused:
        api.send(ws, summary="bad", reference=str(ws.bib), upstream=NOWHERE, base=TEST_BASE, progress=lines.append)
    assert refused.value.check is not None and not refused.value.check.ok
    assert lines[0] == f"approval of Zoll90 by @octocat: added to {LEDGER}"
    assert lines[-1].startswith(f"not sent: {LEDGER} is as it was before")
    assert state(ws.root) == before and ws.approvals.read_bytes() == committed
    assert git(ws.root, "status", "--porcelain", "--", "verification") == ""


def test_rows_stay_when_something_else_changed_the_ledger_or_a_commit_holds_them(checkout, tmp_path):
    ws, remote = checkout
    approve(ws, "Zoll90")
    rows = api.approvals_to_send(ws)
    take_out = api._ledger_approvals(ws, rows)
    written = ws.approvals.read_bytes()
    with open(ws.approvals, "ab") as stream:                                 # another writer, meanwhile
        stream.write(b"\n")
    take_out()
    assert ws.approvals.read_bytes() == written + b"\n"                      # not ours alone any more: left as it is
    ws.approvals.unlink()

    take_out = api._ledger_approvals(ws, rows)
    branch = "cdlbib/test/2026-10-05-approvals"
    with pytest.raises(PublishRefused, match=f"committed on branch {branch}"):
        publish.deliver(ws, branch, "approvals", str(tmp_path / "no-such-remote.git"))
    take_out()                                                               # committed: the rows are the branch's now
    assert ws.approvals.read_bytes() == written and git(ws.root, "status", "--porcelain") == ""
    assert git(ws.root, "show", "--name-only", "--format=", "HEAD").split() == [LEDGER]
    assert publish.deliver(ws, branch, "approvals", str(remote)) == []       # the resumed send: the push alone
    assert git(remote, "rev-parse", branch) == git(ws.root, "rev-parse", "HEAD")


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
