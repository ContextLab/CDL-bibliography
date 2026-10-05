"""The web interface's server against hostile requests: the real server on loopback, a
library in tmp_path, requests sent with `requests`, http.client and raw sockets. Nothing is
replaced by a stand-in."""
import http.client
import json
import re
import socket
from pathlib import Path

import pytest

import conftest
import web_support as web
from cdlbib import api
from cdlbib.web import routes, server

ZOLL90 = conftest.ZOLL90
STATIC = Path(server.__file__).parent / "static"
FORBIDDEN = ("citations", "database", "reference", "ledger", "upstream", "fork", "outfile", "autofix", "engine",
             "_test_inside_own_fork", "path", "mailto", "reviewer", "force", "inputs", "out", "paper", "all_entries")


@pytest.fixture(autouse=True, scope="module")
def real_data_folder_untouched():
    yield
    conftest.no_real_library_touched()


@pytest.fixture
def site(tmp_path, monkeypatch):
    web.isolate(monkeypatch, tmp_path)
    ws = web.make_library(tmp_path / "library", ZOLL90)
    log = []
    running, client = web.start(ws, log=log.append)
    web.wait_idle(running)
    client.ws, client.log = ws, log
    yield client
    running.stop()
    assert running.app.worker.overlaps == 0
    assert not running.app.store.folder.exists()          # the run's private folder goes with the server


def raw_request(client, text):
    """Send bytes as they are; the status line and the whole answer."""
    with socket.create_connection(("127.0.0.1", client.running.port), timeout=20) as sock:
        sock.sendall(text.encode("latin-1") if isinstance(text, str) else text)
        sock.settimeout(20)
        data = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
    head = data.split(b"\r\n", 1)[0].decode("latin-1")
    return (int(head.split()[1]) if head.startswith("HTTP/") else None), data


def plain(client, method, path, headers=None, body=None):
    """One request through http.client, whose path is sent exactly as written."""
    connection = http.client.HTTPConnection("127.0.0.1", client.running.port, timeout=30)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def error_of(response):
    return response.json()["error"]


# --- where it listens ---------------------------------------------------------------------------

def test_it_listens_on_loopback_only_and_the_address_carries_the_token_in_its_fragment(site):
    assert site.running.httpd.server_address[0] == "127.0.0.1"
    assert site.running.url == f"http://127.0.0.1:{site.running.port}/#token={site.token}"
    assert len(site.token) >= 40 and re.fullmatch(r"[A-Za-z0-9_-]+", site.token)
    other, _ = web.start(site.ws)
    try:
        assert other.app.token != site.token
    finally:
        other.stop()


# --- the token ----------------------------------------------------------------------------------

@pytest.mark.parametrize("change", ["missing", "wrong", "prefix", "longer", "empty", "lowercased", "bearer"])
def test_an_api_request_without_exactly_the_token_is_refused(site, change):
    token = {"missing": None, "wrong": "x" * len(site.token), "prefix": site.token[:-1], "longer": site.token + "a",
             "empty": "", "lowercased": site.token.swapcase(), "bearer": "Bearer " + site.token}[change]
    headers = {} if token is None else {web.TOKEN: token}
    for path in ("/api/session", "/api/entries", "/api/jobs/" + "a" * 22):
        response = site.raw("GET", path, headers)
        assert response.status_code == 401 and error_of(response)["kind"] == "Unauthorized"
    response = site.raw("POST", "/api/check/format", dict(headers, Origin=site.origin), json={})
    assert response.status_code == 401


def test_the_token_is_not_accepted_in_the_address_a_cookie_or_the_authorization_header(site):
    assert site.raw("GET", "/api/session", params={"token": site.token}).status_code == 401
    assert site.raw("GET", f"/api/session?X-CDLBIB-Token={site.token}").status_code == 401
    assert site.raw("GET", "/api/session", {"Cookie": f"token={site.token}"}).status_code == 401
    assert site.raw("GET", "/api/session", {"Authorization": f"Bearer {site.token}"}).status_code == 401
    # with the header as well, a token in the address is an argument nobody declared
    response = site.raw("GET", "/api/session", site.headers(), params={"token": site.token})
    assert response.status_code == 400 and "token" in error_of(response)["message"]
    assert site.token not in response.text


