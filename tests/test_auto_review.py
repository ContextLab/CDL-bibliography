"""Acceptance boundary tests for deterministic automatic review."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

from cdlbib.auto_review import (
    assess_epmc,
    expanded_pages,
    fetch_epmc,
    reassess,
    run_auto_review,
    select_result,
)
from cdlbib.verification import (
    Cache,
    ProviderError,
    assess_candidates,
    compare_record,
    load_entries,
    normalized,
    normalize_journal,
)
from test_verification import response


@pytest.fixture
def sample():
    fields = {
        "ID": "A",
        "ENTRYTYPE": "article",
        "title": "A result: its meaning",
        "author": "A B Smith",
        "year": "2020",
        "journal": "Memory and Cognition",
        "volume": "2",
        "number": "3",
        "pages": "123--129",
    }
    record = {
        "DOI": "10.1234/a",
        "title": [fields["title"]],
        "type": "journal-article",
        "author": [{"family": "Smith", "given": "Alice B"}],
        "published": {"date-parts": [[2019]]},
        "published-print": {"date-parts": [[2020]]},
        "container-title": ["Memory & Cognition"],
        "ISSN": ["1234-5678"],
        "volume": "2",
        "issue": "3",
        "page": "123-129",
    }
    raw = {
        "id": "123456",
        "source": "MED",
        "doi": "10.1234/a",
        "title": fields["title"] + ".",
        "authorList": {"author": [{"firstName": "Alice B", "lastName": "Smith"}]},
        "journalInfo": {
            "yearOfPublication": 2020,
            "volume": "2",
            "issue": "3",
            "journal": {"title": "Memory & Cognition", "issn": "1234-5678"},
        },
        "pubTypeList": {"pubType": ["Journal Article"]},
        "pageInfo": "123-9",
    }
    return fields, record, raw


def candidate(fields, record):
    return assess_candidates(fields, response(record))[0]


def secondary(fields, record, raw):
    return assess_epmc(
        fields, candidate(fields, record), raw, "2026-09-09", "https://example.test"
    )


@pytest.mark.parametrize("notice", ["Erratum in", "Retraction in", "Corrected and republished in", "Expression of concern in"])
def test_registry_match_cannot_hide_secondary_correction_notice(sample, notice):
    fields, record, raw = sample
    record["published"] = record["published-print"]
    primary = candidate(fields, record)
    assert not primary["issues"]
    raw["commentCorrectionList"] = {"commentCorrection": [{"type": notice, "reference": "Notice"}]}
    source = secondary(fields, record, raw)
    for local in (fields, dict(fields, doi=record["DOI"])):
        result = select_result(local, [primary, source], [])
        assert result["status"] == "needs_review"
        assert any("notice" in issue for issue in result["issues"])


def test_correction_notice_does_not_block_another_doi(sample):
    fields, record, raw = sample
    record["published"] = record["published-print"]
    primary = candidate(fields, record)
    source = secondary(fields, record, raw)
    source["doi"] = source["raw_record"]["doi"] = "10.1234/unrelated"
    source["raw_record"]["isRetracted"] = "Y"
    assert select_result(dict(fields, doi=record["DOI"]), [primary, source], [])["status"] == "metadata_verified"


def test_literal_punctuation_never_disappears():
    for punctuation in ("&", "%", "#"):
        assert punctuation in normalized("A " + punctuation + " B")
        assert normalized("A " + punctuation + " B") != normalized("A B")
    assert normalized("A &amp; B") == normalized(r"A \& B")


def test_audited_journal_variants_are_exact_and_confined_to_venues():
    short = "Proceedings of the National Academy of Sciences, {USA}"
    full = "Proceedings of the National Academy of Sciences of the United States of America"
    assert normalize_journal(short) == normalize_journal(full)
    assert normalized(short) != normalized(full)
    assert normalize_journal(
        "Proceedings of the National Academy of Sciences, India"
    ) != normalize_journal(full)
    assert normalize_journal("The Journal of Neuroscience") == normalize_journal(
        "Journal of Neuroscience"
    )
    assert normalize_journal("Journal of Mathematical Psychology") != normalize_journal(
        "Journal of Mathematical Psychobiology"
    )


def test_formatting_force_does_not_override_source_disagreement(sample):
    fields, record, _ = sample
    fields = dict(fields, force="True", year="1900")
    evidence, issues = compare_record(fields, record)
    assert not evidence["year"]["match"]
    assert any(issue.startswith("year:") for issue in issues)


def test_optional_issue_is_advisory_but_wrong_issue_blocks(sample):
    fields, record, _ = sample
    record.pop("published")
    fields.pop("number")
    c = candidate(fields, record)
    assert not c["issues"] and c["advisories"]
    assert candidate(dict(fields, number="99"), record)["issues"]
    assert candidate(dict(fields, pages=""), record)["issues"]


def test_ampersand_equivalence_is_venue_only(sample):
    fields, record, _ = sample
    evidence, _ = compare_record(fields, record)
    assert evidence["journal"]["match"]
    fields["title"] = "A and B"
    record["title"] = ["A & B"]
    assert not compare_record(fields, record)[0]["title"]["match"]


@pytest.mark.parametrize(
    "relation", ["has-preprint", "is-version-of", "erratum", "unknown"]
)
def test_version_and_unknown_relationships_still_block(sample, relation):
    fields, record, _ = sample
    record.pop("published")
    record["relation"] = {relation: [{"id": "10.1234/b"}]}
    assert candidate(fields, record)["issues"]
    record["relation"] = {"has-review": [{"id": "10.1234/b"}]}
    assert not candidate(fields, record)["issues"]


def test_secondary_proves_print_year_with_same_volume_and_pages(sample):
    fields, record, raw = sample
    c = secondary(fields, record, raw)
    assert not c["issues"]
    assert (
        c["resolved_findings"] and c["evidence"]["year"]["source_name"] == "europepmc"
    )


@pytest.mark.parametrize(
    "change", ["doi", "author", "pages", "volume", "year", "type", "retracted", "title"]
)
def test_secondary_conflicts_never_approve(sample, change):
    fields, record, raw = sample
    if change == "doi":
        raw["doi"] = "10.1234/b"
    if change == "author":
        raw["authorList"]["author"][0]["firstName"] = "Alice Q"
    if change == "pages":
        raw["pageInfo"] = "124-129"
    if change == "volume":
        raw["journalInfo"]["volume"] = "3"
    if change == "year":
        raw["journalInfo"]["yearOfPublication"] = 2021
    if change == "type":
        raw["pubTypeList"]["pubType"] = ["Preprint"]
    if change == "retracted":
        raw["isRetracted"] = "Y"
    if change == "title":
        raw["title"] = "A result"
    assert secondary(fields, record, raw)["issues"]


def test_secondary_cannot_outvote_substantive_crossref_conflict(sample):
    fields, record, raw = sample
    record["author"][0]["given"] = "Alice Q"
    assert secondary(fields, record, raw)["issues"]
    record["author"][0]["given"] = "Alice"
    assert not secondary(fields, record, raw)["issues"]
    record["page"] = "125-129"
    assert secondary(fields, record, raw)["issues"]


def test_single_page_crossref_can_be_completed_only_with_matching_medline(sample):
    fields, record, raw = sample
    record.pop("published")
    record["page"] = "123"
    assert not secondary(fields, record, raw)["issues"]
    raw["pageInfo"] = "123-130"
    assert secondary(fields, record, raw)["issues"]


@pytest.mark.parametrize(
    "pages,expected",
    [
        ("123-9", "123-129"),
        ("199-02", "199-202"),
        ("S123-S9", "s123-s129"),
        ("E10-E20", "e10-e20"),
        ("e001", "e001"),
        ("1-9", "1-9"),
    ],
)
def test_abbreviated_page_expansion(pages, expected):
    assert expanded_pages(pages) == expected


def test_ambiguous_candidates_and_wrong_explicit_doi_stay_unresolved(sample):
    fields, record, raw = sample
    good = secondary(fields, record, raw)
    rival = deepcopy(candidate(fields, record))
    rival["doi"] = "10.1234/b"
    assert select_result(fields, [good, rival], [])["status"] == "needs_review"
    assert (
        select_result(dict(fields, doi="10.1234/wrong"), [good], [])["status"]
        == "needs_review"
    )


def test_secondary_assessment_is_recomputed_not_trusted(sample):
    fields, record, raw = sample
    primary, second = candidate(fields, record), secondary(fields, record, raw)
    previous = {"status": "metadata_verified", "candidates": [primary, second]}
    assert reassess({"fields": fields}, previous)["status"] == "metadata_verified"
    second["raw_record"]["doi"] = "10.1234/wrong"
    assert reassess({"fields": fields}, previous)["status"] == "needs_review"


def test_multiple_pubmed_ids_for_one_doi_cannot_be_cherry_picked(sample):
    fields, record, raw = sample
    first = secondary(fields, record, raw)
    other = deepcopy(first)
    other["raw_record"]["id"] = "789012"
    other["issues"] = ["Different article"]
    assert select_result(fields, [first, other], [])["status"] == "needs_review"


def test_batch_exact_identifiers_and_truncation(sample):
    raw = sample[2]

    class Client:
        def get(self, url, params):
            assert params["query"] == 'DOI:"10.1234/a" OR DOI:"10.1234/b"'
            return {
                "http_status": 200,
                "body": {"hitCount": 1, "resultList": {"result": [raw]}},
            }

    indexed, _ = fetch_epmc(Client(), ["10.1234/a", "10.1234/b"])
    assert len(indexed["10.1234/a"]) == 1 and not indexed["10.1234/b"]
    with pytest.raises(ValueError):
        fetch_epmc(Client(), ['10.1234/a" OR TITLE:whatever'])

    class Truncated:
        def get(self, *args):
            return {
                "http_status": 200,
                "body": {"hitCount": 200, "resultList": {"result": []}},
            }

    with pytest.raises(ProviderError):
        fetch_epmc(Truncated(), ["10.1234/a"])


def test_migration_retains_history_and_modified_entry_is_pending(tmp_path, sample):
    fields, record, _ = sample
    bib = tmp_path / "a.bib"
    bib.write_text(
        "@article{A,title={A result: its meaning},author={A B Smith},year={2020},journal={Memory and Cognition},volume={2},pages={123--129}}"
    )
    entry = load_entries(bib)["A"]
    record.pop("published")
    cache = Cache(tmp_path / "cache.sqlite3")
    previous = {
        "status": "needs_review",
        "candidates": [candidate(entry["fields"], record)],
    }
    cache.put(bib, entry, previous)
    cache.db.execute("UPDATE reviews SET policy='old'")
    cache.db.commit()
    assert cache.get(bib, entry) is None
    result = run_auto_review(bib, cache, tmp_path / "report.jsonl")
    assert result["A"]["status"] == "metadata_verified"
    count = cache.db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    run_auto_review(bib, cache, tmp_path / "report.jsonl")
    assert cache.db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == count
    bib.write_text(bib.read_text().replace("meaning", "other meaning"))
    assert (
        run_auto_review(bib, cache, tmp_path / "report.jsonl")["A"]["status"]
        == "pending"
    )
