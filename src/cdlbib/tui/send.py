"""The Send view: what will be sent, the completion offers, then the one checked send."""
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static

from .. import api, prompts
from ..errors import GateFailed
from .widgets import Shown, View, focus_now


class SendView(View):
    BINDINGS = [
        Binding("s", "send", "Send"),
        Binding("S", "send(False)", "Send without completion offers", show=False),
        Binding("r", "refresh", "Read state again"),
        Binding("escape", "leave_box", "Leave the box", show=False),
    ]

    DEFAULT_CSS = """
    SendView #send-summary { width: 1fr; margin-right: 2; }
    SendView .form-label { width: 9; }
    SendView #send-state-pane { height: auto; max-height: 50%; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result = None       # draws the result of the last send again
        self.sending = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="pane", id="send-state-pane"):
            yield Shown(id="send-state")
        with Horizontal(classes="form-row"):
            yield Static("Summary", classes="form-label")
            yield Input(placeholder="optional: one line, the pull request's title", id="send-summary")
            yield Button("Send (s)", id="send-go", variant="primary")
        yield Static("S sends without the completion offers (the checks still run).", classes="hint")
        with VerticalScroll(classes="pane empty", id="send-result-pane"):
            yield Shown(id="send-result")

    def activated(self):
        self.state_changed()
        focus_now(self.query_one("#send-go", Button))

    def recolour(self):
        self.state_changed()
        if self.result is not None:
            self.result()

    def action_leave_box(self):
        focus_now(self.query_one("#send-go", Button))

    @on(Button.Pressed, "#send-go")
    def _pressed(self, event):
        self.action_send()

    @on(Input.Submitted, "#send-summary")
    def _entered(self, event):
        focus_now(self.query_one("#send-go", Button))

    # --- what will be sent -------------------------------------------------------------------

    def state_changed(self):
        state, out = self.app.state, self.app.writer()
        if state is None:
            out.line("reading the library's state ...", "muted")
        else:
            out.line("What a send does", bold=True)
            out.line("  Offers completion for new or edited entries, runs the format check and the citation check "
                     "of every new or edited entry, commits cdl.bib and verification/ on a branch, pushes it to "
                     "your fork and opens or updates the pull request. Other files are left as they are.", "muted")
            out.head("Will be sent")
            if state.pending is None:
                out.line("  (nothing can be sent from here)", "muted")
            approvals = state.approvals or []
            for path in state.pending or ([] if state.pending is None or approvals else [None]):
                out.line("  (no changed file)" if path is None else f"  {path}", "muted" if path is None else "accent")
            if approvals:
                out.head("Approvals that will be sent (the send adds them to verification/approvals.jsonl)")
                for item in approvals:
                    out.line(f"  {item['key']}, approved by @{item['login']}", "accent")
                if state.login is None:
                    out.line("  GitHub has not been asked who is logged in (r asks): only the approvals recorded "
                             "under that login are sent.", "muted")
            if state.unsent_approvals:
                out.head("Approvals that will not be sent")
                for item in state.unsent_approvals:
                    out.line(f"  {item['key']}: not sent: {item['why']}", "warning")
            if state.unrelated:
                out.head("Other changed files (left as they are)")
                for path in state.unrelated:
                    out.line(f"  {path}", "muted")
            out.head("Branch")
            out.line(f"  {state.branch or '(none)'}")
            if state.pull_request is not None:
                out.line(f"  pull request: {state.pull_request.url} ({state.pull_request.state})")
            for note in state.notes:
                out.line(f"  {note}", "warning")
        self.query_one("#send-state", Shown).show(out.text)

    def action_refresh(self):
        self.app.job("read the library's state",
                     lambda job: api.library_state(self.app.ws, refresh=True, progress=job.progress), self.app._state)

    # --- sending -----------------------------------------------------------------------------

    def _result(self, draw):
        def again():
            out = self.app.writer()
            draw(out)
            self.query_one("#send-result", Shown).show(out.text)
            self.query_one("#send-result-pane").remove_class("empty")
        self.result = again
        again()

    def action_send(self, offers=True):
        if self.sending:
            self.app.notify("A send is already under way.")
            return
        state = self.app.state
        files = ", ".join(state.pending) if state is not None and state.pending else "the changes of this library"
        approvals = (state.approvals or []) if state is not None else []
        if approvals:
            said = ("the approval of " if len(approvals) == 1 else "the approvals of ") + ", ".join(
                item["key"] for item in approvals)
            files = f"{files} and {said}" if state.pending else said
        first = ("Completion is offered for new or edited entries first; then the checks run"
                 if offers else "Completion offers are skipped; the checks run")
        self.app.confirm(f"Send {files} as a pull request from your fork?\n\n{first}; nothing is sent unless they pass.",
                         lambda: self.start(offers), yes="Send")

    def start(self, offers=True):
        """Completion offers, one entry at a time (unless skipped), then the send."""
        self.sending = True
        if not offers:
            self.app.say("completion offers skipped (as `cdlbib send --no-complete`)")
            self._send()
            return
        self._result(lambda out: out.line("Looking for entries a source can complete ...", "muted"))
        self.app.offer_completion(self._send)

    def _send(self):
        ws, summary = self.app.ws, self.query_one("#send-summary", Input).value.strip() or None
        self._result(lambda out: out.line("Checking and sending; the lines of the checks are in the log ...", "muted"))

        def call(job):
            def report(check):
                fmt = check.format
                if fmt.failure:
                    job.progress(f"errors found: {fmt.failure}")
                elif fmt.ok:
                    job.progress("format: looks good!")
                else:
                    job.progress("format: errors found in " + ", ".join(str(key) for key in fmt.errors))
                    for key in fmt.forced:
                        job.progress(f"  {key}: {prompts.FORCE_REFUSED}")
                    for key, fields in fmt.corrections.items():
                        for name, value in fields.items():
                            job.progress(f"  {key}: {'key' if name == 'ID' else name}: the formatter writes {value}")
            return api.send_checked(ws, summary=summary, progress=job.progress, report=report,
                                    allow_fork_creation=job.allow_fork)

        def done(result):
            self.sending = False

            def draw(out):
                out.line("Sent.", "success", bold=True)
                if result.created_fork:
                    out.line(f"created fork {result.fork}")
                if result.files:
                    out.line("committed: " + ", ".join(result.files))
                if result.approvals:
                    out.line("approvals sent: " + ", ".join(result.approvals))
                out.line(f"pull request: {result.url}", "accent", bold=True)
                out.line(f"you are now on branch {result.branch}")
                if result.left:
                    out.line("left uncommitted: " + ", ".join(result.left))
            self._result(draw)
            self.app.say(f"pull request: {result.url}")
            self.app.notify(f"pull request: {result.url}", timeout=15)
            self.action_refresh()
            self.app.refresh_library(force=True)

        def failed(exc):
            self.sending = False

            def draw(out):
                out.line("Not sent.", "error", bold=True)
                out.line(str(exc))
                check = exc.check if isinstance(exc, GateFailed) else None
                if check is not None and check.citations is not None and check.citations.unresolved:
                    out.head("Entries that are not verified or approved")
                    for key in check.citations.unresolved:
                        out.line(f"  {key}", "warning")
                if check is not None and not check.format.ok:
                    out.head("House format")
                    for key in check.format.errors:
                        out.line(f"  {key}", "warning")
            self._result(draw)
            self.app.notify("Not sent; the reason is in the Send view.", severity="warning", timeout=10)
            self.app.refresh_library()
        self.app.job("check and send", call, done, failed)
