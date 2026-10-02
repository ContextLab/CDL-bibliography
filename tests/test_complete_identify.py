"""Entry completion, finding the work: ``complete.Query``, ``identify``, ``propose``,
``build_arxiv`` and ``checked``.

Nothing here is invented. Every lookup is a real saved response, replayed through the real
client: ``extra_sources.make_client(..., offline=True)`` is the project's ``PoliteClient``
over a real response cache with a transport that refuses every request, and the cache is
filled with

- tests/fixtures/completion/responses.json: the 23 responses fetched once for these tests
  on 2026-10-02 (the README beside it lists each request), stored as the client cached them;
- tests/fixtures/arxiv_preprints.json: the arXiv, arXiv-page and DataCite documents the
  arXiv check's own tests use.

So a lookup the fixtures do not hold fails as a refused request, and ``client.requests == 0``
shows that none was attempted. Expected entries are the exact text of the same work's entry
in the frozen library fixture (``library_entry``); no test reads the live cdl.bib. The three
tests at the end make real requests, as the gate tests of test_machinery_2026_09_25.py do.
"""
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from cdlbib import complete
from cdlbib import extra_sources as xs
from cdlbib.verification import Cache, PoliteClient, dumps, load_entries

from test_machinery_2026_09_25 import RAME72, ZOLL90, crossref_contact

ROOT = Path(__file__).resolve().parents[1]
SAVED = json.loads((ROOT / "tests/fixtures/completion/responses.json").read_text(encoding="utf-8"))
ARXIV = json.loads((ROOT / "tests/fixtures/arxiv_preprints.json").read_text(encoding="utf-8"))
RECORDS = json.loads((ROOT / "tests/fixtures/completion/records.json").read_text(encoding="utf-8"))
FROZEN = (ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib").read_text(encoding="utf-8")
CONTACT = "valid@example.org"  # never sent anywhere: the transport refuses every request
CAPITALS = ("title: capitalisation taken from a title-case source; proper nouns and acronyms cannot be told "
            "apart from ordinary words")
ZOLLER_TITLE = "Students' misunderstandings and misconceptions in college freshman chemistry (general and organic)"


def library_entry(key):
    """The exact text of an entry in the frozen library fixture."""
    start = FROZEN.index("@article{" + key + ",")
    return FROZEN[start:FROZEN.index("}}\n", start) + 2]


@pytest.fixture
def client(tmp_path):
    """The real client over a real cache holding the saved responses; no network."""
    client = xs.make_client(tmp_path / "responses.sqlite3", contact=CONTACT, offline=True)
    for item in SAVED:
        request = item["request"]
        if isinstance(request, list):  # PubMed requests name the caller's contact address
            url, params, xml = request
            request = dumps([url, {k: CONTACT if v == "CONTACT" else v for k, v in params.items()}, xml])
        client.cache.save_response(request, item["response"])
    for case in ARXIV.values():
        for document in case.get("raw", case).values():
            if isinstance(document, dict) and "url" in document:
                client.cache.save_response("arxiv-source-v1:" + document["url"], document)
    yield client
    client.cache.close()


def propose(client, text, **given):
    return complete.propose(complete.Query.parse(text, **given), client, client.cache)


def typed_entry(tmp_path, text):
    path = tmp_path / "typed.bib"
    path.write_text(text + "\n", encoding="utf-8")
    return next(iter(load_entries(path).values()))


def kinds(proposal):
    return {change.field: change.kind for change in proposal.changes}


# --- what the person gave -----------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("10.1002/tea.3660271011", {"doi": "10.1002/tea.3660271011"}),
    ("doi:10.1002/tea.3660271011", {"doi": "10.1002/tea.3660271011"}),
    ("https://doi.org/10.1002/tea.3660271011", {"doi": "10.1002/tea.3660271011"}),
    ("http://dx.doi.org/10.1016/S0146-664X(72)80017-0", {"doi": "10.1016/S0146-664X(72)80017-0"}),
    ("https://doi.org/10.1016/S0146-664X%2872%2980017-0", {"doi": "10.1016/S0146-664X(72)80017-0"}),
    ("PMID:13896567", {"pmid": "13896567"}),
    ("pmid 13896567", {"pmid": "13896567"}),
    ("https://pubmed.ncbi.nlm.nih.gov/13896567/", {"pmid": "13896567"}),
    ("2208.02957", {"arxiv": "2208.02957"}),
    ("arXiv:2208.02957v1", {"arxiv": "2208.02957v1"}),
    ("https://arxiv.org/abs/2208.02957", {"arxiv": "2208.02957"}),
    ("https://arxiv.org/pdf/2208.02957v1.pdf", {"arxiv": "2208.02957v1"}),
    ("cs/0504107v2", {"arxiv": "cs/0504107v2"}),
    ("10.48550/arXiv.2208.02957", {"arxiv": "2208.02957"}),
    ("https://doi.org/10.48550/arXiv.2208.02957", {"arxiv": "2208.02957"}),
    ("Backward learning in paired associates", {"title": "Backward learning in paired associates"}),
    ("  Backward   learning in\npaired associates ", {"title": "Backward learning in paired associates"}),
    ("13896567", {"title": "13896567"}),  # a bare number is not taken for a PMID
    ("1984", {"title": "1984"}),
    ("", {}),
])
def test_each_form_of_query_is_recognised(text, expected):
    query = complete.Query.parse(text)
    assert query == complete.Query(**expected)


