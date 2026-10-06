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
RECORDS.update(json.loads((ROOT / "tests/fixtures/completion/more_records.json").read_text(encoding="utf-8")))
# One record fetched for these tests (see the fixture README): an article that was retracted.
RETRACTED = json.loads((ROOT / "tests/fixtures/completion/retracted-article.json").read_text(encoding="utf-8"))

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
    "MeyeEtal88": (
        "@article{MeyeEtal88,\n"
        "\tAuthor = {D E Meyer and D E Irwin and A M Osman and J Kounios},\n"
        "\tDoi = {10.1037/0033-295x.95.2.183},\n"
        "\tJournal = {Psychological Review},\n"
        "\tNumber = {2},\n"
        "\tPages = {183--237},\n"
        "\tTitle = {The dynamics of cognition and action: mental processes inferred from speed-accuracy decomposition},\n"
        "\tVolume = {95},\n"
        "\tYear = {1988}}"
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
SAME_AS_LIBRARY = ["MoheEtal14", "Zoll90", "Game62", "AlyTurk16", "ChenEtal21"]


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
    record, _ = sources("Zoll90")
    proposal = complete.build({"doi": "10.1002/tea.3660271011"}, record)
    assert proposal.record_source == "crossref"
    assert {c.source for c in proposal.changes if c.kind == "filled"} == {"crossref"}


@pytest.mark.parametrize("key", ["MoheEtal14", "FiedGloc12", "PigeEtal12", "sentence-case-proper-noun", "KoelEtal16", "all-capitals-title", "MeyeEtal88"])
def test_saved_source_titles_use_existing_autofix(key):
    from cdlbib.helpers import format_title
    record, mapped = sources(key)
    proposal = complete.build({"doi": record["DOI"]}, record, mapped)
    expected = format_title(record["title"][0])
    assert change(proposal, "title").proposed == complete.latex_text(expected)
    assert change(proposal, "title").kind == "filled"


@pytest.mark.parametrize("key", ["MoheEtal14", "Zoll90", "Game62", "FiedGloc12", "Schr03"])
def test_saved_source_author_and_journal_use_existing_helpers(key):
    from cdlbib import correction_proposals as cp
    from cdlbib.helpers import reformat_author, format_journal_name
    record, mapped = sources(key)
    proposal = complete.build({"doi": record["DOI"]}, record, mapped)
    author = complete.latex_text(cp.source_authors(record))
    assert change(proposal, "author").proposed == reformat_author(author)
    journal = complete.latex_text(format_journal_name(cp.journal_text(record["container-title"][0])))
    assert change(proposal, "journal").proposed == format_journal_name(journal)


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
    # author: the source's "Glöckner" is written in LaTeX in the library's most common form
    # for an umlaut, {\"o}; this entry of the library uses another form, {\"{o}}. Pages: the
    # article number is PubMed's (Crossref has none).
    "FiedGloc12": (
        "@article{FiedGloc12,\n"
        "\tAuthor = {S Fiedler and A Gl{\\\"o}ckner},\n"
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
    # journal: Crossref's name begins with "The", which the library omits.
    "PigeEtal12": (
        "@article{PigeEtal12,\n"
        "\tAuthor = {W R Pigeon and M Pinquart and K Conner},\n"
        "\tDoi = {10.4088/jcp.11r07586},\n"
        "\tJournal = {The Journal of Clinical Psychiatry},\n"
        "\tNumber = {9},\n"
        "\tPages = {e1160--e1167},\n"
        "\tTitle = {Meta-analysis of sleep disturbance and suicidal thoughts and behaviors},\n"
        "\tVolume = {73},\n"
        "\tYear = {2012}}"
    ),
}
DIFFERING_FIELDS = {"FiedGloc12": {"author"}, "Schr03": {"journal"}, "PigeEtal12": {"journal"}}


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
    # Capitalization is handled by the existing formatter.
    assert mapped["title"] == record["title"] == [
        "Worth the Wait: Delayed Recall after 1 Week Predicts Cognitive and Medial Temporal Lobe "
        "Trajectories in Older Adults"]
    assert change(proposal, "title").kind == "filled" and proposal.issues == []
    assert proposal.needs_decision is True


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



def test_a_first_page_from_one_source_and_the_range_from_the_other_gives_the_range():
    record, mapped = sources("Knut07")
    assert record["page"] == "973" and mapped["page"] == "973-978"
    proposal = complete.build({"doi": "10.1519/r-505011.1"}, record, mapped)
    assert change(proposal, "pages") == complete.FieldChange(
        "pages", None, "973--978", "pubmed; crossref gives the first page", "filled")
    assert [u for u in proposal.unfilled if u.field == "pages"] == []
    assert proposal.needs_decision is False
    # The library's Knut07 plus the DOI; the journal name keeps Crossref's "The".
    assert proposal.proposed_raw == (
        "@article{Knut07,\n"
        "\tAuthor = {H G Knuttgen},\n"
        "\tDoi = {10.1519/r-505011.1},\n"
        "\tJournal = {The Journal of Strength and Conditioning Research},\n"
        "\tNumber = {3},\n"
        "\tPages = {973--978},\n"
        "\tTitle = {Strength training and aerobic exercise: comparison and contrast},\n"
        "\tVolume = {21},\n"
        "\tYear = {2007}}")
    assert proposal.proposed_raw.replace("\tDoi = {10.1519/r-505011.1},\n", "").replace(
        "{The Journal", "{Journal") == LIBRARY["Knut07"]


def test_a_lone_first_page_from_one_source_is_filled_as_a_question():
    record, _ = sources("Knut07")  # Crossref alone: page "973"; the article runs to 978
    proposal = complete.build({"doi": "10.1519/r-505011.1"}, record)
    assert change(proposal, "pages") == complete.FieldChange("pages", None, "973", "crossref", "question")
    assert ("pages: the source gives only a first page (973); the last page is not confirmed"
            in proposal.issues)
    assert proposal.needs_decision is True
    assert "\tPages = {973},\n" in proposal.proposed_raw


def test_an_article_number_is_not_a_lone_first_page():
    record, mapped = sources("FiedGloc12")  # PubMed alone gives "335"; the DOI ends in 00335
    proposal = complete.build({"doi": "10.3389/fpsyg.2012.00335"}, record, mapped)
    assert change(proposal, "pages") == complete.FieldChange("pages", None, "335", "pubmed", "filled")
    assert proposal.needs_decision is False
    record, _ = sources("KoelEtal16")  # Crossref's article-number field
    assert record["article-number"] == "19741" and "page" not in record
    proposal = complete.build({"doi": "10.1038/srep19741"}, record)
    assert change(proposal, "pages") == complete.FieldChange("pages", None, "19741", "crossref", "filled")


def test_typed_pages_that_one_source_states_in_full_are_kept():
    record, mapped = sources("Knut07")
    typed = dict(fields_of(LIBRARY["Knut07"]), doi="10.1519/r-505011.1")
    proposal = complete.build(typed, record, mapped)
    assert change(proposal, "pages") == complete.FieldChange("pages", "973--978", "973--978", "typed", "kept")
    assert [u for u in proposal.unfilled if u.field == "pages"] == []
    # The typed journal name is the record's up to a leading "The": not contradicted, so kept.
    assert change(proposal, "journal").kind == "kept"
    assert "\tJournal = {Journal of Strength and Conditioning Research},\n" in proposal.proposed_raw


def test_a_field_no_source_states_is_listed():
    record, _ = sources("AlyTurk16")  # Crossref has no page for this article
    assert "page" not in record and "article-number" not in record
    proposal = complete.build({"doi": "10.1073/pnas.1518931113"}, record)
    assert unfilled(proposal, "pages") == complete.Unfilled("pages", "pages: no source record states it", {})
    assert "Pages" not in proposal.proposed_raw


def test_issue_numbers_are_compared_as_numbers_and_written_without_a_leading_zero():
    from cdlbib import correction_proposals as cp
    record, mapped = sources("PigeEtal12")
    assert record["issue"] == "09" and mapped["issue"] == "9"
    assert cp.confirm_issue(record, mapped, None) == {"issue": "9", "sources": ["crossref", "pubmed"], "lookup": None}
    assert cp.confirm_issue(record, None, None) == {"issue": "9", "sources": ["crossref"], "lookup": None}
    proposal = complete.build({"doi": "10.4088/jcp.11r07586"}, record, mapped)
    assert change(proposal, "number") == complete.FieldChange("number", None, "9", "crossref+pubmed", "filled")
    assert "\tNumber = {9},\n" in proposal.proposed_raw  # as the library's PigeEtal12 has it
    assert [u for u in proposal.unfilled if u.field == "number"] == []


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
        "\tTitle = {Scipy 1.0: fundamental algorithms for scientific computing in {Python}},\n"
        "\tVolume = {17},\n"
        "\tYear = {2020}}")