def test_the_static_page_needs_no_token_and_holds_none(site):
    for path in ("/", "/index.html", "/app.css", "/theme.css", "/js/main.js", "/js/api.js"):
        response = site.raw("GET", path)
        assert response.status_code == 200 and site.token not in response.text


# --- Host ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("host", ["evil.example", "evil.example:{port}", "127.0.0.1", "127.0.0.1:1", "127.0.0.1:{port}0",
                                  "127.0.0.1.evil.example:{port}", "localhost.evil.example:{port}", "[::1]:{port}",
                                  "0.0.0.0:{port}", "LOCALHOST:{port}", "localhost", "127.0.0.1:{port}.", "rebind.test:{port}",
                                  " 127.0.0.1:{port}x", ""])
def test_a_request_for_any_other_host_is_refused(site, host):
    host = host.format(port=site.running.port)
    for path, headers in (("/", {}), ("/app.css", {}), ("/api/session", site.headers())):
        status, _, body = plain(site, "GET", path, dict(headers, Host=host))
        assert status == 403 and json.loads(body)["error"]["kind"] == "Forbidden", (host, path)
    status, _, _ = plain(site, "POST", "/api/check/format", dict(site.headers(post=True), Host=host,
                                                                 **{"Content-Type": "application/json"}), body="{}")
    assert status == 403


def test_both_loopback_names_are_served_and_a_request_without_a_host_is_not(site):
    port = site.running.port
    for host in (f"127.0.0.1:{port}", f"localhost:{port}"):
        assert plain(site, "GET", "/api/session", dict(site.headers(), Host=host))[0] == 200
    status, data = raw_request(site, f"GET /api/session HTTP/1.0\r\n{web.TOKEN}: {site.token}\r\n\r\n")
    assert status == 403
    status, data = raw_request(site, f"GET /api/session HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nHost: evil.example\r\n"
                                     f"{web.TOKEN}: {site.token}\r\nConnection: close\r\n\r\n")
    assert status == 403


# --- Origin, method, content type ---------------------------------------------------------------

@pytest.mark.parametrize("origin", [None, "null", "http://evil.example", "https://127.0.0.1:{port}", "http://127.0.0.1",
                                    "http://127.0.0.1:{port}0", "http://localhost:{port}", "http://127.0.0.1:{port}/",
                                    "http://127.0.0.1:{port}.evil.example", "file://", ""])
def test_a_change_needs_this_servers_own_origin(site, origin, tmp_path):
    before = site.ws.bib.read_bytes()
    origin = origin.format(port=site.running.port) if origin is not None else None
    headers = {web.TOKEN: site.token}
    if origin is not None:
        headers["Origin"] = origin
    for path, body in (("/api/check/format", {}), ("/api/edit/preview", {"key": None, "raw": ZOLL90}),
                       ("/api/tex/link", {}), ("/api/send", {}), ("/api/undo", {})):
        response = site.raw("POST", path, headers, json=body)
        assert response.status_code == 403 and error_of(response)["kind"] == "Forbidden", (origin, path)
    response = site.raw("POST", "/api/pdf/upload", dict(headers, **{"Content-Type": "application/pdf"}), data=b"%PDF-1.4\n")
    assert response.status_code == 403
    assert site.ws.bib.read_bytes() == before and not (tmp_path / "texmf" / "bibtex").exists()


