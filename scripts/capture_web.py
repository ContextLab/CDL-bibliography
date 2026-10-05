"""Screenshots of the web interface's key states, as PNG files.

    python scripts/capture_web.py [--out docs/media] [--width 1180] [--height 760] [--only NAME ...]
    python scripts/capture_web.py --gif [--out docs/media]

Runs the real server (cdlbib.web.server) on a temporary library: the suite's frozen library
(tests/fixtures/cdl-prewave1-2026-09-26.bib, about 6,400 entries) without Zoll90, with one
entry changed so that a source disagrees with it; then, for the Send and Library state views,
on a managed library downloaded from a local upstream that has since gained a commit, with
an edit that was not sent. HOME, TEXMFHOME, cdlbib's data folder and
the upstream are temporary folders, the lookups are answered from the responses saved under
tests/fixtures/ (no request leaves this computer), and the real data folder is compared
before and after. The PDF is typeset here with pdflatex. Needs the dev dependencies
`playwright` (with chromium installed) and `pytest` (tests/conftest.py is imported).

With --gif, the screenshots above are not made: one short journey on the same temporary
library (a search, an entry, its issues, an edit and its preview) is captured as a frame per
step and joined into web-demo.gif. That needs ffmpeg on PATH.
"""
import argparse
import os
import re
import shutil
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import conftest                      # noqa: E402  (sets the data folder and the upstream to temporary ones)
import intake_pdfs as pdfs           # noqa: E402
import web_support as web            # noqa: E402
from test_complete_identify import library_entry   # noqa: E402

GAME62 = library_entry("Game62")
NAMES = ("library", "evidence", "edit-preview", "check", "review-approve", "review", "add-identifier", "add-pdf", "add-manual", "setup",
         "library-dark", "library-narrow", "send", "state", "update-choices")


def build_library(folder):
    text = conftest.FROZEN_LIBRARY.read_text(encoding="utf-8")
    start = text.index("@article{Zoll90,")
    text = text[:start] + text[text.index("\n@", start) + 1:]
    text = text.replace(GAME62, GAME62.replace("Volume = {63}", "Volume = {36}"))
    ws = web.make_library(folder, text=text)
    web.seed(ws, "pdf_lookups.json.gz", completion=True, verify=("Game62", "MartJohn15", "SilvEtal19"))
    return ws


def managed_library(folder):
    """The managed library, downloaded from the run's local upstream; then an edit that is not
    sent, and a new commit in the upstream."""
    from cdlbib import api
    os.chdir(folder)                 # no cdl.bib here or above: the managed library is the one in use
    ws = api.ensure_library()
    ws.bib.write_text(ws.bib.read_text(encoding="utf-8") + "\n" + GAME62 + "\n", encoding="utf-8")
    work = Path(os.environ["CDLBIB_UPSTREAM"]).parent / "upstream-work"
    (work / "cdl.bib").write_text(library_entry("MartJohn15") + "\n\n" + conftest.ZOLL90 + "\n", encoding="utf-8")
    conftest._git("commit", "--quiet", "-am", "A second entry", cwd=work)
    conftest._git("push", "--quiet", os.environ["CDLBIB_UPSTREAM"], "master", cwd=work)
    return ws


def recompress(path):
    """Write the PNG again with zlib's strongest setting (what Playwright writes is lightly packed)."""
    import struct
    data = path.read_bytes()
    out, at, packed = [data[:8]], 8, b""
    chunks = []
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        chunks.append((kind, data[at + 8:at + 8 + length]))
        at += 12 + length
    packed = zlib.compress(zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT")), 9)
    done = False
    for kind, body in chunks:
        if kind == b"IDAT":
            if done:
                continue
            body, done = packed, True
        out.append(struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body)))
    smaller = b"".join(out)
    if len(smaller) < len(data):
        path.write_bytes(smaller)