def test_an_author_and_a_year_given_beside_the_text_are_kept():
    query = complete.Query.parse("Backward learning in paired associates", author=" B B Murdock ", year=1956)
    assert (query.title, query.author, query.year) == ("Backward learning in paired associates", "B B Murdock", "1956")
    assert complete.Query.parse("10.1002/tea.3660271011", author="", year=None).author is None


def test_a_typed_entry_is_a_query_for_its_doi_first(tmp_path):
    entry = typed_entry(tmp_path, ZOLL90)
    query = complete.Query.from_entry(entry)
    assert (query.doi, query.pmid, query.arxiv) == ("10.1002/tea.3660271011", None, None)
    assert (query.title, query.author, query.year) == (ZOLLER_TITLE, "U Zoller", "1990")
    assert (query.raw, query.key) == (ZOLL90, "Zoll90") and query.fields == entry["fields"]


@pytest.mark.parametrize("key, identifier", [
    ("PianHill22", "2208.02957"),    # Journal = {{arXiv}}, the id in Volume, the arXiv DOI
    ("CarlWagn18", "1801.01944"),    # the id in Pages
    ("AlvaEtal05", "cs/0504107v2"),  # an old-style id with a version, in Pages, no DOI
])
def test_a_typed_arxiv_entry_is_a_query_for_its_arxiv_id(tmp_path, key, identifier):
    query = complete.Query.from_entry(typed_entry(tmp_path, library_entry(key)))
    assert (query.arxiv, query.doi) == (identifier, None)


def test_a_typed_entry_with_only_an_arxiv_doi_or_a_pmid(tmp_path):
    query = complete.Query.from_entry(typed_entry(tmp_path, "@article{New, doi = {10.48550/arXiv.2208.02957}}"))
    assert (query.arxiv, query.doi) == ("2208.02957", None)
    query = complete.Query.from_entry(typed_entry(tmp_path, "@article{New, pmid = {13896567}}"))
    assert (query.pmid, query.doi, query.arxiv) == ("13896567", None, None)


# --- a DOI --------------------------------------------------------------------------------------

def test_a_doi_alone_gives_the_complete_verified_entry(client):
    proposal = propose(client, "10.1002/tea.3660271011")
    assert proposal.proposed_raw == library_entry("Zoll90") == ZOLL90
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    assert proposal.unfilled == [] and proposal.candidates == []
    assert kinds(proposal) == {"author": "filled", "doi": "kept", "journal": "filled", "number": "filled",
                               "pages": "filled", "title": "filled", "volume": "filled", "year": "filled"}
    assert (proposal.key_typed, proposal.key_proposed, proposal.typed_raw) == (None, "Zoll90", None)
    assert proposal.record_source == "crossref" and proposal.doi == "10.1002/tea.3660271011"
    assert client.requests == 0


def test_identify_gives_the_dois_own_record_and_its_pubmed_record(client):
    found = complete.identify(complete.Query.parse("10.1002/tea.3660271011"), client)
    assert found.record["DOI"] == "10.1002/tea.3660271011" and found.record["type"] == "journal-article"
    assert (found.source, found.corroborating, found.candidates, found.note) == ("crossref", None, [], None)
    found = complete.identify(complete.Query.parse("10.1037/h0041332"), client)  # PubMed has this one
    assert found.source == "crossref+pubmed" and found.corroborating["DOI"] == "10.1037/h0041332"
    assert found.corroborating["page"] == "1-11" and found.record["DOI"] == "10.1037/h0041332"


