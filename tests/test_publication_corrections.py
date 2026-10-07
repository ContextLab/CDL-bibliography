"""Publication repairs retain title/byline identity and every source conflict."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import re
import pytest
from cdlbib.auto_review import reassess
from cdlbib.correction_proposals import publication_proposal, replace_publication
from cdlbib.verification import load_entries


def case(tmp_path):
    data = json.loads((Path(__file__).parent / "fixtures/pagination_corrections.json").read_text())["MoheEtal14"]
    bib = tmp_path / "test.bib"
    raw = re.sub(r"(?i)(year\s*=\s*\{)[^{}]+", lambda m: m[1] + "2013", data["entry"]["raw"])
    bib.write_text(raw)
    entry = next(iter(load_entries(bib).values()))
    return bib, entry, reassess(entry, data["previous"])


def test_year_and_page_repairs_require_both_complete_sources(tmp_path):
    bib, entry, previous = case(tmp_path)
    before = deepcopy((entry, previous))
    p = publication_proposal(entry, previous)
    assert set(p["changes"]) == {"year", "pages"}
    bib.write_text(replace_publication(bib.read_text(), entry, p))
    after = next(iter(load_entries(bib).values()))
    assert after["fields"] == dict(entry["fields"], year="2014", pages="315--324")
    assert after["fingerprint"] != entry["fingerprint"]
    assert reassess(after, previous)["status"] == "metadata_verified"
    assert (entry, previous) == before


@pytest.mark.parametrize("conflict", ["title", "author", "year", "pages", "journal", "notice", "identity_title", "identity_author"])
def test_conflicting_publication_or_identity_blocks_multi_field_repair(tmp_path, conflict):
    _, entry, previous = case(tmp_path)
    raw = next(c["raw_record"] for c in previous["candidates"] if c["source"] == "europepmc")
    if conflict == "title": raw["title"] = "Different paper"
    elif conflict == "author": raw["authorList"]["author"][0]["lastName"] = "Other"
    elif conflict == "year": raw["journalInfo"]["yearOfPublication"] = 2000
    elif conflict == "pages": raw["pageInfo"] = "99-100"
    elif conflict == "journal": raw["journalInfo"]["journal"] = {"title": "Different journal", "issn": "0000-0000"}
    elif conflict == "notice": raw["isRetracted"] = "Y"
    else:
        entry["fields"][conflict.removeprefix("identity_")] = "Changed identity"
        previous = reassess(entry, previous)
    assert publication_proposal(entry, previous) is None


def test_combined_title_and_pages_require_original_byline_and_other_identity(tmp_path):
    bib, entry, previous = case(tmp_path)
    entry["fields"].update(year="2014", title="Mistyped title")
    previous = reassess(entry, previous)
    proposal = publication_proposal(entry, previous, include_identity_fields=True)
    assert proposal and set(proposal["changes"]) == {"title", "pages"}
    assert publication_proposal(entry, previous) is None
    for field in ["author", "journal", "year"]:
        entry["fields"][field] = "Wrong"
    assert publication_proposal(entry, reassess(entry, previous), include_identity_fields=True) is None


def test_combined_never_replaces_both_title_and_byline_identity(tmp_path):
    _, entry, previous = case(tmp_path)
    entry["fields"].update(year="2014", title="Mistyped title", author="Other Person")
    assert publication_proposal(entry, reassess(entry, previous), include_identity_fields=True) is None


def test_combined_cannot_ignore_a_conflicting_secondary_title(tmp_path):
    _, entry, previous = case(tmp_path)
    entry["fields"].update(year="2014", title="Mistyped title")
    raw = next(c["raw_record"] for c in previous["candidates"] if c["source"] == "europepmc")
    raw["title"] = "A different work"
    previous = reassess(entry, previous)
    assert publication_proposal(entry, previous, include_identity_fields=True) is None
