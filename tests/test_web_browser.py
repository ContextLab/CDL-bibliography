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


INK = """(img) => {
    const canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
    const context = canvas.getContext('2d');
    context.drawImage(img, 0, 0);
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let dark = 0, light = 0, top = 0;
    for (let i = 0; i < data.length; i += 4) {
        const grey = (data[i] + data[i + 1] + data[i + 2]) / 3;
        if (grey < 100) { dark += 1; if (i / 4 < canvas.width * canvas.height / 2) top += 1; }
        if (grey > 240) light += 1;
    }
    return {width: canvas.width, height: canvas.height, dark, light, top, shown: img.getBoundingClientRect().width};
}"""


def test_add_by_pdf_upload(visit, tmp_path):
    if not pdfs.pdflatex():
        pytest.skip("pdflatex is not installed: the test PDF cannot be typeset")
    if not importlib.util.find_spec("pypdfium2"):
        pytest.skip("the pdf extra (pypdfium2) is not installed: no page is drawn, so nothing rendered can be examined")
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
        assert page.locator("iframe.pdf-frame").first.get_attribute("src").startswith("blob:")
        page.click("button:has-text('Show the first page as an image')")          # what a viewer shows cannot be read from here
    image = page.locator("[role=tabpanel]:visible img.pdf-image")
    expect(image).to_be_visible(timeout=60_000)
    # what is drawn is the page: a white sheet with a real amount of ink, most of it in the upper
    # half (the title and the abstract), at the size the server renders
    ink = image.evaluate(INK)
    assert ink["width"] == 800 and 1000 <= ink["height"] <= 1100 and ink["shown"] > 200
    pixels = ink["width"] * ink["height"]
    assert 0.005 * pixels < ink["dark"] < 0.2 * pixels and ink["light"] > 0.7 * pixels and ink["top"] > 0.5 * ink["dark"]
    import base64
    from cdlbib import api
    assert base64.b64decode(image.get_attribute("src").split(",", 1)[1]) == api.render_first_page(pdf)
    expect(page.locator("button[data-route=dartmouth]")).to_be_visible()
    expect(page.locator("button[data-route=openai]")).to_be_visible()
    expect(page.locator("[role=tabpanel]:visible")).to_contain_text("Create an API key in Dartmouth Chat")
    lookup.click()
    card = page.locator("article.card")
    expect(card).to_have_count(1, timeout=120_000)
    expect(card).to_contain_text("Found by the doi read from the PDF (page 1)")
    # the proposed entry lies beside the PDF's first page
    beside = page.locator(".beside")
    side = beside.locator("img.pdf-image")
    expect(side).to_be_visible(timeout=60_000)
    assert side.evaluate(INK)["dark"] == ink["dark"]
    left, right = beside.locator(".pdf-view").bounding_box(), card.bounding_box()
    assert left["x"] + left["width"] <= right["x"] and abs(left["y"] - right["y"]) < 40
    page.set_viewport_size({"width": 600, "height": 760})                      # narrow: one above the other
    left, right = beside.locator(".pdf-view").bounding_box(), card.bounding_box()
    assert left["y"] + left["height"] <= right["y"] + 1 and abs(left["x"] - right["x"]) < 4
    page.set_viewport_size({"width": 1180, "height": 760})
    card.locator("[data-action=edit]").click()                                 # ... and stays there after a recheck
    card.locator("textarea").fill(ZOLL90.replace("1053--1065", "1053--1066"))
    card.locator("[data-action=recheck]").click()
    expect(card.locator("pre").nth(1)).to_contain_text("1053--1066", timeout=120_000)
    expect(beside.locator("img.pdf-image")).to_be_visible()
    card.locator("[data-action=edit]").click()
    card.locator("textarea").fill(ZOLL90)
    card.locator("[data-action=recheck]").click()
    expect(card.locator("pre").nth(1)).to_have_text(ZOLL90, timeout=120_000)
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


def test_no_view_shows_a_missing_value_as_text(visit):
    """Every view and every tab of it as first drawn, and an entry's three tabs: nowhere is a
    missing value written out as the word null or undefined."""
    page = visit.open()

    def look(where):
        page.wait_for_timeout(400)
        shown = page.locator("body").inner_text()
        assert not re.search(r"\b(null|undefined|NaN)\b|\[object ", shown), (where, re.findall(r".{0,60}\b(?:null|undefined|NaN)\b.{0,40}|.{0,40}\[object .{0,40}", shown))

    for name in ("library", "check", "review", "add", "send", "state", "setup"):
        visit.nav(name)
        look(name)
        for index in range(page.locator("main [role=tab]").count()):
            page.locator("main [role=tab]").nth(index).click()
            look(f"{name}, tab {index}")
    page.click("#alerts .alert button")                 # the review queue's "changed entries" needs GitHub
    visit.nav("review")
    page.click("button:has-text('All entries')")
    page.locator(".queue button.item").first.click()
    look("review, an entry")
    visit.nav("library")
    for key in ("Game62", "Kaha12"):
        page.fill("#search", "key:" + key)
        expect(page.locator(".vt-row .c-key")).to_have_text([key])
        page.click(".vt-row")
        expect(page.locator(".detail-head h2")).to_have_text(key)
        for index in range(3):
            page.locator(".detail [role=tab]").nth(index).click()
            look(f"{key}, tab {index}")
        page.click("[role=tabpanel]:visible details >> nth=0") if page.locator("[role=tabpanel]:visible details").count() else None
        look(f"{key}, a source record opened")
    page.click("button:has-text('Edit')")
    page.click("button:has-text('Preview')")
    look("edit preview")


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


