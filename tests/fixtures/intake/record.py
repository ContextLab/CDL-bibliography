"""Record the lookups of the intake tests: real requests, made once.

    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py searches
    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py pdfs
    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py web
    python tests/fixtures/intake/record.py model          (needs the Dartmouth Chat key)

(or add the path of a verification cache whose Crossref requests name the contact, as
``extra_sources.contact_email`` reads it). ``searches`` runs each search of SEARCHES with
``cdlbib.intake.find_candidates``; ``pdfs`` typesets the PDFs of tests/intake_pdfs.py and
runs ``cdlbib.intake.propose_from_pdf`` on each. Both go through the project's
``PoliteClient`` over an empty response cache; what the client cached is then written to
``searches.json.gz`` / ``pdf_lookups.json.gz`` with the alterations README.md lists.
"""
import gzip
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from cdlbib import extra_sources as xs  # noqa: E402
from cdlbib import intake  # noqa: E402
from cdlbib.workspace import Workspace  # noqa: E402

PER_SOURCE = 5
SEARCHES = [
    {"title": "Backward learning in paired associates"},
    {"authors": ["Manning", "Kahana"]},
    {"title": "Attention is all you need", "authors": ["Vaswani"]},
    {"title": "Array programming with NumPy", "authors": ["Harris", "van der Walt"], "year": "2020"},
    {"title": "Zzyzxqv qwxzvk plorbnix"},
]
PDFS = ("doi", "arxiv", "title", "titled", "mismatch", "unknown")
# What the web interface's tests search for through api.find_candidates, which asks each
# source for intake.PER_SOURCE records (the searches above ask for PER_SOURCE).
WEB_SEARCHES = [{"title": "Attention is all you need", "authors": ["Vaswani"]}]
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def searches(ws, client, folder):
    for search in SEARCHES:
        found = intake.find_candidates(ws, client=client, per_source=PER_SOURCE, **search)
        print(search, "->", len(found), "leads;", "errors:", found.errors, file=sys.stderr)


def web(ws, client, folder):
    for search in WEB_SEARCHES:
        found = intake.find_candidates(ws, client=client, **search)
        print(search, "->", len(found), "leads;", "errors:", found.errors, file=sys.stderr)


def pdfs(ws, client, folder):
    import intake_pdfs
    for name in PDFS:
        result = intake.propose_from_pdf(ws, intake.read_pdf(intake_pdfs.build(name, folder / "pdfs")), client=client)
        print(name, "->", result.message, result.tried, file=sys.stderr)


def model(route="dartmouth"):
    """One real ``extract`` run of the route's adapter on the first pages of the ``unknown``
    PDF, saved with the pages it was given (``model_extract.json``). Needs the route's key."""
    import intake_pdfs
    from cdlbib.research import INSTRUCTIONS, invoke_adapter
    with tempfile.TemporaryDirectory() as folder:
        read = intake.read_pdf(intake_pdfs.build("unknown", Path(folder)))
    pages = read.pages[:intake.MODEL_PAGES]
    extracted = invoke_adapter(intake._adapter(route), {"phase": "extract", "instructions": INSTRUCTIONS,
                                                        "entry": {}, "pages": pages})
    (HERE / "model_extract.json").write_text(json.dumps(
        {"route": route, "pdf": "unknown", "pdf_sha256": read.sha256, "pages": pages, "extracted": extracted},
        ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print("model reading saved:", sorted(extracted.get("fields", {})), file=sys.stderr)


def main(part, contact_source=None):
    if part == "model":
        return model(contact_source or "dartmouth")
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        (folder / "cdl.bib").write_text("", encoding="utf-8")
        client = xs.make_client(folder / "responses.sqlite3", contact=xs.contact_email(contact_source))
        contact = client.contact
        try:
            {"searches": searches, "pdfs": pdfs, "web": web}[part](Workspace(folder), client, folder)
        finally:
            client.cache.close()
        rows = sqlite3.connect(folder / "responses.sqlite3").execute(
            "SELECT request, body FROM responses ORDER BY fetched").fetchall()
    saved = []
    for request, body in rows:
        if request.startswith("["):  # the client's key: URL, parameters, XML or not
            url, params, xml = json.loads(request)
            request = [url, {k: "CONTACT" if v == contact else v for k, v in params.items()}, xml]
        response = json.loads(body)
        response["url"] = re.sub(r"(?<=[?&])(?:mailto|email)=[^&]*&?", "", response["url"]).rstrip("?&")
        if "document_sha256" not in response:  # a saved document is kept byte for byte (its hash is checked)
            response = json.loads(ADDRESS.sub("[address removed]", json.dumps(response, ensure_ascii=False)))
        assert contact not in json.dumps(response) and contact not in json.dumps(request)
        saved.append({"request": request, "response": response})
    name = {"searches": "searches.json.gz", "pdfs": "pdf_lookups.json.gz", "web": "web_searches.json.gz"}[part]
    with gzip.GzipFile(HERE / name, "wb", mtime=0) as handle:
        handle.write(json.dumps(saved, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))
    print(len(saved), "responses saved to", name, file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
