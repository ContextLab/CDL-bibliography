"""Each flow of the web interface end to end through its JSON API, with the files and the
verification database examined afterwards.

The real server on loopback and the real core, against libraries in tmp_path; HOME,
TEXMFHOME, cdlbib's data folder and the upstream are the test's own. Lookups are answered by
the project's real client from the responses saved under tests/fixtures/ (put into the
library's own response cache); a request the cache does not hold cannot leave this computer
(web_support.isolated_environment). PDFs are typeset here by pdflatex. Nothing is replaced by
a stand-in.
"""
import base64
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import conftest
import intake_pdfs as pdfs
import web_support as web
from cdlbib import api, complete, prompts
from cdlbib.errors import IdentityUnavailable
from cdlbib.verification import ACCEPTED, load_entries

from test_complete_identify import library_entry
from test_update import advance

ZOLL90 = conftest.ZOLL90
KAHA12 = ("@book{Kaha12,\n\tAddress = {New York, {NY}},\n\tAuthor = {M J Kahana},\n\tPublisher = {Oxford University "
          "Press},\n\tTitle = {Foundations of human memory},\n\tYear = {2012}}")
TENE11 = complete.render("article", "TeneEtal11", dict(
    author="J B Tenenbaum and C Kemp and T L Griffiths and N D Goodman",
    title="How to grow a mind: statistics, structure, and abstraction", journal="Science", year="2011",
    volume="331", number="6022", pages="1279--1285", doi="10.1126/science.1192788"))
GAME62 = library_entry("Game62")
ID = re.compile(r"[A-Za-z0-9_-]{22}")


@pytest.fixture(autouse=True, scope="module")
def real_data_folder_untouched():
    yield
    conftest.no_real_library_touched()


def _site(tmp_path, monkeypatch, home=True):
    web.isolate(monkeypatch, tmp_path / "env", home=home)
    ws = web.make_library(tmp_path / "library", KAHA12, GAME62, TENE11)
    web.seed(ws, "pdf_lookups.json.gz", "web_searches.json.gz", completion=True, verify=("Game62",))
    running, client = web.start(ws)
    client.ws = ws
    return running, client


@pytest.fixture
def site(tmp_path, monkeypatch):
    running, client = _site(tmp_path, monkeypatch)
    yield client
    running.stop()
    assert running.app.worker.overlaps == 0


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    if not pdfs.pdflatex():
        pytest.skip("pdflatex is not installed: the test PDFs cannot be typeset")
    folder = tmp_path_factory.mktemp("pdfs")
    return {name: pdfs.build(name, folder) for name in ("doi", "unknown")}


def text(ws):
    return ws.bib.read_text(encoding="utf-8")


def keys(ws):
    return list(load_entries(ws.bib))


# --- browse, search, one entry ------------------------------------------------------------------

def test_browse_search_and_one_entry(site):
    found = site.ok("get", "/api/entries")
    assert found["columns"] == ["key", "type", "authors", "year", "title", "venue", "doi", "status", "issues"]
    assert [row[0] for row in found["rows"]] == ["Kaha12", "Game62", "TeneEtal11"]
    assert found["rows"][0] == ["Kaha12", "book", "M J Kahana", "2012", "Foundations of human memory",
                                "Oxford University Press", "", "pending", 1]
    assert found["counts"] == {"pending": 2, "metadata_verified": 1}
    for query, status, expected in (("games", None, ["Game62"]), ("GAMES factorial", None, ["Game62"]), ("type:book", None, ["Kaha12"]),
                                    ("author:tenenbaum year:2011", None, ["TeneEtal11"]), ("status:pending", None, ["Kaha12", "TeneEtal11"]),
                                    ("", "metadata_verified", ["Game62"]), ("memory", "metadata_verified", []),
                                    ('title:"human memory"', None, ["Kaha12"]), ("nothing-like-this", None, []),
                                    ("", None, ["Kaha12", "Game62", "TeneEtal11"])):
        answer = site.ok("get", "/api/search", q=query, status=status)
        assert answer["keys"] == expected and answer["revision"] == found["revision"], query
    assert answer["keys"] == [item.key for item in api.search(site.ws, "")]

    detail = site.ok("get", "/api/entry", key="Game62")
    entry = load_entries(site.ws.bib)["Game62"]
    assert (detail["key"], detail["raw"], detail["fingerprint"]) == ("Game62", GAME62, entry["fingerprint"])
    assert detail["fields"]["volume"] == "63" and detail["result"]["status"] == "metadata_verified"
    source = detail["result"]["candidates"][0]
    assert source["source"] == "crossref" and source["evidence"]["volume"] == {"local": "63", "match": True, "source": ["63"]}
    assert detail["result"]["attempts"] and detail["format"] == [] and detail["closest"] is None
    queue = site.ok("get", "/api/review-queue", all="1")
    assert [item["key"] for item in queue["entries"]] == ["Kaha12", "TeneEtal11"]
    assert (queue["total"], queue["offset"], queue["revision"]) == (2, 0, found["revision"])
    assert queue["entries"][0]["fingerprint"] == load_entries(site.ws.bib)["Kaha12"]["fingerprint"]
    result, error = site.get("/api/review-queue")              # the changed entries: needs the GitHub master
    assert error["kind"] == "CdlbibError" and "could not be selected" in error["message"]


