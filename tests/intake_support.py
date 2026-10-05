"""Shared by the intake tests: a temporary library, and the real client over saved responses.

``offline_client`` is ``extra_sources.make_client(..., offline=True)``: the project's
``PoliteClient`` over a real response cache with a transport that refuses every request,
filled with responses that were fetched once (tests/fixtures/intake/README.md). A lookup
the fixtures do not hold fails as a refused request; ``client.requests == 0`` shows that
none was attempted.
"""
import gzip
import json
from pathlib import Path

from cdlbib import extra_sources as xs
from cdlbib.verification import dumps
from cdlbib.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/intake"
CONTACT = "valid@example.org"  # never sent anywhere: the transport refuses every request


def saved(name):
    return json.loads(gzip.open(FIXTURES / name).read().decode("utf-8"))


def offline_client(folder, *names):
    client = xs.make_client(Path(folder) / "responses.sqlite3", contact=CONTACT, offline=True)
    for name in names:
        for item in saved(name):
            request = item["request"]
            if isinstance(request, list):  # PubMed requests name the caller's contact address
                url, params, xml = request
                request = dumps([url, {k: CONTACT if v == "CONTACT" else v for k, v in params.items()}, xml])
            client.cache.save_response(request, item["response"])
    return client


def library(folder, *entries):
    """A library of its own in ``folder`` holding ``entries`` (exact entry texts)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "verification").mkdir(exist_ok=True)
    (folder / "cdl.bib").write_text("".join(entry + "\n\n" for entry in entries), encoding="utf-8")
    return Workspace(folder)
