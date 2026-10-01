"""A repair needs agreement on identity and replacement, not just a page hit."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from cdlbib.correction_proposals import pagination_proposal, replace_pagination


def case(key="MoheEtal14"):
    data = json.loads((Path(__file__).parent / "fixtures/pagination_corrections.json").read_text())[key]
    return data["entry"], data["previous"]


@pytest.mark.parametrize("key,expected", [("MoheEtal14", "315--324"), ("RoigEtal12", "e44594")])
def test_documented_page_and_article_number_repair(key, expected):
    entry, previous = case(key)
    frozen = deepcopy((entry, previous))
    proposal = pagination_proposal(entry, previous)
    assert proposal["changes"]["pages"]["after"] == expected
    assert proposal["fingerprint"] == entry["fingerprint"]
    assert (entry, previous) == frozen


@pytest.mark.parametrize("field,value", [("title", "Another work"), ("author", "Other, A."),
    ("year", "1990"), ("journal", "Another journal"), ("volume", "999"),
    ("doi", "10.1234/other"), ("number", "999"), ("publisher", "Another publisher")])
def test_other_local_disagreements_cannot_be_repaired(field, value):
    entry, previous = case()
    entry["fields"][field] = value
    assert pagination_proposal(entry, previous) is None


@pytest.mark.parametrize("change", ["missing", "page", "doi", "issn", "title", "author", "year", "issue",
    "type", "correction", "retracted", "id", "ambiguous"])
def test_secondary_disagreement_or_missing_identity_blocks(change):
    entry, previous = case()
    secondary = next(c for c in previous["candidates"] if c["source"] == "europepmc")
    raw = secondary["raw_record"]
    if change == "missing":
        previous["candidates"] = [c for c in previous["candidates"] if c["source"] != "europepmc"]
    elif change == "page": raw["pageInfo"] = "999-1000"
    elif change == "doi": raw["doi"] = "10.1234/other"
    elif change == "issn": raw["journalInfo"]["journal"] = {"title": entry["fields"]["journal"], "issn": "0000-0000"}
    elif change == "title": raw["title"] = "Another work"
    elif change == "author": raw["authorList"]["author"][0]["lastName"] = "Other"
    elif change == "year": raw["journalInfo"]["yearOfPublication"] = 1990
    elif change == "issue": raw["journalInfo"]["issue"] = "999"
    elif change == "type": raw["pubTypeList"] = {"pubType": ["Preprint"]}
    elif change == "correction": raw["commentCorrectionList"] = {"commentCorrection": [{"id": "123"}]}
    elif change == "retracted": raw["isRetracted"] = "Y"
    elif change == "id": raw["id"] = None
    elif change == "ambiguous":
        rival = deepcopy(secondary)
        rival["raw_record"]["id"] = "99999"
        previous["candidates"].append(rival)
    assert pagination_proposal(entry, previous) is None


def test_external_hold_and_competing_work_block():
    entry, previous = case()
    previous["external_evidence"] = [{"conflict": "author suffix"}]
    assert pagination_proposal(entry, previous) is None
    del previous["external_evidence"]
    entry["fields"].pop("doi", None)
    rival = deepcopy(next(c for c in previous["candidates"] if c["source"] == "crossref"))
    rival["doi"] = rival["record"]["DOI"] = "10.1234/rival"
    previous["candidates"].append(rival)
    assert pagination_proposal(entry, previous) is None


@pytest.mark.parametrize("change", ["fingerprint", "before", "duplicate", "injection", "fields", "raw"])
def test_raw_edits_reject_stale_or_ambiguous_proposals(change):
    entry, previous = case()
    proposal = pagination_proposal(entry, previous)
    text = entry["raw"]
    proposals = [proposal]
    if change == "fingerprint": proposal["fingerprint"] = "stale"
    elif change == "before": proposal["changes"]["pages"]["before"] = "999"
    elif change == "duplicate": proposals.append(deepcopy(proposal))
    elif change == "injection": proposal["changes"]["pages"]["after"] = "123},Title={other"
    elif change == "fields": proposal["changes"]["title"] = {"after": "Other"}
    elif change == "raw": text += text
    with pytest.raises(ValueError):
        replace_pagination(text, {entry["key"]: entry}, proposals)


# Spot-check decisions 2026-09-24/25 (verification/apply-2026-09-25/README.md).
# Real cached cases: tests/fixtures/apply-2026-09-25-cases.json.gz ---------------

import gzip  # noqa: E402

from cdlbib import correction_proposals as cp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STAGE1 = json.loads(gzip.open(ROOT / "tests/fixtures/apply-2026-09-25-cases.json.gz").read())


def stage1(key):
    data = deepcopy(STAGE1["cases"][key])
    return data["entry"], data["previous"]


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A small real library: the cdl.bib bylines of the named keys, as a .bib file."""
    monkeypatch.chdir(ROOT)

    def make(*keys, extra=()):
        rows = [(k, STAGE1["library_authors"][k]["author"]) for k in keys] + list(extra)
        path = tmp_path / f"library{len(list(tmp_path.iterdir()))}.bib"
        path.write_text("\n\n".join(f"@article{{{k},\n\tAuthor = {{{a}}},\n\tTitle = {{T}},\n\tYear = {{2000}}}}"
                                    for k, a in rows) + "\n")
        monkeypatch.setattr(cp, "LIBRARY_BIB", path)
        return path
    return make


