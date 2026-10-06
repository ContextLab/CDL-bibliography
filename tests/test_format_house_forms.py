r"""The format checker's formatter for book titles and editions (owner decisions 2026-10-06).

- Ordinals are numerals with a superscript suffix, the form the library already uses:
  ``30\textsuperscript{th}``. A plain ``30th`` becomes it wherever it stands; an ordinal
  word becomes it when it numbers a meeting; a cardinal never becomes an ordinal.
- An acronym in the title of a book or of proceedings keeps its capitals, in braces.
- The verifier's comparison reads the three spellings of an ordinal as equal.

The names below are real: container titles Crossref returns (the saved responses of
tests/fixtures/completion/) and book titles of the library. The format check is run for real
(``helpers.check_bib``, and the ``cdlbib`` command) on real files. The four entries of
cdl.bib the ordinal rule changes are held on a list (``data/pending_house_forms.json``) and
are no error until the owner approves the change of data; those tests read the live cdl.bib,
which the list is about.
"""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cdlbib import helpers
from cdlbib.verification import load_entries, normalized, ordinal_form

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = load_entries(ROOT / "cdl.bib")
PENDING = json.loads((ROOT / "src/cdlbib/data/pending_house_forms.json").read_text(encoding="utf-8"))["entries"]
SAVED = [json.loads((ROOT / "tests/fixtures/completion" / name).read_text(encoding="utf-8"))
         for name in ("type_responses.json", "rule_responses.json")]


def container_titles():
    """Every container title of the saved Crossref records of papers in proceedings."""
    found = []
    for item in SAVED[0] + SAVED[1]:
        body = item["response"].get("body")
        message = body.get("message") if isinstance(body, dict) else None
        if isinstance(message, dict) and message.get("type") == "proceedings-article":
            found += message.get("container-title") or []
    return found


# --- ordinals -------------------------------------------------------------------------------------

@pytest.mark.parametrize("given, written", [
    # Crossref's own names (10.1145/3210240.3210322, 10.18653/v1/d19-1410, 10.18653/v1/d19-6607).
    ("Proceedings of the 16th Annual International Conference on Mobile Systems, Applications, and Services",
     "Proceedings of the 16\\textsuperscript{th} Annual International Conference on Mobile Systems, Applications, "
     "and Services"),
    ("Proceedings of the Conference on Empirical Methods in Natural Language Processing and the 9th International "
     "Joint Conference on Natural Language Processing",
     "Proceedings of the Conference on Empirical Methods in Natural Language Processing and the "
     "9\\textsuperscript{th} International Joint Conference on Natural Language Processing"),
    # The four entries of the library written with an ordinal word that numbers a meeting.
    ("Proceedings of the Second Workshop on Fact Extraction and Verification ({FEVER})",
     "Proceedings of the 2\\textsuperscript{nd} Workshop on Fact Extraction and Verification ({FEVER})"),
    ("Proceedings of the Fifth Annual Workshop on Computational Learning Theory",
     "Proceedings of the 5\\textsuperscript{th} Annual Workshop on Computational Learning Theory"),
    ("Proceedings of the Twenty-Third Annual Conference of the Cognitive Science Society",
     "Proceedings of the 23\\textsuperscript{rd} Annual Conference of the Cognitive Science Society"),
    ("Fourth Annual {USENIX} {Tcl/Tk} Workshop", "4\\textsuperscript{th} Annual {USENIX} {Tcl/Tk} Workshop"),
    # Each suffix, and the teens.
    ("21st Century Education: {A} Reference Handbook", "21\\textsuperscript{st} Century Education: {A} Reference Handbook"),
    ("Proceedings of the 22nd Annual International Conference on Mobile Computing and Networking",
     "Proceedings of the 22\\textsuperscript{nd} Annual International Conference on Mobile Computing and Networking"),
    ("Proceedings of the 53rd Annual Meeting of the Association for Computational Linguistics",
     "Proceedings of the 53\\textsuperscript{rd} Annual Meeting of the Association for Computational Linguistics"),
    ("Proceedings of the 11th Symposium", "Proceedings of the 11\\textsuperscript{th} Symposium"),
    ("Proceedings of the 112th Meeting", "Proceedings of the 112\\textsuperscript{th} Meeting"),
    ("Proceedings of the Eleventh International Conference on Machine Learning",
     "Proceedings of the 11\\textsuperscript{th} International Conference on Machine Learning"),
    ("Proceedings of the twenty first annual meeting of the Cognitive Science Society",
     "Proceedings of the 21\\textsuperscript{st} Annual Meeting of the Cognitive Science Society"),
    ("Proceedings of the Thirtieth Annual Conference of the Cognitive Science Society",
     "Proceedings of the 30\\textsuperscript{th} Annual Conference of the Cognitive Science Society"),
])
def test_an_ordinal_is_written_as_a_numeral_with_a_superscript_suffix(given, written):
    assert helpers.format_booktitle(given) == written
    assert helpers.format_booktitle(written) == written                        # and stays so
    assert ordinal_form(normalized(given)) == ordinal_form(normalized(written))  # the verifier reads them as equal