def test_the_origin_must_be_the_host_that_was_asked(site):
    port = site.running.port
    ok = dict(site.headers(), **{"Content-Type": "application/json"})
    assert plain(site, "POST", "/api/check/format", dict(ok, Host=f"localhost:{port}", Origin=f"http://localhost:{port}"),
                 body="{}")[0] in (200, 202)
    assert plain(site, "POST", "/api/check/format", dict(ok, Host=f"localhost:{port}", Origin=f"http://127.0.0.1:{port}"),
                 body="{}")[0] == 403
    # a read with a foreign Origin, or one a browser marks as coming from another site, is refused too
    assert site.raw("GET", "/api/entries", site.headers(Origin="http://evil.example")).status_code == 403
    assert site.raw("GET", "/api/entries", site.headers(**{"Sec-Fetch-Site": "cross-site"})).status_code == 403
    assert site.raw("GET", "/api/entries", site.headers(**{"Sec-Fetch-Site": "same-site"})).status_code == 403
    assert site.raw("GET", "/api/entries", site.headers(**{"Sec-Fetch-Site": "same-origin"})).status_code == 200


def test_a_change_is_never_made_by_get_and_other_methods_are_refused(site):
    changing = [route for route in routes.ROUTES if route.method == "POST"]
    assert len(changing) > 25
    for route in changing:
        path = route.path.replace("{id}", "a" * 22)
        response = site.raw("GET", path, site.headers())
        assert response.status_code == 405 and response.headers["Allow"] == "POST", path
    for route in routes.ROUTES:
        if route.method == "GET":
            path = route.path.replace("{id}", "a" * 22)
            assert site.raw("POST", path, site.headers(post=True), json={}).status_code == 405, path
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "TRACE"):
        for path in ("/api/edit/save", "/api/entries", "/"):
            response = site.raw(method, path, site.headers(post=True))
            assert response.status_code == 405, (method, path)
            assert not [name for name in response.headers if name.lower().startswith("access-control")]


def test_a_preflight_gets_no_permission(site):
    response = site.raw("OPTIONS", "/api/send", {"Origin": "http://evil.example", "Access-Control-Request-Method": "POST",
                                                 "Access-Control-Request-Headers": "x-cdlbib-token, content-type"})
    assert response.status_code == 405
    assert not [name for name in response.headers if name.lower().startswith("access-control")]


@pytest.mark.parametrize("kind", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x",
                                  "application/jsonx", "text/json", None])
def test_a_change_must_be_json(site, kind):
    headers = site.headers(post=True)
    if kind:
        headers["Content-Type"] = kind
    response = site.raw("POST", "/api/edit/preview", headers, data=json.dumps({"key": None, "raw": ZOLL90}))
    assert response.status_code == 415 and error_of(response)["kind"] == "UnsupportedMediaType"
    assert site.raw("POST", "/api/pdf/upload", dict(headers, **{"Content-Type": kind or "text/plain"}),
                    data=b"%PDF-1.4\n").status_code == 415


# --- bodies -------------------------------------------------------------------------------------

def test_an_oversize_body_is_refused_before_it_is_read(site):
    big = json.dumps({"key": None, "raw": "x" * (server.MAX_JSON + 10)})
    response = site.raw("POST", "/api/edit/preview", site.headers(post=True, **{"Content-Type": "application/json"}), data=big)
    assert response.status_code == 413 and error_of(response)["kind"] == "TooLarge"
    port = site.running.port
    head = (f"POST /api/pdf/upload HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\n"
            f"{web.TOKEN}: {site.token}\r\nContent-Type: application/pdf\r\n")
    # a length beyond the cap is refused at once: no byte of the body is sent here, and the answer still comes
    status, data = raw_request(site, head + f"Content-Length: {10 ** 11}\r\n\r\n%PDF-")
    assert status == 413 and b"TooLarge" in data
    status, _ = raw_request(site, head + f"Content-Length: {server.MAX_UPLOAD + 1}\r\nConnection: close\r\n\r\n")
    assert status == 413
    for length in ("-1", "abc", "1" * 40, ""):
        status, _ = raw_request(site, head + f"Content-Length: {length}\r\n\r\n")
        assert status in (400, 411), length
    status, _ = raw_request(site, head + "Transfer-Encoding: chunked\r\n\r\n5\r\n%PDF-\r\n0\r\n\r\n")
    assert status == 400
    assert not list(site.running.app.store.folder.iterdir())         # nothing was stored


