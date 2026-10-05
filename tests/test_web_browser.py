"""The web interface in a real browser (Playwright, chromium) against the real server and
core: the journeys a person makes, with the library's files examined afterwards.

Skipped, by name, when Playwright or its chromium is not installed. Every journey collects
the browser's console errors and page errors (a Content-Security-Policy violation is one)
and fails on any.
"""
import importlib.util
import re

import pytest

import conftest
import intake_pdfs as pdfs
import web_support as web
from cdlbib import theme
from cdlbib.verification import load_entries

from test_web_flows import GAME62, KAHA12, TENE11, ZOLL90

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    pytest.skip("Playwright is not installed (pip install playwright; python -m playwright install chromium)",
                allow_module_level=True)


@pytest.fixture(autouse=True, scope="module")
def real_data_folder_untouched():
    yield
    conftest.no_real_library_touched()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as play:
        try:
            found = play.chromium.launch()
        except Exception as exc:
            pytest.skip("Playwright's chromium is not installed (python -m playwright install chromium): "
                        + str(exc).splitlines()[0])
        yield found
        found.close()


class Visit:
    def __init__(self, browser, running, ws, **context):
        self.running, self.ws, self.problems = running, ws, []
        self.context = browser.new_context(**{"viewport": {"width": 1180, "height": 760}, **context})
        self.page = self.context.new_page()
        self.page.on("console", lambda message: self.problems.append(f"console {message.type}: {message.text}")
                     if message.type in ("error", "warning") else None)
        self.page.on("pageerror", lambda error: self.problems.append(f"page error: {error}"))
        self.page.on("requestfailed", lambda request: self.problems.append(f"request failed: {request.url}"))
        self.requests = []
        self.page.on("request", lambda request: self.requests.append(request.url))

    def open(self):
        self.page.goto(self.running.url)
        self.page.wait_for_selector(".vt-row", timeout=180_000)
        return self.page

    def nav(self, name):
        self.page.click(f"#nav >> [data-view={name}]")


@pytest.fixture
def visit(browser, tmp_path, monkeypatch):
    web.isolate(monkeypatch, tmp_path / "env")
    ws = web.make_library(tmp_path / "library", KAHA12, GAME62, TENE11)
    web.seed(ws, "pdf_lookups.json.gz", completion=True, verify=("Game62",))
    running, _ = web.start(ws)
    found = Visit(browser, running, ws)
    yield found
    found.context.close()
    running.stop()
    assert found.problems == [], found.problems                 # no console error, page error or CSP violation
    assert all(url.startswith(running.origin + "/") or url.startswith(("blob:", "data:")) for url in found.requests)
    assert running.app.worker.overlaps == 0


def keys(ws):
    return list(load_entries(ws.bib))


# --- arriving -----------------------------------------------------------------------------------

def test_the_token_arrives_in_the_fragment_and_leaves_the_address_bar(visit):
    page = visit.open()
    token = visit.running.app.token
    assert token not in page.url and page.url == visit.running.origin + "/#/library"
    assert not [url for url in visit.requests if token in url]                 # it never travels in an address
    expect(page.locator("#library-path")).to_contain_text("library")
    expect(page.locator("#identity")).to_have_text("GitHub: not checked")      # nobody was asked who is logged in
    expect(page.locator("#match-count")).to_have_text("3 entries")
    assert page.evaluate("() => window.history.length") >= 1
    assert token not in page.content()
    page.reload()                                                              # the key is not kept: the page says so
    expect(page.locator("main h1")).to_have_text("This page needs its key")
    assert page.locator(".vt-row").count() == 0
    other = visit.context.new_page()                                           # the bare address serves no data either
    other.goto(visit.running.origin + "/")
    expect(other.locator("main h1")).to_have_text("This page needs its key")


# --- browse and search --------------------------------------------------------------------------

