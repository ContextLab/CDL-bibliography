"""The Send view: what will be sent, the completion offers, then the one checked send."""
import re

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static

from .. import api, deps
from ..errors import CdlbibError, GateFailed, PublishRefused
from .proposal import ProposalScreen
from .widgets import Shown, View


class SendView(View):
    BINDINGS = [
        Binding("s", "send", "Send"),
        Binding("r", "refresh", "Read the state again"),
        Binding("escape", "leave_box", "Leave the box", show=False),
    ]

    DEFAULT_CSS = """
    SendView #send-summary { width: 1fr; }
    SendView #send-state-pane { height: auto; max-height: 50%; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result = None       # draws the result of the last send again
        self.sending = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="pane", id="send-state-pane"):
            yield Shown(id="send-state")
        yield Static("Summary: one line describing the change (optional; the pull request's title)", classes="label")
        with Horizontal(classes="row"):
            yield Input(placeholder="e.g. Add Zoller 1990", id="send-summary")
            yield Button("Send (s)", id="send-go", variant="primary")
        with VerticalScroll(classes="pane", id="send-result-pane"):
            yield Shown(id="send-result")

    def activated(self):
        self.state_changed()
        self.query_one("#send-go", Button).focus()

    def recolour(self):
        self.state_changed()
        if self.result is not None:
            self.result()

    def action_leave_box(self):
        self.query_one("#send-go", Button).focus()

    @on(Button.Pressed, "#send-go")
    def _pressed(self, event):
        self.action_send()

    @on(Input.Submitted, "#send-summary")
    def _entered(self, event):
        self.query_one("#send-go", Button).focus()

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
            for path in state.pending or ([] if state.pending is None else [None]):
                out.line("  (no changed file)" if path is None else f"  {path}", "muted" if path is None else "accent")
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
        self.result = again
        again()

    def action_send(self):
        if self.sending:
            self.app.notify("A send is already under way.")
            return
        state = self.app.state
        files = ", ".join(state.pending) if state is not None and state.pending else "the changes of this library"
        self.app.confirm(f"Send {files} as a pull request from your fork?\n\nCompletion is offered for new or edited "
                         "entries first; then the checks run; nothing is sent unless they pass.",
                         self.start, yes="Send")

    def start(self):
        """Completion offers, one entry at a time, then the send."""
        self.sending = True
        self._result(lambda out: out.line("Looking for entries a source can complete ...", "muted"))
        ws, holder = self.app.ws, {}

        def first(job):
            if ("stop", str(ws.bib)) in self.app.seen:
                return None
            holder["offers"] = api.completion_offers(ws, seen=self.app.seen)
            return next(holder["offers"], None)

        def following(job):
            return next(holder["offers"], None)

        def unavailable(exc):
            self.app.say(f"Completion unavailable: {exc}")
            self._send()

        def offered(offer):
            if offer is None:
                self._send()
            elif offer.error is not None:
                self.app.say(f"{offer.key}: completion unavailable: {offer.error}")
                seen(offer.key, [], False)
            elif not offer.proposals:
                seen(offer.key, [], False)
            else:
                self.app.push_screen(ProposalScreen(offer.proposals, in_library=True, origin=f"completion of {offer.key}"),
                                     lambda result: seen(offer.key, (result or {}).get("written", []),
                                                         bool(result and result["stopped"])))

        def seen(key, written, stopped):
            def call(job):
                for name in [key, *written]:
                    try:
                        self.app.seen.add((str(ws.bib), name, api.entry(ws, name).fingerprint))
                    except CdlbibError:      # the entry is gone (renamed or removed): nothing to remember
                        pass
                if stopped:
                    self.app.seen.add(("stop", str(ws.bib)))
                    return None
                return next(holder["offers"], None)
            self.app.job("look for the next entry to complete", call, offered, unavailable, quiet=True)
        self.app.job("look for entries a source can complete", first, offered, unavailable)

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
                    for key, fields in fmt.corrections.items():
                        for name, value in fields.items():
                            job.progress(f"  {key}: {'key' if name == 'ID' else name}: the formatter writes {value}")
            try:
                return api.send_checked(ws, summary=summary, progress=job.progress, report=report)
            except PublishRefused as exc:
                if not exc.needs_fork:
                    raise
                if deps.ask():
                    if not job.confirm(f"{exc} Create one now?"):
                        raise PublishRefused(f"{exc} Create one with: gh repo fork {exc.upstream} --clone=false") from exc
                else:
                    login = re.match(r"@(\S+) has no fork of ", str(exc))
                    name = exc.upstream.split("/", 1)[1] if exc.upstream and "/" in exc.upstream else "the upstream repository"
                    job.progress(f"creating your fork {login.group(1)}/{name} ..." if login
                                 else f"creating your fork of {exc.upstream} ...")
                return api.send_checked(ws, summary=summary, progress=job.progress, allow_fork_creation=True)

        def done(result):
            self.sending = False

            def draw(out):
                out.line("Sent.", "success", bold=True)
                if result.created_fork:
                    out.line(f"created fork {result.fork}")
                if result.files:
                    out.line("committed: " + ", ".join(result.files))
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