def test_the_list_is_read_again_only_when_something_changed_on_disk(site):
    first = site.ok("get", "/api/entries")["revision"]
    for _ in range(3):                                          # reading entries and evidence changes nothing
        site.ok("get", "/api/entry", key="Game62")
        site.ok("get", "/api/review-queue", all="1")
        assert site.ok("get", "/api/revision")["revision"] == first
        assert site.ok("get", "/api/search", q="games")["revision"] == first
    site.ws.bib.write_text(text(site.ws).replace("{2012}", "{2013}"), encoding="utf-8")       # another program edits the file
    second = site.ok("get", "/api/revision")["revision"]
    assert second != first
    assert site.ok("get", "/api/entries")["rows"][0][3] == "2013" and site.ok("get", "/api/entries")["revision"] == second


# --- edit ---------------------------------------------------------------------------------------

def test_preview_then_save_writes_exactly_what_was_previewed(site):
    before = text(site.ws)
    edited = KAHA12.replace("{2012}", "{2013}").replace("New York, {NY}", "New York, NY")
    preview = site.ok("post", "/api/edit/preview", {"key": "Kaha12", "raw": edited})
    assert preview["changed"] and preview["problems"] == [] and ID.fullmatch(preview["preview"])
    assert "-\tYear = {2012}}" in preview["diff"] and "+\tYear = {2013}}" in preview["diff"]
    assert ("address", "New York, {NY}") in [(f["field"], f["corrected"]) for f in preview["format"]]
    assert preview["fingerprint"] == load_entries(site.ws.bib)["Kaha12"]["fingerprint"]
    assert preview["status_now"] == "pending" and text(site.ws) == before                    # nothing written yet
    # the save takes the preview's id and nothing else: no text, no fingerprint from the browser
    for extra in ({"raw": "x"}, {"expected_fingerprint": "v2:0"}, {"key": "Kaha12"}):
        assert site.raw("POST", "/api/edit/save", site.headers(post=True), json=dict(preview=preview["preview"], **extra)).status_code == 400
    saved = site.ok("post", "/api/edit/save", {"preview": preview["preview"]})
    assert saved["written"] == ["Kaha12"] and saved["refused"] == [] and saved["renamed"] == {}
    assert text(site.ws) == before.replace(KAHA12, edited)
    assert Path(saved["saved_copy"]).read_text(encoding="utf-8") == before               # the file as it was
    assert site.ok("get", "/api/entries")["rows"][0][3] == "2013"
    assert site.post("/api/edit/save", {"preview": preview["preview"]})[1]["kind"] == "NotFound"      # a preview is used once


def test_a_new_entry_a_key_in_use_and_a_file_that_changed_since_the_preview(site):
    before = text(site.ws)
    new = site.ok("post", "/api/edit/preview", {"key": None, "raw": ZOLL90})
    assert new["key"] is None and new["new_key"] == "Zoll90" and new["problems"] == [] and new["fingerprint"] is None
    taken = site.ok("post", "/api/edit/preview", {"key": None, "raw": ZOLL90.replace("{Zoll90,", "{Kaha12,")})
    assert taken["problems"] and text(site.ws) == before
    result, error = site.post("/api/edit/save", {"preview": taken["preview"]})
    assert error["kind"] == "EditRefused" and text(site.ws) == before
    broken = site.ok("post", "/api/edit/preview", {"key": "Kaha12", "raw": "@book{Kaha12, title = {never closed}"})
    assert broken["problems"] and site.post("/api/edit/save", {"preview": broken["preview"]})[1]["kind"] == "EditRefused"

    stale = site.ok("post", "/api/edit/preview", {"key": "Kaha12", "raw": KAHA12.replace("{2012}", "{2014}")})
    site.ws.bib.write_text(before.replace("Foundations of human memory", "Foundations of human memory, revised"), encoding="utf-8")
    result, error = site.post("/api/edit/save", {"preview": stale["preview"]})
    assert error["kind"] == "EditRefused" and "{2014}" not in text(site.ws) and "revised" in text(site.ws)

    saved = site.ok("post", "/api/edit/save", {"preview": new["preview"]})
    assert saved["written"] == ["Zoll90"] and text(site.ws).rstrip().endswith(ZOLL90)
    assert keys(site.ws) == ["Kaha12", "Game62", "TeneEtal11", "Zoll90"]


# --- approval and revocation --------------------------------------------------------------------

