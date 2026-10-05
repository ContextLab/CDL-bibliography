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
    """Dismisses with the lines that say what was saved, or None."""

    BINDINGS = [
        Binding("ctrl+p", "preview", "Preview", priority=True),
        Binding("ctrl+r", "formatter", "Use the formatter's text", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "close", "Close", priority=True),
    ]
    DEFAULT_CSS = """
    EditScreen #edit-head { height: 1; background: $primary; color: $cdl-on-primary; padding: 0 1; text-style: bold; }
    EditScreen #editor { width: 1fr; height: 1fr; }
    EditScreen #edit-right { width: 1fr; }
    EditScreen #edit-message { height: auto; padding: 0 1; }
    """

    def __init__(self, detail=None):
        super().__init__()
        self.detail = detail                 # desk.EntryDetail of the entry; None for a new one
        self.key = detail.key if detail is not None else None
        self.original = detail.raw if detail is not None else ""
        self.previewed = None                # (the text previewed, desk.EditPreview)

    def compose(self) -> ComposeResult:
        yield Static(f"Edit {self.key}" if self.key else "New entry (typed by hand)", id="edit-head", markup=False)
        with Horizontal():
            yield TextArea(self.original, id="editor", tab_behavior="indent", soft_wrap=True, show_line_numbers=False,
                           placeholder="Type or paste one BibTeX entry, for example:\n\n" + EXAMPLE)
            with Vertical(id="edit-right", classes="pane"):
                with VerticalScroll():
                    yield Shown(id="preview")
        yield Shown(id="edit-message")
        yield Footer()

    def on_mount(self):
        editor = self.query_one("#editor", TextArea)
        editor.indent_type = "tabs"          # the library's entries are indented with tabs
        editor.focus()
        self.query_one("#preview", Shown).show(
            "ctrl+p shows what saving would do: the diff, the house-format findings, a key change, "
            "the status the edit loses, other entries it affects.\nctrl+s saves the text that was previewed.")
        self._message("")

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
        raw = self.text

        def done(found):
            self.previewed = (raw, found)
            self.query_one("#preview", Shown).show(render.preview(found, self.app.colour))
            if found.problems:
                self._message("Cannot be saved as it is: " + "; ".join(found.problems), "error")
            elif not found.changed:
                self._message("The text is what the file already holds; there is nothing to save.")
            else:
                self._message("Previewed. ctrl+s saves this text." if then is None else then, "accent")
        self.app.job(f"preview the edit of {self.key}" if self.key else "preview the new entry",
                     lambda job: api.preview_edit(self.app.ws, self.key, raw), done,
                     lambda exc: self._message(str(exc), "error"))

    def action_formatter(self):
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
        raw = self.text
        if self.previewed is None or self.previewed[0] != raw:
            self.action_preview(then="This is what saving would do. ctrl+s again saves it.")
            return
        found = self.previewed[1]
        if found.problems:
            self._message("Cannot be saved as it is: " + "; ".join(found.problems), "error")
            return
        if not found.changed:
            self._message("The text is what the file already holds; there is nothing to save.")
            return

        def done(applied):
            lines = [f"Saved: {key}" for key in applied.written]
            lines += [f"Renamed: {old} -> {new}" for old, new in applied.renamed.items()]
            lines += [f"Not written {key}: {reason}" for key, reason in applied.refused]
            if applied.backup is not None:
                lines.append(f"Backup before the change: {applied.backup.stamp} (Library state, z restores it)")
            if applied.saved_copy is not None:
                lines.append(f"cdl.bib as it was before the change is kept at {applied.saved_copy}")
            lines += list(applied.notes)
            if applied.written:
                self.dismiss(lines)
            else:
                self._message("\n".join(lines) or "Nothing was written.", "error")

        def refused(exc):
            problems = list(exc.problems) if isinstance(exc, EditRefused) else []
            self._message("\n".join([str(exc)] + [f"  {line}" for line in problems if line != str(exc)]), "error")
        self.app.job(f"save {found.new_key or self.key}",
                     lambda job: api.save_edit(self.app.ws, self.key, raw, found.fingerprint), done, refused)

    # --- close -------------------------------------------------------------------------------

    def unsaved(self):
        if self.text != self.original:
            return f"the edited text of {self.key}" if self.key else "the new entry being typed"
        return None

    def action_close(self):
        if self.text == self.original:
            self.dismiss(None)
            return
        self.app.confirm("Close the editor? The edited text was not saved and is not kept.",
                         lambda: self.dismiss(None), yes="Close without saving", no="Keep editing")
