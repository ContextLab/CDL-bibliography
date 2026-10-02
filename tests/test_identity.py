import shutil
import subprocess

import pytest

from cdlbib import api, identity
from cdlbib.errors import IdentityUnavailable
from cdlbib.workspace import Workspace

from test_machinery_2026_09_25 import ZOLL90


def gh_user():
    """The real login, or None when no user is logged in (e.g. GitHub Actions' app token)."""
    if not shutil.which("gh"):
        return None
    run = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 and run.stdout.strip() else None


def test_current_matches_gh_or_refuses():
    login = gh_user()
    if login is None:
        with pytest.raises(IdentityUnavailable, match="gh auth login"):
            identity.current()
    else:
        me = identity.current()
        assert me.login == login and isinstance(me.id, int) and me.id > 0 and me.handle == "@" + login


def test_no_gh_on_path_refuses(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))          # a real, empty PATH: gh cannot be found
    with pytest.raises(IdentityUnavailable, match="gh auth login"):
        identity.current()


def test_logged_out_gh_refuses(monkeypatch, tmp_path):
    if not shutil.which("gh"):
        pytest.skip("gh is not installed here")
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path))  # a real, empty gh config: nobody is logged in
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(IdentityUnavailable, match="gh auth login"):
        identity.current()


def test_approve_without_identity_writes_nothing(monkeypatch, tmp_path):
    bib = tmp_path / "lib.bib"
    bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    ws = Workspace.for_bib(bib)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(IdentityUnavailable):
        api.approve(ws, "Zoll90", fingerprint="x", source="https://doi.org/10.1002/tea.3660271011", note="checked")
    assert not ws.database.exists()


def test_approve_records_the_github_login(tmp_path):
    login = gh_user()
    if login is None:
        pytest.skip("no GitHub user is logged in (expected in CI); approval needs a real login")
    from cdlbib.verification import load_entries
    bib = tmp_path / "lib.bib"
    bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    ws = Workspace.for_bib(bib)
    fingerprint = load_entries(str(bib))["Zoll90"]["fingerprint"]
    stored = api.approve(ws, "Zoll90", fingerprint=fingerprint,
                         source="https://doi.org/10.1002/tea.3660271011", note="all fields checked against the DOI record")
    assert stored["status"] == "human_verified"
    assert stored["human_review"]["reviewer"] == "@" + login
    assert stored["human_review"]["github_login"] == login and stored["human_review"]["github_id"] > 0
    assert api.status(ws, require_human=True).ok


def test_new_style_review_survives_snapshot_round_trip(tmp_path):
    login = gh_user()
    if login is None:
        pytest.skip("no GitHub user is logged in (expected in CI)")
    from cdlbib.verification import Cache, export_snapshot, import_snapshot, load_entries
    bib = tmp_path / "lib.bib"; bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    ws = Workspace.for_bib(bib)
    fp = load_entries(str(bib))["Zoll90"]["fingerprint"]
    api.approve(ws, "Zoll90", fingerprint=fp, source="https://doi.org/10.1002/tea.3660271011", note="checked")
    snap = tmp_path / "snap.jsonl.gz"
    cache = Cache(str(ws.database)); export_snapshot(str(bib), cache, str(snap)); cache.close()
    fresh = Cache(str(tmp_path / "fresh.sqlite3")); import_snapshot(str(bib), fresh, str(snap)); fresh.close()
    assert api.status(ws, database=str(tmp_path / "fresh.sqlite3"), require_human=True).ok


def fresh_library(tmp_path):
    from cdlbib.verification import load_entries
    bib = tmp_path / "lib.bib"
    bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    return bib, load_entries(str(bib))["Zoll90"]["fingerprint"]


GOOD = {"reviewer": "@someone", "source": "https://doi.org/10.1002/tea.3660271011", "note": "checked"}


@pytest.mark.parametrize("field, value", [("source", None), ("note", None), ("note", 5), ("reviewer", None),
                                          ("source", "  "), ("note", ""), ("reviewer", "\t")])
def test_record_approval_refuses_a_missing_or_non_text_field_and_stores_nothing(tmp_path, field, value):
    from cdlbib.verification import Cache, current_results, record_approval
    bib, fp = fresh_library(tmp_path)
    cache = Cache(str(tmp_path / "db.sqlite3"))
    try:
        with pytest.raises(ValueError, match="Human reviewer, source, and review notes are required"):
            record_approval(cache, str(bib), "Zoll90", fp, dict(GOOD, **{field: value}))
        assert cache.db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0
        assert current_results(str(bib), cache)["Zoll90"]["status"] != "human_verified"
    finally:
        cache.close()


def test_api_approve_with_no_source_is_a_cdlbib_error(tmp_path):
    from cdlbib.errors import ApprovalRefused
    if gh_user() is None:
        pytest.skip("no GitHub user is logged in (expected in CI); approval needs a real login")
    bib, fp = fresh_library(tmp_path)
    ws = Workspace.for_bib(bib)
    with pytest.raises(ApprovalRefused, match="required"):
        api.approve(ws, "Zoll90", fingerprint=fp, source=None, note="n")


def test_cli_without_a_login_refuses_cleanly_and_creates_no_database(monkeypatch, tmp_path):
    from typer.testing import CliRunner
    from cdlbib.verification_cli import app
    bib, fp = fresh_library(tmp_path)
    database = tmp_path / "db.sqlite3"
    monkeypatch.setenv("PATH", str(tmp_path))  # a real, empty PATH: gh cannot be found
    for args in (["approve", "Zoll90", "--fingerprint", fp, "--source", "s", "--note", "n"],
                 ["revoke", "Zoll90", "--reason", "r"]):
        result = CliRunner().invoke(app, args + ["--fname", str(bib), "--database", str(database)])
        assert result.exit_code == 1, result.output
        assert "gh auth login" in result.output
        assert "Traceback" not in result.output and result.exception is None or isinstance(result.exception, SystemExit)
    assert not database.exists()


def test_cli_approve_with_a_stale_fingerprint_exits_2(tmp_path):
    from typer.testing import CliRunner
    from cdlbib.verification_cli import app
    if gh_user() is None:
        pytest.skip("no GitHub user is logged in (expected in CI); approval needs a real login")
    bib, _ = fresh_library(tmp_path)
    result = CliRunner().invoke(app, ["approve", "Zoll90", "--fingerprint", "stale", "--source", "s", "--note", "n",
                                      "--fname", str(bib), "--database", str(tmp_path / "db.sqlite3")])
    assert result.exit_code == 2
    assert "Entry changed since review; approval rejected" in result.output
