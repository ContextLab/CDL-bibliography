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
        line = ""
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


async def until(pilot, condition, timeout=180.0, what="the expected state"):
    """Wait until ``condition()`` holds (for a state reached while a job is still running,
    such as a job's question on the screen)."""
    deadline = time.monotonic() + timeout
    while True:
        await pilot.pause(0.05)
        if condition():
            await pilot.pause()
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"{what} was not reached in {timeout} s; log: {pilot.app.log_lines[-10:]}")


def at_a_terminal(command, steps, env=None, cwd=None, size=(40, 140), timeout=180.0):
    """Run ``command`` with a real pseudo-terminal as its stdin, stdout and stderr. ``steps``:
    [(text to wait for in what is written after the keys before it, bytes to type then)]. Returns (exit status, everything
    it wrote). The process is killed when a text does not appear in ``timeout`` seconds."""
    import fcntl
    import pty
    import select
    import struct
    import subprocess
    import termios
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", size[0], size[1], 0, 0))
    process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, cwd=cwd, close_fds=True,
                               env=dict(env or os.environ, TERM="xterm-256color", LINES=str(size[0]), COLUMNS=str(size[1])))
    os.close(slave)
    seen, steps, deadline, since = b"", list(steps), time.monotonic() + timeout, 0
    try:
        while True:
            if steps and steps[0][0].encode() in seen[since:]:     # written after the last keys were typed
                os.write(master, steps.pop(0)[1])
                seen += b"\n<typed>\n"
                since = len(seen)
                deadline = time.monotonic() + timeout
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                if chunk:
                    seen += chunk
                    continue
            if process.poll() is not None:
                break
            if time.monotonic() > deadline:
                process.kill()
                raise AssertionError("the command did not get to " + repr(steps[0][0] if steps else "its end")
                                     + ": " + seen.decode(errors="replace")[-3000:])
        return process.wait(timeout=10), seen.decode(errors="replace")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)


def changes(app):
    """The rows of the proposal view's table of changes, as shown: {field: (typed, proposed,
    source, kind)}. A cell too long for its column ends in an ellipsis."""
    table = app.screen.query_one("#changes")
    rows = [[str(cell) for cell in table.get_row_at(number)] for number in range(table.row_count)]
    return {row[0]: tuple(row[1:]) for row in rows}
