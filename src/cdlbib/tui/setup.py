"""The Setup view: what cdlbib can use on this computer, the TeX link, and a paper's export."""
import os

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from rich.text import Text
from textual.widgets import Button, Input, Static

from .. import api, deps, prompts
from ..errors import ExportFailed, TexLinkRefused
from .widgets import Shown, View


class SetupView(View):
    BINDINGS = [
        Binding("c", "check", "Check"),
        Binding("l", "link", "Link"),
        Binding("x", "unlink", "Unlink"),
        Binding("b", "export_bib", "Write .bib"),
        Binding("B", "export_bbl", "Write .bbl"),
        Binding("escape", "leave_box", "Leave the box", show=False),
    ]
    DEFAULT_CSS = """
    SetupView #setup-pane { height: 1fr; }
    SetupView #setup-result-pane { height: auto; max-height: 9; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.report = None       # api.SetupReport
        self.routes = []
        self.tex = None          # the TeX link's status, as last told
        self.result = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="pane", id="setup-pane"):
            yield Shown(id="setup-report")
        with Horizontal(classes="row"):
            yield Button("Check everything (c)", id="setup-check")
            yield Button("Link cdl.bib into TeX (l)", id="setup-link")
            yield Button("Remove the link (x)", id="setup-unlink")
        yield Static("Export what a paper cites", classes="label")
        with Horizontal(classes="form-row"):
            yield Static("Paper", classes="form-label")
            yield Input(placeholder="main .tex file, folder, or .aux/.bcf file", id="x-paper")
        with Horizontal(classes="form-row"):
            yield Static("Write to", classes="form-label")
            yield Input(placeholder="optional; default: beside the paper", id="x-out")
        with Horizontal(classes="form-row"):
            yield Static("Style files", classes="form-label")
            yield Input(placeholder=f"optional, for a .bbl; several separated by {os.pathsep}", id="x-inputs")
        with Horizontal(classes="row"):
            yield Button(Text(self.FORCE[False]), id="x-force")
            yield Button("Write the .bib (b)", id="setup-bib")
            yield Button("Write the .bbl (B)", id="setup-bbl")
        with VerticalScroll(classes="pane empty", id="setup-result-pane"):
            yield Shown(id="setup-result")

    FORCE = {False: "[ ] Replace an existing file", True: "[x] Replace an existing file"}
    force = False

    def toggle_force(self):
        self.force = not self.force
        self.query_one("#x-force", Button).label = Text(self.FORCE[self.force])

    def activated(self):
        self.query_one("#setup-check", Button).focus()
        if self.report is None:
            self._read(probe=())

    def recolour(self):
        self._show()
        if self.result is not None:
            self.result()

    def action_leave_box(self):
        self.query_one("#setup-check", Button).focus()

    @on(Button.Pressed)
    def _pressed(self, event):
        {"x-force": self.toggle_force, "setup-check": self.action_check, "setup-link": self.action_link, "setup-unlink": self.action_unlink,
         "setup-bib": self.action_export_bib, "setup-bbl": self.action_export_bbl}[event.button.id]()

    # --- the report --------------------------------------------------------------------------

    def _read(self, probe):
        def call(job):
            report = api.setup_report(self.app.ws, probe=probe, progress=job.progress)
            routes = api.model_routes(probe=("dartmouth", "openai") if probe else ())
            return report, routes

        def done(found):
            self.report, self.routes = found
            self.tex = self.report.tex
            self._show()
        self.app.job("check what this computer has" if probe else "read the setup", call, done)

    def action_check(self):
        self._read(probe="all")

    def _show(self):
        report, out = self.report, self.app.writer()
        if report is None:
            out.line("reading ...", "muted")
            self.query_one("#setup-report", Shown).show(out.text)
            return
        status, found = self.tex, report.where
        out.line(f"library: {found.root}", bold=True)
        out.line(f"chosen by: {prompts.CHOSEN_BY[found.origin]}")
        out.head("TeX link (l links cdl.bib into your TeX tree; x removes the link)")
        for line in prompts.tex_state_lines(status):
            out.line(f"  {line}", ("success" if status.state == "linked" else "warning") if line.startswith("state: ")
                     else None)
        out.head("Available on this computer")
        for feature in report.features:
            known = feature.available
            state = "not checked" if known is None else "yes" if known else "no"
            role = "success" if known else "muted"
            out.part(f"  {feature.name}: {state}", role, bold=bool(known)).line(
                f" ({feature.detail}{'; ' + feature.version if feature.version else ''})", role)
            if feature.how:
                out.line(f"      {feature.how}", "muted")
        if any(feature.available is None for feature in report.features):
            out.line("  c checks what was not checked: it asks gh who is logged in and reads the system keychain "
                     "(macOS may show a dialog).", "accent")
        out.head("Models that can read a PDF")
        for route in self.routes:
            known = route.available
            state = "not checked" if known is None else "set up" if known else "not set up"
            out.line(f"  {route.label}{' (the default)' if route.default else ''}: {state}",
                     "success" if known else "muted", bold=bool(known))
            if route.detail and not known:
                out.line(f"      {route.detail}", "muted")
            out.line(f"      {route.how}", "muted")
        self.query_one("#setup-report", Shown).show(out.text)

    def _result(self, draw):
        def again():
            out = self.app.writer()
            draw(out)
            self.query_one("#setup-result", Shown).show(out.text)
            self.query_one("#setup-result-pane").remove_class("empty")
        self.result = again
        again()

    # --- the TeX link ------------------------------------------------------------------------

    def action_link(self, replace=False):
        ws = self.app.ws

        def linked(status):
            self.tex = status
            self._show()

            def draw(out):
                for line in status.changes:
                    out.line(line)
                out.line(f"state: {prompts.tex_state(status)}", "success" if status.state == "linked" else "warning")
            self._result(draw)
            self.app.say(f"TeX link: {prompts.tex_state(status)}")

        def refused(exc):
            if isinstance(exc, TexLinkRefused) and not replace:
                self.app.confirm(f"{exc}\n\nMove it aside (it is kept) and make the link?",
                                 lambda: self.action_link(replace=True), yes="Move it aside and link")
            self._result(lambda out: out.line(str(exc), "error"))

        def go():
            self.app.job("link cdl.bib into the TeX tree", lambda job: api.tex_link(ws, replace=replace), linked, refused)
        if deps.ask() and not replace and self.tex is not None:
            self.app.confirm(f"Link {self.tex.link} to {ws.bib}?", go, yes="Link")
        else:
            go()

    def action_unlink(self):
        def done(found):
            def draw(out):
                out.line(f"removed {found.link}" if found.removed else f"nothing removed at {found.link}: {found.reason}")
                for line in found.notes:
                    out.line(line)
            self._result(draw)
            self._read(probe=())
        self.app.confirm("Remove the link cdlbib made in your TeX tree? Manuscripts that name cdl.bib without a path "
                         "will no longer find it.",
                         lambda: self.app.job("remove the TeX link", lambda job: api.tex_unlink(), done,
                                              lambda exc: self._result(lambda out: out.line(str(exc), "error"))),
                         yes="Remove the link")

    # --- export ------------------------------------------------------------------------------

    def _export(self, bbl, engine=None):
        paper = self.query_one("#x-paper", Input).value.strip()
        out_path = self.query_one("#x-out", Input).value.strip() or None
        inputs = [part.strip() for part in self.query_one("#x-inputs", Input).value.split(os.pathsep) if part.strip()]
        force, ws = self.force, self.app.ws
        if not paper:
            self._result(lambda out: out.line("Name the paper first: its main .tex file, its folder, or a .aux/.bcf "
                                              "file.", "warning"))
            return
        paper, inputs = os.path.expanduser(paper), [os.path.expanduser(item) for item in inputs]
        out_path = os.path.expanduser(out_path) if out_path else None

        def wrote_bbl(made):
            count = len(made.keys)

            def draw(out):
                out.line(f"wrote {made.path}: {made.backend}" + (f", style {made.style}" if made.style else "")
                         + f", {made.engine}, {count} cited key{'' if count == 1 else 's'}"
                         + (" and every other entry (\\nocite{*})" if made.cited.all_entries else ""), "success")
                for line in made.notes:
                    out.line(line)
            self._result(draw)
            self.app.say(f"wrote {made.path}")

        def wrote_bib(made):
            cited = made.cited
            read_from = {"aux": "the .aux file", "bcf": "the .bcf file", "compiled": "a fresh LaTeX run of the paper",
                         "source": "the .tex source"}[cited.how]
            count, entries = len(cited.keys), len(made.written)

            def draw(out):
                out.line(f"citations read from {read_from}: {count} key{'' if count == 1 else 's'}"
                         + (" and \\nocite{*} (every entry)" if cited.all_entries else ""))
                for line in made.notes:
                    out.line(line)
                out.line(f"wrote {made.path}: {entries} entr{'y' if entries == 1 else 'ies'} from {ws.bib}", "success")
                if made.parents:
                    out.line("included because a cited entry inherits from them: " + ", ".join(made.parents))
                if made.missing:
                    out.line("cited, but not in the library: " + ", ".join(str(item) for item in made.missing), "error")
            self._result(draw)
            self.app.say(f"wrote {made.path}")

        def failed(exc):
            def draw(out):
                out.line(str(exc), "error")
                if isinstance(exc, ExportFailed) and exc.names:
                    out.line("  " + ", ".join(str(name) for name in exc.names), "warning")
            self._result(draw)
            if bbl and engine is None and isinstance(exc, ExportFailed) and exc.kind == "engine_choice" and exc.names:
                named = str(exc.names[0])    # the engine the core names; running it is the person's decision
                self.app.confirm(f"{exc}\n\nCompile this paper with {named} now?",
                                 lambda: self._export(True, engine=named), yes=f"Run {named}", no="Do not run it")
        if bbl:
            self.app.job("write the paper's .bbl (runs LaTeX on the paper's files)" if engine is None
                         else f"write the paper's .bbl with {engine}",
                         lambda job: api.export_bbl(ws, paper, out=out_path, inputs=inputs, engine=engine, force=force),
                         wrote_bbl, failed)
        else:
            self.app.job("write the paper's .bib",
                         lambda job: api.export_bib(ws, paper, out=out_path, inputs=inputs, force=force),
                         wrote_bib, failed)

    def action_export_bib(self):
        self._export(False)

    def action_export_bbl(self):
        self._export(True)
