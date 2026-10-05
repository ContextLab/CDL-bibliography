"""The proposal view every way of adding ends in: what was typed beside what is proposed,
each change with its source, and accept / edit / skip / accept all remaining.

A proposal built from a source record is written by api.apply_proposals; a hand-typed or
model-read draft by api.accept_draft. Whether one may be written is api.acceptable. Nothing
shown here is an approval.
"""
from dataclasses import replace

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from .. import api
from ..errors import EditedEntryParseError
from . import render
from .widgets import ChoiceScreen, Shown

CANNOT = "Cannot accept: complete required fields and resolve duplicate or unsupported entries first."


class PickScreen(ModalScreen):
    """Choose one row of a list. Dismisses with its index, or None for "none of these"."""

    BINDINGS = [Binding("escape", "none", "None of these")]

    def __init__(self, title, rows, none="none of these"):
        super().__init__()
        self.heading, self.rows, self.none = title, list(rows), none

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Static(self.heading, classes="title")
            yield OptionList(*[Option(f"[{number}] {row}", id=f"row-{number - 1}")
                               for number, row in enumerate(self.rows, 1)],
                             Option(f"[0] {self.none}", id="row-none"), id="rows")
            yield Static("enter chooses; esc: none of these", classes="hint")

    def on_mount(self):
        self.query_one(OptionList).focus()

    @on(OptionList.OptionSelected)
    def chosen(self, event):
        name = event.option.id[len("row-"):]
        self.dismiss(None if name == "none" else int(name))

    def action_none(self):
        self.dismiss(None)


class TextEditScreen(ModalScreen):
    """Edit a proposed entry's text. Dismisses with the text, or None."""

    BINDINGS = [Binding("ctrl+s", "accept", "Check this text", priority=True),
                Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, raw, message=""):
        super().__init__()
        self.raw, self.message = raw, message

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide tall"):
            yield Static("Edit the proposed entry", classes="title")
            yield TextArea(self.raw, id="proposal-editor", tab_behavior="indent", soft_wrap=True)
            yield Static(self.message or "ctrl+s checks the edited text again; esc leaves the proposal as it was",
                         classes="hint", id="proposal-editor-hint")

    def on_mount(self):
        self.query_one(TextArea).focus()

    def action_accept(self):
        self.dismiss(self.query_one(TextArea).text)

    def action_cancel(self):
        self.dismiss(None)


