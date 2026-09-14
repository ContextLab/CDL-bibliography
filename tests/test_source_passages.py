from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from source_passages import materialize, numbered_passages
from research import validate_findings
from publisher_metadata import PublisherMetadata


def finding(field, value, ids):
    return {
        "fields": [{"field": field, "value": value, "passage_ids": ids}],
        "uncertainties": [],
    }


def test_authors_are_copied_not_stitched_with_ellipsis():
    pages = [{"page": 1, "text": "Alice Møller*\nInstitute\nŁukasz Kaiser†\n"}]
    result = materialize(
        finding("author", "Alice Møller and Łukasz Kaiser", ["p1l1", "p1l3"]), pages
    )
    evidence = result["fields"]["author"]
    assert [p["quote"] for p in evidence["passages"]] == [
        "Alice Møller*\n",
        "Łukasz Kaiser†\n",
    ]
    assert evidence["grounding"] == "literal_text_present"
    assert validate_findings(result, pages)
    evidence["passages"][1]["quote"] = "Lukasz Kaiser"
    with pytest.raises(ValueError, match="offsets"):
        validate_findings(result, pages)


def test_individual_author_items_preserve_complete_source_order():
    pages = [{"page": 1, "text": "Alice Møller*\nInstitute\nŁukasz Kaiser†\n"}]
    authors = [
        finding("author", "Alice Møller", ["p1l1"])["fields"][0],
        finding("author", "Łukasz Kaiser", ["p1l3"])["fields"][0],
    ]
    result = materialize({"fields": authors, "uncertainties": []}, pages)
    assert result["fields"]["author"]["value"] == "Alice Møller and Łukasz Kaiser"
    for fields in [list(reversed(authors)), [authors[0], authors[0]]]:
        with pytest.raises(ValueError):
            materialize({"fields": fields, "uncertainties": []}, pages)


def test_inferred_series_is_not_grounded_by_conference_name():
    pages = [
        {
            "page": 1,
            "text": "31st Conference on Neural Information Processing Systems (2017)",
        }
    ]
    result = materialize(
        finding(
            "booktitle", "Advances in Neural Information Processing Systems", ["p1l1"]
        ),
        pages,
    )
    assert result["unsupported_fields"] == ["booktitle"]


def test_wrapped_title_and_literal_subtitle_are_preserved():
    pages = [{"page": 1, "text": "A result:\nits meaning\nOther text\n"}]
    assert (
        materialize(finding("title", "A result: its meaning", ["p1l1", "p1l2"]), pages)[
            "unsupported_fields"
        ]
        == []
    )
    assert materialize(
        finding("title", "A result: Other text", ["p1l1", "p1l3"]), pages
    )["unsupported_fields"] == ["title"]


def test_scalar_substrings_and_accent_erasure_do_not_pass():
    pages = [{"page": 1, "text": "12017\nMøller\n"}]
    assert materialize(finding("year", "2017", ["p1l1"]), pages)[
        "unsupported_fields"
    ] == ["year"]
    assert materialize(finding("author", "Moller", ["p1l2"]), pages)[
        "unsupported_fields"
    ] == ["author"]


def test_author_footnote_digit_is_not_a_missing_letter():
    pages = [{"page": 1, "text": "Lukas\nGroßberger3, 4\n"}]
    result = materialize(finding("author", "Lukas Großberger", ["p1l1", "p1l2"]), pages)
    assert result["unsupported_fields"] == []
    result = materialize(
        finding("author", "Lukas Grossberger", ["p1l1", "p1l2"]), pages
    )
    assert result["unsupported_fields"] == ["author"]


def test_source_digest_changes_and_unknown_selection_is_rejected():
    pages = [{"page": 1, "text": "Title"}]
    first = materialize(finding("title", "Title", ["p1l1"]), pages)
    pages[0]["text"] = "Changed"
    second = materialize(finding("title", "Title", ["p1l1"]), pages)
    assert first["source_text_sha256"] != second["source_text_sha256"]
    assert second["unsupported_fields"] == ["title"]
    for ids in [["p1l9"], ["p1l1", "p1l1"], [True]]:
        with pytest.raises(ValueError):
            materialize(finding("title", "Title", ids), pages)
    with pytest.raises(ValueError):
        numbered_passages(pages + pages)


