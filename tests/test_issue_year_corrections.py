"""A final issue year requires independent print-date and issue evidence."""

from copy import deepcopy

import pytest

import test_auto_review
from cdlbib.auto_review import assess_epmc, reassess
from cdlbib.correction_proposals import issue_year_proposal
from test_auto_review import candidate

sample = test_auto_review.sample


def case(sample):
    fields, record, raw = sample
    fields["year"] = "2019"
    primary = candidate(fields, record)
    secondary = assess_epmc(fields, primary, raw, "2026-09-17", "https://example.test")
    entry = {"key": "A", "fields": fields, "fingerprint": "test"}
    previous = {"status": "needs_review", "candidates": [primary, secondary]}
    return entry, previous


def test_issue_year_requires_no_other_change_and_preserves_source_dates(sample):
    entry, previous = case(sample)
    frozen = deepcopy((entry, previous))
    p = issue_year_proposal(entry, previous)
    assert p["changes"] == {"year": {"before": "2019", "after": "2020"}}
    assert reassess(dict(entry, fields=dict(entry["fields"], year="2020")), previous)["status"] == "metadata_verified"
    assert (entry, previous) == frozen


@pytest.mark.parametrize("change", ["missing-print-date", "ambiguous-print-date", "other-issue-year", "page", "author", "doi", "issn", "correction", "external-hold", "second-pubmed", "unsupported-publisher"])
def test_other_conflicts_cannot_be_solved_by_changing_the_year(sample, change):
    entry, previous = case(sample)
    primary, secondary = previous["candidates"]
    raw = secondary["raw_record"]
    if change == "missing-print-date":
        primary["record"].pop("published-print")
    elif change == "ambiguous-print-date":
        primary["record"]["published-print"]["date-parts"].append([2021])
    elif change == "other-issue-year":
        raw["journalInfo"]["yearOfPublication"] = 2021
    elif change == "page":
        raw["pageInfo"] = "123-130"
    elif change == "author":
        raw["authorList"]["author"][0]["firstName"] = "Bob Q"
    elif change == "doi":
        raw["doi"] = "10.1234/other"
    elif change == "issn":
        raw["journalInfo"]["journal"]["issn"] = "9999-9999"
    elif change == "correction":
        raw["isRetracted"] = "Y"
    elif change == "external-hold":
        previous["external_evidence"] = [{"reason": "Unresolved version"}]
    elif change == "second-pubmed":
        other = deepcopy(secondary)
        other["raw_record"]["id"] = "999999"
        previous["candidates"].append(other)
    else:
        entry["fields"]["publisher"] = "Unknown publisher"
    assert issue_year_proposal(entry, previous) is None