def test_browse_search_and_open_an_entry_with_mouse_and_keyboard(visit):
    page = visit.open()
    expect(page.locator(".vt-row")).to_have_count(3)
    page.fill("#search", "games factorial")
    expect(page.locator(".vt-row")).to_have_count(1)
    expect(page.locator("#match-count")).to_have_text("1 of 3 entries")
    page.click(".vt-row")
    expect(page.locator(".detail-head h2")).to_have_text("Game62")
    expect(page.locator(".detail-head .st")).to_have_text("metadata verified")
    expect(page.locator("[role=tabpanel]:visible pre")).to_have_text(GAME62)
    page.click("role=tab[name=/Evidence/]")
    expect(page.locator("[role=tabpanel]:visible")).to_contain_text("Source records compared (1)")
    page.click("[role=tabpanel]:visible details.card summary")
    expect(page.locator("[role=tabpanel]:visible details.card table")).to_contain_text("Journal of Experimental Psychology")
    page.fill("#search", "")
    expect(page.locator(".vt-row")).to_have_count(3)
    expect(page.locator(".vt-row[aria-selected=true] .c-key")).to_have_text("Game62")      # the selection is kept
    # the keyboard alone: the list is one tab stop, the arrows move through it
    page.focus(".vt-scroll")
    page.keyboard.press("ArrowDown")
    expect(page.locator(".detail-head h2")).to_have_text("TeneEtal11")
    page.keyboard.press("Home")
    expect(page.locator(".detail-head h2")).to_have_text("Kaha12")
    expect(page.locator(".vt-scroll")).to_have_attribute("aria-activedescendant", "row-0")
    page.click(".counts >> text=/metadata verified 1/")
    expect(page.locator(".vt-row")).to_have_count(1)
    expect(page.locator(".counts button[aria-pressed=true]")).to_have_text("metadata verified 1")
    page.fill("#search", "status:nonsense")
    expect(page.locator("#match-count")).to_have_text("0 of 3 entries")


def test_the_table_stays_responsive_with_the_whole_frozen_library(browser, tmp_path, monkeypatch):
    web.isolate(monkeypatch, tmp_path / "env")
    ws = web.make_library(tmp_path / "library", text=conftest.FROZEN_LIBRARY.read_text(encoding="utf-8"))
    total = len(load_entries(ws.bib))
    assert total > 6400
    running, _ = web.start(ws)
    found = Visit(browser, running, ws)
    try:
        page = found.open()
        expect(page.locator("#match-count")).to_have_text(f"{total} entries")
        assert page.locator(".vt-row").count() < 80                             # only the rows in view are in the page
        page.focus(".vt-scroll")
        import time
        started = time.monotonic()
        page.keyboard.press("End")
        expect(page.locator(".vt-row[aria-selected=true] .c-key")).to_have_text(list(load_entries(ws.bib))[-1])
        page.keyboard.press("Home")
        for _ in range(30):
            page.keyboard.press("PageDown")
        expect(page.locator(".vt-scroll")).to_have_attribute("aria-activedescendant", re.compile(r"row-\d+"))
        page.mouse.move(400, 500)
        for _ in range(40):
            page.mouse.wheel(0, 4000)
        page.fill("#search", "memory")
        expect(page.locator("#match-count")).to_have_text(re.compile(r"^\d{3,4} of " + str(total) + " entries$"))
        page.fill("#search", "author:kahana memory")
        expect(page.locator("#match-count")).to_have_text(re.compile(r"^\d{1,3} of " + str(total) + " entries$"))
        assert page.locator(".vt-row").count() < 80
        assert time.monotonic() - started < 30                                  # all of the above, with 6,400 entries
    finally:
        found.context.close()
        running.stop()
    assert found.problems == [], found.problems


# --- edit ---------------------------------------------------------------------------------------