def test_a_typed_stub_with_a_doi_keeps_its_key_and_its_text(client, tmp_path):
    stub = "@article{Zoller1990,\n  doi = {10.1002/tea.3660271011}\n}"
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, stub)), client, client.cache)
    assert proposal.typed_raw == stub and proposal.key_typed == "Zoller1990" and proposal.key_proposed == "Zoll90"
    assert proposal.proposed_raw == ZOLL90.replace("{Zoll90,", "{Zoller1990,")
    # The verifier accepts the entry; the format checker names the key it would write.
    assert proposal.status == "metadata_verified"
    assert proposal.issues == ["format: the format checker would write the key as Zoll90"] and proposal.needs_decision


def test_a_doi_crossref_does_not_have_gives_no_record_and_nothing_is_searched(client, tmp_path):
    proposal = propose(client, "10.1002/tea.3660271011x")  # the DOI above with a letter added
    assert proposal.proposed_raw is None and proposal.status is None and proposal.changes == []
    assert proposal.issues == ["The DOI 10.1002/tea.3660271011x was not found in Crossref (HTTP 404); nothing was "
                               "searched for in its place and the entry is left as typed"]
    assert proposal.needs_decision and proposal.candidates == []
    # A typed entry with that DOI and a title Crossref's search would find: still no search
    # (the search is not among the saved responses, so one would have been a refused request).
    typed = ZOLL90.replace("3660271011}", "3660271011x}")
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, typed)), client, client.cache)
    assert proposal.proposed_raw is None and proposal.typed_raw == typed and proposal.key_typed == "Zoll90"
    assert proposal.status is None and "was not found in Crossref" in proposal.issues[0]
    assert client.requests == 0


def test_a_text_that_is_not_a_doi_is_reported_not_raised(client, tmp_path):
    entry = typed_entry(tmp_path, "@article{New, doi = {not a doi}, title = {Anything}}")
    proposal = complete.propose(complete.Query.from_entry(entry), client, client.cache)
    assert proposal.proposed_raw is None and proposal.needs_decision
    assert proposal.issues == ["doi: Invalid DOI: 'not a doi'; the entry is left as typed"]


# --- a PMID -------------------------------------------------------------------------------------

def test_a_pmid_gives_the_entry_of_its_doi_with_both_sources(client):
    proposal = propose(client, "PMID:13896567")
    assert proposal.proposed_raw == library_entry("Game62")
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    assert proposal.notes == ["PMID 13896567 has the DOI 10.1037/h0041332."]
    assert proposal.record_source == "crossref+pubmed" and kinds(proposal)["doi"] == "filled"
    assert {c.field: c.source for c in proposal.changes}["pages"] == "crossref+pubmed"
    assert client.requests == 0


# --- a title and an author ----------------------------------------------------------------------

def test_one_record_matching_title_first_author_and_year_is_the_record(client):
    proposal = propose(client, ZOLLER_TITLE, author="Zoller", year="1990")
    assert proposal.proposed_raw == library_entry("Zoll90")
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    assert proposal.notes == ["One record matches the title, the first author and the year: 10.1002/tea.3660271011."]
    assert kinds(proposal)["doi"] == "filled" and proposal.candidates == []
    assert client.requests == 0


def test_several_matching_records_are_listed_for_a_choice(client):
    # Crossref has this article under two DOIs (one deposit in capitals with the subtitle apart).
    proposal = propose(client, "Strength training and aerobic exercise: comparison and contrast", author="Knuttgen")
    assert proposal.proposed_raw is None and proposal.status is None and proposal.needs_decision
    assert proposal.issues == ["2 records match the title and the first author; one has to be chosen"]
    assert proposal.candidates == [
        {"authors": "HOWARD G. KNUTTGEN", "year": "2007", "journal": "Journal of Strength and Conditioning Research",
         "doi": "10.1519/00124278-200708000-00053",
         "title": "STRENGTH TRAINING AND AEROBIC EXERCISE: COMPARISON AND CONTRAST",
         "type": "journal-article", "source": "crossref"},
        {"authors": "Howard G. Knuttgen", "year": "2007",
         "journal": "The Journal of Strength and Conditioning Research", "doi": "10.1519/r-505011.1",
         "title": "Strength Training and Aerobic Exercise: Comparison and Contrast",
         "type": "journal-article", "source": "crossref"}]
    assert client.requests == 0


