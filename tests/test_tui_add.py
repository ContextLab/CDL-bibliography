"""Adding references in the terminal interface by key presses: by identifier (several at once),
by a title search, from a PDF, and by hand; and the proposal view they all end in (accept,
edit, skip, accept all remaining).

The real app over the real core. Lookups are saved responses put into the library's own
response cache, with the network refused; PDFs are typeset by pdflatex when the test runs.
The library file is read afterwards.
"""
import importlib.util
import os

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
needs_pypdf = pytest.mark.skipif(not importlib.util.find_spec("pypdf"),
                                 reason="pypdf is not installed (pip install 'cdlbib[research]'), so no PDF can be read")


_REAL_HOME = os.environ.get("HOME", "")      # a name only; nothing is read at import


def _dartmouth_key():
    """The Dartmouth Chat key of this user, looked up under the user's own HOME by the one
    test that makes a real model run."""
    with pytest.MonkeyPatch.context() as own:
        own.setenv("HOME", _REAL_HOME)
        try:
            return secrets.get("dartmouth-chat")
        except SecretNotFound:
            return None


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
            table = T.changes(app)                                          # each change with its source, as a table
            assert table["volume"] == ("", "27", "crossref", "filled") and table["doi"][2:] == ("typed", "kept")
            assert table["title"][1].startswith("Students' misunderstandings") and table["title"][1].endswith("…")
            assert [str(column.label) for column in app.screen.query_one("#changes").columns.values()] == [
                "Field", "Typed", "Proposed", "Source", "Kind"]
            assert "Verification: metadata_verified" in findings
            assert "[a] accept" not in T.shown(app, "#proposal-actions")      # the keys are the footer's, said once
            footer = T.screen_text(app).splitlines()[-1]
            assert all(pair in footer for pair in ("a Accept", "e Edit", "s Skip", "A Accept all", "q Stop"))
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
            assert T.shown(app, "#proposal-actions").startswith("Cannot be accepted as it stands:\n  no entry is proposed\n")
            assert "no entry is proposed" in T.screen_text(app)             # ... and its reasons (api.why_not_acceptable)
            assert any("Cannot accept: complete required fields" in note for note in app.notices)
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
            await T.press(pilot, "enter")
            await T.press(pilot, "e")
            assert name(app) == "TextEditScreen" and app.screen.query_one("#proposal-editor").text == ZOLL90
            await T.press(pilot, "pagedown", "up", "up", "up", "end", "left", "left", "backspace", "backspace")
            await T.type_text(pilot, "66")                                 # Pages = {1053--1066}
            await T.press(pilot, "ctrl+s")
            assert name(app) == "ProposalScreen"
            edited = ZOLL90.replace("1053--1065", "1053--1066")
            assert T.shown(app, "#proposed") == edited.expandtabs(4)
            findings = T.shown(app, "#findings")
            assert T.changes(app)["pages"] == ("1053--1065", "1053--1066", "user edit", "changed")
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
            assert name(app) == "ProposalScreen" and T.changes(app)["author"][1] == "B B Murdock"
            assert "@article{Murd56," in T.shown(app, "#proposed")
            findings = T.shown(app, "#findings")                          # the sources disagree: said, not settled
            assert "Unfilled\n  title: sources disagree\n" in findings and "title: title" not in findings
            assert 'crossref: "Backward" learning in paired associates.' in findings
            assert "pubmed: Backward learning in paired associates" in findings
            await T.press(pilot, "a")
            assert name(app) == "ProposalScreen" and ws.bib.read_text(encoding="utf-8") == ""   # incomplete: not written
            await T.press(pilot, "e")                                       # the person types the title
            await T.press(pilot, "pagedown", "up", "up", "end", "enter", "tab")
            await T.type_text(pilot, "Title = {Backward learning in paired associates},")
            await T.press(pilot, "ctrl+s")
            findings = T.shown(app, "#findings")
            assert T.changes(app)["title"] == ("", "Backward learning in paired associates", "user edit", "changed")
            assert "Unfilled" not in findings and "sources disagree" not in findings
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
    assert ws.bib.read_text(encoding="utf-8") == ""                         # a search writes nothing