def capture(out, width, height, only):
    from playwright.sync_api import expect, sync_playwright
    folder = Path(tempfile.mkdtemp(prefix="cdlbib-capture-web-"))
    os.environ.update(web.isolated_environment(folder))
    for name in web.unset():
        os.environ.pop(name, None)
    ws = build_library(folder / "library")
    pdf = pdfs.build("doi", folder / "pdf") if pdfs.pdflatex() else None
    running, _ = web.start(ws)
    wanted = [name for name in NAMES if not only or name in only]
    made = []

    def shot(page, name):
        if name in wanted:
            page.wait_for_timeout(250)
            target = out / f"web-{name}.png"
            page.screenshot(path=str(target))
            recompress(target)
            made.append(target)

    try:
        with sync_playwright() as play:
            browser = play.chromium.launch()
            context = browser.new_context(viewport={"width": width, "height": height}, color_scheme="light")
            page = context.new_page()
            problems = []
            page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: problems.append(str(error)))
            page.goto(running.url)
            page.wait_for_selector(".vt-row", timeout=180_000)

            page.fill("#search", "games factorial")
            expect(page.locator(".vt-row")).to_have_count(1)
            page.click(".vt-row")
            page.wait_for_selector(".detail-head h2")
            page.fill("#search", "")
            expect(page.locator("#match-count")).to_contain_text(re.compile(r"^\d+ entries"))
            shot(page, "library")
            page.click("role=tab[name=/Issues/]")
            shot(page, "evidence")

            page.click("text=Edit")
            page.wait_for_selector("#entry-text")
            page.fill("#entry-text", GAME62.replace("Pages = {1--11}", "Pages = {1-11}").replace("Volume = {63}", "Volume = {36}"))
            page.click("button:has-text('Preview')")
            page.wait_for_selector(".diff")
            shot(page, "edit-preview")
            page.fill("#entry-text", GAME62.replace("Volume = {63}", "Volume = {36}"))    # nothing unsaved is left behind

            if "check" in wanted:       # minutes: the format check reads the whole library
                page.click("#nav >> text=Check")
                page.fill("#check-keys", "Game62 MartJohn15")
                page.click("button:has-text('Check these entries')")
                page.wait_for_selector("text=Entries checked", timeout=900_000)
                shot(page, "check")

            page.click("#nav >> text=Library")
            page.wait_for_selector(".vt-row")
            page.fill("#search", "key:Game62")
            expect(page.locator(".vt-row")).to_have_count(1)
            page.click(".vt-row")
            page.click("button:has-text('Approve')")
            page.wait_for_selector("dialog[open]")
            page.fill("dialog input[name=source]", "The journal's page for the article")
            page.fill("dialog textarea[name=note]", "Volume, issue and pages compared with the printed issue.")
            shot(page, "review-approve")
            page.click("dialog button:has-text('Cancel')")
            page.click("dialog button:has-text('Cancel')")       # typed text: discarding it takes a second step

            page.click("#nav >> [data-view=review]")
            page.click("button:has-text('All entries')")
            page.fill("#review-search", "memory")
            page.wait_for_selector(".queue button.item", timeout=60_000)
            page.wait_for_timeout(800)
            for box in page.locator("#alerts .alert button").all():
                box.click()
            page.locator(".queue button.item").first.click()
            page.wait_for_selector(".detail-head h2")
            shot(page, "review")

            page.click("#nav >> text=Add")
            page.click("role=tab[name='Identifiers']")
            page.fill("#add-identifiers", pdfs.ZOLLER_DOI)
            page.click("button:has-text('Look up')")
            page.wait_for_selector("article.card", timeout=120_000)
            shot(page, "add-identifier")
            page.click("article.card >> [data-action=skip]")

            if pdf is not None:
                page.click("role=tab[name='PDF']")
                page.set_input_files("#add-pdf", str(pdf))
                page.wait_for_selector("[data-action=pdf-lookup]", timeout=120_000)
                if page.locator("img.pdf-image").count() == 0 and page.locator("iframe.pdf-frame").count() == 0:
                    page.wait_for_selector("img.pdf-image", timeout=60_000)
                page.click("[data-action=pdf-lookup]")
                page.wait_for_selector("article.card [data-action=accept]", timeout=120_000)
                page.wait_for_selector(".beside img.pdf-image, .beside iframe", timeout=60_000)
                page.locator(".beside").scroll_into_view_if_needed()
                shot(page, "add-pdf")
                page.click("article.card >> [data-action=skip]")
                page.click("role=tab[name='PDF']")
                page.click("button:has-text('Type it in by hand')")
                page.wait_for_selector("input[data-field=doi]")
                page.locator("[role=tablist]").scroll_into_view_if_needed()
                shot(page, "add-manual")

            page.click("#nav >> [data-view=setup]")
            page.wait_for_selector("main table")
            shot(page, "setup")

            page.click("#nav >> text=Library")
            page.wait_for_selector(".vt-row")
            page.click("#theme-toggle")
            page.click("#theme-toggle")
            page.fill("#search", "memory")
            page.wait_for_timeout(600)
            page.click(".vt-row")
            page.wait_for_selector(".detail-head h2")
            shot(page, "library-dark")
            page.click("#theme-toggle")
            page.set_viewport_size({"width": 390, "height": 760})
            shot(page, "library-narrow")
            page.close()

            running.stop()
            running, _ = web.start(managed_library(folder))
            page = context.new_page()
            page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: problems.append(str(error)))
            page.goto(running.url)
            page.wait_for_selector(".vt-row", timeout=60_000)
            page.click("#nav >> [data-view=send]")
            page.wait_for_selector("text=Files to send")
            shot(page, "send")
            page.click("#nav >> [data-view=state]")
            page.click("button:has-text('Ask the upstream now')")
            page.wait_for_selector(".banner", timeout=60_000)
            shot(page, "state")
            page.click("button:has-text('Update now')")
            page.wait_for_selector("dialog[open]", timeout=60_000)
            shot(page, "update-choices")
            page.click("dialog >> text=Cancel")
            browser.close()
    finally:
        os.chdir(ROOT)
        running.stop()
        shutil.rmtree(folder, ignore_errors=True)
    return made, problems


