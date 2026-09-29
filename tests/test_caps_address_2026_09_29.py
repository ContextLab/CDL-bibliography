"""Acronyms, "\\&" compounds and state abbreviations the formatter let through (2026-09-29).

bibcheck verify passed values that break the house rules because format_journal_name
produced or kept them:

- "AT\\&T" was capitalized word by word into "At\\&t" (JuanRabi85, RabiEtal85);
- a parenthesized acronym "(COMSNETS)" was lowercased to "(comsnets)" (the capital went
  on the parenthesis), and once braced, "({comsnets})" was protected as given
  (CarvEtal22a and 14 other proceedings/journal names);
- "{ieee/acm}" was protected as given (PimeEtal19, Ande04, TardEtal08);
- "Cambridge, Mass." (Albe00) matched no address_key row (the table lists
  "cambridge, mass" without the period), so the house form "City, {ST}" was never applied.

Every input below is frozen here (the values as they stood in cdl.bib at 068fcb1, and
the forms their Crossref / Library of Congress records print); no test reads the live
cdl.bib. Each fix has a negative control: a value already in house form is unchanged.
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


# --- "\&" compounds ---------------------------------------------------------------

@pytest.mark.parametrize("given", [
    r"At\&t Technical Journal",    # JuanRabi85, RabiEtal85 at 068fcb1
    r"AT\&T Technical Journal",    # Crossref container-title (10.1002/j.1538-7305.1985.tb00439.x)
    r"{AT\&T} Technical Journal",  # house form
])
def test_att_is_an_acronym(given):
    assert journal(given) == r"{AT\&T} Technical Journal"


def test_short_ampersand_compounds_are_acronyms():
    assert journal(r"R\&D Management") == r"{R\&D} Management"


def test_free_standing_ampersand_unchanged():
    # Negative controls: "\&" between words is not a compound.
    assert publisher(r"Hermann Beyer \& S{\"{o}}hne") == r"Hermann Beyer \& S{\"{o}}hne"  # Herb91
    assert journal(r"Communication Systems \& Networks") == r"Communication Systems \& Networks"
    assert journal(r"Taylor\&Francis") == r"Taylor\&francis"  # long sides: unchanged behaviour


# --- slash compounds --------------------------------------------------------------

@pytest.mark.parametrize("given, house", [
    ("{ieee/acm} International Conference on Mining Software Repositories",
     "{IEEE/ACM} International Conference on Mining Software Repositories"),  # PimeEtal19
    ("IEEE/ACM International Conference on Mining Software Repositories",
     "{IEEE/ACM} International Conference on Mining Software Repositories"),
    ("{ieee/rsj} International Conference on Intelligent Robots and Systems",
     "{IEEE/RSJ} International Conference on Intelligent Robots and Systems"),  # TardEtal08
])
def test_slash_joined_acronyms(given, house):
    assert journal(given) == house
    assert journal(house) == house  # negative control: the house form is a fixed point


def test_slash_compound_needs_every_part_listed():
    # Negative control: "and/or" is not an acronym compound (neither part is in caps.txt);
    # it is capitalized as one word, as before.
    assert journal("Input and/or Output") == "Input And/or Output"


# --- parenthesized acronyms -------------------------------------------------------

PREFIX = r"14\textsuperscript{th} International Conference on Communication Systems \& Networks "


@pytest.mark.parametrize("given", ["({comsnets})", "(COMSNETS)", "({COMSNETS})"])
def test_comsnets(given):
    # Crossref 10.1109/comsnets53615.2022.9668473: "... NETworkS (COMSNETS)"
    assert journal(PREFIX + given) == PREFIX + "({COMSNETS})"


@pytest.mark.parametrize("given, house", [
    ("Proceedings of the 16\\textsuperscript{th} Annual International Conference on Mobile "
     "Systems, Applications, and Services ({mobisys})", "({MobiSys})"),        # TianEtal18
    ("Proceedings of the 21\\textsuperscript{st} International Workshop on Mobile Computing "
     "Systems and Applications ({hotmobile})", "({HotMobile})"),               # TianEtal20b
    ("Proceedings of the 18\\textsuperscript{th} Conference on Embedded Networked Sensor "
     "Systems ({sensys})", "({SenSys})"),                                      # LiEtal20
    ("Proceedings of the 10\\textsuperscript{th} Workshop on Algorithm Engineering and "
     "Experiments ({alenex})", "({ALENEX})"),                                  # GeisEtal08
    ("8\\textsuperscript{th} {European} Conference on Speech Communication and Technology "
     "({eurospeech})", "({Eurospeech})"),                                      # JoneEtal03
])
def test_listed_acronyms_restore_their_caps(given, house):
    out = journal(given)
    assert out.endswith(house)
    assert journal(out) == out


def test_unlisted_mixed_case_acronym_in_parentheses_is_kept():
    assert journal("Proceedings (CogSci)") == "Proceedings ({CogSci})"


def test_capital_after_opening_parenthesis():
    # BorzEtal23a: ACL Anthology and Crossref print "(Volume 3: System Demonstrations)".
    assert journal("Proceedings of the Association for Computational Linguistics "
                   "(volume 3: System Demonstrations)") == (
        "Proceedings of the Association for Computational Linguistics "
        "(Volume 3: System Demonstrations)")
    assert journal("(workshop papers)") == "(Workshop Papers)"
    # Crossref 10.21437/eurospeech.2003-463 prints "(Eurospeech 2003)"; Eurospeech is a
    # caps.txt word, braced like every caps.txt word in a venue name.
    assert journal("(Eurospeech 2003)") == "({Eurospeech} 2003)"


@pytest.mark.parametrize("name", [
    "({FEVER})",                  # ClanEtal19 house form: braced as printed
    "{npj} Science of Learning",  # printed lower case (GoldRasc19)
    "Clinical {EEG} (Electroencephalography)",
])
def test_house_forms_unchanged(name):
    # Negative controls: a braced word not in caps.txt is still kept as given.
    assert journal(name) == name


def test_listed_acronyms_in_journal_names():
    assert journal("The {febs} Journal") == "The {FEBS} Journal"  # Crossref 10.1111/febs.12253
    assert journal("Xrds: Crossroads, the {ACM} Magazine for Students") == (
        "{XRDS}: Crossroads, the {ACM} Magazine for Students")  # Crossref 10.1145/3357229
    assert journal("Proceedings of the 25\\textsuperscript{th} Annual International {ACM} "
                   "{sigir} Conference") == (
        "Proceedings of the 25\\textsuperscript{th} Annual International {ACM} {SIGIR} Conference")


def test_new_caps_entries_leave_titles_alone():
    # FEVER is deliberately not in caps.txt: format_title shares the table, and "fever" is
    # an English word.
    assert helpers.format_title("Fever and memory") == "Fever and memory"


# --- US state abbreviations --------------------------------------------------------

@pytest.mark.parametrize("given, house", [
    ("Cambridge, Mass.", "Cambridge, {MA}"),  # Albe00; LoC 12064937 260 $a 'Cambridge, Mass.'
    ("Cambridge, Mass", "Cambridge, {MA}"),
    ("Berkeley, Calif.", "Berkeley, {CA}"),
    ("New York, N.Y.", "New York, {NY}"),
    ("Pittsburgh, Penn.", "Pittsburgh, {PA}"),
    ("Evanston, Ill.", "Evanston, {IL}"),
    ("Washington, D.C.", "Washington, {DC}"),
])
def test_state_abbreviations_take_two_letter_codes(given, house):
    assert address(given) == house


@pytest.mark.parametrize("name", [
    "Cambridge, {MA}", "New York, {NY}", "La Jolla, {CA}", "London, {UK}", "Toronto",
    "Hong Kong, China",
])
def test_house_addresses_unchanged(name):
    # Negative controls.
    assert address(name) == name


def test_state_rule_is_address_only():
    # A journal is not an address: "Mass." stays a word.
    assert journal("Mass. Medical Review") == "Mass. Medical Review"


# --- check_bib end to end (real file IO) ------------------------------------------

ENTRIES = r"""@book{Albe00,
	Address = {%s},
	Author = {D Z Albert},
	Publisher = {Harvard {University} Press},
	Title = {Time and chance},
	Year = {2000}}

@article{JuanRabi85,
	Author = {B-H Juang and L R Rabiner},
	Doi = {10.1002/j.1538-7305.1985.tb00439.x},
	Journal = {%s},
	Number = {2},
	Pages = {391--408},
	Title = {A probabilistic distance measure for hidden {M}arkov models},
	Volume = {64},
	Year = {1985}}
"""


def check(tmp_path, raw):
    path = tmp_path / "a.bib"
    path.write_text(raw, encoding="utf-8")
    return helpers.check_bib(str(path), verbose=False)[0]


def test_check_bib_rejects_the_old_values(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    errors = check(tmp_path, ENTRIES % ("Cambridge, Mass.", r"At\&t Technical Journal"))
    assert errors == {"Albe00": {"address": "Cambridge, {MA}"},
                      "JuanRabi85": {"journal": r"{AT\&T} Technical Journal"}}


def test_check_bib_accepts_the_house_forms(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    assert check(tmp_path, ENTRIES % ("Cambridge, {MA}", r"{AT\&T} Technical Journal")) == {}