@pytest.mark.parametrize("before,after,shortens", [
    ("483--490", "483", True), ("305--329", "305", True), ("434--443", "434--442", False),
    ("483--90", "483", True), ("e101--e110", "e101", True),
    ("483--490", "483--490", False), ("483", "483--490", False), ("1063", "1063--1087", False),
    ("483--490", "484--490", False), ("483--490", "483--495", False), ("", "483", False),
    ("483--483", "483", False), ("1--14", "6", False),
])
def test_shortens_pages(before, after, shortens):
    assert cp.shortens_pages(before, after) is shortens


@pytest.mark.parametrize("key,pages", [("MarmEtal78", "483--490"), ("SimoEtal04", "305--329")])
def test_first_page_only_source_never_shortens_a_real_cited_range(key, pages, monkeypatch):
    monkeypatch.chdir(ROOT)
    entry, previous = stage1(key)
    assert entry["fields"]["pages"] == pages
    explain = {}
    assert cp.single_source_proposal(entry, previous, explain) is None
    assert explain["reason"] == "value-held" and "shorten" in explain["detail"]
    assert cp.pagination_proposal(entry, previous) is None


def test_real_range_completion_is_still_proposed(monkeypatch):
    # Negative control: a source that completes a cited first page is not a shortening.
    monkeypatch.chdir(ROOT)
    entry, previous = stage1("AndeEtal94")
    proposal = cp.single_source_proposal(entry, previous)
    assert proposal["changes"]["pages"] == {"before": "1063", "after": "1063--1087"}


# User rule 2026-09-30 (verification/2026-09-29-user-review/CONFIRM.md, answer 5): "one
# source is sufficient; manual entry is the weakest part. notify user if mismatch is found
# and ask how they want to resolve it". A surname change is never proposed automatically:
# not from one source, not when a second source agrees, not when other cdl.bib entries use
# the proposed or the cited spelling. It is held, naming both spellings and the source.
# (These tests used to assert Claude's 2026-09-24 corroboration / library-consensus rule.)