@pytest.mark.parametrize("name", [
    # Book titles of the library whose ordinal word is part of the wording (KrolSund03, Hara96).
    "The Handbook of Second Language Acquisition",
    "Computer Networking and Scholarly Communication in the Twenty-First-Century University",
    # A meeting whose own name begins with an ordinal word: the next word is not one that names a meeting.
    "Proceedings of the Second Language Research Forum",
    "Proceedings of the Fifth Berkeley Symposium on Mathematical Statistics and Probability",
    # Cardinals: no ordinal is made of one.
    "The Thirty Years War", "Proceedings of the 30 Annual Conference", "Twenty Lectures on Algorithmic Game Theory",
    "Thirty Workshop Papers",
    # A numeral with the wrong suffix is not an ordinal anyone can vouch for.
    "Proceedings of the 3th Workshop", "Proceedings of the 22th Conference", "Proceedings of the 11st Meeting",
])
def test_no_ordinal_is_made_where_there_is_none(name):
    assert helpers.format_booktitle(name) == helpers.format_journal_name(name) == name
    assert "textsuperscript" not in helpers.format_booktitle(name)


def test_the_three_spellings_of_an_ordinal_compare_equal_and_a_wrong_suffix_does_not():
    spellings = ["Proceedings of the Thirtieth Annual Conference", "Proceedings of the 30th Annual Conference",
                 "Proceedings of the 30\\textsuperscript{th} Annual Conference"]
    assert {ordinal_form(normalized(s)) for s in spellings} == {"proceedings of the 30th annual conference"}
    # ordinal_form reads the house form itself, on text that normalized() has not been through.
    assert ordinal_form("the 30\\textsuperscript{th} and the twenty-third") == "the 30th and the 23rd"
    assert ordinal_form("the 3\\textsuperscript{th}") == "the 3th" != ordinal_form("the third")
    assert ordinal_form("thirty") == "thirty"
    assert [helpers.house_ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111, 112)] == [
        "1\\textsuperscript{st}", "2\\textsuperscript{nd}", "3\\textsuperscript{rd}", "4\\textsuperscript{th}",
        "11\\textsuperscript{th}", "12\\textsuperscript{th}", "13\\textsuperscript{th}", "21\\textsuperscript{st}",
        "22\\textsuperscript{nd}", "23\\textsuperscript{rd}", "101\\textsuperscript{st}", "111\\textsuperscript{th}",
        "112\\textsuperscript{th}"]


