"""The terminal interface's Library view, driven by key presses: browse, search, the detail
tabs with the evidence, the theme switch, the help, and a library of 6,481 entries.

The real app over the real core (tests/tui_support.py); nothing is mocked. The statuses on
screen are the verifier's own: the gate is run for real over the suite's saved responses.
"""
import re
import shutil
import time
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="the terminal interface needs the optional package textual (pip install 'cdlbib[tui]')")

import conftest  # noqa: E402
import tui_support as T  # noqa: E402
from cdlbib import api, theme  # noqa: E402
from cdlbib.verification import Cache, load_entries, record_approval, record_revocation  # noqa: E402
from cdlbib.workspace import Workspace  # noqa: E402
from test_complete_identify import library_entry  # noqa: E402
from test_desk import GLOC08, KAHA12, TENE11, ZOLL90  # noqa: E402

GAME62 = library_entry("Game62")
WRONG = GAME62.replace("Volume = {63}", "Volume = {36}")
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/cdlbib/tui"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    T.isolate(monkeypatch, tmp_path)
    T.offline(monkeypatch)
    yield
    conftest.no_real_library_touched()


@pytest.fixture
def ws(tmp_path):
    """Five entries; the gate has checked Game62 (its volume is wrong: needs_review, with the
    source's values as evidence) and Kaha12 holds an approval that was then revoked."""
    ws = T.library(tmp_path / "lib", ZOLL90, KAHA12, GLOC08, TENE11, WRONG)
    T.seed_responses(ws, T.COMPLETION)
    check = api.check_keys(ws, ["Game62"], mailto=T.CONTACT)
    assert check.citations.checked["Game62"]["status"] == "needs_review"
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        fingerprint = load_entries(ws.bib)["Kaha12"]["fingerprint"]
        record_approval(cache, ws.bib, "Kaha12", fingerprint, dict(
            reviewer="@fixture", source="the book itself", note="title page checked", github_login="fixture", github_id=1))
        record_revocation(cache, ws.bib, "Kaha12", "the year was misread", "@fixture")
    finally:
        cache.close()
    ws.stored = lambda: (ws.bib.read_bytes(), {item.key: api.entry(ws, item.key).result for item in api.entries(ws)})
    ws.before = ws.stored()
    yield ws
    # Browsing, searching and reading details write nothing: the file and every stored result are as they were.
    assert ws.stored() == ws.before and not (ws.work / "edits").exists()


def table_keys(app, selector="#entries"):
    table = app.screen.query_one(selector)
    return [key.value for key in table.rows]


