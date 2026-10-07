"""Small pieces every screen uses: a text pane, the dialogs, the file picker, the help."""
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.scrollbar import ScrollBar, ScrollBarRender
from textual.widgets import Button, DataTable, DirectoryTree, Input, Static


def focus_now(widget):
    """Give ``widget`` the focus before the next key is handled. Textual's own ``focus()`` puts
    the change at the end of the queue of messages, behind the keys that are already waiting
    there: typed quickly, the key after the one that moved the focus (the letter after ``/``,
    the action after the key of a view) would go to the part that had the focus before."""
    widget.screen.set_focus(widget)


class WholeCells(ScrollBarRender):
    """A scrollbar drawn in whole cells only: no partial-block glyphs at its ends."""
    VERTICAL_BARS = [" "]
    HORIZONTAL_BARS = [" "]


ScrollBar.renderer = WholeCells


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


def cut(text, width):
    """``text`` on one line, at most ``width`` cells, ending in an ellipsis when it was cut."""
    text = " ".join(str(text or "").split())
    width = max(1, int(width))
    return text if len(text) <= width else text[:width - 1] + "…"


def short_path(path, width):
    """A folder's path in at most ``width`` cells: cut from the left, on a folder name."""
    text = str(path)
    if len(text) <= width:
        return text
    parts = text.split("/")
    kept = []
    for part in reversed(parts):
        if len("/".join([part, *kept])) + 2 > width:
            break
        kept.insert(0, part)
    return "…/" + "/".join(kept) if kept else "…" + text[-(width - 1):]


class Table(DataTable):
    """A table whose columns are laid out for its width (``fill_table``). ``filler`` is called
    to lay them out again when the width changes, and when the table comes back on the screen
    after its rows were set while it was hidden."""

    filler = None
    filled_for = None

    def _refit(self):
        if self.filler is not None and self.size.width and self.filled_for != self.size.width:
            self.filler()

    def on_resize(self, event):
        self._refit()

    def on_show(self, event):
        self._refit()


def fill_table(table, columns, rows, keys=None):
    """Put ``rows`` into a DataTable so that every column is whole within the table's width.
    ``columns``: [(label, width)] where width is a number of cells, or a float weight for a
    column that shares what is left. Cells of text are cut to their column with an ellipsis;
    rich Text cells (marks) are taken as they are."""
    total = table.size.width or max(40, table.app.size.width // 2)
    table.filled_for = table.size.width
    room = total - 2 * len(columns) - 1                      # a cell of padding either side of each column
    fixed = sum(width for _, width in columns if isinstance(width, int))
    weight = sum(width for _, width in columns if not isinstance(width, int)) or 1
    spare = max(0, room - fixed)
    widths = [width if isinstance(width, int) else max(6, int(spare * width / weight)) for _, width in columns]
    table.clear(columns=True)
    for (label, _), width in zip(columns, widths):
        table.add_column(cut(label, width) if label.strip() else label, width=width)
    add_rows(table, widths, rows, keys)
    return widths


def add_rows(table, widths, rows, keys=None):
    """More rows for a table that ``fill_table`` laid out (``widths``: what it returned)."""
    for number, row in enumerate(rows):
        cells = [cell if isinstance(cell, Text) else cut(cell, width) for cell, width in zip(row, widths)]
        table.add_row(*cells, key=None if keys is None else keys[number])


class Shown(Static):
    """A pane of text. ``plain`` is the text it shows now. A line too long for the pane is
    continued under its own first word (indented lists stay lists); a text made with
    ``no_wrap`` is shown line for line."""

    plain = ""
    _text = None

    def show(self, content):
        text = content if isinstance(content, Text) else Text(str(content))
        self.plain, self._text = text.plain, text
        self._draw()

    def on_resize(self, event):
        if self._text is not None:
            self._draw()

    def on_show(self, event):
        """Shown again after it was hidden (another view was in front): a text that was set
        meanwhile was laid out for no width, and is laid out now."""
        if self._text is not None and self.drawn_for != self.size.width:
            self._draw()

    drawn_for = None     # the width the text was last laid out for

    def _draw(self):
        text, width = self._text, self.size.width
        self.drawn_for = width
        if text.no_wrap or width < 12:
            self.update(text)
            return
        out = wrapped(text, width)
        out.no_wrap = True
        self.update(out)


def wrapped(text, width):
    """``text`` with every line that is longer than ``width`` cells continued on further
    lines, indented two cells more than the line itself. A line is broken at a space; a word
    too long for a line (a path, an address) is broken after a ``/``, ``-`` or ``.``."""
    out = Text()
    for line in text.split("\n", allow_blank=True):
        plain = line.plain
        indent = len(plain) - len(plain.lstrip(" "))
        hang = min(indent + 2, max(0, width - 10))
        start, room = 0, width
        while len(plain) - start > room:
            window = plain[start:start + room]
            at = window.rfind(" ")
            if at > (indent if start == 0 else 0):
                end, following = start + at, start + at + 1
            else:
                at = max(window.rfind(mark) for mark in "/-.")
                end = following = start + (at + 1 if at > 0 else room)
            if start:
                out.append(" " * hang)
            out.append_text(line[start:end])
            out.append("\n")
            start, room = following, max(10, width - hang)
        if start:
            out.append(" " * hang)
        out.append_text(line[start:])
        out.append("\n")
    out.rstrip()
    return out


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
            yield Shown(id="dialog-notice", classes="notice")

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
            yield Shown(id="dialog-notice", classes="notice")

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
            yield Shown(id="dialog-notice", classes="notice")

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
            yield Shown(id="dialog-notice", classes="notice")

    def on_mount(self):
        if self.text is not None:
            self.query_one("#page", Shown).show(self.text)
        self.query(Input).first().focus()

    def values(self):
        return {name: self.query_one(f"#field-{name}", Input).value.strip() for name, _, _ in self.fields}

    def action_accept(self):
        self.dismiss(self.values())

    def unsaved(self):
        typed = {name: value for name, value in self.values().items()
                 if value != (dict((n, v or "") for n, _, v in self.fields)[name]).strip()}
        return f"what was typed in “{self.heading}”" if typed else None

    def action_cancel(self):
        if self.unsaved():
            self.app.confirm(f"Close “{self.heading}”? What was typed is not kept.", lambda: self.dismiss(None),
                             yes="Close without keeping it", no="Keep editing")
            return
        self.dismiss(None)

    @on(Input.Submitted)
    def submitted(self, event):
        inputs = list(self.query(Input))
        position = inputs.index(event.input)
        if position + 1 < len(inputs):
            focus_now(inputs[position + 1])
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
            yield Shown(id="dialog-notice", classes="notice")

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

    def on_descendant_focus(self, event):
        """The app alone says which view is in front. Left to themselves, Textual's tabs follow
        the focus: they switch, some messages later, to the pane holding whatever part was
        focused, and that late switch would undo the key of another view pressed meanwhile."""
        event.stop()

    def relayout(self):
        """Lay out again what was drawn while the view was not on the screen (it had no size
        then): every pane of text for the width it has now; a view with tables adds those."""
        for pane in self.query(Shown):
            if pane._text is not None and pane.drawn_for != pane.size.width:
                pane._draw()

    def recolour(self):
        """The theme changed: draw the coloured text again."""

    def library_changed(self):
        """The entries were read again."""

    def state_changed(self):
        """The library's state was read again."""
