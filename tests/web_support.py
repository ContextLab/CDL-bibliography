"""Shared by the web interface's tests and scripts/capture_web.py: a library in a temporary
folder, the saved source responses put into that library's own response cache, an isolated
environment, the real server on loopback, and a small client for it.

Nothing is replaced by a stand-in. The server's lookups go through the project's real client
over the library's real response cache, which holds the responses saved under
tests/fixtures/; every proxy variable points at a closed local port, so a request that the
cache does not hold fails instead of leaving this computer.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

import conftest
from intake_support import CONTACT, saved
from cdlbib import extra_sources as xs
from cdlbib import workspace
from cdlbib.verification import Cache, dumps, load_entries, verify_entry
from cdlbib.web import server
from cdlbib.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
COMPLETION = json.loads((ROOT / "tests/fixtures/completion/responses.json").read_text(encoding="utf-8"))
NO_NETWORK = "http://127.0.0.1:9"       # the discard port: nothing listens there
TOKEN = server.TOKEN_HEADER
# Playwright keeps its browsers under the real HOME; read before any test substitutes HOME.
BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
    Path.home() / ("Library/Caches/ms-playwright" if sys.platform == "darwin" else ".cache/ms-playwright"))


def isolated_environment(folder, upstream=True):
    """The variables that keep a run to ``folder``: HOME, TEXMFHOME, cdlbib's data folder, a
    local upstream, the saved responses' contact address, and no way out to the network."""
    folder = Path(folder)
    for name in ("home", "texmf"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    found = {"HOME": str(folder / "home"), "TEXMFHOME": str(folder / "texmf"), "CDLBIB_HOME": str(folder / "data"),
             "CROSSREF_MAILTO": CONTACT, "HTTP_PROXY": NO_NETWORK, "HTTPS_PROXY": NO_NETWORK,
             "http_proxy": NO_NETWORK, "https_proxy": NO_NETWORK, "NO_PROXY": "127.0.0.1,localhost",
             "no_proxy": "127.0.0.1,localhost", "PLAYWRIGHT_BROWSERS_PATH": BROWSERS}
    if upstream:
        found["CDLBIB_UPSTREAM"] = str(conftest.build_upstream(folder / "up"))
    if sys.platform == "darwin":
        found["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return found


def unset():
    """Variables a run must not inherit: a library choice, TeX search paths, and the model keys
    (what a page shows about them is then the same on every computer)."""
    from cdlbib import secrets
    return ["CDLBIB_LIBRARY", "BIBINPUTS", "BSTINPUTS", "TEXINPUTS", "BIBCHECK_RESEARCH_MODEL",
            *[key.env for key in secrets.KEYS.values()]]


def isolate(monkeypatch, folder, home=True):
    """Apply isolated_environment for one test. ``home=False`` is for a test that asks gh who
    is logged in: the real HOME is kept (the login lives there) and so is the way to GitHub;
    cdlbib's data folder, the upstream and the TeX tree are still the test's own."""
    for name, value in isolated_environment(folder).items():
        if home or (name != "HOME" and "proxy" not in name.lower()):
            monkeypatch.setenv(name, value)
    for name in unset():
        monkeypatch.delenv(name, raising=False)
    workspace.select_library(None)


def make_library(folder, *entries, text=None):
    folder = Path(folder)
    (folder / "verification").mkdir(parents=True, exist_ok=True)
    (folder / "cdl.bib").write_text(text if text is not None else "".join(entry + "\n\n" for entry in entries),
                                    encoding="utf-8")
    return Workspace(folder)


def seed(ws, *names, completion=False, verify=()):
    """Put saved responses (tests/fixtures/intake/<name>, and the completion fixtures) into
    the library's own response cache, and store the verifier's result for the entries named
    in ``verify`` exactly as the gate stores it."""
    ws.work.mkdir(parents=True, exist_ok=True)
    client = xs.make_client(ws.database, contact=CONTACT, offline=True)
    try:
        items = [item for name in names for item in saved(name)] + (COMPLETION if completion else [])
        for item in items:
            request = item["request"]
            if isinstance(request, list):       # PubMed requests name the caller's contact address
                url, params, xml = request
                request = dumps([url, {k: CONTACT if v == "CONTACT" else v for k, v in params.items()}, xml])
            client.cache.save_response(request, item["response"])
        if verify:
            found = load_entries(ws.bib)
            cache = Cache(ws.database, ledger=ws.revocations)
            try:
                for key in verify:
                    cache.put(ws.bib, found[key], verify_entry(found[key], client))
            finally:
                cache.close()
    finally:
        client.cache.close()


class Client:
    """requests against a running server, with the token and the Origin a page would send."""

    def __init__(self, running):
        self.running, self.origin, self.token = running, running.origin, running.app.token
        self.http = requests.Session()
        self.http.trust_env = False

    def headers(self, post=False, **more):
        found = {TOKEN: self.token}
        if post:
            found["Origin"] = self.origin
        found.update(more)
        return {name: value for name, value in found.items() if value is not None}

    def raw(self, method, path, headers=None, **more):
        return self.http.request(method, self.origin + path, headers=headers or {}, timeout=120, **more)

    def settle(self, response, lines=None):
        """The result of a response, following its job when it gave one. Returns
        (result, error): exactly one is not None."""
        found = response.json()
        if "job" in found:
            return self.follow(found["job"], lines)
        return found.get("result"), found.get("error")

    def follow(self, job, lines=None):
        """Poll a job to its end, collecting its progress lines; (result, error)."""
        after = 0
        while True:
            view = self.raw("GET", f"/api/jobs/{job}", self.headers(), params={"after": after}).json()["result"]
            if lines is not None:
                lines.extend(view["lines"])
            after = view["next"]
            if view["done"]:
                return view.get("result"), view.get("error")

    def get(self, path, lines=None, **query):
        return self.settle(self.raw("GET", path, self.headers(), params=query), lines)

    def post(self, path, body=None, lines=None):
        return self.settle(self.raw("POST", path, self.headers(post=True), json=body or {}), lines)

    def upload(self, path, data, kind, **query):
        return self.settle(self.raw("POST", path, self.headers(post=True, **{"Content-Type": kind}), data=data,
                                    params=query))

    def ok(self, method, path, *args, **kwargs):
        """The result; an error fails the test with its message."""
        result, error = getattr(self, method)(path, *args, **kwargs)
        assert error is None, error
        return result


def start(ws, log=None):
    running = server.start(ws, log=log).serve_in_thread()
    return running, Client(running)


def wait_idle(running, seconds=120):
    """Wait until the job worker has nothing queued or running (the first job is api.prepare)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        worker = running.app.worker
        if worker.queue.empty() and worker.running is None:
            return
        time.sleep(0.02)
    raise AssertionError("the job worker did not become idle")