# --- what the person typed --------------------------------------------------------------------

WITH_DOI = ["MoheEtal14", "Zoll90", "Game62", "AlyTurk16", "ChenEtal21",
            "FiedGloc12", "PigeEtal12", "LindEtal21"]


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


def test_a_typed_year_is_kept_but_not_confirmed_when_the_sources_leave_the_year_open():
    record, _ = sources("LindEtal21")  # print 2021, online 2020, and no PubMed record to decide
    typed = dict(fields_of(LIBRARY["LindEtal21"]), year="2020")
    proposal = complete.build(typed, record)
    assert change(proposal, "year") == complete.FieldChange("year", "2020", "2020", "typed", "question")
    assert unfilled(proposal, "year") == complete.Unfilled(
        "year", "year: print and online years differ and no rule selects one",
        {"crossref published-print": "2021", "crossref published-online": "2020",
         "crossref issued": "2020", "crossref published": "2020"})
    assert ("year: print and online years differ and no rule selects one; the typed year 2020 is kept "
            "and is not confirmed") in proposal.issues
    assert proposal.needs_decision is True
    assert "\tYear = {2020}}" in proposal.proposed_raw
    assert proposal.key_proposed == "LindEtal20"  # follows the typed year, which the issue says is open


def test_a_typed_value_the_format_checker_would_rewrite_is_shown_in_house_form():
    record, mapped = sources("MoheEtal14")
    typed = dict(fields_of(LIBRARY["MoheEtal14"]), title="Inhibition Drives Early Feature-Based Attention",
                 pages="315-324")
    proposal = complete.build(typed, record, mapped)
    assert change(proposal, "title") == complete.FieldChange(
        "title", "Inhibition Drives Early Feature-Based Attention",
        "Inhibition drives early feature-based attention", "house format", "changed")
    assert change(proposal, "pages") == complete.FieldChange("pages", "315-324", "315--324", "house format", "changed")
    assert proposal.proposed_raw == LIBRARY["MoheEtal14"]
    assert proposal.needs_decision is False