def test_approve_and_revoke_under_the_gh_login_of_the_server(tmp_path, monkeypatch):
    from cdlbib import identity
    try:
        me = identity.current()
    except IdentityUnavailable as exc:
        pytest.skip(f"no GitHub login for a real approval: {exc}")
    running, site = _site(tmp_path, monkeypatch, home=False)       # gh's login is kept under the real HOME
    try:
        assert site.ok("get", "/api/session")["identity"] is None                          # nothing is asked until asked for
        shown = site.ok("post", "/api/identity/check")
        assert shown["available"] is True and shown["detail"] == me.handle
        assert site.ok("get", "/api/session")["identity"]["detail"] == me.handle
        opened = site.ok("get", "/api/entry", key="Kaha12")
        body = {"key": "Kaha12", "fingerprint": opened["fingerprint"], "source": "the book itself", "note": "title page checked"}
        for name in ("reviewer", "login", "github_login", "database"):                     # the browser names no reviewer
            assert site.raw("POST", "/api/approve", site.headers(post=True), json=dict(body, **{name: "someone"})).status_code == 400
        assert site.post("/api/approve", dict(body, fingerprint="v2:" + "0" * 64))[1]["kind"] == "ApprovalRefused"
        assert site.post("/api/approve", dict(body, note=" "))[1]["kind"] == "ApprovalRefused"
        assert site.ok("get", "/api/entry", key="Kaha12")["result"]["status"] == "pending"
        stored = site.ok("post", "/api/approve", body)["stored"]
        assert stored["human_review"]["reviewer"] == me.handle and stored["human_review"]["github_id"] == me.id
        approved = api.entry(site.ws, "Kaha12")
        assert approved.status == "human_verified" and approved.human_review["source"] == "the book itself"
        assert approved.human_review["github_login"] == me.login
        assert [item["key"] for item in site.ok("get", "/api/review-queue", all="1")["entries"]] == ["TeneEtal11"]
        assert site.post("/api/revoke", {"key": "Kaha12", "fingerprint": "v2:" + "0" * 64, "reason": "x"})[1]["kind"] == "ApprovalRefused"
        revoked = site.ok("post", "/api/revoke", {"key": "Kaha12", "fingerprint": opened["fingerprint"], "reason": "wrong edition"})
        assert revoked["status"] == "needs_review" and len(revoked["records"]) == 1
        after = api.entry(site.ws, "Kaha12")
        assert after.status == "needs_review" and after.revoked_approval["reason"] == "wrong edition"
        assert after.revoked_approval["revoked_by"] == me.handle
    finally:
        running.stop()


def test_without_a_login_nothing_is_approved(site):
    """HOME is the test's own here, so gh has no login: the check says so and an approval is refused."""
    shown = site.ok("post", "/api/identity/check")
    if shown["available"]:
        pytest.skip("gh reports a login even with a HOME of the test's own (a token in the environment)")
    assert shown["available"] is False and shown["how"]
    opened = site.ok("get", "/api/entry", key="Kaha12")
    result, error = site.post("/api/approve", {"key": "Kaha12", "fingerprint": opened["fingerprint"], "source": "s", "note": "n"})
    assert error["kind"] == "IdentityUnavailable" and api.entry(site.ws, "Kaha12").status == "pending"


# --- checks -------------------------------------------------------------------------------------

def test_checks_of_the_format_of_chosen_entries_and_of_the_changed_ones(site):
    clean = site.ok("post", "/api/check/format")
    assert set(clean) == {"ok", "failure", "errors", "corrections", "log"} and clean["failure"] == ""
    site.ws.bib.write_text(text(site.ws).replace("Pages = {1--11}", "Pages = {1-11}"), encoding="utf-8")
    found = site.ok("post", "/api/check/format")
    assert found["ok"] is False and "Game62" in found["errors"] and found["corrections"]["Game62"]["pages"] == "1--11"
    site.ws.bib.write_text(text(site.ws).replace("Pages = {1-11}", "Pages = {1--11}"), encoding="utf-8")

    lines = []
    checked = site.ok("post", "/api/check/keys", {"keys": ["Game62"]}, lines)
    assert checked["citations"]["checked"] == {"Game62": {"status": "metadata_verified", "issues": []}}
    assert checked["citations"]["ok"] is True and checked["citations"]["lines"] == [line for line in lines if line in checked["citations"]["lines"]]
    assert any(line.startswith("citations: 1 of 1 chosen entries verified") for line in lines)
    assert api.entry(site.ws, "Game62").status == "metadata_verified"
    result, error = site.post("/api/check/keys", {"keys": ["Game62", "Nope99"]})
    assert error["kind"] == "GateFailed"
    # the changed entries are those that differ from the GitHub master, which cannot be fetched here
    result, error = site.post("/api/check/changed")
    assert error["kind"] == "GateFailed" and "reference" in error["message"].lower()


# --- adding -------------------------------------------------------------------------------------

def test_add_by_identifier_then_accept(site):
    before = text(site.ws)
    lines = []
    found = site.ok("post", "/api/add/identifiers", {"queries": [pdfs.ZOLLER_DOI]}, lines)
    assert found["errors"] == [] and len(found["proposals"]) == 1 and lines == [f"{pdfs.ZOLLER_DOI}: metadata_verified"]
    proposal = found["proposals"][0]
    assert proposal["proposed_raw"] == ZOLL90 and proposal["key_proposed"] == "Zoll90" and proposal["status"] in ACCEPTED
    assert proposal["acceptable"] is True and proposal["cannot_accept"] is None and not proposal["manual"]
    assert {change["field"]: change["source"] for change in proposal["changes"]}["journal"] == "crossref"
    assert text(site.ws) == before                                         # a proposal writes nothing
    assert site.ok("get", "/api/proposal", proposal=proposal["id"])["proposed_raw"] == ZOLL90
    # the decision carries the id only
    assert site.raw("POST", "/api/proposal/accept", site.headers(post=True),
                    json={"proposal": proposal["id"], "proposed_raw": "@article{Evil1,}"}).status_code == 400
    done = site.ok("post", "/api/proposal/accept", {"proposal": proposal["id"]})
    assert done["written"] == ["Zoll90"] and done["refused"] == []
    assert text(site.ws) == before + ZOLL90 + "\n\n" or text(site.ws).rstrip().endswith(ZOLL90)
    assert keys(site.ws) == ["Kaha12", "Game62", "TeneEtal11", "Zoll90"]
    assert site.get("/api/proposal", proposal=proposal["id"])[1]["kind"] == "NotFound"       # used
    assert site.post("/api/proposal/accept", {"proposal": proposal["id"]})[1]["kind"] == "NotFound"
    # the same work again is now a duplicate, and is not accepted
    again = site.ok("post", "/api/add/identifiers", {"queries": [pdfs.ZOLLER_DOI]})["proposals"][0]
    assert again["duplicate_of"] == "Zoll90" and again["acceptable"] is False and again["cannot_accept"]
    result, error = site.post("/api/proposal/accept", {"proposal": again["id"]})
    assert error["kind"] == "CdlbibError" and error["message"] == again["cannot_accept"]
    assert keys(site.ws) == ["Kaha12", "Game62", "TeneEtal11", "Zoll90"]