def test_a_record_that_is_only_similar_is_listed_and_never_taken(client, tmp_path):
    # The printed title is: "Backward" learning in paired associates.  -- not the typed one.
    typed = ("@article{Murd56,\n\tAuthor = {B B Murdock},\n\tTitle = {Backward learning in paired associates},\n"
             "\tYear = {1956}}")
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, typed)), client, client.cache)
    assert proposal.proposed_raw is None and proposal.typed_raw == typed and proposal.needs_decision
    assert proposal.issues == ["No record matches the title, the first author and the year exactly; 1 similar "
                               "record found, and none is taken without a choice"]
    assert proposal.candidates == [
        {"authors": "Bennet B. Murdock", "year": "1956", "journal": "Journal of Experimental Psychology",
         "doi": "10.1037/h0044314", "title": '"Backward" learning in paired associates.',
         "type": "journal-article", "source": "crossref"}]
    assert client.requests == 0


def test_no_matching_record_is_said_so(client):
    # A doctoral thesis of the library (Mann11): neither Crossref nor PubMed has it.
    proposal = propose(client, "Acquisition, storage, and retrieval in digital and biological brains",
                       author="J R Manning", year="2011")
    assert proposal.proposed_raw is None and proposal.candidates == [] and proposal.needs_decision
    assert proposal.issues == ["No record in Crossref or PubMed matches the title, the first author and the year; "
                               "the entry is left as typed"]
    assert client.requests == 0


def search_items(words):
    """The records of a saved Crossref search."""
    for item in SAVED:
        request = item["request"]
        if isinstance(request, list) and words in request[1].get("query.bibliographic", ""):
            return item["response"]["body"]["message"]["items"]
    raise KeyError(words)


def test_what_matching_means_on_the_saved_search_results():
    zoller = {"ENTRYTYPE": "article", "title": ZOLLER_TITLE.upper().replace("'", "’")}
    records = search_items("students' misunderstandings")
    own = next(r for r in records if r["DOI"] == "10.1002/tea.3660271011")
    judged = complete._judged(zoller, own, "crossref", "zoller", "1990")
    assert judged["strict"] and judged["plausible"]  # case and the kind of apostrophe do not count
    assert not complete._judged(zoller, own, "crossref", "zoller", "1991")["strict"]  # the year, when given
    assert complete._judged(zoller, own, "crossref", "zoller", None)["strict"]
    wrong_author = complete._judged(zoller, own, "crossref", "zollar", "1990")
    assert not wrong_author["strict"] and not wrong_author["plausible"]
    # With no author nothing is taken: the same title is only a candidate.
    untold = complete._judged(zoller, own, "crossref", None, None)
    assert not untold["strict"] and untold["plausible"]
    others = [r for r in records if r["DOI"] != "10.1002/tea.3660271011"]
    assert len(others) == 4
    assert not any(complete._judged(zoller, r, "crossref", "zoller", "1990")["plausible"] for r in others)
    # Two word edits or fewer make a title similar, never the same.
    murdock = {"ENTRYTYPE": "article", "title": "Backward learning in paired associates"}
    printed = next(r for r in search_items("backward learning") if r["DOI"] == "10.1037/h0044314")
    judged = complete._judged(murdock, printed, "crossref", "murdock", "1956")
    assert not judged["strict"] and judged["plausible"]
    assert complete._first_surname("B B Murdock") == complete._first_surname("Murdock, Bennet B.") == "murdock"
    assert complete._first_surname("M A A van der Meer and J R Manning") == "van der meer"
    assert complete._first_surname("") is None


def saved_record(doi):
    """The Crossref record of a saved DOI lookup."""
    for item in SAVED:
        body = item["response"].get("body")
        if isinstance(body, dict) and (body.get("message") or {}).get("DOI") == doi:
            return body["message"]
    raise KeyError(doi)


def test_matches_that_are_one_work_are_one_choice():
    def match(record):
        return {"record": record, "doi": record["DOI"], "source": "crossref", "strict": True, "plausible": True}

    # An article and its own preprint (the preprint's record names the article): the article.
    article, preprint = saved_record("10.1523/jneurosci.0360-19.2019"), saved_record("10.1101/511782")
    assert complete._distinct_works([match(preprint), match(article)]) == [match(article)]
    # A preprint whose record names no published version stays a choice of its own.
    unlinked = saved_record("10.1101/2020.01.27.922062")
    assert len(complete._distinct_works([match(unlinked), match(article)])) == 2
    # The two DOI forms APA registered for one article (the saved search result for JacoEtal92).
    import gzip
    cases = json.loads(gzip.open(ROOT / "tests/fixtures/phase0_cases.json.gz").read())["cases"]
    twins = {c["doi"]: c["record"] for c in cases["JacoEtal92"]["previous"]["candidates"]
             if c.get("source") == "crossref" and c.get("doi", "").endswith("0003-066x.47.6.802")}
    assert sorted(twins) == ["10.1037//0003-066x.47.6.802", "10.1037/0003-066x.47.6.802"]
    kept = complete._distinct_works([match(record) for record in twins.values()])
    assert [item["doi"] for item in kept] == ["10.1037/0003-066x.47.6.802"]
    # Two different DOIs of one article that are not that pair remain two choices (Knut07 above).


