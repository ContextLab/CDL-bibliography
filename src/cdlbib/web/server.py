"""The web interface's server: Python's own http.server on 127.0.0.1, for this computer's
user only. It serves a fixed set of static files and the endpoints of routes.ROUTES.

Every request must name this server as its Host. An /api/ request must carry the run's
random token in the X-CDLBIB-Token header (the page is given it in the address's fragment,
which a browser never sends). A request that changes anything is a POST whose Origin is
this server. There are no CORS headers. All work is done by one job worker (jobs.Worker)."""
import json
import secrets
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs

from .. import api, theme
from ..errors import CdlbibError
from . import routes
from .jobs import Busy, Closed, Worker
from .store import MAX_UPLOAD, Full, Store

LOOPBACK = "127.0.0.1"
TOKEN_HEADER = "X-CDLBIB-Token"
MAX_JSON = 1_000_000        # bytes of a JSON request body
MAX_DEPTH = 6               # nesting of a JSON request body
MAX_DRAIN = 8_000_000       # an oversize JSON body up to this is read and thrown away, so the refusal arrives
MAX_QUERY = 4000            # characters of a query string
CSP = ("default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; "
       "frame-src blob:; img-src 'self' blob: data:")
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
           "X-Frame-Options": "DENY", "Content-Security-Policy": CSP,
           "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Resource-Policy": "same-origin"}
MODULES = ("main", "api", "dom", "detail", "library", "edit", "check", "review", "add", "proposal", "offers", "send", "state", "setup")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"),
          **{f"/js/{name}.js": (f"js/{name}.js", "text/javascript; charset=utf-8") for name in MODULES}}
STATUS = {"BadRequest": 400, "NotFound": 404, "InternalError": 500}
BODY_TYPES = {"json": "application/json", "pdf": "application/pdf", "file": "application/octet-stream"}


class Refused(Exception):
    def __init__(self, status, kind, message, headers=()):
        self.status, self.kind, self.message, self.headers = status, kind, message, dict(headers)
        super().__init__(message)


def nesting(text):
    """The deepest nesting of brackets in JSON text, outside its strings."""
    depth = deepest = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "]}":
            depth -= 1
    return deepest


def _no_constant(name):
    raise ValueError(f"{name} is not JSON")


