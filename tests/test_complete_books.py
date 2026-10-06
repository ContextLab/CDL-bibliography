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
    # asking for a book asks the catalogue and nothing else (no Crossref, PubMed or arXiv answer is saved
    # for this search: a request to one of them would be refused and listed in ``errors``)
    lines = []
    asked = intake.find_candidates(ws, client=client, title="Numerical optimization", authors=["Nocedal"], book=True,
                                   progress=lines.append)
    assert [lead["lccn"] for lead in asked] == ["2006923897", "99013263"] and asked.errors == []
    assert lines == ["loc-catalogue: 2 records"] and client.requests == 0
    assert intake.SOURCES == ("crossref", "pubmed", "arxiv") and intake.CATALOGUE == "loc-catalogue"
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


def test_a_crossref_record_of_a_book_is_still_not_built():
    # Crossref's record of a book states no edition and no place: it fills nothing, as before.
    assert "book" not in complete.KINDS
    proposal = complete.build({}, {"type": "book", "DOI": "10.1201/b16018", "title": ["Bayesian Data Analysis"]})
    assert proposal.unsupported == "book" and proposal.proposed_raw is None


# --- a search for a paper does not ask the catalogue; a search that finds nothing does -----------

def test_a_paper_search_that_finds_leads_makes_no_catalogue_request(tmp_path):
    # searches.json.gz holds no catalogue answer: a request to lx2.loc.gov would be refused by the
    # transport, counted in ``requests`` and named in ``errors``.
    saved = offline_client(tmp_path / "papers", "searches.json.gz")
    try:
        assert not saved.cache.db.execute("SELECT count(*) FROM responses WHERE request LIKE 'loc-sru%'").fetchone()[0]
        lines = []
        found = intake.find_candidates(library(tmp_path / "lib"), client=saved, per_source=5,
                                       title="Attention is all you need", authors=["Vaswani"], progress=lines.append)
        assert found and found.errors == [] and saved.requests == 0
        assert [line.split(":")[0] for line in lines] == ["crossref", "pubmed", "arxiv"]       # and no fourth source
        assert not any(lead["source"] == "loc-catalogue" for lead in found)
        # asked for as a book, the same search does go to the catalogue, and to nothing else
        booked = intake.find_candidates(library(tmp_path / "lib2"), client=saved, per_source=5, book=True,
                                        title="Attention is all you need", authors=["Vaswani"])
        assert booked == [] and saved.requests == 1
        assert booked.errors == [("loc-catalogue", "offline: request to lx2.loc.gov refused")]
    finally:
        saved.cache.close()


def test_the_catalogue_is_asked_when_the_paper_sources_give_no_lead(tmp_path):
    # Tulving and Donaldson 1972: Crossref's five records are other works, PubMed and arXiv have none.
    saved = offline_client(tmp_path / "fallback", "typed_books.json.gz")
    try:
        lines = []
        found = intake.find_candidates(library(tmp_path / "lib"), client=saved, per_source=5,
                                       title="Organization of memory", authors=["Tulving"], progress=lines.append)
        assert lines == ["crossref: 5 records", "pubmed: 0 records", "arxiv: 0 records",
                         "loc-catalogue: asked for a book, because Crossref, PubMed and arXiv gave no record for "
                         "this title and author", "loc-catalogue: 1 record"]
        assert [(lead["source"], lead["lccn"], lead["year"]) for lead in found] == [("loc-catalogue", "73182647", "1972")]
        assert found.errors == [] and saved.requests == 0
        # a title alone, or authors alone, never goes to the catalogue: its search needs both
        alone = intake.find_candidates(library(tmp_path / "lib2"), client=saved, per_source=5, title="Zzyzxqv qwxzvk")
        assert all(source != "loc-catalogue" for source, _ in alone.errors) and len(alone.errors) == 3
    finally:
        saved.cache.close()


# --- a typed @book is completed (owner's decision 2026-10-06) -------------------------------------

def typed_book(tmp_path, raw):
    path = tmp_path / "typed.bib"
    path.write_text(raw + "\n", encoding="utf-8")
    return next(iter(load_entries(path).values()))


