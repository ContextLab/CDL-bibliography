"""The terminal interface's one job worker: every call into cdlbib.api runs on its thread and
never two at once; quitting asks while a job runs; and a job that needs an optional package
has it installed from inside the interface (asked first with --ask), for real, in a scratch
environment. No mocks: the calls into cdlbib.api are observed with Python's own profiling
hook, and the packages are installed by uv or pip.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="the terminal interface needs the optional package textual (pip install 'cdlbib[tui]')")

import conftest  # noqa: E402
import intake_pdfs as pdfs  # noqa: E402
import tui_support as T  # noqa: E402
from cdlbib import api  # noqa: E402
from test_complete_identify import library_entry  # noqa: E402
from test_desk import KAHA12, ZOLL90  # noqa: E402

GAME62 = library_entry("Game62")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    T.isolate(monkeypatch, tmp_path)
    T.offline(monkeypatch)
    yield
    conftest.no_real_library_touched()


class Watch:
    """Records, with Python's profiling hook, every call into a function of cdlbib/api.py:
    which thread made it, and how many such calls were under way at once (in any thread)."""

    FILE = os.path.join("cdlbib", "api.py")

    def __init__(self):
        self.lock = threading.Lock()
        self.threads, self.names, self.calls = set(), [], []
        self.depth, self.other_threads_inside = {}, 0

    def __call__(self, frame, event, arg):
        if event not in ("call", "return") or not frame.f_code.co_filename.endswith(self.FILE):
            return
        if frame.f_back is not None and frame.f_back.f_code.co_filename.endswith(self.FILE):
            return                                   # the api calling itself: one call of the interface's
        if frame.f_code.co_name.startswith("<") or frame.f_code.co_flags & 0x20:
            return                                   # a comprehension, or a generator being resumed
        if "." in frame.f_code.co_qualname:
            return                                   # a property of a result (FormatResult.ok): reading data, no call
        me = threading.current_thread().name
        if me == "MainThread" and frame.f_code.co_name == "search":
            if event == "call":                    # the one call let through: recorded, and no part of the queue
                with self.lock:
                    self.threads.add(me)
                    self.calls.append((me, frame.f_code.co_qualname))
            return
        with self.lock:
            if event == "call":
                inside = [name for name, depth in self.depth.items() if depth and name != me]
                self.other_threads_inside += bool(inside)
                self.depth[me] = self.depth.get(me, 0) + 1
                self.threads.add(me)
                self.names.append(frame.f_code.co_name)
                self.calls.append((me, frame.f_code.co_qualname))
            else:
                self.depth[me] = max(0, self.depth.get(me, 0) - 1)

    def __enter__(self):
        threading.setprofile(self)
        sys.setprofile(self)
        return self

    def __exit__(self, *exc):
        sys.setprofile(None)
        threading.setprofile(None)


def test_rapid_actions_run_one_at_a_time_and_only_on_the_worker(tmp_path):
    ws = T.library(tmp_path / "lib", ZOLL90, KAHA12, GAME62)
    T.seed_responses(ws, T.COMPLETION)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            # Without waiting in between: two checks, a search typed letter by letter, a view that
            # loads its queue, the format check, an edit's preview and the setup report.
            await pilot.press("c", "down", "c", "slash", "z", "o", "l", "l", "escape", "f3", "t", "f5", "m", "f8", "c",
                              "f2", "e", "ctrl+p")
            assert not app.jobs.idle                                   # they are queued, not run at once
            await T.settle(pilot)
            return app.jobs
    with Watch() as watch:
        jobs = T.run(journey())
    # Every call into the core is the worker's, but one: filtering the summaries already loaded
    # (api.search over a list: a pure function of the list and the typed text).
    elsewhere = {call for call in watch.calls if call[0] != "cdlbib-jobs"}
    assert elsewhere == {("MainThread", "search")}, sorted(elsewhere)
    assert watch.other_threads_inside == 0 and jobs.most_active == 1
    for name in ("prepare", "entries", "library_state", "check_keys", "entry", "review_queue",
                 "check_format", "preview_edit", "setup_report", "revision"):
        assert name in watch.names, name
    assert watch.names[0] == "prepare"                                  # the first job of all
    spans = [(started, ended) for _, started, ended in jobs.history]
    assert len(spans) >= 12 and all(later[0] >= earlier[1] for earlier, later in zip(spans, spans[1:]))
    labels = [label for label, _, _ in jobs.history]
    assert labels.count("check Zoll90") == 1 and labels.count("check Kaha12") == 1 and "format check" in labels
    assert "search" not in labels                                       # a search is not a job: it never waits
    for key in ("Zoll90", "Kaha12"):                                    # the checks did run: each stored a result
        assert api.entry(ws, key).status != "pending" and api.entry(ws, key).result.get("checked_at")
    assert api.entry(ws, "Game62").status == "pending"


def test_quitting_while_a_job_runs_asks_and_waits_or_stays(tmp_path):
    root = tmp_path / "big"
    root.mkdir()
    shutil.copy(conftest.FROZEN_LIBRARY, root / "cdl.bib")
    from cdlbib.tui import CdlbibApp
    from cdlbib.workspace import Workspace
    seen = {}

    async def journey():
        app = CdlbibApp(Workspace(root))
        async with app.run_test(size=T.SIZE, notifications=True) as pilot:
            await pilot.pause(0.3)                                      # reading 6,481 entries takes seconds
            assert not app.jobs.idle
            await pilot.press("ctrl+q")
            await pilot.pause(0.2)
            assert type(app.screen).__name__ == "ChoiceScreen"
            question = T.shown(app, "#question")
            assert question.startswith("A job is running: read the library") and "more waiting" in question
            labels = [str(button.label) for button in app.screen.query("Button")]
            assert labels == ["[w] Wait for it to finish, then quit", "[x] Quit now; the running job is stopped where it is",
                              "[s] Stay"]
            await pilot.press("s")
            await pilot.pause(0.2)
            assert len(app.screen_stack) == 1 and not app.jobs.idle and app.return_code is None   # still open, still working
            await pilot.press("ctrl+q")
            await pilot.pause(0.2)
            await pilot.press("w")
            await pilot.pause(0.2)
            assert "quitting when the job is done" in str(app.query_one("#jobline").render())
            seen["waiting"] = not app.jobs.idle
            started = time.monotonic()
            while app.return_code is None and time.monotonic() - started < 120:
                await pilot.pause(0.1)
            seen["exited"] = app.return_code
            seen["log"] = list(app.log_lines)
            seen["history"] = [label for label, _, _ in app.jobs.history]
    T.run(journey())
    assert seen["exited"] == 0 and seen["waiting"] and "read the library" in seen["history"]   # finished, not cut off
    assert any(line.startswith("ready: 6481 entries prepared") for line in seen["log"])


def test_quitting_with_nothing_running_does_not_ask(tmp_path):
    ws = T.library(tmp_path / "lib", ZOLL90)
    from cdlbib.tui import CdlbibApp

    async def journey():
        app = CdlbibApp(ws)
        async with app.run_test(size=T.SIZE) as pilot:
            await T.settle(pilot)
            await pilot.press("q")
            started = time.monotonic()
            while app.return_code is None and time.monotonic() - started < 10:
                await pilot.pause(0.05)
            assert app.return_code == 0 and len(app.screen_stack) <= 1
    T.run(journey())


def test_a_failure_the_core_does_not_report_is_shown_and_the_worker_goes_on(tmp_path):
    ws = T.library(tmp_path / "lib", ZOLL90)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            ws.bib.unlink()                                              # the library disappears under the interface
            app.refresh_library(force=True)
            await T.settle(pilot)
            assert "could not be read" in T.shown(app, "#banner") or any("cdl.bib" in line for line in app.log_lines[-3:])
            ws.bib.write_text(ZOLL90 + "\n", encoding="utf-8")
            app.refresh_library(force=True)
            await T.settle(pilot)
            assert T.shown(app, "#banner") == "" and "1 of 1 entries" in T.screen_text(app)
            assert app.jobs.thread.is_alive()
    T.run(journey())


@pytest.mark.skipif(not pdfs.pdflatex(), reason="pdflatex is not installed, so no PDF can be typeset for the test")
def test_a_missing_package_is_installed_from_inside_the_interface_asked_first_with_ask(tmp_path):
    """Real installs into a scratch environment (uv, as tests/test_deps.py): pypdf after a yes
    under --ask, pypdfium2 without a question by default; a no installs nothing."""
    if not shutil.which("uv"):
        pytest.skip("uv is needed to build the scratch environment the packages are installed into")
    python = str(tmp_path / "e" / "bin" / "python")
    clean = {name: value for name, value in os.environ.items()
             if name.lower() not in T.refused_network() and name != "CROSSREF_MAILTO"}      # the index must be reachable
    clean.pop("PYTHONPATH", None)
    made = subprocess.run(["uv", "venv", "-q", str(tmp_path / "e"), "--python", sys.executable], capture_output=True,
                          text=True, env=clean)
    assert made.returncode == 0, made.stderr
    installed = subprocess.run(["uv", "pip", "install", "-q", "--python", python, str(ROOT)], capture_output=True,
                               text=True, env=clean)
    if installed.returncode != 0:
        pytest.skip("the scratch environment could not be built (is a package index reachable?): "
                    + installed.stderr.strip()[-300:])
    pdf = pdfs.build("doi", tmp_path / "pdfs")
    ws = T.library(tmp_path / "work" / "lib", ZOLL90)
    command = [str(tmp_path / "e" / "bin" / "cdlbib"), "--library", str(ws.root)]
    here = dict(clean, **T.isolated_environment(tmp_path / "work" / "user"))

    def has(module):
        return subprocess.run([python, "-c", f"import {module}"], capture_output=True).returncode == 0

    # The interface's own package first: textual is not there. Asked for with --ask and nobody to ask: not installed.
    assert not has("textual")
    asked = subprocess.run([command[0], "--ask", *command[1:], "tui"], capture_output=True, text=True, env=here,
                           stdin=subprocess.DEVNULL, cwd=tmp_path)
    assert asked.returncode == 1 and "the terminal interface needs the package 'textual'" in asked.stderr
    assert not has("textual")
    # By default it is installed, after saying so, and the command runs again: the interface opens.
    status, shown = T.at_a_terminal([*command, "tui"], [("1 of 1 entries", b"?"), ("this help", b"\x1b"), ("<typed>", b"\x11")],
                                    env=here, cwd=tmp_path, timeout=600)      # the help, close it, ctrl+q
    assert status == 0 and "installing textual (needed for: the terminal interface) ..." in shown and has("textual")
    run = subprocess.run([python, str(ROOT / "tests/tui_install_journey.py"), str(tmp_path / "work"), str(pdf)],
                         capture_output=True, text=True, timeout=900, cwd=tmp_path,
                         env=dict(clean, PYTHONPATH=str(ROOT / "tests"), CDLBIB_UPSTREAM=os.environ["CDLBIB_UPSTREAM"]))
    assert run.returncode == 0, run.stderr[-3000:]
    seen = json.loads(run.stdout.strip().splitlines()[-1])
    assert seen["before"] == [False, False]
    assert seen["question"].endswith("needs 'pypdf'. Install it now?")
    assert seen["declined"][0] is False and "needs the package 'pypdf' (install: pip install 'pypdf" in seen["declined"][1]
    assert "needs 'pypdfium2'. Install it now?" in seen["second_question"]
    installed_pypdf, installed_pdfium, info = seen["after_yes"]
    assert installed_pypdf is True and installed_pdfium is False and "doi: 10.1002/tea.3660271011 (page 1)" in info
    assert "The first page is not drawn:" in seen["page_declined"] and "pypdfium2" in seen["page_declined"]
    has_pdfium, blocks, screens = seen["default"]
    assert has_pdfium is True and blocks > 500 and screens == 1          # installed without a question, and drawn
    assert any(line.startswith("installing pypdf (needed for:") for line in seen["log"])
    assert any(line.startswith("installing pypdfium2 (needed for: the PDF page preview)") for line in seen["log"])
    assert "installed pypdfium2" in seen["log"] and seen["most_active"] == 1


# --- nothing ends the worker ------------------------------------------------------------------------

def test_a_callback_or_a_progress_line_that_raises_does_not_end_the_worker(tmp_path):
    ws = T.library(tmp_path / "lib", ZOLL90)

    async def journey():
        async with T.opened(ws) as pilot:
            app, seen = pilot.app, []

            def broken(result):
                raise RuntimeError("the result could not be shown")

            def chatty(job):
                job.progress(object())                       # a line that is no text is still a line
                say, job.runner.say = job.runner.say, None   # ... and a log that cannot be written to
                try:
                    job.progress("lost")
                finally:
                    job.runner.say = say
                return api.entries(ws)
            app.job("a job whose callback raises", lambda job: api.entries(ws), broken)
            app.job("a job whose failure callback raises", lambda job: api.entry(ws, "Nope99"), None, broken)
            app.job("a job whose log line cannot be written", chatty, lambda found: seen.append(len(found)))
            app.job("the job after them", lambda job: api.entry(ws, "Zoll90"), lambda detail: seen.append(detail.key))
            await T.settle(pilot)
            assert seen == [1, "Zoll90"] and app.jobs.thread.is_alive() and app.jobs.idle
            assert "error: a job whose callback raises: RuntimeError: the result could not be shown" in app.log_lines
            assert "error: a job whose failure callback raises: RuntimeError: the result could not be shown" in app.log_lines
            await T.press(pilot, "c")                                        # and the interface still works
            assert "check Zoll90" in [label for label, _, _ in app.jobs.history]
    T.run(journey())


def test_a_job_started_from_an_editor_that_was_closed_reports_to_nobody(tmp_path):
    ws = T.library(tmp_path / "lib", ZOLL90)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            hold = threading.Event()
            app.job("a long job", lambda job: hold.wait(20))                 # the preview has to wait behind it
            await pilot.press("e")
            await pilot.pause(0.3)
            await pilot.press("ctrl+p", "escape")                            # previewed, then closed before it ran
            await pilot.pause(0.3)
            assert type(app.screen).__name__ != "EditScreen" and not app.jobs.idle
            hold.set()
            await T.settle(pilot)
            assert "preview the edit of Zoll90" in [label for label, _, _ in app.jobs.history]
            assert [line for line in app.log_lines if line.startswith("error:")] == [] and app.jobs.thread.is_alive()
    T.run(journey())
