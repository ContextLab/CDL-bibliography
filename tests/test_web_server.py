"""The web interface's server: what it serves, the job worker, the `cdlbib web` command, the
page's files. The real server on loopback against libraries in tmp_path; nothing is replaced
by a stand-in."""
import concurrent.futures
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import conftest
import intake_pdfs as pdfs
import web_support as web
from cdlbib import __version__, api, prompts, theme
from cdlbib.web import jobs, routes, server, store

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(server.__file__).parent / "static"
ZOLL90 = conftest.ZOLL90
KAHA12 = ("@book{Kaha12,\n\tAddress = {New York, {NY}},\n\tAuthor = {M J Kahana},\n\tPublisher = {Oxford University "
          "Press},\n\tTitle = {Foundations of human memory},\n\tYear = {2012}}")
_SIBLING = Path(sys.executable).parent / "cdlbib"
CDLBIB = str(_SIBLING) if _SIBLING.exists() else shutil.which("cdlbib")


@pytest.fixture(autouse=True, scope="module")
def real_data_folder_untouched():
    yield
    conftest.no_real_library_touched()


@pytest.fixture
def site(tmp_path, monkeypatch):
    web.isolate(monkeypatch, tmp_path)
    ws = web.make_library(tmp_path / "library", ZOLL90, KAHA12)
    log = []
    running, client = web.start(ws, log=log.append)
    client.ws, client.log = ws, log
    yield client
    running.stop()
    assert running.app.worker.overlaps == 0


# --- the session and the first job --------------------------------------------------------------

def test_the_first_job_prepares_the_library_and_the_session_names_it(site):
    session = site.ok("get", "/api/session")
    assert session["version"] == __version__ and session["root"] == str(site.ws.root) and session["bib"] == str(site.ws.bib)
    assert session["managed"] is False and session["ask"] is False and session["identity"] is None
    assert session["chosen_by"] == dict(prompts.CHOSEN_BY) and session["probes"] == list(api.PROBES)
    assert "cdlbib export" in session["no_bbl"] and "--bbl" in session["no_bbl"]
    lines = []
    result, error = site.follow(session["prepare"], lines)
    assert error is None and result["entries"] == 2 and lines            # api.prepare's own lines
    web.wait_idle(site.running)
    assert site.running.app.worker.history[0][0] == "prepare"


def test_a_job_is_polled_from_any_line_and_reports_a_typed_error(site):
    web.wait_idle(site.running)
    response = site.raw("POST", "/api/check/keys", site.headers(post=True), json={"keys": ["Nope99"]})
    assert response.status_code == 202 and set(response.json()) == {"job"}
    job = response.json()["job"]
    deadline = time.monotonic() + 120
    while True:
        view = site.raw("GET", f"/api/jobs/{job}", site.headers()).json()["result"]
        if view["done"] or time.monotonic() > deadline:
            break
    assert view["done"] and "result" not in view and view["label"] == "POST /api/check/keys"
    assert view["error"]["kind"] == "GateFailed" and "absent from the bibliography" in view["error"]["message"]
    again = site.raw("GET", f"/api/jobs/{job}", site.headers(), params={"after": 0}).json()["result"]
    assert again["lines"] == view["lines"] and again["next"] == len(view["lines"])
    tail = site.raw("GET", f"/api/jobs/{job}", site.headers(), params={"after": again["next"]}).json()["result"]
    assert tail["lines"] == [] and tail["next"] == again["next"] and tail["done"]
    beyond = site.raw("GET", f"/api/jobs/{job}", site.headers(), params={"after": 10 ** 6}).json()["result"]
    assert beyond["lines"] == []
    assert site.raw("GET", f"/api/jobs/{job}", site.headers(), params={"after": "x"}).status_code == 400


def test_a_job_keeps_its_lines_in_order_and_a_failure_does_not_stop_the_worker():
    worker = jobs.Worker(lambda exc: {"kind": type(exc).__name__, "message": str(exc)})
    worker.start()
    try:
        def talk(say):
            for number in range(5):
                say(f"line {number}\nand its second half")
            return "done"
        first = worker.submit("talk", talk)
        second = worker.submit("fail", lambda say: 1 / 0)
        third = worker.submit("after", lambda say: "still running")
        assert third.wait(30) and first.done and second.done
        assert first.view(0)["lines"] == [text for n in range(5) for text in (f"line {n}", "and its second half")]
        assert first.view(8)["lines"] == ["line 4", "and its second half"] and first.view(0)["result"] == "done"
        assert second.view(0)["error"] == {"kind": "ZeroDivisionError", "message": "division by zero"}
        assert third.view(0)["result"] == "still running" and worker.overlaps == 0
        assert [label for label, _, _ in worker.history] == ["talk", "fail", "after"]
    finally:
        worker.stop()


