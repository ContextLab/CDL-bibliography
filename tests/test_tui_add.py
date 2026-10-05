"""Adding references in the terminal interface by key presses: by identifier (several at once),
by a title search, from a PDF, and by hand; and the proposal view they all end in (accept,
edit, skip, accept all remaining).

The real app over the real core. Lookups are saved responses put into the library's own
response cache, with the network refused; PDFs are typeset by pdflatex when the test runs.
The library file is read afterwards.
"""
import pytest

pytest.importorskip("textual", reason="the terminal interface needs the optional package textual (pip install 'cdlbib[tui]')")

import conftest  # noqa: E402
import intake_pdfs as pdfs  # noqa: E402
import tui_support as T  # noqa: E402
from cdlbib import api, secrets  # noqa: E402
from cdlbib.errors import SecretNotFound  # noqa: E402
from cdlbib.verification import ACCEPTED, load_entries  # noqa: E402
from test_complete_identify import library_entry  # noqa: E402

ZOLL90 = conftest.ZOLL90
GAME62 = library_entry("Game62")
ZOLLER_DOI, GAMES_DOI = "10.1002/tea.3660271011", "10.1037/h0041332"
needs_pdflatex = pytest.mark.skipif(not pdfs.pdflatex(), reason="pdflatex is not installed, so no PDF can be typeset "
                                                                "for the test")


def _dartmouth_key():
    """The Dartmouth Chat key of this user, looked up before any test substitutes HOME."""
    try:
        return secrets.get("dartmouth-chat")
    except SecretNotFound:
        return None


_DARTMOUTH = _dartmouth_key()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    T.isolate(monkeypatch, tmp_path)
    T.offline(monkeypatch)
    for name in ("DARTMOUTH_CHAT_API_KEY", "OPENAI_API_KEY", "BIBCHECK_RESEARCH_MODEL"):
        monkeypatch.delenv(name, raising=False)
    yield
    conftest.no_real_library_touched()


@pytest.fixture
def ws(tmp_path):
    ws = T.library(tmp_path / "lib")
    ws.bib.write_text("", encoding="utf-8")
    T.seed_responses(ws, T.COMPLETION, T.PDF_LOOKUPS, T.TUI_SEARCH)
    return ws


def name(app):
    return type(app.screen).__name__


async def add_tab(pilot, number):
    """Open the Add view on its tab ``number`` (0 Search, 1 Identifier, 2 PDF, 3 Manual)."""
    await T.press(pilot, "f4")
    if number:
        await T.press(pilot, "escape", *["right"] * number, "enter")


# --- identifiers, and the proposal view ----------------------------------------------------------

def test_identifiers_are_looked_up_together_and_each_proposal_is_accepted_or_skipped(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 1)
            assert app.focused.id == "i-ids"
            await T.type_text(pilot, f"{ZOLLER_DOI}, {GAMES_DOI}")
            await T.press(pilot, "enter")
            assert name(app) == "ProposalScreen"
            text = T.screen_text(app)
            assert "Proposal 1 of 2 · built from a source record · identifier" in text
            assert "(no typed entry)" in T.shown(app, "#typed")                      # typed | proposed, side by side
            assert T.shown(app, "#proposed") == ZOLL90.expandtabs(4)
            findings = T.shown(app, "#findings")
            assert "Entry: Zoll90" in findings and "(source: crossref)" in findings   # each change with its source
            assert "title: None -> Students' misunderstandings" in findings
            assert "Verification: metadata_verified" in findings
            assert "[a] accept   [e] edit   [s] skip   [A] accept all remaining   [q] stop" in T.shown(app, "#proposal-actions")
            assert "it does not verify or approve it" in T.shown(app, "#proposal-actions")
            assert ws.bib.read_text(encoding="utf-8") == ""                           # nothing is written by proposing
            await T.press(pilot, "a")
            assert ws.bib.read_text(encoding="utf-8").strip() == ZOLL90 and "Added: Zoll90" in app.log_lines
            assert "Proposal 2 of 2" in T.screen_text(app) and T.shown(app, "#proposed") == GAME62.expandtabs(4)
            await T.press(pilot, "s")
            assert name(app) != "ProposalScreen" and "Skipped: Game62" in app.log_lines
            message = T.shown(app, "#i-message")
            assert "Added: Zoll90" in message and "Skipped: Game62" in message
            assert "cdl.bib as it was before the first accepted change is kept at" in message
            await T.press(pilot, "f2")
            assert "1 of 1 entries" in T.screen_text(app) and "Zoll90" in T.screen_text(app)
    T.run(journey())
    assert set(load_entries(ws.bib)) == {"Zoll90"}
    assert api.entry(ws, "Zoll90").human_review is None                               # accepting is not approving