def test_the_librarys_own_entry_is_rewritten_where_the_format_checker_would_rewrite_it():
    record, mapped = sources("Schr03")  # the frozen entry's journal has stray braces
    proposal = complete.build(fields_of(LIBRARY["Schr03"]), record, mapped)
    assert change(proposal, "journal") == complete.FieldChange(
        "journal", "{European} Archives of Psychiatry and Clinical Neuroscience",
        "European Archives of Psychiatry and Clinical Neuroscience", "house format", "changed")
    assert proposal.proposed_raw == DIFFERS["Schr03"]


def test_typed_values_the_format_checker_accepts_are_kept_byte_for_byte():
    record, mapped = sources("MoheEtal14")
    typed = dict(fields_of(LIBRARY["MoheEtal14"]), doi="https://doi.org/10.1177/0956797613511257",
                 author="Jeff Moher and B M Lakshmanan and H E Egeth and J B Ewen")
    proposal = complete.build(typed, record, mapped)
    assert change(proposal, "doi") == complete.FieldChange(
        "doi", "https://doi.org/10.1177/0956797613511257", "https://doi.org/10.1177/0956797613511257", "typed", "kept")
    assert change(proposal, "author") == complete.FieldChange(
        "author", "Jeff Moher and B M Lakshmanan and H E Egeth and J B Ewen",
        "Jeff Moher and B M Lakshmanan and H E Egeth and J B Ewen", "typed", "kept")


def test_a_doi_filled_from_the_record_is_written_as_the_record_gives_it():
    record, _ = sources("CleeMcCl91")
    proposal = complete.build(RECORDS["CleeMcCl91"]["typed"], record)
    assert change(proposal, "doi").proposed == record["DOI"] == proposal.doi


# --- non-ASCII letters are written in the library's LaTeX form ---------------------------------

def _styles(accent):
    """How often the frozen library writes one symbol accent in each brace style."""
    counts = {"{\\Xl}": 0, "\\X{l}": 0, "{\\X{l}}": 0, "\\Xl": 0}
    for outer, inner in re.findall(r"(\{?)\\" + re.escape(accent) + r"(\{?)\\?[A-Za-z]", FROZEN):
        counts["{\\X{l}}" if outer and inner else "{\\Xl}" if outer else "\\X{l}" if inner else "\\Xl"] += 1
    return counts


def test_one_brace_style_for_every_accent_the_librarys_most_common():
    # The evidence: counts in the frozen library, by accent and in total.
    counts = {accent: _styles(accent) for accent in "\"'`~^"}
    assert counts['"'] == {"{\\Xl}": 85, "\\X{l}": 45, "{\\X{l}}": 39, "\\Xl": 12}
    assert counts["'"] == {"{\\Xl}": 66, "\\X{l}": 82, "{\\X{l}}": 24, "\\Xl": 23}
    assert counts["`"] == {"{\\Xl}": 3, "\\X{l}": 0, "{\\X{l}}": 0, "\\Xl": 0}
    assert counts["~"] == {"{\\Xl}": 7, "\\X{l}": 4, "{\\X{l}}": 0, "\\Xl": 0}
    assert counts["^"] == {"{\\Xl}": 1, "\\X{l}": 0, "{\\X{l}}": 1, "\\Xl": 1}
    total = {style: sum(c[style] for c in counts.values()) for style in counts['"']}
    assert total == {"{\\Xl}": 162, "\\X{l}": 131, "{\\X{l}}": 64, "\\Xl": 36}
    assert complete._accent('"', "o") == '{\\"o}'  # the one place the style is set
    assert complete.latex_text("Glöckner Hervé à ñ ô") == 'Gl{\\"o}ckner Herv{\\\'e} {\\`a} {\\~n} {\\^o}'
    # letter accents and letters as the library has them: {\c{s}}, {\u{g}}, {\H{o}}, {\o}, {\l}, {\ss}
    for form in ("{\\c{s}}", "{\\v{r}}", "{\\u{g}}", "{\\H{o}}", "{\\o}", "{\\l}", "{\\ss}", "{\\AA}", "{\\ae}"):
        assert form in FROZEN
    assert complete.latex_text("ş č ğ ő ø ł ß Å æ") == (
        "{\\c{s}} {\\v{c}} {\\u{g}} {\\H{o}} {\\o} {\\l} {\\ss} {\\AA} {\\ae}")
    # punctuation: the library has --- on 33 title lines and no em dash, `` on 42 and curly quotes on 5
    assert sum("---" in line for line in FROZEN.split("\n") if line.startswith("\tTitle")) == 33
    assert "\u2014" not in FROZEN
    assert complete.latex_text("O\u2019Brien \u2014 a\u2013b \u201cq\u201d x\u00a0y") == "O'Brien --- a--b ``q'' x y"
    assert complete.latex_text("plain ASCII {B}ayes") == "plain ASCII {B}ayes"


def _mapped_characters():
    import unicodedata
    letters = [unicodedata.normalize("NFC", base + mark) for mark in complete._ACCENTS
               for base in "aeiounczsgylrtdhAEIOUNCZSGYLRTDH"]
    return [c for c in letters if len(c) == 1] + list(complete._LETTERS)


