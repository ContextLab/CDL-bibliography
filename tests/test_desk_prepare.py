"""What the desk prepares once per state of the library (api.prepare), and the @string
definitions the one-entry format check is given. Real files; the 6,481-entry frozen library
fixture for the timing; no mocks."""
import shutil
import time

import conftest
from cdlbib import api, desk
from cdlbib.workspace import Workspace

from test_desk import KAHA12, TEXT, ZOLL90


def test_an_entry_that_uses_a_string_definition_is_formatted_with_it(tmp_path):
    ws = Workspace(tmp_path)
    using = ZOLL90.replace("{Journal of Research in Science Teaching}", "jrst")
    text = ('% header\n@string{jrst = "Journal of Research in Science Teaching"}\n@preamble{"\\newcommand{\\x}{x}"}\n\n'
            + using + "\n\n" + KAHA12 + "\n")
    ws.bib.write_text(text, encoding="utf-8")
    assert desk._definitions(text.encode()) == ['@string{jrst = "Journal of Research in Science Teaching"}',
                                                '@preamble{"\\newcommand{\\x}{x}"}']
    detail = api.entry(ws, "Zoll90")
    assert detail.fields["journal"] == "Journal of Research in Science Teaching" and detail.format == []
    edited = using.replace("1053--1065", "1053-1065")
    preview = api.preview_edit(ws, "Zoll90", edited)
    assert preview.ok and [(item.field, item.current, item.corrected) for item in preview.format] == [
        ("pages", "1053-1065", "1053--1065")]
    assert preview.corrected_raw == ZOLL90              # the formatter's entry, with the string written out
    api.save_edit(ws, "Zoll90", edited, preview.fingerprint)
    assert ws.bib.read_text(encoding="utf-8") == text.replace(using, edited)
    assert [item.field for item in api.entry(ws, "Zoll90").format] == ["pages"]
    assert [item.field for item in api.entry(ws, "Kaha12").format] == []
    assert desk._definitions(TEXT.encode()) == [] and desk._definitions(b"@string{broken") == []


def test_prepare_reports_its_steps_and_previews_of_the_whole_library_are_then_quick(tmp_path):
    """The frozen library: prepared once (with progress), after which a preview, a save and
    the preview after that save reuse what was prepared."""
    ws = Workspace(tmp_path)
    shutil.copy(conftest.FROZEN_LIBRARY, ws.bib)
    lines = []
    prepared = api.prepare(ws, progress=lines.append)
    assert prepared.entries == 6481 and prepared.revision == api.revision(ws)
    assert lines[0] == "reading cdl.bib ..." and lines[1] == "read 6481 entries"
    assert "indexed 500 of 6481 entries" in lines and "indexed 6000 of 6481 entries" in lines
    assert lines[-1].startswith("ready: 6481 entries prepared in ")
    quiet = []
    again = api.prepare(ws, progress=quiet.append)       # the same state: nothing is worked out twice
    assert again.seconds < 2 and not any(text.startswith("indexed") for text in quiet)

    key = api.entries(ws)[100].key
    detail = api.entry(ws, key)
    edited = detail.raw.replace("}}", " (edited)}}", 1)
    assert edited != detail.raw
    started = time.monotonic()
    preview = api.preview_edit(ws, key, edited)
    warm = time.monotonic() - started
    assert preview.ok and preview.changed and warm < 5, warm       # a fraction of a second here; 13 s unprepared
    api.save_edit(ws, key, edited, preview.fingerprint)
    started = time.monotonic()
    after = api.preview_edit(ws, key, edited.replace("(edited)", "(edited twice)"))
    assert after.ok and time.monotonic() - started < 5              # the save carried the prepared data over
    held = desk._PARSED[str(ws.bib)]
    assert {"bases", "works", "definitions"} <= set(held[2]) and len(held[2]["works"]) == 6481
    assert held[2]["bases"] == desk._bases(held[1])                 # carried over, and still right
    duplicate = api.preview_edit(ws, None, detail.raw.replace("{" + key + ",", "{Another99,"))
    assert duplicate.duplicate_of == key