# --- setup, export, the managed library ---------------------------------------------------------

def test_export_upload_then_download(visit, tmp_path):
    aux = tmp_path / "paper.aux"
    aux.write_text("\\relax\n\\citation{Game62}\n\\citation{Kaha12}\n\\bibstyle{plain}\n\\bibdata{cdl}\n", encoding="utf-8")
    page = visit.open()
    visit.nav("setup")
    expect(page.locator("main table").first).to_contain_text("gh login")
    page.set_input_files("#export-files", str(aux))
    expect(page.locator("#export-main option")).to_have_text(["paper.aux"])
    page.click("button:has-text('Make the .bib')")
    button = page.locator("[data-action=download]")
    expect(button).to_have_text("Download cdl.bib", timeout=120_000)
    expect(page.locator("main")).to_contain_text("citations read from the .aux file: 2 keys")
    with page.expect_download() as caught:
        button.click()
    saved = tmp_path / "downloaded.bib"
    caught.value.save_as(str(saved))
    assert caught.value.suggested_filename == "cdl.bib"
    assert saved.read_text(encoding="utf-8").strip() == KAHA12 + "\n\n" + GAME62          # the library's order, its exact text
    assert keys(visit.ws) == ["Kaha12", "Game62", "TeneEtal11"]


from test_web_flows import managed  # noqa: E402,F401 - the managed library with an unsent edit and a newer upstream


def test_update_with_unsent_changes_asks_in_the_page(browser, managed):  # noqa: F811
    site, upstream = managed
    found = Visit(browser, site.running, site.ws)
    try:
        page = found.open()
        edited = site.ws.bib.read_text(encoding="utf-8")
        found.nav("state")
        expect(page.locator("main")).to_contain_text("this is the copy cdlbib downloads and manages")
        page.click("button:has-text('Ask the upstream now')")
        expect(page.locator(".banner")).to_contain_text("A newer version of the bibliography is available: 1 new commit, 1 new entry.")
        page.click("button:has-text('Update now')")
        dialog = page.locator("dialog[open]")
        expect(dialog).to_contain_text("you have changes that have not been sent")
        expect(dialog.locator(".choices button")).to_have_text([
            "Keep working without updating (ask again tomorrow)", "Update and keep my changes",
            "Send my changes first (runs `cdlbib send`)",
            "Discard my changes and update (they are saved first; `cdlbib update --undo` brings them back)", "Cancel"])
        assert site.ws.bib.read_text(encoding="utf-8") == edited                # asking changed nothing
        dialog.locator("button:has-text('Cancel')").click()
        expect(page.locator(".alert.info")).to_contain_text("Nothing was changed.")
        assert site.ws.bib.read_text(encoding="utf-8") == edited
        page.click("button:has-text('Update now')")
        page.locator("dialog[open] button:has-text('Update and keep my changes')").click()
        expect(page.locator("main")).to_contain_text("1 backup of", timeout=120_000)
        assert set(keys(site.ws)) == {"TeneEtal11", "Zoll90", "Kaha12"}
        page.click("button:has-text('Undo the last change')")
        page.locator("dialog[open] button:has-text('Restore')").click()
        expect(page.locator("main")).to_contain_text("2 backups of", timeout=120_000)
        assert site.ws.bib.read_text(encoding="utf-8") == edited
    finally:
        found.context.close()
    assert found.problems == [], found.problems


# --- found by the review of 2026-10-05 ----------------------------------------------------------

