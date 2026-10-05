"""Shared by the terminal-interface tests and scripts/capture_tui.py: the real app driven by
Textual's pilot over a temporary library, with the user's folders substituted.

Nothing here is a mock: the app is cdlbib.tui.CdlbibApp, its jobs call the real cdlbib.api,
lookups are the suite's saved responses in the library's own response cache with the network
refused by an unreachable proxy, and PDFs are typeset when a test needs them.
"""
import asyncio
import contextlib
import gzip
import html
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTACT = "valid@example.org"      # never sent anywhere: the proxy refuses every request
SIZE = (150, 46)


def refused_network():
    """An unreachable loopback proxy: a lookup the saved responses do not hold fails at once."""
    proxy = "http://127.0.0.1:1"
    return {"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "ALL_PROXY": proxy, "NO_PROXY": "",
            "http_proxy": proxy, "https_proxy": proxy, "all_proxy": proxy, "no_proxy": ""}


def isolated_environment(folder):
    """The variables that keep a run away from the user's own folders: HOME, the TeX tree and
    cdlbib's data folder are folders under ``folder``."""
    folder = Path(folder)
    for name in ("home", "texmf", "cdlbib-home"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    return {"HOME": str(folder / "home"), "TEXMFHOME": str(folder / "texmf"), "CDLBIB_HOME": str(folder / "cdlbib-home")}


def seed_responses(ws, *files):
    """Fill the library's own response cache with saved responses, as the tests' offline client
    is filled: ``files`` are paths of the completion fixture (a JSON list) or of the intake
    fixtures (gzipped JSON lists)."""
    from cdlbib import extra_sources as xs
    from cdlbib.verification import dumps
    ws.work.mkdir(parents=True, exist_ok=True)
    client = xs.make_client(ws.database, contact=CONTACT, offline=True)
    try:
        for path in files:
            path = Path(path)
            data = gzip.open(path).read() if path.suffix == ".gz" else path.read_bytes()
            for item in json.loads(data.decode("utf-8")):
                request = item["request"]
                if isinstance(request, list):      # PubMed requests name the caller's contact address
                    url, params, xml = request
                    request = dumps([url, {k: CONTACT if v == "CONTACT" else v for k, v in params.items()}, xml])
                client.cache.save_response(request, item["response"])
    finally:
        client.cache.close()


COMPLETION = ROOT / "tests/fixtures/completion/responses.json"
PDF_LOOKUPS = ROOT / "tests/fixtures/intake/pdf_lookups.json.gz"
TUI_SEARCH = ROOT / "tests/fixtures/intake/tui_search.json.gz"


async def settle(pilot, timeout=120.0):
    """Wait until the job worker is idle and the interface has drawn what the jobs returned."""
    app, deadline = pilot.app, time.monotonic() + timeout
    quiet = 0
    while quiet < 3:
        await pilot.pause(0.02)
        quiet = quiet + 1 if app.jobs.idle else 0
        if time.monotonic() > deadline:
            raise AssertionError(f"jobs still running after {timeout} s: {app.jobs.busy_label}; log: {app.log_lines[-10:]}")
    for _ in range(50):                  # a screen that was just pushed has drawn its parts
        await pilot.pause()
        if app.screen.is_mounted and len(app.screen.children):
            break


async def press(pilot, *keys):
    for key in keys:
        await pilot.press(key)
    await settle(pilot)


async def type_text(pilot, text):
    await pilot.press(*[{" ": "space"}.get(char, char) for char in text])
    await settle(pilot)


def screen_text(app):
    """What is on the screen now, as lines of text (from Textual's own screenshot)."""
    svg = app.export_screenshot()
    lines = {}
    for match in re.finditer(r'<text class="[^"]*" x="([\d.]+)" y="([\d.]+)" textLength="[\d.]+" clip-path="[^"]*">(.*?)</text>',
                             svg):
        x, y, text = float(match.group(1)), float(match.group(2)), html.unescape(match.group(3))
        lines.setdefault(y, []).append((x, text.replace("\xa0", " ")))
    out = []
    for y in sorted(lines):
        line, at = "", 0.0
        for x, text in sorted(lines[y]):
            column = round(x / 12.2)
            line = line.ljust(column) + text
        out.append(line.rstrip())
    return "\n".join(out)


def shown(app, selector, screen=None):
    """The text a pane shows (cdlbib.tui.widgets.Shown), by CSS selector."""
    return (screen or app.screen).query_one(selector).plain


def run(coroutine):
    return asyncio.run(coroutine)


@contextlib.asynccontextmanager
async def opened(ws, size=SIZE):
    """The app on ``ws``, started, with its first jobs done."""
    from cdlbib.tui import CdlbibApp
    app = CdlbibApp(ws)
    async with app.run_test(size=size, notifications=True) as pilot:
        await settle(pilot)
        yield pilot
        app.jobs.stop()


def apply_environment(values):
    """Set ``values`` in os.environ; returns what to pass to ``restore_environment``."""
    before = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    return before


def restore_environment(before):
    for name, value in before.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def isolate(monkeypatch, tmp_path):
    """Keep a test away from the user's own folders and settings: HOME, the TeX tree and
    cdlbib's data folder are folders of the test; no library is chosen by the environment;
    TeX's search variables are unset; --ask is off. Returns the folder they are under."""
    from cdlbib import deps, workspace
    folder = tmp_path / "user"
    for name, value in isolated_environment(folder).items():
        monkeypatch.setenv(name, value)
    for name in ("CDLBIB_LIBRARY", "BIBINPUTS", "BSTINPUTS", "TEXINPUTS", "COLORFGBG", "TEXTUAL_THEME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in (("GIT_AUTHOR_NAME", "cdlbib tests"), ("GIT_AUTHOR_EMAIL", "tests@cdlbib.invalid"),
                        ("GIT_COMMITTER_NAME", "cdlbib tests"), ("GIT_COMMITTER_EMAIL", "tests@cdlbib.invalid"),
                        ("GIT_TERMINAL_PROMPT", "0")):
        monkeypatch.setenv(name, value)
    import sys
    if sys.platform == "darwin":       # Apple's developer tools are found without the user's own HOME
        monkeypatch.setenv("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")
    workspace.select_library(None)
    deps.set_ask(False)
    return folder


def offline(monkeypatch):
    """Lookups come from the saved responses only: the contact is the fixtures', and any
    request they do not hold is refused by an unreachable proxy."""
    monkeypatch.setenv("CROSSREF_MAILTO", CONTACT)
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)


def library(folder, *entries, git=False):
    """A library of its own in ``folder`` holding ``entries`` (exact entry texts)."""
    from cdlbib.workspace import Workspace
    folder = Path(folder)
    (folder / "verification").mkdir(parents=True, exist_ok=True)
    (folder / "cdl.bib").write_text("\n\n".join(entries) + "\n", encoding="utf-8")
    return Workspace(folder)
