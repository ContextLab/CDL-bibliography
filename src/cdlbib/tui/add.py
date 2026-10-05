"""The Add view: find a record by title and authors, by identifier, from a PDF, or type the
entry in. Every way ends in the proposal view (cdlbib.tui.proposal)."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, DataTable, Input, Select, Static, TabbedContent, TabPane

from .. import api
from . import render
from .library import cut
from .proposal import ProposalScreen
from .widgets import ChoiceScreen, FilePicker, Shown, View


PAGE_COLUMNS = 54     # cells the drawn first page is wide (its pane is that plus border, padding and scrollbar)
PAGE_SCALE = 4        # pixels of the rendered page averaged into one cell, across


class AddView(View):
    BINDINGS = [
        Binding("ctrl+f", "find", "Find records", priority=True),
        Binding("space", "mark", "Mark", show=False),
        Binding("ctrl+o", "browse", "Choose a PDF", priority=True),
        Binding("l", "lookup", "Look up the PDF's record"),
        Binding("o", "open_pdf", "Open the PDF"),
        Binding("m", "model", "Read with a model"),
        Binding("t", "manual", "Type it in"),
        Binding("ctrl+s", "draft", "Draft the entry", priority=True),
        Binding("escape", "leave_box", "Leave the box", show=False),
    ]
    DEFAULT_CSS = """
    AddView .form-label { width: 16; padding: 1 1 0 0; color: $cdl-muted; }
    AddView .form-row { height: 3; }
    AddView .form-row Input { width: 1fr; }
    AddView #pdf-page-pane { width: 60; }
    AddView #pdf-info-pane { width: 1fr; }
    AddView #pdf-panes { height: 1fr; }
    AddView #manual-form { height: 1fr; }
    AddView #s-year { width: 12; }
    AddView .form-label.short { width: 7; padding: 1 1 0 1; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.leads = []              # what the search gave
        self.marked = set()          # indexes of the marked leads
        self.search_errors = []
        self.pdf = None              # intake.PdfIntake of the PDF read
        self.pdf_png = None
        self.pdf_png_note = ""
        self.pdf_result = None       # intake.PdfResult of the lookup
        self.model_proposal = None   # the model's reading of the PDF, when one was made
        self.prefill = {}            # what the manual form was filled with from the PDF
        self.fields = ()             # the manual form's fields (api.draft_fields)

    def compose(self) -> ComposeResult:
        with TabbedContent(id="add-tabs"):
            with TabPane("Search", id="add-search"):
                with Horizontal(classes="form-row"):
                    yield Static("Title", classes="form-label")
                    yield Input(placeholder="Title, or some of its words", id="s-title")
                with Horizontal(classes="form-row"):
                    yield Static("Authors", classes="form-label")
                    yield Input(placeholder="One or several surnames, separated by ;", id="s-authors")
                    yield Static("Year", classes="form-label short")
                    yield Input(placeholder="Year", id="s-year")
                    yield Button("Find (ctrl+f)", id="s-find")
                yield Shown(id="s-message", classes="message")
                yield DataTable(id="s-results", cursor_type="row")
            with TabPane("Identifier", id="add-identifier"):
                yield Static("DOI, PMID or arXiv id; several separated by spaces, commas or semicolons",
                             classes="label")
                yield Input(placeholder="10.1002/tea.3660271011, 1706.03762", id="i-ids")
                yield Shown(id="i-message", classes="message")
            with TabPane("PDF", id="add-pdf"):
                with Horizontal(classes="form-row"):
                    yield Static("PDF file", classes="form-label")
                    yield Input(placeholder="Path of the PDF (enter reads it)", id="p-path")
                    yield Button("Choose (ctrl+o)", id="p-browse")
                with Horizontal(classes="row"):
                    yield Button("Look up its record (l)", id="p-lookup")
                    yield Button("Open in the system viewer (o)", id="p-open")
                    yield Button("Read with a model (m)", id="p-model")
                    yield Button("Type it in (t)", id="p-manual")
                yield Shown(id="p-message", classes="message")
                with Horizontal(id="pdf-panes"):
                    with VerticalScroll(id="pdf-page-pane", classes="pane"):
                        yield Shown(id="p-page")
                    with VerticalScroll(id="pdf-info-pane", classes="pane"):
                        yield Shown(id="p-info")
            with TabPane("Manual", id="add-manual"):
                yield Shown(id="m-message", classes="message")
                with Horizontal(classes="form-row"):
                    yield Static("Entry type", classes="form-label")
                    yield Select([("article", "article")], id="m-entrytype", allow_blank=False, value="article")
                    yield Button("Draft the entry (ctrl+s)", id="m-draft")
                yield VerticalScroll(id="manual-form")

    def on_mount(self):
        self.query_one("#s-results", DataTable).add_columns(" ", "In library", "Source", "Authors", "Year", "Title",
                                                            "Identifier", "Journal")
        self._search_message()
        self.query_one("#i-message", Shown).show("enter looks the identifiers up and shows each proposal.")
        self._pdf_message("Type the path of a PDF and press enter, or choose it with ctrl+o.")
        self._manual_message()

    _form_asked = False

    def activated(self):
        if not self._form_asked:
            self._form_asked = True
            self.app.job("read the manual form's fields", lambda job: (api.draft_types(), api.draft_fields()),
                         self._form, quiet=True)
        self._focus_tab()

    def recolour(self):
        self._fill_leads()
        self._pdf_show()

    @property
    def tab(self):
        return self.query_one("#add-tabs", TabbedContent).active

    def _focus_tab(self):
        target = {"add-search": "#s-title", "add-identifier": "#i-ids", "add-pdf": "#p-path",
                  "add-manual": "#m-entrytype"}[self.tab]
        self.query_one(target).focus()

    @on(TabbedContent.TabActivated, "#add-tabs")
    def _tab_shown(self, event):
        event.stop()
        if self.app.active_view == "add" and not self._on_tab_bar():
            self._focus_tab()

    def _on_tab_bar(self):
        """Is the cursor on the row of tab names (left and right move between the tabs there)?"""
        focused = self.app.focused
        return focused is not None and focused is self.query_one("#add-tabs", TabbedContent).query_one("Tabs")

    def on_key(self, event):
        if event.key in ("enter", "down") and self._on_tab_bar():
            event.stop()
            self._focus_tab()

    def check_action(self, action, parameters):
        tabs = {"find": "add-search", "mark": "add-search", "browse": "add-pdf", "lookup": "add-pdf",
                "open_pdf": "add-pdf", "model": "add-pdf", "manual": "add-pdf", "draft": "add-manual"}
        return action not in tabs or tabs[action] == self.tab

    def action_leave_box(self):
        self.query_one("#add-tabs", TabbedContent).query_one("Tabs").focus()

    @on(Button.Pressed)
    def _pressed(self, event):
        {"s-find": self.action_find, "p-browse": self.action_browse, "p-lookup": self.action_lookup,
         "p-open": self.action_open_pdf, "p-model": self.action_model, "p-manual": self.action_manual,
         "m-draft": self.action_draft}[event.button.id]()

    # --- the proposals -----------------------------------------------------------------------

    def propose(self, items, message, pdf=None, origin=""):
        """Show the proposals; ``message(lines)`` is told what was done."""
        if not items:
            return

        def closed(result):
            if result is None:
                return
            message(result["lines"] or ["Nothing was written."])
            if result["written"]:
                self.app.notify("Added: " + ", ".join(result["written"]))
            self.app.refresh_library()
        self.app.push_screen(ProposalScreen(items, pdf=pdf, origin=origin), closed)

    # --- Search ------------------------------------------------------------------------------

    def _search_message(self, lines=None, role=None):
        out = self.app.writer()
        for line in lines or ["Type a title, authors, or both, and press enter. The records found are leads: "
                              "choosing one looks it up and shows the proposed entry."]:
            out.line(line, role)
        self.query_one("#s-message", Shown).show(out.text)

    @on(Input.Submitted, "#s-title, #s-authors, #s-year")
    def _search_entered(self, event):
        self.action_find()

    def action_find(self):
        title = self.query_one("#s-title", Input).value.strip() or None
        authors = [name.strip() for name in self.query_one("#s-authors", Input).value.split(";") if name.strip()]
        year = self.query_one("#s-year", Input).value.strip() or None

        def done(found):
            self.leads, self.marked, self.search_errors = list(found), set(), list(found.errors)
            self.searched = True
            self._fill_leads()
            if self.leads:
                self.query_one("#s-results", DataTable).focus()
        self.app.job("find records", lambda job: api.find_candidates(self.app.ws, title=title, authors=authors,
                                                                     year=year, progress=job.progress),
                     done, lambda exc: self._search_message([str(exc)], "error"))

    def _fill_leads(self):
        table, colour = self.query_one("#s-results", DataTable), self.app.colour
        position = table.cursor_row
        table.clear()
        for number, lead in enumerate(self.leads):
            there = lead.get("in_library")
            table.add_row(Text("●" if number in self.marked else " ", colour("accent")),
                          Text(there or "", colour("warning")), ", ".join(lead.get("sources") or [lead.get("source", "")]),
                          cut(lead.get("authors"), 26), lead.get("year") or "", cut(lead.get("title"), 48),
                          lead.get("doi") or lead.get("arxiv") or lead.get("pmid") or "", cut(lead.get("journal"), 30),
                          key=str(number))
        if self.leads:
            table.move_cursor(row=min(position or 0, len(self.leads) - 1))
        if not self.searched:
            return
        out = self.app.writer()
        count = len(self.leads)
        out.line(f"{count} record{'' if count == 1 else 's'} found. enter proposes the selected one (space marks "
                 "several). “In library” names the entry that is the same work." if count else "No record was found.")
        for source, reason in self.search_errors:
            out.line(f"{source} did not answer: {reason}", "warning")
        self.query_one("#s-message", Shown).show(out.text)

    searched = False

    def action_mark(self):
        table = self.query_one("#s-results", DataTable)
        if not table.has_focus or not self.leads:
            return
        self.marked ^= {table.cursor_row}
        self._fill_leads()

    @on(DataTable.RowSelected, "#s-results")
    def _lead_chosen(self, event):
        chosen = sorted(self.marked) or [event.cursor_row]
        leads = [self.leads[number] for number in chosen]

        def call(job):
            return api.propose_new(self.app.ws, [api.candidate_query(lead) for lead in leads])
        self.app.job("look up the chosen record" + ("s" if len(leads) > 1 else ""), call,
                     lambda results: self._proposed(results, self._search_message, "search"),
                     lambda exc: self._search_message([str(exc)], "error"))

    def _proposed(self, results, message, origin, pdf=None):
        for label, reason in results.errors:
            self.app.say(f"{label}: {reason}")
        self.propose(list(results), message, pdf=pdf, origin=origin)

    # --- Identifier --------------------------------------------------------------------------

    @on(Input.Submitted, "#i-ids")
    def _identifiers_entered(self, event):
        queries = [part for part in re.split(r"[\s,;]+", event.value.strip()) if part]
        if not queries:
            return

        def message(lines, role=None):
            out = self.app.writer()
            for line in lines:
                out.line(line, role)
            self.query_one("#i-message", Shown).show(out.text)
        self.app.job(f"look up {len(queries)} identifier{'' if len(queries) == 1 else 's'}",
                     lambda job: api.propose_new(self.app.ws, queries, progress=job.progress),
                     lambda results: self._proposed(results, message, "identifier"),
                     lambda exc: message([str(exc)], "error"))

    # --- PDF ---------------------------------------------------------------------------------

    def _pdf_message(self, *lines, role=None):
        out = self.app.writer()
        for line in lines:
            out.line(line, role)
        self.query_one("#p-message", Shown).show(out.text)

    def action_browse(self):
        typed = self.query_one("#p-path", Input).value.strip()

        def chosen(path):
            if path is not None:
                self.query_one("#p-path", Input).value = str(path)
                self._read_pdf(str(path))
        self.app.push_screen(FilePicker(Path(typed).expanduser() if typed else Path.home(), suffix=".pdf"), chosen)

    @on(Input.Submitted, "#p-path")
    def _path_entered(self, event):
        if event.value.strip():
            self._read_pdf(event.value.strip())

    def _read_pdf(self, path):
        path = str(Path(path).expanduser())

        def read(pdf):
            self.pdf, self.pdf_png, self.pdf_result, self.model_proposal = pdf, None, None, None
            self.pdf_png_note = "drawing the first page ..."
            self._pdf_show()
            if pdf.problem:
                self._pdf_message(f"The PDF could not be read as usual: {pdf.problem}"
                                  + (f" ({pdf.detail})" if pdf.detail else ""), role="warning")
            else:
                self._pdf_message("Read. l looks up its source record; o opens the PDF in the system viewer.")
            self.query_one("#p-lookup", Button).focus()
            self.app.job("draw the first page", lambda job: api.render_first_page(pdf.path, width=PAGE_COLUMNS * PAGE_SCALE), drawn,
                         not_drawn, quiet=True)

        def drawn(png):
            if self.pdf is not None:
                self.pdf_png, self.pdf_png_note = png, ""
                self._pdf_show()

        def not_drawn(exc):
            self.pdf_png_note = f"The first page is not drawn: {exc}"
            self._pdf_show()
        self.app.job(f"read {Path(path).name}", lambda job: api.read_pdf(path, progress=job.progress), read,
                     lambda exc: self._pdf_message(str(exc), role="error"))

    def _pdf_show(self):
        pdf, colour = self.pdf, self.app.colour
        page, info = self.query_one("#p-page", Shown), self.query_one("#p-info", Shown)
        if pdf is None:
            page.show("")
            info.show("")
            return
        if self.pdf_png is not None:
            try:
                page.show(render.half_blocks(self.pdf_png, PAGE_COLUMNS))
            except ValueError as exc:
                page.show(f"The first page is not drawn: {exc}")
        else:
            page.show(Text(self.pdf_png_note, colour("muted")))
        out = self.app.writer()
        out.line(str(pdf.path), bold=True)
        if pdf.problem:
            out.line(f"problem: {pdf.problem}" + (f" ({pdf.detail})" if pdf.detail else ""), "warning")
        if pdf.ocr:
            out.line("The text is OCR output; it can misread characters.", "warning")
        out.head("Identifiers found")
        for found in pdf.identifiers or [None]:
            if found is None:
                out.line("  (none)", "muted")
                continue
            where = "the PDF's metadata" if found.page is None else f"page {found.page}"
            out.line(f"  {found.kind}: {found.value} ({where})")
            out.line(f"      “{found.quote}”", "muted")
        out.head("Title read")
        out.line(f"  {pdf.title_guess}" + (f" ({pdf.title_source})" if pdf.title_source else "") if pdf.title_guess
                 else "  (none)", None if pdf.title_guess else "muted")
        if self.pdf_result is not None:
            out.head("Lookup")
            out.line(f"  {self.pdf_result.message}")
            for line in self.pdf_result.tried:
                out.line(f"    {line}", "muted")
        out.head("Text of the first page")
        out.line(pdf.first_page_text.strip() or "(no text)")
        info.show(out.text)

    def _need_pdf(self):
        if self.pdf is None:
            self.app.notify("Read a PDF first: type its path and press enter, or ctrl+o.")
            return False
        return True

    def action_open_pdf(self):
        if not self._need_pdf():
            return
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        if not shutil.which(opener):
            self._pdf_message(f"No program to open files was found ({opener}); the PDF is at {self.pdf.path}",
                              role="warning")
            return
        subprocess.Popen([opener, str(self.pdf.path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._pdf_message(f"Opened {self.pdf.path} in the system viewer.")

    def action_lookup(self):
        if not self._need_pdf():
            return
        pdf = self.pdf

        def done(result):
            self.pdf_result = result
            self._pdf_show()
            if result.proposal is not None:
                self._pdf_message(result.message)
                self.propose([result.proposal], lambda lines: self._pdf_message(*lines), origin=pdf.path.name)
                return
            self._pdf_message(result.message, role="warning")
            self._no_record(result)
        self.app.job(f"look up the record of {pdf.path.name}",
                     lambda job: api.propose_from_pdf(self.app.ws, pdf, progress=job.progress), done,
                     lambda exc: self._pdf_message(str(exc), role="error"))

    def _no_record(self, result):
        """Nothing matched: similar records to choose from, then a model, then the form."""
        choices = [(str(number), f"lead{number}", render.lead(candidate))
                   for number, candidate in enumerate(result.candidates[:9], 1)]
        choices += [("m", "model", "Read the PDF with a language model (each field with its page and quotation)"),
                    ("t", "manual", "Type the entry in; the form is filled with what was read"),
                    ("n", "nothing", "Nothing now")]

        def chosen(value):
            if value == "model":
                self.action_model()
            elif value == "manual":
                self.action_manual()
            elif value and value.startswith("lead"):
                lead = result.candidates[int(value[4:]) - 1]
                self.app.job("look up the chosen record",
                             lambda job: api.propose_new(self.app.ws, [api.candidate_query(lead)]),
                             lambda results: self._proposed(results, lambda lines: self._pdf_message(*lines),
                                                            self.pdf.path.name),
                             lambda exc: self._pdf_message(str(exc), role="error"))
        self.app.push_screen(ChoiceScreen("\n".join([result.message] + [f"  {line}" for line in result.tried]),
                                          choices, wide=True), chosen)

    def action_model(self, probe=()):
        if not self._need_pdf():
            return
        pdf = self.pdf

        def routes_read(routes):
            out = self.app.writer()
            out.line("Which model reads the PDF? A reading proposes fields with the page and quotation of each; "
                     "it is never a verification or an approval.")
            rows = []
            for number, route in enumerate(routes, 1):
                state = {True: "set up", False: "not set up", None: "not checked"}[route.available]
                out.line()
                out.line(f"[{number}] {route.label}{' (the default)' if route.default else ''}: {state}",
                         "muted" if route.available is False else None, bold=route.available is not False)
                out.line(f"    {route.how}", "muted")
                rows.append((str(number), route.name, f"{route.label}: {state}", route.available is False))
            rows.append(("c", "check", "Check which are set up (reads the system keychain)", False))
            rows.append(("t", "manual", "Type the entry in instead", False))

            def chosen(value):
                if value == "check":
                    self.action_model(probe=tuple(route.name for route in routes))
                elif value == "manual":
                    self.action_manual()
                elif value:
                    self._model_read(pdf, value)
            self.app.push_screen(RouteScreen(out.text, rows), chosen)
        self.app.job("read which model routes are set up", lambda job: api.model_routes(probe=probe), routes_read,
                     lambda exc: self._pdf_message(str(exc), role="error"))

    def _model_read(self, pdf, route):
        def done(proposal):
            self.model_proposal = proposal
            self._pdf_message("The model's reading is shown as a proposal; it is unverified.")
            self.propose([proposal], lambda lines: self._pdf_message(*lines), pdf=pdf, origin=f"{pdf.path.name}, {route}")

        def failed(exc):
            self._pdf_message(str(exc), "t opens the manual form, filled with what was read.", role="error")
        self.app.job(f"read {pdf.path.name} with {route}",
                     lambda job: api.read_pdf_with_model(self.app.ws, pdf, route=route, progress=job.progress),
                     done, failed)

    def action_manual(self):
        if not self._need_pdf():
            return
        pdf, proposal = self.pdf, self.model_proposal

        def done(prefill):
            self.prefill = dict(prefill)
            for name in self.fields:
                self.query_one(f"#m-{name}", Input).value = self.prefill.get(name, "")
            self._manual_message()
            self.query_one("#add-tabs", TabbedContent).active = "add-manual"
        self.app.job("fill the form from the PDF", lambda job: api.manual_prefill(pdf, proposal), done,
                     lambda exc: self._pdf_message(str(exc), role="error"), quiet=True)

    # --- Manual ------------------------------------------------------------------------------

    def _form(self, found):
        types, self.fields = found
        self.query_one("#m-entrytype", Select).set_options([(name, name) for name in types])
        self.query_one("#m-entrytype", Select).value = types[0]
        form = self.query_one("#manual-form", VerticalScroll)
        for name in self.fields:
            form.mount(Horizontal(Static(name, classes="form-label"), Input(id=f"m-{name}"), classes="form-row"))

    def _manual_message(self, lines=None, role=None):
        out = self.app.writer()
        if lines is None:
            out.line("Type the entry's fields; ctrl+s puts them in house format and shows the draft. A typed entry "
                     "has no source record: it stays unverified until a check or an approval.")
            if self.prefill:
                out.line(f"Filled from the PDF: {', '.join(sorted(self.prefill))}. A value left as it was read is "
                         "marked as read from the PDF, not typed.", "accent")
        for line in lines or []:
            out.line(line, role)
        self.query_one("#m-message", Shown).show(out.text)

    def action_draft(self):
        values = {name: self.query_one(f"#m-{name}", Input).value.strip() for name in self.fields}
        read = {name: value for name, value in self.prefill.items() if values.get(name) == value}
        typed = {name: value for name, value in values.items() if value and name not in read}
        kind = self.query_one("#m-entrytype", Select).value
        if not typed and not read:
            self._manual_message(["Nothing is typed yet."], "warning")
            return

        def message(lines, role=None):
            self._manual_message(lines, role)
        self.app.job("draft the typed entry",
                     lambda job: api.draft_manual(self.app.ws, typed, entry_type=kind, prefill=read or None),
                     lambda proposal: self.propose([proposal], message, origin="manual form"),
                     lambda exc: message([str(exc)], "error"))


class RouteScreen(ChoiceScreen):
    """The model routes: one that is not set up is listed, greyed, with how to set it up."""

    def __init__(self, question, rows):
        super().__init__(question, [(letter, value, label) for letter, value, label, _ in rows], wide=True)
        self.off = {value for _, value, _, off in rows if off}

    def on_mount(self):
        super().on_mount()
        for value in self.off:
            button = self.query_one(f"#choice-{value}", Button)
            button.disabled = True
            button.add_class("greyed")

    def on_key(self, event):
        for letter, value, _ in self.choices:
            if event.character == letter and value in self.off:
                event.stop()
                event.prevent_default()          # ChoiceScreen's own handler is not run for this key
                self.app.notify("That route is not set up; how to set it up is written above.")
                return