def test_accept_all_remaining_writes_those_that_need_no_decision(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 1)
            await T.type_text(pilot, f"{ZOLLER_DOI} {GAMES_DOI} 10.9999/completion-cli-missing")
            await T.press(pilot, "enter")
            assert "Proposal 1 of 3" in T.screen_text(app)
            await T.press(pilot, "A")
            assert "Added: Zoll90" in app.log_lines and "Added: Game62" in app.log_lines
            assert name(app) == "ProposalScreen" and "Proposal 3 of 3" in T.screen_text(app)   # this one needs a person
            assert "(no proposed entry)" in T.shown(app, "#proposed")
            await T.press(pilot, "a")
            assert name(app) == "ProposalScreen"                         # it cannot be accepted: the core's rule
            assert any("Cannot accept: complete required fields" in note.message for note in app._notifications)
            await T.press(pilot, "q")
            assert name(app) != "ProposalScreen"
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8").strip() == ZOLL90 + "\n\n" + GAME62


def test_editing_a_proposal_checks_the_edited_text_again(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 1)
            await T.type_text(pilot, ZOLLER_DOI)
            await T.press(pilot, "enter", "e")
            assert name(app) == "TextEditScreen" and app.screen.query_one("#proposal-editor").text == ZOLL90
            await T.press(pilot, "pagedown", "up", "up", "up", "end", "left", "left", "backspace", "backspace")
            await T.type_text(pilot, "66")                                 # Pages = {1053--1066}
            await T.press(pilot, "ctrl+s")
            assert name(app) == "ProposalScreen"
            edited = ZOLL90.replace("1053--1065", "1053--1066")
            assert T.shown(app, "#proposed") == edited.expandtabs(4)
            findings = T.shown(app, "#findings")
            assert "pages: 1053--1065 -> 1053--1066 (source: user edit) [changed]" in findings
            assert "Verification: metadata_verified" not in findings        # the edited text was checked again
            await T.press(pilot, "e", "escape")                            # leaving the editor changes nothing
            assert T.shown(app, "#proposed") == edited.expandtabs(4)
            await T.press(pilot, "a")
            assert name(app) != "ProposalScreen"
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8").strip() == ZOLL90.replace("1053--1065", "1053--1066")
    assert api.entry(ws, "Zoll90").status not in ACCEPTED


# --- search ----------------------------------------------------------------------------------------

def test_a_title_search_lists_leads_with_their_sources_and_the_chosen_one_is_proposed(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 0)
            assert app.focused.id == "s-title"
            await T.type_text(pilot, "Backward learning in paired associates")
            await T.press(pilot, "enter")
            view, table = app.view("add"), app.screen.query_one("#s-results")
            assert len(view.leads) == 3 == table.row_count and view.search_errors == []
            text = T.screen_text(app)
            assert "3 records found" in text and "crossref, pubmed" in text and "10.1037/h0044314" in text
            assert "Bennet B. Murdock" in text and "1956" in text
            assert app.focused is table
            await T.press(pilot, "enter")
            assert name(app) == "ProposalScreen" and "Entry: Murd56" in T.shown(app, "#findings")
            assert "@article{Murd56," in T.shown(app, "#proposed")
            findings = T.shown(app, "#findings")                          # the sources disagree: said, not settled
            assert "Unfilled title: title: sources disagree" in findings
            assert 'crossref: "Backward" learning in paired associates.' in findings
            assert "pubmed: Backward learning in paired associates" in findings
            await T.press(pilot, "a")
            assert name(app) == "ProposalScreen" and ws.bib.read_text(encoding="utf-8") == ""   # incomplete: not written
            await T.press(pilot, "e")                                       # the person types the title
            await T.press(pilot, "pagedown", "up", "up", "end", "enter", "tab")
            await T.type_text(pilot, "Title = {Backward learning in paired associates},")
            await T.press(pilot, "ctrl+s")
            findings = T.shown(app, "#findings")
            assert "title: None -> Backward learning in paired associates (source: user edit) [changed]" in findings
            assert "Unfilled title" not in findings
            await T.press(pilot, "a")
            assert "Added: Murd56" in T.shown(app, "#s-message")
    T.run(journey())
    assert set(load_entries(ws.bib)) == {"Murd56"}
    written = ws.bib.read_text(encoding="utf-8")

    async def again():                                                     # the same search now names the entry
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 0)
            await T.type_text(pilot, "Backward learning in paired associates")
            await T.press(pilot, "enter")
            assert app.view("add").leads[0]["in_library"] == "Murd56"
            assert "Murd56" in T.screen_text(app).split("In library")[-1].splitlines()[1]
            await T.press(pilot, "enter")
            findings = T.shown(app, "#findings")
            assert "Duplicate: Murd56" in findings and "already in the library or batch as Murd56" in findings
            await T.press(pilot, "a")
            assert name(app) == "ProposalScreen"                         # a duplicate cannot be accepted
            await T.press(pilot, "A")
            assert name(app) == "ProposalScreen"
            await T.press(pilot, "s")
    T.run(again())
    assert ws.bib.read_text(encoding="utf-8") == written


