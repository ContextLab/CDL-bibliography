"""What a picture of the terminal interface cannot guarantee later: at three window sizes, in
every view and on the screens laid over them, no part of the window lies over another, no
label, button, placeholder or table column is cut by its box, and the footer shows each key
immediately followed by its own label, none of them cut.

The real app over the real core (tests/tui_support.py); the regions are Textual's own.
"""
import pytest

pytest.importorskip("textual", reason="the terminal interface needs the optional package textual (pip install 'cdlbib[tui]')")

import conftest  # noqa: E402
import tui_support as T  # noqa: E402
from test_complete_identify import library_entry  # noqa: E402
from test_desk import GLOC08, KAHA12, TENE11, ZOLL90  # noqa: E402

SIZES = [(100, 30), (120, 36), (160, 48)]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    T.isolate(monkeypatch, tmp_path)
    T.offline(monkeypatch)
    yield
    conftest.no_real_library_touched()


def _laid_out(screen):
    """The widgets of the screen that are drawn now (overlays such as notifications apart)."""
    found = []
    for widget in screen.walk_children(with_self=False):
        name = type(widget).__name__
        if name in ("ToastRack", "Toast", "Tooltip", "ScrollBar", "ScrollBarCorner", "SelectOverlay"):
            continue
        if not widget.display or any(not parent.display for parent in widget.ancestors):
            continue
        if widget.region.area:
            found.append(widget)
    return found


def problems(app):
    """Every structural fault of the screen as it is now, in words ([] when it is clean)."""
    from textual.widgets import Button, DataTable, Footer, Input, Static
    from textual.widgets._footer import FooterKey
    screen, found = app.screen, []
    drawn = _laid_out(screen)
    shown = set(drawn)
    whole = screen.region
    for widget in drawn:
        region, name = widget.region, f"{type(widget).__name__}#{widget.id or ''}"
        if not whole.contains_region(region) and not any(
                getattr(parent, "allow_vertical_scroll", False) or getattr(parent, "allow_horizontal_scroll", False)
                for parent in widget.ancestors if parent is not screen):
            found.append(f"{name} reaches outside the window: {region}")
        siblings = [other for other in widget.parent.children if other in shown and other is not widget]
        for other in siblings:
            if widget.styles.layer == other.styles.layer and region.overlaps(other.region) \
                    and region.intersection(other.region).area:
                found.append(f"{name} lies over {type(other).__name__}#{other.id or ''}: {region} and {other.region}")
        room = widget.content_size.width
        if getattr(widget, "_text", None) is not None and getattr(widget, "drawn_for", room) != widget.size.width:
            found.append(f"the text of {name} was laid out for {widget.drawn_for} cells, and it has {widget.size.width}")
        if isinstance(widget, Button):
            if len(str(widget.label)) > room and "choice" not in widget.classes:
                found.append(f"the button {str(widget.label)!r} is cut: {room} cells")
        elif isinstance(widget, Input):
            if len(widget.placeholder) > room:
                found.append(f"the placeholder {widget.placeholder!r} of {name} is cut: {room} cells")
        elif isinstance(widget, DataTable):
            if widget.virtual_size.width > widget.size.width:
                found.append(f"the table {name} is wider ({widget.virtual_size.width}) than its box ({widget.size.width})")
        elif type(widget) is Static and widget.size.height == 1 and widget.styles.height is not None \
                and not widget.styles.height.is_auto:
            text = str(widget.render())
            if len(text) > room and widget.id not in ("jobline",):
                found.append(f"the label {text!r} is cut: {room} cells")
    footers = [widget for widget in drawn if isinstance(widget, Footer)]
    if not footers:
        if not getattr(screen, "is_modal", False):
            found.append("no footer")
        return found
    footer = footers[0]
    line = T.screen_text(app).splitlines()[-1]            # the footer is the window's last line
    if footer.region.bottom != whole.bottom:
        found.append(f"the footer is not the last line: {footer.region}")
    keys = [key for key in footer.query(FooterKey) if key.display]
    if not keys:
        found.append("the footer shows no key")
    for key in keys:
        pair = f"{key.key_display} {key.description}"
        if pair not in line:
            found.append(f"the footer does not show {pair!r} whole: {line!r}")
        if key.region.right > footer.region.right:
            found.append(f"the footer's {pair!r} is cut at the right edge")
    if "f1 All keys" not in line:
        found.append(f"the footer does not end in the way to every key: {line!r}")
    return found


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_every_view_is_laid_out_cleanly(tmp_path, size):
    ws = T.library(tmp_path / ("a long folder name for the library " * 2).strip() / "lib",
                   ZOLL90.replace("{27}", "{28}"), KAHA12, GLOC08, TENE11, library_entry("Game62"))
    T.seed_responses(ws, T.COMPLETION, T.TUI_SEARCH)
    faults = {}

    async def journey():
        async with T.opened(ws, size=size) as pilot:
            app = pilot.app

            def look(where):
                found = problems(app)
                if found:
                    faults[where] = found
            assert len(T.screen_text(app).splitlines()[0]) <= size[0] and "…/" in T.screen_text(app).splitlines()[0]
            look("library")
            await T.press(pilot, "slash")
            look("library, searching")
            await T.press(pilot, "escape", "d", "d")
            look("library, evidence")
            await T.press(pilot, "f3", "t")
            look("review")
            await T.press(pilot, "f4")
            await T.type_text(pilot, "Backward learning in paired associates")
            await T.press(pilot, "enter")
            look("add, search")
            await T.press(pilot, "enter")
            look("proposal")
            await T.press(pilot, "e")
            look("proposal editor")
            await T.press(pilot, "escape")
            await T.press(pilot, "q")
            for number, name in enumerate(("identifier", "pdf", "manual"), 1):
                await T.press(pilot, "f4", "escape", *["right"] * (number if number == 1 else 1), "enter")
                look(f"add, {name}")
            await T.press(pilot, "f5")
            look("check")
            await T.press(pilot, "m")
            look("check, with a result")
            await T.press(pilot, "f6")
            look("send")
            await T.press(pilot, "s")
            look("send, the question")
            await T.press(pilot, "n")
            await T.press(pilot, "f7")
            look("library state")
            await T.press(pilot, "f8")
            look("setup")
            await T.press(pilot, "b")
            look("setup, with a result")
            await T.press(pilot, "f1")
            look("help")
            await T.press(pilot, "escape", "f2", "e")
            look("editor")
            await T.press(pilot, "ctrl+p")
            look("editor, previewed")
            await T.press(pilot, "f3")                                       # a notice: a line of its own, over nothing
            assert "Close this first (esc)" in T.shown(app, "#dialog-notice")
            look("editor, with a notice")
            await T.press(pilot, "escape", "ctrl+t")
            look("library, light")
            # what changed while another view was in front is laid out for the window when its view comes back
            await T.press(pilot, "d", "d", "f4", "escape", "right", "enter")
            await T.type_text(pilot, "10.1037/h0041332")
            await T.press(pilot, "enter")
            await T.press(pilot, "s")                                        # the proposal closes; the library is read again
            app.refresh_library(force=True)
            await T.settle(pilot)
            await T.press(pilot, "escape")
            await T.press(pilot, "1")
            look("library, after a change made from another view")
            evidence = str(app.screen.query_one("#library-detail #t-evidence").render())
            assert "Closest source" in evidence or "Source record" in evidence or "Lookups made" in evidence
    T.run(journey())
    assert not faults, "\n".join(f"{where}: {fault}" for where, found in faults.items() for fault in found)
