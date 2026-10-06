"""Record the lookups of the intake tests: real requests, made once.

    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py searches
    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py pdfs
    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py web
    python tests/fixtures/intake/record.py model          (needs the Dartmouth Chat key)

    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py tui
    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py books
    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py chapters
    CROSSREF_MAILTO=you@example.org python tests/fixtures/intake/record.py catalogue
    python tests/fixtures/intake/record.py booktitle      (needs the Dartmouth Chat key)

(or add the path of a verification cache whose Crossref requests name the contact, as
``extra_sources.contact_email`` reads it). ``searches`` runs each search of SEARCHES with
``cdlbib.intake.find_candidates``; ``pdfs`` typesets the PDFs of tests/intake_pdfs.py and
runs ``cdlbib.intake.propose_from_pdf`` on each. Both go through the project's
``PoliteClient`` over an empty response cache; what the client cached is then written to
``searches.json.gz`` / ``pdf_lookups.json.gz`` with the alterations README.md lists.
``tui`` records what the terminal interface's Add view asks through ``cdlbib.api`` in
tests/test_tui_add.py (``tui_search.json.gz``).
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


TUI_SEARCH = {"title": "Backward learning in paired associates"}


def tui(ws, client, folder):
    """The search the Add view makes for TUI_SEARCH (the api's own number of records per
    source), and the lookup of the first lead, as choosing it in the view makes it."""
    from cdlbib import api
    found = intake.find_candidates(ws, client=client, **TUI_SEARCH)
    print(TUI_SEARCH, "->", len(found), "leads;", "errors:", found.errors, file=sys.stderr)
    results = api._proposals(ws, [("first lead", intake.query_for(found[0]))], client=client)
    print("first lead ->", results[0].key_proposed, results[0].status, results.errors, file=sys.stderr)


# Books, as `cdlbib add` is given them (tests/test_complete_books.py): (text, author, year).
BOOKS = [
    ("ISBN 9780195333244", None, None),                 # one author
    ("ISBN 9781439840955", None, None),                 # six authors, a third edition
    ("LCCN 92-17326", None, None),                      # an edited volume, entered under its title
    ("LCCN 10032396", None, None),                      # an imprint of 1883
    ("LCCN 2006923897", None, None),                    # a second edition, as a chosen candidate is looked up
    ("Numerical optimization", "Nocedal", None),        # two editions: candidates
    ("Numerical optimization", "Nocedal", "2006"),
    ("Organization of memory", "Tulving", None),        # two editors
    ("Elements of episodic memory", "Tulving", None),   # two publishers
    ("Statistical power analysis for the behavioral sciences", "Cohen", "1977"),    # "Rev. ed."
    ("ISBN 9780387954714", None, None),                 # a record the catalogue check does not read
    ("LCCN 2099123456", None, None),                    # no such record
    ("Zzyzxqv qwxzvk plorbnix", "Nobody", None),
]
BOOKS_WRITTEN = ("ISBN 9780195333244", "Statistical power analysis for the behavioral sciences")
# Chapters whose Crossref record names two container titles (tests/test_complete_booktitle.py).
CHAPTERS = ["10.1007/978-0-387-21579-2_9", "10.1007/978-3-031-20910-9_48", "10.1016/s0166-4115(08)60886-9",
            "10.1016/s0079-6123(03)45022-x"]
BOOKTITLE_DOI = "10.1007/978-3-031-20910-9_48"


def books(ws, client, folder):
    """Each book of BOOKS through ``api._proposals`` (the catalogue lookups and the first
    check); the books of BOOKS_WRITTEN are then written and judged by the gate for exactly
    their keys, so that every request the gate makes for them is saved too."""
    from cdlbib import api, complete
    written = []
    for text, author, year in BOOKS:
        query = complete.Query.parse(text, author=author, year=year, book=True)
        result = api._proposals(ws, [(text, query)], client=client)[0]
        print(text, author, year, "->", result.key_proposed, result.status, len(result.candidates), file=sys.stderr)
        if text in BOOKS_WRITTEN:
            done = api.apply_proposals(ws, [result])
            written += done.written
    check = api.check_keys(ws, written, database=str(client.cache.path), mailto=client.contact)
    print("gate:", {key: found["status"] for key, found in check.citations.checked.items()}, file=sys.stderr)


def chapters(ws, client, folder):
    from cdlbib import api, complete
    for doi in CHAPTERS:
        result = api._proposals(ws, [(doi, complete.Query.parse(doi))], client=client, allow_model=False)[0]
        print(doi, "->", result.key_proposed, result.status, [u.reason for u in result.unfilled if u.field == "booktitle"],
              file=sys.stderr)


def catalogue(ws, client, folder):
    """The Library of Congress answers to the searches of SEARCHES and WEB_SEARCHES that give
    a title and an author (the only ones the catalogue is asked)."""
    for search in SEARCHES + WEB_SEARCHES:
        if search.get("title") and search.get("authors"):
            found = intake.find_candidates(ws, client=client, sources=("loc-catalogue",), **search)
            print(search, "->", len(found), "catalogue leads;", "errors:", found.errors, file=sys.stderr)


def booktitle(route="dartmouth", contact_source=None):
    """One real model reading of the publisher's page of BOOKTITLE_DOI, asked as
    ``container_titles.from_model`` asks it, saved with the page's lines
    (``booktitle_model.json``). E-mail addresses are removed from the lines before the model
    is given them, so what is saved is what was read. Needs the route's key."""
    from cdlbib import container_titles as ct
    from cdlbib.verification import normalize_doi
    with tempfile.TemporaryDirectory() as folder:
        client = xs.make_client(Path(folder) / "responses.sqlite3", contact=xs.contact_email(contact_source))
        try:
            record = client.crossref_doi(normalize_doi(BOOKTITLE_DOI))["body"]["message"]
            titles = ct.two_titles(record)
            page = ct.fetch_page(normalize_doi(BOOKTITLE_DOI), record)
            page["lines"] = [ADDRESS.sub("[address removed]", line) for line in page["lines"]]
            client.cache.save_response("book-title-page-v1:" + normalize_doi(BOOKTITLE_DOI), page)
            found = ct.from_model(client, client.cache, record, titles, announce=lambda line: print(line, file=sys.stderr))
            _, pages, reading = ct._saved(client.cache, normalize_doi(BOOKTITLE_DOI), titles)
        finally:
            client.cache.close()
    print("model reading:", found.chosen, "|", found.reason, file=sys.stderr)
    if reading is None:
        raise SystemExit("no reading was returned; nothing saved")
    (HERE / "booktitle_model.json").write_text(json.dumps(
        {"doi": BOOKTITLE_DOI, "titles": list(titles), "record": record, "page": page, "reading": reading},
        ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")


def _append(name, saved):
    """Add the saved responses a fixture file does not hold yet (by request)."""
    held = json.loads(gzip.open(HERE / name).read().decode("utf-8"))
    known = {json.dumps(item["request"], sort_keys=True) for item in held}
    new = [item for item in saved if json.dumps(item["request"], sort_keys=True) not in known]
    with gzip.GzipFile(HERE / name, "wb", mtime=0) as handle:
        handle.write(json.dumps(held + new, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))
    print(len(new), "responses added to", name, file=sys.stderr)


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


def main(part, contact_source=None, route=None):
    if part == "model":
        return model(contact_source or "dartmouth")
    if part == "booktitle":       # record.py booktitle [cache with the contact] [route]
        return booktitle(route or "dartmouth", contact_source)
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        (folder / "cdl.bib").write_text("", encoding="utf-8")
        (folder / "verification").mkdir()
        client = xs.make_client(folder / "responses.sqlite3", contact=xs.contact_email(contact_source))
        contact = client.contact
        try:
            {"searches": searches, "pdfs": pdfs, "web": web, "tui": tui, "books": books, "chapters": chapters,
             "catalogue": catalogue}[part](Workspace(folder), client, folder)
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
        if "url" in response:
            response["url"] = re.sub(r"(?<=[?&])(?:mailto|email)=[^&]*&?", "", response["url"]).rstrip("?&")
        if "document_sha256" not in response:  # a saved document is kept byte for byte (its hash is checked)
            response = json.loads(ADDRESS.sub("[address removed]", json.dumps(response, ensure_ascii=False)))
        assert contact not in json.dumps(response) and contact not in json.dumps(request)
        saved.append({"request": request, "response": response})
    if part == "catalogue":       # added to the files of the searches they belong to; nothing else in them changes
        _append("searches.json.gz", saved)
        return _append("web_searches.json.gz", [item for item in saved if "attention" in str(item["request"])])
    name = {"searches": "searches.json.gz", "pdfs": "pdf_lookups.json.gz", "web": "web_searches.json.gz",
            "tui": "tui_search.json.gz", "books": "books.json.gz", "chapters": "chapters.json.gz"}[part]
    with gzip.GzipFile(HERE / name, "wb", mtime=0) as handle:
        handle.write(json.dumps(saved, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))
    print(len(saved), "responses saved to", name, file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None, sys.argv[3] if len(sys.argv) > 3 else None)