def test_publisher_head_excludes_reference_metadata_and_preserves_conflicts():
    parser = PublisherMetadata()
    parser.feed(
        '<head><meta name="citation_title" content="Main article">'
        '<meta name="citation_doi" content="10.1/a">'
        '<meta name="citation_doi" content="10.1/b">'
        '<meta name="citation_pdf_url" content="/main.pdf"></head>'
        '<body><meta name="citation_title" content="Cited paper"></body>'
    )
    assert parser.source_metadata()["citation_title"] == ["Main article"]
    assert parser.source_metadata()["citation_doi"] == ["10.1/a", "10.1/b"]
    assert parser.urls == ["/main.pdf"]


# Source-role cases. Literal grounding proves a value was copied from the
# selected offsets; it cannot prove the value plays the role being claimed.
# Each case below is a wrong answer that `literal_grounding` reports as fully
# supported, so `role_risk` is the only signal that separates them.

FRONT_MATTER = [
    {
        "page": 1,
        "text": "A Study of Things\nJane Roe1\n"
        "1 Dartmouth College, Hanover NH\n"
        "Received: 3 January 2016 / Accepted: 9 May 2018\n"
        "Published: 2 June 2018\n"
        "\u00a9 Springer 2019\n",
    },
    {
        "page": 9,
        "text": "References\n[1] B. Other. Attention Is All You Need. NeurIPS, 2017.\n",
    },
]


@pytest.mark.parametrize(
    "field,value,ids,risk",
    [
        ("year", "2016", ["p1l4"], "receipt_or_revision_date"),
        ("year", "2019", ["p1l6"], "copyright_line"),
        ("title", "Attention Is All You Need", ["p9l2"], "reference_list"),
        ("publisher", "Dartmouth College", ["p1l3"], "affiliation_line"),
    ],
)
def test_wrong_source_role_is_literally_supported_but_flagged(field, value, ids, risk):
    result = materialize(finding(field, value, ids), FRONT_MATTER)
    assert result["unsupported_fields"] == []
    assert result["fields"][field]["grounding"] == "literal_text_present"
    assert risk in result["fields"][field]["role_risk"]
    assert field in result["role_risk_fields"]
    assert any(field in u and risk in u for u in result["uncertainties"])


def test_publication_date_line_is_not_a_role_risk():
    """ "Published:" states the publication date; only receipt/revision dates do not."""
    result = materialize(finding("year", "2018", ["p1l5"]), FRONT_MATTER)
    assert result["fields"]["year"]["role_risk"] == []
    assert result["role_risk_fields"] == {}


def test_preprint_stamp_and_proceedings_year_are_distinguished():
    pages = [
        {
            "page": 1,
            "text": "Attention Is All You Need\narXiv:1706.03762v5 [cs.CL] 6 Dec 2017\n",
        },
        {
            "page": 2,
            "text": "31st Conference on Neural Information Processing Systems, 2017\n",
        },
    ]
    stamped = materialize(finding("year", "2017", ["p1l2"]), pages)
    assert stamped["fields"]["year"]["role_risk"] == ["preprint_version_stamp"]
    printed = materialize(finding("year", "2017", ["p2l1"]), pages)
    assert printed["fields"]["year"]["role_risk"] == []


def test_truncated_author_list_is_flagged_but_complete_one_is_not():
    pages = [{"page": 1, "text": "Some Paper\nAlice Smith, Bob Jones, Carol White\n"}]
    short = materialize(finding("author", "Alice Smith and Bob Jones", ["p1l2"]), pages)
    assert short["unsupported_fields"] == []
    assert short["fields"]["author"]["role_risk"] == ["possible_omitted_author"]
    full = materialize(
        finding("author", "Alice Smith and Bob Jones and Carol White", ["p1l2"]), pages
    )
    assert full["fields"]["author"]["role_risk"] == []


def test_university_press_is_a_publisher_but_a_bare_institution_is_not():
    pages = [{"page": 1, "text": "Oxford University Press\nHarvard University\n"}]
    assert (
        materialize(finding("publisher", "Oxford University Press", ["p1l1"]), pages)[
            "fields"
        ]["publisher"]["role_risk"]
        == []
    )
    assert (
        "institution_named_as_venue"
        in materialize(finding("publisher", "Harvard University", ["p1l2"]), pages)[
            "fields"
        ]["publisher"]["role_risk"]
    )


def test_self_citation_footer_without_a_heading_is_not_a_reference_list():
    """JOSS front pages carry a "how to cite" line with reference shape."""
    pages = [
        {
            "page": 1,
            "text": "UMAP\nMcInnes et al., (2018). UMAP. "
            "Journal of Open Source Software, 3(29), 861.\n",
        }
    ]
    result = materialize(
        finding("journal", "Journal of Open Source Software", ["p1l2"]), pages
    )
    assert result["fields"]["journal"]["role_risk"] == []
