"""Phase 0 (resolver 28) rules on real cached cases, with negative controls.

Fixture: tests/fixtures/phase0_cases.json.gz holds the unmodified latest
current review rows (read-only from the verification cache on 2026-09-22) and
the cdl.bib entries they belong to. See verification/phase0-2026-09-22/README.md.
"""

from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
from auto_review import (cited_work_dois, reassess, secondary_notice_flags, select_result,  # noqa: E402
                         unique_crossref_primaries)
from correction_proposals import (add_doi_proposal, byline_adds_information, byline_loses_detail,  # noqa: E402
                                  drop_publisher_proposal, field_proposal, single_source_identity,
                                  single_source_proposal, title_small_difference)
from pmc_corrections import pmc_article_number_proposal, pmc_coordinate_proposal  # noqa: E402
from verification import (apa_twin_key, compare_record, normalize_doi, normalize_journal,  # noqa: E402
                          print_year_selects_cited)

CASES = json.loads(gzip.open(Path(__file__).parent / "fixtures/phase0_cases.json.gz").read())["cases"]
NOTICE = "DOI-linked source correction/retraction notice requires adjudication"
SUFFIX = "DOI-linked PubMed author suffix conflicts with the citation"
COORDS = "DOI-linked publisher/PubMed article coordinates conflict with or are missing from the citation"
YEAR = "year: conflicting or missing publication dates; select the cited edition explicitly"


@pytest.fixture(autouse=True)
def repository_root(monkeypatch):
    monkeypatch.chdir(ROOT)  # helpers.py reads bibcheck/*.txt relative to the root


def case(key):
    data = deepcopy(CASES[key])
    return data["entry"], data["previous"]


def reviewed(key):
    entry, previous = case(key)
    return entry, reassess(entry, previous)


# 1. Negative DOI-linked evidence is reported only for the cited work ---------

@pytest.mark.parametrize("key", ["HarrEtal20", "BrisEtal02"])
def test_unrelated_search_candidate_notice_is_not_attributed(key):
    entry, result = reviewed(key)
    assert secondary_notice_flags(result["candidates"])  # evidence retained
    assert NOTICE not in result["issues"]
    assert result["status"] == "needs_review"


@pytest.mark.parametrize("key", ["VirtEtal20", "ChanEtal12b", "RebeEtal02"])
def test_cited_work_notice_is_kept(key):
    assert NOTICE in reviewed(key)[1]["issues"]


def test_notice_kept_when_title_evidence_is_missing():
    entry, result = reviewed("BrisEtal02")
    flagged = secondary_notice_flags(result["candidates"])
    candidates = deepcopy(result["candidates"])
    for c in candidates:
        if c.get("source") == "crossref" and c.get("doi") and normalize_doi(c["doi"]) in flagged:
            c["evidence"] = {}
    checked = select_result(entry["fields"], candidates, [])
    assert NOTICE in checked["issues"]


def test_supplied_doi_scopes_flags_to_itself():
    entry, result = reviewed("BrisEtal02")
    flagged = next(iter(secondary_notice_flags(result["candidates"])))
    assert cited_work_dois(entry["fields"], result["candidates"], flagged) == {flagged}
    assert NOTICE in select_result(dict(entry["fields"], doi=flagged), result["candidates"], [])["issues"]


def test_coordinate_flag_from_rival_is_dropped_but_identity_kept():
    assert COORDS not in reviewed("GreeEtal13")[1]["issues"]
    assert COORDS in reviewed("HardEtal13")[1]["issues"]
    # Suffixes are ignored on both sides (user decision 2026-09-24/25): a
    # DOI-linked PubMed suffix is no longer reported as a conflict.
    assert SUFFIX not in reviewed("ColdEtal96b")[1]["issues"]
    # Murd56's own DOI ("Backward" learning..., similarity 0.96) carries Jr.
    assert SUFFIX not in reviewed("Murd56")[1]["issues"]


# 2. Byte-identical Crossref duplicates collapse; differing copies do not ------

def test_identical_duplicate_crossref_records_collapse():
    entry, result = reviewed("BogaEtal07")
    doi = "10.1098/rstb.2007.2059"
    copies = [c for c in result["candidates"] if c.get("source") == "crossref" and normalize_doi(c["doi"]) == doi]
    assert len(copies) >= 2 and len(unique_crossref_primaries(result["candidates"], doi)) == 1
    proposal = pmc_coordinate_proposal(entry, result)
    assert proposal["changes"] == {"number": {"before": None, "after": "1485"},
                                   "pages": {"before": None, "after": "1655--1670"},
                                   "volume": {"before": None, "after": "362"}}
    assert pmc_coordinate_proposal(*reviewed("CanoEtal07"))["changes"] == {
        "pages": {"before": "185", "after": "185--196"}}