def test_every_latex_form_survives_the_house_formatters_and_reads_back_the_same():
    from cdlbib import helpers
    from cdlbib.verification import normalized
    characters = _mapped_characters()
    assert len(characters) > 150 and "ö" in characters and "Š" in characters and "ß" in characters
    lowered = []
    for char in characters:
        word = ("Ab" + char + "cd") if char.islower() else (char + "bcd")
        written = complete.latex_text(word)
        assert written.isascii(), char
        assert normalized(written) == normalized(word), char  # the verifier reads the same letter
        author = "A B " + written + " and C D Smith"
        assert helpers.reformat_author(author) == author, char
        title = "Memory in " + ("{" + written + "}" if char.isupper() else written) + " of rats"
        assert helpers.format_title(title) == title, char
        journal = "Journal of " + written + " Studies"
        if helpers.format_journal_name(journal) != journal:
            lowered.append(char)
    # The journal formatter keeps every LaTeX form as given. (Until 2026-10-06 it lower-cased
    # an accented capital that begins a word, and the command \\H; a command and what it
    # marks is now a token the word rules do not re-case: helpers.name_tokens.)
    assert lowered == []
    # A dot above is not in the table: the author formatter drops the period of {\.Z}.
    assert helpers.reformat_author("A {\\.Z}urek") != "A {\\.Z}urek"
    assert complete.latex_text("Żurek İlhan") == "Żurek İlhan" and complete.not_in_latex("Żurek İlhan") == ["Ż", "İ"]


def test_the_format_checker_accepts_the_latex_forms(tmp_path):
    from cdlbib.helpers import check_bib
    names = ["Müller", "Hervé", "Peña", "Çelik", "Šimić", "Güroğlu", "Erdős", "Ørsted", "Łukasz", "Öztürk"]
    written = [complete.latex_text(name) for name in names]
    entries = [
        "@article{" + "".join(c for c in name if c.isascii())[:4] + "20,\n\tAuthor = {A B " + form + "},\n"
        "\tJournal = {Psychological Science},\n\tTitle = {Memory and the work of {" + form + "}},\n\tYear = {2020}}"
        for name, form in zip(names, written)]
    bib = tmp_path / "accents.bib"
    bib.write_text("\n\n".join(entries) + "\n", encoding="utf-8")
    errors, _ = check_bib(str(bib), verbose=False)
    assert {field for found in errors.values() for field in found} <= {"ID"}  # keys aside, nothing is rewritten


def test_a_letter_whose_latex_form_the_formatter_would_change_is_kept_and_asked_about():
    # Game62's saved record with the family name replaced by one that has a dot above.
    record, mapped = sources("Game62")
    record["author"][0]["family"] = "Żurek"
    proposal = complete.build({"doi": record["DOI"]}, record)
    assert change(proposal, "author") == complete.FieldChange("author", None, "P A Żurek", "crossref", "question")
    assert proposal.issues == ["author: no LaTeX form is known for 'Ż' (LATIN CAPITAL LETTER Z WITH DOT ABOVE); "
                               "written as the source has it"]
    assert proposal.needs_decision is True and "\tAuthor = {P A Żurek},\n" in proposal.proposed_raw
    # Typed: the value stays as typed (it was "A {\.Z}urek", which the checker turned into "{\Z}urek").
    typed = dict(fields_of(LIBRARY["Game62"]), author="P A Żurek")
    kept = complete.build(typed, record)
    assert change(kept, "author") == complete.FieldChange("author", "P A Żurek", "P A Żurek", "typed", "kept")
    assert "\tAuthor = {P A Żurek},\n" in kept.proposed_raw
    # A journal name with an accented capital at the start of a word. The journal formatter
    # lower-cased that letter's LaTeX form until 2026-10-06, so the name was written as the
    # source has it and asked about; the formatter now keeps the form, and the name is written
    # in LaTeX with nothing to ask.
    record, _ = sources("Game62")
    record["container-title"] = ["Österreichische Zeitschrift für Soziologie"]
    journal = complete.build({"doi": record["DOI"]}, record)
    # ("F{\\"u}r": the journal formatter capitalises every word that is not on its list.)
    assert change(journal, "journal") == complete.FieldChange(
        "journal", None, '{\\"O}sterreichische Zeitschrift F{\\"u}r Soziologie', "crossref", "filled")
    assert journal.issues == [] and journal.needs_decision is False


def test_every_accented_source_string_in_the_fixtures_survives_the_latex_form():
    from cdlbib.verification import normalized
    records = [item["crossref"]["record"] for item in RECORDS.values()] + [RETRACTED["body"]["message"]]
    strings = sorted({text for record in records for person in record.get("author", [])
                      for text in (person.get("given"), person.get("family")) if text and not text.isascii()})
    assert "Glöckner" in strings and "İlhan" in strings and "Slavič" in strings and len(strings) == 14
    for text in strings:
        written = complete.latex_text(text)
        assert normalized(written) == normalized(text)  # the verifier reads back the same letters
        if text == "İlhan":  # a dot above has no form that survives the author formatter
            assert written == text and complete.not_in_latex(text) == ["İ"]
        else:
            assert written.isascii() and complete.not_in_latex(text) == []


def test_a_character_with_no_latex_form_is_left_and_named():
    title = "Oscillatory γ-band (30–70 {Hz}) activity induced by a visual search task in humans"
    assert "\tTitle = {" + title + "},\n" in FROZEN  # a title of the frozen library
    assert complete.latex_text(title) == title.replace("–", "--")
    assert complete.not_in_latex(title) == ["γ"]