def test_edit_preview_save(visit):
    page = visit.open()
    page.fill("#search", "key:Kaha12")
    page.click(".vt-row")
    page.click("button:has-text('Edit')")
    expect(page.locator("#entry-text")).to_have_value(KAHA12)
    save = page.locator("button:has-text('Save')")
    expect(save).to_be_disabled()                                              # nothing is saved without a preview
    edited = KAHA12.replace("{2012}", "{2013}")
    page.fill("#entry-text", edited)
    page.click("button:has-text('Preview')")
    expect(page.locator(".diff .add")).to_have_text("+\tYear = {2013}}")
    expect(page.locator(".diff .del")).to_have_text("-\tYear = {2012}}")
    expect(save).to_be_enabled()
    page.fill("#entry-text", edited + " ")                                     # editing again makes the preview stale
    expect(save).to_be_disabled()
    assert visit.ws.bib.read_text(encoding="utf-8").count("{2012}") == 1
    page.fill("#entry-text", edited)
    page.click("button:has-text('Preview')")
    expect(save).to_be_enabled()
    save.click()
    expect(page.locator(".detail-head h2")).to_have_text("Kaha12")            # back in the library, on the entry
    expect(page.locator(".alert.info")).to_contain_text("Saved Kaha12.")
    assert edited in visit.ws.bib.read_text(encoding="utf-8") and "{2012}" not in visit.ws.bib.read_text(encoding="utf-8")
    expect(page.locator("[role=tabpanel]:visible pre")).to_have_text(edited)


def test_leaving_an_edit_asks_first(visit):
    page = visit.open()
    page.click("button:has-text('New entry')")
    page.fill("#entry-text", ZOLL90)
    visit.nav("check")
    expect(page.locator("dialog[open] h2")).to_have_text("Leave without saving?")
    page.click("dialog >> text=Cancel")
    expect(page.locator("#entry-text")).to_have_value(ZOLL90)                  # still there
    page.click("button:has-text('Preview')")
    expect(page.locator("section[aria-label=Preview]")).to_contain_text("Zoll90")
    page.click("button:has-text('Save')")
    expect(page.locator(".alert.info")).to_contain_text("Saved Zoll90.")
    assert keys(visit.ws) == ["Kaha12", "Game62", "TeneEtal11", "Zoll90"]


# --- add ----------------------------------------------------------------------------------------

def test_add_by_identifier(visit):
    page = visit.open()
    visit.nav("add")
    page.click("role=tab[name='Identifiers']")
    page.fill("#add-identifiers", pdfs.ZOLLER_DOI)
    page.click("button:has-text('Look up')")
    card = page.locator("article.card")
    expect(card).to_have_count(1, timeout=120_000)
    expect(card.locator("h3").first).to_have_text("Entry: Zoll90")
    expect(card).to_contain_text("Verification: metadata verified")
    expect(card.locator("pre").nth(1)).to_have_text(ZOLL90)
    assert keys(visit.ws) == ["Kaha12", "Game62", "TeneEtal11"]                 # a proposal has written nothing
    card.locator("[data-action=edit]").click()
    card.locator("textarea").fill(ZOLL90.replace("1053--1065", "1053--1066"))
    card.locator("[data-action=recheck]").click()
    expect(card.locator("pre").nth(1)).to_contain_text("1053--1066", timeout=120_000)
    expect(card).to_contain_text("user edit")
    card.locator("[data-action=edit]").click()
    card.locator("textarea").fill(ZOLL90)
    card.locator("[data-action=recheck]").click()
    expect(card.locator("pre").nth(1)).to_have_text(ZOLL90, timeout=120_000)
    card.locator("[data-action=accept]").click()
    expect(card).to_contain_text("Added: Zoll90", timeout=120_000)
    assert keys(visit.ws) == ["Kaha12", "Game62", "TeneEtal11", "Zoll90"]
    assert visit.ws.bib.read_text(encoding="utf-8").rstrip().endswith(ZOLL90)
    visit.nav("library")
    expect(page.locator("#match-count")).to_have_text("4 entries")


