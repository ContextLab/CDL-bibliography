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
    client = offline_client(tmp_path / "cache", "chapters.json.gz", "book_isbns.json.gz")
    # The catalogue side of each chapter's book lookup (for the book's editors), recorded with
    # the builder-rules responses (tests/fixtures/completion/rule_responses.json).
    for item in json.loads((ROOT / "tests/fixtures/completion/rule_responses.json").read_text(encoding="utf-8")):
        if isinstance(item["request"], str) and item["request"].startswith("loc-sru-v1:"):
            client.cache.save_response(item["request"], item["response"])
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
    # byte for byte the library's entry (which has no publisher or address), with the editors
    # of the same book record (owner's decision 2026-10-06: a chapter's editors are the book's)
    assert proposal.proposed_raw == FROZEN["Scha03"]["raw"].replace(
        "\tPages = ", "\tEditor = {D D Denison and M H Hansen and C C Holmes and B Mallick and B Yu},\n\tPages = ") and proposal.status == "metadata_verified"
    assert change(proposal, "editor").source == "crossref (the book's own Crossref record)"
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
        # The typed title is kept and no title is looked up. The book's record is still asked
        # for the editors (owner's decision 2026-10-06); with none saved here the request is
        # refused, and the editors are left unfilled with that reason.
        assert typed.proposed_raw == FROZEN["Scha03"]["raw"] and {c.kind for c in typed.changes} == {"kept"}
        assert typed.status == "metadata_verified" and typed.choices == []
        assert unfilled(typed, "editor").reason.startswith("editor: Crossref did not answer (offline: request to "
                                                           "api.crossref.org refused)")
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
        "was not asked: it was declined. The book title is left unfilled: type it in",
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
    # the fixture holds the lines the model was given and no other line of the page: the lines about the
    # two titles, each with two lines of context (their hash is the one the reading names)
    assert given == lines and len(lines) == 30 <= ct.MAX_LINES
    assert RECORDED["reading"]["extracted"]["source_text_sha256"] == hashlib.sha256(
        json.dumps([page], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert set(RECORDED["reading"]["extracted"]["provider_trace"]) == {"provider", "model"}       # no response id
    assert set(RECORDED["reading"]["extracted"]["fields"]) == {"booktitle"}
    assert "?" not in RECORDED["page"]["url"] and "#" not in RECORDED["page"]["url"]
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
    assert proposal.issues[0].endswith("This is not a verification. " + ct.UNCONFIRMED)
    assert "does not confirm this choice" in ct.UNCONFIRMED and "Model-assisted and unconfirmed" in ct.UNCONFIRMED
    (choice,) = proposal.choices
    assert choice["by"] == "model" and choice["model_assisted"] is True and choice["chosen"] == BOOK
    assert choice["confirmed"] is False and choice["statement"] == ct.UNCONFIRMED
    assert choice["quote"] and choice["url"].startswith("https://link.springer.com/")
    # the entry is checked by the verifier like any other; its status is the verifier's
    checked = complete.checked(proposal, client)
    assert checked.status == "metadata_verified" and checked.needs_decision and client.requests == 0
    # The verifier accepts either container title, so that status says nothing about the choice: the
    # proposal and its stored record go on saying it is model-assisted and unconfirmed, in what every
    # interface shows (the issues) and in what is serialised (choices).
    assert any(ct.UNCONFIRMED in issue for issue in checked.issues) and checked.choices[0]["confirmed"] is False
    series = complete.build({}, dict(record, **{"container-title": [SERIES]}))        # the other title verifies too
    assert complete.checked(series, client).status == "metadata_verified"
    from cdlbib import api
    data = api.as_data(checked)
    assert data["choices"][0]["model_assisted"] is True and data["choices"][0]["confirmed"] is False
    assert any("Model-assisted and unconfirmed" in issue for issue in data["issues"])


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
    assert list(inspect.signature(ct.fetch_page).parameters) == ["doi", "deadline"]       # no session is taken
    assert not hasattr(ct, "_domains")
    source = inspect.getsource(ct.from_model)
    assert "fetch_page(doi, deadline=deadline)" in source and "record.get(\"link\")" not in inspect.getsource(ct)


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
        with pytest.raises(ct.UnsafeURL, match="no answer within 1 seconds; nothing was asked"):
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
    # the DOI goes into the first URL as a path and nothing else: it cannot name another host
    from urllib.parse import quote
    for doi in ("10.1007/x@evil.example", "10.1007/../../evil.example", "10.1007/x#@evil.example", "10.1007/x?u=1"):
        assert ct.checked_url("https://doi.org/" + quote(doi, safe="/"), resolve=False).startswith("https://doi.org/10.1007/")
    # (that a deadline holds while a body is being sent is tested with a real server below)
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


# --- review of 2026-10-06, items 9-11: time, credentials, whole lines ----------------------------

class _Server:
    """A real local HTTP server for one test: what it is asked, and what it answers, are real."""

    def __init__(self, handler):
        import http.server
        import threading
        self.seen = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append((self.path, dict(self.headers)))
                try:
                    handler(self)
                except (BrokenPipeError, ConnectionResetError):
                    outer.seen.append(("closed by the client", {}))

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def _plain_session():
    import requests
    session = requests.Session()
    session.trust_env = False
    return session


def test_a_server_that_drips_bytes_is_cut_off_at_the_deadline(tmp_path):
    """The server sends its headers at once and then one byte every 0.2 s for a minute: no
    single read ever times out. The retrieval still ends at the deadline."""
    import time

    def drip(request):
        request.send_response(200)
        request.send_header("Content-Type", "text/html")
        request.send_header("Content-Length", "100000")
        request.end_headers()
        for _ in range(300):
            request.wfile.write(b"x")
            request.wfile.flush()
            time.sleep(0.2)

    with _Server(drip) as server:
        started = time.monotonic()
        guarded = ct._DeadlineSession(_plain_session(), started + 1.5, 10**6)
        with pytest.raises(ct.OutOfTime, match="no answer within [12] seconds; the request was cancelled"):
            guarded.get(server.url + "/page", timeout=(5, 15), allow_redirects=False)
        assert 1.2 < time.monotonic() - started < 4          # at the deadline, not after the minute the body takes
        # the same through the paced client's own session, as the Crossref book lookup and the catalogue are read:
        # one request, cancelled, and not asked again
        from cdlbib import extra_sources as xs
        client = xs.make_client(tmp_path / "live.sqlite3", contact="valid@example.org")
        try:
            own = client.session
            started = time.monotonic()
            with ct.within(client, started + 1.5):
                assert isinstance(client.session, ct._DeadlineSession)
                with pytest.raises(ct.ProviderError, match="no answer within [12] seconds"):
                    client.get(server.url + "/works", {"rows": 5})
            assert client.session is own and time.monotonic() - started < 4
            assert [path.split("?")[0] for path, _ in server.seen if path.startswith("/")] == ["/page", "/works"]
            # nothing at all is asked once the deadline has passed
            with ct.within(client, time.monotonic() - 1):
                with pytest.raises(ct.ProviderError, match="nothing was asked"):
                    client.get(server.url + "/again", {})
            assert not any(path.startswith("/again") for path, _ in server.seen)
        finally:
            client.cache.close()


def test_a_body_over_the_limit_is_given_up_while_it_is_read_and_a_good_one_is_read_whole(tmp_path):
    import gzip
    import time
    sent = {"bytes": 0}

    def answer(request):
        if request.path.startswith("/big"):
            request.send_response(200)
            request.send_header("Content-Length", str(50_000_000))
            request.end_headers()
            for _ in range(50_000):
                request.wfile.write(b"y" * 1000)
                sent["bytes"] += 1000
        else:
            body = gzip.compress(json.dumps({"message": {"items": [{"title": ["A"]}], "total-results": 1}}).encode())
            request.send_response(200)
            request.send_header("Content-Type", "application/json")
            request.send_header("Content-Encoding", "gzip")
            request.send_header("Content-Length", str(len(body)))
            request.end_headers()
            request.wfile.write(body)

    with _Server(answer) as server:
        guarded = ct._DeadlineSession(_plain_session(), time.monotonic() + 30, 100_000)
        with pytest.raises(ct.OutOfTime, match="the answer is larger than 100000 bytes; it was cancelled"):
            guarded.get(server.url + "/big", timeout=(5, 15))
        time.sleep(0.3)
        assert sent["bytes"] < 20_000_000                    # the server was stopped long before its 50 MB
        read = guarded.get(server.url + "/small", timeout=(5, 15))
        assert read.status_code == 200 and read.json() == {"message": {"items": [{"title": ["A"]}], "total-results": 1}}
        assert b"".join(read.iter_content(7)) == read.content and "total-results" in read.text
    assert (ct.PAGE_BYTES, ct.RECORD_BYTES, ct.RESOLVE_SECONDS, ct.PAGE_SECONDS) == (2_000_000, 4_000_000, 900, 120)
    import inspect
    assert "within(client, deadline)" in inspect.getsource(ct.resolve)
    assert "within(client, deadline)" in inspect.getsource(ct.book_editors)
    from cdlbib import book_build
    assert "within(client" in inspect.getsource(book_build.find_records)


def test_the_page_session_carries_no_credentials(tmp_path, monkeypatch):
    """A .netrc with a login for the server is real, and a default requests session sends it;
    the session a page is fetched with does not, and takes none from its caller."""
    import requests
    netrc = tmp_path / "netrc"
    netrc.write_text("machine 127.0.0.1 login someone password a-secret-that-must-not-travel\n", encoding="utf-8")
    netrc.chmod(0o600)
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "no-such-bundle.pem"))

    def answer(request):
        request.send_response(200)
        request.send_header("Set-Cookie", "session=abc")
        request.send_header("Content-Length", "2")
        request.end_headers()
        request.wfile.write(b"ok")

    with _Server(answer) as server:
        with requests.Session() as default:
            default.get(server.url + "/default", timeout=5)
        session = ct.page_session()
        assert session.trust_env is False and session.auth is None and session.cert is None
        assert session.proxies == {} and session.verify is True and len(session.cookies) == 0
        assert "Authorization" not in session.headers
        session.get(server.url + "/page", timeout=5)
        seen = {path: headers for path, headers in server.seen}
        assert seen["/default"]["Authorization"].startswith("Basic ")            # the hazard is real
        assert "Authorization" not in seen["/page"] and "Cookie" not in seen["/page"]
        assert len(ct.page_session().cookies) == 0                                 # and each fetch starts with no cookie
        session.close()
    # nothing of the caller's is accepted on a hop: credentials, cookies, a proxy, other headers
    import time
    guarded = ct._CheckedSession(ct.page_session(), time.monotonic() + 30)
    for extra in ({"auth": ("u", "p")}, {"cookies": {"a": "b"}}, {"proxies": {"https": "http://127.0.0.1:1"}},
                  {"headers": {"Authorization": "Bearer x"}}, {"headers": {"Cookie": "a=b"}}, {"cert": "client.pem"}):
        with pytest.raises(ct.UnsafeURL, match="would carry credentials or other data"):
            guarded.get("https://link.springer.com/chapter/x", allow_redirects=False, **extra)
    assert guarded.asked == []
    import inspect
    assert "page_session()" in inspect.getsource(ct.fetch_page) and "session=None" not in inspect.getsource(ct.fetch_page)
    assert "TLS handshake" in ct.page_session.__doc__ and "proxy policy" in ct.page_session.__doc__


