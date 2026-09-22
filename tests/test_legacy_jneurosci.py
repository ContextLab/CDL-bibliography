"""Only documented legacy journal headers can supplement an 'other' type."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from pmc_metadata import article_front
from fulltext_review import assess_fulltext


def fixture(key="OMarEtal94"):
    return json.loads((Path(__file__).parent / "fixtures/pmc_jneurosci.json").read_text())[key]


def assess(data):
    med = data["medline"]
    xml = article_front(data["raw_oai"], med["pmcid"], data["primary"]["doi"], med["id"])
    return assess_fulltext(data["fields"], data["primary"], med, {
        "body": xml, "url": "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/", "retrieved_at": "2026-09-17"})


@pytest.mark.parametrize("key", ["OMarEtal94", "KnieEtal95"])
def test_legacy_journal_type_is_corroborated_by_index_and_article_heading(key):
    result = assess(fixture(key))
    assert not result["issues"]
    assert "article-categories" in result["raw_xml"]


@pytest.mark.parametrize("change", ["registry-type", "registry-issn", "xml-issn", "heading", "medline-type", "preprint", "manuscript", "page", "unmarked-initials", "conflicting-initials"])
def test_missing_or_conflicting_type_and_fields_still_block(change):
    data = fixture()
    if change == "registry-type":
        data["primary"]["record"]["type"] = "posted-content"
    elif change == "registry-issn":
        data["primary"]["record"]["ISSN"] = ["1234-5678"]
    elif change == "xml-issn":
        data["raw_oai"] = data["raw_oai"].replace("0270-6474", "1234-5678")
    elif change == "heading":
        data["raw_oai"] = data["raw_oai"].replace(">Articles<", ">Corrections<")
    elif change == "medline-type":
        data["medline"]["pubTypeList"] = {"pubType": ["Letter"]}
    elif change == "preprint":
        data["medline"]["pubTypeList"]["pubType"].append("Preprint")
    elif change == "manuscript":
        data["raw_oai"] = data["raw_oai"].replace('pub-id-type="other"', 'pub-id-type="manuscript-id"')
    elif change == "unmarked-initials":
        data["raw_oai"] = data["raw_oai"].replace(' initials="SM"', '')
    elif change == "conflicting-initials":
        data["raw_oai"] = data["raw_oai"].replace(' initials="SM"', ' initials="SQ"')
    else:
        data["fields"]["pages"] = "6511--6524"
    assert assess(data)["issues"]


def test_real_legacy_article_with_correction_remains_held():
    result = assess(fixture("WangBuzs96"))
    assert any("related-article annotation" in i for i in result["issues"])