def test_a_typed_book_with_an_isbn_is_completed_field_by_field(client, tmp_path):
    raw = "@book{Kaha12,\n\tIsbn = {9780195333244},\n\tTitle = {Foundations of human memory}}"
    proposal = complete.propose(complete.Query.from_entry(typed_book(tmp_path, raw)), client, client.cache)
    assert proposal.proposed_raw == KAHA12 and proposal.typed_raw == raw and proposal.key_typed == "Kaha12"
    assert [(c.field, c.typed, c.proposed, c.source, c.kind) for c in proposal.changes] == [
        ("address", None, "New York, {NY}", "loc-catalogue", "filled"),
        ("author", None, "M J Kahana", "loc-catalogue", "filled"),
        ("publisher", None, "Oxford University Press", "loc-catalogue", "filled"),
        ("title", "Foundations of human memory", "Foundations of human memory", "typed", "kept"),
        ("year", None, "2012", "loc-catalogue", "filled"),
        ("isbn", "9780195333244", None, "not a house field", "dropped")]
    assert proposal.status == "metadata_verified" and proposal.complete and not proposal.needs_decision
    assert proposal.unsupported is None and api.worth_showing(proposal) and client.requests == 0


def test_a_typed_book_with_two_editions_is_given_the_candidates_and_nothing_is_written(tmp_path, offline):
    raw = "@book{NoceWrig06,\n\tAuthor = {J Nocedal and S J Wright},\n\tTitle = {Numerical optimization}}"
    ws = seeded_library(tmp_path / "lib", "books.json.gz")
    ws.bib.write_text(raw + "\n", encoding="utf-8")
    (proposal,) = api.propose(ws, keys=["NoceWrig06"], reference=None, mailto=CONTACT)
    assert proposal.proposed_raw is None and proposal.typed_raw == raw and proposal.needs_decision
    assert proposal.issues == ["2 catalogue records may be this book (the title and the first author): editions are "
                               "distinct works, and one has to be chosen; the entry is left as typed."]
    assert [(c["year"], c["lccn"], c["journal"]) for c in proposal.candidates] == [
        ("2006", "2006923897", "Springer, 2nd ed"), ("1999", "99013263", "Springer")]
    assert not api.acceptable(proposal) and ws.bib.read_text(encoding="utf-8") == raw + "\n"
    # the typed year, or the typed edition, chooses among the editions; the person's choice does too
    for line in ("\tYear = {2006}", "\tEdition = {2\\textsuperscript{nd}}"):
        ws.bib.write_text(raw[:-1] + ",\n" + line + "}\n", encoding="utf-8")
        (dated,) = api.propose(ws, keys=["NoceWrig06"], reference=None, mailto=CONTACT)
        assert dated.proposed_raw == NOCEWRIG06 and dated.status == "metadata_verified", line
    ws.bib.write_text(raw + "\n", encoding="utf-8")
    chosen = api.choose_candidate(ws, proposal, proposal.candidates[0], mailto=CONTACT, in_library=True)
    assert chosen.proposed_raw == NOCEWRIG06 and chosen.typed_raw == raw and chosen.status == "metadata_verified"
    assert {c.field: c.kind for c in chosen.changes} == {"address": "filled", "author": "kept", "edition": "filled",
                                                         "publisher": "filled", "title": "kept", "year": "filled"}
    done = api.apply_proposals(ws, [chosen])
    assert done.written == ["NoceWrig06"] and ws.bib.read_text(encoding="utf-8").strip() == NOCEWRIG06


