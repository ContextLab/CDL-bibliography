"""Braces that protect nothing in journal, booktitle, publisher and address names (2026-09-29).

format_journal_name braced every caps.txt word, so ordinary title-case words came out
braced: "Harvard {University} Press", "{Oxford} {University} Press", "{American} Journal
of Psychology", "{European} Journal of Neuroscience". These fields are printed as given
(BibTeX styles do not change their case), so the braces protect nothing. A braced word
that is only a capital followed by lower-case letters (optionally "'s") is now written
without braces there (user decision 2026-09-29, "Correct the braces").

Braces that do protect something are kept: acronyms and all-capital words ({IEEE}, {MIT},
{AT\\&T}, {USA}, single letters and roman numerals), internal capitals ({NeuroImage},
{PLoS}, {McGraw}, {MobiSys}), deliberate lower case ({npj}), LaTeX commands and accents
(17\\textsuperscript{th}, F{\\"u}r), and a braced uncaps.txt word inside a name ("{Of}"),
which this formatter would otherwise lower-case. Article titles (format_title, sentence
case) keep their braces: there they protect proper nouns.

Every input is frozen here (values as they stood in cdl.bib at 7f3eead); no test reads
the live cdl.bib.
"""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import helpers  # noqa: E402


def journal(name):
    return helpers.format_journal_name(name)


def publisher(name):
    return helpers.format_journal_name(name, key=helpers.publisher_key, dotted_initials=True)


def address(name):
    return helpers.format_journal_name(name, key=helpers.address_key,
                                       force_caps=helpers.address_codes)


def unbraced(s):
    return s.replace("{", "").replace("}", "")


# --- removed: ordinary capitalization -------------------------------------------------

@pytest.mark.parametrize("fmt, given, house", [
    (publisher, "Harvard {University} Press", "Harvard University Press"),                # Albe00
    (publisher, "{Oxford} {University} Press", "Oxford University Press"),                # Bart32
    (publisher, "Teachers College, Columbia {University}", "Teachers College, Columbia University"),
    (publisher, "{Georg} Thieme", "Georg Thieme"),
    (publisher, "{Thomas}", "Thomas"),
    (journal, "{American} Journal of Psychology", "American Journal of Psychology"),
    (journal, "{European} Journal of Neuroscience", "European Journal of Neuroscience"),
    (journal, "{Parkinsonism} and Related Disorders", "Parkinsonism and Related Disorders"),
    (journal, "Journal of {Alzheimer's} Disease", "Journal of Alzheimer's Disease"),     # possessive
    (journal, "{Alzheimer's} and Dementia", "Alzheimer's and Dementia"),
    (journal, "Scientific {American} Mind", "Scientific American Mind"),
    (journal, "The {American} Journal of Psychology", "The American Journal of Psychology"),  # Youn61
    (journal, "The {Oxford} Handbook of Memory", "The Oxford Handbook of Memory"),
    (journal, "The {Oxford} Handbook of Human Memory", "The Oxford Handbook of Human Memory"),  # KahaEtal24
    (journal, "Proceedings of the Conference of the North {American} Chapter of the Association for "
              "Computational Linguistics: Human Language Technologies",
              "Proceedings of the Conference of the North American Chapter of the Association for "
              "Computational Linguistics: Human Language Technologies"),                    # MikoEtal13b
    (journal, "Proceedings of the 17\\textsuperscript{th} {Python} in Science Conference",
              "Proceedings of the 17\\textsuperscript{th} Python in Science Conference"),
    (journal, "8\\textsuperscript{th} {European} Conference on Speech Communication and Technology "
              "({Eurospeech})",
              "8\\textsuperscript{th} European Conference on Speech Communication and Technology "
              "(Eurospeech)"),                                                              # parenthesized
    (journal, "Perspectives on Memory Research: Essays in Honor of {Uppsala} {University's} "
              "500\\textsuperscript{th} Anniversary",
              "Perspectives on Memory Research: Essays in Honor of Uppsala University's "
              "500\\textsuperscript{th} Anniversary"),
    (journal, "On Human Memory: Evolution, Progress, and Reflections on the 30\\textsuperscript{th} "
              "Anniversary of the {Atkinson}-{Shiffrin} Model",
              "On Human Memory: Evolution, Progress, and Reflections on the 30\\textsuperscript{th} "
              "Anniversary of the Atkinson-Shiffrin Model"),                                # hyphenated
    (journal, "Journal of {Harvard} Studies", "Journal of Harvard Studies"),               # braced, not in caps.txt
])
def test_ordinary_capitalization_loses_its_braces(fmt, given, house):
    out = fmt(given)
    assert out == house
    assert unbraced(out) == unbraced(given)      # only braces change
    assert fmt(out) == out                       # stable