def test_approve_and_withdraw_for_real_in_the_page(browser, tmp_path, monkeypatch):
    from cdlbib import api, identity
    from cdlbib.errors import IdentityUnavailable
    try:
        me = identity.current()
    except IdentityUnavailable as exc:
        pytest.skip(f"no GitHub login for a real approval: {exc}")
    web.isolate(monkeypatch, tmp_path / "env", home=False)          # gh's login is under the real HOME
    ws = web.make_library(tmp_path / "library", KAHA12, GAME62, TENE11)
    running, _ = web.start(ws)
    found = Visit(browser, running, ws)
    try:
        page = found.open()
        page.click("#identity-check")
        expect(page.locator("#identity")).to_have_text("GitHub: " + me.handle, timeout=60_000)
        page.fill("#search", "key:Kaha12")
        page.click(".vt-row")
        page.click("button:has-text('Approve')")
        dialog = page.locator("dialog[open]")
        expect(dialog).to_contain_text("recorded under the GitHub login of this computer: " + me.handle)
        dialog.locator("input[name=source]").fill("the book itself")
        dialog.locator("textarea[name=note]").fill("title page checked")
        dialog.locator("button:has-text('Record the approval')").click()
        expect(page.locator(".detail-head .st")).to_have_text("human verified", timeout=60_000)
        expect(page.locator(".detail")).to_contain_text("Approved by " + me.handle)
        approved = api.entry(ws, "Kaha12")                                     # the database, not the page
        assert approved.status == "human_verified" and approved.human_review["reviewer"] == me.handle
        assert approved.human_review["github_id"] == me.id and approved.human_review["source"] == "the book itself"
        assert approved.human_review["note"] == "title page checked"
        page.click("role=tab[name=/Evidence/]")
        expect(page.locator("[role=tabpanel]:visible")).to_contain_text("title page checked")
        page.click("button:has-text('Withdraw approval')")
        dialog.locator("textarea[name=reason]").fill("wrong edition")
        dialog.locator("button:has-text('Withdraw the approval')").click()
        expect(page.locator(".detail-head .st")).to_have_text("needs review", timeout=60_000)
        after = api.entry(ws, "Kaha12")
        assert after.status == "needs_review" and after.revoked_approval["reason"] == "wrong edition"
        assert after.revoked_approval["revoked_by"] == me.handle and after.human_review is None
    finally:
        found.context.close()
        running.stop()
    assert found.problems == [], found.problems


def test_text_that_changes_while_a_save_runs_is_not_lost(visit):
    page = visit.open()
    web.wait_idle(visit.running)
    page.fill("#search", "key:Kaha12")
    page.click(".vt-row")
    page.click("button:has-text('Edit')")
    saved = KAHA12.replace("{2012}", "{2013}")
    page.fill("#entry-text", saved)
    page.click("button:has-text('Preview')")
    save = page.locator("button:has-text('Save')")
    expect(save).to_be_enabled()
    held = web.Held(visit.running)                       # the save waits behind this
    try:
        save.click()
        text = page.locator("#entry-text")
        expect(text).to_have_attribute("readonly", "")                          # nothing is typed into a text being saved
        expect(page.locator("button:has-text('Preview')")).to_be_disabled()
        later = saved.replace("{2013}", "{2014}")
        text.evaluate("(el, value) => { el.value = value; }", later)           # and if the text changes all the same ...
    finally:
        held.done()
    expect(page.locator("section[aria-label=Preview]")).to_contain_text("differs from what was saved and is not saved", timeout=60_000)
    expect(page.locator("main h1")).to_have_text("Edit Kaha12")                 # ... the editor stays, with it
    expect(text).to_have_value(later)
    expect(text).not_to_have_attribute("readonly", "")
    expect(save).to_be_disabled()
    assert saved in visit.ws.bib.read_text(encoding="utf-8") and "{2014}" not in visit.ws.bib.read_text(encoding="utf-8")
    visit.nav("library")                                                        # still unsaved: leaving asks
    expect(page.locator("dialog[open] h2")).to_have_text("Leave without saving?")
    page.click("dialog >> text=Cancel")
    page.click("button:has-text('Preview')")
    expect(save).to_be_enabled()
    save.click()
    expect(page.locator(".detail-head h2")).to_have_text("Kaha12")
    assert later in visit.ws.bib.read_text(encoding="utf-8")


def test_typed_text_survives_tabs_and_is_discarded_only_on_purpose(visit):
    page = visit.open()
    visit.nav("add")
    page.click("role=tab[name='Manual']")
    title = page.locator("input[data-field=title]")
    title.fill("A hand-typed title")
    page.locator("input[data-field=author]").fill("A Person")
    page.select_option("#manual-type", "book")
    page.click("role=tab[name='Search']")
    page.fill("#add-title", "something to search for")
    page.click("role=tab[name='Identifiers']")
    page.click("role=tab[name='Manual']")
    expect(title).to_have_value("A hand-typed title")                           # the form was not rebuilt
    expect(page.locator("#manual-type")).to_have_value("book")
    page.click("role=tab[name='Search']")
    expect(page.locator("#add-title")).to_have_value("something to search for")
    visit.nav("library")                                                        # leaving the view asks
    dialog = page.locator("dialog[open]")
    expect(dialog.locator("h2")).to_have_text("Leave without saving?")
    page.keyboard.press("Escape")
    expect(page.locator("main h1")).to_have_text("Add references")
    page.click("role=tab[name='Manual']")
    expect(title).to_have_value("A hand-typed title")
    page.click("[data-action=manual-discard]")                                  # discarding is a decision of its own
    expect(dialog.locator("h2")).to_have_text("Discard what you typed?")
    page.click("dialog >> text=Cancel")
    expect(title).to_have_value("A hand-typed title")
    page.click("[data-action=manual-discard]")
    dialog.locator("button:has-text('Discard')").click()
    expect(page.locator("input[data-field=title]")).to_have_value("")
    visit.nav("library")                                                        # nothing typed any more: no question
    expect(page.locator(".vt-row").first).to_be_visible()
    expect(page.locator("dialog[open]")).to_have_count(0)
    # a dialog that holds typed text is not dismissed by one key
    page.click(".vt-row")
    page.click("button:has-text('Approve')")
    dialog.locator("input[name=source]").fill("the journal's page")
    page.keyboard.press("Escape")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Cancel again to discard it.")
    expect(dialog.locator("input[name=source]")).to_have_value("the journal's page")
    page.click("dialog button:has-text('Cancel')")                              # the second, explicit step
    expect(page.locator("dialog[open]")).to_have_count(0)