def test_a_typed_year_that_is_not_the_records_is_a_question_and_is_not_overwritten(tmp_path):
    saved = offline_client(tmp_path / "typed", "typed_books.json.gz", "books.json.gz")
    try:
        raw = ("@book{Galt84,\n\tAuthor = {F Galton},\n\tLccn = {10032396},\n"
               "\tTitle = {Inquiries into human faculty and its development},\n\tYear = {1884}}")
        proposal = complete.propose(complete.Query.from_entry(typed_book(tmp_path, raw)), saved, saved.cache)
        assert "\tYear = {1884}}" in proposal.proposed_raw and "1883" not in proposal.proposed_raw
        assert change(proposal, "year") == complete.FieldChange("year", "1884", "1883", "loc-catalogue", "question")
        assert {c.field: c.kind for c in proposal.changes} == {
            "address": "filled", "author": "kept", "publisher": "filled", "title": "kept", "year": "question",
            "lccn": "dropped"}
        assert proposal.issues == [
            "year: the typed value '1884' is not what the catalogue record has ('1883'); the typed value is kept "
            "until this is decided", "No unique, fully matching catalogue edition",
            "loc-catalogue : year: missing evidence or mismatch"]
        assert proposal.status == "needs_review" and proposal.needs_decision and not proposal.complete
        assert not api.acceptable(proposal) and saved.requests == 0
    finally:
        saved.cache.close()


def test_a_typed_book_that_is_complete_already_gives_nothing_to_decide_and_is_then_verified(tmp_path, offline):
    ws = seeded_library(tmp_path / "lib", "books.json.gz")
    ws.bib.write_text(KAHA12 + "\n", encoding="utf-8")
    assert api.completion_due(ws, reference=None).keys == ["Kaha12"]         # new, and not yet verified
    (proposal,) = api.propose(ws, keys=["Kaha12"], reference=None, mailto=CONTACT)
    assert proposal.proposed_raw == KAHA12 and {c.kind for c in proposal.changes} == {"kept"}
    assert proposal.status == "metadata_verified" and proposal.complete and not proposal.needs_decision
    assert not api.worth_showing(proposal)                                   # so no offer is made for it
    offers = list(api.completion_offers(ws, reference=None, mailto=CONTACT))
    assert [(offer.key, offer.proposals, offer.error) for offer in offers] == [("Kaha12", [], None)]
    # a typed book with only its ISBN: offered, accepted, written over the typed text, verified by the gate
    typed = "@book{Kaha12,\n\tIsbn = {9780195333244},\n\tTitle = {Foundations of human memory}}"
    ws.bib.write_text(typed + "\n", encoding="utf-8")
    (offer,) = list(api.completion_offers(ws, reference=None, mailto=CONTACT))
    (completed,) = offer.proposals
    assert completed.proposed_raw == KAHA12 and api.acceptable(completed)
    assert api.apply_proposals(ws, [completed]).written == ["Kaha12"]
    assert ws.bib.read_text(encoding="utf-8").strip() == KAHA12
    check = api.check_keys(ws, ["Kaha12"], mailto=CONTACT)
    assert check.ok and check.citations.checked["Kaha12"]["accepted_source"] == "loc-catalogue"
    assert api.completion_due(ws, reference=None).keys == []


def test_a_typed_book_with_a_doi_or_without_enough_to_find_it_is_left_as_typed_and_says_why(client, tmp_path):
    gelman = complete.propose(complete.Query.from_entry(FROZEN["GelmEtal13"]), client, client.cache)
    assert gelman.proposed_raw is None and gelman.unsupported is None and gelman.status is None
    assert gelman.issues == [
        "A book with a DOI is not completed: the catalogue check is for a book without a supplied DOI, and "
        "Crossref's record of a book states no edition and no place of publication. The entry is left as typed; "
        "`cdlbib verify` checks it against Crossref"]
    bare = complete.propose(complete.Query.from_entry(typed_book(tmp_path, "@book{X20,\n\tYear = {2020}}")),
                            client, client.cache)
    assert bare.proposed_raw is None and bare.issues == [
        "A typed book is looked up by its ISBN or LCCN, or by its title together with its authors or editors; the "
        "entry has neither; the entry is left as typed"]
    assert client.requests == 0


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


# --- review of 2026-10-06, item 6: the record must carry the number asked for --------------------