# --- preprints ----------------------------------------------------------------------------------

def test_a_preprint_doi_whose_record_names_the_published_article_offers_the_article(client):
    proposal = propose(client, "https://doi.org/10.1101/511782")
    assert proposal.proposed_raw == library_entry("SilvEtal19")
    assert proposal.issues == [
        "The DOI 10.1101/511782 is a preprint; its record names 10.1523/jneurosci.0360-19.2019 as the published "
        "version, which is proposed here (house rule: cite the published version).", CAPITALS]
    assert proposal.needs_decision and proposal.status == "metadata_verified"
    # The DOI that was given is never replaced without the person: it is a question.
    doi = next(c for c in proposal.changes if c.field == "doi")
    assert doi == complete.FieldChange("doi", "10.1101/511782", "10.1523/jneurosci.0360-19.2019", "crossref", "question")
    assert [(c["doi"], c["type"], c["journal"]) for c in proposal.candidates] == [
        ("10.1523/jneurosci.0360-19.2019", "journal-article", "The Journal of Neuroscience"),
        ("10.1101/511782", "posted-content", "")]
    found = complete.identify(complete.Query.parse("10.1101/511782"), client)
    assert found.published_for == "10.1101/511782" and found.record["DOI"] == "10.1523/jneurosci.0360-19.2019"
    assert client.requests == 0


def test_a_preprint_doi_that_names_no_published_version_is_left_as_typed(client):
    # The bioRxiv preprint of ChenEtal21: its own Crossref record has no link to the article.
    proposal = propose(client, "10.1101/2020.01.27.922062")
    assert proposal.proposed_raw is None and proposal.unsupported == "posted-content" and proposal.status is None
    assert proposal.issues == ["A record of type posted-content is not built automatically; the entry is left as typed"]
    assert client.requests == 0


NUMPY = (  # the published version of arXiv:2006.10256, as built
    "@article{HarrEtal20,\n"
    "\tAuthor = {C R Harris and K J Millman and S J van der Walt and R Gommers and P Virtanen and D Cournapeau "
    "and E Wieser and J Taylor and S Berg and N J Smith and R Kern and M Picus and S Hoyer and M H van Kerkwijk "
    "and M Brett and A Haldane and J F del R\\'{i}o and M Wiebe and P Peterson and P G\\'{e}rard-Marchant and "
    "K Sheppard and T Reddy and W Weckesser and H Abbasi and C Gohlke and T E Oliphant},\n"
    "\tDoi = {10.1038/s41586-020-2649-2},\n"
    "\tJournal = {Nature},\n"
    "\tNumber = {7825},\n"
    "\tPages = {357--362},\n"
    "\tTitle = {Array programming with {NumPy}},\n"
    "\tVolume = {585},\n"
    "\tYear = {2020}}"
)


def test_an_arxiv_preprint_that_names_its_published_version_offers_the_article(client):
    proposal = propose(client, "arXiv:2006.10256")
    assert proposal.proposed_raw == NUMPY
    # The library's own entry (HarrEtal20) has the same key, journal, issue, pages, title,
    # volume and year; it has no DOI and writes two given names out in full.
    library = library_entry("HarrEtal20").split("\n")
    built = NUMPY.split("\n")
    assert library[0] == built[0] and library[2:] == built[3:] and library[1] != built[1]
    assert proposal.needs_decision and proposal.record_source == "crossref+pubmed"
    assert proposal.issues[0] == (
        "arXiv:2006.10256 is a preprint; its arXiv record names 10.1038/s41586-020-2649-2 as the published "
        "version, which is proposed here (house rule: cite the published version).")
    # The verifier does not accept it: Crossref lists related works for the article.
    assert proposal.status == "needs_review"
    assert proposal.issues[1:] == [
        "No unambiguous, fully supported metadata match",
        "crossref 10.1038/s41586-020-2649-2: Source has related versions/works; review publication identity"]
    assert [(c["doi"], c["type"], c["journal"], c["year"], c["source"]) for c in proposal.candidates] == [
        ("10.1038/s41586-020-2649-2", "journal-article", "Nature", "2020", "crossref"),
        ("10.48550/arxiv.2006.10256", "preprint", "arXiv", "2020", "arxiv")]
    assert proposal.candidates[1]["title"] == "Array Programming with NumPy"
    assert proposal.candidates[1]["authors"].startswith("Charles R. Harris; K. Jarrod Millman; ")
    assert client.requests == 0