def test_one_action_at_a_time_on_a_proposal_and_a_waiting_request_can_be_cancelled(visit):
    page = visit.open()
    visit.nav("add")
    page.click("role=tab[name='Identifiers']")
    page.fill("#add-identifiers", pdfs.ZOLLER_DOI)
    page.click("button:has-text('Look up')")
    card = page.locator("article.card")
    expect(card).to_have_count(1, timeout=120_000)
    first = card.get_attribute("data-proposal")
    card.locator("[data-action=edit]").click()
    card.locator("textarea").fill(ZOLL90.replace("1053--1065", "1053--1066"))
    visit.nav("library")                                                        # an edited proposal is unsaved work too
    expect(page.locator("dialog[open] h2")).to_have_text("Leave without saving?")
    page.click("dialog >> text=Cancel")
    web.wait_idle(visit.running)
    held = web.Held(visit.running)
    try:
        card.locator("[data-action=recheck]").click()
        expect(card).to_have_attribute("aria-busy", "true")
        for action in ("accept", "edit", "skip", "recheck"):                    # nothing else can be decided meanwhile
            expect(card.locator(f"[data-action={action}]")).to_be_disabled()
        expect(card.locator("textarea")).to_be_disabled()
        assert keys(visit.ws) == ["Kaha12", "Game62", "TeneEtal11"]
        expect(page.locator("#activity button")).to_have_text("Cancel what is waiting", timeout=30_000)
    finally:
        held.done()
    expect(card.locator("pre").nth(1)).to_contain_text("1053--1066", timeout=120_000)
    assert card.get_attribute("data-proposal") != first                         # a new version, under a new id
    expect(card.locator("[data-action=skip]")).to_be_enabled()
    held = web.Held(visit.running)
    try:
        card.locator("[data-action=skip]").click()                              # (skipping needs no job: it is done at once)
        expect(card).to_contain_text("Skipped; nothing was changed.")
        visit.nav("check")
        page.click("button:has-text('Format check only')")
        cancel = page.locator("#activity button")
        expect(cancel).to_have_text("Cancel what is waiting", timeout=30_000)
        cancel.click()
        expect(page.locator("#alerts .alert")).to_contain_text("Cancelled before it started; nothing was done.")
    finally:
        held.done()
    web.wait_idle(visit.running)
    assert "POST /api/check/format" not in [label for label, _, _ in visit.running.app.worker.history]


def test_check_and_send_begin_with_the_completion_step_unless_it_is_skipped(visit):
    page = visit.open()
    visit.nav("check")
    page.click("[data-action=check-changed]")
    # the reference cannot be fetched here: the step says so, as the command line does, and the check goes on
    expect(page.locator("main")).to_contain_text("Completion unavailable: Entries could not be selected for completion", timeout=60_000)
    expect(page.locator("#alerts .alert")).to_contain_text("citation check failed", timeout=60_000)
    page.click("#alerts .alert button")
    assert "GET /api/send/due" in [label for label, _, _ in visit.running.app.worker.history]
    visit.nav("send")
    before = len(visit.running.app.worker.history)
    page.check("#send-no-complete")
    page.click("[data-action=send]")
    expect(page.locator("pre.log").last).to_contain_text("completion skipped (--no-complete)")
    expect(page.locator("main .note.bad")).to_be_visible(timeout=60_000)        # not a checkout: the send's own refusal
    web.wait_idle(visit.running)
    labels = [label for label, _, _ in visit.running.app.worker.history[before:]]
    assert "POST /api/send" in labels and "GET /api/send/due" not in labels
    page.uncheck("#send-no-complete")
    page.click("[data-action=send]")
    expect(page.locator("main")).to_contain_text("Completion unavailable:", timeout=60_000)
    web.wait_idle(visit.running)
    labels = [label for label, _, _ in visit.running.app.worker.history[before:]]
    assert labels.index("GET /api/send/due") < len(labels) - 1 - labels[::-1].index("POST /api/send")
    assert keys(visit.ws) == ["Kaha12", "Game62", "TeneEtal11"]