@pytest.mark.parametrize("body", ['[]', '"text"', '42', 'null', '{"key": NaN}', '{"raw": Infinity}', '{', '', '\xff\xfe',
                                  '{"key": null, "raw": ' + "[" * 40 + "]" * 40 + '}',
                                  '{"a":' * 30 + '1' + '}' * 30,
                                  "[" * 200_000])
def test_json_that_is_not_a_shallow_object_is_refused(site, body):
    response = site.raw("POST", "/api/edit/preview", site.headers(post=True, **{"Content-Type": "application/json"}),
                        data=body.encode("latin-1"))
    assert response.status_code == 400 and error_of(response)["kind"] == "BadRequest"


def test_nesting_is_counted_outside_strings():
    assert server.nesting('{"a": "[[[[{{{{"}') == 1 and server.nesting('{"a": [{"b": []}]}') == 4
    assert server.nesting('{"a": "\\"[[["}') == 1 and server.nesting("") == 0


# --- addresses ----------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/../server.py", "/js/../../server.py", "/js/../index.html", "/%2e%2e/server.py",
                                  "/js/%2e%2e/%2e%2e/routes.py", "/static/index.html", "//etc/passwd", "/js/main.js/",
                                  "/js/", "/js", "/js/main", "/js/main.js%00.css", "/index.html?x=1", "/app.css?",
                                  "/..%2f..%2f..%2fetc%2fpasswd", "/js/..\\..\\server.py", "/favicon.ico", "/robots.txt",
                                  "/server.py", "/routes.py", "/js/nothing.js", "/theme.css/", "/api", "/api/",
                                  "http://evil.example/", "/js/main.js#x"])
def test_only_the_named_static_files_are_served(site, path):
    status, headers, body = plain(site, "GET", path, site.headers())
    assert status in (400, 403, 404), path      # (403: http.client takes the Host of an absolute address from it)
    assert b"def " not in body and b"root:" not in body
    for name, value in server.HEADERS.items():
        assert headers[name] == value


def test_the_static_table_names_files_of_the_packaged_folder_only(site):
    assert set(server.STATIC) == {"/", "/index.html", "/app.css"} | {f"/js/{name}.js" for name in server.MODULES}
    on_disk = {path.relative_to(STATIC).as_posix() for path in STATIC.rglob("*") if path.is_file()}
    assert on_disk == {name for name, _ in server.STATIC.values()}       # nothing unlisted is shipped, nothing listed is missing
    for path, (name, kind) in server.STATIC.items():
        response = site.raw("GET", path)
        assert response.status_code == 200 and response.content == (STATIC / name).read_bytes()
        assert response.headers["Content-Type"] == kind
    theme = site.raw("GET", "/theme.css")
    from cdlbib import theme as palette
    assert theme.text == palette.stylesheet() and theme.headers["Content-Type"].startswith("text/css")


@pytest.mark.parametrize("path", ["/api/jobs/../../etc/passwd", "/api/jobs/..", "/api/jobs/%2e%2e", "/api/jobs/" + "a" * 21,
                                  "/api/jobs/" + "a" * 23, "/api/jobs/" + "a" * 21 + "/", "/api/pdf/../file",
                                  "/api/pdf/" + "." * 22 + "/file", "/api/pdf/" + "a" * 22 + "/file/..",
                                  "/api/export/" + "%2e" * 22 + "/file", "/api/nothing", "/api/entries/", "/api//entries",
                                  "/api/entries/extra", "/API/entries"])
