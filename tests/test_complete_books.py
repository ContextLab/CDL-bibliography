"""Books built from Library of Congress catalogue records (owner's decision 2026-10-06:
"the builder creates book entries from Library of Congress records, which the checker
already uses").

Nothing here is invented. Every lookup is a real response fetched once on 2026-10-06 by
tests/fixtures/intake/record.py (``books``; the README beside it lists what was asked) and
replayed through the real client over a real response cache with a transport that refuses
every request (tests/intake_support.py), so ``client.requests == 0`` shows that nothing was
fetched. The books: one author (Kahana 2012), six authors and a third edition (Gelman et al.
2014), two authors and a second edition (Nocedal and Wright 2006), an edited volume entered
under its title (Campbell 1992), an edited volume with two editors (Tulving and Donaldson
1972), an imprint of 1883 (Galton), two publishers (Tulving 1983), an edition that is not a
number (Cohen 1977) and a record the catalogue check does not read (Denison et al. 2003).

The builder and the catalogue check share the request (``catalogue_discovery.fetch_query``),
the grammar (``catalogue_review.parse_edition``) and the comparison
(``catalogue_review.compare_edition``); the status of a built book is the verifier's.
"""
from pathlib import Path

import pytest

from cdlbib import api, book_build, catalogue_review, complete, intake
from cdlbib.verification import Cache, load_entries

from intake_support import CONTACT, library, offline_client, seeded_library
from test_complete_cli import ADD, refused_network, terminal

