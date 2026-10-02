"""revoke resolves one ledger per run (--ledger, else a patched verification.REVOCATION_LEDGER,
else the workspace of the bibliography) and never assigns the module global."""
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cdlbib import verification as v
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


def run(bib, database, *extra):
    return CliRunner().invoke(app, ["revoke", "Palm78", "--fname", str(bib), "--database", str(database),
                                    "--reason", REASON, "--by", BY, *extra])


def statuses(bib, database, ledger):
    cache = v.Cache(database, ledger=ledger)
    try:
        return {k: r["status"] for k, r in v.current_results(str(bib), cache).items()}
    finally:
        cache.close()


def test_revoke_outside_the_library_uses_the_bibs_workspace(setup, monkeypatch):
    bib, database = setup
    monkeypatch.setattr(v, "REVOCATION_LEDGER", None)  # no patched ledger: the workspace decides
    result = run(bib, database)
    assert result.exit_code == 0, result.output
    ledger = bib.parent / "verification" / "revocations.jsonl"
    [row] = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert row["key"] == "Palm78"
    assert "every matching" not in result.output and "needs_review" in result.output
    assert statuses(bib, database, ledger)["Palm78"] == "needs_review"
    assert v.REVOCATION_LEDGER is None  # module global untouched


def test_explicit_ledger_is_written_and_the_global_is_unchanged(setup, tmp_path, monkeypatch):
    bib, database = setup
    patched = tmp_path / "patched.jsonl"
    monkeypatch.setattr(v, "REVOCATION_LEDGER", patched)
    mine = tmp_path / "chosen ledger.jsonl"
    result = run(bib, database, "--ledger", str(mine))
    assert result.exit_code == 0, result.output
    assert [json.loads(l)["key"] for l in mine.read_text(encoding="utf-8").splitlines()] == ["Palm78"]
    assert not patched.exists()
    assert v.REVOCATION_LEDGER == patched
    assert statuses(bib, database, mine)["Palm78"] == "needs_review"


def test_a_patched_ledger_beats_the_workspace(setup, tmp_path, monkeypatch):
    bib, database = setup
    patched = tmp_path / "patched.jsonl"
    monkeypatch.setattr(v, "REVOCATION_LEDGER", patched)
    assert run(bib, database).exit_code == 0
    assert patched.exists() and not (bib.parent / "verification").exists()