def test_an_arxiv_only_preprint_is_built_in_the_house_form_and_verified(client):
    proposal = propose(client, "2208.02957")
    assert proposal.proposed_raw == library_entry("PianHill22") == (
        "@article{PianHill22,\n\tAuthor = {S T Piantadosi and F Hill},\n\tDoi = {10.48550/arxiv.2208.02957},\n"
        "\tJournal = {{arXiv}},\n\tTitle = {Meaning without reference in large language models},\n"
        "\tVolume = {2208.02957},\n\tYear = {2022}}")
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    assert [(c.field, c.kind, c.source) for c in proposal.changes] == [
        ("author", "filled", "arxiv+datacite"), ("doi", "filled", "datacite"), ("journal", "filled", "house rule"),
        ("title", "filled", "arxiv+datacite"), ("volume", "filled", "arxiv"), ("year", "filled", "arxiv+datacite")]
    assert proposal.key_proposed == "PianHill22" and proposal.record_source == "arxiv+datacite"
    assert proposal.doi == "10.48550/arxiv.2208.02957" and proposal.unfilled == [] and proposal.candidates == []
    found = complete.identify(complete.Query.parse("2208.02957"), client)
    assert found.source == "arxiv" and found.record["base"] == "2208.02957" and found.published_for is None
    assert client.requests == 0


def test_the_house_form_is_the_one_most_arxiv_entries_of_the_library_have():
    entries = load_entries(ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib")
    arxiv = [e["fields"] for e in entries.values() if e["fields"].get("journal") == "{arXiv}"]
    assert len(arxiv) == 44 and all(f["ENTRYTYPE"] == "article" for f in arxiv)
    import re

    def form(fields):
        return tuple(sorted((name, re.sub(r"\d", "N", fields[name])) for name in ("doi", "volume", "pages", "number")
                            if name in fields))

    from collections import Counter
    forms = Counter(form(f) for f in arxiv)
    produced = (("doi", "NN.NNNNN/arxiv.NNNN.NNNNN"), ("volume", "NNNN.NNNNN"))
    assert forms.most_common(2) == [
        (produced, 15),
        ((("doi", "NN.NNNNN/arxiv.NNNN.NNNNN"), ("volume", "doi.org/NN.NNNNN/arXiv.NNNN.NNNNN")), 10)]
    assert sum("volume" in f for f in arxiv) == 37 and sum("pages" in f for f in arxiv) == 4


def test_an_arxiv_title_printed_in_title_case_is_a_question(client):
    proposal = propose(client, "https://arxiv.org/abs/1901.10444")
    assert proposal.proposed_raw == library_entry("WietKiel19")
    assert proposal.issues == [CAPITALS] and proposal.needs_decision and proposal.status == "metadata_verified"
    title = next(c for c in proposal.changes if c.field == "title")
    assert (title.kind, title.source) == ("question", "arxiv+datacite")


def test_an_arxiv_version_that_is_named_is_cited_as_that_version(client):
    proposal = propose(client, "arXiv:2208.02957v1")
    # Version 1 prints the first author as Piantasodi; version 2 (the current one) as Piantadosi.
    assert proposal.proposed_raw == library_entry("PianHill22").replace(
        "{2208.02957}", "{2208.02957v1}").replace("Piantadosi", "Piantasodi")
    assert proposal.status == "metadata_verified" and not proposal.needs_decision
    assert {c.field: c.source for c in proposal.changes} == {
        "author": "arxiv", "doi": "datacite", "journal": "house rule", "title": "arxiv", "volume": "arxiv",
        "year": "arxiv"}


def test_a_withdrawn_arxiv_preprint_needs_a_decision(client):
    proposal = propose(client, "1805.02682")
    assert proposal.needs_decision and proposal.status == "needs_review"
    assert proposal.issues == [
        "arXiv:1805.02682 carries a withdrawal, retraction or correction notice; it is not added without a decision",
        CAPITALS, "arXiv unresolved: arXiv withdrawal or notice requires adjudication"]
    assert proposal.proposed_raw.startswith("@article{CannEtal18,\n\tAuthor = {J P Canning and E E Ingram and ")


def test_a_typed_arxiv_entry_keeps_what_it_has_and_gains_what_is_missing(client, tmp_path):
    typed = library_entry("CarlWagn18")  # the library writes this one with the id in Pages
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, typed)), client, client.cache)
    assert proposal.typed_raw == typed and proposal.key_typed == "CarlWagn18"
    assert proposal.proposed_raw == typed.replace("\tYear", "\tVolume = {1801.01944},\n\tYear")
    assert kinds(proposal) == {"author": "kept", "doi": "kept", "journal": "kept", "pages": "kept", "title": "kept",
                               "volume": "filled", "year": "kept"}
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    # A stub: the arXiv DOI in another spelling is the same identifier and stays as typed.
    stub = "@article{New,\n\tdoi = {10.48550/arXiv.2208.02957},\n\tfile = {paper.pdf}}"
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, stub)), client, client.cache)
    assert proposal.proposed_raw == library_entry("PianHill22").replace("{PianHill22,", "{New,").replace(
        "10.48550/arxiv.2208.02957", "10.48550/arXiv.2208.02957")
    assert kinds(proposal)["doi"] == "kept" and kinds(proposal)["file"] == "dropped"
    assert proposal.status == "metadata_verified"
    assert proposal.issues == ["format: the format checker would write the key as PianHill22"]