def test_browse_shows_every_entry_with_its_status_and_the_counts(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            assert table_keys(app) == ["Zoll90", "Kaha12", "GlocBets08", "TeneEtal11", "Game62"]
            text = T.screen_text(app)
            assert "5 of 5 entries" in text and "5 entries" in text.splitlines()[0]
            assert "? needs_review 2" in text and "· pending 3" in text       # counts per status, with the marks
            assert re.search(r"\?\s+Game62\s", text) and re.search(r"·\s+Zoll90\s", text)   # a status mark per entry
            assert "@article{Zoll90," in T.shown(app, "#library-detail #t-entry")   # the first entry's exact text
            assert "ready: 5 entries prepared" in "\n".join(app.log_lines)          # api.prepare ran first, and said so
            assert app.jobs.history[0][0] == "read the library"
    T.run(journey())


def test_search_uses_the_cores_syntax_and_the_status_filter(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "slash")
            await T.type_text(pilot, "glockner")                      # an accent in the file, none typed
            assert table_keys(app) == ["GlocBets08"] and "1 of 5 entries" in T.screen_text(app)
            assert T.shown(app, "#library-detail #t-entry") == GLOC08.expandtabs(4)
            search = app.screen.query_one("#search")
            search.value = ""
            await T.type_text(pilot, "journal:science year:2011")
            assert table_keys(app) == ["TeneEtal11"]
            search.value = ""
            await T.type_text(pilot, "status:needs_review")
            assert table_keys(app) == ["Kaha12", "Game62"]
            search.value = ""
            await T.type_text(pilot, "e")                               # a letter typed in the box is text, not a key
            assert search.value == "e" and len(app.screen_stack) == 1
            search.value = ""
            await T.press(pilot, "escape", "f")                         # the status filter, one status at a time
            assert table_keys(app) == ["Kaha12", "Game62"] and "only status needs_review" in T.screen_text(app)
            await T.press(pilot, "f")
            assert table_keys(app) == ["Zoll90", "GlocBets08", "TeneEtal11"]
            await T.press(pilot, "f")
            assert len(table_keys(app)) == 5
    T.run(journey())


def test_the_detail_tabs_show_issues_and_the_evidence_field_by_field(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "slash")
            await T.type_text(pilot, "games")
            await T.press(pilot, "escape", "d")                         # Issues
            issues = T.shown(app, "#library-detail #t-issues")
            assert "Status: ? needs_review" in issues and "No unambiguous, fully supported metadata match" in issues
            assert "No unambiguous, fully supported metadata match" in T.screen_text(app)
            await T.press(pilot, "d")                                   # Evidence
            evidence = T.shown(app, "#library-detail #t-evidence")
            assert "Closest source (field by field)" in evidence and "source: crossref" in evidence
            assert "≠ volume\n      library: 36\n      source:  63" in evidence
            assert "issue: volume: missing evidence or mismatch" in evidence
            assert "= year\n      library: 1962\n      source:  1962" in evidence and "source:  Paul A. Games" in evidence
            assert "Lookups made" in evidence and "source=crossref-doi" in evidence
            assert "(no approval recorded for this entry text)" in evidence
            assert "Closest source" in T.screen_text(app)
            app.screen.query_one("#search").value = "kahana"
            await T.settle(pilot)
            evidence = T.shown(app, "#library-detail #t-evidence")
            assert "Revoked approval" in evidence and "reason: the year was misread" in evidence
            assert "source: the book itself" in evidence and "reviewer: @fixture" in evidence
            assert "(no approval recorded for this entry text)" in evidence   # a revoked approval is not shown as one
    T.run(journey())


def test_external_evidence_is_shown_with_its_page_quotes_and_never_as_an_approval(ws):
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        entry = load_entries(ws.bib)["Game62"]
        cache.put(ws.bib, entry, dict(cache.get(ws.bib, entry), external_evidence=dict(
            pdf_sha256="0" * 64, reviewer="dartmouth", fields={"volume": {"value": "36", "page": 1, "quote": "Vol. 36"}},
            uncertainties=["the issue number is not printed"])))
    finally:
        cache.close()
    ws.before = ws.stored()                      # what the interface is to leave as it is

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "slash")
            await T.type_text(pilot, "games")
            evidence = T.shown(app, "#library-detail #t-evidence")
            assert "External evidence (PDF or model reading; not an approval)" in evidence
            assert "volume: 36 (p. 1)" in evidence and "“Vol. 36”" in evidence
            assert "- the issue number is not printed" in evidence
            assert "Status: ? needs_review" in evidence and "(no approval recorded for this entry text)" in evidence
    T.run(journey())


def test_the_theme_switches_with_a_key_and_uses_only_the_palette(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            assert app.theme == "cdlbib-dark"                           # nothing says the terminal is light
            dark = app.export_screenshot()
            assert theme.DARK["background"].lower() in dark.lower() and theme.DARK["primary"].lower() in dark.lower()
            await T.press(pilot, "ctrl+t")
            assert app.theme == "cdlbib-light"
            light = app.export_screenshot()
            assert theme.LIGHT["background"].lower() in light.lower() and theme.LIGHT["text"].lower() in light.lower()
            assert theme.DARK["text"].lower() not in light.lower()
            await T.press(pilot, "ctrl+t")
            assert app.theme == "cdlbib-dark"
    T.run(journey())


def test_the_theme_follows_the_terminal_where_it_says(ws, monkeypatch):
    from cdlbib.tui import themes
    assert themes.terminal_mode({}) == "dark" and themes.terminal_mode({"COLORFGBG": "15;0"}) == "dark"
    assert themes.terminal_mode({"COLORFGBG": "0;15"}) == "light" and themes.terminal_mode({"COLORFGBG": "0;default;7"}) == "light"
    monkeypatch.setenv("COLORFGBG", "0;15")

    async def journey():
        async with T.opened(ws) as pilot:
            assert pilot.app.theme == "cdlbib-light"
    T.run(journey())


def test_the_themes_are_the_palettes_roles():
    from cdlbib.tui import themes
    for mode, roles in theme.MODES.items():
        built = themes.build(mode)
        assert (built.background, built.surface, built.panel, built.foreground) == (
            roles["background"], roles["surface"], roles["panel"], roles["text"])
        assert (built.primary, built.accent, built.success, built.warning, built.error) == (
            roles["primary"], roles["accent"], roles["success"], roles["warning"], roles["error"])
        assert set(built.variables.values()) <= set(roles.values())
        assert built.dark is (mode == "dark")


def test_no_colour_is_named_in_the_tui_package():
    found = {str(path.relative_to(ROOT)): re.findall(r"#[0-9a-fA-F]{6}\b", path.read_text(encoding="utf-8"))
             for path in sorted(PACKAGE.rglob("*")) if path.is_file() and path.suffix in (".py", ".tcss", ".css")}
    assert len(found) >= 10 and not any(found.values()), {name: hits for name, hits in found.items() if hits}
    named = re.compile(r"\b(?:color|background|border[a-z-]*|tint)\s*:\s*[^;$]*\b(?:red|green|blue|white|black|yellow|"
                       r"grey|gray|cyan|magenta|orange|ansi_[a-z_]+)\b")
    for path in sorted(PACKAGE.rglob("*.py")):
        assert not named.search(path.read_text(encoding="utf-8")), path


def test_help_lists_every_key_the_interface_binds(ws):
    from cdlbib.tui import KEYS
    listed = " ".join(key for _, keys in KEYS for key, _ in keys)
    bound = set()
    for path in PACKAGE.glob("*.py"):
        bound |= set(re.findall(r'Binding\("([^"]+)"', path.read_text(encoding="utf-8")))
    names = {"question_mark": "?", "slash": "/", "escape": "esc"}
    missing = sorted(key for key in bound if names.get(key, key).lower() not in listed.lower()
                     and not re.fullmatch(r"f[2-8]|[1-7]", key))
    assert not missing and "F2 … F8" in listed and "1 … 7" in listed

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "question_mark")
            page = T.shown(app, "#page")
            for section, keys in KEYS:
                assert section in page
                for key, what in keys:
                    assert key in page and what in page
            assert "Keys" in T.screen_text(app)
            await T.press(pilot, "escape")
            assert len(app.screen_stack) == 1
            footer = T.screen_text(app).splitlines()[-1]
            assert "Search" in footer and "Edit" in footer and "Help" in footer and "Quit" in footer   # the key hints
    T.run(journey())