def test_an_address_that_is_no_route_is_not_found(site, path):
    status, _, body = plain(site, "GET", path, site.headers())
    assert status == 404 and json.loads(body)["error"]["kind"] == "NotFound"


def test_an_id_that_was_never_issued_or_is_of_another_kind_is_not_found(site):
    unknown = "A" * 22
    assert site.raw("GET", f"/api/jobs/{unknown}", site.headers()).status_code == 404
    assert site.raw("GET", f"/api/pdf/{unknown}/file", site.headers()).status_code == 404
    assert site.raw("GET", f"/api/export/{unknown}/file", site.headers()).status_code == 404
    result, error = site.get("/api/proposal", proposal=unknown)
    assert error["kind"] == "NotFound"
    for path, body in (("/api/edit/save", {"preview": unknown}), ("/api/proposal/accept", {"proposal": unknown}),
                       ("/api/pdf/read", {"pdf": unknown}), ("/api/export/run", {"bundle": unknown})
                       ):
        result, error = site.post(path, body)
        assert result is None and error["kind"] == "NotFound", path
    # an id of one kind is not an id of another
    preview = site.ok("post", "/api/edit/preview", {"key": "Zoll90", "raw": ZOLL90})["preview"]
    for path, body in (("/api/proposal/accept", {"proposal": preview}), ("/api/pdf/read", {"pdf": preview})):
        assert site.post(path, body)[1]["kind"] == "NotFound"
    assert site.raw("GET", f"/api/pdf/{preview}/file", site.headers()).status_code == 404
    for bad in ("../../etc/passwd", "a" * 21, "a" * 22 + "/..", "", 7, None, ["a" * 22], {"id": 1}):
        response = site.raw("POST", "/api/edit/save", site.headers(post=True), json={"preview": bad})
        assert response.status_code == 400, bad


# --- arguments ----------------------------------------------------------------------------------

@pytest.mark.parametrize("name", FORBIDDEN)
def test_arguments_that_steer_a_send_or_name_a_file_are_refused_by_name(site, name):
    for path, body in (("/api/send", {}), ("/api/check/keys", {"keys": ["Zoll90"]}), ("/api/check/changed", {}),
                       ("/api/approve", {"key": "Zoll90", "fingerprint": "v2:0", "source": "s", "note": "n"}),
                       ("/api/export/run", {"bundle": "a" * 22}), ("/api/update", {}), ("/api/tex/link", {})):
        response = site.raw("POST", path, site.headers(post=True), json=dict(body, **{name: "x"}))
        assert response.status_code == 400 and name in error_of(response)["message"], (path, name)
    response = site.raw("GET", "/api/review-queue", site.headers(), params={name: "x"})
    assert response.status_code == 400 and name in error_of(response)["message"]


def test_no_route_declares_a_forbidden_or_path_argument_and_each_names_real_api_functions():
    declared = {name for route in routes.ROUTES for name in route.args}
    assert not declared & routes.NEVER and not [name for name in declared if name.startswith("_")]
    assert not [name for name in declared if any(word in name for word in ("path", "file", "folder", "dir"))]
    assert set(FORBIDDEN) - {"_test_inside_own_fork"} <= routes.NEVER
    for route in routes.ROUTES:
        for name in re.split(r"[,|]\s*", route.api):
            assert not name.strip() or callable(getattr(api, name.strip())), (route.path, name)
        assert bool(route.api) != route.direct, route.path       # exactly the routes that call the api go to the worker
    assert len({(route.method, route.path) for route in routes.ROUTES}) == len(routes.ROUTES)