@pytest.mark.parametrize("given, written", [
    ("Second", "2\\textsuperscript{nd}"), ("2nd", "2\\textsuperscript{nd}"), ("third", "3\\textsuperscript{rd}"),
    ("Twenty-first", "21\\textsuperscript{st}"), ("11th", "11\\textsuperscript{th}"),
    ("2\\textsuperscript{nd}", "2\\textsuperscript{nd}"),
    ("Rev. and expanded", "Rev. and expanded"),      # HeatEtal93, the one edition of the library that is no ordinal
    ("2", "2"), ("Two", "Two"), ("3th", "3th"),      # a cardinal, and a wrong suffix, are left as written
    ("Revised 2nd", "Revised 2\\textsuperscript{nd}"),
    # An ordinal with nothing but the word for an edition after it is the ordinal alone.
    ("Second edition", "2\\textsuperscript{nd}"), ("2nd ed.", "2\\textsuperscript{nd}"),
    ("3\\textsuperscript{rd} Edition", "3\\textsuperscript{rd}"),
    ("Revised 2nd edition", "Revised 2\\textsuperscript{nd} edition"), ("2 edition", "2 edition"),
    # A library catalogue's older abbreviation ("2d ed.", "3d ed."); "12d" and "4d" abbreviate nothing.
    ("2d ed.", "2\\textsuperscript{nd}"), ("3d ed", "3\\textsuperscript{rd}"), ("22d ed.", "22\\textsuperscript{nd}"),
    ("12d ed.", "12d ed."), ("4d ed", "4d ed"), ("Rev. ed.", "Rev. ed."),
])
def test_an_edition_is_written_as_the_library_writes_it(given, written):
    assert helpers.format_edition(given) == written and helpers.format_edition(written) == written


# --- acronyms -------------------------------------------------------------------------------------

@pytest.mark.parametrize("given, written", [
    # Crossref's names as deposited (10.1109/cvpr.2017.354; 10.18653/v1/d19-6607, with its capitals).
    ("2017 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)",
     "2017 {IEEE} Conference on Computer Vision and Pattern Recognition ({CVPR})"),
    ("Proceedings of the Second Workshop on Fact Extraction and VERification (FEVER)",
     "Proceedings of the 2\\textsuperscript{nd} Workshop on Fact Extraction and {VERification} ({FEVER})"),
    # Crossref's book title of 10.1007/978-3-319-10590-1_53 (an en dash, an acronym, a year): the
    # formatter wrote "Eccv" before this rule.
    ("Computer Vision – ECCV 2014", "Computer Vision – {ECCV} 2014"),
    ("Computer Vision -- ECCV 2014", "Computer Vision -- {ECCV} 2014"),
    # All-capital and mixed forms: each keeps the capitals it is given with.
    ("Proceedings of EMNLP", "Proceedings of {EMNLP}"), ("Proceedings of ACM SIGIR", "Proceedings of {ACM} {SIGIR}"),
    ("ICML'19 Workshop on Learning", "{ICML}'19 Workshop on Learning"),
    ("NeurIPS 2019 Workshops", "{NeurIPS} 2019 Workshops"),
    ("2019 IEEE/CVF International Conference on Computer Vision (ICCV)",
     "2019 {IEEE/CVF} International Conference on Computer Vision ({ICCV})"),
    # Forms the library has, given without their braces.
    ("Proceedings of the 23rd ACM National Conference", "Proceedings of the 23\\textsuperscript{rd} {ACM} National Conference"),
    ("Proceedings of the 11th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining",
     "Proceedings of the 11\\textsuperscript{th} {ACM} {SIGKDD} International Conference on Knowledge Discovery and "
     "Data Mining"),
    ("5th IEEE/ACM International Workshop on Grid Computing",
     "5\\textsuperscript{th} {IEEE/ACM} International Workshop on Grid Computing"),
    ("Fourth Annual USENIX Tcl/Tk Workshop", "4\\textsuperscript{th} Annual {USENIX} {Tcl/Tk} Workshop"),
    ("Proceedings of AAAI-94", "Proceedings of {AAAI}-94"),
    ("Proceedings of the 15th ACM Conference on Embedded Network Sensor Systems (SenSys)",
     "Proceedings of the 15\\textsuperscript{th} {ACM} Conference on Embedded Network Sensor Systems ({SenSys})"),
    # Parts of a hyphenated word, and a compound caps.txt does not list whole.
    ("Proceedings of NAACL-HLT", "Proceedings of {NAACL}-{HLT}"),
    ("2019 IEEE/CVF Conference on Computer Vision", "2019 {IEEE/CVF} Conference on Computer Vision"),
    ("Workshop on Tongue-NLP Systems", "Workshop on Tongue-{NLP} Systems"),
    # A name with capitals inside it keeps them.
    ("Essays in Honor of James McGaugh", "Essays in Honor of James {McGaugh}"),
])
def test_an_acronym_keeps_its_capitals_in_braces(given, written):
    assert helpers.format_booktitle(given) == written
    assert helpers.format_booktitle(written) == written
    # the braces (and the spelling of an ordinal) are the only difference: no letter is changed
    assert ordinal_form(normalized(given)) == ordinal_form(normalized(written))


