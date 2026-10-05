"""The Review and Check views by key presses: the queue, approve and revoke under the real
GitHub login of gh (skipped by name without one), and the checks with their live log.
Real app, real core, no mocks; the database is read afterwards."""
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="the terminal interface needs the optional package textual (pip install 'cdlbib[tui]')")

import conftest  # noqa: E402
import tui_support as T  # noqa: E402
from cdlbib import api  # noqa: E402
from test_complete_identify import library_entry  # noqa: E402
from test_desk import KAHA12, ZOLL90  # noqa: E402

GAME62 = library_entry("Game62")


def _token():
    """The token of the user's own gh login, read before any test substitutes HOME (gh keeps
    it in the user's keychain, which a substituted HOME hides). Never printed."""
    if not shutil.which("gh"):
        return None
    try:
        done = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


_TOKEN = _token()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    T.isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("CROSSREF_MAILTO", T.CONTACT)
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "gh-config"))     # gh's own settings: an empty folder
    yield
    conftest.no_real_library_touched()


@pytest.fixture
def reviewer(monkeypatch):
    """The real GitHub login, through gh as the core asks it."""
    if not _TOKEN:
        pytest.skip("no GitHub login for a real approval: `gh auth token` gave none (run: gh auth login)")
    monkeypatch.setenv("GH_TOKEN", _TOKEN)
    from cdlbib import identity
    from cdlbib.errors import IdentityUnavailable
    try:
        return identity.current()
    except IdentityUnavailable as exc:
        pytest.skip(f"no GitHub login for a real approval: {exc}")


@pytest.fixture
def ws(tmp_path):
    return T.library(tmp_path / "lib", ZOLL90, KAHA12)


def queue_keys(app):
    return [key.value for key in app.screen.query_one("#queue").rows]


def test_the_queue_lists_what_waits_and_says_why_the_changed_ones_cannot_be_told_offline(ws, monkeypatch):
    T.offline(monkeypatch)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f3")
            head = T.shown(app, "#review-head")
            assert "New or edited entries (compared with the GitHub master)" in head
            assert "Cannot download the reference bibliography" in head       # the core's message, as it is
            assert "t lists every entry waiting for review" in head and queue_keys(app) == []
            await T.press(pilot, "t")
            assert queue_keys(app) == ["Zoll90", "Kaha12"]
            assert "Every entry that is not verified or approved: 2" in T.shown(app, "#review-head")
            assert "never an approval" in T.shown(app, "#review-head")
            assert "@article{Zoll90," in T.shown(app, "#review-detail #t-entry")
            await T.press(pilot, "down", "d")
            assert "@book{Kaha12," in T.shown(app, "#review-detail #t-entry")
            assert "New, edited, or policy-invalidated entry" in T.shown(app, "#review-detail #t-issues")
    T.run(journey())


def test_approve_and_revoke_are_recorded_under_the_shown_login_after_a_confirmation(ws, reviewer):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f3", "t")
            await T.press(pilot, "a")                                   # gh is asked who is logged in
            assert type(app.screen).__name__ == "PromptScreen"
            page = T.shown(app, "#page")
            assert f"Approving as {reviewer.handle} (the GitHub login of gh; a reviewer's name cannot be typed)" in page
            assert "@article{Zoll90," in page and "Status now: pending" in page
            assert [box.id for box in app.screen.query("Input")] == ["field-source", "field-note"]   # no reviewer box
            await T.type_text(pilot, "the journal's page")
            await T.press(pilot, "enter")
            await T.type_text(pilot, "every field checked")
            await T.press(pilot, "enter")
            assert type(app.screen).__name__ == "ConfirmScreen"
            question = T.shown(app, "#question")
            assert f"Record your approval of Zoll90 as {reviewer.handle}?" in question
            assert "source: the journal's page" in question and "note: every field checked" in question
            await T.press(pilot, "n")                                   # not confirmed: nothing is recorded
            assert api.entry(ws, "Zoll90").status == "pending" and len(app.screen_stack) == 1

            await T.press(pilot, "a")
            await T.type_text(pilot, "the journal's page")
            await T.press(pilot, "enter")
            await T.type_text(pilot, "every field checked")
            await T.press(pilot, "enter", "y")
            stored = api.entry(ws, "Zoll90")
            assert stored.status == "human_verified"
            assert stored.human_review["reviewer"] == reviewer.handle and stored.human_review["github_id"] == reviewer.id
            assert (stored.human_review["source"], stored.human_review["note"]) == ("the journal's page", "every field checked")
            assert f"approved Zoll90 as {reviewer.handle}; status: human_verified" in app.log_lines
            assert queue_keys(app) == ["Kaha12"]                        # it left the queue

            await T.press(pilot, "f2")                                  # the Library view shows the approval
            assert "◆ human_verified" in T.screen_text(app)
            await T.press(pilot, "d", "d")
            evidence = T.shown(app, "#library-detail #t-evidence")
            assert "Human review" in evidence and f"reviewer: {reviewer.handle}" in evidence
            assert "source: the journal's page" in evidence

            await T.press(pilot, "v")                                   # revoke, from the Library view
            assert type(app.screen).__name__ == "PromptScreen"
            assert f"Revoking as {reviewer.handle}" in T.shown(app, "#page")
            assert [box.id for box in app.screen.query("Input")] == ["field-reason"]
            await T.type_text(pilot, "the volume was misread")
            await T.press(pilot, "enter")
            assert "Revoke the approval of Zoll90" in T.shown(app, "#question") and "reason: the volume was misread" in T.shown(app, "#question")
            await T.press(pilot, "y")
            revoked = api.entry(ws, "Zoll90")
            assert revoked.status == "needs_review" and revoked.human_review is None
            assert revoked.revoked_approval["reason"] == "the volume was misread"
            assert "revoked 1 approval record of Zoll90; status: needs_review" in app.log_lines
            assert "? needs_review" in T.screen_text(app)
            assert "Revoked approval" in T.shown(app, "#library-detail #t-evidence")
    T.run(journey())
    from cdlbib import verification
    ledger = Path(verification.REVOCATION_LEDGER)        # the test's own ledger (conftest), never the repository's
    assert "the volume was misread" in ledger.read_text(encoding="utf-8")


