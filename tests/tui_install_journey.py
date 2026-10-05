"""Run by tests/test_tui_worker.py inside a scratch environment that has cdlbib and textual but
not pypdf: the terminal interface reads a PDF, and the package the job needs is installed
from inside the running interface after the question that --ask puts first (a no installs
nothing). Prints what was seen as JSON.

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

        seen["before"] = has("pypdf")
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
        await T.settle(pilot, timeout=600)
        seen["after_yes"] = [has("pypdf"), T.shown(app, "#p-info"), len(app.screen_stack)]
        seen["log"] = [line for line in app.log_lines if "install" in line]
        seen["most_active"] = app.jobs.most_active
        seen["modules"] = sorted(name for name in sys.modules if name.split(".")[0] == "pypdfium2")


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
