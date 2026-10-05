"""Candidate search (``intake.find_candidates``): title, author(s), or both.

Every answer is a real saved response replayed through the real client (intake_support):
tests/fixtures/intake/searches.json.gz holds the Crossref, PubMed and arXiv responses to
the five searches of tests/fixtures/intake/record.py, fetched once on 2026-10-05.
"""
import pytest

from cdlbib import api, complete, intake
from cdlbib.errors import CdlbibError

from conftest import ZOLL90
from intake_support import library, offline_client

MURDOCK_DOI = "10.1037/h0044314"
NUMPY_DOI = "10.1038/s41586-020-2649-2"
SHAPE = {"authors", "year", "journal", "doi", "title", "type", "source", "sources", "in_library"}


@pytest.fixture
def client(tmp_path):
    client = offline_client(tmp_path / "cache", "searches.json.gz")
    yield client
    client.cache.close()


def find(ws, client, **asked):
    return intake.find_candidates(ws, client=client, per_source=5, **asked)


def test_title_only_merges_crossref_and_pubmed_by_doi(tmp_path, client):
    found = find(library(tmp_path / "lib"), client, title="Backward learning in paired associates")
    assert client.requests == 0 and found.errors == []
    first = found[0]
    assert SHAPE <= set(first)
    assert (first["doi"], first["pmid"], first["year"]) == (MURDOCK_DOI, "13306866", "1956")
    assert first["sources"] == ["crossref", "pubmed"] and first["source"] == "crossref"
    assert first["title"] == '"Backward" learning in paired associates.'
    assert first["authors"] == "Bennet B. Murdock" and first["in_library"] is None
    assert len({lead["doi"] for lead in found}) == len(found)  # one lead per work
    # the leads of each source are there, each named
    assert {"crossref", "pubmed"} <= {s for lead in found for s in lead["sources"]}
    # a lead is not an entry: it is looked up by its identifier through the existing path
    assert intake.query_for(first) == complete.Query(doi=MURDOCK_DOI)
    assert api.candidate_query(first) == complete.Query(doi=MURDOCK_DOI)


def test_authors_only_several_authors(tmp_path, client):
    found = find(library(tmp_path / "lib"), client, authors=["Manning", "Kahana"])
    assert client.requests == 0 and found.errors == [] and len(found) >= 5
    for lead in found:
        assert "Manning" in lead["authors"] and "Kahana" in lead["authors"]
    by_doi = {lead["doi"]: lead for lead in found}
    assert by_doi["10.1080/09658211.2012.683010"]["sources"] == ["crossref", "pubmed"]
    assert by_doi["10.1073/pnas.1015174108"]["sources"] == ["pubmed"]
    # one author given as a string, and full names, ask the same sources the same thing
    assert find(library(tmp_path / "lib2"), client, authors=["J. R. Manning", "Kahana, Michael J."]) != []


def test_title_and_author_finds_the_arxiv_record(tmp_path, client):
    found = find(library(tmp_path / "lib"), client, title="Attention is all you need", authors=["Vaswani"])
    assert client.requests == 0 and found.errors == []
    preprint = next(lead for lead in found if lead["source"] == "arxiv")
    assert (preprint["arxiv"], preprint["year"], preprint["type"]) == ("1706.03762", "2017", "preprint")
    assert preprint["title"] == "Attention Is All You Need" and preprint["authors"].startswith("Ashish Vaswani; ")
    assert preprint["doi"] == "10.48550/arxiv.1706.03762" and preprint["journal"] == "arXiv"
    assert intake.query_for(preprint) == complete.Query(arxiv="1706.03762")
    assert all("Vaswani" in lead["authors"] for lead in found)


