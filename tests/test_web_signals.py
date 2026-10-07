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
