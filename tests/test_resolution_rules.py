"""Reject near misses at the new publisher, issue and final-article boundaries."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from verification import compare_record, normalize_publisher, normalized
from auto_review import assess_epmc

ROOT = Path(__file__).resolve().parents[1]


def pilot(key):
    rows = json.loads((ROOT / "verification/pilot50/manifest.json").read_text())[
        "entries"
    ]
    row = next(r for r in rows if r["key"] == key)
    return deepcopy(row["entry"]), deepcopy(row["cached_candidate"])


@pytest.mark.parametrize("key", ["MannEtal22", "GuesMart21", "LifaEtal21"])
def test_final_article_requires_its_own_explicit_doi(key):
    fields, candidate = pilot(key)
    record = candidate["record"]
    assert compare_record(fields, record)[1]
    fields["doi"] = record["DOI"]
    assert not compare_record(fields, record)[1]
    for field in ("doi", "title", "author", "year", "journal", "volume", "pages"):
        changed = dict(fields)
        changed.pop(field)
        assert compare_record(changed, record)[1], field
        changed[field] = "wrong"
        assert compare_record(changed, record)[1], field


@pytest.mark.parametrize(
    "relation",
    [
        {"has-preprint": []},
        {"has-preprint": [{"id": "10.1234/x"}]},
        {"has-preprint": [{"id-type": "doi", "id": "not a doi"}]},
        {"has-preprint": [{"id-type": "doi", "id": 42}]},
        {"is-preprint-of": [{"id-type": "doi", "id": "10.1234/x"}]},
        {"has-preprint": [{"id-type": "doi", "id": "10.1234/x"}], "is-version-of": []},
    ],
)
def test_malformed_or_other_version_relationship_still_blocks(relation):
    fields, candidate = pilot("MannEtal22")
    record = candidate["record"]
    fields["doi"] = record["DOI"]
    record["relation"] = relation
    assert compare_record(fields, record)[1]


@pytest.mark.parametrize(
    "change", ["self-link", "erratum", "preprint", "year", "issue"]
)
def test_final_article_link_cannot_hide_other_conflicts(change):
    fields, candidate = pilot("MannEtal22")
    record = candidate["record"]
    fields["doi"] = record["DOI"]
    if change == "self-link":
        record["relation"]["has-preprint"][0]["id"] = record["DOI"]
    elif change == "erratum":
        record["updated-by"] = [{"DOI": "10.1234/correction"}]
    elif change == "preprint":
        record["type"] = "posted-content"
    elif change == "year":
        record["published-print"] = {"date-parts": [[1990]]}
    elif change == "issue":
        fields["number"] = "999"
    assert compare_record(fields, record)[1]


@pytest.mark.parametrize(
    "short,long",
    [
        ("Elsevier", "Elsevier BV"),
        ("Elsevier", "Elsevier B.V."),
        ("{MIT} Press", "MIT Press - Journals"),
        ("Frontiers", "Frontiers Media SA"),
        ("Karger", "S. Karger AG"),
        (
            "Journal of Neurosurgery Publishing Group",
            "Journal of Neurosurgery Publishing Group (JNSPG)",
        ),
    ],
)
def test_exact_corporate_publisher_names(short, long):
    assert normalize_publisher(short) == normalize_publisher(long)
    assert normalized(short) != normalized(long)


@pytest.mark.parametrize(
    "left,right",
    [
        ("Academic Press", "Elsevier BV"),
        ("Nature Publishing Group", "Springer Science and Business Media LLC"),
        ("Plenum Press", "Springer US"),
        ("Little, Brown, and Co", "Wiley"),
        ("Elsevier Academic Press", "Elsevier"),
        ("MIT Press - Books", "MIT Press"),
        ("Frontiers", "Frontiers Software SLU"),
        ("Karger", "Karger Libri"),
    ],
)
def test_imprints_and_other_names_are_not_equivalent(left, right):
    assert normalize_publisher(left) != normalize_publisher(right)


def test_publisher_rule_does_not_change_titles_or_book_imprints():
    fields, candidate = pilot("DaviEtal09")
    record = candidate["record"]
    assert not compare_record(fields, record)[1]
    fields["title"], record["title"] = "Elsevier", ["Elsevier BV"]
    assert not compare_record(fields, record)[0]["title"]["match"]
    fields["ENTRYTYPE"], record["type"] = "book", "book"
    assert not compare_record(fields, record)[0]["publisher"]["match"]


def test_issue_part_requires_independent_matching_coordinates():
    fields, primary = pilot("WorrEtal04")
    # Synthetic MEDLINE source supplies the complete name/coordinates of the
    # frozen publisher record. Live documentary test is recorded in the audit.
    record = primary["record"]
    raw = {
        "id": "15155522",
        "source": "MED",
        "doi": record["DOI"],
        "title": fields["title"],
        "authorList": {
            "author": [
                {"firstName": p["given"], "lastName": p["family"]}
                for p in record["author"]
            ]
        },
        "journalInfo": {
            "yearOfPublication": 2004,
            "volume": "127",
            "issue": "Pt 7",
            "journal": {"title": "Brain", "issn": record["ISSN"][0]},
        },
        "pubTypeList": {"pubType": ["Journal Article"]},
        "pageInfo": "1496-1506",
    }
    assert not assess_epmc(fields, primary, raw, "2026-09-15", "https://example.test")[
        "issues"
    ]
    for field, value in [("volume", "999"), ("issue", "Suppl 7"), ("issue", "Pt 8")]:
        wrong = deepcopy(raw)
        wrong["journalInfo"][field] = value
        assert assess_epmc(
            fields, primary, wrong, "2026-09-15", "https://example.test"
        )["issues"]
    wrong = deepcopy(raw)
    wrong["journalInfo"]["journal"]["issn"] = "0000-0000"
    assert assess_epmc(fields, primary, wrong, "2026-09-15", "https://example.test")[
        "issues"
    ]


@pytest.mark.parametrize('name,acronym', [
    ('American Psychological Association', 'APA'),
    ('American Association for the Advancement of Science', 'AAAS'),
    ('Oxford University Press', 'OUP'), ('Public Library of Science', 'PLoS'),
    ('Association for Computing Machinery', 'ACM'),
    ('Institute of Electrical and Electronics Engineers', 'IEEE'),
    ('Cambridge University Press', 'CUP'), ('American Physical Society', 'APS'),
])
def test_documented_parenthetical_publisher_acronyms(name, acronym):
    assert normalize_publisher(name) == normalize_publisher(name + ' (' + acronym + ')')
    assert normalized(name) != normalized(name + ' (' + acronym + ')')


@pytest.mark.parametrize('left,right', [
    ('American Psychological Association', 'American Psychiatric Association'),
    ('American Psychological Association', 'APA'),
    ('American Physical Society', 'American Physiological Society'),
    ('Association for Computing Machinery', 'Association for Computing Machinery (ACME)'),
    ('Oxford University Press', 'Oxford University Press (USA)'),
    ('Cambridge University Press', 'Cambridge University Press & Assessment'),
    ('IEEE', 'Institution of Electrical Engineers'),
])
def test_publisher_acronyms_do_not_merge_other_entities_or_branches(left, right):
    assert normalize_publisher(left) != normalize_publisher(right)


def test_ieee_expansion_is_confined_to_article_publisher_comparison():
    assert normalize_publisher('{IEEE}') == normalize_publisher('Institute of Electrical and Electronics Engineers (IEEE)')
    fields = {'ENTRYTYPE':'book', 'title':'Example', 'author':'A Smith', 'year':'2020', 'publisher':'Oxford University Press'}
    record = {'type':'book', 'title':['Example'], 'author':[{'given':'Alice','family':'Smith'}],
              'published':{'date-parts':[[2020]]}, 'publisher':'Oxford University Press (OUP)'}
    assert 'publisher: missing evidence or mismatch' in compare_record(fields,record)[1]