def test_differing_duplicate_crossref_records_stay_ambiguous():
    entry, result = reviewed("BogaEtal07")
    doi = "10.1098/rstb.2007.2059"
    copy = next(c for c in reversed(result["candidates"])
                if c.get("source") == "crossref" and normalize_doi(c["doi"]) == doi)
    copy["record"] = dict(copy["record"], page="1655-1671")
    assert len(unique_crossref_primaries(result["candidates"], doi)) == 2
    assert pmc_coordinate_proposal(entry, result) is None


# 3. Print year ------------------------------------------------------------------

@pytest.mark.parametrize("key", ["Zoll90", "MuijReyn03"])
def test_digitized_later_online_date_accepts_print_year(key):
    entry, result = reviewed(key)
    assert result["status"] == "metadata_verified"


@pytest.mark.parametrize("key", ["LindEtal21", "BaleEtal21", "StonEtal18"])
def test_online_first_and_wrong_year_controls_stay_open(key):
    assert reviewed(key)[1]["status"] == "needs_review"


def zoll90_record():
    entry, previous = case("Zoll90")
    record = next(c["record"] for c in previous["candidates"] if c.get("source") == "crossref"
                  and normalize_doi(c["doi"]) == "10.1002/tea.3660271011")
    return entry["fields"], deepcopy(record)


def test_print_year_rule_requires_every_condition():
    fields, record = zoll90_record()
    # compare_record still reports the conflict; select_result's route accepts it.
    assert print_year_selects_cited(fields, record) and compare_record(fields, record)[1] == [YEAR]
    variants = {
        "online earlier": dict(record, **{"published-online": {"date-parts": [[1989, 5]]}}),
        "online same year": dict(record, **{"published-online": {"date-parts": [[1990, 5]]}}),
        "issued online": dict(record, issued={"date-parts": [[2011, 2, 3]]}),
        "two print dates": dict(record, **{"published-print": {"date-parts": [[1990], [1991]]}}),
        "no online": {k: v for k, v in record.items() if k != "published-online"} | {"issued": {"date-parts": [[1991]]}},
        "proceedings": dict(record, type="proceedings-article"),
    }
    for name, changed in variants.items():
        assert not print_year_selects_cited(fields, changed), name
    for name, local in {"cited online year": dict(fields, year="2011"), "volume": dict(fields, volume="28"),
                        "pages": dict(fields, pages="1053--1066"), "no pages": {k: v for k, v in fields.items() if k != "pages"},
                        "book": dict(fields, ENTRYTYPE="book")}.items():
        assert not print_year_selects_cited(local, record), name


def test_print_year_route_blocked_by_contradicting_linked_source():
    from verification import print_year_route
    entry, result = reviewed("Zoll90")
    primary = next(c for c in result["candidates"] if c.get("source") == "crossref"
                   and normalize_doi(c["doi"]) == "10.1002/tea.3660271011")
    assert print_year_route(entry["fields"], primary, result["candidates"], result["attempts"])
    # The DOI-linked PubMed lookup must have been made before absence counts.
    assert not print_year_route(entry["fields"], primary, result["candidates"])
    unlooked = [a for a in result["attempts"] if a.get("source") != "europepmc"]
    assert not print_year_route(entry["fields"], primary, result["candidates"], unlooked)
    assert select_result(entry["fields"], result["candidates"], unlooked)["status"] == "needs_review"
    for issue in ("Secondary pages: missing evidence or mismatch", "Secondary year: missing evidence or mismatch",
                  "Full-text and PubMed volumes do not establish the same issue"):
        linked = dict(deepcopy(primary), source="europepmc", issues=[issue])
        candidates = result["candidates"] + [linked]
        assert not print_year_route(entry["fields"], primary, candidates, result["attempts"]), issue
        assert select_result(entry["fields"], candidates, [])["status"] == "needs_review", issue
    # A second finding on the registry record itself is never waived.
    assert not print_year_route(entry["fields"], dict(primary, issues=[YEAR, "number: missing evidence or mismatch"]),
                                result["candidates"], result["attempts"])


# 4. Duplicate DOIs ----------------------------------------------------------------

@pytest.mark.parametrize("key,doi", [
    ("JacoEtal92", "10.1037/0003-066x.47.6.802"),  # clean APA // twin
    ("Gros88", "10.1016/0893-6080(88)90021-4"),  # reissued book chapter
    ("HakiEtal20", "10.3758/s13423-020-01790-z"),  # PsyArXiv preprint
    ("Este50", "10.1037/h0058559"),  # 1994 reprint contradicts year/volume/pages
    ("Raic06", "10.1126/science.1134405"),  # different journal/year
])
def test_non_competing_second_doi_does_not_block(key, doi):
    result = reviewed(key)[1]
    assert result["status"] == "metadata_verified" and result["accepted_doi"] == doi


@pytest.mark.parametrize("key", ["Pike84", "YoneJaco96a", "Knut07"])
def test_genuine_duplicate_registrations_stay_ambiguous(key):
    assert reviewed(key)[1]["status"] == "needs_review"


