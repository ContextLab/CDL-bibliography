"""Ctrl-C at a question when the command was started with interrupts ignored.

A shell without job control (a script, `nohup`, `cmd &` from sh) starts its background jobs
with SIGINT set to "ignore", and every process below inherits that; Python then installs no
KeyboardInterrupt handler. Before 2026-10-05 a cdlbib question asked in that state could not
be left with Ctrl-C: the read never returned (tests/test_update.py's
test_ctrl_c_at_the_question_aborts_with_nothing_changed hung for its whole 300 s limit when
the suite was run as such a job, on this code and on the code before it). A real
pseudo-terminal and a real SIGINT, as that test; the test process ignores SIGINT itself while
it starts the command, so the command inherits it.
"""
import signal

from test_update import at_a_terminal, backup_names, empty_folder, everything, managed, unsent  # noqa: F401


def test_ctrl_c_ends_the_question_when_interrupts_were_ignored_at_the_start(managed, tmp_path):
    home, upstream, ws, new = unsent(managed)
    before, state = everything(ws.root), (home / "state.json").read_bytes()
    inherited = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        code, out, shown = at_a_terminal("where", cwd=empty_folder(tmp_path), answers=b"", interrupt=True)
    finally:
        signal.signal(signal.SIGINT, inherited)
    assert code == 1 and out == "" and shown.endswith("Aborted.\n") and "Traceback" not in shown
    assert everything(ws.root) == before and backup_names(home) == []
    assert (home / "state.json").read_bytes() == state