def test_the_web_package_sends_only_through_send_checked_and_imports_only_the_front_end_boundary():
    allowed = {"api", "deps", "prompts", "workspace", "theme", "errors", "__version__"}
    for path in Path(server.__file__).parent.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "api.send(" not in text and "check_citations" not in text and "complete." not in text, path.name
        for line in text.splitlines():
            found = re.match(r"\s*from \.\.(\w*) import (.+)", line)
            if found:
                names = {found.group(1)} if found.group(1) else {name.strip() for name in found.group(2).split(",")}
                assert names <= allowed, (path.name, line)
            assert not re.match(r"\s*(from|import) cdlbib", line), (path.name, line)
    text = (Path(server.__file__).parent / "routes.py").read_text(encoding="utf-8")
    assert text.count("api.send_checked(") == 1 and "summary=" in text and "allow_fork_creation=" in text


def test_unknown_arguments_and_wrong_types_are_refused(site):
    cases = [("/api/edit/preview", {"key": None, "raw": ZOLL90, "extra": 1}, "extra"),
             ("/api/edit/preview", {"key": "has space", "raw": ZOLL90}, "key"),
             ("/api/edit/preview", {"key": None, "raw": 5}, "raw"),
             ("/api/edit/preview", {"key": None}, "raw"),
             ("/api/edit/preview", {"key": None, "raw": "x" * 100_001}, "raw"),
             ("/api/edit/preview", {"key": None, "raw": "a\x00b"}, "raw"),
             ("/api/check/keys", {"keys": "Zoll90 Other"}, "keys"),
             ("/api/check/keys", {"keys": [1, 2]}, "keys"),
             ("/api/check/keys", {"keys": ["k"] * 501}, "keys"),
             ("/api/check/keys", {"keys": []}, "keys"),
             ("/api/add/search", {"title": "t", "year": "19x9"}, "year"),
             ("/api/add/manual", {"entry_type": "article", "fields": {"bad name": "x"}}, "fields"),
             ("/api/add/manual", {"entry_type": "article", "fields": {"title": {"nested": 1}}}, "fields"),
             ("/api/add/manual", {"entry_type": "../x", "fields": {}}, "entry_type"),
             ("/api/pdf/model", {"pdf": "a" * 22, "route": "other"}, "route"),
             ("/api/update/decide", {"decision": "a" * 22, "choice": "merge"}, "choice"),
             ("/api/undo", {"stamp": "../../x"}, "stamp"),
             ("/api/undo", {"stamp": "/etc"}, "stamp"),
             ("/api/setup/check", {"probe": "everything"}, "probe"),
             ("/api/tex/link", {"replace": "yes"}, "replace"),
             ("/api/send", {"summary": "x" * 101}, "summary"),
             ("/api/send", {"summary": ["a"]}, "summary"),
             ("/api/add/choose", {"search": "a" * 22, "index": -1}, "index"),
             ("/api/add/choose", {"search": "a" * 22, "index": True}, "index")]
    for path, body, name in cases:
        response = site.raw("POST", path, site.headers(post=True), json=body)
        assert response.status_code == 400 and name in error_of(response)["message"], (path, body)
    # a JSON route takes nothing from its address
    response = site.raw("POST", "/api/send?summary=x", site.headers(post=True), json={})
    assert response.status_code == 400
    assert site.raw("GET", "/api/entry", site.headers(), params={"key": "Zoll90", "raw": "x"}).status_code == 400
    assert site.raw("GET", "/api/entry", site.headers()).status_code == 400
    assert site.raw("GET", "/api/entries?" + "a=1&" * 100, site.headers()).status_code == 400
    assert site.raw("GET", "/api/entries?" + "x" * 5000, site.headers()).status_code in (400, 414)
    assert site.raw("GET", "/api/entries", site.headers(), data="{}").status_code == 400      # a GET has no body


# --- uploads ------------------------------------------------------------------------------------