def test_apa_twin_with_a_differing_coordinate_is_not_collapsed():
    entry, previous = case("JacoEtal92")
    for c in previous["candidates"]:
        if c.get("source") == "crossref" and c["doi"].startswith("10.1037//"):
            c["record"] = dict(c["record"], page="803-809")
    assert reassess(entry, previous)["status"] == "needs_review"
    assert apa_twin_key("10.1037//0003-066X.47.6.802") == apa_twin_key("10.1037/0003-066x.47.6.802")


def test_apa_twin_with_correction_flag_is_not_collapsed():
    entry, previous = case("JacoEtal92")
    for c in previous["candidates"]:
        if c.get("source") == "crossref" and c["doi"].startswith("10.1037//"):
            c["record"] = dict(c["record"], **{"updated-by": [{"DOI": "10.1037/x", "type": "correction"}]})
    assert reassess(entry, previous)["status"] == "needs_review"


def test_rival_chapter_does_not_clear_an_incompletely_matched_article():
    entry, previous = case("Gros88")
    entry["fields"].pop("pages")
    assert reassess(entry, previous)["status"] == "needs_review"


# 5. Documented journal variants ---------------------------------------------------

def test_documented_journal_variants():
    assert reviewed("KoleMage78")[1]["status"] == "metadata_verified"
    assert normalize_journal("American Journal of Psychology") == normalize_journal("The American Journal of Psychology")
    assert normalize_journal("{American} Journal of Psychology") == normalize_journal("The American Journal of Psychology")
    assert normalize_journal("Canadian Journal of Psychology / Revue canadienne de psychologie") == normalize_journal(
        "Canadian Journal of Psychology")
    assert normalize_journal("Lancet") == normalize_journal("The Lancet")
    assert normalize_journal("Annals of Statistics") == normalize_journal("The Annals of Statistics")
    for a, b in [("American Journal of Psychiatry", "The American Journal of Psychology"),
                 ("Canadian Journal of Experimental Psychology", "Canadian Journal of Psychology"),
                 ("Lancet Neurology", "The Lancet"), ("The Lancet Oncology", "Lancet"),
                 ("Annals of Applied Statistics", "The Annals of Statistics"),
                 ("Journal of Experimental Psychology: General", "Journal of Experimental Psychology")]:
        assert normalize_journal(a) != normalize_journal(b), (a, b)


def test_journal_variant_does_not_approve_another_journal():
    entry, previous = case("KoleMage78")
    entry["fields"]["journal"] = "Canadian Journal of Experimental Psychology"
    assert reassess(entry, previous)["status"] == "needs_review"


# 6a. Article-number rule (A1b) ---------------------------------------------------

@pytest.mark.parametrize("key,changes", [
    ("CombEtal19", {"number": {"before": "14", "after": None}, "pages": {"before": "1--14", "after": "14"}}),
    ("Herc09", {"number": {"before": "31", "after": None},
                "pages": {"before": "doi.org/10.3389/neuro.09.031.2009", "after": "31"}}),
])
def test_article_number_proposal(key, changes):
    proposal = pmc_article_number_proposal(*reviewed(key))
    assert proposal["changes"] == changes and proposal["rule"] == "A1b"


@pytest.mark.parametrize("key", ["FoxGrei10", "FiedGloc12", "KoelEtal16"])
def test_article_number_held_cases(key):
    # FoxGrei10 number 10 != article 19; FiedGloc12 number "OCT"; KoelEtal16 only Crossref has issue 1.
    assert pmc_article_number_proposal(*reviewed(key)) is None


def test_article_number_refuses_other_page_shapes():
    entry, previous = case("CombEtal19")
    entry["fields"]["pages"] = "5--9"
    assert pmc_article_number_proposal(entry, reassess(entry, previous)) is None
    entry, previous = case("Herc09")
    entry["fields"]["pages"] = "doi.org/10.3389/neuro.09.032.2009"  # a different DOI
    assert pmc_article_number_proposal(entry, reassess(entry, previous)) is None


# 6b. Single authoritative source -------------------------------------------------

@pytest.mark.parametrize("key,rule,changes", [
    ("CraiEtal96", "S1-I1", {"pages": {"before": "159--179", "after": "159--180"}}),
    ("KiEtal16", "S1-I1", {"title": {
        "before": "Attention stronly modulates reliability of neural responses to naturalistic narrative stimuli",
        "after": "Attention strongly modulates reliability of neural responses to naturalistic narrative stimuli"}}),
    ("Game62", "S1-I2", {"journal": {"before": "Journal of Experimental Psychology: General",
                                      "after": "Journal of Experimental Psychology"}}),
])
def test_single_source_corrections(key, rule, changes):
    entry, result = reviewed(key)
    proposal = single_source_proposal({**entry, "fields": {k: v for k, v in entry["fields"].items() if k != "publisher"}}, result)
    assert proposal["rule"] == rule and proposal["changes"] == changes
    edited = dict(entry, fields=dict({k: v for k, v in entry["fields"].items() if k != "publisher"},
                                     **{f: c["after"] for f, c in changes.items()}))
    assert reassess(edited, result)["status"] == "metadata_verified"


