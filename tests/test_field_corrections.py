"""Single-field fixes must retain the same fully corroborated citation identity."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from auto_review import reassess
from correction_proposals import field_proposal, replace_field, source_title
from verification import load_entries


def case(field):
    data = json.loads((Path(__file__).parent / "fixtures/pagination_corrections.json").read_text())["MoheEtal14"]
    entry, previous = data["entry"], data["previous"]
    entry["fields"]["pages"] = "315--324"
    entry["fields"][field] = "Wrong title" if field == "title" else "9999"
    previous = reassess(entry, previous)
    return entry, previous


@pytest.mark.parametrize("field", ["title", "volume", "number", "year", "author", "journal"])
def test_two_source_single_field_fix(field):
    entry, previous = case(field)
    frozen = deepcopy((entry, previous))
    proposal = field_proposal(entry, previous, field)
    assert proposal is not None
    proposed = dict(entry, fields=dict(entry["fields"], **{field: proposal["changes"][field]["after"]}))
    assert reassess(proposed, previous)["status"] == "metadata_verified"
    assert (entry, previous) == frozen


@pytest.mark.parametrize("field", ["title", "volume", "number", "year", "author", "journal"])
@pytest.mark.parametrize("conflict", ["author", "page", "doi", "hold"])
def test_no_other_field_can_disagree(field, conflict):
    entry, previous = case(field)
    raw = next(c["raw_record"] for c in previous["candidates"] if c["source"] == "europepmc")
    if conflict == "author": raw["authorList"]["author"][0]["lastName"] = "Someone else"
    elif conflict == "page": raw["pageInfo"] = "12-15"
    elif conflict == "doi": raw["doi"] = "10.1234/wrong"
    elif conflict == "hold": previous["external_evidence"] = [{"reason": "unresolved conflict"}]
    assert field_proposal(entry, previous, field) is None


def test_nested_raw_title_edit_preserves_all_other_fields(tmp_path):
    bib = tmp_path / "entry.bib"
    original = '@article{Key,\n  Title = {A {DNA} finding, part 1},\n  Year = {2000},\n  Author = {A Smith}}'
    bib.write_text(original)
    entry = load_entries(bib)["Key"]
    proposal = {"key": "Key", "fingerprint": entry["fingerprint"],
                "changes": {"title": {"before": entry["fields"]["title"], "after": "A {DNA} finding, part 2"}}}
    changed = replace_field(original, entry, proposal)
    assert changed == original.replace("part 1", "part 2")
    bib.write_text(changed)
    assert load_entries(bib)["Key"]["fields"] == dict(entry["fields"], title="A {DNA} finding, part 2")
    for unsafe in ("x},year={999", "{unclosed", "line\nbreak"):
        proposal["changes"]["title"]["after"] = unsafe
        with pytest.raises(ValueError):
            replace_field(original, entry, proposal)


def test_source_title_does_not_discard_semantics_or_protected_case():
    assert "{COVID-19}" in source_title("Experience due to COVID-19", "Experience during {COVID-19}")
    assert "{fMRI}" in source_title("Effects in fMRI—subcortical activity", "Effects in {fMRI}--subcortical activity")
    assert "{EEGLAB}" in source_title("EEGLAB: a toolbox", "{EEGLAB}: an old toolbox")
    for source, local in [("Time inmind", "Time in mind"), ("A title*", "A title"),
                          ("Noise 1/F2", r"Noise $1/F^2$"),
                          ("10. TEACHER-STUDENT INTERACTION", "Teacher-student interaction"),
                          ("ALL CAPITAL HEADING", "All capital heading")]:
        with pytest.raises(ValueError):
            source_title(source, local)


def doi_case():
    data = json.loads((Path(__file__).parent / "fixtures/pagination_corrections.json").read_text())["MoheEtal14"]
    entry, previous = data["entry"], data["previous"]
    entry["fields"]["pages"] = "315--324"
    primary = next(c for c in previous["candidates"] if c["source"] == "crossref")
    rival = deepcopy(primary)
    rival["doi"] = rival["record"]["DOI"] = "10.1234/duplicate"
    previous["candidates"].append(rival)
    previous = reassess(entry, previous)
    assert previous["status"] == "needs_review"
    return entry, previous


def test_doi_addition_requires_a_unique_corroborated_identity():
    entry, previous = doi_case()
    p = field_proposal(entry, previous, "doi")
    assert p["changes"]["doi"] == {"before": None, "after": "10.1177/0956797613511257"}
    assert reassess(dict(entry, fields=dict(entry["fields"], doi=p["doi"])), previous)["status"] == "metadata_verified"


@pytest.mark.parametrize("conflict", ["missing_pubmed", "two_pubmed", "wrong_title", "supplied_doi", "correction", "hold"])
def test_doi_cannot_select_from_ambiguous_or_conflicting_evidence(conflict):
    entry, previous = doi_case()
    secondary = next(c for c in previous["candidates"] if c["source"] == "europepmc")
    if conflict == "missing_pubmed":
        previous["candidates"].remove(secondary)
    elif conflict == "two_pubmed":
        other = deepcopy(secondary)
        other["doi"] = other["raw_record"]["doi"] = "10.1234/duplicate"
        other["raw_record"]["id"] = "99999"
        previous["candidates"].append(other)
    elif conflict == "wrong_title": secondary["raw_record"]["title"] = "Another work"
    elif conflict == "supplied_doi": entry["fields"]["doi"] = "10.1234/duplicate"
    elif conflict == "correction": secondary["raw_record"]["isRetracted"] = "Y"
    elif conflict == "hold": previous["external_evidence"] = [{"issue": "source conflict"}]
    assert field_proposal(entry, previous, "doi") is None


def test_author_repair_requires_the_complete_ordered_second_byline():
    for change in ("missing", "reverse", "given", "suffix"):
        entry, previous = case("author")
        authors = next(c["raw_record"]["authorList"]["author"] for c in previous["candidates"] if c["source"] == "europepmc")
        if change == "missing": authors.pop()
        elif change == "reverse": authors.reverse()
        elif change == "given": authors[0]["firstName"] = "Different"
        else: authors[0]["suffix"] = "Jr"
        assert field_proposal(entry, previous, "author") is None


def test_shared_duplicate_author_is_not_corroboration():
    entry, previous = case("author")
    for candidate in previous["candidates"]:
        if candidate["source"] == "crossref":
            authors = candidate["record"]["author"]
        elif candidate["source"] == "europepmc":
            authors = candidate["raw_record"]["authorList"]["author"]
        else:
            continue
        authors.append(deepcopy(authors[-1]))
    assert field_proposal(entry, reassess(entry, previous), "author") is None


def test_journal_correction_needs_independent_title_not_only_same_issn():
    entry, previous = case("journal")
    journal = next(c["raw_record"]["journalInfo"]["journal"] for c in previous["candidates"] if c["source"] == "europepmc")
    for key in ("title", "medlineAbbreviation", "isoabbreviation"):
        journal[key] = "A different historical journal title"
    assert field_proposal(entry, previous, "journal") is None