ROOT = Path(__file__).resolve().parents[1]
FROZEN = load_entries(ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib")
SRU = "https://lx2.loc.gov/sru/lcdb"

KAHA12 = ("@book{Kaha12,\n\tAddress = {New York, {NY}},\n\tAuthor = {M J Kahana},\n"
          "\tPublisher = {Oxford University Press},\n\tTitle = {Foundations of human memory},\n\tYear = {2012}}")
GALT83 = ("@book{Galt83,\n\tAddress = {London},\n\tAuthor = {F Galton},\n\tPublisher = {Macmillan},\n"
          "\tTitle = {Inquiries into human faculty and its development},\n\tYear = {1883}}")
NOCEWRIG06 = ("@book{NoceWrig06,\n\tAddress = {New York, {NY}},\n\tAuthor = {J Nocedal and S J Wright},\n"
              "\tEdition = {2\\textsuperscript{nd}},\n\tPublisher = {Springer},\n\tTitle = {Numerical optimization},\n"
              "\tYear = {2006}}")
GELMETAL14 = ("@book{GelmEtal14,\n\tAddress = {Boca Raton, {FL}},\n"
              "\tAuthor = {A Gelman and J B Carlin and H S Stern and D B Dunson and A Vehtari and D B Rubin},\n"
              "\tEdition = {3\\textsuperscript{rd}},\n\tPublisher = {{CRC} Press},\n\tTitle = {{Bayesian} data analysis},\n"
              "\tYear = {2014}}")
CAMP92 = ("@book{Camp92,\n\tAddress = {Amsterdam},\n\tEditor = {J I D Campbell},\n\tPublisher = {North-Holland},\n"
          "\tTitle = {The nature and origins of mathematical skills},\n\tYear = {1992}}")
TULVDONA72 = ("@book{TulvDona72,\n\tAddress = {New York, {NY}},\n\tEditor = {E Tulving and W Donaldson},\n"
              "\tPublisher = {Academic Press},\n\tTitle = {Organization of memory},\n\tYear = {1972}}")
COHE77 = ("@book{Cohe77,\n\tAddress = {New York, {NY}},\n\tAuthor = {J Cohen},\n\tPublisher = {Academic Press},\n"
          "\tTitle = {Statistical power analysis for the behavioral sciences},\n\tYear = {1977}}")


@pytest.fixture
def client(tmp_path):
    client = offline_client(tmp_path / "cache", "books.json.gz")
    yield client
    client.cache.close()


def book(client, text, author=None, year=None, ws=None):
    query = complete.Query.parse(text, author=author, year=year, book=True)
    return complete.propose(query, client, client.cache, ws=ws)


def change(proposal, name):
    return next(c for c in proposal.changes if c.field == name)


def fields_of(raw, tmp_path):
    path = tmp_path / "one.bib"
    path.write_text(raw + "\n", encoding="utf-8")
    return next(iter(load_entries(path).values()))["fields"]


# --- what is asked for ---------------------------------------------------------------------------

def test_an_isbn_and_an_lccn_are_read_as_a_book_and_nothing_else_is():
    parse = complete.Query.parse
    for text in ("ISBN 9780195333244", "isbn:978-0-19-533324-4", "ISBN-13: 9780195333244", "9780195333244",
                 "978-0-19-533324-4"):
        assert parse(text) == complete.Query(isbn="9780195333244", book=True), text
    assert parse("ISBN 0-19-533324-1") == parse("0-19-533324-1") == complete.Query(isbn="0195333241", book=True)
    assert parse("ISBN 080582031X").isbn == "080582031X"
    # a bare number is an ISBN only with a correct check digit, as an ISBN-13 or written with hyphens
    assert parse("9780195333245").isbn is None and parse("0195333241").isbn is None
    assert parse("13896567") == complete.Query(title="13896567")          # as before: the words of a title
    for text, number in (("LCCN 2012007685", "2012007685"), ("lccn: 92-17326", "92017326"),
                         ("LCCN:10032396", "10032396"), ("LCCN 2012-7685", "2012007685")):
        assert parse(text) == complete.Query(lccn=number, book=True), text
    assert parse("2012007685").lccn is None and parse("LCCN 12").lccn is None
    # identifiers of papers are read as before
    assert parse("10.1002/tea.3660271011") == complete.Query(doi="10.1002/tea.3660271011")
    assert parse("PMID:13896567") == complete.Query(pmid="13896567")
    assert parse("arXiv:2208.02957") == complete.Query(arxiv="2208.02957")
    # a title is a book's only when said so
    assert parse("Foundations of human memory", author="Kahana") == complete.Query(
        title="Foundations of human memory", author="Kahana")
    assert parse("Foundations of human memory", author="Kahana", book=True).book is True
    # the queries the catalogue is sent hold a checked number and nothing else
    assert book_build.identifier_query("isbn", "9780195333244") == 'bath.isbn="9780195333244"'
    assert book_build.identifier_query("lccn", "92017326") == 'bath.lccn="92017326"'
    for kind, value in (("isbn", '1" or dc.title="x'), ("lccn", "92-17326"), ("issn", "12345678"), ("isbn", "123")):
        with pytest.raises(ValueError):
            book_build.identifier_query(kind, value)


def test_a_wrong_check_digit_is_said_and_nothing_is_asked(client):
    proposal = book(client, "ISBN 9780195333245")
    assert proposal.proposed_raw is None and proposal.status is None and proposal.needs_decision
    assert proposal.issues == ["9780195333245 is not an ISBN: its check digit is wrong; nothing was looked up"]
    assert client.requests == 0


# --- one record: the built entry -----------------------------------------------------------------

def test_a_book_by_isbn_is_built_in_house_format_and_verified_by_the_catalogue_check(client):
    proposal = book(client, "ISBN 9780195333244")
    # The entry of the frozen library, which braces two words of the publisher that the publisher
    # formatter does not (the library's present entry has them as written here).
    assert proposal.proposed_raw == KAHA12 == FROZEN["Kaha12"]["raw"].replace(
        "{Oxford} {University} Press", "Oxford University Press")
    assert proposal.entry_type == "book" and proposal.record_source == "loc-catalogue"
    assert proposal.key_proposed == "Kaha12" and proposal.unsupported is None and proposal.doi is None
    assert [(c.field, c.typed, c.source, c.kind) for c in proposal.changes] == [
        (name, None, "loc-catalogue", "filled") for name in ("address", "author", "publisher", "title", "year")]
    assert change(proposal, "address").proposed == "New York, {NY}"
    assert proposal.unfilled == [] and proposal.issues == [] and proposal.candidates == []
    assert proposal.notes == ["Built from the Library of Congress catalogue record LCCN 2012007685 "
                              "(ISBN 9780195333244, 0195333241)."]
    # the status is the verifier's own, from its catalogue route; a proposal is never an approval
    assert proposal.status == "metadata_verified" and proposal.complete and not proposal.needs_decision
    assert api.acceptable(proposal) and client.requests == 0


def test_the_built_fields_are_the_ones_the_catalogue_check_compares(client):
    # The same saved search, read by the check's own grammar and compared by its own comparison.
    response = client.cache.response('loc-sru-v1:10:bath.isbn="9780195333244"', 10**9)
    (xml,) = response["records"] if "records" in response else catalogue_review.parse_search(
        response["raw_xml"], 'bath.isbn="9780195333244"')["records"]
    assert response["url"].startswith(SRU + "?") and "bath.isbn" in response["url"]
    record = catalogue_review.parse_edition(xml)
    assert (record["title"], record["publisher"], record["address"], record["edition"]) == (
        ["Foundations of human memory"], ["Oxford University Press"], ["New York"], "")
    built = book_build.build_book(xml)
    fields = dict(FROZEN["Kaha12"]["fields"], publisher="Oxford University Press")
    assert built.proposed_raw == KAHA12
    evidence, issues = catalogue_review.compare_edition(fields, record, xml)
    assert issues == [] and evidence["address"]["source_place_code"] == "nyu"      # NY from the record's 008 code
    assert set(book_build.STATE_CODES) < set(catalogue_review.STATE_FORMS)
    assert all(code.lower() in catalogue_review.STATE_FORMS[marc] for marc, code in book_build.STATE_CODES.items())


def test_a_book_by_lccn_with_an_imprint_of_1883(client):
    proposal = book(client, "LCCN 10032396")
    # The frozen library's entry says "London, {UK}"; the record prints "London", and no country is added.
    assert proposal.proposed_raw == GALT83 == FROZEN["Galt83"]["raw"].replace("London, {UK}", "London")
    assert proposal.status == "metadata_verified" and proposal.complete and not proposal.needs_decision
    assert proposal.notes == ["Built from the Library of Congress catalogue record LCCN 10032396."]
    assert change(proposal, "address").proposed == "London"      # no country is added to what the record prints
    assert client.requests == 0


def test_six_authors_and_a_third_edition(client, tmp_path):
    proposal = book(client, "ISBN 9781439840955")
    assert proposal.proposed_raw == GELMETAL14 and proposal.status == "metadata_verified"
    assert change(proposal, "edition") == complete.FieldChange(
        "edition", None, "3\\textsuperscript{rd}", "loc-catalogue", "filled")       # the record: "Third edition"
    # The library cites this edition as GelmEtal13 with the year 2013 and Chapman & Hall/CRC; the record's
    # imprint is CRC Press, 2014. What differs is the library's entry, which is not changed here.
    mine, theirs = fields_of(proposal.proposed_raw, tmp_path), FROZEN["GelmEtal13"]["fields"]
    assert {k for k in mine if mine[k] != theirs.get(k)} <= {"ID", "year", "publisher", "address", "title"}
    assert mine["author"] == theirs["author"] and mine["edition"] == theirs["edition"]
    assert client.requests == 0


def test_an_edited_volume_is_keyed_by_its_editors(client):
    proposal = book(client, "Organization of memory", author="Tulving")
    assert proposal.proposed_raw == TULVDONA72 and proposal.key_proposed == "TulvDona72"
    assert change(proposal, "editor") == complete.FieldChange(
        "editor", None, "E Tulving and W Donaldson", "loc-catalogue", "filled")
    assert "author" not in {c.field for c in proposal.changes}
    assert proposal.status == "metadata_verified" and proposal.complete and not proposal.needs_decision
    assert proposal.notes[1] == "One catalogue record matches the title and the first author."
    assert complete.required_fields("book", {"editor": "E Tulving"}) == ("editor", "title", "year")
    assert complete.required_fields("book", {"author": "E Tulving"}) == ("author", "title", "year")
    assert complete.required_fields("article") == complete.KINDS["article"].required
    assert client.requests == 0


def test_a_capital_after_the_article_of_a_title_entry_is_asked_about(client):
    # The record: "The Nature and origins of mathematical skills / edited by Jamie I.D. Campbell."
    proposal = book(client, "LCCN 92-17326")
    assert proposal.proposed_raw == CAMP92 and proposal.status == "metadata_verified"
    assert proposal.issues == [
        "title: the record capitalises 'Nature' after the opening article, as the cataloguing rule does for a book "
        "entered under its title; it is written in lower case, so brace it if it is a name"]
    assert proposal.needs_decision and proposal.complete
    assert proposal.notes[1] == ("address: the record gives the publisher 2 places (Amsterdam; New York); "
                                 "the first is written")
    # A capital anywhere else is a proper noun in a catalogue title, and is braced.
    assert book_build._braced_title("Organization in vision: essays on Gestalt perception") == (
        "Organization in vision: essays on {Gestalt} perception")
    assert book_build._braced_title("Foundations of human memory") == "Foundations of human memory"
    assert client.requests == 0


def test_two_publishers_are_a_question(client):
    # Tulving 1983: "Oxford [Oxfordshire] : Clarendon Press ; New York : Oxford University Press". The
    # library cites the second (Tulv83); the check accepts either with its own place.
    proposal = book(client, "Elements of episodic memory", author="Tulving")
    assert "\tPublisher = {Clarendon Press}" in proposal.proposed_raw and "\tAddress = {Oxford}" in proposal.proposed_raw
    assert {c.field: c.kind for c in proposal.changes} == {
        "address": "question", "author": "filled", "publisher": "question", "title": "filled", "year": "filled"}
    assert proposal.issues == [
        "publisher: the record names 2 publishers, each with its place (Clarendon Press (Oxford); Oxford "
        "University Press (New York)); the first is written, and the citation may name the other"]
    assert proposal.status == "metadata_verified" and proposal.needs_decision and proposal.complete
    assert FROZEN["Tulv83"]["fields"]["publisher"] == "{Oxford} {University} Press"
    assert client.requests == 0


# --- several records: never chosen silently -----------------------------------------------------

def test_a_title_with_two_editions_is_answered_with_both_and_neither_is_taken(client):
    proposal = book(client, "Numerical optimization", author="Nocedal")
    assert proposal.proposed_raw is None and proposal.status is None and proposal.needs_decision
    assert proposal.issues == ["2 catalogue records match the title and the first author: editions are distinct "
                               "works, and one has to be chosen."]
    assert [(c["year"], c["lccn"], c["edition"], c["journal"], c["source"], c["type"]) for c in proposal.candidates] == [
        ("2006", "2006923897", "2nd ed", "Springer, 2nd ed", "loc-catalogue", "book"),
        ("1999", "99013263", "", "Springer", "loc-catalogue", "book")]
    assert all(c["title"] == "Numerical optimization" and c["doi"] is None for c in proposal.candidates)
    # the chosen candidate is looked up by its own identifier, like any other lead
    chosen = complete.Query.from_candidate(proposal.candidates[0])
    assert chosen == complete.Query(lccn="2006923897", book=True) == api.candidate_query(proposal.candidates[0])
    assert api.candidate_identifier(proposal.candidates[0]) == "LCCN 2006923897"
    built = complete.propose(chosen, client, client.cache)
    assert built.proposed_raw == NOCEWRIG06 and built.status == "metadata_verified" and not built.needs_decision
    assert client.requests == 0


def test_the_year_picks_the_edition_only_when_one_record_has_it(client, tmp_path):
    proposal = book(client, "Numerical optimization", author="Nocedal", year="2006")
    assert proposal.proposed_raw == NOCEWRIG06 and proposal.status == "metadata_verified"
    assert proposal.notes[1] == ("One catalogue record matches the title, the first author and the year (1 other "
                                 "record with this title, of other years, not taken).")
    assert proposal.candidates == [] and not proposal.needs_decision
    # the library's own entry of the second edition has the same fields
    assert fields_of(NOCEWRIG06, tmp_path) == FROZEN["NoceWrig06"]["fields"]
    # a year no record has: the records are offered, none is built
    other = complete.propose(complete.Query(title="Numerical optimization", author="Nocedal", year="2001", book=True),
                             client, client.cache)
    assert other.proposed_raw is None and len(other.candidates) == 2
    assert other.issues == ["No catalogue record with this title is of 2001; 2 of other years found, and none is "
                            "taken without a choice."]
    assert client.requests == 0


def test_catalogue_records_are_leads_of_a_search_with_their_edition(tmp_path, client):
    ws = library(tmp_path / "lib", NOCEWRIG06)
    found = intake.find_candidates(ws, client=client, title="Numerical optimization", authors=["Nocedal"],
                                   sources=("loc-catalogue",))
    assert found.errors == [] and client.requests == 0
    assert [(lead["year"], lead["lccn"], lead["journal"], lead["sources"]) for lead in found] == [
        ("2006", "2006923897", "Springer, 2nd ed", ["loc-catalogue"]),
        ("1999", "99013263", "Springer", ["loc-catalogue"])]
    assert found[0]["authors"] == "Nocedal, Jorge; Wright, Stephen J" and found[0]["source"] == "loc-catalogue"
    # the same work by title and surnames: both editions are flagged, and the person sees which is which
    assert [lead["in_library"] for lead in found] == ["NoceWrig06", "NoceWrig06"]
    assert intake.query_for(found[1]) == complete.Query(lccn="99013263", book=True)
    assert "loc-catalogue" in intake.SOURCES
    # the catalogue is asked only for a title together with an author
    assert list(book_build.leads(client, "Numerical optimization", [], None, 10)) == []
    assert list(book_build.leads(client, None, ["Nocedal"], None, 10)) == []


# --- what is not built, and why -----------------------------------------------------------------

def test_an_edition_that_is_not_a_number_is_built_without_it_and_stays_unverified(client):
    # Cohen 1977: the record's edition statement is "Rev. ed.". The house format writes a number only, and
    # the catalogue check asks for the edition of a record that states one.
    proposal = book(client, "Statistical power analysis for the behavioral sciences", author="Cohen", year="1977")
    assert proposal.proposed_raw == COHE77
    assert proposal.unfilled == [complete.Unfilled(
        "edition", "edition: the record's edition statement is not a numbered edition, and the house format writes "
        "only a number; the catalogue check cannot verify the entry without the edition", {"loc-catalogue": "Rev. ed"})]
    assert proposal.status == "needs_review" and proposal.needs_decision
    assert proposal.issues == ["No unique, fully matching catalogue edition",
                               "loc-catalogue : edition: missing evidence or mismatch"]
    assert complete.FIRST_CHECK in proposal.notes
    assert book_build._edition_house("Rev. ed") is None and book_build._edition_house("2nd ed") == "2\\textsuperscript{nd}"
    # The older catalogue form "2d ed." is the second edition (owner decision 2026-10-06 on ordinals):
    # the check's edition comparison reads it as the number, and it is written in the house form.
    # "12d" and "4d" abbreviate no ordinal and stay unread.
    assert catalogue_review.normalized_edition("2d ed") == "2"
    assert catalogue_review.normalized_edition("2d ed.") == catalogue_review.normalized_edition("2\\textsuperscript{nd}")
    assert book_build._edition_house("2d ed") == "2\\textsuperscript{nd}"
    assert book_build._edition_house("3d ed.") == "3\\textsuperscript{rd}"
    assert book_build._edition_house("22d ed") == "22\\textsuperscript{nd}"
    assert book_build._edition_house("12d ed") is None and book_build._edition_house("4d ed") is None
    assert book_build._edition_house("Third edition") == "3\\textsuperscript{rd}"
    assert book_build._edition_house("11th ed.") == "11\\textsuperscript{th}"
    assert client.requests == 0


def test_a_record_the_catalogue_check_does_not_read_gives_no_entry(client):
    # Denison et al. 2003: "editors, David D. Denison ... [et al.]" names only part of the byline.
    proposal = book(client, "ISBN 9780387954714")
    assert proposal.proposed_raw is None and proposal.status is None and proposal.needs_decision
    assert proposal.issues == [
        'The catalogue record LCCN 2002030566 ("Nonlinear estimation and classification", 2003) is not one the '
        "catalogue check reads, so no entry it could verify can be built from it (Transcribed responsibility names "
        "only part of the byline). Enter the book by hand; it then needs a human check."]
    assert not api.acceptable(proposal) and client.requests == 0


def test_a_book_the_catalogue_does_not_have(client):
    missing = book(client, "LCCN 2099123456")
    assert missing.proposed_raw is None and missing.status is None and missing.candidates == []
    assert missing.issues == ["No Library of Congress catalogue record has the LCCN 2099123456; nothing was "
                              "searched for in its place"]
    untitled = book(client, "Zzyzxqv qwxzvk plorbnix", author="Nobody")
    assert untitled.proposed_raw is None and untitled.issues == [
        "No Library of Congress catalogue record has the title and the first author; nothing was searched for in "
        "its place"]
    # a title without an author is not a catalogue search
    alone = book(client, "Foundations of human memory")
    assert alone.proposed_raw is None and "its title together with its first author" in alone.issues[0]
    assert client.requests == 0


def test_the_catalogue_not_answering_is_a_failed_lookup_and_nothing_is_proposed(tmp_path):
    client = offline_client(tmp_path / "empty")          # no saved response: every request is refused
    try:
        for text, author in (("ISBN 9780195333244", None), ("LCCN 10032396", None),
                             ("Numerical optimization", "Nocedal")):
            proposal = book(client, text, author=author)
            assert proposal.status == complete.LOOKUP_FAILED and proposal.proposed_raw is None
            assert proposal.issues == ["The lookup failed: the Library of Congress catalogue did not answer "
                                       "(offline: request to lx2.loc.gov refused); nothing is proposed"]
            assert api.proposal_failed(proposal)
        assert client.requests == 3
    finally:
        client.cache.close()


def test_a_crossref_record_of_a_book_is_still_not_built_and_a_typed_book_is_left_as_typed():
    # Crossref's record of a book states no edition and no place: it fills nothing, as before.
    assert "book" not in complete.KINDS
    proposal = complete.build({}, {"type": "book", "DOI": "10.1201/b16018", "title": ["Bayesian Data Analysis"]})
    assert proposal.unsupported == "book" and proposal.proposed_raw is None
    typed = complete.build({"ENTRYTYPE": "book", "ID": "GelmEtal13"}, {})
    assert typed.unsupported == "book" and typed.proposed_raw is None


# --- build, write, verify ------------------------------------------------------------------------

@pytest.fixture
def offline(monkeypatch):
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)


