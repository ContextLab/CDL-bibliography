"""`cdlbib tui`: the command starts the real interface at a real (pseudo-)terminal on the
library the command line chose, and is listed with the other commands. No mocks."""
import re
import sys

import pytest
from typer.testing import CliRunner

pytest.importorskip("textual", reason="the terminal interface needs the optional package textual (pip install 'cdlbib[tui]')")

import conftest  # noqa: E402
import tui_support as T  # noqa: E402
from cdlbib import cli  # noqa: E402

ZOLL90 = conftest.ZOLL90
CTRL_Q = b"\x11"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    T.isolate(monkeypatch, tmp_path)
    T.offline(monkeypatch)
    yield
    conftest.no_real_library_touched()


def test_the_command_is_listed_and_says_what_it_does():
    styling = re.compile(r"\x1b\[[0-9;]*m")
    listed = CliRunner().invoke(cli.app, ["--help"])
    assert listed.exit_code == 0 and re.search(r"\btui\b", styling.sub("", listed.stdout))
    own = CliRunner().invoke(cli.app, ["tui", "--help"])
    assert own.exit_code == 0 and "Open the terminal interface on the library." in styling.sub("", own.stdout)


def test_the_command_opens_the_interface_on_the_chosen_library_and_quits(tmp_path):
    ws = T.library(tmp_path / "lib", ZOLL90)
    before = ws.bib.read_bytes()
    status, seen = T.at_a_terminal(
        [sys.executable, "-c", "from cdlbib.cli import main; main()", "--library", str(ws.root), "tui"],
        [("1 of 1 entries", b"?"), ("Keys", b"\x1b"), ("F2 Library", CTRL_Q)], cwd=tmp_path)
    assert status == 0, seen[-2000:]
    assert "cdlbib" in seen and "Zoll90" in seen and "F2 Library" in seen and "this help" in seen
    assert ws.bib.read_bytes() == before


def test_textual_is_the_optional_extra_tui_and_the_command_asks_for_it_first():
    import inspect
    from cdlbib import deps
    assert deps.requirements_for("tui") == ["textual<9,>=8"]
    assert deps.manual_command("tui", "textual") == "pip install 'textual<9,>=8'"
    source = inspect.getsource(cli.tui)
    assert 'deps.need("textual", "tui", "the terminal interface")' in source
    assert source.index("deps.need") < source.index("library(ctx")       # before a library is downloaded for it
    assert "textual" not in open(cli.__file__, encoding="utf-8").read().split("def tui")[0]   # nothing imports it earlier