def test_the_send_and_state_pages_list_an_approval_that_waits_when_no_file_has_changed(visit):
    """The library is a real checkout with nothing changed, and one human approval recorded
    under a GitHub login in its verification database. The Send page lists the approval and
    does not say "nothing has changed"; the Library state page lists it and offers the way to
    Send. Looking adds nothing to verification/approvals.jsonl."""
    import os
    import subprocess
    from cdlbib import verification as v
    ws = visit.ws
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@cdlbib.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@cdlbib.invalid")
    for args in (("init", "--quiet"), ("symbolic-ref", "HEAD", "refs/heads/master"), ("add", "cdl.bib"),
                 ("commit", "--quiet", "-m", "start")):
        subprocess.run(["git", *args], cwd=ws.root, env=env, capture_output=True, text=True, check=True)
    page = visit.open()
    visit.nav("send")
    expect(page.locator("main dl")).to_contain_text("nothing has changed")
    expect(page.locator("main dl")).not_to_contain_text("Approvals to send")

    cache = v.Cache(str(ws.database), ledger=ws.revocations)
    try:
        v.record_approval(cache, str(ws.bib), "Game62", load_entries(ws.bib)["Game62"]["fingerprint"],
                          {"reviewer": "@octocat", "source": "The printed volume.", "note": "Compared every field.",
                           "github_login": "octocat", "github_id": 583231})
    finally:
        cache.close()
    visit.nav("state")
    expect(page.locator("main")).to_contain_text("Unsent approvals")
    expect(page.locator("main")).to_contain_text("Game62 (@octocat)")
    page.get_by_role("button", name="Go to Send").click()
    expect(page.locator("main h1")).to_have_text("Send")
    expect(page.locator("main dl")).to_contain_text("Approvals to send")
    expect(page.locator("main dl")).to_contain_text("Game62, approved by @octocat")
    expect(page.locator("main dl")).to_contain_text("verification/approvals.jsonl (the send adds the approvals below to it)")
    expect(page.locator("main dl")).not_to_contain_text("nothing has changed")
    assert not ws.approvals.exists()


def test_names_are_chosen_one_by_one_in_the_proposal(browser, tmp_path, monkeypatch):
    from cdlbib.web import routes
    web.isolate(monkeypatch, tmp_path / "env")
    ws, item, raw = web.name_question(tmp_path / "library")
    running, _ = web.start(ws)
    found = Visit(browser, running, ws)
    try:
        page = found.open()
        kept = routes.keep(running.app, item, in_library=True)       # as the send step's completion offer keeps it
        from playwright.sync_api import expect as _expect
        # the card is drawn by the page's own module from the proposal's data
        page.evaluate("""async (data) => {
            const { proposalCard } = await import('/js/proposal.js');
            document.getElementById('main').replaceChildren(proposalCard(data, { verb: 'Completed' }));
        }""", kept)
        card = page.locator("article.card")
        _expect(card.locator("fieldset.names legend")).to_contain_text("author names differ")
        _expect(card.locator("fieldset.names input[type=radio]")).to_have_count(2)      # only the name that differs is asked
        _expect(card.locator("fieldset.names li").first).to_have_text("A Cleeremans")
        card.locator("fieldset.names input[value=source]").check()
        card.locator("[data-action=names]").click()
        _expect(card.locator("pre").nth(1)).to_contain_text("McClelland", timeout=120_000)
        _expect(card.locator("fieldset.names")).to_have_count(0)
        _expect(card).to_contain_text("user edit")
        assert ws.bib.read_text(encoding="utf-8") == raw
        card.locator("[data-action=accept]").click()
        _expect(card).to_contain_text("Completed: CleeMcCl91", timeout=120_000)
        assert "McClelland" in ws.bib.read_text(encoding="utf-8") and "McCleeland" not in ws.bib.read_text(encoding="utf-8")
    finally:
        found.context.close()
        running.stop()
    assert found.problems == [], found.problems


def test_the_whole_review_queue_is_searched_and_paged_and_follows_the_file(browser, tmp_path, monkeypatch):
    from cdlbib import complete
    web.isolate(monkeypatch, tmp_path / "env")
    entries = [complete.render("article", f"Auth{n:03d}", dict(author=f"A Author{n}", title=f"Paper number {n}", journal="Journal of Tests",
                                                              year=str(1900 + n), volume="1", pages="1--2")) for n in range(230)]
    ws = web.make_library(tmp_path / "library", *entries)
    running, _ = web.start(ws)
    found = Visit(browser, running, ws)
    try:
        page = found.open()
        found.nav("review")
        page.click("#alerts .alert button")                     # "changed entries" needs the GitHub master
        page.click("button:has-text('All entries')")
        items = page.locator(".queue button.item")
        expect(page.locator("#review-count")).to_have_text("230 entries are not verified or approved. Showing 1 to 100.")
        expect(items).to_have_count(100)
        page.click("button:has-text('Next 100')")
        expect(items.first).to_contain_text("Auth100")
        page.click("button:has-text('Next 100')")
        expect(page.locator("#review-count")).to_contain_text("Showing 201 to 230.")
        expect(items).to_have_count(30)
        expect(page.locator("button:has-text('Next 100')")).to_be_disabled()
        page.fill("#review-search", "key:Auth229 year:2129")
        expect(items).to_have_count(1)
        expect(page.locator("#review-count")).to_have_text("1 entry is not verified or approved, matching the search.")
        items.first.click()
        expect(page.locator(".detail-head h2")).to_have_text("Auth229")
        expect(page.locator("[role=tabpanel]:visible")).to_contain_text("Paper number 229")
        # another program edits the entry; when the window is looked at again, the queue and the entry are read again
        ws.bib.write_text(ws.bib.read_text(encoding="utf-8").replace("Paper number 229", "Paper number 229 revised"), encoding="utf-8")
        page.evaluate("() => window.dispatchEvent(new Event('focus'))")
        expect(page.locator("[role=tabpanel]:visible")).to_contain_text("Paper number 229 revised", timeout=30_000)
        expect(items.first).to_contain_text("Paper number 229 revised")
    finally:
        found.context.close()
        running.stop()
    assert found.problems == [], found.problems