def test_single_source_preserves_accents_in_house_form():
    # House form (user decision 2026-09-24): initials without periods; the
    # source's surname accents are kept.
    entry, result = reviewed("GronEtal00")
    proposal = single_source_proposal(entry, result)
    after = proposal["changes"]["author"]["after"]
    assert "Grön" in after and after.startswith("G Grön")


@pytest.mark.parametrize("key,reason", [
    ("HopkEtal12", "value-held"),  # citation has full names; source initials only
    ("CahiEtal96", "value-held"),
    ("FourEtal19", "too-many-fields"),
    # Crossref spells D R Gitelman "Gitleman": a surname mismatch, held for the user
    # (user rule 2026-09-30) before the erratum check is reached. The cited work's
    # erratum still keeps it open.
    ("RebeEtal02", "value-held"),
    # Crossref's "McClelland" for the cited "McCleeland" was proposed from one source until
    # 2026-09-30; under the user's rule the respelling is the user's to decide.
    ("CleeMcCl91", "value-held"),
])
def test_single_source_holds(key, reason):
    entry, result = reviewed(key)
    explain = {}
    assert single_source_proposal(entry, result, explain) is None
    assert explain["reason"] == reason
    if key == "RebeEtal02":
        assert "surname mismatch" in explain["detail"] and "'D R Gitleman'" in explain["detail"]
        assert "library consensus" not in explain["detail"]
        assert result["status"] == "needs_review"
    if key == "CleeMcCl91":
        assert "cited 'J L McCleeland', source 'J L McClelland'" in explain["detail"]


def test_existing_author_generator_never_discards_given_names():
    for key in ("HopkEtal12", "CahiEtal96"):
        assert field_proposal(*reviewed(key), "author") is None


def test_single_source_identity_requires_first_author_year_and_anchor():
    entry, result = reviewed("CraiEtal96")
    record = next(c["record"] for c in result["candidates"] if c.get("source") == "crossref"
                  and normalize_doi(c["doi"]) == "10.1037/0096-3445.125.2.159")
    fields = {k: v for k, v in entry["fields"].items() if k != "publisher"}
    assert single_source_identity(fields, record) == "I1"
    assert single_source_identity(dict(fields, year="1995"), record) is None
    assert single_source_identity(dict(fields, author="X Someone and " + fields["author"]), record) is None
    assert single_source_identity(dict(fields, journal="Psychological Review", volume="1", pages="1--2"), record) is None
    assert single_source_identity(dict(fields, title="An entirely different paper about memory"), record) is None
    assert single_source_identity(dict(fields, doi="10.1037/other"), record) is None


def test_single_source_refuses_when_two_records_fit():
    entry, result = reviewed("CraiEtal96")
    twin = deepcopy(next(c for c in result["candidates"] if c.get("source") == "crossref"
                         and normalize_doi(c["doi"]) == "10.1037/0096-3445.125.2.159"))
    twin["doi"] = twin["record"]["DOI"] = "10.9999/duplicate.159"
    result["candidates"].append(twin)
    explain = {}
    assert single_source_proposal(entry, result, explain) is None
    assert explain["reason"] == "ambiguous-identity"


def test_single_source_refuses_when_pubmed_contradicts():
    entry, result = reviewed("KiEtal16")
    for c in result["candidates"]:
        if c.get("source") == "europepmc":
            c["raw_record"] = dict(c["raw_record"], title="Attention weakly modulates reliability of neural responses")
    explain = {}
    assert single_source_proposal(entry, result, explain) is None
    assert "disagree" in explain.get("detail", "")


def test_title_and_byline_helpers():
    assert title_small_difference("Attention stronly modulates", "Attention strongly modulates")
    assert title_small_difference("Memory for words", "Memory for words: a review of findings")
    assert not title_small_difference("Memory for words", "Forgetting of pictures in children")
    assert byline_adds_information("A Cleeremans and J L McCleeland",
                                   [{"given": "Axel", "family": "Cleeremans"}, {"given": "James L.", "family": "McClelland"}])
    assert not byline_adds_information("Michael E Hopkins", [{"given": "M.E.", "family": "Hopkins"}])
    assert not byline_adds_information("A Smith", [{"given": "A", "family": "Smith"}, {"given": "B", "family": "Jones"}])
    assert byline_adds_information("A Smith and others", [{"given": "Ann", "family": "Smith"}, {"given": "B", "family": "Jones"}])
    assert byline_loses_detail("Michael E Hopkins", [{"given": "M.E.", "family": "Hopkins"}])
    assert not byline_loses_detail("9999", [{"given": "M.E.", "family": "Hopkins"}])


