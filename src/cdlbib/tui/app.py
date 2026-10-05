"""The terminal interface: one window, seven views, one job worker.

Presentation and input only. Every action is a call into cdlbib.api, run as a job on the
one worker (cdlbib.tui.worker); what the core returns is shown as it is.
"""
import threading

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Footer, RichLog, Static, TabbedContent, TabPane

from .. import api, theme
from ..errors import CdlbibError
from . import themes
from .add import AddView
from .check import CheckView
from .edit import EditScreen
from .library import LibraryView
from .review import ReviewView
from .send import SendView
from .setup import SetupView
from .state import StateView
from .widgets import ChoiceScreen, ConfirmScreen, PromptScreen, Shown, TextScreen, Writer
from .worker import Runner

VIEWS = (("library", "Library"), ("review", "Review"), ("add", "Add"), ("check", "Check"), ("send", "Send"),
         ("state", "Library state"), ("setup", "Setup"))

# Every key, by where it works: the help screen is this table.
KEYS = (
    ("Everywhere", (
        ("F1 or ?", "this help (? when the cursor is not in a text box)"),
        ("F2 … F8, or 1 … 7", "Library, Review, Add, Check, Send, Library state, Setup"),
        ("ctrl+t", "switch between the dark and the light theme"),
        ("ctrl+l", "show or hide the log of the running job"),
        ("ctrl+q, or q", "quit (asks first while a job is running)"),
        ("tab / shift+tab", "move between the parts of a view"),
        ("esc", "leave a text box; close a dialog"),
    )),
    ("Library", (
        ("/", "type a search: words, field:word (key author title venue year doi type status), \"a phrase\""),
        ("f", "show one status at a time (press again for the next; then all)"),
        ("up / down / pgup / pgdn", "move in the table; the entry's details follow"),
        ("d", "next detail tab: Entry, Issues, Evidence"),
        ("e", "edit the selected entry"),
        ("n", "type a new entry"),
        ("c", "check the selected entry now (format, then its citation)"),
        ("a", "approve the selected entry under your GitHub login"),
        ("v", "revoke the approval of the selected entry"),
    )),
    ("Edit (an entry's text)", (
        ("ctrl+p", "preview: the diff, the format findings, key change, status that is lost, entries affected"),
        ("ctrl+r", "put the formatter's corrected text into the editor"),
        ("ctrl+s", "save the previewed text"),
        ("esc", "close (asks first when the text was changed)"),
    )),
    ("Review", (
        ("t", "the changed entries waiting for review, or every entry waiting"),
        ("r", "read the queue again"),
        ("d", "next detail tab"),
        ("a", "approve the selected entry (source and note; your GitHub login is shown)"),
        ("v", "revoke the selected entry's approval (reason)"),
        ("e", "edit the selected entry"),
        ("c", "check the selected entry now"),
    )),
    ("Add", (
        ("esc, then left / right", "from a text box to the row of tab names, and between Search, Identifier, PDF, Manual"),
        ("enter or down", "on the row of tab names: into the tab"),
        ("ctrl+f", "Search tab: find records for the title, authors and year typed (also enter in a box)"),
        ("space", "Search tab: mark or unmark the selected record"),
        ("enter", "Search tab: propose the marked records (or the selected one); Identifier tab: look them up"),
        ("ctrl+o", "PDF tab: choose the file from the folder tree"),
        ("enter", "PDF tab, in the path box: read the PDF"),
        ("l", "PDF tab: look up the PDF's source record"),
        ("o", "PDF tab: open the PDF in the system viewer"),
        ("m", "PDF tab: read the PDF with a language model"),
        ("t", "PDF tab: type the entry in, the form filled with what was read"),
        ("ctrl+s", "Manual tab: draft the entry from the form"),
    )),
    ("A proposal", (
        ("a", "accept: write this entry"),
        ("e", "edit the proposed text, then check it again"),
        ("s", "skip this one"),
        ("A", "accept this and all remaining proposals that need no decision"),
        ("r / k", "a typed duplicate: remove it / keep both for the formatter"),
        ("t / c", "a proposal whose model evidence was not stored: try again / go on without it"),
        ("q or esc", "stop here; nothing more is written"),
    )),
    ("Check", (
        ("c", "check the entry selected in the Library view"),
        ("g", "completion offers for the changed entries, then their check"),
        ("G", "check the changed entries without the completion offers"),
        ("m", "run the format check on the whole library"),
    )),
    ("Send", (
        ("s", "send: completion offers first, then the checks, then the pull request from your fork"),
        ("S", "send without the completion offers (the checks still run)"),
        ("r", "read the library's state again (asks the upstream and GitHub)"),
    )),
    ("Library state", (
        ("r", "look for upstream changes now"),
        ("u", "update the library (asks what to do when there are unsent changes)"),
        ("b", "read the list of backups again"),
        ("z", "undo: put the library back as it was at the selected backup"),
        ("p", "store again the model evidence that entries still wait for"),
    )),
    ("Setup", (
        ("c", "check everything: asks gh who is logged in and reads the system keychain"),
        ("l", "link cdl.bib into your TeX tree"),
        ("x", "remove the link cdlbib made"),
        ("b", "write the frozen .bib of the paper named in the form"),
        ("B", "write the paper's compiled .bbl"),
    )),
    ("Dialogs", (
        ("y / n", "answer a yes/no question"),
        ("the letter shown", "choose that answer"),
        ("ctrl+s", "confirm a form"),
        ("enter", "next box of a form; in the last one, confirm"),
    )),
)