def test_the_cores_own_sentences_are_shown_for_what_cannot_be_accepted_and_for_the_tex_link(visit):
    from cdlbib import api, prompts
    page = visit.open()
    visit.nav("add")
    page.click("role=tab[name='Identifiers']")
    page.fill("#add-identifiers", "10.1037/h0041332")                           # Game62: in the library already
    page.click("button:has-text('Look up')")
    card = page.locator("article.card")
    expect(card).to_have_count(1, timeout=120_000)
    held = visit.running.app.store.get("proposal", card.get_attribute("data-proposal"))["proposal"]
    reasons = api.why_not_acceptable(held)
    assert reasons
    expect(card.locator(".why-not li")).to_have_text(reasons)
    expect(card.locator("[data-action=accept]")).to_be_disabled()
    visit.nav("setup")
    expect(page.locator(".tex-lines li")).to_have_text(prompts.tex_state_lines(api.setup_report(visit.ws).tex))
    visit.nav("state")
    expect(page.locator("#pending-evidence")).to_have_count(0)                  # nothing is owed


# --- the last review (2026-10-05) ---------------------------------------------------------------

def test_no_decision_is_taken_over_an_edit_that_was_not_checked(visit):
    page = visit.open()
    visit.nav("add")
    page.click("role=tab[name='Identifiers']")
    page.fill("#add-identifiers", pdfs.ZOLLER_DOI + "\narXiv:" + pdfs.ARXIV_ID)
    page.click("button:has-text('Look up')")
    cards = page.locator("article.card")
    expect(cards).to_have_count(2, timeout=120_000)
    card = cards.filter(has_text="Entry: Zoll90")
    card.locator("[data-action=edit]").click()
    card.locator("textarea").fill(ZOLL90.replace("1053--1065", "1053--1066"))
    web.wait_idle(visit.running)
    before = len(visit.running.app.worker.history)
    for action in ("accept", "skip"):                                           # neither acts over the unchecked text
        card.locator(f"[data-action={action}]").click()
        expect(card.locator(".unchecked")).to_contain_text("The editor holds text that has not been checked.")
    assert keys(visit.ws) == ["Kaha12", "Game62", "TeneEtal11"] and len(visit.running.app.worker.history) == before
    expect(card.locator("textarea")).to_have_value(ZOLL90.replace("1053--1065", "1053--1066"))       # and the text is still there
    page.click("[data-action=accept-remaining]")                                # the others are accepted; this card is left out, and says so
    expect(cards.filter(has_text="Accepted with the remaining proposals.")).to_have_count(1, timeout=120_000)
    expect(card.locator(".left-out")).to_contain_text("its editor holds text that has not been checked")
    assert "Zoll90" not in keys(visit.ws) and len(keys(visit.ws)) == 4
    card.locator("[data-action=discard-edit]").click()                          # discarding is the explicit step
    expect(card.locator(".unchecked")).to_have_count(0)
    expect(card.locator("textarea")).to_be_hidden()
    card.locator("[data-action=accept]").click()
    expect(page.locator("section[aria-label=Proposals]")).to_contain_text("Added: Zoll90", timeout=120_000)
    assert visit.ws.bib.read_text(encoding="utf-8").rstrip().endswith(ZOLL90)


def test_an_entry_that_changed_on_disk_after_it_was_opened_is_not_overwritten(visit):
    page = visit.open()
    page.fill("#search", "key:Kaha12")
    page.click(".vt-row")
    page.click("button:has-text('Edit')")
    expect(page.locator("#entry-text")).to_have_value(KAHA12)
    theirs = KAHA12.replace("Oxford University Press", "Oxford Univ. Press")
    visit.ws.bib.write_text(visit.ws.bib.read_text(encoding="utf-8").replace(KAHA12, theirs), encoding="utf-8")     # another program
    mine = KAHA12.replace("{2012}", "{2013}")
    page.fill("#entry-text", mine)
    page.click("button:has-text('Preview')")
    preview = page.locator("section[aria-label=Preview]")
    expect(preview).to_contain_text("The entry changed on disk after you opened it.")
    expect(page.locator("#kept-text")).to_have_text(mine)                       # the text typed is kept, to copy
    expect(page.locator("button:has-text('Save')")).to_be_disabled()
    expect(page.locator("#entry-text")).to_have_value(mine)
    assert theirs in visit.ws.bib.read_text(encoding="utf-8") and "{2013}" not in visit.ws.bib.read_text(encoding="utf-8")
    page.click("[data-action=reload]")
    expect(page.locator("#entry-text")).to_have_value(theirs)
    page.fill("#entry-text", theirs.replace("{2012}", "{2013}"))
    page.click("button:has-text('Preview')")
    page.click("button:has-text('Save')")
    expect(page.locator(".detail-head h2")).to_have_text("Kaha12")
    assert theirs.replace("{2012}", "{2013}") in visit.ws.bib.read_text(encoding="utf-8")