def test_arxiv_documents_that_cannot_be_read_are_refused_not_raised():
    from cdlbib.errors import CdlbibError, CompletionRefused
    raw = {k: v for k, v in ARXIV["PianHill22"]["raw"].items() if k != "datacite"}
    with pytest.raises(CompletionRefused) as refusal:
        complete.build_arxiv({}, raw)
    assert str(refusal.value) == "The arXiv and DataCite documents of arXiv:2208.02957 cannot be read ('datacite')"
    assert isinstance(refusal.value, CdlbibError)
    assert complete.build_arxiv({"ENTRYTYPE": "misc", "ID": "X"}, raw).unsupported == "misc"


def test_a_typed_doi_that_is_not_the_preprints_is_never_replaced():
    raw = ARXIV["PianHill22"]["raw"]
    proposal = complete.build_arxiv({"ENTRYTYPE": "article", "ID": "Zoll90", "doi": "10.1002/tea.3660271011"}, raw)
    assert proposal.proposed_raw == "@article{Zoll90,\n\tDoi = {10.1002/tea.3660271011}}" and proposal.needs_decision
    assert proposal.issues == ["doi: the arXiv record's DOI 10.48550/arxiv.2208.02957 is not the typed DOI "
                               "10.1002/tea.3660271011; nothing was filled from it"]


def test_an_arxiv_lookup_that_is_refused_is_reported(client):
    proposal = propose(client, "arXiv:2208.02958")  # not among the saved documents: the request is refused
    assert proposal.proposed_raw is None and proposal.status == "provider_error" and proposal.needs_decision
    assert proposal.issues[0].startswith("The lookup failed: a source did not answer (offline: request to "
                                         "export.arxiv.org refused)")


# --- what propose records -----------------------------------------------------------------------

def test_a_lookup_that_fails_is_a_proposal_and_the_next_query_still_runs(client, tmp_path):
    typed = "@article{Rame72,\n\tDoi = {10.1016/S0146-664X(72)80017-0}}"  # not among the saved responses
    queries = [complete.Query.from_entry(typed_entry(tmp_path, typed)), complete.Query.parse("10.1002/tea.3660271011")]
    failed, built = [complete.propose(query, client, client.cache) for query in queries]
    assert failed.status == "provider_error" and failed.proposed_raw is None and failed.needs_decision
    assert failed.issues == ["The lookup failed: a source did not answer (offline: request to api.crossref.org "
                             "refused); the entry is left as typed"]
    assert (failed.typed_raw, failed.key_typed, failed.doi) == (typed, "Rame72", "10.1016/S0146-664X(72)80017-0")
    assert built.proposed_raw == ZOLL90 and built.status == "metadata_verified"
    with pytest.raises(complete.ProviderError):  # identify itself raises the project's error
        complete.identify(queries[0], client)


def test_the_builders_questions_and_values_are_carried_through_unchanged(client):
    for doi in ("10.1002/tea.3660271011", "10.1037/h0041332", "10.1038/s41586-020-2649-2"):
        found = complete.identify(complete.Query.parse(doi), client)
        direct = complete.build({"doi": doi}, found.record, found.corroborating)
        proposal = propose(client, doi)
        assert proposal.changes == direct.changes and proposal.unfilled == direct.unfilled
        assert proposal.proposed_raw == direct.proposed_raw and proposal.key_proposed == direct.key_proposed
        assert proposal.issues[:len(direct.issues)] == direct.issues
        assert proposal.needs_decision >= direct.needs_decision
    # Nothing but the verifier sets the status, and it is never a human approval.
    assert propose(client, "10.1037/h0041332").status == "metadata_verified"