class App:
    """One run of the interface on one library: the token, the store, the worker."""

    def __init__(self, ws, log=None):
        self.ws = ws
        self.log = log or (lambda line: None)
        self.token = secrets.token_urlsafe(32)
        self.store = Store()
        self.worker = Worker(self.failure)
        self.managed = api.is_managed(ws)
        self.origin = api.library_state(ws).origin
        self.cached = self.offers = self.offered = self.identity = self.prepare_job = None
        self.generation, self.seen = 0, set()
        self.hosts = self.origins = ()
        folder = resources.files("cdlbib.web") / "static"
        self.static = {path: (kind, (folder / name).read_bytes()) for path, (name, kind) in STATIC.items()}
        self.static["/theme.css"] = ("text/css; charset=utf-8", theme.stylesheet().encode("utf-8"))

    def failure(self, exc):
        found = routes.failure(exc)
        if found["kind"] == "InternalError":
            self.log("internal error: " + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:])
        return found

    def prepare(self):
        try:        # one waiting preparation is enough; when the queue is full the next request prepares
            self.prepare_job = self.worker.submit("prepare", lambda say: api.as_data(api.prepare(self.ws, say)),
                                                  single=True).id
        except (Busy, Closed):
            pass

    def start(self):
        self.worker.start()
        self.prepare()

    def close(self):
        """Take no more jobs, cancel the ones that have not started, wait (for a bounded time)
        for the one that is running, and only then remove the run's folder."""
        self.worker.stop()
        self.store.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version, sys_version = "cdlbib", ""
    timeout = 120
    app = None

    def log_message(self, *args):       # the base class would log request lines; ours are in _send
        pass

    def end_headers(self):
        for name, value in HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def send_error(self, code, message=None, explain=None):    # a request http.server itself refused
        self.close_connection = True
        if self.request_version == "HTTP/0.9":      # the request line was not read: answer in HTTP/1.1 all the same
            self.request_version = "HTTP/1.1"
        self._send(code, {"error": {"kind": "BadRequest", "message": "the request could not be read"}}, "(unread)")

    def _send(self, status, body, shown, kind="application/json; charset=utf-8", headers=()):
        if isinstance(body, bytes):
            data = body
        else:       # the token is in no answer, also when a request's own text held it and an error repeats that text
            data = json.dumps(body, ensure_ascii=False).replace(self.app.token, "[removed]").encode("utf-8")
        self.app.log(f"{self.command or '?'} {shown} {status}")
        try:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            for name, value in dict(headers).items():
                self.send_header(name, value)
            if status >= 400:
                self.close_connection = True
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.close_connection = True

    def _host(self):
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0] not in self.app.hosts:
            raise Refused(403, "Forbidden", "this server answers only to its own address on this computer")
        return hosts[0]

    def _origin(self, host, required):
        origins = self.headers.get_all("Origin") or []
        if not origins and not required:
            return
        if len(origins) != 1 or origins[0] != f"http://{host}":
            raise Refused(403, "Forbidden", "the request did not come from this server's own page")

    def _body(self, route):
        if self.headers.get("Transfer-Encoding"):
            raise Refused(400, "BadRequest", "a request body must state its length")
        kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kind != BODY_TYPES[route.body]:
            raise Refused(415, "UnsupportedMediaType", f"this request takes {BODY_TYPES[route.body]}")
        stated = self.headers.get("Content-Length") or ""
        if not stated.isdigit() or len(stated) > 12:
            raise Refused(411, "LengthRequired", "a request body must state its length")
        length, most = int(stated), MAX_JSON if route.body == "json" else MAX_UPLOAD
        if route.body != "json" and length <= most:
            kind = "pdf" if route.body == "pdf" else "bundle"
            try:        # room for the upload is set aside before a byte of it is read
                self.app.store.reserve(kind, length)
            except Full as exc:
                raise Refused(413, "QuotaExceeded", str(exc)) from exc
            self.reserved = (kind, length)
        if length > most:
            if route.body == "json" and length <= MAX_DRAIN:
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    left -= len(chunk)
            raise Refused(413, "TooLarge", f"the request is larger than {most} bytes")
        data = self.rfile.read(length)
        if len(data) != length:
            raise Refused(400, "BadRequest", "the request body ended early")
        return data

    def _json(self, data):
        try:
            text = data.decode("utf-8")
            if nesting(text) > MAX_DEPTH:
                raise ValueError("nested too deeply")
            given = json.loads(text, parse_constant=_no_constant)
        except (ValueError, RecursionError) as exc:
            raise Refused(400, "BadRequest", "the request body is not the JSON this server takes") from exc
        if not isinstance(given, dict):
            raise Refused(400, "BadRequest", "the request body must be a JSON object")
        return given

    def _query(self, query):
        if len(query) > MAX_QUERY:
            raise Refused(414, "BadRequest", "the request's query is too long")
        try:
            found = parse_qs(query, keep_blank_values=True, strict_parsing=bool(query), max_num_fields=60,
                             encoding="utf-8", errors="strict")
        except ValueError as exc:
            raise Refused(400, "BadRequest", "the request's query could not be read") from exc
        return {name: values[0] if len(values) == 1 else values for name, values in found.items()}

    def _handle(self):
        shown = "(no route)"
        self.reserved = None
        try:
            host = self._host()
            target = self.path
            if not target.startswith("/") or "#" in target:
                raise Refused(400, "BadRequest", "the request could not be read")
            path, _, query = target.partition("?")
            if not path.startswith("/api/"):
                found = self.app.static.get(target)
                if found is None:
                    raise Refused(404, "NotFound", "there is no such page")
                if self.command != "GET":
                    raise Refused(405, "MethodNotAllowed", "this address is read with GET", {"Allow": "GET"})
                return self._send(200, found[1], path, kind=found[0])
            self._origin(host, required=self.command != "GET")
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                raise Refused(403, "Forbidden", "the request did not come from this server's own page")
            tokens = self.headers.get_all(TOKEN_HEADER) or []
            if len(tokens) != 1 or not secrets.compare_digest(tokens[0].encode("utf-8", "replace"),
                                                             self.app.token.encode("ascii")):
                raise Refused(401, "Unauthorized", "this request does not carry this run's token; open the address "
                                                   "that `cdlbib web` printed")
            route, held = routes.find(self.command, path)
            if route is None:
                if held:
                    raise Refused(405, "MethodNotAllowed", "this address takes " + ", ".join(held),
                                  {"Allow": ", ".join(held)})
                raise Refused(404, "NotFound", "there is no such address")
            shown = route.path
            body = None
            given = self._query(query)
            if route.method == "POST":
                body = self._body(route)
                if route.body == "json":
                    if given:
                        raise Refused(400, "BadRequest", "this request takes its arguments in its JSON body")
                    given, body = self._json(body), None
            elif self.headers.get("Content-Length") not in (None, "0"):
                raise Refused(400, "BadRequest", "a GET request has no body")
            try:
                args = routes.arguments(route, given, held)
            except routes.Bad as exc:
                raise Refused(400, "BadRequest", str(exc)) from exc
            self._answer(route, args, body)
        except Refused as exc:
            self._send(exc.status, {"error": {"kind": exc.kind, "message": exc.message}}, shown, headers=exc.headers)
        except Exception as exc:     # never a traceback to the browser
            self._send(500, {"error": self.app.failure(exc)}, shown)
        finally:
            if self.reserved:           # what was stored is counted with its object from here on
                self.app.store.release(*self.reserved)

    def _answer(self, route, args, body):
        app = self.app
        if route.direct:
            try:
                made = route.handler(app, args, None, body) if body is not None else route.handler(app, args, None)
            except Exception as exc:
                error = app.failure(exc)
                return self._send(STATUS.get(error["kind"], 200), {"error": error}, route.path)
            if route.answer == "bytes":
                kind, data, name = made
                headers = {"Content-Disposition": f'attachment; filename="{name}"'} if name else {}
                return self._send(200, data, route.path, kind=kind, headers=headers)
            return self._send(200, {"result": made}, route.path)
        try:
            job = app.worker.submit(f"{route.method} {route.path}", routes.guarded(app, route, args), single=route.single)
        except Busy as exc:
            raise Refused(429, "TooManyJobs", str(exc), {"Retry-After": "2"}) from exc
        except Closed as exc:
            raise Refused(503, "Stopping", "cdlbib web is stopping") from exc
        if route.path in routes.CHANGES_LIBRARY:
            app.prepare()
        if route.wait and job.wait(route.wait):
            if job.error is not None:
                return self._send(STATUS.get(job.error["kind"], 200), {"error": job.error}, route.path)
            return self._send(200, {"result": job.result}, route.path)
        self._send(202, {"job": job.id}, route.path)

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _other(self):
        self.close_connection = True
        self._send(405, {"error": {"kind": "MethodNotAllowed", "message": "this server takes GET and POST"}},
                   "(no route)", headers={"Allow": "GET, POST"})

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _other


