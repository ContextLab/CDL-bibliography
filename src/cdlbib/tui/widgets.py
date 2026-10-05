"""Small pieces every screen uses: a text pane, the dialogs, the file picker, the help."""
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Static

# status -> (mark, role colour). The status itself is always shown beside its mark, as the core gives it.
MARKS = {
    "metadata_verified": ("✓", "success"),
    "human_verified": ("◆", "success"),
    "needs_review": ("?", "warning"),
    "provider_error": ("!", "error"),
    "pending": ("·", "muted"),
}


def mark(status):
    return MARKS.get(status, ("•", "muted"))


class Shown(Static):
    """A pane of text. ``plain`` is the text it shows now."""

    plain = ""

    def show(self, content):
        text = content if isinstance(content, Text) else Text(str(content))
        self.plain = text.plain
        self.update(text)


class Writer:
    """Builds a rich Text line by line with the theme's role colours."""

    def __init__(self, colour):
        self.colour, self.text = colour, Text()

    def line(self, content="", role=None, bold=False):
        style = self._style(role, bold)
        self.text.append(str(content) + "\n", style)
        return self

    def part(self, content, role=None, bold=False):
        self.text.append(str(content), self._style(role, bold))
        return self

    def head(self, content):
        if self.text.plain and not self.text.plain.endswith("\n\n"):
            self.text.append("\n")
        return self.line(content, "accent", bold=True)

    def _style(self, role, bold):
        parts = ([self.colour(role)] if role else []) + (["bold"] if bold else [])
        return " ".join(parts) or None


class ConfirmScreen(ModalScreen):
    """A yes/no question. Dismisses with True or False; Escape is no."""

    BINDINGS = [Binding("y", "answer(True)", "Yes"), Binding("n", "answer(False)", "No"),
                Binding("escape", "answer(False)", "No", show=False)]

    def __init__(self, question, yes="Yes", no="No"):
        super().__init__()
        self.question, self.yes, self.no = question, yes, no

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Shown(id="question")
            with Horizontal(classes="buttons"):
                yield Button(f"{self.yes} (y)", id="yes", variant="primary")
                yield Button(f"{self.no} (n)", id="no")

    def on_mount(self):
        self.query_one("#question", Shown).show(self.question)
        self.query_one("#no", Button).focus()

    def action_answer(self, value):
        self.dismiss(bool(value))

    @on(Button.Pressed)
    def pressed(self, event):
        self.dismiss(event.button.id == "yes")


class ChoiceScreen(ModalScreen):
    """A question with lettered answers. ``choices``: [(letter, value, what it does)].
    Dismisses with the value chosen, or None on Escape when ``escape`` allows it."""

    def __init__(self, question, choices, escape=True, wide=False):
        super().__init__()
        self.question, self.choices, self.escape, self.wide = question, list(choices), escape, wide

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide" if self.wide else "dialog"):
            with VerticalScroll(classes="dialog-text"):
                yield Shown(id="question")
            with Vertical(classes="choices"):
                for letter, value, label in self.choices:
                    yield Button(Text(f"[{letter}] {label}"), id=f"choice-{value}", classes="choice")

    def on_mount(self):
        self.query_one("#question", Shown).show(self.question)
        self.query(Button).first().focus()

    def on_key(self, event):
        for letter, value, _ in self.choices:
            if event.character == letter:
                event.stop()
                self.dismiss(value)
                return
        if event.key == "escape" and self.escape:
            event.stop()
            self.dismiss(None)

    @on(Button.Pressed)
    def pressed(self, event):
        self.dismiss(event.button.id[len("choice-"):])


class TextScreen(ModalScreen):
    """A page of text to read; Escape or q closes it."""

    BINDINGS = [Binding("escape", "close", "Close"), Binding("q", "close", "Close", show=False)]

    def __init__(self, title, text):
        super().__init__()
        self.heading, self.text = title, text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Static(self.heading, classes="title", markup=False)
            with VerticalScroll(classes="dialog-text"):
                yield Shown(id="page")
            yield Static("Esc closes", classes="hint")

    def on_mount(self):
        self.query_one("#page", Shown).show(self.text)
        self.query_one(VerticalScroll).focus()

    def action_close(self):
        self.dismiss(None)


class PromptScreen(ModalScreen):
    """One or several labelled inputs. ``fields``: [(name, label, value)]. Dismisses with
    {name: text}, or None on Escape."""

    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "accept", "OK")]

    def __init__(self, title, fields, ok="OK", text=None):
        super().__init__()
        self.heading, self.fields, self.ok, self.text = title, list(fields), ok, text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Static(self.heading, classes="title", markup=False)
            if self.text is not None:
                with VerticalScroll(classes="dialog-text"):
                    yield Shown(id="page")
            for name, label, value in self.fields:
                yield Static(label, classes="label", markup=False)
                yield Input(value=value or "", id=f"field-{name}")
            with Horizontal(classes="buttons"):
                yield Button(f"{self.ok} (ctrl+s)", id="ok", variant="primary")
                yield Button("Cancel (esc)", id="cancel")

    def on_mount(self):
        if self.text is not None:
            self.query_one("#page", Shown).show(self.text)
        self.query(Input).first().focus()

    def values(self):
        return {name: self.query_one(f"#field-{name}", Input).value.strip() for name, _, _ in self.fields}

    def action_accept(self):
        self.dismiss(self.values())

    def action_cancel(self):
        self.dismiss(None)

    @on(Input.Submitted)
    def submitted(self, event):
        inputs = list(self.query(Input))
        position = inputs.index(event.input)
        if position + 1 < len(inputs):
            inputs[position + 1].focus()
        else:
            self.action_accept()

    @on(Button.Pressed)
    def pressed(self, event):
        self.action_accept() if event.button.id == "ok" else self.action_cancel()


class FilePicker(ModalScreen):
    """Choose a file from the folder tree. Dismisses with its path, or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, start=None, suffix=None):
        super().__init__()
        self.start = Path(start or Path.home()).expanduser()
        if not self.start.is_dir():
            self.start = self.start.parent if self.start.parent.is_dir() else Path.home()
        self.suffix = suffix

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide tall"):
            yield Static(f"Choose a file under {self.start}" + (f" ({self.suffix})" if self.suffix else ""),
                         classes="title", markup=False)
            yield DirectoryTree(str(self.start), id="tree")
            yield Static("Enter opens a folder or chooses a file; Esc cancels", classes="hint")

    def on_mount(self):
        self.query_one(DirectoryTree).focus()

    @on(DirectoryTree.FileSelected)
    def chosen(self, event):
        if self.suffix and event.path.suffix.lower() != self.suffix:
            self.app.notify(f"{event.path.name} is not a {self.suffix} file")
            return
        self.dismiss(event.path)

    def action_cancel(self):
        self.dismiss(None)


class View(Vertical):
    """One of the main views. The app tells it when it is shown, when the library or its
    state was read again, and when the theme changed."""

    def activated(self):
        """The view was brought to the front: load what it shows and take the focus."""

    def recolour(self):
        """The theme changed: draw the coloured text again."""

    def library_changed(self):
        """The entries were read again."""

    def state_changed(self):
        """The library's state was read again."""
