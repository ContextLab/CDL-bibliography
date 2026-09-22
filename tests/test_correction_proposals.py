"""A repair needs agreement on identity and replacement, not just a page hit."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from correction_proposals import pagination_proposal, replace_pagination


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