def test_add_by_pdf_upload(visit, tmp_path):
    if not pdfs.pdflatex():
        pytest.skip("pdflatex is not installed: the test PDF cannot be typeset")
    pdf = pdfs.build("doi", tmp_path / "pdf")
    page = visit.open()
    visit.nav("add")
    page.click("role=tab[name='PDF']")
    page.set_input_files("#add-pdf", str(pdf))
    lookup = page.locator("[data-action=pdf-lookup]")
    expect(lookup).to_be_visible(timeout=120_000)
    expect(page.locator("[role=tabpanel]:visible")).to_contain_text(pdfs.ZOLLER_DOI)
    expect(page.locator("[role=tabpanel]:visible")).to_contain_text("largest text on page 1")
    # the PDF itself in the browser's viewer; a browser without one (headless chromium) is shown its
    # first page drawn by the server, which needs the pdf extra
    if page.locator("iframe.pdf-frame").count():
        assert page.locator("iframe.pdf-frame").get_attribute("src").startswith("blob:")
    elif importlib.util.find_spec("pypdfium2"):
        expect(page.locator("img.pdf-image")).to_be_visible(timeout=60_000)
        assert page.locator("img.pdf-image").get_attribute("src").startswith("data:image/png;base64,")
    expect(page.locator("button[data-route=dartmouth]")).to_be_visible()
    expect(page.locator("button[data-route=openai]")).to_be_visible()
    expect(page.locator("[role=tabpanel]:visible")).to_contain_text("Create an API key in Dartmouth Chat")
    lookup.click()
    card = page.locator("article.card")
    expect(card).to_have_count(1, timeout=120_000)
    expect(card).to_contain_text("Found by the doi read from the PDF (page 1)")
    card.locator("[data-action=accept]").click()
    expect(card).to_contain_text("Added: Zoll90", timeout=120_000)
    assert keys(visit.ws)[-1] == "Zoll90"
    # the manual form starts from what was read
    page.click("role=tab[name='PDF']")
    page.click("button:has-text('Type it in by hand')")
    expect(page.locator("input[data-field=doi]")).to_have_value(pdfs.ZOLLER_DOI, timeout=60_000)
    expect(page.locator("input[data-field=title]")).to_have_value(re.compile("^Students"))


# --- review -------------------------------------------------------------------------------------

def test_the_review_queue_and_the_approval_dialog(visit):
    page = visit.open()
    visit.nav("review")
    page.click("button:has-text('All entries')")
    items = page.locator(".queue button.item")
    expect(items).to_have_count(2)
    items.first.click()
    expect(page.locator(".detail-head h2")).to_have_text("Kaha12")
    page.click("button:has-text('Approve')")
    dialog = page.locator("dialog[open]")
    expect(dialog.locator("h2")).to_have_text("Record a human approval of Kaha12")
    expect(dialog).to_contain_text("GitHub login of this computer")
    expect(dialog.locator("input[name=reviewer], input[name=login]")).to_have_count(0)     # no field names a reviewer
    dialog.locator("button:has-text('Record the approval')").click()          # nothing typed: nothing is sent
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("dialog[open]")).to_have_count(0)
    page.click("button:has-text('Approve')")
    page.click("dialog >> text=Cancel")
    expect(page.locator("dialog[open]")).to_have_count(0)
    expect(page.locator(".detail-head .st")).to_have_text("pending")
    from cdlbib import api
    assert api.entry(visit.ws, "Kaha12").status == "pending" and api.entry(visit.ws, "Kaha12").human_review is None


# --- appearance ---------------------------------------------------------------------------------

def _rgb(colour):
    return "rgb({}, {}, {})".format(*(int(colour[i:i + 2], 16) for i in (1, 3, 5)))


