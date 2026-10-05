"""The Library view: search box, the table of entries with a status mark each, and the
selected entry's text, issues and evidence."""
from collections import Counter

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Input, TabbedContent, TabPane

from .. import api
from ..errors import CdlbibError
from . import render
from .widgets import Shown, View, mark

CHUNK = 400     # rows put into the table at a time; more are added as the cursor nears the end


def cut(text, width):
    text = " ".join(str(text or "").split())
    return text if len(text) <= width else text[:width - 1] + "…"


class DetailPanes(Vertical):
    """One entry: its text, its issues, its evidence."""

    TABS = ("d-entry", "d-issues", "d-evidence")

    def compose(self) -> ComposeResult:
        with TabbedContent(id="detail"):
            with TabPane("Entry", id="d-entry"):
                with VerticalScroll():
                    yield Shown(id="t-entry")
            with TabPane("Issues", id="d-issues"):
                with VerticalScroll():
                    yield Shown(id="t-issues")
            with TabPane("Evidence", id="d-evidence"):
                with VerticalScroll():
                    yield Shown(id="t-evidence")

    detail = None

    def show(self, detail):
        self.detail = detail
        colour = self.app.colour
        if detail is None:
            for name in ("t-entry", "t-issues", "t-evidence"):
                self.query_one(f"#{name}", Shown).show("")
            return
        self.query_one("#t-entry", Shown).show(Text(detail.raw.expandtabs(4)))
        self.query_one("#t-issues", Shown).show(render.issues(detail, colour))
        self.query_one("#t-evidence", Shown).show(render.evidence(detail, colour))

    def waiting(self, summary, running):
        """The entry's details are being read (a job, like every reading of the library). Until
        they are here, what the table already knows of the entry is shown, and behind a running
        job the line says what is waited for."""
        self.detail = None
        out = self.app.writer()
        out.line(f"{summary.key} ({summary.type})", bold=True)
        for label, value in (("authors", summary.authors), ("year", summary.year), ("title", summary.title),
                             ("venue", summary.venue), ("doi", summary.doi)):
            if value:
                out.line(f"  {label}: {value}")
        out.part("  status: ").text.append_text(render.status_text(summary.status, self.app.colour))
        out.line()
        for issue in summary.issues:
            out.line(f"  {issue}", "warning")
        out.line()
        out.line(f"The entry's text, issues and evidence load when the running job finishes: {running}" if running
                 else "reading the entry's text, issues and evidence ...", "muted")
        for name in ("t-entry", "t-issues", "t-evidence"):
            self.query_one(f"#{name}", Shown).show(out.text)

    def next_tab(self):
        tabs = self.query_one("#detail", TabbedContent)
        tabs.active = self.TABS[(self.TABS.index(tabs.active) + 1) % len(self.TABS)]

    def open(self, name):
        self.query_one("#detail", TabbedContent).active = name