def _hostile(client, genuine_query, asked_query):
    """The catalogue's real answer to ``genuine_query``, saved as its answer to ``asked_query``
    with the echoed query rewritten: an answer that echoes what was asked and holds another record."""
    import hashlib
    saved = dict(client.cache.response("loc-sru-v1:10:" + genuine_query, 10**9))
    raw = saved["raw_xml"].replace(genuine_query.replace('"', "&quot;"), asked_query.replace('"', "&quot;")).replace(
        genuine_query, asked_query)
    saved.update(raw_xml=raw, query=asked_query, document_sha256=hashlib.sha256(raw.encode()).hexdigest())
    client.cache.save_response("loc-sru-v1:10:" + asked_query, saved)


def test_an_answer_that_echoes_the_isbn_and_holds_another_book_is_not_used(client, tmp_path):
    # Kahana's record, returned for the ISBN of Nocedal and Wright's second edition (a valid ISBN).
    _hostile(client, 'bath.isbn="9780195333244"', 'bath.isbn="9780387303031"')
    proposal = book(client, "ISBN 9780387303031")
    assert proposal.proposed_raw is None and proposal.status is None and proposal.needs_decision
    assert proposal.issues == ["The catalogue's answer for the ISBN 9780387303031 holds 1 record, none of which "
                               "carries that number itself; it is not used; nothing is proposed"]
    _hostile(client, 'bath.lccn="10032396"', 'bath.lccn="2012007685"')
    wrong = book(client, "LCCN 2012007685")
    assert wrong.proposed_raw is None and "none of which carries that number itself" in wrong.issues[0]
    # a typed book with that ISBN is left as typed for the same reason
    typed = "@book{NoceWrig06,\n\tIsbn = {9780387303031},\n\tTitle = {Numerical optimization}}"
    left = complete.propose(complete.Query.from_entry(typed_book(tmp_path, typed)), client, client.cache)
    assert left.proposed_raw is None and left.issues[0].endswith("it is not used; the entry is left as typed")
    assert client.requests == 0


def test_the_record_built_from_is_kept_with_its_own_matching_field_and_the_check_is_held_to_it(client, tmp_path):
    thirteen = book(client, "ISBN 9780195333244")
    (built,) = thirteen.choices
    assert built == {"field": "record", "by": "loc-catalogue", "record_id": "17200404", "lccn": "2012007685",
                     "isbns": ["9780195333244", "0195333241"],
                     "matched": {"field": "020", "value": "9780195333244", "asked": "9780195333244"}}
    by_lccn = book(client, "LCCN 10032396")
    assert by_lccn.choices[0]["matched"] == {"field": "010", "value": "10032396", "asked": "10032396"}
    assert book(client, "Organization of memory", author="Tulving").choices[0]["matched"] is None     # no number was asked
    # the two lengths of one ISBN are the same number; another number is not
    response = client.cache.response('loc-sru-v1:10:bath.isbn="9780195333244"', 10**9)
    (xml,) = catalogue_review.parse_search(response["raw_xml"], 'bath.isbn="9780195333244"')["records"]
    assert book_build.record_isbns(xml) == ["9780195333244", "0195333241"]
    assert book_build.matched_identifier(xml, isbn="0195333241")["value"] == "0195333241"
    assert book_build.same_isbn("0195333241", "9780195333244") and book_build.same_isbn("9780195333244", "0195333241")
    assert not book_build.same_isbn("9780195333244", "9780387303031")
    assert not book_build.same_isbn("9780195333245", "9780195333245")              # a wrong check digit is no ISBN
    assert book_build.matched_identifier(xml, isbn="9780387303031") is None
    assert book_build.matched_identifier(xml, lccn="2012007685") and not book_build.matched_identifier(xml, lccn="10032396")
    # the check's answer counts only for the record the entry was built from
    entry = typed_book(tmp_path, KAHA12)
    open_result = {"status": "needs_review", "issues": [], "candidates": [], "attempts": []}
    same = book_build.catalogue_check(entry, dict(open_result), client, record_id="17200404")
    assert same["status"] == "metadata_verified" and same["accepted_record_id"] == "17200404"
    other = book_build.catalogue_check(entry, dict(open_result), client, record_id="999")
    assert other["status"] == "needs_review" and other["issues"] == [
        "The catalogue check matched the entry to record 17200404, not to the record it was built from (999); it is "
        "not taken as verified"]
    assert "accepted_record_id" not in other and client.requests == 0


