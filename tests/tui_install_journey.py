"""Run by tests/test_tui_worker.py inside a scratch environment that has cdlbib and textual but
neither pypdf nor pypdfium2: the terminal interface reads a PDF, and the packages the jobs
need are installed from inside the running interface, with a question first (--ask) and
without one (the default). Prints what was seen as JSON.

    python tui_install_journey.py LIBRARY_FOLDER PDF
"""
import importlib.util
import json
import sys
from pathlib import Path

import tui_support as T
from cdlbib import deps
from cdlbib.workspace import Workspace


def has(module):
    importlib.invalidate_caches()
    return importlib.util.find_spec(module) is not None


async def journey(ws, pdf, seen):
    async with T.opened(ws) as pilot:
        app = pilot.app

        def asking():
            return type(app.screen).__name__ == "ConfirmScreen"

        seen["before"] = [has("pypdf"), has("pypdfium2")]
        deps.set_ask(True)                                    # as `cdlbib --ask tui`
        await T.press(pilot, "f4", "escape", "right", "right", "enter")
        await T.type_text(pilot, str(pdf))
        await pilot.press("enter")
        await T.until(pilot, asking, what="the question about pypdf")
        seen["question"] = T.shown(app, "#question")
        await T.press(pilot, "n")                             # not now: nothing is installed
        seen["declined"] = [has("pypdf"), T.shown(app, "#p-message")]

        app.screen.query_one("#p-path").focus()
        await pilot.press("enter")
        await T.until(pilot, asking, what="the question about pypdf, again")
        await pilot.press("y")                                # install, then the job runs again
        await T.until(pilot, lambda: asking() and "pypdfium2" in T.shown(app, "#question"), timeout=600,
                      what="the question about pypdfium2")
        seen["second_question"] = T.shown(app, "#question")
        seen["after_yes"] = [has("pypdf"), has("pypdfium2"), T.shown(app, "#p-info", screen=app.screen_stack[0])]
        await T.press(pilot, "n")
        seen["page_declined"] = T.shown(app, "#p-page")

        deps.set_ask(False)                                   # the default: say so, install, run again
        app.screen.query_one("#p-path").focus()
        await pilot.press("enter")
        await T.settle(pilot, timeout=600)
        seen["default"] = [has("pypdfium2"), T.shown(app, "#p-page").count("▀"), len(app.screen_stack)]
        seen["log"] = [line for line in app.log_lines if "install" in line]
        seen["most_active"] = app.jobs.most_active


def main(folder, pdf):
    folder = Path(folder)
    T.apply_environment(T.isolated_environment(folder / "user"))
    ws = Workspace(folder / "lib")
    seen = {}
    try:
        T.run(journey(ws, Path(pdf), seen))
    finally:
        print(json.dumps(seen))


if __name__ == "__main__":
    main(*sys.argv[1:])
