import os
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
    from cdlbib.verification import Cache, load_entries
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
