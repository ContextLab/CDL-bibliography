"""Researched values the formatter/checker used to reject or rewrite (held 2026-09-27).

verification/apply-2026-09-29-waves2-9/README.md, "Fields check_bib rejects", lists
source-backed values that stayed unapplied because bibcheck mangled or rejected them.
Every value below is frozen from that list (and from the resolution batches it cites);
no test reads the live cdl.bib. Each accepted form has a negative control showing that
the neighbouring malformed form is still rejected or still reformatted as before.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
import helpers  # noqa: E402


def journal(name):
    return helpers.format_journal_name(name)


def publisher(name):
    return helpers.format_journal_name(name, key=helpers.publisher_key, dotted_initials=True)


def address(name):
    return helpers.format_journal_name(name, key=helpers.address_key,
                                       force_caps=helpers.address_codes)


# --- pages --------------------------------------------------------------------------

@pytest.mark.parametrize("key,pages", [
    ("HeniEtal19", "ENEURO.0306-19.2019"),  # eNeuro eLocator (Crossref article number)
    ("ViveEtal10", "24ra22"),               # PubMed 20375008 'PG  - 24ra22'
    ("BrinCrag72", "28P--29P"),             # PubMed 'PG  - 28P-29P'
    ("Perr14", "i--97"),                    # Crossref roman front matter to arabic end
    ("Unde45", "i--33"),                    # Crossref 10.1037/h0093547 'i-33'
    ("Ward37", "i--64"),                    # Crossref 10.1037/h0093534 'i-64'
    ("Webb17", "i--90"),                    # Crossref 10.1037/h0093121 'i-90'
    ("Calk96", "i--56"),
    ("MullSchu94", "81--190, 257--339"),    # article printed in two parts (user default)
    ("supplement", "S43--S62"),
    ("roman", "i--xii"),
])
def test_held_pages_round_trip(key, pages):
    assert helpers.valid_pages(pages) == (True, [pages, pages]), key


@pytest.mark.parametrize("pages", [
    "ENEURO.0306-19",         # truncated eLocator
    "eneuro.0306-19.2019",    # lower-case journal code
    "24r22",                  # one-letter article type
    "24ra",                   # no article digits
    "28P--29Q",               # suffix differs
    "29P--28P",               # suffixed range runs backward
    "28P--29",                # suffix on one end only
    "97--i",                  # arabic then roman
    "I--97",                  # upper-case roman front matter is not the printed form
    "iiii--9",                # not a roman numeral
    "xii--i",                 # roman range runs backward
    "257--339, 81--190",      # parts out of order
    "81--190, 257--200",      # second part runs backward
    "81--190, 150--339",      # parts overlap
    "81--190,",               # empty part
    "81--190, e.g.",          # malformed part
    "12--3",                  # existing rule: backward range
    "IMAG.a.136--IMAG.a.140", # existing rule: article numbers are not ranges
])
def test_malformed_pages_still_rejected(pages):
    assert helpers.valid_pages(pages)[0] is False


def test_two_part_range_separator_is_normalized():
    # accepted as a valid range, but the house separator is ", " (a fixable format error)
    assert helpers.valid_pages("81-190,257-339") == (True, ["81-190,257-339", "81--190, 257--339"])


# --- authors ------------------------------------------------------------------------

@pytest.mark.parametrize("author", [
    "M J Morrell and {RNS System in Epilepsy Study Group}",  # KingEtal11
    "{DeepSeek-AI}",                                           # Deep25
    "{Qwen Team}",                                             # Qwen25, Qwen26
    "{SciPy 1.0 Contributors}",                                # VirtEtal20 as researched
    "{R Core Team}",                                           # RCor12 as printed (R 2.15 CITATION)
    "{National Center for PTSD (VA)}",
])
def test_braced_group_authors_round_trip(author):
    assert helpers.reformat_author(author) == author


def test_group_author_key():
    # an organization (a fully braced name) is ONE author keyed by the letters of its
    # successive words until 4 letters are reached (user rule 2026-09-28, resolution-plan
    # README "Organization authors in keys": "use as many organization 'words' as are
    # available, until 4 letters are achieved"): RNS (3 letters) + S(ystem) -> RNSS
    assert helpers.authors2key("M J Morrell and {RNS System in Epilepsy Study Group}", "2011") \
        == "MorrRNSS11"
    assert helpers.authors2key("{DeepSeek-AI}", "2025") == "Deep25"


# --- organizations: braced names are never split at " and " (2026-09-27) ----------------

@pytest.mark.parametrize("author,key", [
    # short first words: letters of the next words fill the part up to 4 (rule 2026-09-28)
    ("{U.S. Food and Drug Administration}", "USFo20"),            # US20a/b -> USFo20a/b
    ("{R Core Team}", "RCor20"),                                  # R12 -> RCor12
    ("{ R Core Team}", "RCor20"),                                 # the old stray-space form
    ("{SciPy 1.0 Contributors}", "SciP20"),                       # digits are not letters
    ("{A I}", "AI20"),                                            # fewer than 4 letters in all
    # a first word of 4+ letters: its first 4 letters, as before
    ("{Centers for Disease Control and Prevention}", "Cent20"),   # ContPrev23 -> Cent23
    ("{American Academy of Sleep Medicine}", "Amer20"),           # Amer23a-c (already conform)
    ("{Qwen Team}", "Qwen20"),                                    # Qwen25, Qwen26
    ("{Stan Development Team}", "Stan20"),                        # Stan13
    ("{{U.S. Food and Drug Administration}}", "USFo20"),          # the double-braced form
])
def test_organization_is_one_author_keyed_by_its_words_up_to_4_letters(author, key):
    assert helpers.split_names(author) == [author]
    assert helpers.authors2key(author, "2020") == key
    assert helpers.reformat_author(author) == author


def test_organization_with_and_round_trips():
    # HEAD formatted it as "{ U S Food and Drug Administration}", splitting the group at
    # " and " and reading "U.S." as initials; FoodAdmi20a/b carried Force for that.
    fda = "{U.S. Food and Drug Administration}"
    assert helpers.reformat_author(fda) == fda
    assert helpers.last_names_from_str(fda) == ["Administration"]
    # a person followed by an organization, and the organization first (ProjEtal18)
    assert helpers.split_names("M J Morrell and " + fda) == ["M J Morrell", fda]
    assert helpers.authors2key("{Project Jupyter} and M Bussonnier and J Forde", "2018") == "ProjEtal18"
    assert helpers.authors2key(fda + " and J Smith", "2020") == "USFoSmit20"


def test_braced_particle_surname_is_a_person_not_an_organization():
    # Real bylines (PezzEtal14-style, van der Meer): a braced surname inside a personal
    # name is not braced whole, so it is keyed and formatted as before.
    assert helpers.organization_key("M A A {van der Meer}") is None
    assert helpers.authors2key("M A {van der Meer} and A A Carey and Y Tanaka", "2010") == "vand" + "Etal10"
    assert helpers.authors2key("G Pezzulo and M A A {van der Meer} and C S Lansink and C M A Pennartz",
                               "2014") == "PezzEtal14"
    assert helpers.authors2key("A {de la Vega} and E Finn", "2021") == "delaFinn21"
    assert helpers.reformat_author("M A {van der Meer} and A A Carey") == "M A {van der Meer} and A A Carey"


def test_split_names_matches_str_split_outside_braces():
    assert helpers.split_names("A B Smith and C D Jones") == ["A B Smith", "C D Jones"]
    assert helpers.split_names("A {Smith and Jones}") == ["A {Smith and Jones}"]
    # unbalanced braces fall back to the old split
    assert helpers.split_names("A {Smith and C Jones") == ["A {Smith", "C Jones"]
    assert helpers.split_names("A Smith} and C Jones") == ["A Smith}", "C Jones"]


def test_unbraced_group_name_still_read_as_person():
    # without braces the capitals are still clumped initials (existing rule)
    assert helpers.reformat_author("RNS Study Group") == "R N S Study Group"
    # a name with a braced part is not a braced group: its initials are still split
    assert helpers.reformat_author("PC {Van Ness}") == "P C {Van Ness}"
    assert helpers.reformat_author("M.A. Smith") == "M A Smith"


def test_fully_braced():
    assert helpers.fully_braced("{RNS System in Epilepsy Study Group}")
    assert not helpers.fully_braced("{\\.I} Polat")
    assert not helpers.fully_braced("{A} {B}")
    assert not helpers.fully_braced("P C {Van Ness}")


# --- journal, publisher, address ----------------------------------------------------

FISH22 = ("Philosophical Transactions of the Royal Society of London Series {A}: "
          "Containing Papers of a Mathematical or Physical Character")


@pytest.mark.parametrize("fmt,value", [
    (journal, "{eNeuro}"),                                             # HeniEtal19
    (journal, FISH22),                                                 # Fish22
    (journal, "Proceedings of the Second Workshop on Fact Extraction and "
              "{VERification} ({FEVER})"),
    (publisher, "{PMLR}"),                                             # RangEtal14
    (publisher, "O'Reilly"),                                           # BirdEtal09
    (publisher, "O'Reilly Media"),
    (address, "La Jolla, {CA}"),                                       # BartEtal04c
])
def test_held_names_round_trip(fmt, value):
    assert fmt(value) == value


def test_name_negative_controls():
    # unbraced words follow the existing title-case rule
    assert journal("eNeuro") == "Eneuro"
    assert publisher("PMLR") == "Pmlr"
    # a caps.txt word keeps its caps.txt form even when braced differently
    assert journal("{mit} Press") == journal("MIT Press")
    # capital "A" is still the caps.txt letter; "a" opening a subtitle is too
    assert journal("Physica A") == "Physica {A}"
    assert journal("Intracranial {EEG}: a Guide for Cognitive Neuroscientists") == \
        "Intracranial {EEG}: {A} Guide for Cognitive Neuroscientists"
    # "a" ending a name is not an article
    assert journal("Physica a") == "Physica {A}"
    # a lower-case letter after the apostrophe is not raised
    assert publisher("Charles Scribner's Sons") == "Charles Scribner's Sons"
    assert publisher("O'reilly") == "O'reilly"
    # a state code after the city is still a state code; an all-capital city word too
    assert address("La Jolla, CA") == "La Jolla, {CA}"
    assert address("Baton Rouge, La") == "Baton Rouge, {LA}"


def test_held_values_pass_check_bib(tmp_path):
    bib = tmp_path / "held.bib"
    bib.write_text("""@article{MorrRNSS11,
\tAuthor = {M J Morrell and {RNS System in Epilepsy Study Group}},
\tJournal = {Neurology},
\tPages = {81--190, 257--339},
\tTitle = {Responsive cortical stimulation for the treatment of medically intractable partial epilepsy},
\tYear = {2011}}

