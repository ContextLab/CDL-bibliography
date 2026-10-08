"""The editor of one entry's text: type, preview, save. Also the place a new entry is typed."""
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static, TextArea

from .. import api
from ..errors import EditRefused
from . import render
from .widgets import Shown

EXAMPLE = "@article{Key20,\n    Author = {A Author and B Author},\n    Journal = {Journal},\n    Title = {Title},\n    Year = {2020}}"


class EditScreen(Screen):
    """Dismisses with the lines that say what was saved, or None.

    Opened with an entry's detail, with nothing (a new entry), or with only the ``key`` of an
    entry whose detail has not been read yet: the editor then opens at once, reads the entry
    itself (a job, in its turn on the one worker) and says so; until the text is here nothing
    can be typed into it, and a preview, a save or the formatter's text asked for meanwhile is
    remembered and done, in the order asked, when it is here: never on the empty text."""

    BINDINGS = [
        Binding("ctrl+p", "preview", "Preview", priority=True),
        Binding("ctrl+r", "formatter", "Formatter's text", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+o", "reload", "Reload", priority=True),
        Binding("escape", "close", "Close", priority=True),
    ]
    DEFAULT_CSS = """
    EditScreen #edit-head { height: 1; background: $primary; color: $cdl-on-primary; padding: 0 1; text-style: bold; }
    EditScreen #editor { width: 1fr; height: 1fr; }
    EditScreen #edit-right { width: 1fr; }
    EditScreen #edit-message { height: auto; padding: 0 1; }
    """

    def __init__(self, detail=None, key=None):
        super().__init__()
        self.detail = detail                 # desk.EntryDetail of the entry; None for a new one
        self.key = detail.key if detail is not None else key
        self.unread = detail is None and key is not None     # the entry's text is not in the editor yet
        self.reading = False                 # the job that reads it is queued or running
        self.asked = []                      # the actions asked for before the text was here, in order
        self.original = detail.raw if detail is not None else ""
        self.previewed = None                # (the text previewed, desk.EditPreview)
        # The fingerprint of the entry as it was when this editor was opened: what a save says it
        # replaces, whatever a later preview finds in the file.
        self.opened = detail.fingerprint if detail is not None else None
        self.moved = False                   # the entry was changed in the file since it was opened here
        self.saving = False

    def compose(self) -> ComposeResult:
        yield Static(f"Edit {self.key}" if self.key else "New entry (typed by hand)", id="edit-head", markup=False)
        with Horizontal():
            yield TextArea(self.original, id="editor", tab_behavior="indent", soft_wrap=True, show_line_numbers=False,
                           placeholder="Type or paste one BibTeX entry, for example:\n\n" + EXAMPLE)
            with Vertical(id="edit-right", classes="pane"):
                with VerticalScroll():
                    yield Shown(id="preview")
        yield Shown(id="edit-message")
        yield Shown(id="dialog-notice", classes="notice")
        yield Footer()

    def on_mount(self):
        editor = self.query_one("#editor", TextArea)
        editor.indent_type = "tabs"          # the library's entries are indented with tabs
        editor.focus()
        self.query_one("#preview", Shown).show(
            "ctrl+p shows what saving would do: the diff, the house-format findings, a key change, "
            "the status the edit loses, other entries it affects.\nctrl+s saves the text that was previewed.")
        self._message("")
        if self.unread:
            editor.read_only = True          # nothing is typed into a text that is not here yet
            self._read()

    # --- an entry opened before its text was read ------------------------------------------------

    def _read(self):
        self.reading = True
        self._waiting()

        def read(detail):
            self.detail, self.original, self.opened = detail, detail.raw, detail.fingerprint
            self.unread = self.reading = False
            editor = self.query_one("#editor", TextArea)
            editor.load_text(detail.raw)
            editor.read_only = False
            self._message("")
            asked, self.asked = self.asked, []
            for name in asked:               # each as if its key were pressed now
                getattr(self, f"action_{name}")()

        def failed(exc):
            self.reading, self.asked = False, []
            self._message(f"{exc}\n{self.key} could not be read, so there is no text to edit. ctrl+o tries again; "
                          "esc closes the editor.", "error")
        self.app.job(f"read {self.key}", lambda job: api.entry(self.app.ws, self.key), read, failed)

    WORDS = {"preview": "the preview", "save": "the save", "formatter": "the formatter's text"}

    def _waiting(self):
        running = self.app.jobs.busy_label
        line = f"reading {self.key} ... the editor takes typing when its text is here"
        if running and running != f"read {self.key}":
            line += f" (after the running job: {running})"
        if self.asked:
            names = list(dict.fromkeys(self.WORDS[name] for name in self.asked))
            line += f"\nAsked for, and done when the text is here: {', '.join(names)}"
        self._message(line + ".", "accent")

    def _later(self, name):
        """True when the entry's text is not here yet: the action is remembered (while the text
        is being read), and nothing is done now."""
        if not self.unread:
            return False
        if self.reading:
            self.asked.append(name)
            self._waiting()
        return True

    @property
    def text(self):
        return self.query_one("#editor", TextArea).text

    def _message(self, line, role=None):
        self.query_one("#edit-message", Shown).show(Text(line, self.app.colour(role) if role else ""))

    def recolour(self):
        if self.previewed is not None:
            self.query_one("#preview", Shown).show(render.preview(self.previewed[1], self.app.colour))

    # --- preview -----------------------------------------------------------------------------

    def action_preview(self, then=None):
        if self.saving or self._later("preview"):
            return
        raw = self.text

        def done(found):
            self.previewed = (raw, found)
            self.query_one("#preview", Shown).show(render.preview(found, self.app.colour))
            self.moved = self.key is not None and found.fingerprint != self.opened
            if self.moved:
                self._message(self.MOVED.format(key=self.key), "error")
            elif found.problems:
                self._message("Cannot be saved as it is: " + "; ".join(found.problems), "error")
            elif not found.changed:
                self._message("The text is what the file already holds; there is nothing to save.")
            else:
                self._message("Previewed. ctrl+s saves this text." if then is None else then, "accent")
        self.app.job(f"preview the edit of {self.key}" if self.key else "preview the new entry",
                     lambda job: api.preview_edit(self.app.ws, self.key, raw), done,
                     lambda exc: self._message(str(exc), "error"))

    MOVED = ("{key} was changed in the file after it was opened here, by something else. Nothing was saved, and "
             "your text is still in the editor. ctrl+o reads the entry again as it is now; it asks before it "
             "replaces your text.")

    def action_reload(self):
        """Read the entry again from the file; the text in the editor is replaced only after a yes."""
        if self.saving or self.key is None or self.reading:
            return
        if self.unread:                      # the first reading failed: read again
            self._read()
            return

        def read(detail):
            def take():
                self.detail, self.original, self.opened = detail, detail.raw, detail.fingerprint
                self.previewed, self.moved = None, False
                self.query_one("#editor", TextArea).load_text(detail.raw)
                self.query_one("#preview", Shown).show("")
                self._message(f"{self.key} is in the editor as it is in the file now.", "accent")
            if self.text in (self.original, detail.raw):
                take()
            else:
                self.app.confirm(f"Replace the text in the editor with {self.key} as it is in the file now? The text "
                                 "you typed is not kept.", take, yes="Replace my text", no="Keep my text")
        self.app.job(f"read {self.key} again", lambda job: api.entry(self.app.ws, self.key), read,
                     lambda exc: self._message(str(exc), "error"))

    def action_formatter(self):
        if self.saving or self._later("formatter"):
            return
        if self.previewed is None or self.previewed[0] != self.text:
            self._message("Preview first (ctrl+p): the formatter's text belongs to a preview of this text.", "warning")
            return
        corrected = self.previewed[1].corrected_raw
        if not corrected or corrected == self.text:
            self._message("The formatter would write the text as it is.")
            return
        self.query_one("#editor", TextArea).load_text(corrected)
        self.action_preview(then="The formatter's text is in the editor and previewed. ctrl+s saves it.")

    # --- save --------------------------------------------------------------------------------

    def action_save(self):
        if self.saving or self._later("save"):
            return
        raw = self.text
        if self.previewed is None or self.previewed[0] != raw:
            self.action_preview(then="This is what saving would do. ctrl+s again saves it.")
            return
        found = self.previewed[1]
        if self.moved:
            self._message(self.MOVED.format(key=self.key), "error")
            return
        if found.problems:
            self._message("Cannot be saved as it is: " + "; ".join(found.problems), "error")
            return
        if not found.changed:
            self._message("The text is what the file already holds; there is nothing to save.")
            return
        editor = self.query_one("#editor", TextArea)

        def locked(on):
            self.saving, editor.read_only = on, on

        def call(job):
            applied = api.save_edit(self.app.ws, self.key, raw, self.opened)
            written = applied.written[0] if applied.written else None
            return applied, (api.entry(self.app.ws, written) if written else None)

        def done(result):
            applied, now = result
            locked(False)
            lines = [f"Saved: {key}" for key in applied.written]
            lines += [f"Renamed: {old} -> {new}" for old, new in applied.renamed.items()]
            lines += [f"Not written {key}: {reason}" for key, reason in applied.refused]
            if applied.backup is not None:
                lines.append(f"Backup before the change: {applied.backup.stamp} (Library state, z restores it)")
            if applied.saved_copy is not None:
                lines.append(f"cdl.bib as it was before the change is kept at {applied.saved_copy}")
            lines += list(applied.notes)
            if not applied.written:
                self._message("\n".join(lines) or "Nothing was written.", "error")
            elif self.text == raw:
                self.dismiss(lines)
            else:                            # the editor holds other text than was saved: it stays, with that text
                for line in lines:
                    self.app.say(line)
                self.detail, self.key, self.original, self.opened = now, now.key, now.raw, now.fingerprint
                self.previewed = None
                self.query_one("#edit-head", Static).update(f"Edit {self.key}")
                self._message(f"{lines[0]}. The editor holds text that differs from what was saved; ctrl+p previews "
                              "it.", "warning")
                self.app.refresh_library()

        def refused(exc):
            locked(False)
            problems = list(exc.problems) if isinstance(exc, EditRefused) else []
            self._message("\n".join([str(exc)] + [f"  {line}" for line in problems if line != str(exc)]), "error")
        locked(True)                         # nothing can be typed into a text that is being saved
        self._message(f"saving {found.new_key or self.key} ... the editor takes no typing until it is done", "accent")
        self.app.job(f"save {found.new_key or self.key}", call, done, refused)

    # --- close -------------------------------------------------------------------------------

    def unsaved(self):
        if self.text != self.original:
            return f"the edited text of {self.key}" if self.key else "the new entry being typed"
        return None

    def action_close(self):
        if self.saving:
            self._message("A save is under way; the editor closes when it is done.", "warning")
            return
        if self.text == self.original:
            self.dismiss(None)
            return
        self.app.confirm("Close the editor? The edited text was not saved and is not kept.",
                         lambda: self.dismiss(None), yes="Close without saving", no="Keep editing")