def test_requests_that_arrive_together_are_run_one_at_a_time(site):
    web.wait_idle(site.running)
    edited = ZOLL90.replace("{27}", "{28}")

    def one(number):
        kind = number % 6
        if kind == 0:
            return site.get("/api/entries")
        if kind == 1:
            return site.get("/api/entry", key="Zoll90")
        if kind == 2:
            return site.post("/api/edit/preview", {"key": "Zoll90", "raw": edited})
        if kind == 3:
            return site.post("/api/check/format")
        if kind == 4:
            return site.get("/api/search", q="memory")
        return site.get("/api/state")

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        answers = list(pool.map(one, range(48)))
    assert all(error is None for _, error in answers)
    web.wait_idle(site.running)
    worker = site.running.app.worker
    history = sorted(worker.history, key=lambda item: item[1])
    assert worker.overlaps == 0 and len(history) >= 49                     # prepare, then every request
    assert all(earlier[2] <= later[1] for earlier, later in zip(history, history[1:]))   # no two intervals overlap
    assert {label for label, _, _ in history} >= {"prepare", "GET /api/entries", "POST /api/edit/preview",
                                                  "POST /api/check/format", "GET /api/search", "GET /api/state"}
    assert site.ws.bib.read_text(encoding="utf-8") == ZOLL90 + "\n\n" + KAHA12 + "\n\n"     # previews wrote nothing


def test_errors_of_the_core_are_typed_by_their_class(site):
    result, error = site.get("/api/entry", key="Nope99")
    assert result is None and error["kind"] == "CdlbibError" and "Nope99" in error["message"]
    preview = site.ok("post", "/api/edit/preview", {"key": "Zoll90", "raw": ZOLL90.replace("{27}", "{28}")})
    site.ws.bib.write_text(site.ws.bib.read_text(encoding="utf-8").replace("{1990}", "{1991}"), encoding="utf-8")
    result, error = site.post("/api/edit/save", {"preview": preview["preview"]})
    assert error["kind"] == "EditRefused" and isinstance(error["problems"], list)
    result, error = site.post("/api/send")
    assert error["kind"] == "PublishRefused" and error["needs_fork"] is False and "needs_confirmation" not in error
    result, error = site.get("/api/backups")
    assert error["kind"] == "CdlbibError" and "has not downloaded a library yet" in error["message"]
    result, error = site.post("/api/update")
    assert error["kind"] == "CdlbibError" and "nothing to update" in error["message"]
    assert routes.failure(ValueError("boom")) == {"kind": "InternalError", "message": "ValueError: boom"}
    assert routes.failure(routes.Bad("no")) == {"kind": "BadRequest", "message": "no"}
    assert routes.failure(store.Missing("gone")) == {"kind": "NotFound", "message": "gone"}


def test_the_store_issues_random_ids_keeps_kinds_apart_and_removes_its_folder(tmp_path):
    held = store.Store()
    try:
        assert held.folder.stat().st_mode & 0o077 == 0
        ids = {held.put("proposal", {"n": n}) for n in range(200)}
        assert len(ids) == 200 and all(store.ID.match(found) for found in ids)
        one = next(iter(ids))
        assert held.get("proposal", one)["n"] in range(200)
        for kind, found in (("pdf", one), ("proposal", "A" * 22), ("proposal", "../x"), ("proposal", None), ("proposal", 7)):
            with pytest.raises(store.Missing):
                held.get(kind, found)
        folder = held.new_folder()
        kept = held.put("pdf", {"folder": folder})
        assert folder.parent == held.folder and folder.stat().st_mode & 0o077 == 0
        held.drop("proposal", kept)                       # the wrong kind drops nothing
        assert folder.exists()
        held.drop("pdf", kept)
        assert not folder.exists()
        first = held.put("search", [])
        for _ in range(store.KEPT + 5):
            held.put("search", [])
        with pytest.raises(store.Missing):                # the oldest made room
            held.get("search", first)
    finally:
        held.close()
    assert not held.folder.exists()