def test_an_upload_that_is_not_a_pdf_is_refused_and_nothing_is_kept(site):
    store = site.running.app.store.folder
    for body in (b"", b"GIF89a", b"<html>%PDF-", b" %PDF-1.4", b"PK\x03\x04", b"%PDF"):
        result, error = site.upload("/api/pdf/upload", body, "application/pdf")
        assert result is None and error["kind"] == "BadRequest" and "%PDF-" in error["message"]
    assert not list(store.iterdir())
    assert site.raw("POST", "/api/pdf/upload", site.headers(post=True, **{"Content-Type": "application/pdf"}),
                    data=b"%PDF-1.4\n", params={"name": "x.pdf"}).status_code == 400       # no argument names the file
    result, error = site.upload("/api/pdf/upload", b"%PDF-1.4\nnot really a pdf\n", "application/pdf")
    assert error is None and re.fullmatch(r"[A-Za-z0-9_-]{22}", result["pdf"])
    (folder,) = store.iterdir()
    assert [path.name for path in folder.iterdir()] == ["upload.pdf"] and folder.stat().st_mode & 0o077 == 0
    assert store.stat().st_mode & 0o077 == 0
    # what the reader makes of it is a typed problem, not a failure of the server
    read = site.ok("post", "/api/pdf/read", {"pdf": result["pdf"]})
    assert read["problem"] and "path" not in read and str(store) not in json.dumps(read)


def test_a_manuscript_upload_keeps_a_plain_name_only_and_never_leaves_its_folder(site):
    store = site.running.app.store.folder
    kind = "application/octet-stream"
    first = site.ok("upload", "/api/export/upload", b"\\documentclass{article}", kind, name="main.tex")
    bundle = first["bundle"]
    assert first["name"] == "main.tex"
    for declared in ("../../evil.tex", "/etc/passwd.tex", "..\\evil.tex", "a/b.tex", ".hidden.tex", "sp ace.tex", "main.tex",
                     "x" * 100 + ".tex", "néant.tex", "%2e%2e%2fup.tex", "con;rm -rf.tex"):
        made = site.ok("upload", "/api/export/upload", b"text", kind, name=declared, bundle=bundle)
        assert re.fullmatch(r"paper-[0-9a-f]{8}\.tex", made["name"]), declared
    for declared in ("run.sh", "paper.pdf", "notes", "cdl.bib", "x.tex.exe", "x.bst", "tex", ""):
        result, error = site.upload("/api/export/upload", b"text", kind, name=declared, bundle=bundle)
        assert error["kind"] == "BadRequest", declared
    held = site.running.app.store.get("bundle", bundle)
    inside = sorted(path.name for path in held["folder"].iterdir())
    assert inside == sorted(held["files"]) and held["folder"].parent == store
    assert sorted(path.name for path in store.iterdir()) == [held["folder"].name]        # nothing beside the bundle
    assert site.upload("/api/export/upload", b"x", kind, name="a.tex", bundle="A" * 22)[1]["kind"] == "NotFound"
    assert site.raw("POST", "/api/export/upload", site.headers(post=True, **{"Content-Type": kind}), data=b"x",
                    params={"name": "a.tex", "path": "/tmp/x"}).status_code == 400


# --- every answer -------------------------------------------------------------------------------