def test_add_by_search_choose_edit_recheck_and_skip(site):
    before = text(site.ws)
    found = site.ok("post", "/api/add/search", {"title": "Attention is all you need", "authors": ["Vaswani"]})
    assert found["errors"] == [] and found["items"] and ID.fullmatch(found["search"])
    index = next(n for n, lead in enumerate(found["items"]) if lead.get("arxiv") == pdfs.ARXIV_ID)
    assert found["items"][index]["in_library"] is None
    assert site.post("/api/add/choose", {"search": found["search"], "index": 999})[1]["kind"] == "BadRequest"
    chosen = site.ok("post", "/api/add/choose", {"search": found["search"], "index": index})
    proposal = chosen["proposals"][0]
    raw = proposal["proposed_raw"]
    assert raw.startswith("@article{VaswEtal") and "Attention is all you need" in raw and text(site.ws) == before

    result, error = site.post("/api/proposal/recheck", {"proposal": proposal["id"], "raw": "this is not an entry"})
    assert error["kind"] == "EditedEntryParseError"
    assert site.ok("get", "/api/proposal", proposal=proposal["id"])["proposed_raw"] == raw      # the proposal is as it was
    edited = raw.replace("Attention is all you need", "Attention is all you really need")
    again = site.ok("post", "/api/proposal/recheck", {"proposal": proposal["id"], "raw": edited})
    assert again["id"] != proposal["id"] and again["proposed_raw"] == edited and again["superseded"] is None
    # the version that was rechecked is not changed, only superseded, and no decision is taken on it any more
    old = site.ok("get", "/api/proposal", proposal=proposal["id"])
    assert old["proposed_raw"] == raw and old["superseded"] == again["id"]
    for path in ("/api/proposal/accept", "/api/proposal/skip", "/api/proposal/remove-duplicate"):
        result, error = site.post(path, {"proposal": proposal["id"]})
        assert error["kind"] == "StaleProposal" and error["current"] == again["id"], path
    result, error = site.post("/api/proposal/recheck", {"proposal": proposal["id"], "raw": raw})
    assert error["kind"] == "StaleProposal" and text(site.ws) == before
    proposal = again
    assert [(c["field"], c["source"]) for c in again["changes"] if c["source"] == "user edit"] == [("title", "user edit")]
    assert again["status"] not in ACCEPTED                                  # the source no longer agrees with the title
    assert site.ok("post", "/api/proposal/skip", {"proposal": proposal["id"]}) == {"skipped": proposal["id"]}
    assert site.post("/api/proposal/accept", {"proposal": proposal["id"]})[1]["kind"] == "NotFound"
    assert text(site.ws) == before


def test_accept_remaining_writes_the_proposals_that_need_no_decision(site):
    before = keys(site.ws)
    found = site.ok("post", "/api/add/identifiers", {"queries": [pdfs.ZOLLER_DOI, "arXiv:" + pdfs.ARXIV_ID]})
    first, second = found["proposals"]
    assert first["acceptable"] and second["acceptable"] and not first["needs_decision"]
    dup = site.ok("post", "/api/add/identifiers", {"queries": ["10.1037/h0041332"]})["proposals"][0]     # Game62: in the library
    assert dup["duplicate_of"] == "Game62" and not dup["acceptable"]
    wanted = [item["id"] for item in (first, second) if not item["needs_decision"]]
    done = site.ok("post", "/api/proposal/accept-remaining", {"proposals": [first["id"], second["id"], dup["id"]]})
    assert done["accepted"] == wanted and len(done["written"]) == len(wanted) and "Zoll90" in done["written"]
    assert done["stale"] == []
    assert keys(site.ws) == before + done["written"]
    assert site.ok("get", "/api/proposal", proposal=dup["id"])["duplicate_of"] == "Game62"      # left for a decision
    assert site.post("/api/proposal/accept-remaining", {"proposals": ["A" * 22]})[1]["kind"] == "NotFound"