# --- item 8: plain source text is escaped before house braces are added ---------------------------

def _altered(client, **swap):
    """Kahana's real record with some of its transcribed text replaced."""
    response = client.cache.response('loc-sru-v1:10:bath.isbn="9780195333244"', 10**9)
    (xml,) = catalogue_review.parse_search(response["raw_xml"], 'bath.isbn="9780195333244"')["records"]
    for old, new in swap.items():
        assert old in xml
        xml = xml.replace(old, new)
    return xml


def test_characters_tex_reads_as_commands_are_escaped_and_the_check_still_agrees(client, tmp_path):
    xml = _altered(client, **{"Foundations of human memory": "100% human memory: R&amp;D notes on C# and snake_case",
                              "Oxford University Press": "A&amp;B Press"})
    built = book_build.build_book(xml)
    assert "\tTitle = {100\\% human memory: {R\\&D} notes on {C}\\# and snake\\_case}" in built.proposed_raw
    assert "\tPublisher = {{A\\&B} Press}" in built.proposed_raw            # and "B" is not lowered after the ampersand
    assert built.unfilled == [] and not built.needs_decision
    # no unescaped special character is left in any field of the entry
    import re
    fields = fields_of(built.proposed_raw, tmp_path)
    for name, value in fields.items():
        assert not re.search(r"(?<!\\)[%&#_~^$]", value), (name, value)
    # the text reads back as exactly these fields through the strict scanner (nothing was cut at the %)
    assert {k.lower(): v for k, v in intake.scan_entry(built.proposed_raw)[2].items()}["title"] == fields["title"]
    # and the catalogue check compares the escaped fields as equal to the record's plain text
    record = catalogue_review.parse_edition(xml)
    evidence, issues = catalogue_review.compare_edition(dict(fields), record, xml)
    assert issues == [] and evidence["title"]["match"] and evidence["publisher"]["match"]
    assert book_build.plain_source("title", "100% & #1_a") == "100\\% \\& \\#1\\_a"
    # a brace in source text is never taken for the builder's own: house braces are added after escaping
    with pytest.raises(ValueError, match="a backslash or a brace"):
        book_build.plain_source("title", "{Gestalt} & co")
    assert book_build._braced_title(book_build.plain_source("title", "Essays on Gestalt & R&D")) == (
        "Essays on {Gestalt} \\& {R\\&D}")


def test_text_with_no_plain_tex_form_is_not_written(client):
    for text in ("x ~ y", "x^2", "a \\textbf{b}", "cost $5"):
        with pytest.raises(ValueError):
            book_build.plain_source("title", text)
    tilde = book_build.build_book(_altered(client, **{"Foundations of human memory": "Memory ~ a history"}))
    assert "Title" not in tilde.proposed_raw and tilde.needs_decision and not tilde.complete
    assert [u.field for u in tilde.unfilled] == ["title"] and "Memory ~ a history" in tilde.unfilled[0].source_values.values()
    caret = book_build.build_book(_altered(client, **{"Oxford University Press": "X^2 Press"}))
    assert "Publisher" not in caret.proposed_raw and caret.unfilled[0].field == "publisher"
    assert caret.unfilled[0].reason.startswith("publisher: the source text has a character with no plain TeX form")
    # a name is never escaped: one with such a character is not written
    named = book_build.build_book(_altered(client, **{"Kahana, Michael J.": "Kah%ana, Michael J.",
                                                     "Michael Jacob Kahana": "Michael Jacob Kah%ana"}))
    assert "Author" not in named.proposed_raw and named.unfilled[0] == complete.Unfilled(
        "author", "author: a name in the record has a character that is not plain text in TeX",
        {"loc-catalogue": "Michael Jacob Kah%ana"})


# --- security review of 2026-10-06: escaping and refusal are two layers, and the entry is read back ---