def test_policy_lists():
    entry, previous = case("CraiEtal96")
    assert drop_publisher_proposal(entry)["changes"] == {
        "publisher": {"before": entry["fields"]["publisher"], "after": None}}
    entry, previous = case("KoleMage78")
    assert drop_publisher_proposal(dict(entry, fields=dict(entry["fields"], ENTRYTYPE="book"))) is None
    result = reassess(entry, previous)
    assert add_doi_proposal(entry, result)["changes"]["doi"]["after"] == result["accepted_doi"]
    assert add_doi_proposal(dict(entry, fields=dict(entry["fields"], doi="10.1037/h0081669")), result) is None


def test_book_or_monograph_rival_still_blocks():
    from verification import rival_blocks
    entry, result = reviewed("Gros88")
    selected = next(c for c in result["candidates"] if c.get("source") == "crossref"
                    and normalize_doi(c["doi"]) == "10.1016/0893-6080(88)90021-4")
    chapter = next(c for c in result["candidates"] if c.get("source") == "crossref"
                   and normalize_doi(c["doi"]) == "10.7551/mitpress/5271.003.0004")
    assert not rival_blocks(entry["fields"], selected, chapter)
    for kind in ("book", "monograph", "edited-book", "other"):
        assert rival_blocks(entry["fields"], selected, dict(chapter, record=dict(chapter["record"], type=kind))), kind


def test_proposals_never_drop_accents():
    assert not byline_adds_information("F P{\\'e}rez and B E Granger",
                                       [{"given": "Fernando", "family": "Perez"}, {"given": "Brian E", "family": "Granger"}])
    assert byline_loses_detail("F P{\\'e}rez", [{"given": "Fernando", "family": "Perez"}])
    from correction_proposals import loses_characters
    assert loses_characters('Archiv F\\"{u}r Psychiatrie', "Archiv F�r Psychiatrie")
    assert loses_characters("Uber {\\\"U}ber", "Uber Uber")
    assert not loses_characters("G Gron", "Georg Grön")


def test_proposals_keep_case_protection_and_decode_entities():
    from correction_proposals import journal_text, loses_characters
    assert loses_characters("comments on {B}owers's (2009) attempt", "comment on bowers’s (2009) attempt")
    assert loses_characters("on {A}mazons {M}echanical {T}urk", "on amazon’s mechanical turk")
    assert not loses_characters("{Parkinson}'s disease", "{Parkinson}'s disease treatment")
    assert not loses_characters("M Racsm\\'{a}ny", "M Racsmány")
    assert journal_text("Journal of Neurology, Neurosurgery &amp; Psychiatry") == \
        "Journal of Neurology, Neurosurgery and Psychiatry"


def test_venue_replacement_needs_pubmed_title_at_publication():
    entry, result = reviewed("Knig96")  # cited Science; Crossref and PubMed both give Nature
    proposal = single_source_proposal(entry, result)
    assert proposal["changes"]["journal"] == {"before": "Science", "after": "Nature"}
    entry, result = reviewed("WrigBeck83")  # Crossref's current title "Psychiatric Services" for 1983
    explain = {}
    assert single_source_proposal(entry, result, explain) is None
    assert explain["detail"] == "journal: journal-replacement-unconfirmed"


@pytest.mark.parametrize("key", ["PereGran07", "PlauMcCl10"])
def test_accent_or_protected_case_loss_is_held(key):
    entry, result = reviewed(key)
    explain = {}
    fields = {k: v for k, v in entry["fields"].items() if k != "publisher"}
    assert single_source_proposal(dict(entry, fields=fields), result, explain) is None, explain


def test_surname_fix_refuses_a_source_that_only_drops_letters():
    # Crossref "Peynrcoğlu" lost the dotless i characters of Peynırcıoğlu.
    assert not byline_adds_information("M J Watkins and Z F Peynircio\\v{g}lu",
                                       [{"given": "Michael J", "family": "Watkins"},
                                        {"given": "Zehra F", "family": "Peynrcoğlu"}])
    assert byline_adds_information("J M Parish", [{"given": "J M", "family": "Parrish"}])