GIF_SIZE = (960, 620)


def record(out):
    """The journey of web-demo.gif: a screenshot at each step, each shown for its time, joined by ffmpeg."""
    import subprocess
    from playwright.sync_api import expect, sync_playwright
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg was not found on PATH; --gif needs it to join the frames")
    folder = Path(tempfile.mkdtemp(prefix="cdlbib-capture-web-"))
    os.environ.update(web.isolated_environment(folder))
    for name in web.unset():
        os.environ.pop(name, None)
    ws = build_library(folder / "library")
    running, _ = web.start(ws)
    width, height = GIF_SIZE
    frames = folder / "frames"
    frames.mkdir()
    target, problems, shown = out / "web-demo.gif", [], []

    def frame(page, seconds):
        page.wait_for_timeout(250)
        path = frames / f"{len(shown):03d}.png"
        page.screenshot(path=str(path))
        shown.append((path, seconds))

    try:
        with sync_playwright() as play:
            browser = play.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": height}, color_scheme="light")
            page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: problems.append(str(error)))
            page.goto(running.url)
            page.wait_for_selector(".vt-row", timeout=180_000)
            frame(page, 1.5)
            page.click("#search")
            for typed in ("games", "games fact", "games factorial"):
                page.fill("#search", typed)
                page.wait_for_timeout(700)
                frame(page, 0.7)
            expect(page.locator(".vt-row")).to_have_count(1)
            page.click(".vt-row")
            page.wait_for_selector(".detail-head h2")
            frame(page, 2.5)
            page.click("role=tab[name=/Issues/]")
            frame(page, 3)
            page.click("text=Edit")
            page.wait_for_selector("#entry-text")
            frame(page, 1.5)
            page.fill("#entry-text", GAME62.replace("Volume = {63}", "Volume = {36}").replace("Pages = {1--11}", "Pages = {1-11}"))
            frame(page, 1.5)
            page.click("button:has-text('Preview')")
            page.wait_for_selector(".diff")
            frame(page, 4)
            page.fill("#entry-text", GAME62.replace("Volume = {63}", "Volume = {36}"))    # nothing unsaved is left behind
            browser.close()
        listing = folder / "frames.txt"
        listing.write_text("".join(f"file '{path}'\nduration {seconds}\n" for path, seconds in shown)
                           + f"file '{shown[-1][0]}'\n", encoding="utf-8")   # the concat demuxer needs the last file twice
        # One palette for all frames, few colours, no dithering: flat interface colours stay
        # flat, which is what keeps the file small.
        done = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-vf",
             "split[a][b];[a]palettegen=max_colors=32:stats_mode=full[p];[b][p]paletteuse=dither=none",
             "-fps_mode", "vfr", str(target)], capture_output=True, text=True)
        if done.returncode != 0:
            raise SystemExit("ffmpeg failed: " + done.stderr[-1000:])
    finally:
        os.chdir(ROOT)
        running.stop()
        shutil.rmtree(folder, ignore_errors=True)
    return [target], problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "docs" / "media"))
    parser.add_argument("--width", type=int, default=1180)
    parser.add_argument("--height", type=int, default=760)
    parser.add_argument("--only", nargs="*", default=[], choices=NAMES)
    parser.add_argument("--gif", action="store_true", help="record web-demo.gif instead of the screenshots (needs ffmpeg)")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    made, problems = record(out) if args.gif else capture(out, args.width, args.height, args.only)
    for path in made:
        print(f"{path} ({path.stat().st_size // 1024} KB)")
    for line in problems:
        print("browser error:", line, file=sys.stderr)
    problem = conftest.real_data_folder_problem()
    if problem:
        print("ERROR:", problem, file=sys.stderr)
    return 1 if problems or problem else 0


if __name__ == "__main__":
    raise SystemExit(main())
