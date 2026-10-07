"""The Check view: run the format check and the citation gate on chosen entries; the lines of
the running check are in the log."""
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Static

from .. import api, prompts
from . import render
from .widgets import Shown, View


class CheckView(View):
    BINDINGS = [
        Binding("c", "selected", "Check selected"),
        Binding("g", "changed", "Offers, then check changed"),
        Binding("G", "changed(False)", "Check the changed entries, no offers", show=False),
        Binding("m", "format", "Format check"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last = None     # what to draw again when the theme changes

    def compose(self) -> ComposeResult:
        yield Shown(id="check-head", classes="message")
        with Horizontal(classes="row"):
            yield Button("Check selected (c)", id="check-selected")
            yield Button("Offers, then check changed (g)", id="check-changed")
            yield Button("Format check (m)", id="check-format")
        yield Static("G checks the changed entries without the completion offers.", classes="hint")
        with VerticalScroll(classes="pane"):
            yield Shown(id="check-result")

    def activated(self):
        self.state_changed()
        if self.last is None:
            self.query_one("#check-result", Shown).show("The result of a check is shown here.")
        self.query_one("#check-selected", Button).focus()

    def state_changed(self):
        selected = self.app.view("library").selected
        self.query_one("#check-head", Shown).show(
            f"Selected in the Library view: {selected or '(no entry)'}. A check runs the format check of the library, "
            "then the citation check of the chosen entries; its lines appear in the log below (ctrl+l).")

    def recolour(self):
        if self.last is not None:
            self.last()

    @on(Button.Pressed)
    def _pressed(self, event):
        {"check-selected": self.action_selected, "check-changed": self.action_changed,
         "check-format": self.action_format}[event.button.id]()

    # --- actions -----------------------------------------------------------------------------

    def action_selected(self):
        key = self.app.view("library").selected
        if not key:
            self.app.notify("No entry is selected in the Library view.")
            return
        self.app.check_keys([key], f"check {key}")

    def action_changed(self, offers=True):
        """The command line's verify: completion offers for the changed entries first (skipped
        with G, as its --no-complete), then their check."""
        if offers:
            self.app.offer_completion(self._check_changed)
        else:
            self.app.say("completion offers skipped (as `cdlbib verify --no-complete`)")
            self._check_changed()

    def _check_changed(self):
        def call(job):
            keys = [detail.key for detail in api.review_queue(self.app.ws)]
            return keys, (api.check_keys(self.app.ws, keys, progress=job.progress) if keys else None)

        def done(found):
            keys, check = found
            if check is None:
                self._show(lambda out: out.line("No changed entry is waiting: every new or edited entry is verified "
                                                "or approved (compared with the GitHub master)."))
            else:
                self.show_check(keys, check)
            self.app.refresh_library()
        self.app.job("check the changed entries", call, done,
                     lambda exc: self.show_failure("check the changed entries", exc))

    def action_format(self):
        def done(result):
            def draw(out):
                out.head("Format check of the library")
                self._format(out, result, None)
            self._show(draw)
        self.app.job("format check", lambda job: api.check_format(self.app.ws), done,
                     lambda exc: self.show_failure("format check", exc))

    # --- results -----------------------------------------------------------------------------

    def _show(self, draw):
        def again():
            out = self.app.writer()
            draw(out)
            self.query_one("#check-result", Shown).show(out.text)
        self.last = again
        again()

    def _format(self, out, result, keys, chosen_only=False):
        if result.failure:
            out.line(f"  errors found: {result.failure}", "error")
            return
        found = {key: fields for key, fields in result.corrections.items() if keys is None or key in keys}
        if result.ok and chosen_only:
            out.line("  none on the chosen entries (the other entries were not checked)", "success")
        elif result.ok:
            out.line("  format: looks good!", "success")
        elif not found:
            count = len(result.errors)
            out.line(f"  none on the chosen entries ({count} other entr{'y has' if count == 1 else 'ies have'} findings)")
        for key in result.forced:
            if keys is None or key in keys:
                out.line(f"  {key}: {prompts.FORCE_REFUSED}", "error")
        for key, fields in found.items():
            out.line(f"  {key}", "warning", bold=True)
            for name, value in fields.items():
                out.line(f"      {'key' if name == 'ID' else name}: the formatter writes {value}")

    def show_check(self, keys, check):
        def draw(out):
            out.line(f"Checked: {', '.join(keys)}", bold=True)
            out.line("Result: passed" if check.ok else "Result: not passed", "success" if check.ok else "warning")
            out.head("House format")
            self._format(out, check.format, set(keys), chosen_only=check.scope == "keys")
            out.head("Citations")
            citations = check.citations
            if citations is None:
                out.line("  not run", "muted")
                return
            for key, result in citations.checked.items():
                out.part(f"  {key}: ").text.append_text(render.status_text(result["status"], self.app.colour))
                out.line()
                for line in result.get("issues") or []:
                    out.line(f"      {line}", "warning")
            out.head("What the check printed")
            for line in citations.lines:
                out.line(f"  {line}")
        self._show(draw)

    def show_failure(self, label, exc):
        self._show(lambda out: out.line(f"{label}: the check could not be done.", "error").line(str(exc)))
        self.app.notify(str(exc), severity="error", timeout=12)