class Running:
    """A started server: ``url`` is the address to open (the token is in its fragment)."""

    def __init__(self, app, httpd):
        self.app, self.httpd = app, httpd
        self.port = httpd.server_address[1]
        self.origin = f"http://{LOOPBACK}:{self.port}"
        self.url = f"{self.origin}/#token={app.token}"
        self.thread = None

    def serve(self):
        self.httpd.serve_forever(poll_interval=0.2)

    def serve_in_thread(self):
        self.thread = threading.Thread(target=self.serve, name="cdlbib-web", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.thread is not None:
            self.httpd.shutdown()
            self.thread.join(timeout=10)
        self.httpd.server_close()
        self.app.close()


def start(ws, port=0, log=None):
    """Bind 127.0.0.1:``port`` (0: a port the system picks) for the library ``ws`` and start
    the job worker, whose first job is api.prepare. Returns Running; nothing is served until
    ``serve`` or ``serve_in_thread``."""
    app = App(ws, log=log)
    handler = type("CdlbibHandler", (Handler,), {"app": app})
    try:
        httpd = ThreadingHTTPServer((LOOPBACK, port), handler)
    except OSError as exc:
        app.store.close()
        raise CdlbibError(f"The web interface could not listen on {LOOPBACK}:{port}: {exc}") from exc
    httpd.daemon_threads = True
    running = Running(app, httpd)
    app.hosts = (f"{LOOPBACK}:{running.port}", f"localhost:{running.port}")
    app.start()
    return running


def run(port=0, open_browser=True, say=print):
    """The `cdlbib web` command: serve the library in use until interrupted."""
    ws = api.ensure_library(progress=say)

    def log(line):                      # refusals and failures only; ordinary requests are not listed
        if line.startswith("internal error") or line.rsplit(" ", 1)[-1] >= "400":
            print(line, file=sys.stderr)

    running = start(ws, port=port, log=log)
    say(f"cdlbib web: {ws.bib}")
    say(f"open: {running.url}")
    say("This address works on this computer only, and until this command is stopped (Ctrl-C).")
    if open_browser:
        try:
            webbrowser.open(running.url)
        except Exception as exc:        # no browser to open: the address is printed above
            say(f"the browser could not be opened ({type(exc).__name__}); open the address above")
    try:
        running.serve()
    except KeyboardInterrupt:
        pass
    finally:
        running.httpd.server_close()
        running.app.close()