def test_add_from_a_pdf_with_an_identifier(site, made):
    before = keys(site.ws)
    data = made["doi"].read_bytes()
    sent = site.ok("upload", "/api/pdf/upload", data, "application/pdf")
    assert site.post("/api/pdf/lookup", {"pdf": sent["pdf"]})[1]["kind"] == "BadRequest"       # not read yet
    lines = []
    read = site.ok("post", "/api/pdf/read", {"pdf": sent["pdf"]}, lines)
    assert read["pdf"] == sent["pdf"] and read["problem"] is None and "path" not in read
    assert read["identifiers"][0] == {"kind": "doi", "value": pdfs.ZOLLER_DOI, "page": 1,
                                      "quote": "J. Res. Sci. Teach. 27(10), 1053–1065 (1990) DOI: " + pdfs.ZOLLER_DOI}
    assert read["title_source"] == "largest text on page 1" and len(read["pages"]) == 2
    served = site.raw("GET", f"/api/pdf/{sent['pdf']}/file", site.headers())
    assert served.content == data and served.headers["Content-Type"] == "application/pdf"
    assert site.raw("GET", f"/api/pdf/{sent['pdf']}/file").status_code == 401                 # the preview needs the token too
    found = site.ok("post", "/api/pdf/lookup", {"pdf": sent["pdf"]})
    assert found["matched"] and found["found_by"]["kind"] == "doi" and found["tried"] == [f"doi {pdfs.ZOLLER_DOI}: record found"]
    proposal = found["proposal"]
    assert proposal["proposed_raw"] == ZOLL90 and proposal["pdf"] == sent["pdf"] and proposal["acceptable"]
    assert proposal["notes"][0] == f"Found by the doi read from the PDF (page 1): {pdfs.ZOLLER_DOI}"
    done = site.ok("post", "/api/proposal/accept", {"proposal": proposal["id"]})
    assert done["written"] == ["Zoll90"] and keys(site.ws) == before + ["Zoll90"]


def test_the_first_page_of_an_uploaded_pdf_as_an_image(site, made):
    pytest.importorskip("pypdfium2", reason="the pdf extra (pypdfium2) is not installed: no page is drawn")
    sent = site.ok("upload", "/api/pdf/upload", made["doi"].read_bytes(), "application/pdf")
    png = base64.b64decode(site.ok("post", "/api/pdf/page", {"pdf": sent["pdf"]})["png"])
    assert png == api.render_first_page(made["doi"]) and png.startswith(b"\x89PNG\r\n\x1a\n")
    assert site.post("/api/pdf/page", {"pdf": "A" * 22})[1]["kind"] == "NotFound"


def test_a_pdf_no_source_knows_model_routes_and_the_manual_form(site, made):
    before = keys(site.ws)
    sent = site.ok("upload", "/api/pdf/upload", made["unknown"].read_bytes(), "application/pdf")
    read = site.ok("post", "/api/pdf/read", {"pdf": sent["pdf"]})
    assert read["identifiers"] == [] and read["title_guess"] == pdfs.UNKNOWN_TITLE
    found = site.ok("post", "/api/pdf/lookup", {"pdf": sent["pdf"]})
    assert not found["matched"] and found["proposal"] is None and "No source record was found" in found["message"]
    assert found["prefill"] == {"title": pdfs.UNKNOWN_TITLE}

    listed = site.ok("get", "/api/model-routes")["routes"]
    assert [(route["name"], route["default"], route["available"]) for route in listed] == [("dartmouth", True, None), ("openai", False, None)]
    assert all(route["how"] for route in listed)                            # shown whether or not the route is set up
    checked = site.ok("post", "/api/model-routes/check", {"route": "dartmouth"})["routes"]
    assert checked[0]["available"] is False and checked[1]["available"] is None      # only the one asked about was looked up
    result, error = site.post("/api/pdf/model", {"pdf": sent["pdf"], "route": "dartmouth"})
    assert error["kind"] == "SecretNotFound" and "Dartmouth Chat is not set up" in error["message"]

    form = site.ok("get", "/api/add/form")
    assert "article" in form["types"] and {"title", "author", "year", "journal"} <= set(form["fields"])
    assert site.ok("get", "/api/pdf/prefill", pdf=sent["pdf"])["fields"] == {"title": pdfs.UNKNOWN_TITLE}
    typed = {"author": "A Q Example and B R Sample", "year": "2019", "journal": "Annals of Improbable Lattices",
             "volume": "12", "pages": "45--67"}
    without = site.ok("post", "/api/add/manual", {"entry_type": "article", "fields": typed, "pdf": sent["pdf"], "omit": ["title"]})
    assert "Title" not in (without["proposed_raw"] or "") and not without["acceptable"]
    draft = site.ok("post", "/api/add/manual", {"entry_type": "article", "fields": typed, "pdf": sent["pdf"]})
    assert draft["manual"] is True and draft["status"] == "needs_review" and draft["record_source"] is None
    sources = {change["field"]: change["source"] for change in draft["changes"]}
    assert sources["title"] == "read from the PDF (not typed)" and sources["author"] != sources["title"]
    assert "Plorbnix dynamics" in draft["proposed_raw"] and draft["acceptable"]
    done = site.ok("post", "/api/proposal/accept", {"proposal": draft["id"]})
    key = done["key"]
    assert done["written"] == [key] and done["evidence_stored"] is None and keys(site.ws) == before + [key]
    written = api.entry(site.ws, key)
    assert written.status not in ACCEPTED and written.human_review is None        # a typed draft is no verification
    assert [item["key"] for item in site.ok("get", "/api/review-queue", all="1")["entries"]][-1] == key