def test_meyer88_kounios_is_held_for_the_user(library):
    # Regression: risky001 applied Crossref's typo "Kounois"; five other cdl.bib
    # entries spell J Kounios and none spells Kounois.
    library("AngeEtal07", "JensEtal02", "Koun93", "Koun94", "SmitKoun96")
    entry, previous = stage1("MeyeEtal88")
    assert entry["fields"]["author"].endswith("J Kounios")
    # Today the DOI-linked PubMed record 3375400 (fetched by revert-kounios)
    # spells Kounios, so the sources disagree and nothing is proposed.
    explain = {}
    assert cp.single_source_proposal(entry, previous, explain) is None
    assert explain["detail"] == "author: sources disagree"
    # When risky001 was generated there was no PubMed record (pubmed_id null):
    # Crossref alone. The mismatch is held for the user, with both spellings named.
    previous["candidates"] = [c for c in previous["candidates"] if c["source"] != "europepmc"]
    explain = {}
    assert cp.single_source_proposal(entry, previous, explain) is None
    assert explain["reason"] == "value-held"
    assert "surname mismatch (crossref)" in explain["detail"]
    assert "'J Kounios'" in explain["detail"] and "'J Kounois'" in explain["detail"]
    assert "library consensus" not in explain["detail"]
    hold = cp.surname_change_hold("MeyeEtal88", entry["fields"]["author"],
                                  entry["fields"]["author"].replace("Kounios", "Kounois"), source="crossref")
    assert hold.startswith("author: surname mismatch (crossref): cited 'J Kounios', source 'J Kounois'")


def test_single_source_surname_change_is_held_for_the_user(library):
    library(extra=[("Other00", "A N Other")])
    entry, previous = stage1("MeyeEtal88")
    previous["candidates"] = [c for c in previous["candidates"] if c["source"] != "europepmc"]
    explain = {}
    assert cp.single_source_proposal(entry, previous, explain) is None
    assert "surname mismatch" in explain["detail"] and "Kounois" in explain["detail"]
    entry, previous = stage1("MartJohn15")
    explain = {}
    assert cp.single_source_proposal(entry, previous, explain) is None
    assert "cited 'S Johnson', source 'S Johnston'" in explain["detail"]


def test_library_use_of_the_proposed_spelling_does_not_release_a_surname_change(library):
    entry, previous = stage1("CleeMcCl91")
    uses = [k for k, v in STAGE1["library_authors"].items() if "J L McClelland" in v["author"]][:3]
    assert uses  # the library does spell him McClelland elsewhere
    for make in (lambda: library(*uses), lambda: library(extra=[("Other00", "A N Other")])):
        make()
        explain = {}
        assert cp.single_source_proposal(entry, previous, explain) is None
        assert "cited 'J L McCleeland', source 'J L McClelland'" in explain["detail"]


def test_second_source_does_not_release_a_surname_change(library):
    library(extra=[("Other00", "A N Other")])
    entry, previous = stage1("DoesEtal08")  # Kitaj -> Kitajo: Crossref and PubMed 17556771
    explain = {}
    assert cp.single_source_proposal(entry, previous, explain) is None
    assert "cited 'K Kitaj', source 'K Kitajo'" in explain["detail"]
    library(extra=[("Other00", "K Kitaj and A N Other")])
    explain = {}
    assert cp.single_source_proposal(entry, previous, explain) is None
    assert "surname mismatch" in explain["detail"] and "library consensus" not in explain["detail"]


def test_surname_change_hold_controls():
    # agree -> no hold: a given-name change, an accent restored, a reordering
    assert cp.surname_change_hold("X", "J L McClelland and A B Smith", "James L McClelland and A B Smith") is None
    assert cp.surname_change_hold("X", "G Gron", 'G Gr{\\"o}n') is None
    assert cp.surname_change_hold("X", "G H Baltuch and M J Kahana", "M J Kahana and G H Baltuch") is None
    # disagree -> held, both spellings and the source named, one clause per position
    hold = cp.surname_change_hold("X", "A Smith and B Jones", "A Smyth and B Jonas", source="PubMed 123")
    assert hold == ("author: surname mismatch (PubMed 123): cited 'A Smith', source 'A Smyth'; "
                    "cited 'B Jones', source 'B Jonas'; " + cp.USER_SURNAME_RULE)
    # a respelling hidden in a reordering is still held
    assert "cited 'B Jones', source 'A Smyth'" in cp.surname_change_hold("X", "A Smith and B Jones", "B Jones and A Smyth")