def test_a_search_that_no_source_answers_says_which_did_not(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 0)
            await T.press(pilot, "tab")
            await T.type_text(pilot, "Nobodyatall; Otherperson")
            await T.press(pilot, "ctrl+f")
            message = T.shown(app, "#s-message")
            assert "No record was found." in message
            for source in ("crossref", "pubmed", "arxiv"):
                assert f"{source} did not answer:" in message
    T.run(journey())


# --- PDF -------------------------------------------------------------------------------------------

@needs_pdflatex
def test_a_pdf_is_read_shown_looked_up_and_its_record_proposed(ws, tmp_path):
    pdf = pdfs.build("doi", tmp_path / "pdfs")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 2)
            assert app.focused.id == "p-path"
            await T.type_text(pilot, str(pdf))
            await T.press(pilot, "enter")
            info = T.shown(app, "#p-info")
            assert f"doi: {ZOLLER_DOI} (page 1)" in info and "Title read" in info
            assert "misunderstandings and misconceptions in college freshman chemistry" in info
            assert "(largest text on page 1)" in info
            assert "Text of the first page" in info and "Haifa University" in info
            page = T.shown(app, "#p-page")
            if api.features()[[f.name for f in api.features()].index("pypdf")].available:
                try:
                    import pypdfium2  # noqa: F401
                    assert page.count("▀") > 500 and len(page.splitlines()) > 20      # the first page, in half blocks
                except ImportError:
                    assert "The first page is not drawn" in page
            await T.press(pilot, "l")
            assert name(app) == "ProposalScreen" and str(pdf.name) in T.screen_text(app)
            findings = T.shown(app, "#findings")
            assert f"Found by the doi read from the PDF (page 1): {ZOLLER_DOI}" in findings
            assert T.shown(app, "#proposed") == ZOLL90.expandtabs(4)
            await T.press(pilot, "a")
            assert name(app) != "ProposalScreen" and "Added: Zoll90" in T.shown(app, "#p-message")
            assert "A source record was found by the doi read from the PDF." in T.shown(app, "#p-info")
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8").strip() == ZOLL90


@needs_pdflatex
def test_a_pdf_no_source_knows_offers_a_model_then_the_form_filled_with_what_was_read(ws, tmp_path):
    pdf = pdfs.build("unknown", tmp_path / "pdfs")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 2)
            await T.type_text(pilot, str(pdf))
            await T.press(pilot, "enter")
            await T.press(pilot, "l")
            assert name(app) == "ChoiceScreen"
            question = T.shown(app, "#question")
            assert "No source record was found for this PDF" in question
            assert "It can be read with a language model, or typed in by hand." in question
            labels = [str(button.label) for button in app.screen.query("Button")]
            assert any("Read the PDF with a language model" in label for label in labels)
            assert any("Type the entry in" in label for label in labels)

            await T.press(pilot, "m")                                      # the routes, Dartmouth first
            assert name(app) == "RouteScreen"
            routes = T.shown(app, "#question")
            assert routes.index("[1] Dartmouth Chat (the default): not checked") < routes.index("[2] OpenAI: not checked")
            assert "Create an API key in Dartmouth Chat" in routes and "never a verification or an approval" in routes
            await T.press(pilot, "c")                                      # look the keys up: none under this HOME
            assert name(app) == "RouteScreen"
            routes = T.shown(app, "#question")
            assert "[1] Dartmouth Chat (the default): not set up" in routes and "[2] OpenAI: not set up" in routes
            assert "Create an API key in Dartmouth Chat" in routes        # how to set it up stays on the screen
            off = [button for button in app.screen.query("Button") if button.disabled]
            assert [button.id for button in off] == ["choice-dartmouth", "choice-openai"]   # listed, greyed
            await T.press(pilot, "1")
            assert name(app) == "RouteScreen"                            # a route that is not set up is not run

            await T.press(pilot, "t")                                      # the form, with what was read
            assert app.view("add").tab == "add-manual"
            assert app.screen.query_one("#m-title").value == pdfs.UNKNOWN_TITLE
            assert "Filled from the PDF: title" in T.shown(app, "#m-message")
            app.screen.query_one("#m-author").focus()
            await T.type_text(pilot, "Ada Q. Example and Bo R. Sample")
            app.screen.query_one("#m-year").focus()
            await T.type_text(pilot, "2019")
            app.screen.query_one("#m-journal").focus()
            await T.type_text(pilot, "Annals of Improbable Lattices")
            await T.press(pilot, "ctrl+s")
            assert name(app) == "ProposalScreen" and "typed by hand" in T.screen_text(app)
            findings = T.shown(app, "#findings")
            assert "read from the PDF (not typed)" in findings and "(source: typed)" in findings
            assert "Verification: needs_review" in findings and "No source record" in findings
            assert "@article{ExamSamp19," in T.shown(app, "#proposed")
            await T.press(pilot, "a")
            assert name(app) != "ProposalScreen" and "Added: ExamSamp19" in T.shown(app, "#m-message")
    T.run(journey())
    entry = api.entry(ws, "ExamSamp19")
    assert entry.status not in ACCEPTED and entry.human_review is None    # written, unverified, unapproved
    assert "Title = {Plorbnix dynamics in zzyzxqv lattices under qwxzvk forcing}" in entry.raw