@pytest.mark.parametrize("fmt, plain, house", [
    # caps.txt words given lower case or unbraced are no longer braced by the formatter
    (publisher, "oxford university press", "Oxford University Press"),
    (journal, "american journal of psychology", "American Journal of Psychology"),
    (journal, "european journal of neuroscience", "European Journal of Neuroscience"),
])
def test_caps_txt_words_are_not_braced_in_names(fmt, plain, house):
    assert fmt(plain) == house


# --- kept: braces that protect something ---------------------------------------------

@pytest.mark.parametrize("fmt, value", [
    (publisher, "{MIT} Press"),                                   # acronym
    (publisher, "{SAGE} Publications"),
    (publisher, "{McGraw}-Hill"),                                 # internal capital
    (publisher, "Chapman \\& {Hall/CRC}"),
    (journal, "{IEEE} Transactions on Pattern Analysis and Machine Intelligence"),
    (journal, "{AT\\&T} Technical Journal"),                      # "\\&" acronym
    (journal, "Proceedings of the National Academy of Sciences, {USA}"),
    (journal, "{NeuroImage}"),
    (journal, "{PLoS} One"),
    (journal, "{npj} Digital Medicine"),                          # deliberate lower case
    (journal, "Philosophical Transactions of the Royal Society of London Series {B}: Biological Sciences"),
    (journal, "Archiv F{\\\"u}r Psychiatrie Und Nervenkrankheiten"),  # accent
    (journal, "K{\\\"u}nstliche Intelligenz"),
    (journal, "Fourth Annual {USENIX} {Tcl/Tk} Workshop"),
    (journal, "Proceedings of the 16\\textsuperscript{th} Annual International Conference on Mobile "
              "Systems, Applications, and Services ({MobiSys})"),
    (journal, "Studies in Memory, Volume {III}"),                 # roman numeral
    (address, "New York, {NY}"),                                  # state code
    (address, "Cambridge, {MA}"),
])
def test_protective_braces_are_kept(fmt, value):
    assert fmt(value) == value


def test_braced_uncaps_word_inside_a_name_is_kept():
    # Without its braces "Of" would be lower-cased by the uncaps.txt rule, so the braces
    # protect something; the formatter must keep them (and stay stable).
    assert helpers.unbrace_ordinary("{Of}", True) == "{Of}"
    assert helpers.unbrace_ordinary("{The}", True) == "{The}"
    assert helpers.unbrace_ordinary("{The}", False) == "The"      # first word: capitalized anyway


@pytest.mark.parametrize("word", [
    "{IEEE}", "{A}", "{III}", "{NeuroImage}", "{npj}", "{e}", "F{\\\"u}r", "{\\\"u}",
    "17\\textsuperscript{th}", "{Hall/CRC}", "{AT\\&T}", "{Oxford University}", "{Mc}Graw",
])
def test_unbrace_ordinary_leaves_other_braces(word):
    assert helpers.unbrace_ordinary(word, True) == word


@pytest.mark.parametrize("word, plain", [
    ("{University}", "University"), ("{Oxford},", "Oxford,"), ("({European}", "(European"),
    ("{Alzheimer's}", "Alzheimer's"), ("({Eurospeech})", "(Eurospeech)"),
])
def test_unbrace_ordinary_removes_ordinary_braces(word, plain):
    assert helpers.unbrace_ordinary(word, True) == plain


# --- titles are untouched ----------------------------------------------------------

@pytest.mark.parametrize("title", [
    "The {Oxford} handbook of human memory",
    "Remembering: a study in experimental and social psychology",
    "Recurrent neural network based language model for {American} speakers",
    "Semantic memory in {Alzheimer's} disease",
])
def test_article_titles_keep_their_braces(title):
    assert helpers.format_title(title) == title


def test_title_still_braces_caps_txt_proper_nouns():
    # negative control for the change: format_title still braces a caps.txt proper noun
    assert helpers.format_title("A study of european memory") == "A study of {European} memory"


# --- check_bib end to end (real file IO) ------------------------------------------

ENTRIES = r"""@book{Albe00,
	Address = {Cambridge, {MA}},
	Author = {D Z Albert},
	Publisher = {%s},
	Title = {Time and chance},
	Year = {2000}}

@article{Youn61,
	Author = {R K Young},
	Journal = {%s},
	Number = {2},
	Pages = {311--313},
	Title = {The stimulus in serial verbal learning},
	Volume = {74},
	Year = {1961}}
"""


def check(tmp_path, raw):
    path = tmp_path / "a.bib"
    path.write_text(raw, encoding="utf-8")
    return helpers.check_bib(str(path), verbose=False)[0]


def test_check_bib_rejects_braced_ordinary_words(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    errors = check(tmp_path, ENTRIES % ("Harvard {University} Press", "The {American} Journal of Psychology"))
    assert errors == {"Albe00": {"publisher": "Harvard University Press"},
                      "Youn61": {"journal": "The American Journal of Psychology"}}


def test_check_bib_accepts_the_unbraced_forms(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    assert check(tmp_path, ENTRIES % ("Harvard University Press", "The American Journal of Psychology")) == {}
