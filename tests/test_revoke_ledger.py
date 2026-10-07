"""revoke resolves one ledger per run (--ledger, else a patched verification.REVOCATION_LEDGER,
else the workspace of the bibliography) and never assigns the module global."""
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cdlbib import verification as v
from cdlbib.verification import revocation_ledger
from cdlbib.verification_cli import app

FIX = Path(__file__).resolve().parent / "fixtures" / "revocation"
REASON = "Not directly approved by the user (attribution audit 2026-09-29)"
BY = "Jeremy Manning (decision); run by Claude"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    lib = tmp_path / "library A"
    lib.mkdir()
    bib = lib / "cdl.bib"
    shutil.copy(FIX / "entries-7f3eead.bib", bib)
    database = tmp_path / "live.sqlite3"
    cache = v.Cache(database)
    try:
        assert v.import_snapshot(str(bib), cache, str(FIX / "baseline-7f3eead-3-approvals.jsonl.gz")) == 3
    finally:
        cache.close()
    elsewhere = tmp_path / "unrelated B"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return bib, database


def run(bib, database, ledger=None):
    """The command's own steps without the login: resolve the ledger once, then record the
    revocation. Returns what record_revocation returned: (records written, entry status)."""
    path = revocation_ledger(str(bib), ledger)
    cache = v.Cache(database, ledger=path)
    try:
        return v.record_revocation(cache, str(bib), "Palm78", REASON, BY, ledger=path)
    finally:
        cache.close()


def statuses(bib, database, ledger):
    cache = v.Cache(database, ledger=ledger)
    try:
        return {k: r["status"] for k, r in v.current_results(str(bib), cache).items()}
    finally:
        cache.close()


def test_revoke_outside_the_library_uses_the_bibs_workspace(setup, monkeypatch):
    bib, database = setup
    monkeypatch.setattr(v, "REVOCATION_LEDGER", None)  # no patched ledger: the workspace decides
    records, status = run(bib, database)
    assert len(records) == 1 and status == "needs_review"
    ledger = bib.parent / "verification" / "revocations.jsonl"
    [row] = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert row["key"] == "Palm78"
    assert statuses(bib, database, ledger)["Palm78"] == "needs_review"
    assert v.REVOCATION_LEDGER is None  # module global untouched


def test_explicit_ledger_is_written_and_the_global_is_unchanged(setup, tmp_path, monkeypatch):
    bib, database = setup
    patched = tmp_path / "patched.jsonl"
    monkeypatch.setattr(v, "REVOCATION_LEDGER", patched)
    mine = tmp_path / "chosen ledger.jsonl"
    records, status = run(bib, database, str(mine))
    assert len(records) == 1 and status == "needs_review"
    assert [json.loads(l)["key"] for l in mine.read_text(encoding="utf-8").splitlines()] == ["Palm78"]
    assert not patched.exists()
    assert v.REVOCATION_LEDGER == patched
    assert statuses(bib, database, mine)["Palm78"] == "needs_review"


def test_a_patched_ledger_beats_the_workspace(setup, tmp_path, monkeypatch):
    bib, database = setup
    patched = tmp_path / "patched.jsonl"
    monkeypatch.setattr(v, "REVOCATION_LEDGER", patched)
    records, status = run(bib, database)
    assert len(records) == 1 and status == "needs_review"
    assert patched.exists() and not (bib.parent / "verification").exists()


def test_cli_revoke_end_to_end_records_the_github_login(setup, monkeypatch):
    from test_identity import gh_user
    login = gh_user()
    if login is None:
        pytest.skip("no GitHub user is logged in (expected in CI); revoking needs a real login")
    bib, database = setup
    monkeypatch.setattr(v, "REVOCATION_LEDGER", None)  # the workspace of the bib decides; cwd is elsewhere
    result = CliRunner().invoke(app, ["revoke", "Palm78", "--fname", str(bib), "--database", str(database),
                                      "--reason", REASON])
    assert result.exit_code == 0, result.output
    ledger = bib.parent / "verification" / "revocations.jsonl"
    [row] = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert row["key"] == "Palm78" and row["revoked_by"] == "@" + login
    assert statuses(bib, database, ledger)["Palm78"] == "needs_review"


@pytest.mark.parametrize("reason, by", [(None, BY), (5, BY), (REASON, None), (" ", BY), (REASON, " ")])
def test_record_revocation_refuses_a_non_text_reason_or_by_and_writes_nothing(setup, tmp_path, reason, by):
    bib, database = setup
    ledger = tmp_path / "ledger.jsonl"
    cache = v.Cache(database, ledger=ledger)
    try:
        with pytest.raises(ValueError, match=r"A revocation needs a reason \(--reason\) and a GitHub login \(gh auth login\)"):
            v.record_revocation(cache, str(bib), "Palm78", reason, by, ledger=ledger)
        assert cache.revocations() == []
    finally:
        cache.close()
    assert not ledger.exists()
    assert statuses(bib, database, ledger)["Palm78"] == "human_verified"


def test_api_revoke_with_no_reason_is_a_cdlbib_error(setup, tmp_path):
    from test_identity import gh_user
    from cdlbib import api
    from cdlbib.errors import ApprovalRefused
    from cdlbib.workspace import Workspace
    if gh_user() is None:
        pytest.skip("no GitHub user is logged in (expected in CI); revoking needs a real login")
    bib, database = setup
    with pytest.raises(ApprovalRefused, match="A revocation needs"):
        api.revoke(Workspace.for_bib(bib), "Palm78", None, ledger=str(tmp_path / "l.jsonl"), database=str(database))
    assert not (tmp_path / "l.jsonl").exists()