@needs_pdflatex
def test_a_real_model_reading_is_proposed_with_page_quotes_and_stays_unverified(ws, tmp_path, monkeypatch):
    if not _DARTMOUTH:
        pytest.skip("no Dartmouth Chat key here, so no real model run through the interface")
    for variable in T.refused_network():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("DARTMOUTH_CHAT_API_KEY", _DARTMOUTH)
    pdf = pdfs.build("unknown", tmp_path / "pdfs")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 2)
            await T.type_text(pilot, str(pdf))
            await T.press(pilot, "enter")
            await T.press(pilot, "m")
            assert "[1] Dartmouth Chat (the default): set up" in T.shown(app, "#question")
            await T.press(pilot, "1")
            await T.settle(pilot, timeout=300)
            assert name(app) == "ProposalScreen" and "read from the PDF by a model" in T.screen_text(app)
            findings = T.shown(app, "#findings")
            assert "model reading, p.1" in findings and "Verification: needs_review" in findings
            await T.press(pilot, "a")
            await T.settle(pilot)
    T.run(journey())
    for key in load_entries(ws.bib):
        entry = api.entry(ws, key)
        assert entry.status == "needs_review" and entry.human_review is None and entry.external_evidence["fields"]


# --- manual ----------------------------------------------------------------------------------------

def test_a_typed_entry_is_drafted_in_house_format_and_written_unverified(ws):
    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 3)
            assert app.focused.id == "m-entrytype"
            fields = [box.id for box in app.screen.query("#manual-form Input")]
            assert fields[:4] == ["m-author", "m-title", "m-year", "m-journal"] and len(fields) == len(api.draft_fields())
            await T.press(pilot, "ctrl+s")
            assert "Nothing is typed yet." in T.shown(app, "#m-message") and name(app) != "ProposalScreen"
            for box, text in (("m-author", "Ada Q. Example and Glockner, Bo"), ("m-title", "the neural basis of Imaginary things"),
                              ("m-year", "2031"), ("m-journal", "Journal of Imaginary Results"), ("m-volume", "12"),
                              ("m-pages", "45-67")):
                app.screen.query_one(f"#{box}").focus()
                await T.type_text(pilot, text)
            await T.press(pilot, "ctrl+s")
            assert name(app) == "ProposalScreen"
            proposed = T.shown(app, "#proposed")
            assert "@article{ExamGloc31," in proposed and "Author = {Ada Q Example and Bo Glockner}" in proposed
            assert "Pages = {45--67}" in proposed                           # the house formatter wrote it
            findings = T.shown(app, "#findings")
            assert "Verification: needs_review" in findings and "No source record" in findings
            await T.press(pilot, "a")
            assert name(app) != "ProposalScreen" and "Added: ExamGloc31" in T.shown(app, "#m-message")
    T.run(journey())
    entry = api.entry(ws, "ExamGloc31")
    assert entry.status not in ACCEPTED and entry.human_review is None and "Year = {2031}" in entry.raw
