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
    "{R Core Team}",                                           # RCor12 as printed
    "{National Center for PTSD (VA)}",
])
def test_braced_group_authors_round_trip(author):
    assert helpers.reformat_author(author) == author


def test_group_author_key():
    # the key follows the group author as authors2key builds it
    assert helpers.authors2key("M J Morrell and {RNS System in Epilepsy Study Group}", "2011") \
        == "MorrRNSS11"
    assert helpers.authors2key("{DeepSeek-AI}", "2025") == "Deep25"


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
""")
    errors, _ = helpers.check_bib(str(bib), verbose=False)
    assert errors == {}


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