@article{Heni19,
\tAuthor = {M Henin},
\tJournal = {{eNeuro}},
\tPages = {ENEURO.0306-19.2019},
\tTitle = {A test title},
\tYear = {2019}}

@article{Vive10,
\tAuthor = {M Viventi},
\tJournal = {Philosophical Transactions of the Royal Society of London Series {A}: Containing Papers of a Mathematical or Physical Character},
\tPages = {24ra22},
\tTitle = {Another test title},
\tYear = {2010}}

@book{Bird09,
\tAddress = {La Jolla, {CA}},
\tAuthor = {S Bird},
\tPublisher = {O'Reilly},
\tTitle = {Natural language processing with {Python}},
\tYear = {2009}}

@inproceedings{Rang14,
\tAuthor = {A Ranganath},
\tBooktitle = {Artificial Intelligence and Statistics},
\tPages = {i--97},
\tPublisher = {{PMLR}},
\tTitle = {Black box variational inference},
\tYear = {2014}}

@article{Brin72,
\tAuthor = {G S Brindley},
\tJournal = {Journal of Physiology},
\tPages = {28P--29P},
\tTitle = {Third test title},
\tYear = {1972}}

@misc{USFo20a,
\tAuthor = {{U.S. Food and Drug Administration}},
\tHowpublished = {\\url{https://www.accessdata.fda.gov/cdrh_docs/reviews/DEN200033.pdf}},
\tTitle = {{DEN200033} de novo decision summary: {NightWare} kit (digital therapy device)},
\tYear = {2020}}

@misc{USFo20b,
\tAuthor = {{U.S. Food and Drug Administration}},
\tHowpublished = {\\url{https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/denovo.cfm?id=DEN200033}},
\tTitle = {Device classification under section 513(f)(2) (de novo) --- {DEN200033}},
\tYear = {2020}}

@misc{Cent23,
\tAuthor = {{Centers for Disease Control and Prevention}},
\tHowpublished = {\\url{https://www.cdc.gov/media/releases/2023/s0810-US-Suicide-Deaths-2022.html}},
\tTitle = {Provisional suicide deaths in the {United States}, 2022},
\tYear = {2023}}

@manual{RCor12,
\tAddress = {Vienna, Austria},
\tAuthor = {{R Core Team}},
\tOrganization = {{R Foundation for Statistical Computing}},
\tTitle = {{R}: a language and environment for statistical computing},
\tYear = {2012}}
""")
    errors, _ = helpers.check_bib(str(bib), verbose=False)
    assert errors == {}


def test_check_bib_wants_the_organization_keys(tmp_path):
    # FoodAdmi20a/b (HEAD, with Force) without Force: the author now passes, and the old
    # keys are corrected to the organization rule's USFo20a/USFo20b (rule 2026-09-28);
    # R12 (the 2026-09-27 first-word rule) is corrected to RCor12.
    bib = tmp_path / "org.bib"
    bib.write_text("""@misc{FoodAdmi20a,
\tAuthor = {{U.S. Food and Drug Administration}},
\tTitle = {{DEN200033} de novo decision summary: {NightWare} kit (digital therapy device)},
\tYear = {2020}}

@misc{FoodAdmi20b,
\tAuthor = {{U.S. Food and Drug Administration}},
\tTitle = {Device classification under section 513(f)(2) (de novo) --- {DEN200033}},
\tYear = {2020}}

@manual{R12,
\tAddress = {Vienna, Austria},
\tAuthor = {{R Core Team}},
\tOrganization = {{R Foundation for Statistical Computing}},
\tTitle = {{R}: a language and environment for statistical computing},
\tYear = {2012}}
""")
    errors, _ = helpers.check_bib(str(bib), verbose=False)
    assert set(errors) == {"FoodAdmi20a", "FoodAdmi20b", "R12"}
    assert {e["ID"] for e in errors.values()} == {"USFo20a", "USFo20b", "RCor12"}
    assert all(set(e) == {"ID"} for e in errors.values())   # no author correction


def test_check_bib_still_rejects_malformed_pages(tmp_path):
    bib = tmp_path / "bad.bib"
    bib.write_text("""@article{Brin72,
\tAuthor = {G S Brindley},
\tJournal = {Journal of Physiology},
\tPages = {257--339, 81--190},
\tTitle = {Third test title},
\tYear = {1972}}
""")
    with pytest.raises(Exception, match="ambiguous or incorrect"):
        helpers.check_bib(str(bib), verbose=False)


def test_statutory_section_kept_in_titles():
    # FoodAdmi20b: "section 513(f)(2)" became "513({F})(2)" (the entry carried Force for it)
    title = "Device classification under section 513(f)(2) (de novo) --- {DEN200033}"
    assert helpers.format_title(title) == title
    # negative controls: a lone lettered subsection and a letter-led designation are
    # still formatted as before
    assert helpers.format_title("Rule (f) of the code") == "Rule ({F}) of the code"
    assert helpers.format_title("Section F(2) of the code") == "Section {F}(2) of the code"