def seeded(tmp_path):
    """A library of its own whose response cache holds the saved lookups."""
    return seeded_library(tmp_path / "lib", "books.json.gz")


def test_a_built_book_is_written_and_the_gate_verifies_it_by_its_catalogue_route(tmp_path, offline):
    ws = seeded(tmp_path)
    lines = []
    results = api.propose_new(ws, ["ISBN 9780195333244"], mailto=CONTACT, progress=lines.append)
    (proposal,) = results
    assert results.errors == [] and lines == ["ISBN 9780195333244: metadata_verified"]
    assert proposal.proposed_raw == KAHA12 and api.acceptable(proposal) and not proposal.needs_decision
    assert ws.bib.read_text(encoding="utf-8") == ""                       # proposing writes nothing
    done = api.apply_proposals(ws, [proposal])
    assert done.written == ["Kaha12"] and done.refused == []
    assert ws.bib.read_text(encoding="utf-8").strip() == KAHA12
    check = api.check_keys(ws, ["Kaha12"], mailto=CONTACT)                # the gate: format, then citations
    assert check.ok and check.format.ok and check.citations.ok
    result = check.citations.checked["Kaha12"]
    assert result["status"] == "metadata_verified" and result["accepted_source"] == "loc-catalogue"
    assert result["accepted_record_id"] == "17200404" and "human_review" not in result
    assert result["catalogue_review"]["query"] == 'dc.title="foundations of human memory" and dc.author="kahana"'
    # stored as any catalogue verification is, and valid as one
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        stored = cache.get(ws.bib, load_entries(ws.bib)["Kaha12"])
    finally:
        cache.close()
    assert stored["status"] == "metadata_verified" and catalogue_review.valid_catalogue_approval(stored)
    # the same work again is a duplicate
    again = api.propose_new(ws, ["ISBN 9780195333244"], mailto=CONTACT)
    assert again[0].duplicate_of == "Kaha12" and not api.acceptable(again[0])