# --- the command --------------------------------------------------------------------------------

def _serve(tmp_path, *arguments, before=()):
    """`cdlbib [before] --library LIB web --no-open [arguments]` as a real process; (process, address)."""
    env = dict(os.environ, **web.isolated_environment(tmp_path / "env"))
    for name in web.unset():
        env.pop(name, None)
    library = web.make_library(tmp_path / "library", ZOLL90)
    process = subprocess.Popen([CDLBIB, *before, "--library", str(library.root), "web", "--no-open", *arguments],
                               cwd=tmp_path, env=env, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    said, address = [], None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and process.poll() is None:
        line = process.stderr.readline()
        said.append(line)
        found = re.match(r"open: (http://127\.0\.0\.1:(\d+)/#token=([A-Za-z0-9_-]+))$", line.strip())
        if found:
            address = found
            said.append(process.stderr.readline())      # the line that follows the address
            break
    return process, address, said


def test_the_command_prints_the_address_serves_until_interrupted_and_cleans_up(tmp_path):
    import requests
    process, address, said = _serve(tmp_path)
    try:
        assert address, said
        origin, token = f"http://127.0.0.1:{address.group(2)}", address.group(3)
        http = requests.Session()
        http.trust_env = False
        session = http.get(origin + "/api/session", headers={web.TOKEN: token}).json()["result"]
        assert session["root"] == str((tmp_path / "library").resolve()) and session["ask"] is False
        assert http.get(origin + "/api/session").status_code == 401
        assert http.get(origin + "/").status_code == 200
    finally:
        process.send_signal(signal.SIGINT)
        out, err = process.communicate(timeout=60)
    assert process.returncode == 0, err
    assert "Traceback" not in err and token not in err and token not in out      # only the one printed address held it
    assert "GET (no route) 401" in err                                            # a refusal is logged, without the token
    assert any("this computer only" in line for line in said + [err])


def test_ask_is_carried_into_the_session_and_a_port_in_use_is_an_error(tmp_path):
    import requests
    process, address, said = _serve(tmp_path, before=("--ask",))
    try:
        assert address, said
        http = requests.Session()
        http.trust_env = False
        port = address.group(2)
        assert http.get(f"http://127.0.0.1:{port}/api/session", headers={web.TOKEN: address.group(3)}).json()["result"]["ask"] is True
        second = subprocess.run([CDLBIB, "--library", str(tmp_path / "library"), "web", "--no-open", "--port", port],
                                cwd=tmp_path, capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, **web.isolated_environment(tmp_path / "env2")))
        assert second.returncode == 1 and "could not listen on 127.0.0.1:" + port in second.stderr
        assert "Traceback" not in second.stderr
    finally:
        process.send_signal(signal.SIGINT)
        process.communicate(timeout=60)


def test_the_command_is_listed_with_its_options():
    done = subprocess.run([CDLBIB, "web", "--help"], capture_output=True, text=True, timeout=60)
    text = conftest.plain_output(done).stdout
    assert done.returncode == 0 and "--port" in text and "--no-open" in text


# --- a missing optional package, from inside a job -----------------------------------------------