ALLOWED_FIELDS = {"address", "author", "edition", "editor", "publisher", "title", "year"}
HOSTILE = [
    "Title}, Note = {x",
    "}\n@misc{evil, title={x}}",
    "x}\n\n@misc{evil,\n\ttitle = {x}}\n@book{again",
    "\\input{/etc/passwd}",
    "\\write18{rm -rf ~}",
    "\\immediate\\write18{id}",
    "100%\nNote = {x},",
    "an opening { brace",
    "a closing } brace",
    "ends in a backslash\\",
    "^^5cinput",
    "tab\there",
    "nul\x00here",
    "@string{x = y}",
    "A" * 100_000,
    "$\\backslash$",
]


def _xml_text(text):
    from xml.sax.saxutils import escape
    return escape(text).replace("\x00", "&#0;") if "\x00" not in text else None


def _sound(proposal, tmp_path):
    """What must hold for any entry the builder returns, whatever the record said."""
    import re
    raw = proposal.proposed_raw
    assert raw.count("@") == 1 and raw.startswith("@book{") and raw.endswith("}")
    kind, key, scanned = intake.scan_entry(raw)                    # the strict scanner: one entry, plainly written
    assert kind == "book" and set(scanned) <= ALLOWED_FIELDS, scanned
    path = tmp_path / "back.bib"
    path.write_text(raw + "\n", encoding="utf-8")
    (entry,) = load_entries(path).values()                         # the library's own reader: exactly one entry
    assert set(entry["fields"]) - {"ENTRYTYPE", "ID"} == set(scanned)
    assert {k: v for k, v in entry["fields"].items() if k not in ("ENTRYTYPE", "ID")} == scanned
    for name, value in scanned.items():
        left = book_build._HOUSE_COMMAND.sub("", value)
        assert "\\" not in left and "@" not in value, (name, value)         # no command TeX would run
        assert intake.structure_problem(value) is None and len(value) <= 2 * book_build.MAX_FIELD
        assert not re.search(r"(?<!\\)[%&#_~^$]", left), (name, value)
    return scanned


@pytest.mark.parametrize("field, original", [("title", "Foundations of human memory"),
                                             ("publisher", "Oxford University Press"),
                                             ("address", "New York :")])
@pytest.mark.parametrize("hostile", HOSTILE, ids=[repr(h[:24]) for h in HOSTILE])
def test_a_hostile_value_in_a_record_never_changes_the_structure_of_the_entry(client, tmp_path, field, original, hostile):
    """The real record of Kahana 2012 with one transcribed value replaced, through the real
    builder: the field is left unfilled with the reason, or the record is not read at all
    (the check's grammar refuses it). Never a second entry, an extra field, or a command."""
    text = _xml_text(hostile)
    if text is None:
        pytest.skip("a NUL cannot be written in XML at all: the catalogue cannot send it")
    xml = _altered(client, **{original: text + (" :" if field == "address" else "")})
    try:
        built = book_build.build_book(xml)
    except ValueError:
        return                                                    # the check's grammar does not read such a record
    scanned = _sound(built, tmp_path)
    assert field not in scanned                                   # the hostile value is not written in any form
    (missing,) = [u for u in built.unfilled if u.field == field]
    assert missing.reason.startswith(field + ": ") and "it is not written" in missing.reason
    assert all(len(v) <= 200 for v in missing.source_values.values())          # nor is 100,000 characters of it kept
    assert "evil" not in built.proposed_raw and "Note" not in built.proposed_raw and "passwd" not in built.proposed_raw
    if field != "title":
        assert scanned["title"] == "Foundations of human memory"              # the rest of the entry is as it was


