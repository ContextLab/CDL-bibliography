"""The Library state view: which library is in use, upstream changes, update, backups, undo."""
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, DataTable

from .. import api, prompts
from ..errors import UpdateConflict, UpdateNeedsDecision
from .widgets import ChoiceScreen, Shown, View


def backup_line(backup, only_copy):
    changed = len(backup.changed)
    return ((f"branch {backup.branch}" if backup.branch else "no branch")
            + f" at {backup.commit[:8]}, {changed} changed file{'' if changed == 1 else 's'}"
            + (", local commits saved" if backup.has_bundle else "")
            + (", holds commits kept nowhere else" if only_copy else ""))


class StateView(View):
    BINDINGS = [
        Binding("r", "refresh", "Look for upstream changes"),
        Binding("u", "update", "Update"),
        Binding("b", "backups", "Backups"),
        Binding("z", "undo", "Undo to the selected backup"),
    ]
    DEFAULT_CSS = """
    StateView #state-pane { height: auto; max-height: 14; }
    StateView #state-result-pane { height: auto; max-height: 10; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.saved = None        # what api.backups gave, with the rest of the list
        self.result = None
        self.loaded = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="pane", id="state-pane"):
            yield Shown(id="state-now")
        with Horizontal(classes="row"):
            yield Button("Look for upstream changes (r)", id="state-refresh")
            yield Button("Update (u)", id="state-update", variant="primary")
            yield Button("Undo to the selected backup (z)", id="state-undo")
        with VerticalScroll(classes="pane", id="state-result-pane"):
            yield Shown(id="state-result")
        yield Shown(id="backups-head", classes="message")
        yield DataTable(id="backups", cursor_type="row")

    def on_mount(self):
        self.query_one("#backups", DataTable).add_columns("Backup", "Taken", "What it holds")

    def activated(self):
        self.state_changed()
        self.query_one("#state-refresh", Button).focus()
        if not self.loaded:
            self.action_backups()

    def recolour(self):
        self.state_changed()
        self._backups_shown()
        if self.result is not None:
            self.result()

    @on(Button.Pressed)
    def _pressed(self, event):
        {"state-refresh": self.action_refresh, "state-update": self.action_update,
         "state-undo": self.action_undo}[event.button.id]()

    # --- the state ---------------------------------------------------------------------------

    @property
    def managed(self):
        return bool(self.app.state is not None and self.app.state.managed)

    def state_changed(self):
        state, out = self.app.state, self.app.writer()
        if state is None:
            out.line("reading the library's state ...", "muted")
            self.query_one("#state-now", Shown).show(out.text)
            return
        out.line(f"Library: {state.root}", bold=True)
        out.line(f"chosen by: {prompts.CHOSEN_BY[state.origin]}")
        if state.managed:
            out.line("last update check: " + (state.last_check.strftime("%Y-%m-%d %H:%M UTC") if state.last_check
                                              else "never"))
            if state.new_commits is None:
                out.line("upstream: not compared yet (r looks now)", "muted")
            elif state.new_commits:
                count, entries = state.new_commits, state.new_entries
                out.line(f"upstream: {count} new commit{'' if count == 1 else 's'}"
                         + (f", {entries} new entr{'y' if entries == 1 else 'ies'}" if entries else "")
                         + " (u updates)", "warning")
            else:
                out.line("upstream: nothing new" + (" (asked just now)" if state.refreshed else " (as last fetched)"),
                         "success")
            if state.local_commits:
                out.line(f"commits here that the upstream does not have: {state.local_commits}")
        else:
            out.line("This library is not the copy cdlbib downloads and manages: updating it, its backups and undo "
                     "are not offered here (u, b and z are for the managed copy).", "muted")
        out.line(f"branch: {state.branch or '(none)'}")
        if state.pull_request is not None:
            out.line(f"pull request: {state.pull_request.url} ({state.pull_request.state})")
        if state.pending:
            out.line("unsent changes: " + ", ".join(state.pending), "accent")
        elif state.pending is not None:
            out.line("unsent changes: none")
        if state.unrelated:
            out.line("other changed files (a send leaves them): " + ", ".join(state.unrelated), "muted")
        if state.interrupted:
            out.line(f"An earlier write or update did not finish; the state before it is kept at {state.interrupted}",
                     "error")
        for note in state.notes:
            out.line(note, "warning")
        self.query_one("#state-now", Shown).show(out.text)
        for name in ("#state-update", "#state-undo"):
            self.query_one(name, Button).disabled = not state.managed

    def action_refresh(self):
        self.app.job("look for upstream changes",
                     lambda job: api.library_state(self.app.ws, refresh=True, progress=job.progress), self.app._state)

    def _result(self, draw):
        def again():
            out = self.app.writer()
            draw(out)
            self.query_one("#state-result", Shown).show(out.text)
        self.result = again
        again()

    def _not_managed(self):
        if self.managed:
            return False
        self.app.notify("This library is not the copy cdlbib manages; its update, backups and undo are not offered here.")
        return True

    # --- update ------------------------------------------------------------------------------

    def action_update(self, decision=None, seen=None):
        if self._not_managed():
            return
        ws = self.app.ws

        def done(result):
            failed_to = result.action in ("skipped_offline", "interrupted")

            def draw(out):
                for note in result.notes:
                    out.line(note, "warning")
                out.line(result.message or result.action, "error" if failed_to else "success")
                if result.backup is not None:
                    out.line(f"backup taken before the change: {result.backup.stamp} (z restores it)")
            self._result(draw)
            self.app.say(result.message or result.action)
            self.action_backups()
            self.app.refresh_library(force=True)
            self.action_refresh()
            if decision == "send":
                self.app.action_view("send")
                self.app.view("send").start()

        def failed(exc):
            if isinstance(exc, UpdateNeedsDecision):
                self._ask(exc)
                return

            def draw(out):
                out.line(str(exc), "error")
                if isinstance(exc, UpdateConflict):
                    for key in exc.entries:
                        out.line(f"  entry changed here and upstream: {key}", "warning")
                    for path in exc.files:
                        out.line(f"  file: {path}", "warning")
                    out.line("Nothing was changed.")
            self._result(draw)
        self.app.job("update the library" if decision is None else f"update the library ({decision})",
                     lambda job: api.update(ws, decision=decision, force=True, progress=job.progress, seen=seen),
                     done, failed)

    def _ask(self, exc):
        """The question about unsent changes, in the core's words, with its answers."""
        answers = prompts.answers(exc)
        choices = [(answers[choice][0], choice, answers[choice][1]) for choice in exc.choices]

        def chosen(decision):
            if decision is None:
                self._result(lambda out: out.line("Nothing was changed: no answer was given.", "muted"))
                return
            self.action_update(decision=decision, seen=exc.seen)
        # The question in the core's words; its lettered answers are the buttons, word for word.
        listed = {f"  [{letter}] {text}" for letter, _, text in choices}
        question = "\n".join(line for line in prompts.unsent_question(exc).splitlines() if line not in listed)
        self.app.push_screen(ChoiceScreen(question, choices, wide=True), chosen)

    # --- backups and undo --------------------------------------------------------------------

    def action_backups(self):
        if not self.managed:
            self.loaded = self.app.state is not None
            self._backups_shown()
            return

        def call(job):
            saved = api.backups()
            return dict(saved=saved, only={backup.stamp: api.holds_only_copy(backup) for backup in saved},
                        unreadable=api.unreadable_backups(), checkpoint=api.completion_undo_checkpoint(),
                        folder=api.backups_folder(), root=api.managed_root())

        def done(found):
            self.saved, self.loaded = found, True
            self._backups_shown()
        self.app.job("read the backups", call, done, quiet=True)

    def _backups_shown(self):
        table, out = self.query_one("#backups", DataTable), self.app.writer()
        table.clear()
        if not self.managed:
            out.line("Backups", bold=True)
            out.line("(kept for the library cdlbib manages; this is another library)", "muted")
        elif self.saved is None:
            out.line("Backups: reading ...", "muted")
        else:
            found = self.saved
            saved, unreadable = found["saved"], found["unreadable"]
            if not saved and not unreadable:
                out.line(f"no backups of {found['root']} yet", "muted")
            else:
                out.line(f"{len(saved)} {'readable ' if unreadable else ''}backup{'' if len(saved) == 1 else 's'} of "
                         f"{found['root']}" + (f" and {len(unreadable)} unreadable" if unreadable else "")
                         + f", newest first (kept in {found['folder']})", bold=True)
            if found["checkpoint"]:
                out.line(f"z without a selection restores the checkpoint {found['checkpoint']}", "muted")
            rows = {backup.stamp: (backup.stamp, backup.when, backup_line(backup, found["only"][backup.stamp]))
                    for backup in saved}
            rows.update({stamp: (stamp, "", f"unreadable ({reason})") for stamp, reason in unreadable})
            for stamp in sorted(rows, reverse=True):
                table.add_row(*rows[stamp], key=stamp)
        self.query_one("#backups-head", Shown).show(out.text)

    def action_undo(self):
        if self._not_managed():
            return
        table = self.query_one("#backups", DataTable)
        if not table.row_count:
            self.app.notify("There is no backup to go back to.")
            return
        stamp = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value

        def done(undone):
            restored = undone.restored

            def draw(out):
                out.line(f"restored backup {restored.stamp} ({restored.when}): "
                         f"{backup_line(restored, False)}", "success")
                out.line(f"the library as it was just before is backup {undone.before.stamp}; z on it returns to it")
                for branch, commit in undone.taken_off:
                    out.line(f"branch {branch} was on commit {commit[:8]}, which is on no other branch and not in the "
                             f"upstream; backup {undone.before.stamp} keeps it, and undoing to that backup puts the "
                             "branch back on it", "warning")
                for note in undone.notes:
                    out.line(note, "warning")
            self._result(draw)
            self.app.say(f"restored backup {restored.stamp}")
            self.action_backups()
            self.app.refresh_library(force=True)

        def failed(exc):
            self._result(lambda out: out.line(str(exc), "error"))
        self.app.confirm(f"Put the library back as it was at backup {stamp}?\n\nThe library as it is now is backed up "
                         "first, so this can be undone the same way.",
                         lambda: self.app.job(f"undo to backup {stamp}", lambda job: api.undo(stamp), done, failed),
                         yes="Undo to it")