def test_a_missing_package_is_installed_from_inside_a_job_or_asked_about_first(tmp_path):
    if not shutil.which("uv"):
        pytest.skip("uv is needed to build the scratch environment without the pdf extra")
    if not pdfs.pdflatex():
        pytest.skip("pdflatex is not installed: the test PDF cannot be typeset")
    python = tmp_path / "e" / "bin" / "python"
    subprocess.run(["uv", "venv", "-q", str(tmp_path / "e"), "--python", sys.executable], check=True)
    built = subprocess.run(["uv", "pip", "install", "-q", "--python", str(python), "-e", f"{ROOT}[research]"],
                           capture_output=True, text=True)
    if built.returncode != 0:
        pytest.skip("the scratch environment could not be built (no network?): " + built.stderr.strip()[-200:])
    pdf = pdfs.build("doi", tmp_path / "pdf")
    env = dict(os.environ, CDLBIB_HOME=str(tmp_path / "data"))      # HOME stays: uv's package cache is there

    def drive(mode):
        library = web.make_library(tmp_path / f"library-{mode}", ZOLL90)
        done = subprocess.run([str(python), str(ROOT / "tests" / "web_dependency_driver.py"), str(library.root), str(pdf), mode],
                              capture_output=True, text=True, timeout=600, env=env, cwd=tmp_path)
        assert done.returncode == 0, done.stderr[-3000:]
        return json.loads(done.stdout.strip().splitlines()[-1])

    asked = drive("ask")
    assert asked["missing_at_start"] and asked["session_ask"] is True
    first = asked["first"]["error"]
    assert first["kind"] == "MissingDependency" and first["needs_confirmation"] == "install"
    assert first["package"] == "pypdfium2" and first["extra"] == "pdf" and "Install it now?" in first["question"]
    assert asked["missing_after_first"] and not asked["first"]["lines"]            # nothing was installed unasked
    second = asked["second"]
    if second["error"] and "install failed" in second["error"]["message"]:
        pytest.skip("pypdfium2 could not be installed here (no network?); the question was asked as it should be")
    assert second["error"] is None and second["png"] == "89504e470d0a1a0a" and second["bytes"] > 1000
    assert any(line.startswith("installing pypdfium2 (needed for: ") for line in second["lines"])

    subprocess.run(["uv", "pip", "uninstall", "-q", "--python", str(python), "pypdfium2"], check=True)
    default = drive("default")
    assert default["missing_at_start"] and default["session_ask"] is False
    assert default["first"]["error"] is None and default["first"]["png"] == "89504e470d0a1a0a"
    assert any(line.startswith("installing pypdfium2 (needed for: ") for line in default["first"]["lines"])


# --- the page's files ---------------------------------------------------------------------------

NAMED_COLOURS = ("white", "black", "red", "green", "blue", "gray", "grey", "silver", "yellow", "orange", "purple", "pink",
                 "brown", "navy", "teal", "maroon", "olive", "lime", "aqua", "cyan", "magenta", "fuchsia", "gold", "beige",
                 "ivory", "crimson", "salmon", "tomato", "coral", "khaki", "indigo", "violet", "tan", "darkgreen",
                 "lightgray", "lightgrey", "darkgray", "darkgrey", "whitesmoke", "gainsboro", "dimgray", "slategray")


def test_no_web_file_names_a_colour():
    """Every colour is a variable of the theme sheet (cdlbib.theme): no hex, rgb(), hsl() or
    named colour in the page's files, in their style rules or in script."""
    for path in sorted(STATIC.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", text), path.name
        assert not re.search(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", text), path.name
        if path.suffix == ".css":
            rules = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
            for name, value in re.findall(r"([a-z-]+)\s*:\s*([^;{}]+)[;}]", rules):
                assert not re.search(r"\b(?:" + "|".join(NAMED_COLOURS) + r")\b", value), (name, value)
            used = set(re.findall(r"var\((--[a-z-]+)", rules))
            roles = {"--cdl-" + role.replace("_", "-") for role in theme.LIGHT}
            assert {name for name in used if name.startswith("--cdl-")} <= roles
            assert {name for name in used if not name.startswith("--cdl-")} <= {"--row", "--gap", "--radius"}
        if path.suffix == ".js":
            assert not re.search(r"\.style\.(?:color|background|border|outline|fill|stroke)", text), path.name
            assert not re.search(r"""["'](?:""" + "|".join(NAMED_COLOURS) + r""")["']""", text), path.name
    sheet = theme.stylesheet()
    assert ":root {" in sheet and "prefers-color-scheme: dark" in sheet and ':root[data-theme="dark"]' in sheet
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "color-scheme: light dark" in css and "@media (max-width: 480px)" in css and ":focus-visible" in css
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('href="/theme.css"') < html.index('href="/app.css"')
    assert 'name="viewport"' in html and 'role="alert"' in html and 'aria-live="assertive"' in html and 'lang="en"' in html


def test_the_static_files_are_packaged():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"web/static/*"' in text and '"web/static/js/*"' in text
    from importlib import resources
    folder = resources.files("cdlbib.web") / "static"
    for name, _ in server.STATIC.values():
        assert (folder / name).is_file(), name