def test_a_built_book_the_verifier_does_not_accept_stays_unverified_after_it_is_written(tmp_path, offline):
    ws = seeded(tmp_path)
    query = complete.Query.parse("Statistical power analysis for the behavioral sciences", author="Cohen",
                                 year="1977", book=True)
    (proposal,) = api.propose_new(ws, [query], mailto=CONTACT)
    assert proposal.proposed_raw == COHE77 and proposal.status == "needs_review" and proposal.needs_decision
    assert api.acceptable(proposal)       # it may be written by the person looking at it; that is no verification
    assert api.apply_proposals(ws, [proposal]).written == ["Cohe77"]
    check = api.check_keys(ws, ["Cohe77"], mailto=CONTACT)
    assert check.format.ok and not check.citations.ok and not check.ok
    result = check.citations.checked["Cohe77"]
    assert result["status"] == "needs_review" and result["issues"] == ["No unique, fully matching catalogue edition"]
    mine = [c for c in result["candidates"] if c.get("source") == "loc-catalogue"
            and c["record"].get("published") == {"date-parts": [[1977]]}]
    assert len(mine) == 1 and mine[0]["issues"] == ["edition: missing evidence or mismatch"]
    assert mine[0]["record"]["edition"] == "Rev. ed"


def test_an_edited_built_book_is_rechecked_as_a_book(tmp_path, offline):
    ws = seeded(tmp_path)
    (proposal,) = api.propose_new(ws, ["ISBN 9780195333244"], mailto=CONTACT)
    assert proposal.proposed_raw == KAHA12
    same = api.recheck_proposal(ws, proposal, proposal.proposed_raw, mailto=CONTACT)
    assert same.unsupported is None and same.status == "metadata_verified" and same.complete
    assert same.entry_type == "book" and same.record_source == "loc-catalogue" and api.acceptable(same)
    # the same text as a book that no catalogue record built is, as before, not one the builder makes
    from dataclasses import replace
    assert api.recheck_proposal(ws, replace(proposal, record_source="crossref"), proposal.proposed_raw,
                                mailto=CONTACT).unsupported == "book"


def test_add_at_the_command_line_shows_the_catalogue_as_the_source(tmp_path, offline):
    ws = seeded(tmp_path)
    argv = ["--library", str(ws.root), "add", "ISBN 9780195333244", "--mailto", CONTACT]
    status, out = terminal(tmp_path, ADD, "a\n", argv=argv)
    assert status == 0, out
    assert "author: None -> M J Kahana (source: loc-catalogue)" in out
    assert "Verification: metadata_verified" in out and "Added: Kaha12" in out
    assert "Built from the Library of Congress catalogue record LCCN 2012007685" in out
    assert ws.bib.read_text(encoding="utf-8").strip() == KAHA12