def test_the_daily_check_is_shown_when_the_page_opens(browser, managed):  # noqa: F811
    """The managed library has an unsent edit and its upstream a newer commit: the daily check
    made at start changed nothing and the page asks, in the core's words."""
    site, upstream = managed
    from test_web_hardening import _make_due
    edited = site.ws.bib.read_text(encoding="utf-8")
    site.running.stop()
    _make_due()
    running, _ = web.start(site.ws)
    found = Visit(browser, running, site.ws)
    try:
        page = found.open()
        dialog = page.locator("dialog[open]")
        expect(dialog).to_contain_text("you have changes that have not been sent", timeout=60_000)
        assert site.ws.bib.read_text(encoding="utf-8") == edited
        dialog.locator("button:has-text('Update and keep my changes')").click()
        expect(page.locator("#match-count")).to_have_text("3 entries", timeout=120_000)
        assert set(keys(site.ws)) == {"TeneEtal11", "Zoll90", "Kaha12"}
        page.reload()
        assert [label for label, _, _ in running.app.worker.history].count("daily update check") == 1
    finally:
        found.context.close()
        running.stop()
    assert found.problems == [], found.problems


# --- every view stays clean -----------------------------------------------------------------------

CLEAN = """() => {
  const bad = [];
  const shown = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const say = (what, el) => bad.push(what + ': ' + (el.textContent || el.tagName).trim().slice(0, 60));
  const root = document.documentElement, main = document.getElementById('main'), top = document.querySelector('header.top');
  if (root.scrollWidth > root.clientWidth) bad.push('the page scrolls sideways');
  if (main.scrollWidth > main.clientWidth + 1) bad.push('the view scrolls sideways');
  const rows = document.querySelector('.vt-scroll');
  if (rows && rows.scrollWidth > rows.clientWidth + 1) bad.push('the list of entries is wider than its box');
  // nothing lies under the header, and a view opens at its top
  if (main.getBoundingClientRect().top < top.getBoundingClientRect().bottom - 1) bad.push('the view starts under the header');
  // controls and chips: one line, and their text inside their box
  for (const el of document.querySelectorAll('button, .tag, .st, th, [role=tab], #identity, .brand')) {
    if (!shown(el)) continue;
    if (el.scrollWidth > el.clientWidth + 1 && !['hidden', 'clip'].includes(getComputedStyle(el).overflowX)) say('text overflows its box', el);
    if (el.matches('.item, .choices button') || !el.matches('button, .tag, .st, [role=tab]')) continue;
    const style = getComputedStyle(el);
    const line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.45;
    const inner = el.getBoundingClientRect().height - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    if (inner > line * 1.6) say('more than one line', el);
  }
  for (const cell of document.querySelectorAll('.vt-row > *, .vt-head > *, .queue .item > div')) {       // one line each, cut with an ellipsis
    if (shown(cell) && cell.scrollHeight > cell.clientHeight + 2) say('a one-line cell holds more than one line', cell);
  }
  for (const cell of document.querySelectorAll('td, dd, dt, .note, .card, .panel, li')) {
    if (cell.closest('.deep')) continue;       // nested data scrolls sideways inside its own box, by design
    if (shown(cell) && cell.scrollWidth > cell.clientWidth + 1 && getComputedStyle(cell).overflowX === 'visible') say('content overflows its box', cell);
  }
  // no rule that breaks inside words
  for (const el of main.querySelectorAll('*')) {
    const style = getComputedStyle(el);
    if (style.overflowWrap === 'anywhere' || style.wordBreak === 'break-all') { say('breaks anywhere', el); break; }
  }
  // no word is split over two lines (identifiers may wrap after / . _ - : =, where the page allows it)
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (!parent || !shown(parent) || parent.closest('textarea, select, script, style, .visually-hidden')) continue;
    for (const found of node.data.matchAll(/[\\p{L}\\p{N}]{2,}/gu)) {
      range.setStart(node, found.index);
      range.setEnd(node, found.index + found[0].length);
      const lines = new Set([...range.getClientRects()].map((rect) => Math.round(rect.top)));
      if (lines.size > 1) { bad.push('a word is broken across lines: ' + found[0] + ' in: ' + node.data.trim().slice(0, 50)); break; }
    }
  }
  // the header: brand, views and login on one row from 1000px up; the views on one line
  const tops = new Set([...document.querySelectorAll('#nav button')].map((el) => Math.round(el.getBoundingClientRect().top)));
  if (window.innerWidth >= 1000) {
    if (tops.size !== 1) bad.push('the views wrap in the header');
    const middles = ['.brand', '#nav', '.who'].map((name) => { const box = document.querySelector(name).getBoundingClientRect(); return box.top + box.height / 2; });
    if (Math.max(...middles) - Math.min(...middles) > 12 || top.getBoundingClientRect().height > 60) bad.push('the header is not one row');
  }
  return bad;
}"""