class LogLine(Message):
    def __init__(self, line):
        super().__init__()
        self.line = line


class CdlbibApp(App):
    TITLE = "cdlbib"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; color: $foreground; }
    ModalScreen { align: center middle; background: $background 70%; }
    #top { height: 1; background: $primary; color: $cdl-on-primary; padding: 0 1; text-style: bold; }
    #banner { height: auto; background: $panel; color: $warning; padding: 0 1; display: none; }
    #banner.shown { display: block; }
    #views { height: 1fr; }
    #log { height: 7; border-top: solid $cdl-border; background: $surface; color: $foreground; padding: 0 1; }
    #log.hidden { display: none; }
    #jobline { height: 1; background: $surface; color: $cdl-muted; padding: 0 1; }
    #jobline.busy { color: $accent; }
    .dialog { width: 76; max-width: 95%; height: auto; max-height: 90%; border: round $accent; background: $surface;
              padding: 1 2; }
    .dialog.wide { width: 95%; }
    .dialog.tall { height: 90%; }
    .dialog-text { height: auto; max-height: 24; }
    .title { text-style: bold; color: $accent; margin-bottom: 1; }
    .label { color: $cdl-muted; margin-top: 1; }
    .hint { color: $cdl-muted; }
    .buttons { height: auto; margin-top: 1; }
    .buttons Button { margin-right: 2; }
    .choices { height: auto; margin-top: 1; }
    .choice { width: 100%; height: auto; min-height: 3; margin-bottom: 0; text-wrap: wrap; content-align: left middle; }
    .row { height: auto; }
    .row Button { margin-right: 1; }
    .pane { border: round $cdl-border; padding: 0 1; }
    .pane:focus-within { border: round $accent; }
    .message { height: auto; color: $foreground; padding: 0 1; }
    .greyed { color: $cdl-muted; }
    DataTable { height: 1fr; background: $background; }
    DataTable > .datatable--header { background: $panel; color: $accent; text-style: bold; }
    Input { background: $surface; color: $foreground; border: tall $cdl-border; }
    Input:focus { border: tall $accent; }
    Input > .input--placeholder { color: $cdl-muted; }
    TextArea { background: $surface; color: $foreground; border: tall $cdl-border; }
    TextArea:focus { border: tall $accent; }
    Button { background: $panel; color: $foreground; border: tall $cdl-border; height: 3; min-width: 10; }
    Button:focus { border: tall $accent; text-style: bold; }
    Button.-primary { background: $primary; color: $cdl-on-primary; }
    Button:disabled { color: $cdl-muted; text-style: italic; }
    TabbedContent { height: 1fr; }
    ContentSwitcher { height: 1fr; }
    TabPane { height: 1fr; padding: 0; }
    Tabs { background: $surface; }
    Tab { color: $cdl-muted; }
    Tab.-active { color: $accent; text-style: bold; }
    Underline > .underline--bar { color: $accent; background: $panel; }
    Select { background: $surface; }
    DirectoryTree { height: 1fr; background: $surface; }
    """
    BINDINGS = [
        Binding("f1", "help", "Help", priority=True),
        Binding("question_mark", "help", "Help", show=False),
        Binding("f2", "view('library')", "Library", priority=True, show=False),
        Binding("f3", "view('review')", "Review", priority=True, show=False),
        Binding("f4", "view('add')", "Add", priority=True, show=False),
        Binding("f5", "view('check')", "Check", priority=True, show=False),
        Binding("f6", "view('send')", "Send", priority=True, show=False),
        Binding("f7", "view('state')", "State", priority=True, show=False),
        Binding("f8", "view('setup')", "Setup", priority=True, show=False),
        Binding("1", "view('library')", "Library", show=False),
        Binding("2", "view('review')", "Review", show=False),
        Binding("3", "view('add')", "Add", show=False),
        Binding("4", "view('check')", "Check", show=False),
        Binding("5", "view('send')", "Send", show=False),
        Binding("6", "view('state')", "State", show=False),
        Binding("7", "view('setup')", "Setup", show=False),
        Binding("ctrl+t", "switch_theme", "Theme", priority=True),
        Binding("ctrl+l", "toggle_log", "Log", priority=True),
        Binding("ctrl+q", "leave", "Quit", priority=True),
        Binding("q", "leave", "Quit", show=False),
    ]

    def __init__(self, ws):
        super().__init__()
        self.ws = ws
        self.entries = []            # [desk.EntrySummary], as api.entries gave them last
        self.state = None            # desk.LibraryState, as api.library_state gave it last
        self.problem = None          # why the library could not be read
        self.pending = []            # [api.PendingEvidence]: model evidence written entries still wait for
        self.log_lines = []          # every line of the log, for tests and the capture script
        self.seen = set()            # completion offers already decided in this sitting (touched by jobs only)
        self._revision = None        # the revision the entries were read at (touched by jobs only)
        self._leaving = False
        self.jobs = Runner(self.call_from_thread, self.say, self.ask, self._jobs_changed, self._unexpected)
        for mode in ("dark", "light"):
            self.register_theme(themes.build(mode))
        self.theme = themes.NAMES[themes.terminal_mode()]

    def get_theme_variable_defaults(self):
        roles = theme.DARK
        return {"cdl-muted": roles["muted"], "cdl-border": roles["border"], "cdl-on-primary": roles["on_primary"]}

    # --- layout ------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(f"cdlbib · {self.ws.root}", id="top", markup=False)
        yield Shown(id="banner")
        with TabbedContent(id="views", initial="library"):
            with TabPane("F2 Library", id="library"):
                yield LibraryView(id="library-view")
            with TabPane("F3 Review", id="review"):
                yield ReviewView(id="review-view")
            with TabPane("F4 Add", id="add"):
                yield AddView(id="add-view")
            with TabPane("F5 Check", id="check"):
                yield CheckView(id="check-view")
            with TabPane("F6 Send", id="send"):
                yield SendView(id="send-view")
            with TabPane("F7 Library state", id="state"):
                yield StateView(id="state-view")
            with TabPane("F8 Setup", id="setup"):
                yield SetupView(id="setup-view")
        yield RichLog(id="log", max_lines=5000, wrap=True, markup=False, highlight=False)
        yield Static("starting ...", id="jobline", markup=False)
        yield Footer()

    def on_mount(self):
        self.theme_changed_signal.subscribe(self, self._theme_changed)
        self.job("read the library", lambda job: api.prepare(self.ws, job.progress), self._prepared, self._unreadable)
        self.refresh_library(force=True)
        self.job("look for upstream changes",
                 lambda job: api.library_state(self.ws, refresh=True, progress=job.progress), self._state)
        self.view("library").activated()

    # --- colours -----------------------------------------------------------------------------

    def colour(self, role):
        return theme.MODES[themes.mode_of(self.theme)][role]

    def writer(self):
        return Writer(self.colour)

    def _theme_changed(self, _theme):
        self._banner()
        for name, _ in VIEWS:
            self.view(name).recolour()
        recolour = getattr(self.screen, "recolour", None)
        if recolour is not None:
            recolour()

    def action_switch_theme(self):
        self.theme = themes.other(self.theme)

    # --- the log and the job line --------------------------------------------------------------

    def say(self, line):
        """Add a line to the log; safe from any thread."""
        self.post_message(LogLine(str(line)))

    @on(LogLine)
    def _log_line(self, event):
        self.log_lines.append(event.line)
        self.query_one("#log", RichLog).write(Text(event.line))

    def action_toggle_log(self):
        self.query_one("#log").toggle_class("hidden")

    def _jobs_changed(self):
        label, waiting = self.jobs.busy_label, self.jobs.waiting
        line = self.query_one("#jobline", Static)
        line.set_class(label is not None, "busy")
        line.update("idle · F1 lists every key" if label is None else
                    f"working: {label}" + (f" · {waiting} waiting" if waiting else ""))
        if self._leaving and self.jobs.idle:
            self._close()

    def _unexpected(self, label, exc):
        self.notify(f"{label}: {exc}", severity="error", timeout=10)

    # --- jobs --------------------------------------------------------------------------------

    def job(self, label, call, done=None, failed=None, key=None, quiet=False):
        """Queue an api call; its result goes to ``done``, its CdlbibError to ``failed`` (by
        default shown as a notification; the log has it too)."""
        owner = self.screen if len(self.screen_stack) > 1 else None

        def still_there(callback):
            """A job started from a dialog or an editor reports to it only while it is open."""
            if callback is None or owner is None:
                return callback
            return lambda *args: callback(*args) if owner in self._screen_stack else None

        def started(job):
            if owner is not None and owner not in self._screen_stack:
                return None                  # its dialog or editor was closed before its turn came: nothing is done
            return call(job)
        return self.jobs.submit(label, started, still_there(done), still_there(failed), key=key, quiet=quiet)

    def ask(self, question):
        """Called by a job on the worker thread: a yes/no dialog, and the job waits."""
        answered, answer = threading.Event(), []

        def show():
            def chosen(value):
                answer.append(bool(value))
                answered.set()
            self.push_screen(ConfirmScreen(question), chosen)
        try:
            self.call_from_thread(show)
        except Exception:
            return False
        answered.wait()
        return answer[0]

    def confirm(self, question, then, yes="Yes", no="No"):
        """On the interface's thread: ask, and call ``then()`` on yes."""
        self.push_screen(ConfirmScreen(question, yes, no), lambda value: then() if value else None)

    # --- the library -------------------------------------------------------------------------

    def refresh_library(self, force=False):
        """Read what is shown again when the files changed (api.revision), as a job."""
        def call(job):
            revision = api.revision(self.ws)
            found = {"entries": None}
            if force or revision != self._revision:
                if self._revision is not None:
                    api.prepare(self.ws)          # what previews need, for the library as it is now
                found["entries"] = api.entries(self.ws)
                self._revision = revision
            found["state"] = api.library_state(self.ws)
            found["pending"] = api.pending_evidence(self.ws)
            return found
        self.job("read what changed", call, self._refreshed, self._unreadable, key="refresh", quiet=True)

    def _prepared(self, prepared):
        self.problem = None

    def _unreadable(self, exc):
        self.problem = str(exc)
        self._banner()
        self.notify(str(exc), severity="error", timeout=15)

    def _refreshed(self, found):
        if found["entries"] is not None:
            self.problem = None
            self.entries = found["entries"]
            self.query_one("#top", Static).update(f"cdlbib · {self.ws.root} · {len(self.entries)} entries")
            self.view("library").library_changed()
            self.view("review").library_changed()
        self.pending = found["pending"]
        self._state(found["state"], keep_fetched=True)

    def _state(self, state, keep_fetched=False):
        if keep_fetched and self.state is not None and state.new_commits is None:
            state.new_commits, state.new_entries = self.state.new_commits, self.state.new_entries
        if keep_fetched and self.state is not None and state.pull_request is None:
            state.pull_request = self.state.pull_request
        self.state = state
        self._banner()
        for name in ("send", "state", "check"):
            self.view(name).state_changed()

    def _banner(self):
        out, state = self.writer(), self.state
        if self.problem:
            out.line(self.problem, "error")
        if state is not None and state.new_commits:
            count, entries = state.new_commits, state.new_entries
            out.line(f"{count} new upstream commit{'' if count == 1 else 's'}"
                     + (f" ({entries} new entr{'y' if entries == 1 else 'ies'})" if entries else "")
                     + " · F7 Library state, then u updates", "warning")
        if state is not None and state.interrupted:
            out.line(f"An earlier write or update did not finish; the state before it is kept at {state.interrupted}"
                     " · F7 Library state", "error")
        text = out.text
        text.rstrip()
        banner = self.query_one("#banner", Shown)
        banner.show(text)
        banner.set_class(bool(text.plain), "shown")

    def on_app_focus(self):
        if self.jobs.idle and self.is_mounted:
            self.refresh_library()

    # --- views -------------------------------------------------------------------------------

    def view(self, name):
        return self.query_one(f"#{name}-view")

    @property
    def active_view(self):
        return self.query_one("#views", TabbedContent).active

    def action_view(self, name):
        if len(self.screen_stack) > 1:       # an editor or a dialog is open: it is closed first, by its own keys
            self.notify("Close this first (esc); the views are behind it.")
            return
        self.query_one("#views", TabbedContent).active = name
        self.view(name).activated()

    @on(TabbedContent.TabActivated, "#views")
    def _view_shown(self, event):
        if event.tabbed_content.id == "views" and event.pane is not None and event.pane.id in dict(VIEWS):
            self.view(event.pane.id).activated()

    def action_help(self):
        if isinstance(self.screen, TextScreen):
            return
        out = self.writer()
        for section, keys in KEYS:
            out.head(section)
            for key, what in keys:
                out.part(f"  {key:<22}", "accent").line(f" {what}")
        self.push_screen(TextScreen("Keys", out.text))

    # --- quitting ----------------------------------------------------------------------------

    def unsaved(self):
        """What is typed and not saved anywhere, in words: the open editors and dialogs, and the
        manual form. One rule for every way out."""
        places = [*self.screen_stack, *(self.view(name) for name, _ in VIEWS)]
        return [found for found in (getattr(place, "unsaved", lambda: None)() for place in places) if found]

    def action_leave(self):
        if isinstance(self.screen, ConfirmScreen) and getattr(self.screen, "about_quitting", False):
            return
        dirty = self.unsaved()
        if dirty:
            screen = ConfirmScreen("Quit? This was typed and is not saved; quitting does not keep it:\n\n"
                                   + "\n".join(f"  {line}" for line in dirty), "Quit and discard it", "Keep editing")
            screen.about_quitting = True
            self.push_screen(screen, lambda value: self._leave() if value else None)
            return
        self._leave()

    def _leave(self):
        closing = getattr(self.screen, "before_quit", None)
        if closing is not None and self.jobs.idle:
            closing()                    # the screen puts away what it holds open (a job of its own), then the app goes
            self._leaving = True
            if self.jobs.idle:
                self._close()
            return
        if self.jobs.idle:
            self._close()
            return
        label, waiting = self.jobs.busy_label, self.jobs.waiting

        def chosen(value):
            if value == "wait":
                if closing is not None:
                    closing()
                self._leaving = True
                self.query_one("#jobline", Static).update(f"quitting when the job is done: {self.jobs.busy_label}")
                if self.jobs.idle:
                    self._close()
            elif value == "now":
                self._close()
        self.push_screen(ChoiceScreen(
            f"A job is running: {label}" + (f" ({waiting} more waiting)" if waiting else "") + ".",
            [("w", "wait", "Wait for it to finish, then quit"),
             ("x", "now", "Quit now; the running job is stopped where it is"),
             ("s", "stay", "Stay")]), chosen)

    def _close(self):
        self.jobs.stop()
        self.exit()

    # --- actions several views share ------------------------------------------------------------

    def edit(self, detail=None):
        """Open the editor on an entry (``detail``: desk.EntryDetail), or on a new one."""
        def closed(lines):
            if lines:
                for line in lines:
                    self.say(line)
                self.notify(lines[0])
                self.refresh_library()
        self.push_screen(EditScreen(detail), closed)

    def check_keys(self, keys, label):
        def call(job):
            return api.check_keys(self.ws, keys, progress=job.progress)

        def done(check):
            self.view("check").show_check(keys, check)
            self.refresh_library()
            self.notify(f"{label}: passed" if check.ok else f"{label}: not passed; see the Check view (F5)",
                        severity="information" if check.ok else "warning")
        self.job(label, call, done, lambda exc: self.view("check").show_failure(label, exc))

    def offer_completion(self, then):
        """The step that comes before the checks of changed entries, here as in the command
        line's verify and send: each new or edited entry that is not yet accepted is looked up,
        one at a time, and what a source would complete is shown as a proposal to accept, edit
        or skip. ``then()`` is called when there is nothing more to offer, when the person
        stopped, or when the offers cannot be made (said in the log)."""
        from .proposal import ProposalScreen
        ws, holder = self.ws, {}

        def first(job):
            if ("stop", str(ws.bib)) in self.seen:
                return None
            due = api.completion_due(ws)             # which entries the offers would look at; no source is asked
            if not due.reachable:
                job.progress(f"Completion unavailable: {due.problem}")
                return None
            if not due:
                job.progress("completion offers: no new or edited entry is waiting for one")
                return None
            count = len(due.keys)
            job.progress(f"completion offers: {count} new or edited entr{'y' if count == 1 else 'ies'} to look at")
            holder["offers"] = api.completion_offers(ws, seen=self.seen)
            return next(holder["offers"], None)

        def unavailable(exc):
            self.say(f"Completion unavailable: {exc}")
            then()

        def offered(offer):
            if offer is None:
                then()
            elif offer.error is not None:
                self.say(f"{offer.key}: completion unavailable: {offer.error}")
                seen(offer.key, [], False)
            elif not offer.proposals:
                seen(offer.key, [], False)
            else:
                self.push_screen(ProposalScreen(offer.proposals, in_library=True, origin=f"completion of {offer.key}"),
                                 lambda result: seen(offer.key, (result or {}).get("written", []),
                                                     bool(result and result["stopped"])))

        def seen(key, written, stopped):
            def call(job):
                for name in [key, *written]:
                    try:
                        self.seen.add((str(ws.bib), name, api.entry(ws, name).fingerprint))
                    except CdlbibError:      # the entry is gone (renamed or removed): nothing to remember
                        pass
                if stopped:
                    self.seen.add(("stop", str(ws.bib)))
                    return None
                return next(holder["offers"], None)
            self.job("look for the next entry to complete", call, offered, unavailable, quiet=True)
        self.job("look for entries a source can complete", first, offered, unavailable)

    def _with_login(self, what, then):
        """Ask gh who is logged in (a job), and go on with the handle; without a login, say
        what the core says about it."""
        def done(features):
            login = next(feature for feature in features if feature.name == "gh login")
            if login.available:
                then(login.detail)
            else:
                out = self.writer()
                out.line(f"{what} is recorded under your GitHub login, and none was found.", "warning")
                out.line(login.detail).line(login.how)
                self.push_screen(TextScreen(f"{what}: no GitHub login", out.text))
        self.job("ask gh who is logged in", lambda job: api.features(probe=("github",), progress=job.progress), done)

    def approve(self, detail):
        def with_handle(handle):
            out = self.writer()
            out.line(f"Approving as {handle} (the GitHub login of gh; a reviewer's name cannot be typed).", "accent")
            out.line(f"Status now: {detail.status}").line().line(detail.raw.expandtabs(4))

            def filled(values):
                if values is None:
                    return
                question = (f"Record your approval of {detail.key} as {handle}?\n\nsource: {values['source']}\n"
                            f"note: {values['note']}")
                self.confirm(question, lambda: self.job(
                    f"approve {detail.key}",
                    lambda job: api.approve(self.ws, detail.key, detail.fingerprint, values["source"], values["note"]),
                    approved), yes="Approve")
            self.push_screen(PromptScreen(f"Approve {detail.key}", [
                ("source", "Source you checked the entry against (the article's page, the PDF, the book)", ""),
                ("note", "Note: what you checked", "")], ok="Approve", text=out.text), filled)

        def approved(stored):
            review = stored.get("human_review") or {}
            line = f"approved {detail.key} as {review.get('reviewer', '')}; status: {stored['status']}"
            self.say(line)
            self.notify(line)
            self.refresh_library(force=True)
        self._with_login("An approval", with_handle)

    def revoke(self, detail):
        def with_handle(handle):
            out = self.writer()
            out.line(f"Revoking as {handle} (the GitHub login of gh).", "accent")
            out.line(f"Status now: {detail.status}")
            for name, value in (detail.human_review or {}).items():
                out.line(f"  {name}: {value}")

            def filled(values):
                if values is None:
                    return
                self.confirm(f"Revoke the approval of {detail.key} as {handle}?\n\nreason: {values['reason']}",
                             lambda: self.job(
                                 f"revoke the approval of {detail.key}",
                                 lambda job: api.revoke(self.ws, detail.key, values["reason"],
                                                        expected_fingerprint=detail.fingerprint), revoked),
                             yes="Revoke")
            self.push_screen(PromptScreen(f"Revoke the approval of {detail.key}", [
                ("reason", "Reason for revoking", "")], ok="Revoke", text=out.text), filled)

        def revoked(result):
            count = len(result.records)
            line = (f"revoked {count} approval record{'' if count == 1 else 's'} of {detail.key}; "
                    f"status: {result.status}")
            self.say(line)
            self.notify(line)
            self.refresh_library(force=True)
        self._with_login("A revocation", with_handle)

    def notify(self, message, *, title="", severity="information", timeout=None, markup=False):
        """A notification; its text is shown as it is (a path or a message may hold brackets)."""
        super().notify(str(message), title=title, severity=severity, timeout=timeout, markup=markup)


def run(ws):
    """Open the interface on the library ``ws`` and return when the person quits."""
    CdlbibApp(ws).run()