class LibraryView(View):
    BINDINGS = [
        Binding("slash", "search", "Search"),
        Binding("escape", "table", "Table", show=False),
        Binding("f", "filter", "Status filter"),
        Binding("d", "detail_tab", "Detail tab"),
        Binding("e", "edit", "Edit"),
        Binding("n", "new", "New entry"),
        Binding("c", "check", "Check"),
        Binding("a", "approve", "Approve"),
        Binding("v", "revoke", "Revoke"),
    ]
    DEFAULT_CSS = """
    LibraryView #left { width: 3fr; }
    LibraryView #right { width: 2fr; }
    LibraryView #counts { height: auto; padding: 0 1; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.matches = []        # the summaries the search gave
        self.shown = 0           # how many of them are in the table
        self.status = None       # the status filter
        self.selected = None     # the key under the cursor
        self.read = {}           # {key: desk.EntryDetail} read since the library last changed
        self.searched = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="left"):
                yield Input(placeholder='Search: words, field:word (author: title: year: status: ...), "a phrase"',
                            id="search")
                yield Shown(id="counts")
                yield DataTable(id="entries", cursor_type="row", zebra_stripes=False)
            with Vertical(id="right", classes="pane"):
                yield DetailPanes(id="library-detail")

    def on_mount(self):
        table = self.query_one("#entries", DataTable)
        table.add_columns(" ", "Key", "Authors", "Year", "Title", "Venue")
        self.query_one("#counts", Shown).show("reading the library ...")

    # --- what the app tells ------------------------------------------------------------------

    def activated(self):
        self.query_one("#entries", DataTable).focus()

    def library_changed(self):
        self._stale = True
        self.read = {}               # the details read from the library as it was
        self.search()

    def recolour(self):
        self._fill(keep=self.selected)
        self.query_one("#library-detail", DetailPanes).show(self.detail)

    @property
    def detail(self):
        return self.query_one("#library-detail", DetailPanes).detail

    # --- search ------------------------------------------------------------------------------

    @on(Input.Changed, "#search")
    def _typed(self, event):
        self.search()

    @on(Input.Submitted, "#search")
    def _entered(self, event):
        self.action_table()

    def search(self):
        """Filter the summaries that are already loaded. This is the one call into cdlbib.api
        made on the interface's own thread: api.search over a list is a pure function of that
        list and the typed text (no file, database, lock or network; the list is replaced, never
        changed, when the library is read again), so it cannot meet the job that is running,
        and a search stays usable during a long check or send."""
        try:
            self.matches = api.search(self.app.entries, self.query_one("#search", Input).value, status=self.status)
        except CdlbibError as exc:
            self._search_failed(exc)
            return
        self.searched = True
        self._fill(keep=self.selected)

    def _search_failed(self, exc):
        self.query_one("#counts", Shown).show(Text(str(exc), self.app.colour("error")))

    def _row(self, item):
        glyph, role = mark(item.status)
        colour = self.app.colour(role)
        return (Text(glyph, colour), item.key, cut(item.authors, 24), item.year, cut(item.title, 50),
                cut(item.venue, 30))

    def _fill(self, keep=None):
        table = self.query_one("#entries", DataTable)
        position = next((i for i, item in enumerate(self.matches) if item.key == keep), 0) if keep else 0
        self.shown = min(len(self.matches), max(CHUNK, position + CHUNK // 2))
        table.clear()
        for item in self.matches[:self.shown]:
            table.add_row(*self._row(item), key=item.key)
        self._counts()
        if self.matches:
            table.move_cursor(row=position)
            self._select(self.matches[position].key)
        else:
            self.selected = None
            self.query_one("#library-detail", DetailPanes).show(None)

    def _more(self, upto=None):
        """Put the next rows into the table (all of them up to ``upto``)."""
        table = self.query_one("#entries", DataTable)
        end = min(len(self.matches), max(self.shown + CHUNK, (upto or 0) + 1))
        for item in self.matches[self.shown:end]:
            table.add_row(*self._row(item), key=item.key)
        self.shown = end
        self._counts()

    def _counts(self):
        colour, entries = self.app.colour, self.app.entries
        out = Text()
        out.append(f"{len(self.matches)} of {len(entries)} entries", "bold")
        if self.shown < len(self.matches):
            out.append(f" (the first {self.shown} are listed; more are added as you move down)", colour("muted"))
        if self.status:
            out.append(f" · only status {self.status} (f: next)", colour("warning"))
        out.append("\n")
        for status, count in sorted(Counter(item.status for item in entries).items()):
            glyph, role = mark(status)
            out.append(f"{glyph} {status} {count}   ", colour(role))
        self.query_one("#counts", Shown).show(out)

    # --- the selected entry ------------------------------------------------------------------

    @on(DataTable.RowHighlighted, "#entries")
    def _highlighted(self, event):
        if event.row_key is None or event.row_key.value is None:
            return
        if event.cursor_row >= self.shown - 20 and self.shown < len(self.matches):
            self._more()
        self._select(event.row_key.value)

    def _select(self, key):
        if key == self.selected and self.detail is not None and self.detail.key == key and not self._stale:
            return
        self.selected, self._stale = key, False
        panes = self.query_one("#library-detail", DetailPanes)
        if key in self.read:                 # read since the library last changed: shown at once, no job
            panes.show(self.read[key])
            return
        summary = next((item for item in self.matches if item.key == key), None)
        if summary is not None:
            panes.waiting(summary, self.app.jobs.busy_label)

        def done(detail):
            self.read[detail.key] = detail
            if detail.key == self.selected:
                panes.show(detail)
        self.app.job(f"read {key}", lambda job: api.entry(self.app.ws, key), done, key="detail", quiet=True)

    _stale = False

    def reload_detail(self):
        self._stale = True
        self.read.pop(self.selected, None)
        if self.selected:
            self._select(self.selected)

    # --- actions -----------------------------------------------------------------------------

    def action_search(self):
        self.query_one("#search", Input).focus()

    def action_table(self):
        self.query_one("#entries", DataTable).focus()

    def action_filter(self):
        present = [None] + sorted({item.status for item in self.app.entries})
        self.status = present[(present.index(self.status) + 1) % len(present)] if self.status in present else None
        self.search()

    def action_detail_tab(self):
        self.query_one("#library-detail", DetailPanes).next_tab()

    def _current(self):
        detail = self.detail
        if detail is None or detail.key != self.selected:
            self.app.notify("No entry is selected yet.")
            return None
        return detail

    def action_edit(self):
        detail = self._current()
        if detail is not None:
            self.app.edit(detail)

    def action_new(self):
        self.app.edit(None)

    def action_check(self):
        if self.selected:
            self.app.check_keys([self.selected], f"check {self.selected}")

    def action_approve(self):
        detail = self._current()
        if detail is not None:
            self.app.approve(detail)

    def action_revoke(self):
        detail = self._current()
        if detail is not None:
            self.app.revoke(detail)