def test_the_theme_toggle_and_the_palette(visit):
    page = visit.open()
    toggle = page.locator("#theme-toggle")
    expect(toggle).to_have_text("Theme: system")
    expect(page.locator("body")).to_have_css("background-color", _rgb(theme.LIGHT["background"]))     # the context is light
    expect(page.locator("header.top")).to_have_css("background-color", _rgb(theme.GREEN))
    toggle.click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    toggle.click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(toggle).to_have_text("Theme: dark")
    expect(page.locator("body")).to_have_css("background-color", _rgb(theme.DARK["background"]))
    expect(page.locator("body")).to_have_css("color", _rgb(theme.DARK["text"]))
    expect(page.locator(".vt")).to_have_css("background-color", _rgb(theme.DARK["surface"]))
    page.keyboard.press("Shift+Tab")                                           # by keyboard: a visible focus mark
    expect(page.locator(":focus")).to_have_css("outline-style", "solid")
    expect(page.locator(":focus")).to_have_attribute("id", "identity-check")
    toggle.click()
    expect(toggle).to_have_text("Theme: system")
    assert page.locator("html").get_attribute("data-theme") is None


def test_the_system_dark_scheme_is_followed(browser, visit):
    dark = Visit(browser, visit.running, visit.ws, color_scheme="dark")
    try:
        page = dark.open()
        expect(page.locator("body")).to_have_css("background-color", _rgb(theme.DARK["background"]))
        page.click("#theme-toggle")                                            # light, against the system
        expect(page.locator("body")).to_have_css("background-color", _rgb(theme.LIGHT["background"]))
    finally:
        dark.context.close()
    assert dark.problems == [], dark.problems


def test_a_narrow_window_keeps_every_view_usable(browser, visit):
    narrow = Visit(browser, visit.running, visit.ws, viewport={"width": 390, "height": 760})
    try:
        page = narrow.open()
        for name in ("library", "check", "review", "add", "send", "state", "setup"):
            narrow.nav(name)
            expect(page.locator("#nav [aria-current=page]")).to_have_attribute("data-view", name)
            page.wait_for_timeout(300)
            width = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            assert width[0] <= width[1], (name, width)                          # no sideways scrolling of the page
        narrow.nav("library")
        expect(page.locator(".vt-row").first).to_be_visible()
        expect(page.locator(".vt-row .c-authors").first).to_be_hidden()         # fewer columns, the same rows
        expect(page.locator(".vt-row .c-title").first).to_be_visible()
        page.click(".vt-row")
        expect(page.locator(".detail-head h2")).to_be_visible()
        page.click("button:has-text('Approve')")
        box = page.locator("dialog[open]").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390
        page.keyboard.press("Escape")
    finally:
        narrow.context.close()
    assert narrow.problems == [], narrow.problems


def test_every_view_opens_and_controls_have_names(visit):
    page = visit.open()
    for name, heading in (("check", "Check"), ("review", "Review queue"), ("add", "Add references"), ("send", "Send"),
                          ("state", "Library state"), ("setup", "Setup"), ("library", None)):
        visit.nav(name)
        if heading:
            expect(page.locator("main h1")).to_have_text(heading)
        page.wait_for_timeout(300)
        unnamed = page.evaluate("""() => [...document.querySelectorAll('button, input, select, textarea')].filter((el) => {
            if (el.closest('[hidden]')) return false;
            const label = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.textContent.trim()
              || (el.closest('label') ? el.closest('label').textContent.trim() : '') || el.getAttribute('title');
            return !label;
        }).map((el) => el.outerHTML.slice(0, 120))""")
        assert unnamed == [], (name, unnamed)
    visit.nav("setup")
    expect(page.locator("main")).to_contain_text("cdlbib export PAPER --bbl")              # the .bbl is made in a terminal
    expect(page.locator("main")).to_contain_text("not checked")
    visit.nav("state")
    expect(page.locator("main")).to_contain_text("is not a git checkout of its own")
    expect(page.locator("#alerts .alert:not(.info)")).to_have_count(1)        # the review queue's "changed entries" needs GitHub
    expect(page.locator("#alerts")).to_have_attribute("role", "alert")
