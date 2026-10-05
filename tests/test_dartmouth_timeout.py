"""The Dartmouth adapter's one further request after a read timeout, against a real HTTP
server on this computer: the first request is left unanswered past the limit, the second is
answered. No model service is contacted."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from cdlbib import dartmouth_research_adapter as adapter

ANSWER = {"id": "local", "usage": None, "choices": [{"finish_reason": "stop", "message": {
    "content": json.dumps({"fields": {}, "uncertainties": ["nothing was read"]})}}]}


@pytest.fixture
def service(monkeypatch):
    """A server whose first ``slow`` requests wait 3 s before answering; gives (state, limit)."""
    state = {"seen": 0, "slow": 1}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            state["seen"] += 1
            if state["seen"] <= state["slow"]:
                time.sleep(3)
            body = json.dumps(ANSWER).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                pass                      # the client gave up on this request

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(adapter, "BASE", f"http://127.0.0.1:{server.server_address[1]}")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    yield state
    server.shutdown()
    server.server_close()


def test_a_request_that_times_out_once_is_made_once_more(service):
    finding, trace = adapter.complete({}, {}, "Extract", requests.Session(), "not-a-key", "local-model", read_timeout=1)
    assert service["seen"] == 2 and finding["uncertainties"] == ["nothing was read"]
    assert trace["provider"] == "dartmouth" and trace["model"] == "local-model"


def test_two_timeouts_are_an_error_that_says_so_and_no_third_request_is_made(service):
    service["slow"] = 5
    with pytest.raises(ValueError, match="did not answer within 1 seconds, twice"):
        adapter.complete({}, {}, "Extract", requests.Session(), "not-a-key", "local-model", read_timeout=1)
    assert service["seen"] == 2


def test_a_failed_adapter_is_reported_with_the_last_line_it_printed(tmp_path):
    from cdlbib.research import invoke_adapter
    script = tmp_path / "failing_adapter.py"
    script.write_text("import sys\nsys.stdin.read()\nprint('first line', file=sys.stderr)\n"
                      "print('Example adapter failed: the service did not answer', file=sys.stderr)\nsys.exit(2)\n",
                      encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        invoke_adapter(script, {"phase": "extract"})
    assert str(caught.value) == ("Research adapter failed: CalledProcessError: "
                                 "Example adapter failed: the service did not answer")


def test_only_a_sentence_written_in_the_adapter_is_printed_never_another_errors_text(tmp_path):
    """A ValueError that could carry remote text (a URL from a search result, say) is named
    by its type only; control characters never reach the caller's message."""
    import subprocess
    import sys
    code = ("import sys\nfrom cdlbib import dartmouth_research_adapter as a\n"
            "def run(payload):\n    raise {}\n"
            "a.run = run\nsys.argv = ['adapter']\na.main()\n")
    def said(raised):
        done = subprocess.run([sys.executable, "-c", code.format(raised)], input="{}", capture_output=True, text=True)
        assert done.returncode == 2 and done.stdout == ""
        return done.stderr.strip()
    assert said("ValueError('PDF URL must use HTTPS: http://evil.example/\\x1b[31m')") == "Dartmouth adapter failed: ValueError"
    assert said("a.Said('Dartmouth research HTTP 503')") == "Dartmouth adapter failed: Dartmouth research HTTP 503"

    from cdlbib.research import invoke_adapter
    script = tmp_path / "noisy_adapter.py"
    script.write_text("import sys\nsys.stdin.read()\nsys.stderr.write('failed \\x1b[31mred\\x07 ' + 'x' * 500)\nsys.exit(2)\n",
                      encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        invoke_adapter(script, {})
    message = str(caught.value)
    assert "\x1b" not in message and "\x07" not in message and len(message) < 260