# --- PDF -------------------------------------------------------------------------------------------

@needs_pdflatex
@needs_pypdf
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
            assert not app.screen.query("#p-page")                         # the page itself is not drawn in the terminal
            assert "o opens the PDF itself in the system viewer" in T.shown(app, "#p-message")
            assert "▀" not in T.screen_text(app)
            await T.press(pilot, "l")
            assert name(app) == "ProposalScreen" and str(pdf.name) in T.screen_text(app)
            findings = T.shown(app, "#findings")
            assert f"Found by the doi read from the PDF (page 1): {ZOLLER_DOI}" in findings
            assert T.shown(app, "#proposed") == ZOLL90.expandtabs(4)
            beside = app.screen.query_one("#proposal-pdf")                 # what was read from the PDF, beside the proposal
            assert beside.display and "Haifa University" in T.shown(app, "#pdf-text")
            assert f"doi: {ZOLLER_DOI} (page 1)" in T.shown(app, "#pdf-text") and not app.screen.query("#pdf-page")
            assert f"Read from {pdf.name}" in T.screen_text(app) and "Identifiers found" in T.screen_text(app)
            await T.press(pilot, "e")                                      # editing and checking again keeps it there
            await T.press(pilot, "pagedown", "up", "up", "up", "end", "left", "left", "backspace", "6")
            await T.press(pilot, "ctrl+s")
            assert T.changes(app)["pages"] == ("1053--1065", "1053--1066", "user edit", "changed")
            assert app.screen.query_one("#proposal-pdf").display and "Haifa University" in T.shown(app, "#pdf-text")
            await T.press(pilot, "a")
            assert name(app) != "ProposalScreen" and "Added: Zoll90" in T.shown(app, "#p-message")
            assert "A source record was found by the doi read from the PDF." in T.shown(app, "#p-info")
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8").strip() == ZOLL90.replace("1053--1065", "1053--1066")

    async def narrow():                                                    # in a narrow window too
        async with T.opened(ws, size=(100, 30)) as pilot:
            app = pilot.app
            await add_tab(pilot, 2)
            await T.type_text(pilot, str(pdf))
            await T.press(pilot, "enter")
            await T.press(pilot, "l")
            assert name(app) == "ProposalScreen" and app.screen.query_one("#proposal-pdf").display
            assert "Haifa University" in T.shown(app, "#pdf-text") and "Duplicate: Zoll90" in T.shown(app, "#findings")
            await T.press(pilot, "q")
    T.run(narrow())


@needs_pdflatex
@needs_pypdf
def test_the_pdf_is_chosen_from_the_folder_tree(ws, tmp_path):
    pdf = pdfs.build("doi", tmp_path / "pdfs")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 2)
            await T.type_text(pilot, str(pdf.parent))                 # a folder: the picker starts there
            await T.press(pilot, "ctrl+o")
            tree = app.screen.query_one("#tree")
            assert name(app) == "FilePicker" and str(tree.path) == str(pdf.parent) and "doi.pdf" in T.screen_text(app)
            for _ in range(20):
                if tree.cursor_node is not None and str(tree.cursor_node.label) == "doi.pdf":
                    break
                await T.press(pilot, "down")
            assert str(tree.cursor_node.label) == "doi.pdf"
            await T.press(pilot, "enter")
            assert name(app) != "FilePicker" and app.screen.query_one("#p-path").value == str(pdf)
            assert f"doi: {ZOLLER_DOI} (page 1)" in T.shown(app, "#p-info")     # chosen, and read
            await T.press(pilot, "ctrl+o", "escape")
            assert name(app) != "FilePicker"
    T.run(journey())


