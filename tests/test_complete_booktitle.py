"""A chapter record with a series title and a book title (owner's decision 2026-10-06: "Try
to resolve automatically through llm-driven web search").

``container_titles`` first asks the records the project already uses (the book's own
Crossref record and its Library of Congress record, found by the chapter's ISBNs) and only
then a model, which may do no more than choose between the record's two titles.

Nothing here is invented, and no test calls a model service unless ``CDLBIB_TEST_LIVE_MODEL=1``
is set. The lookups are real responses fetched once on 2026-10-06 by
tests/fixtures/intake/record.py (``chapters``, ``books``) and replayed through the real client
over a transport that refuses every request. The model reading is one real answer of the
Dartmouth Chat adapter's ``extract`` phase to the lines of the chapter's real page at its
publisher, recorded once by ``record.py booktitle`` (``booktitle_model.json``) and replayed.

The chapters, all real: Scha03 and Mann23 (Springer) and MayeEtal92b (Elsevier) of the frozen
library, whose book has a Crossref record of its own; and Whitehouse 2004 in Progress in Brain
Research (10.1016/s0079-6123(03)45022-x), whose record carries no ISBN, so no record decides.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from cdlbib import complete, container_titles as ct, deps
from cdlbib.verification import load_entries

from conftest import live_model
from intake_support import FIXTURES, offline_client

ROOT = Path(__file__).resolve().parents[1]
FROZEN = load_entries(ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib")
SCHA03, MANN23, MAYE92, WHIT04 = ("10.1007/978-0-387-21579-2_9", "10.1007/978-3-031-20910-9_48",
                                  "10.1016/s0166-4115(08)60886-9", "10.1016/s0079-6123(03)45022-x")
RECORDED = json.loads((FIXTURES / "booktitle_model.json").read_text(encoding="utf-8"))
SERIES, BOOK = "Studies in Neuroscience, Psychology and Behavioral Economics", "Intracranial EEG"
NO_ROUTE = {}     # an explicit configuration with no key: the keychain is not read (cdlbib.secrets)


@pytest.fixture
def client(tmp_path):
    client = offline_client(tmp_path / "cache", "chapters.json.gz")
    yield client
    client.cache.close()


def record_of(client, doi):
    return deepcopy(client.crossref_doi(doi)["body"]["message"])


def propose(client, doi, **options):
    return complete.propose(complete.Query.parse(doi), client, client.cache, **options)


def change(proposal, name):
    return next(c for c in proposal.changes if c.field == name)


def unfilled(proposal, name):
    return next(u for u in proposal.unfilled if u.field == name)


# --- which records are meant -------------------------------------------------------------------

def test_only_a_chapter_record_with_two_different_titles_is_looked_into(client):
    record = record_of(client, SCHA03)
    assert ct.two_titles(record) == ("Lecture Notes in Statistics", "Nonlinear Estimation and Classification")
    assert ct.two_titles(dict(record, **{"container-title": ["Nonlinear Estimation and Classification"]})) is None
    assert ct.two_titles(dict(record, **{"container-title": ["A", "B", "C"]})) is None
    assert ct.two_titles(dict(record, **{"container-title": ["Same title", "Same Title"]})) is None
    assert ct.two_titles(dict(record, type="journal-article")) is None
    assert ct.resolve(dict(record, type="journal-article"), client, environ=NO_ROUTE) is None
    # the choice is between the two strings and nothing else
    assert ct.decide(("A book", "A series"), ["A Book"]) == "A book"
    assert ct.decide(("A book", "A series"), ["Another book"]) is None
    assert ct.decide(("A book", "A series"), ["A book", "A series"]) is None
    assert client.requests == 0


# --- step 1: the book's own Crossref record -----------------------------------------------------

def test_the_books_own_crossref_record_says_which_title_is_the_books(client):
    proposal = propose(client, SCHA03, allow_model=False)
    # byte for byte the library's entry (which has no publisher, address or editor)
    assert proposal.proposed_raw == FROZEN["Scha03"]["raw"] and proposal.status == "metadata_verified"
    assert change(proposal, "booktitle") == complete.FieldChange(
        "booktitle", None, "Nonlinear Estimation and Classification", "crossref (the book's own Crossref record)",
        "filled")
    assert proposal.notes == [
        'booktitle: the record names two titles, "Lecture Notes in Statistics" and "Nonlinear Estimation and '
        'Classification"; "Nonlinear Estimation and Classification" is taken as the book\'s. The book\'s own Crossref '
        'record (10.1007/978-0-387-21579-2, ISBN 9780387954714) has the title "Nonlinear Estimation and '
        'Classification" and names "Lecture Notes in Statistics" as its series.']
    (choice,) = proposal.choices
    assert {k: choice[k] for k in ("field", "by", "chosen", "other", "model_assisted", "doi", "isbn", "type", "series")} == {
        "field": "booktitle", "by": "crossref-book-record", "chosen": "Nonlinear Estimation and Classification",
        "other": "Lecture Notes in Statistics", "model_assisted": False, "doi": "10.1007/978-0-387-21579-2",
        "isbn": "9780387954714", "type": "book", "series": ["Lecture Notes in Statistics"]}
    # a choice made by a record needs no decision of its own
    assert proposal.complete and not proposal.needs_decision and proposal.issues == []
    assert client.requests == 0


def test_two_more_chapters_of_the_library_are_decided_the_same_way(client):
    mann = propose(client, MANN23, allow_model=False)
    assert change(mann, "booktitle").proposed == "Intracranial {EEG}" and mann.status == "metadata_verified"
    assert mann.choices[0]["doi"] == "10.1007/978-3-031-20910-9" and mann.choices[0]["series"] == [SERIES]
    # The library's Mann23 has the book's subtitle too ("... a guide for cognitive neuroscientists"); the
    # chapter's record states the title without it, and that is what is written.
    assert FROZEN["Mann23"]["fields"]["booktitle"] == "Intracranial {EEG}: a guide for cognitive neuroscientists"
    mayer = propose(client, MAYE92, allow_model=False)
    assert change(mayer, "booktitle").proposed == "The Nature and Origins of Mathematical Skills"
    assert mayer.entry_type == "incollection" and mayer.status == "metadata_verified" and not mayer.needs_decision
    # The library has this chapter as an article in "Advances in Psychology" (MayeEtal92b): the series.
    assert FROZEN["MayeEtal92b"]["fields"]["journal"] == "Advances in Psychology"
    assert mayer.choices[0]["other"] == "Advances in Psychology" and client.requests == 0


def test_a_typed_book_title_is_kept_and_nothing_is_looked_up(tmp_path):
    client = offline_client(tmp_path / "bare", "chapters.json.gz")
    try:
        client.cache.db.execute("DELETE FROM responses WHERE request LIKE '%filter%'")     # no book record saved
        client.cache.db.commit()
        typed = complete.propose(complete.Query.from_entry(FROZEN["Scha03"]), client, client.cache, allow_model=False)
        assert typed.proposed_raw == FROZEN["Scha03"]["raw"] and {c.kind for c in typed.changes} == {"kept"}
        assert typed.status == "metadata_verified" and typed.choices == [] and client.requests == 0
    finally:
        client.cache.close()


# --- step 2: the catalogue ------------------------------------------------------------------------

def test_the_books_catalogue_record_says_it_when_crossref_has_no_record_of_the_book(tmp_path, client):
    record = record_of(client, SCHA03)
    books = offline_client(tmp_path / "books", "books.json.gz")       # holds the catalogue's answer to this ISBN
    try:
        found = ct.from_catalogue(books, books.cache, record, ct.two_titles(record))
        assert (found.chosen, found.other, found.by) == (
            "Nonlinear Estimation and Classification", "Lecture Notes in Statistics", "loc-catalogue")
        assert found.sentence == ('The book\'s Library of Congress record (LCCN 2002030566, ISBN 9780387954714) has '
                                  'the title "Nonlinear estimation and classification" and names "Lecture Notes in '
                                  'Statistics" as its series.')
        assert found.evidence["url"].startswith("https://lx2.loc.gov/sru/lcdb?") and found.evidence["document_sha256"]
        assert found.evidence["series"][0] == "Lecture notes in statistics" and not found.model_assisted
        assert books.requests == 0
    finally:
        books.cache.close()


# --- no record decides ----------------------------------------------------------------------------

def test_without_a_model_route_the_book_title_stays_unfilled_and_says_how_to_enable_one(client):
    record = record_of(client, WHIT04)
    assert record["container-title"] == ["Progress in Brain Research", "Acetylcholine in the Cerebral Cortex"]
    assert "ISBN" not in record                    # nothing to find the book's own record by
    found = ct.resolve(record, client, environ=NO_ROUTE)
    assert found.chosen is None and found.by is None and found.question is None
    assert found.reason == ("no record of the book says which is its title; no model route is set up, so no model "
                            "was asked. " + ct.HOW)
    assert "cdlbib setup" in ct.HOW
    # in the proposal: today's unfilled book title, with the reason; the verifier's status as before
    declined = propose(client, WHIT04, allow_model=False)
    assert unfilled(declined, "booktitle") == complete.Unfilled(
        "booktitle", "booktitle: no single registry title: no record of the book says which is its title; a model "
        "was not asked: it was declined",
        {"crossref": "Progress in Brain Research; Acetylcholine in the Cerebral Cortex"})
    assert "Booktitle" not in declined.proposed_raw and declined.choices == []
    assert declined.status == "needs_review" and declined.needs_decision and not declined.complete
    assert client.requests == 0


def test_with_ask_a_model_is_not_asked_and_the_question_is_given(client):
    record = record_of(client, WHIT04)
    one_key = {"DARTMOUTH_CHAT_API_KEY": "not-a-key-and-never-sent"}     # a route that is set up, by configuration
    deps.set_ask(True)
    try:
        found = ct.resolve(record, client, environ=one_key)
    finally:
        deps.set_ask(False)
    assert found.chosen is None and found.reason.endswith("a model can be asked, and was not: you asked to be "
                                                          "asked first (--ask)")
    assert found.question == (
        'The record of 10.1016/s0079-6123(03)45022-x names two titles ("Progress in Brain Research" and '
        '"Acetylcholine in the Cerebral Cortex") and no record says which is the book\'s. Ask Dartmouth Chat to read '
        "the publisher's page for it (one request; it can take a few minutes)?")
    proposal = complete.build({}, record)
    ct.apply(proposal, found)
    from cdlbib import api
    assert api.model_question(proposal) == found.question and client.requests == 0


def test_a_record_source_that_does_not_answer_is_said_and_no_model_is_asked_in_its_place(tmp_path):
    saved = offline_client(tmp_path / "bare", "chapters.json.gz")
    try:
        record = record_of(saved, SCHA03)
        saved.cache.db.execute("DELETE FROM responses WHERE request LIKE '%filter%'")
        saved.cache.db.commit()
        announced = []
        found = ct.resolve(record, saved, announce=announced.append,
                           environ={"DARTMOUTH_CHAT_API_KEY": "not-a-key-and-never-sent"})
        assert found.chosen is None and announced == []
        assert found.reason == (
            "Crossref did not answer (offline: request to api.crossref.org refused); the Library of Congress "
            "catalogue did not answer (offline: request to lx2.loc.gov refused); the book's own record could not "
            "be looked up, and no model is asked in its place")
    finally:
        saved.cache.close()


# --- step 3: a recorded real model reading -------------------------------------------------------

def recorded_cache(client):
    """The page and the reading as ``from_model`` saved them when the reading was recorded."""
    titles = tuple(RECORDED["titles"])
    client.cache.save_response("book-title-page-v1:" + RECORDED["doi"], RECORDED["page"])
    pages = ct.pages_for(RECORDED["page"], titles)
    digest = hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    client.cache.save_response("book-title-reading-v1:" + digest, RECORDED["reading"])
    return titles, pages


def test_the_recorded_page_and_what_the_model_was_given(client):
    assert RECORDED["doi"] == MANN23 and RECORDED["titles"] == [SERIES, BOOK]
    assert RECORDED["reading"]["route"] == "dartmouth"
    assert RECORDED["page"]["url"] == "https://link.springer.com/chapter/10.1007/978-3-031-20910-9_48"
    lines = RECORDED["page"]["lines"]
    assert lines[0] == "meta citation_inbook_title: Intracranial EEG"           # the page's own citation metadata
    assert "Part of the book series: Studies in Neuroscience, Psychology and Behavioral Economics ((SNPBE))" in lines
    assert not any("@" in line for line in lines)                              # addresses were removed before it was read
    (page,) = ct.pages_for(RECORDED["page"], tuple(RECORDED["titles"]))
    given = page["text"].splitlines()
    assert 0 < len(given) <= ct.MAX_LINES and len(given) < len(lines)           # only the lines about the two titles
    assert ct.lines_about(["nothing", "about", "either"], RECORDED["titles"]) == []
    assert ct.checked_url(RECORDED["page"]["url"], resolve=False) == RECORDED["page"]["url"]
    html = ('<html><head><title>T</title><meta name="citation_inbook_title" content="A Book"><script>var x = '
            '"A Series";</script></head><body><p>Part of the book series: <a href="/s">A Series</a></p></body></html>')
    assert ct.page_lines(html) == ["meta citation_inbook_title: A Book", "T", "Part of the book series: A Series"]


def test_a_recorded_model_reading_chooses_the_book_title_with_its_quotation(client):
    titles, pages = recorded_cache(client)
    record = RECORDED["record"]
    announced = []
    found = ct.from_model(client, client.cache, record, titles, announce=announced.append, environ=NO_ROUTE)
    # the saved page and reading are read again without a request, a key or an announcement
    assert announced == [] and client.requests == 0
    assert (found.chosen, found.other, found.by, found.model_assisted) == (BOOK, SERIES, "model", True)
    assert found.chosen in titles                                   # the registry's string, not the model's
    assert found.evidence == {
        "source": "model", "route": "dartmouth", "model": "zai-org.glm-5.3",
        "url": "https://link.springer.com/chapter/10.1007/978-3-031-20910-9_48",
        "quote": "meta citation_inbook_title: Intracranial EEG / Intracranial EEG",
        "document_sha256": RECORDED["page"]["document_sha256"],
        "page_retrieved_at": RECORDED["page"]["retrieved_at"], "read_at": RECORDED["reading"]["retrieved_at"]}
    assert found.sentence == (
        "Model-assisted choice (dartmouth, zai-org.glm-5.3): on the publisher's page "
        "https://link.springer.com/chapter/10.1007/978-3-031-20910-9_48 the book title was read from the line "
        '"meta citation_inbook_title: Intracranial EEG / Intracranial EEG". This is not a verification.')
    # the model also selected the line that cites the book with its series; that line decides nothing
    quoted = [p["quote"] for p in RECORDED["reading"]["extracted"]["fields"]["booktitle"]["passages"]]
    assert any(BOOK in q and SERIES in q for q in quoted)


def test_a_model_assisted_choice_is_marked_needs_a_decision_and_the_verifier_still_judges(client):
    titles, _ = recorded_cache(client)
    record = record_of(client, MANN23)
    found = ct.from_model(client, client.cache, record, titles, environ=NO_ROUTE)
    proposal = complete.build({}, dict(record, **{"container-title": [found.chosen]}))
    ct.apply(proposal, found)
    assert change(proposal, "booktitle") == complete.FieldChange(
        "booktitle", None, "Intracranial {EEG}", "crossref (model-assisted choice)", "filled")
    assert proposal.needs_decision and proposal.complete and proposal.status is None      # no status from a model
    assert len(proposal.issues) == 1 and proposal.issues[0].startswith(
        'booktitle: the record names two titles, "Studies in Neuroscience, Psychology and Behavioral Economics" and '
        '"Intracranial EEG"; "Intracranial EEG" is taken as the book\'s. Model-assisted choice (dartmouth, ')
    assert proposal.issues[0].endswith("This is not a verification. Check the title against the page before accepting.")
    (choice,) = proposal.choices
    assert choice["by"] == "model" and choice["model_assisted"] is True and choice["chosen"] == BOOK
    assert choice["quote"] and choice["url"].startswith("https://link.springer.com/")
    # the entry is checked by the verifier like any other; its status is the verifier's
    checked = complete.checked(proposal, client)
    assert checked.status == "metadata_verified" and checked.needs_decision and client.requests == 0


def test_the_model_can_only_choose_one_of_the_two_titles(client):
    titles, pages = recorded_cache(client)
    reading = RECORDED["reading"]["extracted"]
    assert ct.choice_from_reading(titles, pages, reading)[0] == BOOK

    def refused(titles=titles, pages=pages, reading=reading):
        with pytest.raises(ValueError) as caught:
            ct.choice_from_reading(titles, pages, reading)
        return str(caught.value)

    # a title the record does not have never comes out, whatever the model named
    assert refused(titles=(SERIES, "Intracranial EEG: A Guide")) == (
        "the book title the model named is not one of the record's two titles")
    third = deepcopy(reading)
    third["fields"]["booktitle"]["value"] = "Handbook of Intracranial EEG"
    assert refused(reading=third) == "the book title the model named is not one of the record's two titles"
    # the reading must be of exactly the lines that are judged
    other_pages = [{"page": 1, "text": pages[0]["text"] + "Intracranial EEG\n"}]
    assert refused(pages=other_pages) == "the reading is of another text than the page's lines"
    # a quotation that is not the page's own line
    forged = deepcopy(reading)
    forged["fields"]["booktitle"]["passages"][0]["quote"] = "meta citation_inbook_title: Something else\n"
    assert refused(reading=forged) == "the reading's passages are not lines of the page"
    # only the line that holds both titles: it does not say which is the book's
    both = deepcopy(reading)
    both["fields"]["booktitle"]["passages"] = [p for p in reading["fields"]["booktitle"]["passages"]
                                               if SERIES in p["quote"]]
    assert both["fields"]["booktitle"]["passages"] and refused(reading=both) == (
        "no quoted line contains the chosen title without the other, so the lines do not say which is the book's")
    # no book title named, a value that is not literally on the lines, a risky passage
    none = deepcopy(reading)
    del none["fields"]["booktitle"]
    assert refused(reading=none) == "the model named no book title on the page"
    loose = deepcopy(reading)
    loose["fields"]["booktitle"]["grounding"] = "interpretation_required"
    assert refused(reading=loose) == "the model's book title is not literally on the lines it selected"
    risky = deepcopy(reading)
    risky["fields"]["booktitle"]["role_risk"] = ["reference_list"]
    assert "may not state the work's own book title (reference_list)" in refused(reading=risky)
    # a reading that does not decide leaves the title unchosen, with the reason
    client.cache.save_response(
        "book-title-reading-v1:" + hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        dict(RECORDED["reading"], extracted=none))
    undecided = ct.from_model(client, client.cache, RECORDED["record"], titles, environ=NO_ROUTE)
    assert undecided.chosen is None and undecided.reason == (
        "a model read the publisher's page (https://link.springer.com/chapter/10.1007/978-3-031-20910-9_48) and its "
        "reading does not decide it: the model named no book title on the page")


@live_model
def test_live_a_model_reads_the_publishers_page(tmp_path):
    """One real run: the page is fetched and Dartmouth Chat is asked (minutes; needs its key)."""
    from cdlbib import extra_sources as xs
    client = xs.make_client(tmp_path / "live.sqlite3")
    try:
        record = client.crossref_doi(MANN23)["body"]["message"]
        lines = []
        found = ct.from_model(client, client.cache, record, ct.two_titles(record), announce=lines.append)
        assert len(lines) == 1 and "asking Dartmouth Chat" in lines[0]
        assert found.chosen in (None, BOOK)           # it may not decide; it can never choose anything else
        if found.chosen:
            assert found.by == "model" and found.evidence["quote"]
    finally:
        client.cache.close()


# --- what is fetched, and from where (security review, 2026-10-06) -------------------------------

def test_the_hosts_a_page_is_fetched_from_are_a_fixed_list_that_no_record_extends(client):
    from cdlbib import publisher_corrections
    assert ct.PAGE_HOSTS == frozenset(publisher_corrections.ISSUE_HEAD_HOSTS) and isinstance(ct.PAGE_HOSTS, frozenset)
    assert {"doi.org", "link.springer.com", "idp.springer.com", "linkinghub.elsevier.com"} <= ct.PAGE_HOSTS
    before = set(ct.PAGE_HOSTS)
    # a record that names other sites, in every field a deposit can fill, changes nothing: fetch_page is
    # given the DOI alone, and no function of the module takes a host from a record or a reading
    hostile = dict(record_of(client, MANN23), URL="https://evil.example/x", publisher="evil.example",
                   link=[{"URL": "https://evil.example/pdf"}, {"URL": "http://127.0.0.1/"}],
                   resource={"primary": {"URL": "https://evil.example/"}})
    found = ct.resolve(hostile, client, allow_model=False)
    assert found.chosen == BOOK and set(ct.PAGE_HOSTS) == before
    import inspect
    assert list(inspect.signature(ct.fetch_page).parameters) == ["doi", "session", "deadline"]
    assert not hasattr(ct, "_domains")
    source = inspect.getsource(ct.from_model)
    assert "fetch_page(doi)" in source and "record.get(\"link\")" not in inspect.getsource(ct)


HOSTILE_URLS = [
    ("https://link.springer.com@evil.example/", "a user name or password in the URL"),
    ("https://user:pw@link.springer.com/", "a user name or password in the URL"),
    ("https://evil.example#@link.springer.com", "a host that is not one of the publisher hosts this package fetches from"),
    ("https://evil.example/?@link.springer.com", "a host that is not one of the publisher hosts this package fetches from"),
    ("https://link.springer.com.evil.example/", "a host that is not one of the publisher hosts this package fetches from"),
    ("https://evillink.springer.com/", "a host that is not one of the publisher hosts this package fetches from"),
    ("https://springer.com/", "a host that is not one of the publisher hosts this package fetches from"),
    ("http://127.0.0.1/", "not an HTTPS URL"),
    ("http://link.springer.com/", "not an HTTPS URL"),
    ("https://127.0.0.1/", "an IP address in place of a host name"),
    ("https://[::1]/", "an IP address in place of a host name"),
    ("https://[::ffff:127.0.0.1]/", "an IP address in place of a host name"),
    ("https://169.254.169.254/latest/meta-data/", "an IP address in place of a host name"),
    ("https://2130706433/", "a host that is not one of the publisher hosts this package fetches from"),
    ("https://link.springer.com\\@evil.example/", "a backslash, white space or control character in the URL"),
    ("https://link.springer.com\\.evil.example/", "a backslash, white space or control character in the URL"),
    ("https://link.springer.com/a b", "a backslash, white space or control character in the URL"),
    ("https://link.springer.com/\r\nHost: evil.example", "a backslash, white space or control character in the URL"),
    ("https://link.springer.com\t.evil.example/", "a backslash, white space or control character in the URL"),
    ("https://link.springer.com:8443/", "a port other than 443"),
    ("https://link.springer.com:80/", "a port other than 443"),
    ("https://localhost/", "a host that is not one of the publisher hosts this package fetches from"),
    ("https://link.springer.com\u3002evil.example/", "the URL cannot be parsed"),
    ("ftp://link.springer.com/", "not an HTTPS URL"),
    ("//link.springer.com/", "not an HTTPS URL"),
    ("", "not a URL of usable length"),
    ("https://link.springer.com/" + "a" * 3000, "not a URL of usable length"),
]


@pytest.mark.parametrize("url, why", HOSTILE_URLS)
def test_a_hostile_url_is_refused_before_anything_is_asked(url, why):
    with pytest.raises(ct.UnsafeURL) as caught:
        ct.checked_url(url, resolve=False)
    assert str(caught.value) == why
    assert "evil" not in str(caught.value)               # the refusal repeats nothing of the URL


def test_what_is_checked_is_what_is_asked_for():
    # lower case, no final dot, the default port and a fragment are not part of what is asked for
    assert ct.checked_url("https://LINK.Springer.com./chapter/10.1007/x?a=1#frag", resolve=False) == (
        "https://link.springer.com/chapter/10.1007/x?a=1")
    assert ct.checked_url("https://doi.org:443/10.1007/978-3-031-20910-9_48", resolve=False) == (
        "https://doi.org/10.1007/978-3-031-20910-9_48")
    # an address is public or it is not asked: every private, loopback, link-local and reserved form
    for address in ("127.0.0.1", "10.0.0.8", "192.168.1.1", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1",
                    "fe80::1", "fc00::1", "::ffff:10.0.0.1", "::ffff:127.0.0.1", "224.0.0.1", "100.64.0.1",
                    "fe80::1%en0", "not an address"):
        assert ct.public_address(address) is False, address
    assert ct.public_address("93.184.216.34") and ct.public_address("2606:4700:4700::1111")


class _Counting:
    """A real requests session that counts what it is asked for."""

    def __init__(self):
        import requests
        self.session, self.urls = requests.Session(), []

    def get(self, url, **options):
        self.urls.append(url)
        return self.session.get(url, **options)


def test_every_hop_is_checked_and_a_redirect_to_a_private_address_is_never_followed():
    """A real local server stands for the private address a redirect names: it answers anyone
    who connects, and counts. The checked session is given each redirect target a hostile
    publisher page could send, as the fetcher gives it (one ``get`` per hop, redirects off),
    and connects to none of them."""
    import http.server
    import threading
    import time
    hits = []

    class Private(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"internal")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Private)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        inner = _Counting()
        guarded = ct._CheckedSession(inner, time.monotonic() + 30)
        targets = [f"http://127.0.0.1:{port}/secret", f"https://127.0.0.1:{port}/secret", f"http://localhost:{port}/",
                   f"https://localhost:{port}/", f"https://[::1]:{port}/", f"https://link.springer.com:{port}/",
                   f"https://link.springer.com@127.0.0.1:{port}/", "https://169.254.169.254/latest/meta-data/"]
        for target in targets:
            with pytest.raises(ct.UnsafeURL):
                guarded.get(target, allow_redirects=False, timeout=(2, 2), stream=True)
        assert inner.urls == [] and guarded.asked == [] and hits == []
        # the server does answer a request that is not checked: the refusals above are the guard's
        import requests
        with requests.Session() as plain:
            plain.trust_env = False
            assert plain.get(f"http://127.0.0.1:{port}/open", timeout=5).text == "internal"
        assert hits == ["/open"]
        # a request that would follow redirects by itself, or carry parameters, is not made either
        for options in ({}, {"allow_redirects": True}, {"allow_redirects": False, "params": {"q": "x"}}):
            with pytest.raises(ct.UnsafeURL):
                guarded.get("https://link.springer.com/chapter/x", **options)
        # and nothing at all once the time allowed is over
        late = ct._CheckedSession(inner, time.monotonic() - 1)
        with pytest.raises(ct.UnsafeURL, match="the time allowed"):
            late.get("https://link.springer.com/chapter/x", allow_redirects=False)
        assert inner.urls == []
    finally:
        server.shutdown()
        server.server_close()


def test_a_host_that_resolves_to_a_private_address_is_refused(monkeypatch):
    # "localhost" really resolves to the loopback address on this machine: put on the list for this one
    # test, it is still refused by what it resolves to (the list itself is not changed for any other test).
    monkeypatch.setattr(ct, "PAGE_HOSTS", frozenset(ct.PAGE_HOSTS | {"localhost"}))
    assert ct.checked_url("https://localhost/x", resolve=False) == "https://localhost/x"
    with pytest.raises(ct.UnsafeURL, match="resolves to an address that is not a public one"):
        ct.checked_url("https://localhost/x")


def test_the_fetch_refuses_a_doi_that_leads_off_the_list_and_the_bounds_come_first(tmp_path, monkeypatch):
    import inspect
    import time
    from cdlbib import search_tools
    # the fetcher is the package's own: redirects by hand, the body streamed and cut off at its limit
    fetcher = inspect.getsource(search_tools.get_source)
    assert "allow_redirects=False" in fetcher and "stream=True" in fetcher and "iter_content" in fetcher
    assert fetcher.index("size > 2_000_000") < fetcher.index('b"".join(chunks)')        # the cap, then the body
    own = inspect.getsource(ct.fetch_page)
    assert "get_source(guarded" in own and "max_redirects=PAGE_REDIRECTS" in own and ".content" not in own
    assert (ct.PAGE_REDIRECTS, ct.PAGE_SECONDS, ct.MAX_LINES, ct.MAX_PAGE_LINES) == (6, 120, 150, 5000)
    # a deadline that has passed: nothing is asked, whatever the DOI
    asked = _Counting()
    with pytest.raises(ValueError, match="the page is not fetched: the time allowed for reading the page is over"):
        ct.fetch_page("10.1007/978-3-031-20910-9_48", session=asked, deadline=time.monotonic() - 1)
    assert asked.urls == []
    # the DOI goes into the first URL as a path and nothing else: it cannot name another host
    for doi in ("10.1007/x@evil.example", "10.1007/../../evil.example", "10.1007/x#@evil.example", "10.1007/x?u=1"):
        with pytest.raises(ValueError):
            ct.fetch_page(doi, session=asked, deadline=time.monotonic() - 1)
    assert asked.urls == []
    # a page is cut while it is parsed, not after: lines, their length, and the metadata lines
    many = "<html><body>" + "".join(f"<p>line {n}</p>" for n in range(ct.MAX_PAGE_LINES + 500)) + "</body></html>"
    assert len(ct.page_lines(many)) == ct.MAX_PAGE_LINES
    long = ct.page_lines("<p>" + "x" * 100_000 + "</p>" + "".join(
        f'<meta name="citation_title" content="t{n}">' for n in range(500)))
    assert len(long) == 51 and max(map(len, long)) <= 500
    # the lines a model is given are at most MAX_LINES, and the record steps ask a bounded number of times
    assert len(ct.lines_about(["Intracranial EEG"] * 1000, (SERIES, BOOK))) == ct.MAX_LINES
    assert ct._isbns({"ISBN": [f"97800000000{n:02d}" for n in range(40)]}) == [f"97800000000{n:02d}" for n in range(4)]


def test_a_resolution_that_ran_out_of_time_asks_no_model(tmp_path, monkeypatch):
    saved = offline_client(tmp_path / "late", "chapters.json.gz")
    try:
        record = record_of(saved, WHIT04)
        monkeypatch.setattr(ct, "RESOLVE_SECONDS", -1)        # the limit itself, set so that it has passed
        announced = []
        found = ct.resolve(record, saved, announce=announced.append,
                           environ={"DARTMOUTH_CHAT_API_KEY": "not-a-key-and-never-sent"})
        assert found.chosen is None and announced == [] and saved.requests == 0
        assert found.reason.startswith("the record lookups took longer than the time allowed")
    finally:
        saved.cache.close()