def test_print_year_approval_is_a_valid_snapshot_envelope():
    """A restored R1 approval keeps its evidence check (verification/apply-2026-09-23)."""
    from verification import valid_print_year_approval
    entry, result = reviewed("Zoll90")
    assert result["status"] == "metadata_verified" and valid_print_year_approval(result)
    doi = "10.1002/tea.3660271011"

    def altered(change):
        changed = deepcopy(result)
        for c in changed["candidates"]:
            if c.get("source") == "crossref" and normalize_doi(c["doi"]) == doi:
                change(c)
        return changed

    online_first = altered(lambda c: c["record"].update({"published-online": {"date-parts": [[1989, 5]]}}))
    other_year = altered(lambda c: c["evidence"]["year"].update(local="2011"))
    second_issue = altered(lambda c: c.update(issues=[YEAR, "number: missing evidence or mismatch"]))
    no_journal = altered(lambda c: c["evidence"].pop("journal"))
    for name, bad in {"online first": online_first, "cited online year": other_year,
                      "second finding": second_issue, "not a journal citation": no_journal,
                      "other accepted source": dict(result, accepted_source="europepmc"),
                      "other DOI": dict(result, accepted_doi="10.1002/tea.3660271012"),
                      "PubMed never looked up": dict(result, attempts=[a for a in result["attempts"]
                                                                        if a.get("source") != "europepmc"])}.items():
        assert not valid_print_year_approval(bad), name


# 7. Spot-check fixes (2026-09-24) ------------------------------------------------
# verification/fixes-2026-09-24/: real cached review rows frozen by build_cases.py
# (unmodified), plus the stored PubMed / publisher issue lookups.

FIX = json.loads(gzip.open(ROOT / "tests/fixtures/fixes-2026-09-24-cases.json.gz", "rt").read())


def fix_case(key):
    data = deepcopy(FIX["cases"][key])
    entry = data["entry"]
    return entry, reassess(entry, data["previous"])


def crossref_record(result, doi):
    return next(c["record"] for c in result["candidates"]
                if c.get("source") == "crossref" and c.get("doi") and normalize_doi(c["doi"]) == doi)


@pytest.mark.parametrize("key,after", [
    ("AlyTurk16", "M Aly and N B Turk-Browne"),  # was "Mariam Aly and Nicholas B Turk-Browne"
    ("SmitHalg89", "M E Smith and E Halgren"),   # was "Michael E Smith and Eric Halgren"
    ("Youn79", "D C Young"),                     # was "David C Young"
])
def test_spotcheck_author_after_values_are_house_initials(key, after):
    entry, result = fix_case(key)
    proposal = single_source_proposal(entry, result)
    assert proposal["changes"]["author"]["after"] == after
    edited = dict(entry, fields=dict(entry["fields"], **{f: c["after"] for f, c in proposal["changes"].items()}))
    assert reassess(edited, result)["status"] == "metadata_verified"


def test_spotcheck_smithalg89_gets_the_source_issue():
    from correction_proposals import after_value_statements, complete_issue
    entry, result = fix_case("SmitHalg89")
    proposal = complete_issue(entry, result, single_source_proposal(entry, result))
    assert proposal["changes"]["number"] == {"before": None, "after": "1"}
    assert proposal["issue_completion"] == {"issue": "1", "sources": ["crossref"]}
    assert after_value_statements(entry, result, proposal)[1] == {}
    # Already has a number, or no source states one: nothing is added.
    entry2, result2 = fix_case("AlyTurk16")
    assert complete_issue(entry2, result2, single_source_proposal(entry2, result2)) is None


@pytest.mark.parametrize("key,sources", [("Murd71", ["crossref"]), ("Hint03", ["crossref", "pubmed"])])
def test_spotcheck_split_issue_is_kept_only_because_a_source_states_it(key, sources):
    # The user did not see the issue in Springer's visible citation line; Crossref
    # (and PubMed for Hint03) state it, and so does the page's citation_issue meta.
    entry, result = fix_case(key)
    proposal = single_source_proposal(entry, result)
    assert proposal["changes"]["volume"]["after"] == "10"
    assert proposal["changes"]["number"]["after"] == ("4" if key == "Murd71" else "1")
    assert proposal["issue_evidence"]["sources"] == sources
    assert proposal["field_sources"]["number"] == "+".join(sources)


def test_split_issue_no_source_states_needs_lookup_then_drops():
    # Derived from Hint03: remove the issue from its Crossref and PubMed records.
    entry, result = fix_case("Hint03")
    for c in result["candidates"]:
        if c.get("source") == "crossref":
            c["record"].pop("issue", None)
            c["issues"] = [i for i in c.get("issues", []) if not i.startswith("number:")]
        if c.get("source") == "europepmc":
            c["raw_record"].get("journalInfo", {}).pop("issue", None)
    explain = {}
    assert single_source_proposal(entry, result, explain) is None
    assert explain["reason"] == "issue-lookup-required" and explain["cited_issue"] == "1"
    empty = {"complete": True, "pubmed": {"query": "doi", "pmids": [], "matched": []},
             "publisher": {"url": "https://link.springer.com/article/10.3758/BF03196465",
                           "doi_confirmed": True, "citation_issue": []}}
    proposal = single_source_proposal(entry, result, issue_lookups={"10.3758/bf03196465": empty})
    assert proposal["changes"] == {"volume": {"before": "10(1)", "after": "10"}}
    assert proposal["issue_evidence"]["issue"] is None
    # A publisher page stating the issue confirms it: it is never dropped, and
    # since the resolver cannot verify an issue Crossref lacks, the entry is held.
    stated = dict(empty, publisher=dict(empty["publisher"], citation_issue=["1"]))
    explain = {}
    assert single_source_proposal(entry, result, explain, issue_lookups={"10.3758/bf03196465": stated}) is None
    assert explain["reason"] == "issue-confirmed-outside-resolver"
    assert explain["issue_evidence"]["sources"] == ["publisher-citation_issue"]
    # A page for another DOI is not evidence.
    other = dict(empty, publisher=dict(stated["publisher"], doi_confirmed=False))
    assert "number" not in single_source_proposal(entry, result, issue_lookups={"10.3758/bf03196465": other})["changes"]


