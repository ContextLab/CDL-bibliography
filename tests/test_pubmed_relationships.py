"""Distinguish PubMed commentary from correction and publication-version links."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from auto_review import blocking_pubmed_relationships, select_result
from test_auto_review import sample, secondary
from test_fulltext_review import assessment


def link(kind):
    return {"type": kind, "source": "MED", "id": "1234567", "reference": "Linked citation"}


@pytest.mark.parametrize("kind", ["Comment in", "Comment on"])
def test_identified_commentary_does_not_block_matching_metadata(sample, kind):
    raw = sample[2]
    raw["commentCorrectionList"] = {"commentCorrection": [link(kind)]}
    before = deepcopy(raw)
    assert not blocking_pubmed_relationships(raw)
    result = secondary(*sample)
    assert not result["issues"]
    assert select_result(sample[0], [result], [])["status"] == "metadata_verified"
    assert not assessment(sample)["issues"]
    assert raw == before and result["raw_record"]["commentCorrectionList"] == before["commentCorrectionList"]


@pytest.mark.parametrize("kind", ["Erratum in", "Erratum for", "Retraction in", "Retraction of",
    "Expression of concern in", "Corrected and republished in", "Preprint in", "Republished from",
    "Update in", "Unrecognized relation", "CommentIn", "Comment in (correction)"])
def test_other_relationships_remain_blocking(sample, kind):
    sample[2]["commentCorrectionList"] = {"commentCorrection": [link("Comment in"), link(kind)]}
    assert blocking_pubmed_relationships(sample[2])
    assert secondary(*sample)["issues"]
    assert assessment(sample)["issues"]


@pytest.mark.parametrize("broken", ["missing_id", "non_numeric_id", "unknown_source", "not_list", "not_object"])
def test_malformed_comment_link_is_not_benign(sample, broken):
    row = link("Comment in")
    if broken == "missing_id": row.pop("id")
    elif broken == "non_numeric_id": row["id"] = "bad"
    elif broken == "unknown_source": row["source"] = "PPR"
    sample[2]["commentCorrectionList"] = {"commentCorrection":
        row if broken == "not_list" else ["bad"] if broken == "not_object" else [row]}
    assert blocking_pubmed_relationships(sample[2])
    assert secondary(*sample)["issues"]


def test_retraction_flag_cannot_be_hidden_by_commentary(sample):
    sample[2]["commentCorrectionList"] = {"commentCorrection": [link("Comment in")]}
    sample[2]["isRetracted"] = "Y"
    assert secondary(*sample)["issues"]
    assert assessment(sample)["issues"]


def test_commentary_does_not_resolve_a_real_field_conflict(sample):
    sample[2]["commentCorrectionList"] = {"commentCorrection": [link("Comment in")]}
    sample[0]["title"] = "A different work"
    assert secondary(*sample)["issues"]
    assert assessment(sample)["issues"]
