"""`cdlbib web` can be stopped however it was started."""
import os
import re
import signal
import subprocess
import time

import pytest

import web_support as web
from test_web_server import CDLBIB, ZOLL90, stopped


@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM])
def test_the_server_stops_when_it_was_started_with_interrupts_ignored(tmp_path, number):
    """A shell starts a background job with SIGINT ignored and the child inherits that; the
    server must still stop on SIGINT, and on SIGTERM, with its ordinary exit."""
    env = dict(os.environ, **web.isolated_environment(tmp_path / "env"))
    for name in web.unset():
        env.pop(name, None)
    library = web.make_library(tmp_path / "library", ZOLL90)
    process = subprocess.Popen([CDLBIB, "--library", str(library.root), "web", "--no-open"], cwd=tmp_path, env=env,
                               stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                               preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN))
    try:
        said, deadline = [], time.monotonic() + 60
        while time.monotonic() < deadline and process.poll() is None:
            said.append(process.stderr.readline())
            if re.match(r"open: http://127\.0\.0\.1:\d+/#token=", said[-1]):
                said.append(process.stderr.readline())      # the line that follows the address
                break
        assert process.poll() is None, said
    finally:
        out, err = stopped(process, number)
    assert process.returncode == 0, err
    assert "Traceback" not in err


@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM])
def test_a_signal_that_arrives_while_the_browser_is_being_opened_stops_the_server_in_order(tmp_path, number):
    """Seen once on a GitHub runner: SIGTERM sent just after the address was printed ended the
    process with the signal's own death (-15), because the server took over the signals only
    after printing and after opening the browser. Here the "browser" is a program that takes
    five seconds, so the signal arrives in that time for certain: the server must stop with
    its ordinary exit and leave no upload folder behind."""
    env = dict(os.environ, **web.isolated_environment(tmp_path / "env"))
    for name in web.unset():
        env.pop(name, None)
    browser = tmp_path / "slow-browser"
    browser.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    browser.chmod(0o755)
    env["BROWSER"] = f"{browser} %s"
    temporary = tmp_path / "temporary"       # where the server makes its folder of uploads
    temporary.mkdir()
    env["TMPDIR"] = str(temporary)
    library = web.make_library(tmp_path / "library", ZOLL90)
    process = subprocess.Popen([CDLBIB, "--library", str(library.root), "web"], cwd=tmp_path, env=env,
                               stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                               preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN))
    try:
        said, deadline = [], time.monotonic() + 60
        while time.monotonic() < deadline and process.poll() is None:
            said.append(process.stderr.readline())
            if said[-1].startswith("This address works on this computer only"):
                break
        assert process.poll() is None, said
        started = time.monotonic()
    finally:
        out, err = stopped(process, number)
    assert process.returncode == 0, (process.returncode, err)
    assert time.monotonic() - started < 30
    assert list(temporary.glob("cdlbib-web-*")) == [], "the folder of uploads was left behind"