@pytest.mark.parametrize("name, written", [
    # Ordinary words: one capital each, hyphenated or not.
    ("Human-Computer Interaction", "Human-Computer Interaction"),
    ("Advances in Neural Information Processing Systems", "Advances in Neural Information Processing Systems"),
    # A name given wholly in capitals says nothing about which words are acronyms.
    ("PROCEEDINGS OF THE FIFTH BERKELEY SYMPOSIUM", "Proceedings of the Fifth Berkeley Symposium"),
    # A caps.txt word keeps its caps.txt form, however it is given.
    ("Neurips Workshop", "{NeurIPS} Workshop"), ("NEURIPS Workshop Papers", "{NeurIPS} Workshop Papers"),
    # An elided prefix is a name, not an acronym.
    ("O'Reilly Open Source Convention", "O'Reilly Open Source Convention"),
])
def test_what_is_no_acronym_is_formatted_as_before(name, written):
    assert helpers.format_booktitle(name) == written == helpers.format_journal_name(name)


def test_a_name_the_journal_list_knows_by_an_alias_is_left_to_the_alias():
    # journal_key.xls has an alias for this name (ScheEtal02's, without its braces), and the
    # alias decides the form as before: no acronym is read in a name the list rewrites whole.
    name = ("Proceedings of the 25th Annual International ACM SIGIR Conference on Research and Development in "
            "Information Retrieval")
    assert isinstance(helpers.journal_key.get(name.lower()), str)
    assert helpers.format_booktitle(name) == helpers.format_journal_name(name) == (
        "Proceedings of the Association for Computing Machinery Conference on Research and Development in Information "
        "Retrieval")
    # The library's entry has the acronyms in braces, which the alias does not match.
    kept = LIBRARY["ScheEtal02"]["fields"]["booktitle"]
    assert "{ACM} {SIGIR}" in kept and helpers.format_booktitle(kept) == kept


def test_journals_publishers_and_addresses_are_formatted_as_before():
    # The two rules are the book title's: the formatter of the other fields is unchanged.
    assert helpers.format_journal_name("Proceedings of the 30th Annual Conference") == "Proceedings of the 30th Annual Conference"
    assert helpers.format_journal_name("Journal of NAACL Studies") == "Journal of Naacl Studies"
    assert helpers.format_journal_name("Second Language Research") == "Second Language Research"


def test_the_saved_crossref_names_of_proceedings_come_out_in_house_form():
    names = container_titles()
    assert len(names) >= 8
    for name in names:
        written = helpers.format_booktitle(name)
        assert helpers.format_booktitle(written) == written, name
        assert ordinal_form(normalized(written)) == ordinal_form(normalized(name)), name   # no word gained or lost
        assert not helpers.PLAIN_ORDINAL.search(written), name                             # no plain "16th" is left


# --- the library ----------------------------------------------------------------------------------

