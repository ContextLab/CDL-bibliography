"""Formatting equivalences cannot hide differences in content or identity."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

from cdlbib.verification import compare_record, normalize_pages, normalize_title, normalized
from cdlbib.auto_review import compatible_authors, select_result


def test_monospace_text_is_preserved_including_nested_markup():
    assert normalized(r"\texttt{Davos}: A package") == "davos: a package"
    assert normalized(r"\texttt{A \textbf{B}}") == "a b"
    assert normalized(r"\texttt{Alpha}") != normalized(r"\texttt{Beta}")
    assert normalized(r"\texttt{Davos}: A package") != normalized(": A package")


@pytest.mark.parametrize("left,right", [
    ("Memory.", "Memory"), ("Why?", "Why?."), ("A test: Results.", "a test: results"),
])
def test_one_terminal_sentence_period(left, right):
    assert normalize_title(left) == normalize_title(right)
    assert normalized(left) != normalized(right)


@pytest.mark.parametrize("left,right", [
    ("Memory..", "Memory"), ("Memory...", "Memory"), ("Why?", "Why"),
    ("A test: results", "A test results"), ("A. B", "A B"),
    ("Memory!", "Memory"), ("Phase-reversal", "Phase reversal"),
    ("A finding", "Another finding"), ("A finding: Erratum", "A finding"),
])
def test_meaningful_punctuation_and_words_survive(left, right):
    assert normalize_title(left) != normalize_title(right)


@pytest.mark.parametrize("left,right,same", [
    ("334--334", "334", True), ("001--001", "001", True),
    ("334--335", "334", False), ("001--001", "1", False),
    ("e334--e334", "e334", False), ("334--34", "334", False),
])
def test_only_identical_numeric_page_endpoints_collapse(left, right, same):
    assert (normalize_pages(left) == normalize_pages(right)) == same


@pytest.mark.parametrize("first,second,expected", [
    ("A.B.", "Alice B", True), ("Alice B.C.", "Alice B C", True),
    ("A.B.", "Alice C", False), ("Alice B", "Ann B", False),
    ("AB", "Alice B", False), ("B.A.", "Alice B", False),
])
def test_secondary_name_compatibility_uses_explicit_dotted_initials(first, second, expected):
    a = {"author": [{"family": "Smith", "given": first}]}
    b = {"author": [{"family": "Smith", "given": second}]}
    assert compatible_authors(a, b) is expected


def test_terminal_period_does_not_hide_other_fields_or_competing_dois():
    fields = {"ENTRYTYPE": "article", "title": "Memory", "author": "A Smith",
              "year": "2020", "journal": "Journal", "volume": "1", "pages": "1--9"}
    record = {"DOI": "10.1234/one", "type": "journal-article", "title": ["Memory."],
              "author": [{"family": "Smith", "given": "Alice"}], "published": {"date-parts": [[2020]]},
              "container-title": ["Journal"], "volume": "1", "page": "1-9"}
    evidence, issues = compare_record(fields, record)
    assert not issues
    for field in ("author", "year", "journal", "volume", "pages"):
        assert compare_record(dict(fields, **{field: "wrong"}), record)[1]
    one = {"source": "crossref", "doi": record["DOI"], "record": record, "evidence": evidence, "issues": issues}
    two = deepcopy(one)
    two["doi"] = two["record"]["DOI"] = "10.1234/two"
    two["record"]["title"] = ["Memory"]
    assert select_result(fields, [one, two], [])["status"] == "needs_review"


@pytest.mark.parametrize("hyphen", ["‐", "‑"])
def test_unicode_hyphens_preserve_word_boundaries_and_name_parts(hyphen):
    from cdlbib.verification import author_evidence
    assert normalize_title("Self" + hyphen + "reference") == normalize_title("Self-reference")
    assert normalize_title("Self" + hyphen + "reference") != normalize_title("Self reference")
    assert normalize_title("Self" + hyphen + "reference") != normalize_title("Selfreference")
    assert author_evidence("Anne-Marie Smith", [{"given": "Anne" + hyphen + "Marie", "family": "Smith"}])[0]
    assert not author_evidence("Anne-Marie Smith", [{"given": "Anne" + hyphen + "Martha", "family": "Smith"}])[0]


@pytest.mark.parametrize("name", ["Journal of Physiology", "Lancet Neurology", "New England Journal of Medicine", "Annals of Mathematical Statistics", "Computer Journal"])
def test_documented_journal_article_variants_are_confined_to_venues(name):
    from cdlbib.verification import normalize_journal
    assert normalize_journal(name) == normalize_journal("The " + name)
    assert normalize_title(name) != normalize_title("The " + name)


@pytest.mark.parametrize("left,right", [
    ("Journal of Physiology", "Journal of Physiology and Biochemistry"),
    ("Lancet Neurology", "The Lancet"),
    ("Annals of Mathematical Statistics", "Annals of Statistics"),
    ("The Quarterly Journal of Experimental Psychology Section A", "The Quarterly Journal of Experimental Psychology Section B"),
    ("Journal of Experimental Psychology", "Journal of Experimental Psychology: General"),
    ("A Journal", "The A Journal"),
])
def test_venue_variants_preserve_distinct_and_historical_journals(left, right):
    from cdlbib.verification import normalize_journal
    assert normalize_journal(left) != normalize_journal(right)


@pytest.mark.parametrize('name', ['Journal of the Acoustical Society of America', 'Journal of General Psychology',
    'Journal of Psychology', 'American Journal of Human Genetics', 'Journal of Comparative Neurology',
    'International Journal of Robotics Research', 'European Physical Journal B', 'Journal of Experimental Biology',
    'British Journal for the Philosophy of Science', 'Journal of Abnormal and Social Psychology'])
def test_further_catalogued_article_variants(name):
    from cdlbib.verification import normalize_journal
    assert normalize_journal(name) == normalize_journal('The ' + name)
    assert normalize_title(name) != normalize_title('The ' + name)


@pytest.mark.parametrize('left,right', [
    ('Journal of Psychology', 'Canadian Journal of Psychology'),
    ('Journal of the Acoustic Society of America', 'The Journal of the Acoustical Society of America'),
    ('European Physical Journal B', 'The European Physical Journal A'),
    ('Journal of Experimental Biology', 'The British Journal of Experimental Biology'),
    ('Journal of Abnormal and Social Psychology', 'Journal of Abnormal Psychology'),
])
def test_journal_article_variants_preserve_names_and_historical_titles(left, right):
    from cdlbib.verification import normalize_journal
    assert normalize_journal(left) != normalize_journal(right)