@needs_pdflatex
@needs_pypdf
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
            for route in api.model_routes(probe=("dartmouth", "openai")):   # what exactly is missing, as the core says it
                assert route.detail and route.detail in routes
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
            assert app.screen.query_one("#proposal-pdf").display and "Nowhere College" in T.shown(app, "#pdf-text")
            findings = T.shown(app, "#findings")
            sources = {field: row[2] for field, row in T.changes(app).items()}
            assert sources["title"].startswith("read from the PDF") and sources["year"] == "typed"
            assert "Verification: needs_review" in findings and "No source record" in findings
            assert "@article{ExamSamp19," in T.shown(app, "#proposed")
            await T.press(pilot, "a")
            assert name(app) != "ProposalScreen" and "Added: ExamSamp19" in T.shown(app, "#m-message")
    T.run(journey())
    entry = api.entry(ws, "ExamSamp19")
    assert entry.status not in ACCEPTED and entry.human_review is None    # written, unverified, unapproved
    assert "Title = {Plorbnix dynamics in zzyzxqv lattices under qwxzvk forcing}" in entry.raw


@needs_pdflatex
@needs_pypdf
def test_a_route_that_is_set_up_is_listed_without_the_steps_to_set_it_up(ws, tmp_path, monkeypatch):
    """The steps are for a route that is not set up, or not checked. The variable holds a
    token that is no key: only whether it is set is looked at here, and no route is run."""
    monkeypatch.setenv("DARTMOUTH_CHAT_API_KEY", "a-test-token-that-is-not-a-key")
    pdf = pdfs.build("unknown", tmp_path / "pdfs")
    dartmouth, openai = api.model_routes()
    assert (dartmouth.available, openai.available) == (True, None) and dartmouth.how and openai.how

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 2)
            await T.type_text(pilot, str(pdf))
            await T.press(pilot, "enter")
            await T.press(pilot, "m")
            assert name(app) == "RouteScreen"
            routes = " ".join(T.shown(app, "#question").split())
            assert "[1] Dartmouth Chat (the default): set up" in routes and "[2] OpenAI: not checked" in routes
            assert "Create an API key in Dartmouth Chat" not in routes and "free are used" not in routes
            assert "Create an OpenAI API key." in routes                 # not checked: its steps are there
            assert "never a verification or an approval" in routes
            await T.press(pilot, "escape")
    T.run(journey())


@conftest.live_model
@needs_pdflatex
@needs_pypdf
def test_a_real_model_reading_is_proposed_with_page_quotes_and_stays_unverified(ws, tmp_path, monkeypatch):
    key = _dartmouth_key()
    if not key:
        pytest.skip("no Dartmouth Chat key here, so no real model run through the interface")
    for variable in T.refused_network():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("DARTMOUTH_CHAT_API_KEY", key)
    pdf = pdfs.build("unknown", tmp_path / "pdfs")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 2)
            await T.type_text(pilot, str(pdf))
            await T.press(pilot, "enter")
            await T.press(pilot, "m")
            assert "[1] Dartmouth Chat (the default): set up" in T.shown(app, "#question")
            await pilot.press("1")                       # the adapter allows the model 240 s, twice
            await T.settle(pilot, timeout=600)
            assert name(app) == "ProposalScreen" and "read from the PDF by a model" in T.screen_text(app)
            findings = T.shown(app, "#findings")
            assert any(row[2].startswith("model reading, p.1") for row in T.changes(app).values())
            assert "Verification: needs_review" in findings
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


# --- names the typed entry and the source spell differently -----------------------------------------

