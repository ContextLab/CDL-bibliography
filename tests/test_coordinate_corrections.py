"""Multiple coordinate repairs must retain independently established identity."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from cdlbib.auto_review import reassess
from cdlbib.correction_proposals import coordinate_proposal, replace_coordinates
from cdlbib.verification import load_entries


def case(tmp_path, volume="999"):
    data = json.loads((Path(__file__).parent / "fixtures/pagination_corrections.json").read_text())["MoheEtal14"]
    bib = tmp_path / "test.bib"
    raw = data["entry"]["raw"]
    import re
    raw = re.sub(r"(?i)(volume\s*=\s*\{)[^{}]+", lambda m: m[1] + volume, raw)
    bib.write_text(raw)
    entry = next(iter(load_entries(bib).values()))
    return bib, entry, reassess(entry, data["previous"])


def test_two_coordinates_checked_against_both_sources_and_raw_edit(tmp_path):
    bib, entry, previous = case(tmp_path)
    frozen = deepcopy((entry, previous))
    proposal = coordinate_proposal(entry, previous)
    assert set(proposal["changes"]) == {"volume", "pages"}
    changed = replace_coordinates(bib.read_text(), entry, proposal)
    bib.write_text(changed)
    after = next(iter(load_entries(bib).values()))
    assert after["fields"] == dict(entry["fields"], volume="25", pages="315--324")
    assert after["fingerprint"] != entry["fingerprint"]
    assert reassess(after, previous)["status"] == "metadata_verified"
    assert (entry, previous) == frozen


@pytest.mark.parametrize("conflict", ["title", "author", "year", "journal", "pages", "volume", "doi", "notice"])
def test_multi_coordinate_fix_cannot_mask_a_secondary_conflict(tmp_path, conflict):
    _, entry, previous = case(tmp_path)
    raw = next(c["raw_record"] for c in previous["candidates"] if c["source"] == "europepmc")
    if conflict == "title": raw["title"] = "Other study"
    elif conflict == "author": raw["authorList"]["author"][0]["lastName"] = "Other"
    elif conflict == "year": raw["journalInfo"]["yearOfPublication"] = 1999
    elif conflict == "journal": raw["journalInfo"]["journal"] = {"title": "Other journal", "issn": "0000-0000"}
    elif conflict == "pages": raw["pageInfo"] = "10-20"
    elif conflict == "volume": raw["journalInfo"]["volume"] = "99"
    elif conflict == "doi": raw["doi"] = "10.1234/other"
    else: raw["isRetracted"] = "Y"
    assert coordinate_proposal(entry, previous) is None


@pytest.mark.parametrize("volume,allowed", [("25(2)", True), ("25(3)", False), ("25(S2)", False)])
def test_embedded_issue_must_agree_before_volume_is_split(tmp_path, volume, allowed):
    _, entry, previous = case(tmp_path, volume)
    assert (coordinate_proposal(entry, previous) is not None) == allowed
