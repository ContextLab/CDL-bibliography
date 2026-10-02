"""Revoking a human approval (2026-09-29): audited, fingerprint-bound, never restored.

Fixtures are frozen real records: the text of Palm78, NastEtal20 and Mink15 at commits
7f3eead (Mink15 with {Parkinson's}) and 4cdc644 (braces dropped), and their real
2026-09-25 approval rows from the 7f3eead baseline. NastEtal20 is the negative control:
its approval is never revoked and must survive every step.
"""
import gzip
import json
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cdlbib import verification as v  # noqa: E402
from cdlbib.verification_cli import app  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "revocation"
OLD_BIB = FIX / "entries-7f3eead.bib"
NEW_BIB = FIX / "entries-4cdc644.bib"
OLD_SNAPSHOT = FIX / "baseline-7f3eead-3-approvals.jsonl.gz"
PALM_FP = "v2:c2cb1560ba3267d42b4af49e7c6a285368e2ecd97a7c3d7a20c69aed034882d1"
MINK_OLD_FP = "v2:0c83ad54efbd8e0b9d5861cb788114a53c60bde8fc5ad1dcef171b9dbbc5c53b"
REASON = "Not directly approved by the user (attribution audit 2026-09-29)"
BY = "Jeremy Manning (decision); run by Claude"


def statuses(bib, database):
    cache = v.Cache(database)
    try:
        return {k: r["status"] for k, r in v.current_results(str(bib), cache).items()}
    finally:
        cache.close()


def restore(bib, database, snapshot):
    cache = v.Cache(database)
    try:
        return v.import_snapshot(str(bib), cache, str(snapshot))
    finally:
        cache.close()


def export(bib, database, snapshot):
    cache = v.Cache(database)
    try:
        v.export_snapshot(str(bib), cache, str(snapshot))
    finally:
        cache.close()


def revoke(bib, database, key, *fingerprints):
    cache = v.Cache(str(database), ledger=v.REVOCATION_LEDGER)
    try:
        return v.record_revocation(cache, str(bib), key, REASON, BY, fingerprints=list(fingerprints) or None,
                                   ledger=v.REVOCATION_LEDGER)
    finally:
        cache.close()


def approve(bib, database, key, fingerprint, human_review):
    cache = v.Cache(str(database), ledger=v.REVOCATION_LEDGER)
    try:
        return v.record_approval(cache, str(bib), key, fingerprint, human_review)
    finally:
        cache.close()


@pytest.fixture
def library(tmp_path):
    bib = tmp_path / "cdl.bib"
    shutil.copy(OLD_BIB, bib)
    database = tmp_path / "live.sqlite3"
    assert restore(bib, database, OLD_SNAPSHOT) == 3
    assert set(statuses(bib, database).values()) == {"human_verified"}
    return bib, database


def test_revoke_records_audit_row_and_leaves_needs_review(library):
    bib, database = library
    records, _ = revoke(bib, database, "Palm78")
    assert len(records) == 1
    assert statuses(bib, database) == {"Palm78": "needs_review", "NastEtal20": "human_verified",
                                       "Mink15": "human_verified"}
    [row] = v.read_revocation_ledger()
    assert row["key"] == "Palm78" and row["fingerprint"] == PALM_FP
    assert row["revoked_by"] == BY and row["reason"] == REASON and row["revoked_at"]
    assert row["approval"]["reviewer"] == "Jeremy Manning"
    assert row["approval_checked_at"] == "2026-09-25T19:06:55.934795+00:00"
    assert row["approval_digest"] == v.approval_digest(row["approval"])
    cache = v.Cache(database)
    try:
        current = v.current_results(str(bib), cache)["Palm78"]
    finally:
        cache.close()
    assert "human_review" not in current
    assert current["revoked_approval"]["human_review"] == row["approval"]
    assert current["issues"][0].startswith("Human approval revoked")
    # Revoking again adds nothing.
    assert revoke(bib, database, "Palm78")[0] == []
    assert len(v.read_revocation_ledger()) == 1


def test_snapshot_restore_never_resurrects_a_revoked_approval(library, tmp_path):
    bib, database = library
    assert len(revoke(bib, database, "Palm78")[0]) == 1
    live = statuses(bib, database)
    # New snapshot into an empty database equals the live status, revocation included.
    snapshot = tmp_path / "baseline.jsonl.gz"
    export(bib, database, snapshot)
    header = json.loads(gzip.open(snapshot, "rt").readline())
    assert [r["key"] for r in header["revocations"]] == ["Palm78"]
    assert statuses(bib, tmp_path / "empty1.sqlite3") == {k: "pending" for k in live}
    restore(bib, tmp_path / "empty1.sqlite3", snapshot)
    assert statuses(bib, tmp_path / "empty1.sqlite3") == live
    # The OLD snapshot (approval still present) into an empty database: stays revoked via the ledger.
    assert restore(bib, tmp_path / "empty2.sqlite3", OLD_SNAPSHOT) == 3
    assert statuses(bib, tmp_path / "empty2.sqlite3") == live
    # ...and into the live database: nothing restored, still revoked.
    assert restore(bib, database, OLD_SNAPSHOT) == 0
    assert statuses(bib, database) == live