def test_a_model_reading_is_accepted_with_its_evidence_and_is_no_approval(site, made):
    """Everything after the model's answer. The proposal is the real one that
    intake.proposal_from_findings builds (each quotation checked against the PDF's pages) from
    an adapter answer of the shape tests/test_intake_model.py uses, kept in the server's store
    as /api/pdf/model keeps it; the model call itself is made by the next test when a key exists."""
    from cdlbib import intake
    from cdlbib.source_passages import materialize
    from cdlbib.web import routes
    from test_intake_model import EXPECTED, SELECTED
    before = keys(site.ws)
    sent = site.ok("upload", "/api/pdf/upload", made["unknown"].read_bytes(), "application/pdf")
    site.ok("post", "/api/pdf/read", {"pdf": sent["pdf"]})
    read = site.running.app.store.get("pdf", sent["pdf"])["intake"]
    answer = materialize({"fields": SELECTED, "uncertainties": ["The issue number is not printed."]}, read.pages[:intake.MODEL_PAGES])
    answer["provider_trace"] = {"provider": "test selection", "model": None}
    kept = routes.keep(site.running.app, intake.proposal_from_findings(site.ws, read, answer, "dartmouth"), pdf=sent["pdf"])

    shown = site.ok("get", "/api/proposal", proposal=kept["id"])
    assert shown["proposed_raw"] == EXPECTED and shown["manual"] and shown["status"] == "needs_review" and shown["needs_decision"]
    assert shown["evidence"]["pdf_sha256"] == read.sha256 and shown["evidence"]["fields"]["year"]["page"] == 1
    assert all(change["source"].startswith("model reading, p.1: ") for change in shown["changes"])
    assert site.ok("get", "/api/pdf/prefill", pdf=sent["pdf"], model=kept["id"])["fields"]["journal"] == "Annals of Improbable Lattices"
    # a proposal that needs a decision is never taken with "the remaining ones"
    assert site.ok("post", "/api/proposal/accept-remaining", {"proposals": [kept["id"]]})["accepted"] == []
    assert keys(site.ws) == before
    done = site.ok("post", "/api/proposal/accept", {"proposal": kept["id"]})
    assert done["written"] == ["ExamSamp19"] and done["evidence_stored"] is True and keys(site.ws) == before + ["ExamSamp19"]
    detail = site.ok("get", "/api/entry", key="ExamSamp19")
    assert detail["raw"] == EXPECTED and detail["fingerprint"] == done["fingerprint"]
    assert detail["result"]["status"] == "needs_review" and "human_review" not in detail["result"]      # evidence, not approval
    assert "2019" in detail["result"]["external_evidence"]["fields"]["year"]["quote"]
    assert "ExamSamp19" in [item["key"] for item in site.ok("get", "/api/review-queue", all="1")["entries"]]


def test_a_real_model_reading_through_the_server(tmp_path, monkeypatch, made):
    from cdlbib import secrets
    from cdlbib.errors import SecretNotFound
    try:
        secrets.get("dartmouth-chat")
    except SecretNotFound as exc:
        pytest.skip(f"no Dartmouth Chat key here, so no real model run: {exc}")
    key = os.environ.get(secrets.KEYS["dartmouth-chat"].env)
    running, site = _site(tmp_path, monkeypatch, home=False)         # the keychain and the way to the model are the real ones
    if key:
        monkeypatch.setenv(secrets.KEYS["dartmouth-chat"].env, key)
    try:
        sent = site.ok("upload", "/api/pdf/upload", made["unknown"].read_bytes(), "application/pdf")
        site.ok("post", "/api/pdf/read", {"pdf": sent["pdf"]})
        assert site.ok("post", "/api/model-routes/check", {"route": "dartmouth"})["routes"][0]["available"] is True
        lines = []
        proposal = site.ok("post", "/api/pdf/model", {"pdf": sent["pdf"], "route": "dartmouth"}, lines)
        assert "Dartmouth Chat" in lines[0] and proposal["manual"] and proposal["status"] == "needs_review"
        assert proposal["evidence"]["provider_trace"]["extract"]["provider"] == "dartmouth" and proposal["pdf"] == sent["pdf"]
        assert pdfs.UNKNOWN_TITLE.lower() in proposal["proposed_raw"].lower()
        assert all(change["source"].startswith("model reading, p.") for change in proposal["changes"])
        assert keys(site.ws) == ["Kaha12", "Game62", "TeneEtal11"]                    # a reading writes nothing
    finally:
        running.stop()


# --- the managed library: state, update, backups, undo ------------------------------------------

@pytest.fixture
def managed(tmp_path, monkeypatch):
    """The managed library, downloaded from the test's own upstream, with an unsent edit; the
    upstream then gains a commit. Gives (client, upstream)."""
    web.isolate(monkeypatch, tmp_path / "env")
    monkeypatch.chdir(tmp_path)
    ws = api.ensure_library()
    assert api.is_managed(ws) and text(ws) == ZOLL90 + "\n"
    ws.bib.write_text(ZOLL90 + "\n\n" + KAHA12 + "\n", encoding="utf-8")                  # an edit that was not sent
    upstream = Path(os.environ["CDLBIB_UPSTREAM"])
    advance(upstream, "A second entry", **{"cdl.bib": TENE11 + "\n\n" + ZOLL90 + "\n"})
    running, client = web.start(ws)
    client.ws = ws
    yield client, upstream
    running.stop()
    assert running.app.worker.overlaps == 0