@pytest.mark.parametrize("choice", ["u", "k"])
def test_a_name_the_source_spells_differently_is_settled_name_by_name(tmp_path, choice):
    """The proposal is one completion offers during a send; that way to it asks GitHub for the
    reference, which this test cannot, so the proposal view is opened on it directly. The
    proposal is made as tests/test_complete_cli.py makes it, from a recorded Crossref deposit."""
    from cdlbib import complete, extra_sources as xs
    from cdlbib.tui.proposal import ProposalScreen
    from cdlbib.workspace import Workspace
    from test_complete_build import RECORDS, sources
    from test_complete_recheck import seed_record
    record, _ = sources("CleeMcCl91")
    raw = complete.render("article", "CleeMcCl91", dict(RECORDS["CleeMcCl91"]["typed"], doi=record["DOI"]))
    ws = Workspace(tmp_path / "lib")
    ws.root.mkdir()
    ws.bib.write_text(raw, encoding="utf-8")
    ws.work.mkdir()
    client = xs.make_client(ws.database, contact=T.CONTACT, offline=True)
    try:
        seed_record(client, record)
        query = complete.Query.from_entry(next(iter(load_entries(ws.bib).values())))
        item = complete.build(query.fields, record)
        item.typed_raw = query.raw
        complete._plan_proposal(ws, item, query, ())
        complete.checked(item, client)
    finally:
        client.cache.close()
    assert api.name_choices(item) == [("author", ["A Cleeremans", "J L McCleeland"], ["A Cleeremans", "J L McClelland"])]

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            app.push_screen(ProposalScreen([item], in_library=True))
            await T.settle(pilot)
            assert name(app) == "ChoiceScreen"                              # only the name that differs is asked
            assert "The author list: the name typed and the name the source gives differ." in T.shown(app, "#question")
            labels = [str(button.label) for button in app.screen.query("Button")]
            assert labels == ["[k] keep typed J L McCleeland", "[u] use source J L McClelland"]
            await T.press(pilot, "escape")                                  # this question has to be answered
            assert name(app) == "ChoiceScreen"
            await T.press(pilot, choice)
            assert name(app) == "ProposalScreen"
            findings = T.shown(app, "#findings")
            if choice == "u":
                assert T.changes(app)["author"][2] == "user edit" and "McClelland" in T.shown(app, "#proposed")
                await T.press(pilot, "a")
                assert "Completed: CleeMcCl91" in app.log_lines
            else:
                assert T.changes(app)["author"][2].startswith("typed (source alternative")
                await T.press(pilot, "s")
    T.run(journey())
    written = ws.bib.read_text(encoding="utf-8")
    if choice == "u":
        assert "McClelland" in written and "McCleeland" not in written
    else:
        assert written == raw


# --- a model reading whose evidence could not be stored -------------------------------------------

@needs_pdflatex
@needs_pypdf
def test_an_entry_written_without_its_model_evidence_stays_on_screen_until_it_is_stored(tmp_path):
    """The reading is the Dartmouth adapter's own code after the model call, over a selection
    of passages (as tests/test_intake_model.py makes it), since no key is here for a real run;
    the proposal view is opened on it directly. The store fails for real: a folder is where
    the database should be."""
    from cdlbib import intake
    from cdlbib.source_passages import materialize
    from cdlbib.tui.proposal import ProposalScreen
    from test_intake_model import SELECTED
    read = api.read_pdf(pdfs.build("unknown", tmp_path / "pdfs"))
    found = materialize({"fields": SELECTED, "uncertainties": ["The issue number is not printed."]},
                        read.pages[:intake.MODEL_PAGES])
    found["provider_trace"] = {"provider": "test selection", "model": None}
    ws = T.library(tmp_path / "lib")
    ws.bib.write_text("", encoding="utf-8")
    proposal = intake.proposal_from_findings(ws, read, found, "dartmouth")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            app.push_screen(ProposalScreen([proposal], pdf=read))
            await T.settle(pilot)
            assert "read from the PDF by a model" in T.screen_text(app)
            assert any(row[2].startswith("model reading, p.1") for row in T.changes(app).values())
            assert "Nowhere College" in T.shown(app, "#pdf-text")           # the page it was read from, beside it
            ws.work.mkdir(exist_ok=True)
            ws.database.mkdir()                                            # the evidence store cannot be opened
            await T.press(pilot, "a")
            assert name(app) == "ProposalScreen"                         # not passed over: it stays, with the reason
            actions = T.shown(app, "#proposal-actions")
            assert "ExamSamp19 was written, but the model reading's evidence was not stored with it:" in actions
            assert "could not be stored" in actions and "[t] try storing the evidence again" in actions
            assert "@article{ExamSamp19," in ws.bib.read_text(encoding="utf-8")
            await T.press(pilot, "a")
            await T.press(pilot, "s")                                      # nothing else is done meanwhile
            assert name(app) == "ProposalScreen"
            await T.press(pilot, "t")                                      # still blocked: the new reason, still there
            assert name(app) == "ProposalScreen" and "could not be stored" in T.shown(app, "#proposal-actions")
            ws.database.rmdir()
            await T.press(pilot, "t")
            assert name(app) != "ProposalScreen"
            assert "The model reading's evidence is stored with ExamSamp19; it is not an approval." in app.log_lines
    T.run(journey())
    entry = api.entry(ws, "ExamSamp19")
    assert entry.status == "needs_review" and entry.human_review is None
    assert entry.external_evidence["pdf_sha256"] == read.sha256 and "title" in entry.external_evidence["fields"]
    assert api.pending_evidence(ws) == []


