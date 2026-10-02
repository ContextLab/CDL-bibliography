"""Entry completion, the pure builder: ``cdlbib.complete.build`` and ``render``.

Every source record is a saved real response (tests/fixtures/completion/records.json; the
README beside it names the case file each one was taken from). Expected entries are written
out in full below. The ones in ``LIBRARY`` are the exact text of the same work's entry in the
frozen library fixture (tests/fixtures/cdl-prewave1-2026-09-26.bib), which the first test
checks; no test reads the live cdl.bib.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from cdlbib import complete
from cdlbib.auto_review import epmc_record
from cdlbib.errors import CdlbibError, CompletionRefused

ROOT = Path(__file__).resolve().parents[1]
RECORDS = json.loads((ROOT / "tests/fixtures/completion/records.json").read_text(encoding="utf-8"))
FROZEN = (ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib").read_text(encoding="utf-8")

# The exact text of each work's entry in the frozen library fixture.
LIBRARY = {
    "MoheEtal14": (
        "@article{MoheEtal14,\n"
        "\tAuthor = {J Moher and B M Lakshmanan and H E Egeth and J B Ewen},\n"
        "\tDoi = {10.1177/0956797613511257},\n"
        "\tJournal = {Psychological Science},\n"
        "\tNumber = {2},\n"
        "\tPages = {315--324},\n"
        "\tTitle = {Inhibition drives early feature-based attention},\n"
        "\tVolume = {25},\n"
        "\tYear = {2014}}"
    ),
    "Zoll90": (
        "@article{Zoll90,\n"
        "\tAuthor = {U Zoller},\n"
        "\tDoi = {10.1002/tea.3660271011},\n"
        "\tJournal = {Journal of Research in Science Teaching},\n"
        "\tNumber = {10},\n"
        "\tPages = {1053--1065},\n"
        "\tTitle = {Students' misunderstandings and misconceptions in college freshman chemistry (general and organic)},\n"
        "\tVolume = {27},\n"
        "\tYear = {1990}}"
    ),
    "Game62": (
        "@article{Game62,\n"
        "\tAuthor = {P A Games},\n"
        "\tDoi = {10.1037/h0041332},\n"
        "\tJournal = {Journal of Experimental Psychology},\n"
        "\tNumber = {1},\n"
        "\tPages = {1--11},\n"
        "\tTitle = {A factorial analysis of verbal learning tasks},\n"
        "\tVolume = {63},\n"
        "\tYear = {1962}}"
    ),
    "KoelEtal16": (
        "@article{KoelEtal16,\n"
        "\tAuthor = {S Koelsch and T Busch and S Jentschke and M Rohrmeier},\n"
        "\tDoi = {10.1038/srep19741},\n"
        "\tJournal = {Scientific Reports},\n"
        "\tNumber = {1},\n"
        "\tPages = {19741},\n"
        "\tTitle = {Under the hood of statistical learning: a statistical {MMN} reflects the magnitude of transitional probabilities in auditory sequences},\n"
        "\tVolume = {6},\n"
        "\tYear = {2016}}"
    ),
    "AlyTurk16": (
        "@article{AlyTurk16,\n"
        "\tAuthor = {M Aly and N B Turk-Browne},\n"
        "\tDoi = {10.1073/pnas.1518931113},\n"
        "\tJournal = {Proceedings of the National Academy of Sciences, {USA}},\n"
        "\tNumber = {4},\n"
        "\tPages = {e420--e429},\n"
        "\tTitle = {Attention promotes episodic encoding by stabilizing hippocampal representations},\n"
        "\tVolume = {113},\n"
        "\tYear = {2016}}"
    ),
    "ChenEtal21": (
        "@article{ChenEtal21,\n"
        "\tAuthor = {H-T Chen and J R Manning and M A A van der Meer},\n"
        "\tDoi = {10.1016/j.cub.2021.07.061},\n"
        "\tJournal = {Current Biology},\n"
        "\tNumber = {19},\n"
        "\tPages = {4293--4304.e5},\n"
        "\tTitle = {Between-subject prediction reveals a shared representational geometry in the rodent hippocampus},\n"
        "\tVolume = {31},\n"
        "\tYear = {2021}}"
    ),
    "FiedGloc12": (
        "@article{FiedGloc12,\n"
        "\tAuthor = {S Fiedler and A Gl{\\\"{o}}ckner},\n"
        "\tDoi = {10.3389/fpsyg.2012.00335},\n"
        "\tJournal = {Frontiers in Psychology},\n"
        "\tPages = {335},\n"
        "\tTitle = {The dynamics of decision making in risky choice: an eye-tracking analysis},\n"
        "\tVolume = {3},\n"
        "\tYear = {2012}}"
    ),
    "Schr03": (
        "@article{Schr03,\n"
        "\tAuthor = {M Schredl},\n"
        "\tDoi = {10.1007/s00406-003-0438-1},\n"
        "\tJournal = {{European} Archives of Psychiatry and Clinical Neuroscience},\n"
        "\tNumber = {5},\n"
        "\tPages = {241--247},\n"
        "\tTitle = {Effects of state and trait factors on nightmare frequency},\n"
        "\tVolume = {253},\n"
        "\tYear = {2003}}"
    ),
    "PigeEtal12": (
        "@article{PigeEtal12,\n"
        "\tAuthor = {W R Pigeon and M Pinquart and K Conner},\n"
        "\tDoi = {10.4088/jcp.11r07586},\n"
        "\tJournal = {Journal of Clinical Psychiatry},\n"
        "\tNumber = {9},\n"
        "\tPages = {e1160--e1167},\n"
        "\tTitle = {Meta-analysis of sleep disturbance and suicidal thoughts and behaviors},\n"
        "\tVolume = {73},\n"
        "\tYear = {2012}}"
    ),
    "LindEtal21": (
        "@article{LindEtal21,\n"
        "\tAuthor = {C A Lindbergh and N Walker and R {La Joie} and S Weiner-Light and A M Staffaroni and K B Casaletto and F Elahi and S M Walters and M You and D Cotter and B Asken and A C Apple and E Tsoy and J Neuhaus and C Fonseca and A Wolf and Y Cobigo and H Rosen and J H Kramer},\n"
        "\tDoi = {10.1017/S1355617720001009},\n"
        "\tJournal = {Journal of the International Neuropsychological Society},\n"
        "\tNumber = {4},\n"
        "\tPages = {382--388},\n"
        "\tTitle = {Worth the wait: delayed recall after 1 week predicts cognitive and medial temporal lobe trajectories in older adults},\n"
        "\tVolume = {27},\n"
        "\tYear = {2021}}"
    ),
    "Knut07": (
        "@article{Knut07,\n"
        "\tAuthor = {H G Knuttgen},\n"
        "\tJournal = {Journal of Strength and Conditioning Research},\n"
        "\tNumber = {3},\n"
        "\tPages = {973--978},\n"
        "\tTitle = {Strength training and aerobic exercise: comparison and contrast},\n"
        "\tVolume = {21},\n"
        "\tYear = {2007}}"
    ),
    "CleeMcCl91": (
        "@article{CleeMcCl91,\n"
        "\tAuthor = {A Cleeremans and J L McClelland},\n"
        "\tJournal = {Journal of Experimental Psychology: General},\n"
        "\tNumber = {3},\n"
        "\tPages = {235--253},\n"
        "\tTitle = {Learning the structure of event sequences},\n"
        "\tVolume = {120},\n"
        "\tYear = {1991}}"
    ),
    "VirtEtal20": (
        "@article{VirtEtal20,\n"
        "\tAuthor = {P Virtanen and R Gommers and T E Oliphant and M Haberland and T Reddy and D Cournapeau and E Burovski and P Peterson and W Weckesser and J Bright and S J {van der Walt} and M Brett and J Wilson and K Jarrod Millman and N Mayorov and A R J Nelson and E Jones and R Kern and E Larson and C J Carey and {\\I}lhan Polat and Y Feng and E W Moore and J {VanderPlas} and D Laxalde and J Perktold and R Cimrman and I Henriksen and E A Quintero and C R Harris and A M Archibald and A H Ribeiro and F Pedregosa and P {van Mulbregt} and {SciPy 1 0 Contributors}},\n"
        "\tJournal = {Nature Methods},\n"
        "\tNumber = {3},\n"
        "\tPages = {261--272},\n"
        "\tTitle = {{SciPy} 1.0: fundamental algorithms for scientific computing in {Python}},\n"
        "\tVolume = {17},\n"
        "\tYear = {2020}}"
    ),
}


def sources(name):
    """(Crossref record, PubMed-derived record or None) of one saved work."""
    item = RECORDS[name]
    record = item["crossref"]["record"]
    mapped = epmc_record(item["europepmc"]["raw_record"], record) if "europepmc" in item else None
    return deepcopy(record), mapped


def fields_of(text):
    """The fields of one house-layout entry, as a person would have typed them."""
    kind, key = re.match(r"@(\w+)\{([^,]+),", text).groups()
    fields = {"ENTRYTYPE": kind, "ID": key}
    for name, value in re.findall(r"(?m)^\t(\w+) = \{(.*)\}[,}]$", text):
        fields[name.lower()] = value
    return fields


def change(proposal, field):
    found = [c for c in proposal.changes if c.field == field]
    assert len(found) == 1, (field, proposal.changes)
    return found[0]


def unfilled(proposal, field):
    found = [u for u in proposal.unfilled if u.field == field]
    assert len(found) == 1, (field, proposal.unfilled)
    return found[0]


# --- the expectations themselves ------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(LIBRARY))
def test_expected_entries_are_the_frozen_library_entries(key):
    assert "\n\n" + LIBRARY[key] + "\n\n" in "\n\n" + FROZEN


def test_fields_of_reads_an_entry_back():
    assert fields_of(LIBRARY["Zoll90"]) == {
        "ENTRYTYPE": "article", "ID": "Zoll90", "author": "U Zoller", "doi": "10.1002/tea.3660271011",
        "journal": "Journal of Research in Science Teaching", "number": "10", "pages": "1053--1065",
        "title": "Students' misunderstandings and misconceptions in college freshman chemistry (general and organic)",
        "volume": "27", "year": "1990"}


# --- render -----------------------------------------------------------------------------------

def test_render_writes_the_house_layout_in_the_format_checkers_field_order():
    fields = {"year": "1990", "title": "Students' misunderstandings and misconceptions in college freshman "
              "chemistry (general and organic)", "volume": "27", "pages": "1053--1065", "number": "10",
              "journal": "Journal of Research in Science Teaching", "doi": "10.1002/tea.3660271011",
              "author": "U Zoller", "ENTRYTYPE": "article", "ID": "ignored"}
    assert complete.render("article", "Zoll90", fields) == LIBRARY["Zoll90"]


@pytest.mark.parametrize("key", sorted(LIBRARY))
def test_render_reproduces_every_library_entry_from_its_fields(key):
    fields = fields_of(LIBRARY[key])
    assert complete.render(fields["ENTRYTYPE"], key, fields) == LIBRARY[key]


def test_render_with_no_fields_is_a_bare_entry():
    assert complete.render("article", "Zoll90", {}) == "@article{Zoll90}"


# --- a DOI alone ----------------------------------------------------------------------------

# Works whose built entry is the library's entry, byte for byte.
SAME_AS_LIBRARY = ["MoheEtal14", "Zoll90", "Game62", "KoelEtal16", "AlyTurk16", "ChenEtal21"]


@pytest.mark.parametrize("key", SAME_AS_LIBRARY)
def test_a_doi_alone_builds_the_library_entry(key):
    record, mapped = sources(key)
    doi = fields_of(LIBRARY[key])["doi"]
    proposal = complete.build({"doi": doi}, record, mapped)
    assert proposal.proposed_raw == LIBRARY[key]
    assert proposal.key_typed is None and proposal.key_proposed == key
    assert proposal.entry_type == "article" and proposal.unsupported is None
    assert proposal.doi == doi
    assert proposal.unfilled == [] and proposal.issues == []
    assert proposal.needs_decision is False
    assert proposal.record_source == ("crossref+pubmed" if mapped else "crossref")
    # Not this task's to decide: the verifier, duplicates, key suffixes, the typed text.
    assert proposal.status is None and proposal.duplicate_of is None
    assert proposal.candidates == [] and proposal.renames == {} and proposal.typed_raw is None


def test_changes_of_a_doi_only_entry_name_the_source_of_every_field():
    record, mapped = sources("MoheEtal14")
    proposal = complete.build({"doi": "10.1177/0956797613511257"}, record, mapped)
    FC = complete.FieldChange
    assert proposal.changes == [
        FC("author", None, "J Moher and B M Lakshmanan and H E Egeth and J B Ewen", "crossref+pubmed", "filled"),
        FC("doi", "10.1177/0956797613511257", "10.1177/0956797613511257", "typed", "kept"),
        FC("journal", None, "Psychological Science", "crossref", "filled"),
        FC("number", None, "2", "crossref+pubmed", "filled"),
        FC("pages", None, "315--324", "crossref+pubmed", "filled"),
        FC("title", None, "Inhibition drives early feature-based attention", "crossref+pubmed", "filled"),
        FC("volume", None, "25", "crossref+pubmed", "filled"),
        FC("year", None, "2014", "crossref+pubmed", "filled"),
    ]


def test_without_pubmed_every_value_is_crossrefs():
    record, _ = sources("MoheEtal14")
    proposal = complete.build({"doi": "10.1177/0956797613511257"}, record)
    assert proposal.record_source == "crossref"
    assert {c.source for c in proposal.changes if c.kind == "filled"} == {"crossref"}
    # FINDING: Crossref prints this title in Title Case, and the title helper keeps a word with
    # two capitals in braces; only PubMed's sentence-case text gives the library's title.
    assert change(proposal, "title").proposed == "Inhibition drives early {Feature-Based} attention"
    assert proposal.proposed_raw == LIBRARY["MoheEtal14"].replace("feature-based", "{Feature-Based}")


def test_the_print_year_is_chosen_when_the_online_date_is_a_later_digitisation():
    record, mapped = sources("Zoll90")
    assert mapped is None
    assert record["published-print"]["date-parts"] == [[1990, 12]]
    assert record["published-online"]["date-parts"] == [[2011, 2, 3]]
    proposal = complete.build({"doi": "10.1002/tea.3660271011"}, record)
    assert change(proposal, "year") == complete.FieldChange("year", None, "1990", "crossref", "filled")


def test_pages_come_from_pubmed_when_crossref_has_none():
    record, mapped = sources("AlyTurk16")
    assert "page" not in record and "article-number" not in record
    proposal = complete.build({"doi": "10.1073/pnas.1518931113"}, record, mapped)
    assert change(proposal, "pages") == complete.FieldChange("pages", None, "e420--e429", "pubmed", "filled")


def test_an_issue_stated_by_one_source_only_is_written_and_names_that_source():
    # Crossref states issue 1; the DOI-linked PubMed record states none. The existing rule
    # (correction_proposals.confirm_issue) writes an issue that at least one source states.
    for key in ("Game62", "KoelEtal16"):
        record, mapped = sources(key)
        assert record["issue"] == "1" and mapped["issue"] is None
        proposal = complete.build({"doi": record["DOI"]}, record, mapped)
        assert change(proposal, "number") == complete.FieldChange("number", None, "1", "crossref", "filled")
        assert [u for u in proposal.unfilled if u.field == "number"] == []


def test_no_issue_is_written_when_no_source_states_one():
    record, mapped = sources("FiedGloc12")
    proposal = complete.build({"doi": "10.3389/fpsyg.2012.00335"}, record, mapped)
    assert [c for c in proposal.changes if c.field == "number"] == []
    assert "Number" not in proposal.proposed_raw
    assert proposal.unfilled == []


# Works in the library whose built entry differs from the library's entry. Each expected
# text is what the house helpers give for the saved records; the comment says which field
# differs and why.
DIFFERS = {
    # author: the source's "Glöckner" is written as the source prints it (Unicode); the
    # library spells the same letter in LaTeX (Gl{\"{o}}ckner). Pages: the article number
    # is PubMed's (Crossref has none).
    "FiedGloc12": (
        "@article{FiedGloc12,\n"
        "\tAuthor = {S Fiedler and A Glöckner},\n"
        "\tDoi = {10.3389/fpsyg.2012.00335},\n"
        "\tJournal = {Frontiers in Psychology},\n"
        "\tPages = {335},\n"
        "\tTitle = {The dynamics of decision making in risky choice: an eye-tracking analysis},\n"
        "\tVolume = {3},\n"
        "\tYear = {2012}}"
    ),
    # journal: the library has stray braces ({European}); the journal formatter removes them.
    "Schr03": (
        "@article{Schr03,\n"
        "\tAuthor = {M Schredl},\n"
        "\tDoi = {10.1007/s00406-003-0438-1},\n"
        "\tJournal = {European Archives of Psychiatry and Clinical Neuroscience},\n"
        "\tNumber = {5},\n"
        "\tPages = {241--247},\n"
        "\tTitle = {Effects of state and trait factors on nightmare frequency},\n"
        "\tVolume = {253},\n"
        "\tYear = {2003}}"
    ),
    # journal: Crossref's name begins with "The", which the library omits. number: Crossref
    # says "09" and PubMed "9", which the issue rule reads as a disagreement, so none is written.
    "PigeEtal12": (
        "@article{PigeEtal12,\n"
        "\tAuthor = {W R Pigeon and M Pinquart and K Conner},\n"
        "\tDoi = {10.4088/jcp.11r07586},\n"
        "\tJournal = {The Journal of Clinical Psychiatry},\n"
        "\tPages = {e1160--e1167},\n"
        "\tTitle = {Meta-analysis of sleep disturbance and suicidal thoughts and behaviors},\n"
        "\tVolume = {73},\n"
        "\tYear = {2012}}"
    ),
}
DIFFERING_FIELDS = {"FiedGloc12": {"author"}, "Schr03": {"journal"}, "PigeEtal12": {"journal", "number"}}


@pytest.mark.parametrize("key", sorted(DIFFERS))
def test_a_doi_alone_where_the_built_entry_differs_from_the_library(key):
    record, mapped = sources(key)
    library = fields_of(LIBRARY[key])
    proposal = complete.build({"doi": library["doi"]}, record, mapped)
    assert proposal.proposed_raw == DIFFERS[key]
    assert proposal.key_proposed == key
    built = fields_of(proposal.proposed_raw)
    assert {f for f in set(library) | set(built) if library.get(f) != built.get(f)} == DIFFERING_FIELDS[key]


# --- fields a helper refuses, or that sources disagree on -------------------------------------

def test_a_corporate_author_leaves_the_byline_unfilled_with_the_helpers_reason():
    record, mapped = sources("LindEtal21")
    assert record["author"][-1]["name"] == "the Hillblom Aging Network"
    proposal = complete.build({"ID": "LindEtal21", "doi": "10.1017/S1355617720001009"}, record, mapped)
    assert unfilled(proposal, "author").reason == "Incomplete or corporate source byline"
    assert "the Hillblom Aging Network" in unfilled(proposal, "author").source_values["crossref"]
    assert [c for c in proposal.changes if c.field == "author"] == []
    # The library's entry without its Author line: every other field is built.
    assert proposal.proposed_raw == LIBRARY["LindEtal21"].replace(
        "\tAuthor = {C A Lindbergh and N Walker and R {La Joie} and S Weiner-Light and A M Staffaroni and "
        "K B Casaletto and F Elahi and S M Walters and M You and D Cotter and B Asken and A C Apple and "
        "E Tsoy and J Neuhaus and C Fonseca and A Wolf and Y Cobigo and H Rosen and J H Kramer},\n", "")
    assert "Author" not in proposal.proposed_raw
    assert proposal.key_typed == "LindEtal21" and proposal.key_proposed is None
    assert proposal.needs_decision is False


def test_without_an_author_and_without_a_typed_key_there_is_no_key():
    record, mapped = sources("LindEtal21")
    proposal = complete.build({"doi": "10.1017/S1355617720001009"}, record, mapped)
    assert proposal.key_proposed is None
    assert unfilled(proposal, "ID").reason == "a key needs the authors and the year"
    assert proposal.proposed_raw.startswith("@article{" + complete.NO_KEY + ",\n\tDoi = {10.1017/S1355617720001009},")


def test_print_year_with_pubmed_agreeing_is_chosen_and_without_it_is_left_open():
    record, mapped = sources("LindEtal21")
    assert record["published-print"]["date-parts"] == [[2021, 4]]
    assert record["published-online"]["date-parts"] == [[2020, 10, 14]]
    assert mapped["published"] == {"date-parts": [[2021]]}
    with_pubmed = complete.build({"ID": "LindEtal21", "doi": "10.1017/S1355617720001009"}, record, mapped)
    assert change(with_pubmed, "year") == complete.FieldChange("year", None, "2021", "crossref+pubmed", "filled")
    alone = complete.build({"ID": "LindEtal21", "doi": "10.1017/S1355617720001009"}, record)
    assert [c for c in alone.changes if c.field == "year"] == []
    assert unfilled(alone, "year") == complete.Unfilled(
        "year", "year: print and online years differ and no rule selects one",
        {"crossref published-print": "2021", "crossref published-online": "2020",
         "crossref issued": "2020", "crossref published": "2020"})
    assert "Year" not in alone.proposed_raw


def test_an_all_capitals_title_is_left_unfilled_with_the_helpers_reason():
    record, mapped = sources("all-capitals-title")
    assert record["title"] == ["BRAIN WORK AND BRAIN IMAGING"]
    proposal = complete.build({"doi": "10.1146/annurev.neuro.29.051605.112819"}, record, mapped)
    assert unfilled(proposal, "title") == complete.Unfilled(
        "title", "Possible numbered heading or all-capital source typography",
        {"crossref": "BRAIN WORK AND BRAIN IMAGING"})
    # Not in the library: every other value is the saved Crossref record's, in house form.
    assert proposal.proposed_raw == (
        "@article{RaicMint06,\n"
        "\tAuthor = {M E Raichle and M A Mintun},\n"
        "\tDoi = {10.1146/annurev.neuro.29.051605.112819},\n"
        "\tJournal = {Annual Review of Neuroscience},\n"
        "\tNumber = {1},\n"
        "\tPages = {449--476},\n"
        "\tVolume = {29},\n"
        "\tYear = {2006}}")
    assert [u.field for u in proposal.unfilled] == ["title"]


def test_pages_that_the_two_sources_give_differently_are_left_unfilled_with_both_values():
    record, mapped = sources("Knut07")
    assert record["page"] == "973" and mapped["page"] == "973-978"
    proposal = complete.build({"doi": "10.1519/r-505011.1"}, record, mapped)
    assert unfilled(proposal, "pages") == complete.Unfilled(
        "pages", "pages: sources disagree", {"crossref": "973", "pubmed": "973-978"})
    assert [c for c in proposal.changes if c.field == "pages"] == []
    # The library's Knut07 has no DOI, Pages = {973--978} and no "The" in the journal name.
    assert proposal.proposed_raw == (
        "@article{Knut07,\n"
        "\tAuthor = {H G Knuttgen},\n"
        "\tDoi = {10.1519/r-505011.1},\n"
        "\tJournal = {The Journal of Strength and Conditioning Research},\n"
        "\tNumber = {3},\n"
        "\tTitle = {Strength training and aerobic exercise: comparison and contrast},\n"
        "\tVolume = {21},\n"
        "\tYear = {2007}}")


def test_typed_pages_are_kept_when_the_sources_disagree():
    record, mapped = sources("Knut07")
    typed = dict(fields_of(LIBRARY["Knut07"]), doi="10.1519/r-505011.1")
    proposal = complete.build(typed, record, mapped)
    assert change(proposal, "pages") == complete.FieldChange("pages", "973--978", "973--978", "typed", "kept")
    assert unfilled(proposal, "pages").source_values == {"crossref": "973", "pubmed": "973-978"}
    assert "\tPages = {973--978},\n" in proposal.proposed_raw
    # The typed journal name is the record's up to a leading "The": not contradicted, so kept.
    assert change(proposal, "journal").kind == "kept"
    assert "\tJournal = {Journal of Strength and Conditioning Research},\n" in proposal.proposed_raw


def test_an_issue_the_sources_state_differently_is_left_unfilled_with_the_helpers_reason():
    record, mapped = sources("PigeEtal12")
    assert record["issue"] == "09" and mapped["issue"] == "9"
    proposal = complete.build({"doi": "10.4088/jcp.11r07586"}, record, mapped)
    assert unfilled(proposal, "number") == complete.Unfilled(
        "number", "number: sources disagree on the issue: crossref=09; pubmed=9",
        {"crossref": "09", "pubmed": "9"})
    assert "Number" not in proposal.proposed_raw


def test_a_corrected_article_is_built_and_says_that_a_correction_exists():
    record = deepcopy(RECORDS["corporate-author"]["crossref"]["record"])
    with pytest.raises(ValueError):  # PubMed's record carries the correction link: not usable
        epmc_record(RECORDS["corporate-author"]["europepmc"]["raw_record"], record)
    assert record["updated-by"][0]["type"] == "correction"
    proposal = complete.build({"doi": "10.1038/s41592-019-0686-2"}, record)
    assert proposal.issues == ["Source flags an update/correction/retraction relationship"]
    assert unfilled(proposal, "author").reason == "Incomplete or corporate source byline"
    # The library's VirtEtal20 has no DOI and lists the authors, ending in the corporate
    # {SciPy 1 0 Contributors}, which the byline helper refuses to build.
    assert proposal.proposed_raw == (
        "@article{" + complete.NO_KEY + ",\n"
        "\tDoi = {10.1038/s41592-019-0686-2},\n"
        "\tJournal = {Nature Methods},\n"
        "\tNumber = {3},\n"
        "\tPages = {261--272},\n"
        "\tTitle = {{SciPy} 1.0: fundamental algorithms for scientific computing in {Python}},\n"
        "\tVolume = {17},\n"
        "\tYear = {2020}}")


# --- what the person typed --------------------------------------------------------------------

WITH_DOI = ["MoheEtal14", "Zoll90", "Game62", "KoelEtal16", "AlyTurk16", "ChenEtal21",
            "FiedGloc12", "Schr03", "PigeEtal12", "LindEtal21"]


@pytest.mark.parametrize("key", WITH_DOI)
def test_a_complete_typed_entry_is_proposed_exactly_as_typed(key):
    record, mapped = sources(key)
    typed = fields_of(LIBRARY[key])
    before = deepcopy((typed, record, mapped))
    proposal = complete.build(typed, record, mapped)
    assert (typed, record, mapped) == before  # the builder changes none of its arguments
    assert proposal.proposed_raw == LIBRARY[key]
    assert {c.kind for c in proposal.changes} == {"kept"}
    assert all(c.typed == c.proposed == typed[c.field] and c.source == "typed" for c in proposal.changes)
    assert proposal.key_typed == key and proposal.key_proposed == key
    assert proposal.needs_decision is False


def test_a_typed_title_that_matches_is_kept_with_its_own_braces():
    record, mapped = sources("MoheEtal14")
    typed = {"doi": "10.1177/0956797613511257", "title": "Inhibition drives early {F}eature-based attention"}
    proposal = complete.build(typed, record, mapped)
    assert change(proposal, "title") == complete.FieldChange(
        "title", "Inhibition drives early {F}eature-based attention",
        "Inhibition drives early {F}eature-based attention", "typed", "kept")
    assert "\tTitle = {Inhibition drives early {F}eature-based attention},\n" in proposal.proposed_raw


def test_a_typed_volume_the_source_contradicts_is_a_shown_change():
    record, mapped = sources("MoheEtal14")
    proposal = complete.build({"doi": "10.1177/0956797613511257", "volume": "52"}, record, mapped)
    assert change(proposal, "volume") == complete.FieldChange("volume", "52", "25", "crossref+pubmed", "changed")
    assert proposal.proposed_raw == LIBRARY["MoheEtal14"]
    assert proposal.needs_decision is False


def test_a_typed_surname_spelled_differently_is_a_question_and_is_not_applied():
    record, mapped = sources("CleeMcCl91")
    typed = RECORDS["CleeMcCl91"]["typed"]  # the entry as it stood in cdl.bib on 2026-09-17
    assert typed["author"] == "A Cleeremans and J L McCleeland"
    assert [p["family"] for p in record["author"]] == ["Cleeremans", "McClelland"]
    proposal = complete.build(typed, record, mapped)
    assert change(proposal, "author") == complete.FieldChange(
        "author", "A Cleeremans and J L McCleeland", "A Cleeremans and J L McClelland", "crossref", "question")
    assert proposal.needs_decision is True
    assert any("surname mismatch" in issue and "McCleeland" in issue and "McClelland" in issue
               for issue in proposal.issues)
    assert proposal.proposed_raw == (
        "@article{CleeMcCl91,\n"
        "\tAuthor = {A Cleeremans and J L McCleeland},\n"
        "\tDoi = {10.1037/0096-3445.120.3.235},\n"
        "\tJournal = {Journal of Experimental Psychology: General},\n"
        "\tNumber = {3},\n"
        "\tPages = {235--253},\n"
        "\tTitle = {Learning the structure of event sequences},\n"
        "\tVolume = {120},\n"
        "\tYear = {1991}}")
    # With the question answered the source's way, this is the library's entry plus the DOI.
    assert proposal.proposed_raw.replace("McCleeland", "McClelland").replace(
        "\tDoi = {10.1037/0096-3445.120.3.235},\n", "") == LIBRARY["CleeMcCl91"]
    assert change(proposal, "doi") == complete.FieldChange("doi", None, "10.1037/0096-3445.120.3.235", "crossref", "filled")
    assert change(proposal, "number") == complete.FieldChange("number", None, "3", "crossref", "filled")
    assert proposal.key_typed == "CleeMcCl91" and proposal.key_proposed == "CleeMcCl91"
    assert proposal.doi == "10.1037/0096-3445.120.3.235"


def test_typed_fields_outside_the_house_list_and_a_publisher_are_dropped_and_listed():
    record, mapped = sources("MoheEtal14")
    assert record["publisher"] == "SAGE Publications"
    typed = {"doi": "10.1177/0956797613511257", "publisher": "SAGE Publications",
             "url": "https://doi.org/10.1177/0956797613511257", "month": "feb"}
    proposal = complete.build(typed, record, mapped)
    assert proposal.proposed_raw == LIBRARY["MoheEtal14"]
    dropped = [c for c in proposal.changes if c.kind == "dropped"]
    assert dropped == [
        complete.FieldChange("month", "feb", None, "not a house field", "dropped"),
        complete.FieldChange("publisher", "SAGE Publications", None, "house rule: no publisher on an article", "dropped"),
        complete.FieldChange("url", "https://doi.org/10.1177/0956797613511257", None, "not a house field", "dropped"),
    ]


def test_typed_pages_are_never_shortened_to_the_first_page():
    record, _ = sources("Knut07")  # Crossref alone: page "973"
    typed = dict(fields_of(LIBRARY["Knut07"]), doi="10.1519/r-505011.1")
    proposal = complete.build(typed, record)
    assert change(proposal, "pages") == complete.FieldChange("pages", "973--978", "973--978", "typed", "kept")
    assert unfilled(proposal, "pages") == complete.Unfilled(
        "pages", "pages: the source would shorten the cited range", {"crossref": "973"})


def test_a_typed_year_that_is_the_online_year_is_changed_to_the_print_year():
    record, mapped = sources("LindEtal21")
    typed = dict(fields_of(LIBRARY["LindEtal21"]), year="2020")
    proposal = complete.build(typed, record, mapped)
    assert change(proposal, "year") == complete.FieldChange("year", "2020", "2021", "crossref+pubmed", "changed")
    # The typed byline cannot be compared with a corporate source byline: kept, and said so.
    assert change(proposal, "author").kind == "kept"
    assert unfilled(proposal, "author").reason == "Incomplete or corporate source byline"
    assert proposal.proposed_raw == LIBRARY["LindEtal21"]


# --- Review Focus 1: the DOI is another work's ------------------------------------------------

def test_a_doi_that_resolves_to_a_different_work_keeps_the_typed_title_and_authors():
    record, mapped = sources("Zoll90")  # the DOI typed by mistake resolves to Zoller 1990
    typed = {"ID": "MoheEtal14", "doi": "10.1002/tea.3660271011",
             "title": "Inhibition drives early feature-based attention",
             "author": "J Moher and B M Lakshmanan and H E Egeth and J B Ewen"}
    proposal = complete.build(typed, record, mapped)
    assert proposal.needs_decision is True
    assert proposal.issues == [
        "doi: the DOI 10.1002/tea.3660271011 resolves to a different work than the typed title and authors "
        "(the record: \"Students' misunderstandings and misconceptions in college freshman chemistry "
        "(general and organic)\", by Zoller); nothing was filled from it"]
    assert proposal.proposed_raw == (
        "@article{MoheEtal14,\n"
        "\tAuthor = {J Moher and B M Lakshmanan and H E Egeth and J B Ewen},\n"
        "\tDoi = {10.1002/tea.3660271011},\n"
        "\tTitle = {Inhibition drives early feature-based attention}}")
    assert change(proposal, "title") == complete.FieldChange(
        "title", "Inhibition drives early feature-based attention",
        "Students' misunderstandings and misconceptions in college freshman chemistry (general and organic)",
        "crossref", "question")
    assert change(proposal, "author") == complete.FieldChange(
        "author", "J Moher and B M Lakshmanan and H E Egeth and J B Ewen", "U Zoller", "crossref", "question")
    assert change(proposal, "doi").kind == "question"
    # Nothing of the other work is written into the entry.
    assert all(c.kind == "question" for c in proposal.changes)
    assert "Zoller" not in proposal.proposed_raw and "1990" not in proposal.proposed_raw
    assert proposal.key_proposed is None


def test_a_typed_title_alone_that_is_another_works_is_the_same_conflict():
    record, mapped = sources("Zoll90")
    typed = {"doi": "10.1002/tea.3660271011", "title": "Inhibition drives early feature-based attention"}
    proposal = complete.build(typed, record, mapped)
    assert proposal.needs_decision is True
    assert "resolves to a different work than the typed title" in proposal.issues[0]
    assert "\tTitle = {Inhibition drives early feature-based attention}}" in proposal.proposed_raw
    assert "Journal" not in proposal.proposed_raw


def test_a_small_title_difference_is_a_change_not_a_different_work():
    record, mapped = sources("MoheEtal14")
    typed = {"doi": "10.1177/0956797613511257", "title": "Inhibition drives feature-based attention"}
    proposal = complete.build(typed, record, mapped)
    assert proposal.needs_decision is False and proposal.issues == []
    assert change(proposal, "title") == complete.FieldChange(
        "title", "Inhibition drives feature-based attention",
        "Inhibition drives early feature-based attention", "crossref+pubmed", "changed")
    assert proposal.proposed_raw == LIBRARY["MoheEtal14"]


def test_a_typed_doi_that_is_not_the_records_is_never_replaced():
    record, mapped = sources("MoheEtal14")
    proposal = complete.build({"doi": "10.1177/0956797613511258"}, record, mapped)
    assert proposal.needs_decision is True
    assert proposal.issues == ["doi: the record's DOI 10.1177/0956797613511257 is not the typed DOI "
                               "10.1177/0956797613511258; nothing was filled from it"]
    assert proposal.proposed_raw == "@article{" + complete.NO_KEY + ",\n\tDoi = {10.1177/0956797613511258}}"


# --- records that are not built ---------------------------------------------------------------

def test_a_book_chapter_record_is_not_built_and_the_type_is_named():
    record, mapped = sources("book-chapter")
    assert record["type"] == "book-chapter"
    typed = {"doi": "10.4324/9781315782379-49"}
    proposal = complete.build(typed, record, mapped)
    assert proposal.unsupported == "book-chapter"
    assert proposal.proposed_raw is None and proposal.changes == [] and proposal.unfilled == []
    assert proposal.issues == ["A record of type book-chapter is not built automatically; the entry is left as typed"]
    assert proposal.needs_decision is False


def test_a_preprint_record_is_not_built_by_the_article_builder():
    record, mapped = sources("preprint")
    assert record["type"] == "posted-content" and record["subtype"] == "preprint"
    proposal = complete.build({"doi": "10.1101/511782"}, record, mapped)
    assert proposal.unsupported == "posted-content" and proposal.proposed_raw is None
    assert proposal.issues == ["A record of type posted-content is not built automatically; the entry is left as typed"]


def test_a_typed_entry_that_is_not_an_article_is_not_built():
    record, mapped = sources("MoheEtal14")
    proposal = complete.build({"ENTRYTYPE": "inproceedings", "ID": "MoheEtal14", "doi": "10.1177/0956797613511257"},
                              record, mapped)
    assert proposal.unsupported == "inproceedings" and proposal.entry_type == "inproceedings"
    assert proposal.proposed_raw is None
    assert proposal.issues == ["An entry of type inproceedings is not built automatically; the entry is left as typed"]


def test_an_erratum_record_is_refused_with_the_reason():
    record, mapped = sources("erratum")
    assert record["title"] == ["Author Correction: SciPy 1.0: fundamental algorithms for scientific computing in Python"]
    assert record["update-to"][0]["type"] == "correction"
    with pytest.raises(CompletionRefused) as refused:
        complete.build({"doi": "10.1038/s41592-020-0772-5"}, record, mapped)
    assert isinstance(refused.value, CdlbibError)
    assert str(refused.value) == ("The record 10.1038/s41592-020-0772-5 is a correction of "
                                  "10.1038/s41592-019-0686-2, not the article itself; cite the article")


def test_the_builder_prints_nothing(capsys):
    for key in ("MoheEtal14", "LindEtal21", "PigeEtal12", "book-chapter"):
        record, mapped = sources(key)
        complete.build({"doi": record["DOI"]}, record, mapped)
    complete.render("article", "Zoll90", fields_of(LIBRARY["Zoll90"]))
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


# --- the built entries pass the format checker --------------------------------------------------

def test_built_entries_pass_the_format_checker(tmp_path):
    from cdlbib.helpers import check_bib
    built = []
    for key, doi in (("MoheEtal14", None), ("Zoll90", None), ("Game62", None), ("KoelEtal16", None),
                     ("AlyTurk16", None), ("ChenEtal21", None), ("FiedGloc12", None), ("Schr03", None),
                     ("PigeEtal12", None), ("Knut07", "10.1519/r-505011.1")):
        record, mapped = sources(key)
        proposal = complete.build({"doi": doi or fields_of(LIBRARY[key])["doi"]}, record, mapped)
        built.append(proposal.proposed_raw)
    bib = tmp_path / "built.bib"
    bib.write_text("\n\n".join(built) + "\n", encoding="utf-8")
    errors, _ = check_bib(str(bib), verbose=False)
    assert errors == {}
