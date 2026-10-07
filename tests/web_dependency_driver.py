"""Run by tests/test_web_server.py with the interpreter of a scratch environment in which the
`pdf` extra is NOT installed: the real server, one uploaded PDF, and the request for its
first page, which needs pypdfium2.

    python web_dependency_driver.py LIBRARY_FOLDER PDF ask|default

Prints one JSON object: what the server answered at each step. Uses only cdlbib and requests.
"""
import base64
import importlib.util
import json
import sys
from pathlib import Path

import requests

from cdlbib import deps
from cdlbib.web import server
from cdlbib.workspace import Workspace


def main(folder, pdf, mode):
    deps.set_ask(mode == "ask")
    running = server.start(Workspace(folder)).serve_in_thread()
    http = requests.Session()
    http.trust_env = False
    headers = {server.TOKEN_HEADER: running.app.token, "Origin": running.origin}

    def settle(response):
        found, lines, after = response.json(), [], 0
        while "job" in found:
            view = http.get(f"{running.origin}/api/jobs/{found['job']}", headers=headers, params={"after": after}).json()["result"]
            lines += view["lines"]
            after = view["next"]
            if view["done"]:
                return view.get("result"), view.get("error"), lines
        return found.get("result"), found.get("error"), lines

    def page(**more):
        result, error, lines = settle(http.post(running.origin + "/api/pdf/page", headers=headers, json=dict(pdf=sent, **more)))
        png = base64.b64decode(result["png"]) if result else b""
        return {"error": error, "lines": lines, "png": png[:8].hex(), "bytes": len(png)}

    out = {"missing_at_start": importlib.util.find_spec("pypdfium2") is None}
    try:
        sent = settle(http.post(running.origin + "/api/pdf/upload", headers=dict(headers, **{"Content-Type": "application/pdf"}),
                                data=Path(pdf).read_bytes()))[0]["pdf"]
        out["session_ask"] = http.get(running.origin + "/api/session", headers=headers).json()["result"]["ask"]
        out["first"] = page()
        if mode == "ask":
            out["missing_after_first"] = importlib.util.find_spec("pypdfium2") is None
            out["second"] = page(allow_install=True)
    finally:
        running.stop()
    print(json.dumps(out))


if __name__ == "__main__":
    main(*sys.argv[1:4])