def test_the_library_is_in_the_new_form_but_for_the_listed_entries():
    """Every book title and edition of cdl.bib is as the formatter writes it, except the four
    book titles on the pending list, which are exactly as listed."""
    differing = {}
    for key, entry in LIBRARY.items():
        for name, formatter in (("booktitle", helpers.format_booktitle), ("edition", helpers.format_edition)):
            value = entry["fields"].get(name)
            if value and formatter(value) != value:
                differing[(key, name)] = (value, formatter(value))
    assert differing == {(item["key"], item["field"]): (item["value"], item["proposed"]) for item in PENDING}
    assert differing == helpers.pending_forms() and len(differing) == 4
    assert sum("\\textsuperscript{" in e["fields"].get("booktitle", "") for e in LIBRARY.values()) == 44
    assert sum("\\textsuperscript{" in e["fields"].get("edition", "") for e in LIBRARY.values()) == 32
    # The library has no plain "30th" in a book title and no acronym without its braces.
    assert not [k for k, e in LIBRARY.items() if helpers.PLAIN_ORDINAL.search(e["fields"].get("booktitle", ""))]
    # Two book titles have an ordinal word that numbers nothing: they are not rewritten.
    for key in ("KrolSund03", "Hara96"):
        assert helpers.format_booktitle(LIBRARY[key]["fields"]["booktitle"]) == LIBRARY[key]["fields"]["booktitle"]


def check(path, **options):
    """helpers.check_bib on a real file: (errors, what it printed)."""
    said = io.StringIO()
    with contextlib.redirect_stdout(said), contextlib.redirect_stderr(io.StringIO()):
        errors, _ = helpers.check_bib(str(path), verbose=False, **options)
    return errors, said.getvalue()


def entries(*keys):
    return "\n\n".join(LIBRARY[key]["raw"] for key in keys) + "\n"


def test_a_listed_entry_is_named_and_is_no_error_and_any_other_is(tmp_path):
    bib = tmp_path / "some.bib"
    bib.write_text(entries("BoseEtal92", "ShafGood08"), encoding="utf-8")
    errors, said = check(bib)
    assert errors == {}
    assert said.splitlines()[-2:] == [
        "1 entry is written in a form a house rule now changes; left as written, and no error, until the owner "
        "approves the change:",
        'BoseEtal92: \tbooktitle "Proceedings of the Fifth Annual Workshop on Computational Learning Theory" would be '
        '"Proceedings of the 5\\textsuperscript{th} Annual Workshop on Computational Learning Theory"']
    # Autofix leaves a listed entry as it is.
    fixed = tmp_path / "fixed.bib"
    check(bib, autofix=True, outfile=str(fixed))
    assert load_entries(fixed)["BoseEtal92"]["fields"]["booktitle"] == LIBRARY["BoseEtal92"]["fields"]["booktitle"]

    # The same text under another key is not on the list: an error, with the house form.
    bib.write_text(entries("BoseEtal92").replace("{BoseEtal92,", "{BoseEtal92a,"), encoding="utf-8")
    errors, said = check(bib)
    assert errors["BoseEtal92a"]["booktitle"] == helpers.pending_forms()[("BoseEtal92", "booktitle")][1]
    assert "house rule" not in said
    # A listed entry whose book title is anything but the listed text is an error too.
    bib.write_text(entries("BoseEtal92").replace("Fifth Annual Workshop", "5th Annual Workshop"), encoding="utf-8")
    errors, said = check(bib)
    assert errors == {"BoseEtal92": {"booktitle": "Proceedings of the 5\\textsuperscript{th} Annual Workshop on "
                                                  "Computational Learning Theory"}}
    # In the house form it is neither an error nor named.
    bib.write_text(entries("BoseEtal92").replace("Fifth Annual Workshop", "5\\textsuperscript{th} Annual Workshop"),
                   encoding="utf-8")
    assert check(bib) == ({}, check(bib)[1]) and "house rule" not in check(bib)[1]


def test_the_format_check_writes_an_edition_and_an_acronym_in_house_form(tmp_path):
    bib = tmp_path / "some.bib"
    text = entries("GelmEtal13", "BauEtal17")
    assert "Edition = {3\\textsuperscript{rd}}" in text and "Booktitle = {{IEEE} Conference on Computer Vision" in text
    bib.write_text(text, encoding="utf-8")
    assert check(bib)[0] == {}
    bib.write_text(text.replace("{3\\textsuperscript{rd}}", "{Third}").replace("{{IEEE} Conference on Computer Vision",
                                                                             "{IEEE Conference on Computer Vision"),
                   encoding="utf-8")
    assert check(bib)[0] == {"GelmEtal13": {"edition": "3\\textsuperscript{rd}"},
                             "BauEtal17": {"booktitle": LIBRARY["BauEtal17"]["fields"]["booktitle"]}}
    fixed = tmp_path / "fixed.bib"
    check(bib, autofix=True, outfile=str(fixed))
    assert {k: e["fields"] for k, e in load_entries(fixed).items()} == {k: LIBRARY[k]["fields"] for k in ("GelmEtal13", "BauEtal17")}