def test_state_update_with_unsent_edits_backups_and_undo(managed):
    site, upstream = managed
    edited = text(site.ws)
    assert site.ok("get", "/api/session")["managed"] is True
    state = site.ok("get", "/api/state")
    assert state["managed"] and state["origin"] == "managed" and state["pending"] == ["cdl.bib"] and state["new_commits"] == 0
    fresh = site.ok("post", "/api/state/refresh")
    assert (fresh["new_commits"], fresh["new_entries"], fresh["refreshed"]) == (1, 1, True) and text(site.ws) == edited

    result, error = site.post("/api/update")
    assert result is None and error["kind"] == "UpdateNeedsDecision" and text(site.ws) == edited      # nothing changed, nothing asked
    assert error["choices"] == ["keep", "update", "send", "discard"] and error["new_commits"] == 1 and error["changed"] == ["cdl.bib"]
    assert error["question"].startswith("A newer version of the bibliography is available (1 new commit), and you have "
                                        "changes that have not been sent:")
    assert error["answers"] == {choice: prompts.ANSWERS[choice][1] for choice in error["choices"]}
    assert all(prompts.ANSWERS[choice][1] in error["question"] for choice in error["choices"])
    assert "seen" not in error and ID.fullmatch(error["decision"])
    assert site.raw("POST", "/api/update/decide", site.headers(post=True),
                    json={"decision": error["decision"], "choice": "update", "seen": "x"}).status_code == 400

    done = site.ok("post", "/api/update/decide", {"decision": error["decision"], "choice": "update"})
    assert done["decision"] == "update" and done["action"] == "updated" and done["message"]
    assert set(keys(site.ws)) == {"TeneEtal11", "Zoll90", "Kaha12"}                        # the upstream's entry and the edit
    assert site.post("/api/update/decide", {"decision": error["decision"], "choice": "update"})[1]["kind"] == "NotFound"
    assert [row[0] for row in site.ok("get", "/api/entries")["rows"]] == keys(site.ws)

    saved = site.ok("get", "/api/backups")
    assert saved["backups"] and saved["root"] == str(site.ws.root) and saved["unreadable"] == []
    stamp = saved["backups"][0]["stamp"]
    assert saved["backups"][0]["changed"] == 1 and re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z", stamp)
    for bad in ("20200101T000000.000000Z", "nothing"):
        assert site.post("/api/undo", {"stamp": bad})[1]["kind"] == "BadRequest"
    undone = site.ok("post", "/api/undo", {"stamp": stamp})
    assert undone["restored"]["stamp"] == stamp and text(site.ws) == edited              # the edit, as it was before the update
    assert len(site.ok("get", "/api/backups")["backups"]) == 2
    again = site.ok("post", "/api/undo")                                                    # undoing the undo
    assert again["restored"]["stamp"] == undone["before"]["stamp"] and set(keys(site.ws)) == {"TeneEtal11", "Zoll90", "Kaha12"}


@pytest.mark.parametrize("choice", ["keep", "discard"])
def test_keeping_or_discarding_unsent_edits_is_an_explicit_choice(managed, choice):
    site, upstream = managed
    edited = text(site.ws)
    error = site.post("/api/update")[1]
    assert error["kind"] == "UpdateNeedsDecision"
    assert site.post("/api/update/decide", {"decision": error["decision"], "choice": "merge"})[1] is not None
    done = site.ok("post", "/api/update/decide", {"decision": error["decision"], "choice": choice})
    if choice == "keep":
        assert text(site.ws) == edited and done["action"] == "left_alone"
    else:
        assert text(site.ws) == TENE11 + "\n\n" + ZOLL90 + "\n"
        site.ok("post", "/api/undo")                                         # "they are saved first"
        assert text(site.ws) == edited


# --- setup, the TeX link, export ----------------------------------------------------------------

def test_setup_reports_passively_and_checks_only_what_is_asked(site):
    report = site.ok("get", "/api/setup")
    assert [item["name"] for item in report["features"]] == [item.name for item in api.features()]
    found = {item["name"]: item for item in report["features"]}
    assert found["gh login"]["available"] in (None, False) and found["Dartmouth Chat key"]["available"] is None
    assert found["git"]["available"] is True and found["Dartmouth Chat key"]["how"]
    assert report["where"]["root"] == str(site.ws.root) and report["chosen_by"] == prompts.CHOSEN_BY[report["where"]["origin"]]
    assert report["tex"]["state"] in ("absent", "no_tex") and report["tex"]["bibinputs_line"]
    lines = []
    checked = site.ok("post", "/api/setup/check", {"probe": "dartmouth-chat"}, lines)
    after = {item["name"]: item for item in checked["features"]}
    assert after["Dartmouth Chat key"]["available"] is False and after["OpenAI key"]["available"] is None
    assert after["gh login"]["available"] == found["gh login"]["available"] and lines


def test_the_tex_link_is_made_and_removed_in_the_tests_own_tree(site, tmp_path):
    if not shutil.which("kpsewhich"):
        pytest.skip("kpsewhich is not installed (the link is proven with the real program)")
    link = tmp_path / "env" / "texmf" / "bibtex" / "bib" / "cdl.bib"
    made = site.ok("post", "/api/tex/link")
    assert made["state"] == "linked" and Path(made["link"]) == link and os.readlink(link) == str(site.ws.bib)
    assert Path(made["resolves_to"]).resolve() == site.ws.bib
    assert site.ok("get", "/api/setup")["tex"]["state"] == "linked"
    gone = site.ok("post", "/api/tex/unlink")
    assert gone["removed"] is True and not os.path.lexists(link)
    link.write_text("someone else's file\n", encoding="utf-8")
    result, error = site.post("/api/tex/link")
    assert error["kind"] == "TexLinkRefused" and link.read_text(encoding="utf-8") == "someone else's file\n"
    replaced = site.ok("post", "/api/tex/link", {"replace": True})
    assert replaced["state"] == "linked" and os.readlink(link) == str(site.ws.bib)
    aside = [path for path in link.parent.iterdir() if path.name.startswith("cdl.bib.cdlbib-saved-")]
    assert len(aside) == 1 and aside[0].read_text(encoding="utf-8") == "someone else's file\n"