def test_the_two_layers_each_refuse_on_their_own(client, tmp_path):
    # layer 1: what is not plain text is refused, never repaired; what is plain is escaped
    for hostile in HOSTILE:
        with pytest.raises(ValueError):
            book_build.plain_source("title", hostile)
    assert book_build.plain_source("title", "100% of R&D, #1 in snake_case") == "100\\% of R\\&D, \\#1 in snake\\_case"
    assert book_build.plain_source("title", "100% of it")[3] == "\\"            # the % cannot open a comment
    # layer 2: a finished value is refused whatever produced it
    for bad in ("x}, Note = {y", "{open", "close}", "ends\\", "a\nb", "\\input{x}", "\\write18{x}", "@misc{a", "a^^5cb",
                "\\textbf{x}", "x" * (2 * book_build.MAX_FIELD + 1), "mail@host"):
        with pytest.raises(ValueError):
            book_build.checked_value("title", bad)
    for good in ("100\\% {R\\&D} notes", "New York, {NY}", "2\\textsuperscript{nd}", "Gl{\\\"o}ckner and {\\o}rsted",
                 "Fran{\\c{c}}ois"):
        assert book_build.checked_value("title", good) == good
    # the proof: an assembled entry must read back as exactly its fields
    fields = {"title": "A book", "year": "2012"}
    good = complete.render("book", "Key12", fields)
    assert book_build.proved(good, fields) == good
    for raw in (good.replace("{A book}", "{A book},\n\tNote = {x}"), good + "\n@misc{evil,\n\tTitle = {x}}",
                good.replace("A book", "A book}, Note = {x"), good.replace("@book", "@misc")):
        with pytest.raises(ValueError):
            book_build.proved(raw, fields)
    # the builder uses all three, and writes no source value by any other way
    import inspect
    source = inspect.getsource(book_build.build_book)
    assert "plain(\"title\"" in source and "plain(\"publisher\"" in source and "plain(\"address\"" in source
    assert "checked_value(name, written)" in source and "proved(complete.render(" in source
    assert 'r"[1-9]\\d{3}", fields["year"]' in source                              # the year is a pattern, not text
    assert "proved(" in inspect.getsource(book_build.propose_typed_book)
    from cdlbib import container_titles
    assert "render(" not in inspect.getsource(container_titles)                     # it writes no entry at all


def test_a_name_with_and_or_braces_is_not_written(client, tmp_path):
    hostile = [("Kahana, Michael J.", "Kahana and {Evil}, Michael J."), ("Kahana, Michael J.", "Kahana} and {x, Michael J."),
               ("Kahana, Michael J.", "Kahana, Michael and Mallory"), ("Kahana, Michael J.", "Kahana\\input, Michael J.")]
    for old, new in hostile:
        for byline in ("Michael Jacob Kahana", None):
            swap = {old: _xml_text(new)}
            if byline:        # with the transcribed byline changed to agree, so that the grammar reads the record
                given, family = new.split(", ")[1], new.split(", ")[0]
                swap[byline] = _xml_text(f"{given} {family}")
            try:
                built = book_build.build_book(_altered(client, **swap))
            except ValueError:
                continue                                           # the check's grammar does not read the record
            scanned = _sound(built, tmp_path)
            assert "author" not in scanned and "Evil" not in built.proposed_raw and "Mallory" not in built.proposed_raw
            assert [u.field for u in built.unfilled][:1] == ["author"]
    # the name guard itself, on people as the grammar hands them over
    record_people = [{"given": "Michael and Mallory", "family": "Kahana"}, {"given": "M", "family": "Kah{ana"},
                     {"given": "M", "family": "and"}, {"given": "M\nJ", "family": "Kahana"}]
    import re
    for person in record_people:
        assert any(book_build._SPECIAL.search(person[p]) or re.search(r"(?i)(?:^|\s)and(?:\s|$)|[\x00-\x1f\x7f]", person[p])
                   for p in ("given", "family")), person


# --- re-review of 2026-10-06, item 6: a cut answer, and an entry accepted some other way -------------