@needs_pdflatex
@needs_pypdf
def test_evidence_left_waiting_is_listed_in_library_state_and_stored_from_there(tmp_path):
    """After the first failure (a folder where the database should be) the store is refused for
    a second, lasting reason: the entry holds an approval (recorded with the verifier's own
    function, under a fixture name). When that is revoked, p stores the evidence."""
    from cdlbib import intake
    from cdlbib.source_passages import materialize
    from cdlbib.tui.proposal import ProposalScreen
    from cdlbib.verification import Cache, record_approval, record_revocation
    from test_intake_model import SELECTED
    read = api.read_pdf(pdfs.build("unknown", tmp_path / "pdfs"))
    found = materialize({"fields": SELECTED, "uncertainties": []}, read.pages[:intake.MODEL_PAGES])
    found["provider_trace"] = {"provider": "test selection", "model": None}
    ws = T.library(tmp_path / "lib", ZOLL90)
    proposal = intake.proposal_from_findings(ws, read, found, "dartmouth")

    def reviewed(act):
        cache = Cache(ws.database, ledger=ws.revocations)
        try:
            act(cache)
        finally:
            cache.close()

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            app.push_screen(ProposalScreen([proposal], pdf=read))
            await T.settle(pilot)
            ws.work.mkdir(exist_ok=True)
            assert not ws.database.exists()
            ws.database.mkdir()                                            # the evidence store cannot be opened
            await T.press(pilot, "a")
            assert "the evidence is kept, and Library state lists it to store later" in T.shown(app, "#proposal-actions")
            ws.database.rmdir()
            await T.press(pilot, "c")                                      # go on; the entry stays written
            assert name(app) != "ProposalScreen" and "ExamSamp19: left without its model evidence" in app.log_lines
            assert [item.key for item in api.pending_evidence(ws)] == ["ExamSamp19"]
            fingerprint = api.entry(ws, "ExamSamp19").fingerprint
            reviewed(lambda cache: record_approval(cache, ws.bib, "ExamSamp19", fingerprint, dict(
                reviewer="@fixture", source="the PDF", note="checked", github_login="fixture", github_id=1)))
            app.refresh_library(force=True)                                # reading the library tries once, and is refused
            await T.settle(pilot)
            await T.press(pilot, "f7")
            state = T.shown(app, "#state-now")
            assert "Model evidence not yet stored with its entry (p stores it again)\n  ExamSamp19\n" in state
            await T.press(pilot, "p")
            assert "ExamSamp19: the model evidence was not stored:" in T.shown(app, "#state-result")
            assert "human_verified" in T.shown(app, "#state-result") and api.pending_evidence(ws) != []
            reviewed(lambda cache: record_revocation(cache, ws.bib, "ExamSamp19", "to store the evidence", "@fixture"))
            await T.press(pilot, "p")
            assert ("The model reading's evidence is stored with ExamSamp19; it is not an approval."
                    in T.shown(app, "#state-result"))
            assert "Model evidence not yet stored" not in T.shown(app, "#state-now")
            await T.press(pilot, "p")
            assert any("No model evidence is waiting to be stored." in note for note in app.notices)
    T.run(journey())
    assert api.pending_evidence(ws) == []
    entry = api.entry(ws, "ExamSamp19")
    assert entry.external_evidence["pdf_sha256"] == read.sha256 and entry.human_review is None