def test_a_library_of_6481_entries_stays_responsive(tmp_path):
    root = tmp_path / "big"
    root.mkdir()
    shutil.copy(conftest.FROZEN_LIBRARY, root / "cdl.bib")
    ws = Workspace(root)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            view, table = app.view("library"), app.screen.query_one("#entries")
            assert len(app.entries) == 6481 and "6481 of 6481 entries" in T.screen_text(app)
            assert table.row_count == 400 == view.shown              # the rest are added as the cursor moves down
            started = time.monotonic()
            await T.press(pilot, "slash")
            await T.type_text(pilot, "memory")
            typed = time.monotonic() - started
            assert len(view.matches) == len(api.search(app.entries, "memory")) > 1000
            assert table.row_count == 400 and "more are added as you move down" in T.screen_text(app)
            assert typed < 15, f"typing six letters into the search took {typed:.1f} s"
            started = time.monotonic()
            await T.type_text(pilot, " kahana")
            assert time.monotonic() - started < 15 and 0 < table.row_count == len(view.matches) < 400
            app.screen.query_one("#search").value = ""
            await T.press(pilot, "escape")
            table.move_cursor(row=395)                                # near the end of what is listed
            await T.settle(pilot)
            assert table.row_count == 800 and view.selected == app.entries[395].key
            assert T.shown(app, "#library-detail #t-entry").startswith("@")
            started = time.monotonic()
            await T.press(pilot, "pagedown", "pagedown", "down", "down")
            assert time.monotonic() - started < 10
    T.run(journey())


def test_an_entry_not_read_yet_shows_what_is_known_while_a_job_runs(ws):
    import threading

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            hold = threading.Event()
            app.job("a long check", lambda job: hold.wait(30))
            await pilot.press("down")                                       # Kaha12: not read yet
            await pilot.pause(0.3)
            shown = T.shown(app, "#library-detail #t-entry")
            assert shown.startswith("Kaha12 (book)\n  authors: M J Kahana\n  year: 2012\n  title: Foundations of human memory")
            assert "status: ? needs_review" in shown
            assert "The entry's text, issues and evidence load when the running job finishes: a long check" in shown
            await pilot.press("slash", "g", "a", "m", "e", "s")            # and a search does not wait either
            await pilot.pause(0.3)
            assert table_keys(app) == ["Game62"] and not app.jobs.idle
            await pilot.press("escape")
            hold.set()
            await T.settle(pilot)
            assert "@article{Game62," in T.shown(app, "#library-detail #t-entry")
            app.screen.query_one("#search").value = ""
            await T.settle(pilot)
            app.job("another long check", lambda job: hold.clear() or hold.wait(30))
            app.screen.query_one("#entries").move_cursor(row=4)             # Game62 again: read before, shown at once
            await pilot.pause(0.3)
            assert "@article{Game62," in T.shown(app, "#library-detail #t-entry") and not app.jobs.idle
            hold.set()
            await T.settle(pilot)
    T.run(journey())