def _cut_answer(client, isbn):
    """An answer to an ISBN query that the catalogue cut short: it counts eleven records and
    returns ten, of which one (Kahana's real record, given this ISBN) carries the number."""
    import hashlib
    import re
    saved = dict(client.cache.response('loc-sru-v1:10:bath.isbn="9780195333244"', 10**9))
    raw = saved["raw_xml"]
    (wrapper,) = re.findall(r"<zs:record>.*?</zs:record>", raw, re.S)
    records = []
    for position in range(1, 11):
        one = wrapper.replace("<zs:recordPosition>1<", f"<zs:recordPosition>{position}<")
        one = one.replace(">17200404<", f">{17200404 + position - 1}<")
        if position == 1:
            one = one.replace("9780195333244", isbn)
        else:                      # the others are records of other books: they carry other numbers
            one = one.replace("9780195333244", "9780387303031").replace("0195333241", "0387303030")
        records.append(one)
    raw = raw.replace(wrapper, "".join(records)).replace("<zs:numberOfRecords>1<", "<zs:numberOfRecords>11<")
    query = f'bath.isbn="{isbn}"'
    raw = raw.replace('bath.isbn="9780195333244"', query).replace("bath.isbn=&quot;9780195333244&quot;",
                                                                 f"bath.isbn=&quot;{isbn}&quot;")
    saved.update(raw_xml=raw, query=query, document_sha256=hashlib.sha256(raw.encode()).hexdigest())
    client.cache.save_response("loc-sru-v1:10:" + query, saved)
    parsed = catalogue_review.parse_search(raw, query)
    assert parsed["truncated"] and len(parsed["records"]) == 10
    return parsed


def test_one_matching_record_in_a_cut_answer_is_not_the_only_one(client, tmp_path):
    parsed = _cut_answer(client, "9781439840955")
    assert sum(bool(book_build.matched_identifier(xml, isbn="9781439840955")) for xml in parsed["records"]) == 1
    proposal = book(client, "ISBN 9781439840955")
    assert proposal.proposed_raw is None and proposal.status is None and proposal.needs_decision
    assert proposal.issues == [
        "The catalogue's answer for the ISBN 9781439840955 was cut short, so the record in it cannot be taken as "
        "the only one with that number; nothing is proposed. The catalogue lists more records than the ten it "
        "returned; give the ISBN or the LCCN."]
    assert len(proposal.candidates) == 1                    # the one record that carries the number is shown, not built
    typed = "@book{Gelm14,\n\tIsbn = {9781439840955},\n\tTitle = {Bayesian data analysis}}"
    left = complete.propose(complete.Query.from_entry(typed_book(tmp_path, typed)), client, client.cache)
    assert left.proposed_raw is None and "one has to be chosen; the entry is left as typed" in left.issues[0]
    assert client.requests == 0


def test_an_acceptance_that_is_not_the_catalogues_of_the_built_record_is_put_to_the_catalogue_check(client, tmp_path):
    entry = typed_book(tmp_path, KAHA12)
    elsewhere = {"status": "metadata_verified", "accepted_source": "crossref", "accepted_doi": "10.1093/x", "issues": [],
                 "candidates": [], "attempts": []}
    # with no record to hold it to, an accepted result is returned as it is (as before)
    assert book_build.catalogue_check(entry, dict(elsewhere), client) == elsewhere
    # an entry built from record 17200404: an acceptance by another source is not the answer; the catalogue's is
    held = book_build.catalogue_check(entry, dict(elsewhere), client, record_id="17200404")
    assert (held["status"], held["accepted_source"], held["accepted_record_id"]) == (
        "metadata_verified", "loc-catalogue", "17200404")
    # ... and when the catalogue accepts another record than the one it was built from, it is not verified
    for accepted in (elsewhere, {"status": "metadata_verified", "accepted_source": "loc-catalogue",
                                 "accepted_record_id": "17200404", "issues": [], "candidates": [], "attempts": []}):
        other = book_build.catalogue_check(entry, dict(accepted), client, record_id="999")
        assert other["status"] == "needs_review" and "not to the record it was built from (999)" in other["issues"][0]
    # the same acceptance, of the same record, is returned without another look
    same = {"status": "metadata_verified", "accepted_source": "loc-catalogue", "accepted_record_id": "17200404",
            "issues": [], "candidates": [], "attempts": []}
    assert book_build.catalogue_check(entry, dict(same), client, record_id="17200404") == same
    import inspect
    source = inspect.getsource(complete.checked)
    assert source.index("catalogue_check(entry, result, client, record_id=") > source.index("_anthology_checked")
    assert client.requests == 0
