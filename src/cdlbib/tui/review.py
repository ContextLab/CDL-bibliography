"""The Review view: the entries waiting for a person, with approve and revoke."""
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable

from .. import api
from .library import NOT_READ, DetailPanes
from .widgets import Shown, Table, View, fill_table, focus_now, mark


class ReviewView(View):
    BINDINGS = [
        Binding("t", "toggle", "Changed/all"),
        Binding("r", "reload", "Reload"),
        Binding("d", "detail_tab", "Tab"),
        Binding("a", "approve", "Approve"),
        Binding("v", "revoke", "Revoke"),
        Binding("e", "edit", "Edit"),
        Binding("c", "check", "Check"),
    ]
    DEFAULT_CSS = """
    ReviewView #review-left { width: 3fr; }
    ReviewView #review-right { width: 2fr; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.every = False       # False: the changed entries (compared with the GitHub master); True: all
        self.queue = None        # [desk.EntryDetail]; None: not read yet
        self.stale = True
        self.selected = None
        self.failure = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="review-left"):
                yield Shown(id="review-head", classes="message")
                yield Table(id="queue", cursor_type="row")
            with Vertical(id="review-right", classes="pane"):
                yield DetailPanes(id="review-detail")

    def on_mount(self):
        self._head()
        self._fill()
        self.query_one("#queue", Table).filler = self._fill

    def activated(self):
        focus_now(self.query_one("#queue", DataTable))
        if self.stale:
            self.action_reload()

    def library_changed(self):
        self.stale = True
        if self.app.active_view == "review":
            self.action_reload()

    def recolour(self):
        self._fill()
        panes = self.query_one("#review-detail", DetailPanes)
        panes.show(panes.detail)

    # --- the queue ---------------------------------------------------------------------------

    def _head(self):
        out = self.app.writer()
        what = ("Every entry that is not verified or approved" if self.every else
                "New or edited entries (compared with the GitHub master) that are not verified or approved")
        count = "" if self.queue is None else f": {len(self.queue)}"
        out.line(what + count, bold=True)
        if self.failure:
            out.line(self.failure, "error")
            if not self.every:
                out.line("t lists every entry waiting for review; that needs no network.", "muted")
        out.line("a approves and v revokes under your GitHub login; a lookup, a proposal or a model reading is "
                 "never an approval.", "muted")
        self.query_one("#review-head", Shown).show(out.text)

    def action_reload(self):
        every = self.every
        self.stale = False

        def done(queue):
            if every != self.every:
                return
            self.queue, self.failure = queue, None
            self._fill()

        def failed(exc):
            self.queue, self.failure = [], str(exc)
            self._fill()
        self.app.job("read the review queue", lambda job: api.review_queue(self.app.ws, all_entries=every), done,
                     failed, key="review")

    def action_toggle(self):
        self.every = not self.every
        self.queue = None
        self._head()
        self.action_reload()

    def _fill(self):
        table = self.query_one("#queue", DataTable)
        queue = self.queue or []
        rows = []
        for detail in queue:
            glyph, role = mark(detail.status)
            colour = self.app.colour(role)
            rows.append((Text(glyph, colour), detail.key, Text(detail.status, colour), (detail.issues or [""])[0]))
        longest = max([len(detail.key) for detail in queue] + [3])
        fill_table(table, [(" ", 1), ("Key", min(longest, 22)), ("Status", 17), ("First issue", 1.0)], rows,
                   [detail.key for detail in queue])
        self._head()
        keys = [detail.key for detail in queue]
        if keys:
            position = keys.index(self.selected) if self.selected in keys else 0
            table.move_cursor(row=position)
            self._select(keys[position])
        else:
            self.selected = None
            self.query_one("#review-detail", DetailPanes).show(None)

    @on(DataTable.RowHighlighted, "#queue")
    def _highlighted(self, event):
        if event.row_key is not None and event.row_key.value is not None:
            self._select(event.row_key.value)

    def _select(self, key):
        self.selected = key

        def done(detail):
            if detail.key == self.selected:
                self.query_one("#review-detail", DetailPanes).show(detail)
        self.app.job(f"read {key}", lambda job: api.entry(self.app.ws, key), done, key="review-detail", quiet=True)

    # --- actions -----------------------------------------------------------------------------

    def _current(self):
        """As LibraryView._current: an entry is approved or revoked only when its detail is shown."""
        detail = self.query_one("#review-detail", DetailPanes).detail
        if detail is None or detail.key != self.selected:
            self.app.notify(NOT_READ.format(key=self.selected) if self.selected else "No entry is selected.")
            return None
        return detail

    def action_detail_tab(self):
        self.query_one("#review-detail", DetailPanes).next_tab()

    def action_approve(self):
        detail = self._current()
        if detail is not None:
            self.app.approve(detail)

    def action_revoke(self):
        detail = self._current()
        if detail is not None:
            self.app.revoke(detail)

    def action_edit(self):
        """As in the Library view: an entry whose detail is still being read is opened at once,
        and the editor reads it itself."""
        detail = self.query_one("#review-detail", DetailPanes).detail
        if detail is not None and detail.key == self.selected:
            self.app.edit(detail)
        elif self.selected:
            self.app.edit(key=self.selected)
        else:
            self.app.notify("No entry is selected.")

    def action_check(self):
        if self.selected:
            self.app.check_keys([self.selected], f"check {self.selected}")