def test_arxiv_record_is_merged_into_its_published_doi(tmp_path, client):
    found = find(library(tmp_path / "lib"), client, title="Array programming with NumPy",
                 authors=["Harris", "van der Walt"], year="2020")
    assert client.requests == 0 and found.errors == []
    assert [lead["doi"] for lead in found] == [NUMPY_DOI]
    lead = found[0]
    assert lead["sources"] == ["pubmed", "arxiv"] and lead["source"] == "pubmed"
    assert (lead["pmid"], lead["arxiv"], lead["year"]) == ("32939066", "2006.10256", "2020")
    assert intake.query_for(lead) == complete.Query(doi=NUMPY_DOI)  # the published record, not the preprint


def test_in_library_by_identifier_and_by_title_and_authors(tmp_path, client):
    by_doi = ("@article{Murd56,\n\tAuthor = {B B Murdock},\n\tDoi = {" + MURDOCK_DOI + "},\n"
              "\tTitle = {Some title typed differently},\n\tYear = {1956}}")
    by_pmid = "@article{HarrEtal20,\n\tAuthor = {C R Harris},\n\tPmid = {32939066},\n\tTitle = {NumPy},\n\tYear = {2020}}"
    by_title = ("@article{MannKaha12,\n\tAuthor = {J R Manning and M J Kahana},\n"
                "\tTitle = {Interpreting semantic clustering effects in free recall},\n\tYear = {2012}}")
    ws = library(tmp_path / "lib", ZOLL90, by_doi, by_pmid, by_title)
    assert find(ws, client, title="Backward learning in paired associates")[0]["in_library"] == "Murd56"
    assert find(ws, client, title="Array programming with NumPy", authors=["Harris", "van der Walt"],
                year="2020")[0]["in_library"] == "HarrEtal20"
    marked = {lead["doi"]: lead["in_library"] for lead in find(ws, client, authors=["Manning", "Kahana"])}
    assert marked["10.1080/09658211.2012.683010"] == "MannKaha12"
    assert marked["10.1073/pnas.1015174108"] is None  # other authors follow: not the same byline
    assert client.requests == 0
    assert ws.bib.read_text(encoding="utf-8").count("@article") == 4  # nothing was written


def test_no_record_and_bounded_count(tmp_path, client):
    ws = library(tmp_path / "lib")
    nothing = find(ws, client, title="Zzyzxqv qwxzvk plorbnix")
    assert nothing == [] and nothing.errors == []
    assert len(intake.find_candidates(ws, client=client, per_source=5, limit=2, authors=["Manning", "Kahana"])) == 2
    assert client.requests == 0


def test_sources_can_be_restricted_and_the_asked_year_comes_first(tmp_path, client):
    found = intake.find_candidates(library(tmp_path / "lib"), client=client, per_source=5,
                                   authors=["Manning", "Kahana"])
    crossref = intake.find_candidates(library(tmp_path / "lib2"), client=client, per_source=5,
                                      authors=["Manning", "Kahana"], sources=("crossref",))
    assert {lead["source"] for lead in crossref} == {"crossref"} and 0 < len(crossref) < len(found)
    assert client.requests == 0
    # the ranking rule, on the leads just found: a lead of the asked year sorts before the others
    keys = {lead["year"]: intake._relevance(lead, None, ["manning"], "2014") for lead in found}
    assert keys["2014"] < keys["2012"] and keys["2014"] < keys["2009"]
    assert intake._relevance(found[0], None, ["someone else"], None) is None
    assert intake._relevance(found[0], "An unrelated title about warblers", [], None) is None


def test_a_source_that_does_not_answer_is_named_and_the_others_are_kept(tmp_path, client):
    # Only Crossref's answer to this search is in the cache with rows=5 and no year; asking
    # with a year changes the Crossref and PubMed requests, which the offline client refuses.
    found = find(library(tmp_path / "lib"), client, title="Attention is all you need", authors=["Vaswani"], year="2017")
    assert [source for source, _ in found.errors] == ["crossref", "pubmed"]
    assert all("offline" in reason for _, reason in found.errors)
    assert [lead["arxiv"] for lead in found] == ["1706.03762"]  # arXiv's request has no year in it