@pytest.mark.parametrize("key", ["ScudEtal14", "CohnEtal96"])
def test_issue_only_in_the_citation_is_dropped_after_real_lookups(key):
    from correction_proposals import after_value_statements
    entry, result = fix_case(key)
    explain = {}
    assert single_source_proposal(entry, result, explain) is None
    assert explain["reason"] == "issue-lookup-required"
    lookups = {d: v for d, v in FIX["lookups"].items() if v["key"] == key}
    assert len(lookups) == 1 and next(iter(lookups.values()))["complete"]
    proposal = single_source_proposal(entry, result, issue_lookups=lookups)
    assert proposal["changes"] == {"number": {"before": "1", "after": None}}
    assert proposal["subclasses"] == {"number": "number-dropped-unconfirmed"}
    stated_by, violations = after_value_statements(entry, result, proposal, next(iter(lookups.values())))
    assert violations == {} and "pubmed-eutils lookup" in stated_by["number"][0]


def test_nonplain_stated_issue_is_held():
    entry, result = fix_case("EkstWatr14")
    lookups = {d: v for d, v in FIX["lookups"].items() if v["key"] == "EkstWatr14"}
    explain = {}
    assert single_source_proposal(entry, result, explain, issue_lookups=lookups) is None
    assert "not a plain number: 0 2" in explain["detail"]


def test_house_given_names():
    from correction_proposals import house_given
    # Real registry given names from the fixture records.
    assert house_given("M.-Marsel") == "M-M"            # RebeEtal02 (Mesulam)
    assert house_given("Matthijs A.A.") == "M A A"      # PezzEtal17
    assert house_given("Nicholas B.") == "N B"          # AlyTurk16
    assert house_given("Krešimir") == "K"               # delaEtal07
    assert house_given("Éadaoin W.") == "É W"           # GrifEtal11
    assert house_given("Y-C") == "Y-C"
    assert house_given("R.Mark") == "R M"               # WuEtal01
    for held in ("JR", "de", "Alice Jr.", "María de las", "2nd"):
        with pytest.raises(ValueError):
            house_given(held)


def test_particles_case_and_accents_are_kept():
    from correction_proposals import house_byline, source_authors
    entry, result = fix_case("PezzEtal17")
    assert single_source_proposal(entry, result)["changes"]["author"]["after"] == \
        "G Pezzulo and C Kemere and M A A {van der Meer}"
    entry, result = fix_case("delaEtal07")
    record = crossref_record(result, "10.1038/nature06028")
    assert source_authors(record, entry["fields"]["author"]) == \
        "J {de la Rocha} and B Doiron and E Shea-Brown and K Josić and A Reyes"
    entry, result = fix_case("WillEtal05b")
    record = crossref_record(result, "10.1111/j.1460-9568.2004.03817.x")
    assert "G {van Bruggen}" in source_authors(record, entry["fields"]["author"])  # not "Van Bruggen"
    assert "G {Van Bruggen}" in source_authors(record)  # no citation: the source text, braced
    assert house_byline([{"given": "Jaime", "family": "de la Rocha"}]) == "J de la Rocha"
    # No proposal ever adds a name suffix (user decision 2026-09-24).
    assert house_byline([{"given": "R B", "family": "Freeman", "suffix": "Jr."}]) == "R B Freeman"


def test_corporate_and_brace_led_bylines_are_never_rewritten():
    from correction_proposals import source_authors
    entry, result = fix_case("VirtEtal20")  # Crossref lists "SciPy 1.0 Contributors"
    with pytest.raises(ValueError):
        source_authors(crossref_record(result, "10.1038/s41592-020-0772-5"))
    for key in ("VirtEtal20", "GrifEtal11"):
        entry, result = fix_case(key)
        proposal = single_source_proposal(entry, result)
        assert not proposal or "author" not in proposal["changes"]
        assert not field_proposal(entry, result, "author")


def test_all_capital_or_ambiguous_source_names_are_held():
    entry, result = fix_case("KotcEtal96")  # Crossref "GRÖZINGER"
    explain = {}
    assert single_source_proposal(entry, result, explain) is None
    assert explain["detail"] == "All-capital source surname: case is not evidence"
    entry, result = fix_case("WuEtal01")  # Crossref "R.Mark": no longer proposed as "RMark"
    assert single_source_proposal(entry, result) is None