def test_export_from_an_uploaded_aux_file(site):
    before = {path: path.read_bytes() for path in site.ws.root.rglob("*") if path.is_file() and ".bibcheck" not in path.parts}
    aux = "\\relax\n\\citation{Game62}\n\\citation{Nope99}\n\\bibstyle{plain}\n\\bibdata{cdl}\n"
    sent = site.ok("upload", "/api/export/upload", aux.encode(), "application/octet-stream", name="paper.aux")
    assert sent["name"] == "paper.aux" and sent["files"] == ["paper.aux"]
    for name in ("out", "outfile", "force", "engine", "inputs", "path"):
        assert site.raw("POST", "/api/export/run", site.headers(post=True), json={"bundle": sent["bundle"], name: "x"}).status_code == 400
    made = site.ok("post", "/api/export/run", {"bundle": sent["bundle"]})
    assert (made["written"], made["cited"], made["missing"], made["read_from"]) == (1, 2, ["Nope99"], "the .aux file")
    assert made["name"] == "cdl.bib" and ID.fullmatch(made["export"])
    served = site.raw("GET", f"/api/export/{made['export']}/file", site.headers())
    assert served.status_code == 200 and served.headers["Content-Disposition"] == 'attachment; filename="cdl.bib"'
    assert served.content.decode("utf-8").strip() == GAME62
    assert site.raw("GET", f"/api/export/{made['export']}/file").status_code == 401
    after = {path: path.read_bytes() for path in site.ws.root.rglob("*") if path.is_file() and ".bibcheck" not in path.parts}
    assert after == before                                                   # nothing was written in the library
    assert site.post("/api/export/run", {"bundle": sent["bundle"], "main": "other.aux"})[1]["kind"] == "BadRequest"


def test_export_from_uploaded_tex_files_that_include_one_another(site):
    kind = "application/octet-stream"
    main = ("\\documentclass{article}\n\\begin{document}\nAs shown \\cite{TeneEtal11}.\n\\input{intro}\n"
            "\\bibliographystyle{plain}\n\\bibliography{cdl}\n\\end{document}\n")
    first = site.ok("upload", "/api/export/upload", main.encode(), kind, name="main.tex")
    second = site.ok("upload", "/api/export/upload", b"See also \\cite{Kaha12}.\n", kind, name="intro.tex", bundle=first["bundle"])
    assert second["files"] == ["main.tex", "intro.tex"]
    made = site.ok("post", "/api/export/run", {"bundle": first["bundle"], "main": "main.tex"})
    assert made["cited"] == 2 and made["written"] == 2 and made["missing"] == []
    assert made["read_from"] in ("a fresh LaTeX run of the paper", "the .tex source")
    got = site.raw("GET", f"/api/export/{made['export']}/file", site.headers()).content.decode("utf-8")
    assert KAHA12 in got and TENE11 in got and "Game62" not in got and got.index("Kaha12") < got.index("TeneEtal11")
    session = site.ok("get", "/api/session")
    assert "--bbl" in session["no_bbl"]                                      # a .bbl is not offered here; the page says how
    assert not [route for route in web.server.routes.ROUTES if "bbl" in route.path or "bbl" in route.api]


# --- sending ------------------------------------------------------------------------------------

def test_a_send_that_cannot_pass_changes_nothing(site, tmp_path):
    """The library becomes a real checkout with an unsent edit. Without the network the gate
    cannot compare with the GitHub master, so the send stops with the core's typed refusal."""
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@cdlbib.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@cdlbib.invalid")

    def git(*args):
        return subprocess.run(["git", *args], cwd=site.ws.root, env=env, capture_output=True, text=True, check=True).stdout.strip()

    git("init", "--quiet")
    git("symbolic-ref", "HEAD", "refs/heads/master")
    git("config", "user.name", "cdlbib tests")              # the checkout has an author: the send gets as far as its gate
    git("config", "user.email", "tests@cdlbib.invalid")
    git("add", "cdl.bib")
    git("commit", "--quiet", "-m", "start")
    site.ws.bib.write_text(text(site.ws).replace("human memory}", "human memories}"), encoding="utf-8")
    state = site.ok("get", "/api/state")
    assert state["branch"] == "master" and state["pending"] == ["cdl.bib"] and state["managed"] is False
    head, edited = git("rev-parse", "HEAD"), text(site.ws)
    for name in ("citations", "reference", "database", "upstream", "fork", "outfile", "base", "mailto", "verbose"):
        assert site.raw("POST", "/api/send", site.headers(post=True), json={name: False}).status_code == 400
    lines = []
    result, error = site.post("/api/send", {"summary": "A new year for Kahana"}, lines)
    # the gate itself stops it: the format check passes, the citation check cannot reach its reference
    assert result is None and error["kind"] == "GateFailed", error
    assert error["message"].startswith("citation check failed: ") and "check" not in error
    assert lines == ["format: looks good!"]
    # nothing was committed, no branch was made, nothing was pushed (there is nowhere to push to), no file changed
    assert git("rev-parse", "HEAD") == head and git("branch", "--list") == "* master" and text(site.ws) == edited
    assert git("status", "--porcelain", "--untracked-files=no") == "M cdl.bib" and git("remote") == ""
    assert git("for-each-ref", "--format=%(refname)") == "refs/heads/master" and git("stash", "list") == ""
    result, error = site.post("/api/send/offers", {"restart": True})
    assert error["kind"] == "CdlbibError" and text(site.ws) == edited