def test_a_typed_accented_letter_is_shown_in_latex_form():
    record, mapped = sources("FiedGloc12")
    typed = dict(fields_of(LIBRARY["FiedGloc12"]), author="S Fiedler and A Glöckner")
    proposal = complete.build(typed, record, mapped)
    assert change(proposal, "author") == complete.FieldChange(
        "author", "S Fiedler and A Glöckner", 'S Fiedler and A Gl{\\"o}ckner', "house format", "changed")
    assert proposal.proposed_raw == DIFFERS["FiedGloc12"]
    # The library's own spelling of the same letter, typed, is kept as typed.
    kept = complete.build(fields_of(LIBRARY["FiedGloc12"]), record, mapped)
    assert change(kept, "author").kind == "kept" and kept.proposed_raw == LIBRARY["FiedGloc12"]


# --- fix round 2 ----------------------------------------------------------------------------------

def test_a_retraction_banner_is_not_part_of_the_title():
    record = deepcopy(RETRACTED["body"]["message"])
    assert record["title"] == ["RETRACTED: Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive "
                               "developmental disorder in children"]
    title = "Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children"
    proposal = complete.build({"doi": "10.1016/S0140-6736(97)11096-0"}, record)
    assert change(proposal, "title") == complete.FieldChange("title", None, title, "crossref", "filled")
    assert "RETRACTED" not in proposal.proposed_raw
    assert proposal.issues[0].startswith("The article was retracted") and proposal.needs_decision is True
    typed = complete.build({"doi": "10.1016/S0140-6736(97)11096-0", "title": title}, record)
    assert change(typed, "title") == complete.FieldChange("title", title, title, "typed", "kept")
    assert typed.needs_decision is True


def test_complete_says_whether_the_entry_has_its_key_and_required_fields():
    record, mapped = sources("MoheEtal14")
    whole = complete.build({"doi": "10.1177/0956797613511257"}, record, mapped)
    assert whole.complete is True and whole.needs_decision is False
    # A corporate author: no byline, so no key either.
    scipy = complete.build({"doi": "10.1038/s41592-019-0686-2"},
                           deepcopy(RECORDS["corporate-author"]["crossref"]["record"]))
    assert scipy.proposed_raw.startswith("@article{" + complete.NO_KEY + ",")
    assert scipy.complete is False and scipy.needs_decision is True
    # The year left open by the sources.
    record, _ = sources("LindEtal21")
    year = complete.build(fields_of(LIBRARY["LindEtal21"]) | {"year": ""}, record)
    assert "Year" not in year.proposed_raw and year.complete is False and year.needs_decision is True
    # A single source suffices, including a title printed in Title Case.
    record, _ = sources("MoheEtal14")
    title = complete.build({"doi": "10.1177/0956797613511257"}, record)
    assert change(title, "title").kind == "filled" and title.complete is True
    # Pages are not required: an entry without them is complete.
    record, _ = sources("AlyTurk16")
    pages = complete.build({"doi": "10.1073/pnas.1518931113"}, record)
    assert "Pages" not in pages.proposed_raw and pages.complete is True and pages.needs_decision is False


def test_page_labels_keep_the_sources_capitals():
    # The library writes such pages with a capital: CutlGram88 has S82--S90, GapiEtal11 S70--S74.
    assert "\tPages = {S82--S90},\n" in FROZEN and "\tPages = {S70--S74},\n" in FROZEN
    assert not re.search(r"(?m)^\tPages = \{s\d", FROZEN)
    for printed, written in (("S82-S90", "S82--S90"), ("S82-90", "S82--S90"), ("S82-9", "S82--S89"),
                             ("e1160-e1167", "e1160--e1167"), ("R45-R50", "R45--R50")):
        record, _ = sources("MoheEtal14")  # the saved record with its page replaced
        record["page"] = printed
        proposal = complete.build({"doi": "10.1177/0956797613511257"}, record)
        assert change(proposal, "pages").proposed == written, printed


def test_a_page_that_is_the_article_number_is_not_a_lone_first_page():
    record, _ = sources("KoelEtal16")
    record["page"] = record["article-number"]  # some records carry the number in both
    proposal = complete.build({"doi": "10.1038/srep19741"}, record)
    assert change(proposal, "pages") == complete.FieldChange("pages", None, "19741", "crossref", "filled")


def test_a_family_name_is_written_whole_as_the_source_gives_it():
    # The library's own multi-word surnames, given back as a source would give them.
    for family, written in (("La Joie", "R {La Joie}"), ("Van der Linden", "R {Van der Linden}"),
                            ("Lopes da Silva", "R {Lopes da Silva}"), ("van der Meer", "R van der Meer"),
                            ("Fernández del Río", "R {Fern{\\'a}ndez del R{\\'i}o}")):
        record, _ = sources("Game62")
        record["author"] = [{"given": "Renaud", "family": family}]
        proposal = complete.build({"doi": record["DOI"]}, record)
        assert change(proposal, "author").proposed == written
    assert "R {La Joie}" in FROZEN and "{Van der Linden}" in FROZEN and "{Lopes da Silva}" in FROZEN
    assert "M A A van der Meer" in FROZEN