def test_edited_text_that_could_not_be_checked_is_not_passed_over_by_accept_skip_or_accept_all(ws):
    edited = ZOLL90.replace("1053--1065", "1053--1066")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 1)
            await T.type_text(pilot, ZOLLER_DOI)
            await T.press(pilot, "enter")
            await T.press(pilot, "e")
            await T.press(pilot, "pagedown", "up", "up", "up", "end", "left", "left", "backspace", "6")
            saved = ws.database.read_bytes()
            ws.database.unlink()
            ws.database.mkdir()                                            # the check cannot open its cache
            await T.press(pilot, "ctrl+s")
            ws.database.rmdir()
            ws.database.write_bytes(saved)
            assert name(app) == "ProposalScreen" and T.shown(app, "#proposed") == ZOLL90.expandtabs(4)
            assert "Edited text for this proposal was not checked; e opens it again." in T.shown(app, "#proposal-actions")
            for key in ("a", "s", "A"):                                    # none of them goes past the edited text
                await T.press(pilot, key)
                assert name(app) == "ChoiceScreen" and "edited text that was not checked" in T.shown(app, "#question")
                await T.press(pilot, "escape")
                assert name(app) == "ProposalScreen" and ws.bib.read_text(encoding="utf-8") == ""
            await T.press(pilot, "q")                                      # stopping asks too
            assert name(app) == "ConfirmScreen"
            await T.press(pilot, "n")
            await T.press(pilot, "a")
            await T.press(pilot, "e")                                      # open it again: the edited text is there
            assert name(app) == "TextEditScreen" and app.screen.query_one("#proposal-editor").text == edited
            await T.press(pilot, "ctrl+s")
            assert T.shown(app, "#proposed") == edited.expandtabs(4) and "was not checked" not in T.shown(app, "#proposal-actions")
            await T.press(pilot, "a")
            assert name(app) != "ProposalScreen"
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8").strip() == edited

    async def discarded():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 1)
            await T.type_text(pilot, GAMES_DOI)
            await T.press(pilot, "enter")
            await T.press(pilot, "e")
            await T.press(pilot, "pagedown", "end", "left", "left", "backspace", "3")
            saved = ws.database.read_bytes()
            ws.database.unlink()
            ws.database.mkdir()
            await T.press(pilot, "ctrl+s")
            ws.database.rmdir()
            ws.database.write_bytes(saved)
            await T.press(pilot, "a")
            await T.press(pilot, "d")                                      # discard the edited text, said so
            assert name(app) == "ProposalScreen" and "was not checked" not in T.shown(app, "#proposal-actions")
            await T.press(pilot, "a")
            assert name(app) != "ProposalScreen"
    T.run(discarded())
    assert GAME62 in ws.bib.read_text(encoding="utf-8")                      # the proposal as it was shown


# --- a book, by its ISBN (owner's decision 2026-10-06) ----------------------------------------------

def test_a_book_is_added_by_its_isbn_and_its_source_is_the_catalogue(tmp_path):
    """The lookups are the real Library of Congress and Crossref answers of
    tests/fixtures/intake/books.json.gz, replayed with the network refused."""
    ws = T.library(tmp_path / "books")
    ws.bib.write_text("", encoding="utf-8")
    T.seed_responses(ws, T.ROOT / "tests/fixtures/intake/books.json.gz")
    kaha12 = ("@book{Kaha12,\n\tAddress = {New York, {NY}},\n\tAuthor = {M J Kahana},\n"
              "\tPublisher = {Oxford University Press},\n\tTitle = {Foundations of human memory},\n\tYear = {2012}}")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await add_tab(pilot, 1)
            assert "ISBN:" in T.screen_text(app) and "LCCN:" in T.screen_text(app)      # the tab says what it takes
            await T.type_text(pilot, "ISBN:9780195333244")
            await T.press(pilot, "enter")
            assert name(app) == "ProposalScreen"
            assert T.shown(app, "#proposed") == kaha12.expandtabs(4)
            table = T.changes(app)
            assert table["author"] == ("", "M J Kahana", "loc-catalogue", "filled")
            assert {row[2] for row in table.values()} == {"loc-catalogue"}              # every field: the catalogue
            findings = T.shown(app, "#findings")
            assert "Verification: metadata_verified" in findings
            assert "Built from the Library of Congress catalogue record LCCN 2012007685" in findings
            assert ws.bib.read_text(encoding="utf-8") == ""
            await T.press(pilot, "a")
            assert ws.bib.read_text(encoding="utf-8").strip() == kaha12 and "Added: Kaha12" in app.log_lines
    T.run(journey())