def test_nothing_to_search_for(tmp_path, client):
    ws = library(tmp_path / "lib")
    for asked in ({}, {"title": "  "}, {"authors": ["", " "]}, {"year": "2020"}):
        with pytest.raises(CdlbibError, match="Nothing to search for"):
            intake.find_candidates(ws, client=client, **asked)
    with pytest.raises(CdlbibError, match="Nothing to search for"):
        api.find_candidates(ws)  # refused before any client is made
    with pytest.raises(CdlbibError, match="no DOI, PMID or arXiv id"):
        intake.query_for({"title": "x", "doi": None})


def test_arxiv_request_terms():
    assert intake.arxiv_search_params("Attention is all you need", ["Vaswani"], 5) == {
        "search_query": "ti:attention AND ti:all AND ti:you AND ti:need AND au:vaswani",
        "start": 0, "max_results": 5, "sortBy": "relevance"}
    assert intake.arxiv_search_params(None, ["van der Walt", "Glöckner, Andreas"])["search_query"] == (
        'au:"van der walt" AND au:glockner')


def test_typed_text_cannot_change_a_sources_query(tmp_path, client):
    """Query syntax typed into a name or a title reaches PubMed and arXiv as plain words."""
    import re
    hostile = ['Vaswani"[au] OR all[sb]) OR ("x', "Kahana]) AND (hasabstract", "van der Walt\x00\n", "O'Brien:ti",
               'x" OR au:"y', "a\\b)(c", "\u202eevil"]
    for name in hostile:
        assert re.fullmatch(r"[a-z0-9]+(?: [a-z0-9]+)*", intake._surname(name)), name
    assert intake._surname("van der Walt\x00\n") == "van der walt"
    params = intake.arxiv_search_params('need" OR all:electron OR ti:"attention', hostile)
    for term in params["search_query"].split(" AND "):  # each term: one field tag, then words (quoted if several)
        assert re.fullmatch(r'ti:[a-z0-9]+|au:[a-z0-9]+|au:"[a-z0-9]+(?: [a-z0-9]+)+"', term), term
    assert " OR " not in params["search_query"] and "all:" not in params["search_query"]
    # the same real saved answers: quotes, brackets and a field tag around the words change nothing
    found = find(library(tmp_path / "lib"), client, title='"Attention" is (all) you [need]', authors=['"Vaswani"'])
    # Crossref takes free text as a request parameter (no syntax): that one request differs from
    # the saved one and is refused by the offline transport; PubMed's and arXiv's are the saved ones
    assert client.requests == 1 and [source for source, _ in found.errors] == ["crossref"]
    assert [lead["arxiv"] for lead in found if lead.get("arxiv")] == ["1706.03762"]
    ws = library(tmp_path / "lib2")
    for year in ("2020 OR 1=1", "20201", "2020[dp] OR all[sb]", "next year"):
        with pytest.raises(CdlbibError, match="Not a year"):
            intake.find_candidates(ws, client=client, title="Attention is all you need", year=year)
    with pytest.raises(CdlbibError, match="Unknown source 'elsewhere'"):
        intake.find_candidates(ws, client=client, title="Attention is all you need", sources=("elsewhere",))


def test_what_is_asked_of_a_source_is_bounded(tmp_path, client):
    ws = library(tmp_path / "lib")
    # per_source and limit are clamped before any request: 10**9 records are never asked for
    found = intake.find_candidates(ws, client=client, authors=["Manning", "Kahana"], per_source=10**9, limit=10**9)
    assert found == [] and len(found.errors) == 3  # the requests (rows=50) are not in the cache: refused offline
    assert all("offline" in reason for _, reason in found.errors)
    long_title = "attention " * 5000
    assert len(intake._plain(long_title, intake.MAX_QUERY_CHARS)) <= intake.MAX_QUERY_CHARS
    assert len(intake.arxiv_search_params(long_title, ["a" * 5000])["search_query"]) < 200
    with pytest.raises(CdlbibError, match="whole number"):
        intake.find_candidates(ws, client=client, title="Attention is all you need", per_source="many")