def test_the_command_passes_the_library_and_names_the_listed_entries(tmp_path):
    """`cdlbib verify --no-citations` on the library itself, as CI runs it: it passes, and the
    four entries are named in what it prints."""
    cdlbib = Path(sys.executable).parent / "cdlbib"
    done = subprocess.run([str(cdlbib), "--library", str(ROOT), "verify", "--no-citations"], capture_output=True,
                          text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    lines = done.stdout.splitlines()
    assert lines[-1] == "looks good!" and "format: looks good!" in lines
    start = lines.index("4 entries are written in a form a house rule now changes; left as written, and no error, "
                        "until the owner approves the change:")
    assert [line.split(":")[0] for line in lines[start + 1:start + 5]] == [item["key"] for item in PENDING]


# --- long and hostile input ---------------------------------------------------------------------------

LONG = 50_000


def hostile():
    """Long inputs of the kinds that make a careless pattern slow: one piece repeated, alone,
    with a tail that matches nothing, and with a character in the middle that breaks the run."""
    pieces = ("A.", "twenty-", " ", "1", "first ", "AB", "{AB}-", "30th ", "A", "Twenty-First ", "(", "th")
    for piece in pieces:
        text = piece * (LONG // len(piece))
        yield repr(piece), text
        yield repr(piece) + " and a tail", text + "!~"
        yield repr(piece) + " broken in the middle", text[:LONG // 2] + "#" + text[LONG // 2:]


def test_the_rules_read_long_hostile_input_in_time_proportional_to_its_length():
    """Titles come from registry records and from what a person types. Each rule added for
    ordinals and acronyms, and each pattern the same change added or relies on elsewhere, reads
    50,000 characters of every hostile kind well within a second (each takes hundredths)."""
    import re
    import time
    from cdlbib import acl_review, texinstall, verification
    rules = {"acronyms": helpers._acronym_parts, "plain ordinals": helpers._plain_ordinals,
             "meeting ordinals": helpers._meeting_ordinals, "two capitals": helpers._two_capitals,
             "meeting window": helpers._numbers_a_meeting,
             "ordinal_form": verification.ordinal_form, "anthology pages": acl_review.pages,
             "version": texinstall._VERSION.search, "pages": lambda text: re.fullmatch(r"\d+(?:--\d+)?", text)}
    slowest = (0.0, "", "")
    for kind, text in hostile():
        assert len(text) >= LONG - 20
        for name, rule in rules.items():
            started = time.perf_counter()
            rule(text)
            slowest = max(slowest, (time.perf_counter() - started, name, kind))
    assert slowest[0] < 1.0, slowest


def test_a_value_too_long_to_be_a_name_is_formatted_without_the_two_rules():
    import time
    assert helpers.MAX_RULE_LENGTH == 2000
    name = "Proceedings of the 30th NAACL Conference"
    long_name = name + " and" * 500
    assert len(long_name) > helpers.MAX_RULE_LENGTH
    assert helpers.format_booktitle(long_name) == helpers.format_journal_name(long_name)
    assert "textsuperscript" not in helpers.format_booktitle(long_name)
    assert helpers.format_edition("2nd " * 600) == "2nd " * 600
    # At the longest length the rules read, every hostile kind is formatted at once; beyond
    # it the formatter is the one every journal name already goes through.
    for kind, text in hostile():
        started = time.perf_counter()
        helpers.format_booktitle(text[:helpers.MAX_RULE_LENGTH])
        helpers.format_edition(text[:helpers.MAX_RULE_LENGTH])
        assert time.perf_counter() - started < 1.0, kind
        assert helpers.format_booktitle(text) == helpers.format_journal_name(text), kind