def test_a_family_name_the_source_may_have_split_wrongly_is_a_question():
    # Crossref's record of the NumPy paper (saved for the lookup tests) gives the given names
    # "Jaime Fernández" and the family name "del Río"; the library has "Fern{\'{a}}ndez del R{\'{i}}o".
    responses = json.loads((ROOT / "tests/fixtures/completion/responses.json").read_text(encoding="utf-8"))
    record = next(r["response"]["body"]["message"] for r in responses
                  if r["request"][0] == "https://api.crossref.org/works/10.1038%2Fs41586-020-2649-2")
    person = next(p for p in record["author"] if p["family"] == "del Río")
    assert person["given"] == "Jaime Fernández"
    proposal = complete.build({"doi": "10.1038/s41586-020-2649-2"}, record)
    author = change(proposal, "author")
    assert author.kind == "question" and "J F del R{\\'i}o" in author.proposed
    assert ("author: the source gives the given names 'Jaime Fernández' and the family name 'del Río'; "
            "the family name may be 'Fernández del Río'") in proposal.issues
    assert proposal.needs_decision is True and proposal.complete is False
    # The other particle names of that record are not asked about.
    assert sum(issue.startswith("author: the source gives the given names") for issue in proposal.issues) == 1
    assert "S J van der Walt" in author.proposed and "M H van Kerkwijk" in author.proposed


@pytest.mark.parametrize("corroborating", [
    {}, {"DOI": "10.1177/0956797613511257", "title": ["x"]},
    {"DOI": "10.1177/0956797613511257", "title": ["x"], "published": {}, "author": []},
    {"DOI": "10.1177/0956797613511257", "title": ["x"], "published": {"date-parts": [[2014]]}, "author": "J Moher"},
    {"DOI": "10.1177/0956797613511257", "title": [None], "published": {"date-parts": [[2014]]}, "author": []},
])
def test_a_corroborating_record_that_is_not_in_the_expected_form_is_set_aside(corroborating):
    record, _ = sources("MoheEtal14")
    proposal = complete.build({"doi": "10.1177/0956797613511257"}, record, corroborating)
    assert "The PubMed record is not in the expected form and was not used" in proposal.issues
    assert proposal.record_source == "crossref"


def test_reasons_are_plain_words_when_a_part_of_the_record_is_missing():
    record, _ = sources("MoheEtal14")
    record["title"] = [None]
    record["issued"] = None
    proposal = complete.build({"doi": "10.1177/0956797613511257"}, record)
    assert unfilled(proposal, "title").reason == "title: the record's title is not in the expected form"
    assert all("NoneType" not in u.reason and "object" not in u.reason for u in proposal.unfilled)


# --- fix round 3 ----------------------------------------------------------------------------------

def test_sources_that_disagree_are_an_issue_and_need_a_decision():
    # Real: Crossref spells the last author of MeyeEtal88 "Kounois", PubMed "Kounios".
    record, mapped = sources("MeyeEtal88")
    assert record["author"][-1]["family"] == "Kounois" and mapped["author"][-1]["family"] == "Kounios"
    proposal = complete.build({"doi": record["DOI"]}, record, mapped)
    assert unfilled(proposal, "author").reason == "author: sources disagree"
    assert proposal.issues == ["author: sources disagree (crossref: David E. Meyer; David E. Irwin; Allen M. Osman; "
                               "John Kounois; pubmed: D E Meyer; D E Irwin; A M Osman; J Kounios)"]
    assert proposal.needs_decision is True
    # Pages (not a required field): the saved MoheEtal14 records with PubMed's pages replaced.
    record, mapped = sources("MoheEtal14")
    mapped["page"] = "100-110"
    pages = complete.build({"doi": record["DOI"]}, record, mapped)
    assert unfilled(pages, "pages").source_values == {"crossref": "315-324", "pubmed": "100-110"}
    assert pages.issues == ["pages: sources disagree (crossref: 315-324; pubmed: 100-110)"]
    assert pages.complete is True and pages.needs_decision is True


def test_a_name_damaged_at_the_source_is_kept_and_asked_about():
    # Crossref's record 10.1249/00005768-198704001-00264 (saved for the lookup tests) has the
    # family name "O??Reilly": the apostrophe was lost at the publisher.
    responses = json.loads((ROOT / "tests/fixtures/completion/responses.json").read_text(encoding="utf-8"))
    record = next(r["response"]["body"]["message"] for r in responses
                  if r["request"][0] == "https://api.crossref.org/works/10.1249%2F00005768-198704001-00264")
    assert [p["family"] for p in record["author"]][2] == "O??Reilly"
    proposal = complete.build({"doi": record["DOI"]}, deepcopy(record))
    assert change(proposal, "author") == complete.FieldChange(
        "author", None, "W R Frontera and C N Meredith and K O??Reilly and H Knuttgen and W J Evans", "crossref",
        "question")
    assert proposal.issues == ["author: the source text looks damaged ('O??Reilly'); written as the source has it"]
    assert proposal.needs_decision is True and proposal.complete is False


def test_more_retraction_banners_and_a_notices_title():
    for banner in ("Retracted Article: ", "[RETRACTED] ", "REMOVED: ", "RETRACTED: RETRACTED: ", "WITHDRAWN: "):
        record = deepcopy(RETRACTED["body"]["message"])
        del record["updated-by"]
        record["title"] = [banner + record["title"][0].removeprefix("RETRACTED: ")]
        proposal = complete.build({"doi": "10.1016/S0140-6736(97)11096-0"}, record)
        assert change(proposal, "title").proposed.startswith("Ileal-lymphoid-nodular hyperplasia"), banner
        assert proposal.issues[0] == (f"The publisher's title begins with \"{banner.strip()}\"; it is not added "
                                      "without a decision") and proposal.needs_decision is True
    record = deepcopy(RETRACTED["body"]["message"])
    del record["updated-by"]
    record["title"] = ["Retraction: " + record["title"][0].removeprefix("RETRACTED: ")]
    notice = complete.build({"doi": "10.1016/S0140-6736(97)11096-0"}, record)
    assert notice.issues[0] == ("The record's title reads as a retraction or removal notice; it is not added "
                                "without a decision") and notice.needs_decision is True
    # Not banners: a title that only begins with the word.
    for title in ("Withdrawn but not forgotten: memory for retracted articles", "Retracted articles and their afterlife"):
        assert complete._BANNER.match(title) is None and complete._NOTICE_TITLE.match(title) is None


