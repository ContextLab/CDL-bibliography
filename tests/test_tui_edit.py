"""Editing an entry in the terminal interface by key presses: the editor, the preview (diff,
format findings, the status that is lost), the formatter's text, saving, a new entry, and the
refusals. The files are compared afterwards. Real app, real core, no mocks."""
import pytest

pytest.importorskip("textual", reason="the terminal interface needs the optional package textual (pip install 'cdlbib[tui]')")

import conftest  # noqa: E402
import tui_support as T  # noqa: E402
from cdlbib import api  # noqa: E402
from cdlbib.verification import Cache, load_entries, record_approval  # noqa: E402
from test_desk import KAHA12, ZOLL90  # noqa: E402

REVIEW = dict(reviewer="@fixture", source="the journal's page", note="every field checked", github_login="fixture",
              github_id=1)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    T.isolate(monkeypatch, tmp_path)
    T.offline(monkeypatch)
    yield
    conftest.no_real_library_touched()


@pytest.fixture
def ws(tmp_path):
    return T.library(tmp_path / "lib", ZOLL90, KAHA12)


def approve(ws, key):
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        record_approval(cache, ws.bib, key, load_entries(ws.bib)[key]["fingerprint"], REVIEW)
    finally:
        cache.close()


async def change_volume(pilot):
    """In the editor of Zoll90: the last line but one is ``Volume = {27},``; make it 28."""
    await T.press(pilot, "pagedown", "up", "end", "left", "left", "backspace", "8")


def test_edit_preview_save_writes_exactly_the_edit_and_shows_what_it_costs(ws):
    approve(ws, "Zoll90")
    before = ws.bib.read_text(encoding="utf-8")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            assert "◆ human_verified" in T.screen_text(app)
            await T.press(pilot, "e")
            assert type(app.screen).__name__ == "EditScreen" and "Edit Zoll90" in T.screen_text(app)
            assert app.screen.text == ZOLL90
            await change_volume(pilot)
            assert app.screen.text == ZOLL90.replace("{27}", "{28}")
            await T.press(pilot, "ctrl+p")
            preview = T.shown(app, "#preview")
            assert "-    Volume = {27}," in preview and "+    Volume = {28}," in preview          # the diff
            assert "now: ◆ human_verified" in preview and "after saving: · pending" in preview
            assert "Saving loses the status human_verified" in preview
            assert "House format\n  (no findings)" in preview
            assert "Saving loses the status human_verified" in T.screen_text(app)
            assert ws.bib.read_text(encoding="utf-8") == before                                  # a preview writes nothing
            await T.press(pilot, "ctrl+s")
            assert type(app.screen).__name__ != "EditScreen"
            assert "Saved: Zoll90" in app.log_lines
            assert "Volume = {28}" in T.shown(app, "#library-detail #t-entry")                    # the table and detail follow
            assert "· pending 2" in T.screen_text(app) and "human_verified" not in T.screen_text(app)
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8") == before.replace("{27}", "{28}")
    assert api.entry(ws, "Zoll90").status == "pending" and api.entry(ws, "Kaha12").raw == KAHA12
    copies = list((ws.work / "edits").glob("*-cdl.bib"))
    assert len(copies) == 1 and copies[0].read_text(encoding="utf-8") == before                  # the file as it was is kept


def test_save_without_a_preview_previews_first_and_writes_nothing(ws):
    before = ws.bib.read_bytes()

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "e")
            await change_volume(pilot)
            await T.press(pilot, "ctrl+s")
            assert type(app.screen).__name__ == "EditScreen" and ws.bib.read_bytes() == before
            assert "This is what saving would do. ctrl+s again saves it." in T.shown(app, "#edit-message")
            assert "+    Volume = {28}," in T.shown(app, "#preview")
            await T.press(pilot, "backspace", "9")                    # the text changed after the preview
            await T.press(pilot, "ctrl+s")
            assert ws.bib.read_bytes() == before and "+    Volume = {29}," in T.shown(app, "#preview")
            await T.press(pilot, "ctrl+s")
            assert type(app.screen).__name__ != "EditScreen"
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8") == before.decode().replace("{27}", "{29}")