def _walk(visit, page, pdf):
    """Every view, tab and dialog once; yields a name each time something new is on the screen."""
    yield "library"
    page.fill("#search", "key:Game62")
    expect(page.locator(".vt-row .c-key")).to_have_text(["Game62"])
    page.click(".vt-row")
    expect(page.locator(".detail-head h2")).to_have_text("Game62")
    for index, name in enumerate(("entry", "issues", "evidence")):
        page.locator(".detail [role=tab]").nth(index).click()
        yield "library, " + name
    page.click(".detail [role=tabpanel]:visible details.card summary")
    yield "library, a source record"
    page.click("button:has-text('Approve')")
    yield "the approval dialog"
    page.keyboard.press("Escape")
    page.click("button:has-text('Edit')")
    page.fill("#entry-text", GAME62.replace("Pages = {1--11}", "Pages = {1-11}"))
    page.click("button:has-text('Preview')")
    expect(page.locator(".diff")).to_be_visible()
    yield "edit, previewed"
    page.fill("#entry-text", GAME62)
    visit.nav("check")
    yield "check"
    page.click("button:has-text('Format check only')")
    expect(page.locator("section[aria-label=Result] .note").first).to_be_visible(timeout=60_000)
    yield "check, a result"
    visit.nav("review")
    page.click("#alerts .alert button")
    page.click("button:has-text('All entries')")
    page.locator(".queue button.item").first.click()
    expect(page.locator(".detail-head h2")).to_be_visible()
    yield "review, an entry"
    visit.nav("add")
    yield "add, search"
    page.click("role=tab[name='Identifiers']")
    page.fill("#add-identifiers", pdfs.ZOLLER_DOI)
    page.click("button:has-text('Look up')")
    expect(page.locator("article.card")).to_have_count(1, timeout=120_000)
    yield "add, a proposal"
    page.locator("article.card [data-action=edit]").click()
    yield "add, a proposal's editor"
    page.locator("article.card [data-action=edit]").click()
    if pdf is not None:
        page.click("role=tab[name='PDF']")
        page.set_input_files("#add-pdf", str(pdf))
        expect(page.locator("[data-action=pdf-lookup]")).to_be_visible(timeout=120_000)
        expect(page.locator("button[data-route=openai]")).to_be_visible(timeout=60_000)
        yield "add, a PDF"
        page.click("[data-action=pdf-lookup]")
        expect(page.locator(".beside article.card")).to_have_count(1, timeout=120_000)
        expect(page.locator(".beside img.pdf-image, .beside iframe")).to_have_count(1, timeout=60_000)
        yield "add, a proposal beside its PDF"
    page.click("role=tab[name='Manual']")
    expect(page.locator("input[data-field=title]")).to_be_visible(timeout=60_000)
    yield "add, manual"
    visit.nav("send")
    yield "send"
    visit.nav("state")
    expect(page.locator("main dl.kv").first).to_be_visible()
    yield "library state"
    visit.nav("setup")
    expect(page.locator("main table").first).to_be_visible()
    yield "setup"
    page.click("button:has-text('Remove the link')") if page.locator("button:has-text('Remove the link')").count() else None
    if page.locator("dialog[open]").count():
        yield "setup, a confirmation"
        page.keyboard.press("Escape")


@pytest.mark.parametrize("width,height,scheme", [(1180, 760, "light"), (1440, 900, "light"), (390, 800, "light"),
                                                  (1000, 700, "light"), (1180, 760, "dark")])
def test_every_view_is_clean_at_every_size(browser, visit, tmp_path, width, height, scheme):
    """Each view, tab and dialog: no text broken inside a word, nothing outside its box, buttons
    and chips on one line, no sideways scrolling, one consistent header, nothing under it."""
    pdf = pdfs.build("doi", tmp_path / "pdf") if pdfs.pdflatex() and importlib.util.find_spec("pypdfium2") else None
    sized = Visit(browser, visit.running, visit.ws, viewport={"width": width, "height": height}, color_scheme=scheme)
    problems = {}
    try:
        page = sized.open()
        for name in _walk(sized, page, pdf):
            page.wait_for_timeout(250)
            found = page.evaluate(CLEAN)
            if found:
                problems[name] = found
    finally:
        sized.context.close()
    assert problems == {}, problems
    assert sized.problems == [], sized.problems


def test_going_to_a_view_or_a_tab_never_leaves_its_top_out_of_sight(visit):
    page = visit.open()
    for name in ("setup", "add", "state", "send", "check", "review", "library"):
        visit.nav("setup")
        page.locator("main").evaluate("(el) => el.scrollTo(0, el.scrollHeight)")       # far down in a long view ...
        visit.nav(name)
        page.wait_for_timeout(200)
        assert page.locator("main").evaluate("(el) => el.scrollTop") == 0, name         # ... and the next one opens at its top
        box = page.locator("main > :first-child").first.bounding_box()
        assert box["y"] >= page.locator("header.top").bounding_box()["height"], name