def test_an_entry_type_that_is_not_built_makes_no_lookup(client, tmp_path):
    typed = "@phdthesis{Mann11,\n\tAuthor = {J R Manning},\n\tTitle = {Acquisition, storage, and retrieval},\n\tYear = {2011}}"
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, typed)), client, client.cache)
    assert proposal.unsupported == "phdthesis" and proposal.proposed_raw is None and proposal.typed_raw == typed
    assert proposal.issues == ["An entry of type phdthesis is not built automatically; the entry is left as typed"]
    assert proposal.status is None and client.requests == 0


def test_a_record_that_is_a_correction_notice_is_refused_as_a_proposal(client):
    record = RECORDS["erratum"]["crossref"]["record"]
    doi = record["DOI"]
    client.cache.save_response(dumps(["https://api.crossref.org/works/" + quote(doi, safe=""), {}, False]),
                               {"url": "https://api.crossref.org/works/" + doi, "http_status": 200,
                                "retrieved_at": RECORDS["erratum"]["crossref"]["retrieved_at"],
                                "body": {"status": "ok", "message": record}})
    proposal = propose(client, doi)
    assert proposal.proposed_raw is None and proposal.needs_decision and proposal.status is None
    assert proposal.issues == ["The record 10.1038/s41592-020-0772-5 is a correction of 10.1038/s41592-019-0686-2, "
                               "not the article itself; cite the article"]


def test_checks_that_cannot_run_are_recorded_and_need_a_decision(client):
    # A record whose title is printed in capitals: the builder leaves the title out, and the
    # format checker raises on an entry without a title. The verifier's lookup of this DOI is
    # not among the saved responses, so the source does not answer either.
    record = RECORDS["all-capitals-title"]["crossref"]["record"]
    built = complete.build({"doi": record["DOI"]}, record)
    assert "Title" not in built.proposed_raw and not built.needs_decision
    proposal = complete.checked(built, client)
    assert proposal is built and proposal.needs_decision and proposal.status == "provider_error"
    assert proposal.issues == [
        "The format check could not run on the proposed entry (IndexError: string index out of range)",
        "The proposed entry could not be verified: a source did not answer (offline: request to api.crossref.org "
        "refused)"]


def test_a_typed_value_the_record_contradicts_is_a_shown_change_and_the_result_is_verified(client):
    proposal = complete.propose(complete.Query(doi="10.1002/tea.3660271011", key="Zoll90", raw="typed",
                                               fields={"ENTRYTYPE": "article", "ID": "Zoll90",
                                                       "doi": "10.1002/tea.3660271011", "volume": "28"}),
                                client, client.cache)
    assert "\tVolume = {27}," in proposal.proposed_raw  # the source's value is proposed, as a shown change
    assert next(c for c in proposal.changes if c.field == "volume") == complete.FieldChange(
        "volume", "28", "27", "crossref", "changed")
    assert proposal.status == "metadata_verified"


def test_nothing_is_printed(client, capsys):
    propose(client, "10.1002/tea.3660271011")
    propose(client, "2208.02957")
    propose(client, "Strength training and aerobic exercise: comparison and contrast", author="Knuttgen")
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


# --- live: real requests into a fresh cache, as the gate tests make -----------------------------

@pytest.fixture
def live(tmp_path):
    cache = Cache(tmp_path / "db.sqlite3")
    yield PoliteClient(cache, crossref_contact()), cache
    cache.close()


def test_live_a_doi_alone_gives_the_verified_entry_zoll90(live):
    client, cache = live
    proposal = complete.propose(complete.Query.parse("10.1002/tea.3660271011"), client, cache)
    assert proposal.proposed_raw == ZOLL90
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    assert 1 <= client.requests <= 3


def test_live_a_doi_alone_gives_the_verified_entry_rame72(live):
    client, cache = live
    proposal = complete.propose(complete.Query.parse("https://doi.org/10.1016/S0146-664X(72)80017-0"), client, cache)
    assert proposal.proposed_raw == RAME72 % "1" == library_entry("Rame72")
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision


def test_live_a_typed_stub_with_a_doi_is_completed(live, tmp_path):
    client, cache = live
    stub = "@article{Rame72,\n\tDoi = {10.1016/S0146-664X(72)80017-0}}"
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, stub)), client, cache)
    assert proposal.proposed_raw == RAME72 % "1" and proposal.typed_raw == stub
    assert proposal.status == "metadata_verified" and not proposal.needs_decision