def test_a_slice_of_a_line_is_judged_as_the_whole_line():
    """The review's case: one line names the book and the series; offsets that select only
    the series title out of it must not make the series the book."""
    titles = ("Series Title", "Actual Book")
    text = "Book: Actual Book; series: Series Title\n"
    pages = [{"page": 1, "text": text}]
    digest = hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def reading(value, start, end):
        return {"source_text_sha256": digest, "fields": {"booktitle": {
            "value": value, "grounding": "literal_text_present", "role_risk": [],
            "passages": [{"page": 1, "start": start, "end": end, "quote": text[start:end]}]}}}

    start = text.index("Series Title")
    for value, (a, b) in (("Series Title", (start, start + len("Series Title"))),
                          ("Actual Book", (text.index("Actual Book"), text.index("Actual Book") + len("Actual Book"))),
                          ("Series Title", (0, len(text)))):
        with pytest.raises(ValueError) as caught:
            ct.choice_from_reading(titles, pages, reading(value, a, b))
        assert str(caught.value) == ("no quoted line contains the chosen title without the other, so the lines do "
                                     "not say which is the book's"), (value, a, b)
    # a slice of a line that holds the chosen title alone is still good, and what is quoted is the whole line
    two = [{"page": 1, "text": "Part of the book: Actual Book\nBook series: Series Title\n"}]
    digest = hashlib.sha256(json.dumps(two, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    at = two[0]["text"].index("Actual")
    good = {"source_text_sha256": digest, "fields": {"booktitle": {
        "value": "Actual Book", "grounding": "literal_text_present", "role_risk": [],
        "passages": [{"page": 1, "start": at, "end": at + 6, "quote": "Actual"}]}}}
    assert ct.choice_from_reading(titles, two, good) == ("Actual Book", "Part of the book: Actual Book")
    # offsets that are not offsets
    for start, end in ((-1, 5), (5, 5), (0, 10_000), ("0", 5)):
        bad = {"source_text_sha256": digest, "fields": {"booktitle": {
            "value": "Actual Book", "grounding": "literal_text_present", "role_risk": [],
            "passages": [{"page": 1, "start": start, "end": end, "quote": "x"}]}}}
        with pytest.raises(ValueError, match="not lines of the page"):
            ct.choice_from_reading(titles, two, bad)


# --- item 6: the record must carry the number asked for ------------------------------------------

def _hostile(client, genuine_query, asked_query):
    """The catalogue's real answer to ``genuine_query``, saved as its answer to ``asked_query``
    with the echoed query rewritten: an answer that echoes what was asked and holds another
    record. Its hash is the hash of what is saved, as a hostile answer's would be."""
    saved = dict(client.cache.response("loc-sru-v1:10:" + genuine_query, 10**9))
    raw = saved["raw_xml"].replace(genuine_query.replace('"', "&quot;"), asked_query.replace('"', "&quot;")).replace(
        genuine_query, asked_query)
    assert asked_query in raw.replace("&quot;", '"')
    saved.update(raw_xml=raw, query=asked_query, document_sha256=hashlib.sha256(raw.encode()).hexdigest())
    client.cache.save_response("loc-sru-v1:10:" + asked_query, saved)


def test_a_catalogue_answer_for_a_books_isbn_must_hold_a_record_with_that_isbn(tmp_path):
    books = offline_client(tmp_path / "books", "books.json.gz", "chapters.json.gz")
    try:
        record = record_of(books, SCHA03)
        titles = ct.two_titles(record)
        genuine = ct.from_catalogue(books, books.cache, record, titles)
        assert genuine.chosen == "Nonlinear Estimation and Classification"
        assert genuine.evidence["matched"] == {"field": "020", "value": "9780387954714", "asked": "9780387954714"}
        assert ct.from_crossref(books, record, titles).evidence["matched"] == {
            "field": "ISBN", "value": ["9780387954714", "9780387215792"], "asked": "9780387954714"}
        # another book's record (Kahana 2012), returned for the chapter's ISBNs with the query echoed, and
        # titled like the series: without the check it would make the series the book
        for isbn in ("9780387954714", "9780387215792"):
            _hostile(books, 'bath.isbn="9780195333244"', f'bath.isbn="{isbn}"')
        series_like = ("Foundations of human memory", "Nonlinear Estimation and Classification")
        assert ct.from_catalogue(books, books.cache, dict(record, **{"container-title": list(series_like)}), series_like) is None
        assert list(ct.catalogue_books(books, books.cache, record)) == [] and books.requests == 0
    finally:
        books.cache.close()


# --- re-review of 2026-10-06: a hard deadline, cut lines, and the mark that stays --------------------

def test_the_deadline_holds_before_headers_inside_chunk_framing_and_against_a_small_gzip_that_inflates(tmp_path):
    """Three real servers that an inactivity timeout does not catch: one never sends its
    headers, one drips a chunk-extension line (read inside the HTTP library, before any body
    byte is handed over), one sends 300 KB of gzip that unpacks to 300 MB."""
    import time
    import zlib

    def answer(request):
        if request.path.startswith("/silent"):
            time.sleep(20)                                   # connected, and no status line
        elif request.path.startswith("/chunk"):
            request.send_response(200)
            request.send_header("Transfer-Encoding", "chunked")
            request.end_headers()
            request.wfile.write(b"5;ext=")
            for _ in range(100):                             # the extension of the first chunk-size line, forever
                request.wfile.write(b"x")
                request.wfile.flush()
                time.sleep(0.2)
        else:
            packer = zlib.compressobj(9, zlib.DEFLATED, 31)
            body = b"".join(packer.compress(b"\0" * 1_000_000) for _ in range(300)) + packer.flush()
            assert len(body) < 400_000
            request.send_response(200)
            request.send_header("Content-Encoding", "gzip")
            request.send_header("Content-Length", str(len(body)))
            request.end_headers()
            request.wfile.write(body)

    with _Server(answer) as server:
        for path in ("/silent", "/chunk"):
            started = time.monotonic()
            guarded = ct._DeadlineSession(_plain_session(), started + 1.5, 10**6)
            with pytest.raises(ct.OutOfTime, match="no answer within [12] seconds; the request was cancelled"):
                guarded.get(server.url + path, timeout=(5, 15))
            assert 1.2 < time.monotonic() - started < 3.5, path           # released at the deadline
        started = time.monotonic()
        guarded = ct._DeadlineSession(_plain_session(), started + 30, 1_000_000)
        with pytest.raises(ct.OutOfTime, match="larger than 1000000 bytes when it is unpacked"):
            guarded.get(server.url + "/bomb", timeout=(5, 15))
        assert time.monotonic() - started < 10
        sent = [headers.get("Accept-Encoding") for path, headers in server.seen if path.startswith("/")]
        assert sent == ["gzip, deflate"] * 3                              # nothing else is asked for
    # an encoding that was not asked for is not unpacked at all
    with pytest.raises(ct.OutOfTime, match="an encoding that was not asked for"):
        ct._inflater("br")
    # anything else that the bounded work does is released at the deadline too (a host lookup, for one)
    started = time.monotonic()
    with pytest.raises(ct.OutOfTime, match="no answer within 1 seconds"):
        ct.timed(started + 0.5, 1, lambda: time.sleep(10))
    assert time.monotonic() - started < 2
    assert ct.timed(time.monotonic() + 5, 5, lambda: "done") == "done"
    with pytest.raises(KeyError):
        ct.timed(time.monotonic() + 5, 5, lambda: {}["missing"])


def test_a_line_that_was_cut_is_no_evidence_for_a_title():
    """The re-review's case: one paragraph names the series, 500 characters of filler, then
    the book. The page's lines are cut at 500 characters, so the book's name is gone from
    the line that is judged: such a line cannot make the series the book."""
    titles = ("Series Title", "Actual Book")
    block = "Series: Series Title " + "filler " * 80 + "; book: Actual Book"
    (line,) = ct.page_lines(f"<html><body><p>{block}</p></body></html>")
    assert len(line) == ct.LINE_CHARS == 500 and "Actual Book" not in line and "Series Title" in line
    pages = [{"page": 1, "text": line + "\n"}]
    digest = hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    start = line.index("Series Title")
    reading = {"source_text_sha256": digest, "fields": {"booktitle": {
        "value": "Series Title", "grounding": "literal_text_present", "role_risk": [],
        "passages": [{"page": 1, "start": start, "end": start + 12, "quote": "Series Title"}]}}}
    with pytest.raises(ValueError, match="no quoted line contains the chosen title without the other"):
        ct.choice_from_reading(titles, pages, reading)
    # the same words in a line that is whole are evidence, as before
    whole = [{"page": 1, "text": "Book series: Other\nPart of the book: Series Title\n"}]
    digest = hashlib.sha256(json.dumps(whole, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    at = whole[0]["text"].index("Series Title")
    good = {"source_text_sha256": digest, "fields": {"booktitle": {
        "value": "Series Title", "grounding": "literal_text_present", "role_risk": [],
        "passages": [{"page": 1, "start": at, "end": at + 12, "quote": "Series Title"}]}}}
    assert ct.choice_from_reading(titles, whole, good)[0] == "Series Title"
    # none of the recorded reading's own lines was cut
    assert all(len(line) < ct.LINE_CHARS for line in RECORDED["page"]["lines"] if BOOK in line and SERIES not in line)


def test_a_model_assisted_title_stays_marked_after_the_entry_is_written(client, tmp_path):
    from cdlbib import api, auto_review
    from cdlbib.verification import Cache, record_approval
    from intake_support import library
    titles, _ = recorded_cache(client)
    record = record_of(client, MANN23)
    found = ct.from_model(client, client.cache, record, titles, environ=NO_ROUTE)
    proposal = complete.build({}, dict(record, **{"container-title": [found.chosen]}))
    ct.apply(proposal, found)
    ws = library(tmp_path / "lib")
    proposal = complete._plan_proposal(ws, complete.checked(proposal, client), complete.Query(), ())
    assert proposal.status == "metadata_verified" and ct.model_choice(proposal)["chosen"] == BOOK
    done = api.apply_proposals(ws, [proposal])
    assert done.written == ["Mann23"]
    assert done.notes[-1] == "Mann23: booktitle chosen with a model, unconfirmed; the entry needs a person's review"
    entry = load_entries(ws.bib)["Mann23"]
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        stored = cache.get(ws.bib, entry)
        # the verifier would accept this entry (it accepts either title); the stored result does not say so
        assert stored["status"] == "needs_review"
        assert stored["issues"] == ["booktitle chosen with a model, unconfirmed: human confirmation required"]
        kept = stored["external_evidence"]
        assert (kept["kind"], kept["summary"], kept["model_assisted"], kept["confirmed"]) == (
            ct.MODEL_CHOICE, "booktitle chosen with a model, unconfirmed", True, False)
        assert (kept["route"], kept["model"], kept["chosen"], kept["other"]) == ("dartmouth", "zai-org.glm-5.3", BOOK, SERIES)
        assert kept["url"] == RECORDED["page"]["url"] and kept["document_sha256"] == RECORDED["page"]["document_sha256"]
        assert kept["quote"] == "meta citation_inbook_title: Intracranial EEG / Intracranial EEG"
        assert kept["fields"]["booktitle"] == {"value": BOOK, "quote": kept["quote"], "page": kept["url"]}
        # judged again from what is saved (as every later check does), it is still not accepted
        again = auto_review.reassess(entry, stored)
        assert again["status"] == "needs_review" and again["external_evidence"] == kept
        # what the views read
        detail = api.entry(ws, "Mann23")
        assert detail.status == "needs_review" and detail.external_evidence["summary"].startswith("booktitle chosen with a model")
        assert api.status(ws).counts.get("needs_review") == 1 if hasattr(api.status(ws), "counts") else True
        # a person's approval stands, and the mark is not put over it
        record_approval(cache, ws.bib, "Mann23", entry["fingerprint"], dict(
            reviewer="@fixture", source="the publisher's page", note="title checked", github_login="fixture", github_id=1))
    finally:
        cache.close()
    after = ct.keep_model_choice(ws, "Mann23", entry["fingerprint"], ct.model_choice(proposal))
    assert after["status"] == "human_verified"
    # a proposal with no model-assisted choice stores nothing of the kind
    assert ct.model_choice(complete.build({}, record)) is None
    from cdlbib.errors import CdlbibError
    with pytest.raises(CdlbibError, match="is not the entry that was written"):
        ct.keep_model_choice(ws, "Mann23", "another-fingerprint", ct.model_choice(proposal))