class ProposalScreen(Screen):
    """Walks through ``items`` (complete.Proposal). Dismisses with {"lines": what was done,
    "written": the keys written, "stopped": whether the person stopped}."""

    BINDINGS = [
        Binding("a", "accept", "Accept"),
        Binding("e", "edit", "Edit"),
        Binding("s", "skip", "Skip"),
        Binding("A", "accept_all", "Accept all remaining"),
        Binding("r", "remove", "Remove the typed duplicate", show=False),
        Binding("k", "keep", "Keep both", show=False),
        Binding("q", "stop", "Stop"),
        Binding("escape", "stop", "Stop", show=False),
    ]
    DEFAULT_CSS = """
    ProposalScreen #proposal-head { height: 1; background: $primary; color: $cdl-on-primary; padding: 0 1;
                                    text-style: bold; }
    ProposalScreen #sides { height: 2fr; }
    ProposalScreen #findings-pane { height: 3fr; }
    ProposalScreen .side { width: 1fr; }
    ProposalScreen .side-title { color: $accent; text-style: bold; }
    ProposalScreen #proposal-actions { height: auto; padding: 0 1; }
    """

    def __init__(self, items, pdf=None, in_library=False, origin=""):
        super().__init__()
        self.items = list(items)
        self.pdf = pdf                   # the read PDF a model-read draft came from
        self.in_library = in_library     # the proposals complete entries of the library (completion offers)
        self.origin = origin
        self.index = -1
        self.all_remaining = False
        self.lines, self.written = [], []
        self.stopped = False
        self.busy = True                 # True while a job decides what to show next
        self._batch = None               # (the context manager, the batch); touched by jobs only
        self._backup_said = False
        self._closing = False

    @property
    def item(self):
        return self.items[self.index] if 0 <= self.index < len(self.items) else None

    def compose(self) -> ComposeResult:
        yield Static("Proposal", id="proposal-head")
        with Horizontal(id="sides"):
            with VerticalScroll(classes="side pane"):
                yield Static("Typed", classes="side-title")
                yield Shown(id="typed")
            with VerticalScroll(classes="side pane"):
                yield Static("Proposed", classes="side-title")
                yield Shown(id="proposed")
        with VerticalScroll(id="findings-pane", classes="pane"):
            yield Shown(id="findings")
        yield Shown(id="proposal-actions")
        yield Footer()

    def on_mount(self):
        def call(job):
            manager = api.completion_batch(self.app.ws)
            self._batch = (manager, manager.__enter__())
        self.app.job("open the batch", call, lambda _: self._next(), self._failed, quiet=True)

    def recolour(self):
        if self.item is not None and not self.busy:
            self._show()

    # --- moving on ---------------------------------------------------------------------------

    def _failed(self, exc):
        self.busy = False
        self.app.notify(str(exc), severity="error", timeout=12)

    def _say(self, line):
        self.lines.append(line)
        self.app.say(line)

    def _next(self):
        self.index += 1
        if self.item is None:
            self._finish()
            return
        self.busy = True
        self._arrive(first=True)

    def _arrive(self, first=False):
        """Bring the current proposal to the person: candidates to choose from first, then
        names to settle, then (with "accept all remaining") acceptance without a question
        when the core allows it, else the proposal itself."""
        item = self.item
        if first and item.candidates:
            rows = [render.lead(candidate) for candidate in item.candidates]

            def picked(choice):
                if choice is None:
                    self._say(f"{item.key_typed or '(new)'}: none of the candidates was chosen")
                    self._next()
                    return
                self.app.job("look up the chosen record",
                             lambda job: api.choose_candidate(self.app.ws, item, item.candidates[choice],
                                                              in_library=self.in_library),
                             self._replace_and_settle, self._lookup_failed)
            self.app.push_screen(PickScreen("Which record is this entry?", rows), picked)
            return
        self._settle_names()

    def _lookup_failed(self, exc):
        self._say(f"{self.item.key_typed or '(new)'}: {exc}")
        self._next()

    def _replace_and_settle(self, item):
        self.items[self.index] = item
        self._settle_names()

    def _settle_names(self):
        item = self.item
        if not item.proposed_raw:
            self._decide()
            return
        self.app.job("read the name questions", lambda job: api.name_choices(item), self._names, self._failed,
                     quiet=True)

    def _names(self, found, done=()):
        """Ask name by name for the first list not yet settled; ``done``: fields already asked."""
        pending = [(field, typed, source) for field, typed, source in found if field not in done]
        if not pending:
            self._decide()
            return
        field, typed, source = pending[0]
        names, pairs = list(typed), [i for i in range(len(typed)) if typed[i] != source[i]]

        def ask(position):
            if position == len(pairs):
                item = self.item
                self.app.job(f"check the chosen {field} names",
                             lambda job: api.resolve_names(self.app.ws, item, field, names),
                             lambda result: self._named(result, tuple(done) + (field,), found), self._failed)
                return
            at = pairs[position]

            def answered(value):
                if value == "use":
                    names[at] = source[at]
                ask(position + 1)
            self.app.push_screen(ChoiceScreen(
                f"The {field} list: the name typed and the name the source gives differ.",
                [("k", "keep", f"keep typed {typed[at]}"), ("u", "use", f"use source {source[at]}")], escape=False),
                answered)
        ask(0)

    def _named(self, result, done, found):
        self.items[self.index] = result
        self._names(found, done)

    def _decide(self):
        item = self.item
        if not self.all_remaining:
            self.busy = False
            self._show()
            return
        self.app.job("accept the remaining proposals", lambda job: self._write(item, automatic=True),
                     self._wrote, self._failed, quiet=True)

    # --- showing -----------------------------------------------------------------------------

    def _show(self):
        item, colour = self.item, self.app.colour
        kind = ("read from the PDF by a model" if getattr(item, "evidence", None) else
                "typed by hand" if item.manual else "built from a source record")
        self.query_one("#proposal-head", Static).update(
            f"Proposal {self.index + 1} of {len(self.items)} · {kind}" + (f" · {self.origin}" if self.origin else ""))
        self.query_one("#typed", Shown).show(Text((item.typed_raw or "(no typed entry)").expandtabs(4)))
        self.query_one("#proposed", Shown).show(Text((item.proposed_raw or "(no proposed entry)").expandtabs(4)))
        self.query_one("#findings", Shown).show(render.proposal(item, colour))
        actions = Text()
        if item.duplicate_of and item.duplicate_in_library:
            actions.append("[r] remove this typed duplicate   [k] keep both for the formatter   [q] stop",
                           colour("accent"))
        else:
            actions.append("[a] accept   [e] edit   [s] skip   [A] accept all remaining   [q] stop", colour("accent"))
        actions.append("\nAccepting writes the entry; it does not verify or approve it.", colour("muted"))
        self.query_one("#proposal-actions", Shown).show(actions)

    # --- writing (runs in a job) -----------------------------------------------------------------

    def _write(self, item, automatic=False, remove=False):
        """In a job: write ``item`` when the core allows it. Returns (what happened, result)."""
        ws = self.app.ws
        if remove:
            return "applied", api.apply_proposals(ws, [replace(item, remove_duplicate=True)], batch=self._batch[1])
        if not api.acceptable(item) or (automatic and item.needs_decision):
            return ("ask" if automatic else "cannot"), None
        if item.manual:
            return "accepted", api.accept_draft(ws, item, pdf=self.pdf if getattr(item, "evidence", None) else None)
        return "applied", api.apply_proposals(ws, [item], batch=self._batch[1])

    def _wrote(self, outcome):
        what, result = outcome
        if what == "ask":            # "accept all remaining" stops at one that needs the person
            self.busy = False
            self._show()
            return
        if what == "cannot":
            self.busy = False
            self.app.notify(CANNOT, severity="warning", timeout=8)
            return
        applied = result.applied if what == "accepted" else result
        for key in applied.removed:
            self._say(f"Removed duplicate: {key}")
        for key in applied.written:
            self._say(f"Completed: {key}" if self.in_library else f"Added: {key}")
            self.written.append(key)
        for key, reason in applied.refused:
            self._say(f"Not written {key}: {reason}")
        for line in applied.notes:
            self._say(line)
        if applied.backup is not None and not self._backup_said:
            self._backup_said = True
            self._say(f"Batch backup: {applied.backup.stamp}; cdlbib update --undo restores the state before this "
                      "command’s accepted changes.")
        if applied.saved_copy is not None and not self._backup_said:
            self._backup_said = True
            self._say(f"cdl.bib as it was before the first accepted change is kept at {applied.saved_copy}")
        if what == "accepted":
            if result.evidence_stored:
                self._say(f"The model reading's evidence is stored with {result.key}; it is not an approval.")
            elif result.evidence_stored is False:
                self._say(f"The entry was written, but the model evidence was not stored: {result.evidence_error}")
        self._next()

    # --- actions -----------------------------------------------------------------------------

    def _ready(self):
        return self.item is not None and not self.busy and not self._closing

    def _duplicate(self):
        return bool(self.item.duplicate_of and self.item.duplicate_in_library)

    def action_accept(self):
        if not self._ready() or self._duplicate():
            return
        item = self.item
        self.busy = True
        self.app.job(f"write {item.key_proposed or item.key_typed or 'the entry'}", lambda job: self._write(item),
                     self._wrote, self._failed)

    def action_accept_all(self):
        if not self._ready() or self._duplicate():
            return
        self.all_remaining = True
        item = self.item
        self.busy = True
        self.app.job("accept the remaining proposals", lambda job: self._write(item, automatic=True),
                     self._wrote_all, self._failed)

    def _wrote_all(self, outcome):
        if outcome[0] == "ask":
            self.busy = False
            self.app.notify("This one needs your decision: accept (a), edit (e) or skip (s). The remaining ones "
                            "that need none are then accepted.", timeout=8)
            return
        self._wrote(outcome)

    def action_skip(self):
        if not self._ready():
            return
        self._say(f"Skipped: {self.item.key_proposed or self.item.key_typed or '(new)'}")
        self._next()

    def action_remove(self):
        if not self._ready() or not self._duplicate():
            return
        item = self.item
        self.busy = True
        self.app.job(f"remove the typed duplicate {item.key_typed}", lambda job: self._write(item, remove=True),
                     self._wrote, self._failed)

    def action_keep(self):
        if self._ready() and self._duplicate():
            self._say(f"Kept both: {self.item.key_typed} and {self.item.duplicate_of}")
            self._next()

    def action_edit(self, raw=None, message=""):
        if not self._ready():
            return
        item = self.item
        original = item.proposed_raw or item.typed_raw or ""

        def edited(text):
            if text is None:
                return
            if text == original:
                self.app.notify("The editor left the entry unchanged.")
                return
            self.busy = True

            def failed(exc):
                self.busy = False
                if isinstance(exc, EditedEntryParseError):
                    self.action_edit(text, f"Edited entry could not be read: {exc}. ctrl+s checks again; esc gives up.")
                else:
                    self.app.notify(f"Edited entry could not be checked: {exc}. Returning to choices.",
                                    severity="error", timeout=12)

            def checked(new):
                self.items[self.index] = new
                self.busy = False
                self._show()
            self.app.job("check the edited entry", lambda job: api.recheck_proposal(self.app.ws, item, text),
                         checked, failed)
        self.app.push_screen(TextEditScreen(original if raw is None else raw, message), edited)

    def action_stop(self):
        if self._closing:
            return
        if self.item is not None:
            self.stopped = True
        self._finish()

    # --- closing -----------------------------------------------------------------------------

    def before_quit(self):
        self._finish(dismiss=False)

    def _finish(self, dismiss=True):
        if self._closing:
            return
        self._closing = True

        def call(job):
            if self._batch is not None:
                manager, self._batch = self._batch[0], None
                manager.__exit__(None, None, None)

        def closed(_):
            if dismiss:
                self.dismiss({"lines": self.lines, "written": self.written, "stopped": self.stopped})
        self.app.job("close the batch", call, closed, lambda exc: closed(None), quiet=True)