def test_the_placeholder_typed_as_a_key_is_not_a_key():
    record, mapped = sources("LindEtal21")  # no byline, so no key can be made
    proposal = complete.build({"ID": complete.NO_KEY, "doi": "10.1017/S1355617720001009"}, record, mapped)
    assert proposal.key_typed is None and proposal.complete is False and proposal.needs_decision is True
    record, mapped = sources("MoheEtal14")
    made = complete.build({"ID": complete.NO_KEY, "doi": "10.1177/0956797613511257"}, record, mapped)
    assert made.key_typed is None and made.key_proposed == "MoheEtal14" and made.proposed_raw == LIBRARY["MoheEtal14"]


def test_a_given_name_that_may_hold_part_of_the_family_name_is_a_question_for_the_librarys_particles():
    # The library's bylines have family names beginning da, de, del, van, van der, von, …
    for form in ("F H {Lopes da Silva}", "{van der Walt}", "{de Haan}", "{von Stein}"):
        assert form in FROZEN
    for given, family, kind in (("Fernando Lopes", "da Silva", "question"), ("Fernando", "Lopes da Silva", "filled"),
                                ("Jan Willem", "de Vries", "question"), ("Stéfan J.", "van der Walt", "filled"),
                                ("Matthijs A. A.", "van der Meer", "filled"), ("Astrid", "von Stein", "filled")):
        record, _ = sources("Game62")
        record["author"] = [{"given": given, "family": family}]
        proposal = complete.build({"doi": record["DOI"]}, record)
        assert change(proposal, "author").kind == kind, (given, family)


def test_page_forms_the_pagination_rule_does_not_know_are_left_unfilled():
    # A roman-numeral range and a range with letter suffixes: the library has one roman page
    # value and no suffix-letter range, and the pagination rule accepts neither.
    assert len(re.findall(r"(?m)^\tPages = \{[ivxlcdm]+(?:--|\})", FROZEN)) == 1
    assert not re.search(r"(?m)^\tPages = \{\d+[A-Za-z]", FROZEN)
    for printed in ("iii-xii", "12S-19S"):
        record, _ = sources("MoheEtal14")
        record["page"] = printed
        proposal = complete.build({"doi": record["DOI"]}, record)
        assert unfilled(proposal, "pages") == complete.Unfilled(
            "pages", "pages: unsupported source locator", {"crossref": printed})


def test_house_question_says_when_a_typed_value_was_kept_because_the_formatter_would_change_it():
    # For every caller of _house_form (build, and the arXiv builder): when it returns the typed
    # value unchanged, _house_question gives the reason to raise, or None.
    # The journal formatter keeps the LaTeX form of an accented capital since 2026-10-06, so
    # this name is put in LaTeX and there is nothing to raise.
    typed = "Österreichische Zeitschrift Für Soziologie"
    assert complete._house_form("journal", typed) == '{\\"O}sterreichische Zeitschrift F{\\"u}r Soziologie'
    assert complete._house_question("journal", typed) is None
    # The author formatter still drops the period of a dot above ({\\.Z}): such a typed value
    # is kept as typed, with the reason.
    assert complete._house_form("author", "P A Żurek") == "P A Żurek"
    assert complete._house_question("journal", "Psychological Science") is None
    assert complete._house_question("author", 'S Fiedler and A Gl{\\"o}ckner') is None


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

def test_a_book_chapter_record_is_not_built_as_an_article_and_the_type_is_named():
    # Chapters are built since milestone M7 (tests/test_complete_types.py), as @incollection.
    # A typed @article is never turned into one: the record fills nothing.
    record, mapped = sources("book-chapter")
    assert record["type"] == "book-chapter"
    typed = {"ENTRYTYPE": "article", "doi": "10.4324/9781315782379-49"}
    proposal = complete.build(typed, record, mapped)
    assert proposal.unsupported == "book-chapter" and proposal.entry_type == "article"
    assert proposal.proposed_raw is None and proposal.changes == [] and proposal.unfilled == []
    assert proposal.issues == ["A record of type book-chapter is not built as an entry of type article; "
                               "the entry is left as typed"]
    assert proposal.needs_decision is False
    # With no typed type, the record's own type is built.
    assert complete.build({"doi": "10.4324/9781315782379-49"}, record, mapped).entry_type == "incollection"


def test_a_preprint_record_is_not_built_by_the_article_builder():
    record, mapped = sources("preprint")
    assert record["type"] == "posted-content" and record["subtype"] == "preprint"
    proposal = complete.build({"doi": "10.1101/511782"}, record, mapped)
    assert proposal.unsupported == "posted-content" and proposal.proposed_raw is None
    assert proposal.issues == ["A record of type posted-content is not built automatically; the entry is left as typed"]