def test_snapshot_carries_revocation_without_the_ledger(library, tmp_path, monkeypatch):
    bib, database = library
    assert len(revoke(bib, database, "Palm78")[0]) == 1
    snapshot = tmp_path / "baseline.jsonl.gz"
    export(bib, database, snapshot)
    monkeypatch.setattr(v, "REVOCATION_LEDGER", tmp_path / "elsewhere.jsonl")
    fresh = tmp_path / "fresh.sqlite3"
    restore(bib, fresh, snapshot)
    # The fresh database learned the revocation from the snapshot header, so a later
    # restore of the old snapshot into it cannot bring the approval back either.
    assert restore(bib, fresh, OLD_SNAPSHOT) == 0
    assert statuses(bib, fresh)["Palm78"] == "needs_review"
    assert statuses(bib, fresh)["NastEtal20"] == "human_verified"


def test_lapsed_approval_on_old_fingerprint_is_revoked_too(tmp_path):
    bib = tmp_path / "cdl.bib"
    shutil.copy(OLD_BIB, bib)
    database = tmp_path / "live.sqlite3"
    restore(bib, database, OLD_SNAPSHOT)
    shutil.copy(NEW_BIB, bib)  # the braces batch: Mink15's approval lapses
    assert statuses(bib, database)["Mink15"] == "pending"
    assert len(revoke(bib, database, "Mink15", MINK_OLD_FP)[0]) == 1
    [row] = v.read_revocation_ledger()
    assert row["fingerprint"] == MINK_OLD_FP
    # If the text ever reverted to the approved form, an old restore still cannot approve it.
    shutil.copy(OLD_BIB, bib)
    assert statuses(bib, database)["Mink15"] == "needs_review"
    assert restore(bib, tmp_path / "empty.sqlite3", OLD_SNAPSHOT) == 3
    assert statuses(bib, tmp_path / "empty.sqlite3") == {
        "Palm78": "human_verified", "NastEtal20": "human_verified", "Mink15": "needs_review"}


def test_reapproval_with_new_note_survives_but_the_revoked_one_cannot_be_replayed(library):
    bib, database = library
    assert len(revoke(bib, database, "Palm78")[0]) == 1
    [row] = v.read_revocation_ledger()
    old = row["approval"]
    base = {"reviewer": old["reviewer"], "source": old["source"]}
    with pytest.raises(ValueError, match="revoked"):
        approve(bib, database, "Palm78", PALM_FP, dict(base, note=old["note"]))
    assert statuses(bib, database)["Palm78"] == "needs_review"
    approve(bib, database, "Palm78", PALM_FP, dict(base, note="Checked the 1978 Erlbaum printing myself"))
    assert statuses(bib, database)["Palm78"] == "human_verified"


def test_revoke_refuses_an_entry_without_a_human_approval(library):
    bib, database = library
    with pytest.raises(ValueError, match="No human approval"):
        revoke(bib, database, "NastEtal20", "v2:not-its-fingerprint")
    assert v.read_revocation_ledger() == []
    cache = v.Cache(str(database), ledger=v.REVOCATION_LEDGER)
    try:
        with pytest.raises(ValueError, match="A revocation needs --reason and --by"):
            v.record_revocation(cache, str(bib), "Palm78", " ", BY, ledger=v.REVOCATION_LEDGER)
    finally:
        cache.close()
    assert statuses(bib, database)["Palm78"] == "human_verified"


def test_malformed_ledger_fails_closed(library):
    bib, database = library
    Path(v.REVOCATION_LEDGER).write_text('{"key": "Palm78"}\n')
    with pytest.raises(ValueError, match="Invalid revocation record"):
        statuses(bib, database)


def test_ledger_copy_edited_after_revocation_is_still_revoked(library):
    """Commit 856d637 renamed folders inside the approval notes of eleven ledger rows, so
    their approval text no longer hashed to the recorded digest, and replaying the approval
    as the ledger shows it was accepted as new (ScotEtal07, 2026-09-30). A revocation now
    revokes both its recorded digest and the digest of the approval text it carries."""
    bib, database = library
    assert len(revoke(bib, database, "Palm78")[0]) == 1
    [row] = v.read_revocation_ledger()
    original = dict(row["approval"])
    edited = dict(original, note=original["note"] + " (folder renamed: apply-2026-09-28 -> apply-2026-09-25e)")
    Path(v.REVOCATION_LEDGER).write_text(v.dumps(dict(row, approval=edited)) + "\n")
    [row] = v.read_revocation_ledger()
    assert v.approval_digest(row["approval"]) != row["approval_digest"]
    assert v.revoked_digests(row) == {row["approval_digest"], v.approval_digest(edited)}
    base = {"reviewer": original["reviewer"], "source": original["source"]}
    for note in (edited["note"], original["note"]):  # the ledger's text and the text approved
        with pytest.raises(ValueError, match="revoked"):
            approve(bib, database, "Palm78", PALM_FP, dict(base, note=note))
        assert statuses(bib, database)["Palm78"] == "needs_review"
    # A stored row carrying the ledger's text is revoked even when recorded after the revocation.
    later = {"status": "human_verified", "human_review": edited, "checked_at": "2099-01-01T00:00:00+00:00"}
    assert v.revocation_matches(row, PALM_FP, later)
    # Negative controls: a genuinely new review stands and does not carry the revocation notice;
    # other approvals are untouched.
    approve(bib, database, "Palm78", PALM_FP, dict(base, note="Checked the 1978 Erlbaum printing myself"))
    cache = v.Cache(database)
    try:
        now = v.current_results(str(bib), cache)
    finally:
        cache.close()
    assert now["Palm78"]["status"] == "human_verified"
    assert not any(str(i).startswith("Human approval revoked") for i in now["Palm78"].get("issues", []))
    assert not v.revocation_matches(row, PALM_FP, now["Palm78"])
    assert now["NastEtal20"]["status"] == now["Mink15"]["status"] == "human_verified"