def test_the_formatters_text_is_applied_with_one_key(tmp_path):
    ws = T.library(tmp_path / "lib", ZOLL90.replace("1053--1065", "1053-1065"), KAHA12)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "d")
            assert "pages:" in T.shown(app, "#library-detail #t-issues")        # the finding is on the Issues tab too
            assert "formatter: 1053--1065" in T.shown(app, "#library-detail #t-issues")
            await T.press(pilot, "e", "ctrl+p")
            preview = T.shown(app, "#preview")
            assert "The text is what the file already holds" in T.shown(app, "#edit-message")
            assert "now:       1053-1065" in preview and "formatter: 1053--1065" in preview
            await T.press(pilot, "ctrl+r")
            assert app.screen.text == ZOLL90
            assert "+    Pages = {1053--1065}," in T.shown(app, "#preview")
            assert "The formatter's text is in the editor and previewed" in T.shown(app, "#edit-message")
            await T.press(pilot, "ctrl+s")
            assert type(app.screen).__name__ != "EditScreen"
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8") == ZOLL90 + "\n\n" + KAHA12 + "\n"


def test_a_new_entry_is_typed_previewed_and_added(ws):
    typed = "@book{Test20, author={A Tester}, title={A book of tests}, publisher={Test Press}, address={Hanover, {NH}}, year={2020}}"
    before = ws.bib.read_text(encoding="utf-8")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "n")
            assert "New entry (typed by hand)" in T.screen_text(app)
            assert app.screen.text == ""
            await T.type_text(pilot, typed)
            assert app.screen.text == typed
            await T.press(pilot, "ctrl+p")
            preview = T.shown(app, "#preview")
            assert "+@book{Test20," in preview and "after saving: · pending" in preview and "now:" not in preview.split("House format")[0].split("Status")[1]
            await T.press(pilot, "ctrl+s")
            assert type(app.screen).__name__ != "EditScreen" and "Saved: Test20" in app.log_lines
            assert "3 of 3 entries" in T.screen_text(app)
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8").startswith(before.rstrip("\n")) and typed in ws.bib.read_text(encoding="utf-8")
    assert set(load_entries(ws.bib)) == {"Zoll90", "Kaha12", "Test20"}


def test_a_key_in_use_is_refused_in_the_preview_and_closing_asks_first(ws):
    before = ws.bib.read_bytes()

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "e")
            editor = app.screen.query_one("#editor")
            editor.move_cursor((0, len("@article{Zoll90")))
            await T.press(pilot, *["backspace"] * 6)
            await T.type_text(pilot, "Kaha12")
            assert app.screen.text == ZOLL90.replace("{Zoll90,", "{Kaha12,")
            await T.press(pilot, "ctrl+p")
            assert "Cannot be saved as it is" in T.shown(app, "#preview") and "Kaha12" in T.shown(app, "#edit-message")
            assert "Zoll90 -> Kaha12 (collision)" in T.shown(app, "#preview")
            await T.press(pilot, "ctrl+s")
            assert type(app.screen).__name__ == "EditScreen" and ws.bib.read_bytes() == before
            await T.press(pilot, "escape")                            # the text was changed: a question first
            assert type(app.screen).__name__ == "ConfirmScreen"
            assert "The edited text was not saved and is not kept" in T.shown(app, "#question")
            await T.press(pilot, "n")
            assert type(app.screen).__name__ == "EditScreen"
            await T.press(pilot, "escape", "y")
            assert len(app.screen_stack) == 1
    T.run(journey())
    assert ws.bib.read_bytes() == before


def test_an_entry_that_changed_on_disk_since_the_preview_is_not_overwritten(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "e")
            await change_volume(pilot)
            await T.press(pilot, "ctrl+p")
            other = ws.bib.read_text(encoding="utf-8").replace("Number = {10}", "Number = {11}")
            ws.bib.write_text(other, encoding="utf-8")                # another program edits the same entry
            await T.press(pilot, "ctrl+s")
            assert type(app.screen).__name__ == "EditScreen"
            assert "changed" in T.shown(app, "#edit-message")
            assert ws.bib.read_text(encoding="utf-8") == other
    T.run(journey())