def test_a_typed_entry_that_is_not_an_article_is_not_built():
    record, mapped = sources("MoheEtal14")
    for kind in ("book", "phdthesis", "techreport", "misc", "inbook"):
        proposal = complete.build({"ENTRYTYPE": kind, "ID": "MoheEtal14", "doi": "10.1177/0956797613511257"},
                                  record, mapped)
        assert proposal.unsupported == kind and proposal.entry_type == kind
        assert proposal.proposed_raw is None
        assert proposal.issues == [f"An entry of type {kind} is not built automatically; the entry is left as typed"]
    # A type the builder makes (M7), typed over a record of another type: nothing is filled.
    proposal = complete.build({"ENTRYTYPE": "inproceedings", "ID": "MoheEtal14", "doi": "10.1177/0956797613511257"},
                              record, mapped)
    assert proposal.unsupported == "journal-article" and proposal.entry_type == "inproceedings"
    assert proposal.proposed_raw is None
    assert proposal.issues == ["A record of type journal-article is not built as an entry of type inproceedings; "
                               "the entry is left as typed"]


def test_an_erratum_record_is_refused_with_the_reason():
    record, mapped = sources("erratum")
    assert record["title"] == ["Author Correction: SciPy 1.0: fundamental algorithms for scientific computing in Python"]
    assert record["update-to"][0]["type"] == "correction"
    with pytest.raises(CompletionRefused) as refused:
        complete.build({"doi": "10.1038/s41592-020-0772-5"}, record, mapped)
    assert isinstance(refused.value, CdlbibError)
    assert str(refused.value) == ("The record 10.1038/s41592-020-0772-5 is a correction of "
                                  "10.1038/s41592-019-0686-2, not the article itself; cite the article")


def test_a_retracted_article_is_named_and_needs_a_decision():
    record = deepcopy(RETRACTED["body"]["message"])
    assert record["DOI"] == "10.1016/s0140-6736(97)11096-0"
    assert [(u["type"], u["DOI"]) for u in record["updated-by"]] == [
        ("correction", "10.1016/s0140-6736(04)15715-2"), ("retraction", "10.1016/s0140-6736(10)60175-4")]
    proposal = complete.build({"doi": "10.1016/S0140-6736(97)11096-0"}, record)
    assert proposal.issues[0] == ("The article was retracted (the retraction notice: "
                                  "10.1016/s0140-6736(10)60175-4); it is not added without a decision")
    assert "Source flags an update/correction/retraction relationship" in proposal.issues
    assert proposal.needs_decision is True
    assert proposal.proposed_raw is not None and "\tJournal = {The Lancet},\n" in proposal.proposed_raw
    # The record gives initials without periods ("AJ"), which the byline helper refuses.
    assert unfilled(proposal, "author").reason == "Undotted capital initials are ambiguous: AJ"


def test_an_erratum_message_reads_properly():
    record, _ = sources("erratum")
    record["update-to"][0]["type"] = "erratum"  # Crossref's other name for the same kind of notice
    with pytest.raises(CompletionRefused) as refused:
        complete.build({"doi": "10.1038/s41592-020-0772-5"}, record)
    assert str(refused.value).startswith("The record 10.1038/s41592-020-0772-5 is an erratum of ")


# A record whose parts are not in the form Crossref documents. Each is the saved MoheEtal14
# record with one part replaced; the builder says which part it could not read.
@pytest.mark.parametrize("part, value, field, reason", [
    ("author", "Moher J", "author", "author: the record's author is not in the expected form"),
    ("author", [{"given": ["Jeff"], "family": "Moher"}], "author", "author: the record's author is not in the expected form"),
    ("container-title", "Psychological Science", "journal",
     "journal: the record's container-title is not in the expected form"),
    ("page", 315, "pages", "pages: the record's page is not in the expected form"),
    ("volume", 25, "volume", "volume: the record's volume is not in the expected form"),
    ("title", "Inhibition Drives Early Feature-Based Attention", "title",
     "title: the record's title is not in the expected form"),
    ("published-print", {"date-parts": "2014"}, "year", "year: the record's published-print is not in the expected form"),
])
def test_a_malformed_part_of_a_record_is_an_unfilled_field_with_the_reason(part, value, field, reason):
    record, _ = sources("MoheEtal14")
    record[part] = value
    if field == "year":
        for name in ("published-online", "issued", "published"):
            del record[name]
    proposal = complete.build({"doi": "10.1177/0956797613511257"}, record)
    assert unfilled(proposal, field).reason == reason
    assert [c for c in proposal.changes if c.field == field] == []
    assert field.capitalize() + " = " not in proposal.proposed_raw


def test_a_record_with_no_title_or_no_authors_lists_them_as_missing():
    record, _ = sources("MoheEtal14")
    del record["title"], record["author"]
    proposal = complete.build({"doi": "10.1177/0956797613511257"}, record)
    assert unfilled(proposal, "title").reason == "title: no source record states it"
    assert unfilled(proposal, "author").reason == "author: no source record states it"


def test_a_record_with_no_type_is_not_built():
    record, _ = sources("MoheEtal14")
    del record["type"]
    proposal = complete.build({"doi": "10.1177/0956797613511257"}, record)
    assert proposal.unsupported == "unknown"
    assert proposal.issues == ["A record with no type is not built automatically; the entry is left as typed"]


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


def test_koel_typed_entry_uses_house_formatter_authority():
    from cdlbib.helpers import format_title
    record, mapped = sources('KoelEtal16')
    typed = fields_of(LIBRARY['KoelEtal16'])
    before = deepcopy(typed)
    item = complete.build(typed, record, mapped)
    assert typed == before
    proposed = complete._written_fields(item)
    assert proposed['title'] == format_title(typed['title'])
    assert proposed['author'] == typed['author']
    assert proposed['doi'] == typed['doi']
    assert item.key_typed == 'KoelEtal16'