def test_every_kind_of_answer_carries_the_headers_and_no_cors(site):
    pdf = site.ok("upload", "/api/pdf/upload", b"%PDF-1.4\n", "application/pdf")["pdf"]
    post = site.headers(post=True)
    answers = [site.raw("GET", "/"), site.raw("GET", "/app.css"), site.raw("GET", "/theme.css"), site.raw("GET", "/js/main.js"),
               site.raw("GET", "/api/session", site.headers()), site.raw("GET", "/api/entries", site.headers()),
               site.raw("POST", "/api/check/format", post, json={}),                         # 202: a job
               site.raw("GET", f"/api/pdf/{pdf}/file", site.headers()),                        # bytes
               site.raw("GET", "/api/session"),                                                # 401
               site.raw("POST", "/api/check/format", site.headers(), json={}),                 # 403
               site.raw("GET", "/nothing"), site.raw("GET", "/api/nothing", site.headers()),   # 404
               site.raw("GET", "/api/send", site.headers()), site.raw("DELETE", "/"),          # 405
               site.raw("POST", "/api/send", post, json={"database": "x"}),                    # 400
               site.raw("POST", "/api/send", post, data="x", **{}),                            # 415
               site.raw("GET", "/api/entry", site.headers(), params={"key": "Nope99"})]        # 200: an error of the core is data
    assert [a.status_code for a in answers] == [200, 200, 200, 200, 200, 200, 202, 200, 401, 403, 404, 404, 405, 405, 400, 415, 200]
    for answer in answers:
        for name, value in server.HEADERS.items():
            assert answer.headers[name] == value, (answer.url, name)
        assert not [name for name in answer.headers if name.lower().startswith("access-control")]
        assert "Set-Cookie" not in answer.headers
    assert server.HEADERS["Content-Security-Policy"] == (
        "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; "
        "frame-src blob:; img-src 'self' blob: data:")
    assert "unsafe" not in server.CSP
    status, data = raw_request(site, "NONSENSE\r\n\r\n")           # a request http.server itself refuses
    assert status == 400 and b"Content-Security-Policy" in data and b"no-store" in data
    status, data = raw_request(site, "GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n" + "X: " + "a" * 70000 + "\r\n\r\n")
    assert status in (400, 431) and b"X-Content-Type-Options" in data


def test_the_token_is_in_no_log_line_and_no_answer(site):
    token = site.token
    texts = []
    for response in (site.raw("GET", "/api/session", site.headers()), site.raw("GET", "/api/session", params={"token": token}),
                     site.raw("GET", f"/api/{token}", site.headers()), site.raw("GET", f"/{token}"),
                     site.raw("GET", f"/api/jobs/{token[:22]}", site.headers()),
                     site.raw("POST", "/api/send", site.headers(post=True), json={token: 1}),
                     site.raw("POST", "/api/edit/preview", site.headers(post=True), json={"key": token + " x", "raw": "x"}),
                     site.raw("GET", "/api/entry", site.headers(), params={"key": token}),
                     site.raw("GET", "/api/session", {web.TOKEN: token + "x"})):
        texts.append(response.text)
    raw_request(site, f"GET /?token={token} HTTP/9.9\r\n\r\n")
    raw_request(site, f"BAD {token}\r\n\r\n")
    assert len(site.log) >= 9
    assert not [line for line in site.log if token in line or token[:16] in line]
    assert not [text for text in texts if token in text]       # not even when an error repeats what was asked
    assert all(re.fullmatch(r"[A-Z?]+ (/[A-Za-z0-9_./{}-]*|\(no route\)|\(unread\)) \d{3}", line) for line in site.log), site.log


# --- the page's own files -----------------------------------------------------------------------

def test_the_page_loads_nothing_from_elsewhere_and_never_parses_markup():
    for path in STATIC.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"""["'(]\s*(?:https?:)?//""", text), path.name          # no address of another origin
        assert not re.search(r"@import|url\(|<iframe|<object|<embed|<form\b", text), path.name
        if path.suffix == ".js":
            for word in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                         "setAttribute(\"style\"", "srcdoc", "javascript:", "sessionStorage", "document.cookie"):
                assert word not in text, (path.name, word)
            assert "import(" not in text, path.name
            for line in re.findall(r"(?m)^import\b.*$", text):
                assert re.fullmatch(r'import (\{[^}]*\}|\* as \w+) from "\./[a-z]+\.js";', line), (path.name, line)
        if path.suffix == ".html":
            assert not re.search(r"\son[a-z]+\s*=|style\s*=|<style|<script(?![^>]*\ssrc=)", text), path.name
    main = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
    assert "history.replaceState" in main and "location.hash" in main
    assert "localStorage.setItem(\"cdlbib-theme\"" in main and main.count("localStorage") == 2     # the theme, nothing else