def test_without_a_login_approving_shows_how_to_log_in_and_records_nothing(ws):
    found = next(feature for feature in api.features(probe=("github",)) if feature.name == "gh login")
    if found.available:
        pytest.skip("a GitHub login is reachable even with an empty gh configuration, so the no-login screen cannot be shown")
    before = {path.name: path.read_bytes() for path in ws.root.rglob("*") if path.is_file()}

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "a")
            assert type(app.screen).__name__ == "TextScreen"
            page = T.shown(app, "#page")
            assert "An approval is recorded under your GitHub login, and none was found." in page
            assert found.how in page and "gh auth login" in T.screen_text(app)
            await T.press(pilot, "escape")
            assert len(app.screen_stack) == 1
    T.run(journey())
    assert api.entry(ws, "Zoll90").status == "pending"
    assert {name: data for name, data in before.items()} == {
        path.name: path.read_bytes() for path in ws.root.rglob("*") if path.is_file() and path.name in before}


def test_checking_the_selected_entry_runs_the_gate_and_shows_its_lines(tmp_path, monkeypatch):
    T.offline(monkeypatch)
    ws = T.library(tmp_path / "lib", GAME62, ZOLL90.replace("{27}", "{28}").replace("1053--1065", "1053-1065"))
    T.seed_responses(ws, T.COMPLETION)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            assert "· pending 2" in T.screen_text(app)
            await T.press(pilot, "c")                                   # the selected entry: Game62
            assert "citations: 1 of 1 chosen entries verified; network requests: 0" in app.log_lines   # the live log
            assert "✓ metadata_verified 1" in T.screen_text(app)
            await T.press(pilot, "f5")
            result = T.shown(app, "#check-result")
            assert "Checked: Game62" in result and "Result: passed" in result and "Game62: ✓ metadata_verified" in result
            assert "none on the chosen entries (the other entries were not checked)" in result
            assert "Selected in the Library view: Game62" in T.shown(app, "#check-head")

            await T.press(pilot, "f2", "down", "f5", "c")                # the other entry: wrong volume, pages not in house format
            result = T.shown(app, "#check-result")
            assert "Checked: Zoll90" in result and "Result: not passed" in result
            assert "Zoll90: ? needs_review" in result and "pages: the formatter writes 1053--1065" in result
            assert "citations: 0 of 1 chosen entries verified" in "\n".join(app.log_lines)

            await T.press(pilot, "m")                                   # the format check of the library
            result = T.shown(app, "#check-result")
            assert "Format check of the library" in result and "Zoll90" in result and "pages: the formatter writes 1053--1065" in result

            await T.press(pilot, "g")                                   # the changed entries: GitHub cannot be asked here
            result = T.shown(app, "#check-result")
            assert "check the changed entries: the check could not be done." in result
            assert "Cannot download the reference bibliography" in result
    T.run(journey())
    assert api.entry(ws, "Game62").status == "metadata_verified" and api.entry(ws, "Zoll90").status == "needs_review"