def test_accent_commands_are_not_case_protection():
    from correction_proposals import loses_characters
    from correction_proposals import source_authors
    entry, result = fix_case("RacsEtal08")
    record = next(c["record"] for c in result["candidates"] if c.get("source") == "crossref"
                  and c["record"].get("DOI", "").lower() == "10.1080/17470210701728750")
    assert source_authors(record, entry["fields"]["author"]) == \
        "M Racsm\\'{a}ny and M A Conway and E A Garab and G Nagymáté"
    # Magymáté -> Nagymáté is a surname mismatch: held for the user (user rule
    # 2026-09-30), never proposed automatically.
    explain = {}
    assert single_source_proposal(entry, result, explain) is None
    assert "surname mismatch" in explain["detail"] and "Nagymáté" in explain["detail"]
    assert not loses_characters("J Garc\\'{i}a", "J García", "author")
    assert not loses_characters("José García", "J García", "author")  # initials drop given-name letters only
    assert loses_characters("José García", "J Garcia", "author")      # a surname accent is lost


def test_after_values_must_be_stated_by_a_source():
    from correction_proposals import after_value_statements
    entry, result = fix_case("Hint03")
    proposal = single_source_proposal(entry, result)
    stated_by, violations = after_value_statements(entry, result, proposal)
    assert violations == {} and stated_by["number"] == ["crossref", "pubmed:12747488"]
    # Negative controls: a value only the citation (or nobody) has.
    wrong = deepcopy(proposal)
    wrong["changes"]["number"]["after"] = "2"
    assert "number" in after_value_statements(entry, result, wrong)[1]
    dropped = deepcopy(proposal)
    dropped["changes"]["number"]["after"] = None
    assert after_value_statements(entry, result, dropped)[1]["number"].startswith("deleted although stated")
    entry, result = fix_case("Youn79")
    proposal = single_source_proposal(entry, result)
    carried = deepcopy(proposal)
    carried["changes"]["title"]["after"] = entry["fields"]["title"]  # the citation's own typo
    assert "title" in after_value_statements(entry, result, carried)[1]


def test_issue_lookup_replays_stored_responses_with_zero_requests(tmp_path):
    """The real lookup code over stored PubMed/publisher responses (no network)."""
    import sqlite3
    from publisher_corrections import _summary_matches, issue_lookup
    from verification import Cache, PoliteClient
    cache = Cache(tmp_path / "lookups.sqlite3")
    for request, fetched, body in FIX["replay"]["responses"]:
        cache.db.execute("INSERT INTO responses VALUES (?, ?, ?)", (request, fetched, body))
    cache.db.commit()

    class NoNetwork:
        headers = {}

        def get(self, *args, **kwargs):
            raise AssertionError("a stored lookup must not reach the network")
    client = PoliteClient(cache, "tests@example.org", session=NoNetwork())
    entry, result = fix_case("Hint03")
    hint = issue_lookup(cache, client, "10.3758/bf03196465", crossref_record(result, "10.3758/bf03196465"))
    assert [(h["pmid"], h["issue"]) for h in hint["pubmed"]["matched"]] == [("12747488", "1")]
    assert hint["publisher"]["doi_confirmed"] and hint["publisher"]["citation_issue"] == ["1"]
    entry, result = fix_case("ScudEtal14")
    scud = issue_lookup(cache, client, "10.1016/j.bandc.2014.03.016",
                        crossref_record(result, "10.1016/j.bandc.2014.03.016"))
    assert scud["complete"] and scud["pubmed"]["pmids"] == ["24747513"]
    assert [h["issue"] for h in scud["pubmed"]["matched"]] == [""]  # PubMed has the work, no issue
    assert scud["publisher"]["doi_confirmed"] and scud["publisher"]["citation_issue"] == []  # Elsevier API
    entry, result = fix_case("CohnEtal96")
    cohn = issue_lookup(cache, client, "10.1613/jair.295", crossref_record(result, "10.1613/jair.295"))
    assert cohn["pubmed"]["query"].startswith("doi, then ecitmatch") and cohn["pubmed"]["matched"] == []
    assert cohn["publisher"]["error"] and not cohn["publisher"]["doi_confirmed"]
    assert client.requests == 0
    # A summary naming another DOI is not the work.
    summary = json.loads(next(b for r, _, b in FIX["replay"]["responses"] if "esummary" in r and "12747488" in r))
    item = summary["body"]["result"]["12747488"]
    record = crossref_record(fix_case("Hint03")[1], "10.3758/bf03196465")
    assert _summary_matches(item, "10.3758/bf03196465", record)
    assert not _summary_matches(item, "10.3758/bf03212827", record)
