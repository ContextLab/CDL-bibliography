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
    """Every book title and edition of cdl.bib is as the formatter writes it, except the
    entries on the pending list, which are exactly as listed. (The list held four book titles
    when the rule was made; the owner approved their change the same day and it is empty.)"""
    differing = {}
    for key, entry in LIBRARY.items():
        for name, formatter in (("booktitle", helpers.format_booktitle), ("edition", helpers.format_edition)):
            value = entry["fields"].get(name)
            if value and formatter(value) != value:
                differing[(key, name)] = (value, formatter(value))
    assert differing == {(item["key"], item["field"]): (item["value"], item["proposed"]) for item in PENDING}
    assert differing == helpers.pending_forms()
    assert sum("\\textsuperscript{" in e["fields"].get("booktitle", "") for e in LIBRARY.values()) >= 44
    assert sum("\\textsuperscript{" in e["fields"].get("edition", "") for e in LIBRARY.values()) >= 32
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


WORDS, HOUSE = "Fifth Annual Workshop", "5\\textsuperscript{th} Annual Workshop"
BOSE = "Proceedings of the %s on Computational Learning Theory"


def bose(form=WORDS, key="BoseEtal92"):
    """BoseEtal92 as the library has it, with its book title in the given form (the library
    had the words until the owner approved the house form on 2026-10-06)."""
    text = LIBRARY["BoseEtal92"]["raw"]
    assert BOSE % HOUSE in text
    return text.replace(BOSE % HOUSE, BOSE % form).replace("{BoseEtal92,", "{" + key + ",") + "\n"


def test_a_listed_entry_is_named_and_is_no_error_and_any_other_is(tmp_path, monkeypatch):
    # The mechanism, with a list of this test's own holding the entry as it stood before the
    # owner approved its change (the packaged list is empty now).
    monkeypatch.setattr(helpers, "pending_forms", lambda: {("BoseEtal92", "booktitle"): (BOSE % WORDS, BOSE % HOUSE)})
    bib = tmp_path / "some.bib"
    bib.write_text(bose() + "\n" + entries("ShafGood08"), encoding="utf-8")
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
    assert load_entries(fixed)["BoseEtal92"]["fields"]["booktitle"] == BOSE % WORDS

    # The same text under another key is not on the list: an error, with the house form.
    bib.write_text(bose(key="BoseEtal92a"), encoding="utf-8")
    errors, said = check(bib)
    assert errors["BoseEtal92a"]["booktitle"] == BOSE % HOUSE
    assert "house rule" not in said
    # A listed entry whose book title is anything but the listed text is an error too.
    bib.write_text(bose("5th Annual Workshop"), encoding="utf-8")
    errors, said = check(bib)
    assert errors == {"BoseEtal92": {"booktitle": "Proceedings of the 5\\textsuperscript{th} Annual Workshop on "
                                                  "Computational Learning Theory"}}
    # In the house form it is neither an error nor named.
    bib.write_text(bose(HOUSE), encoding="utf-8")
    assert check(bib) == ({}, check(bib)[1]) and "house rule" not in check(bib)[1]
    # With the packaged list (empty since the four entries were changed) the words are an error.
    monkeypatch.undo()
    assert helpers.pending_forms() == {}
    bib.write_text(bose(), encoding="utf-8")
    assert check(bib)[0] == {"BoseEtal92": {"booktitle": BOSE % HOUSE}}


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
    entries on the pending list (none, since the owner approved the four) are named in what
    it prints."""
    cdlbib = Path(sys.executable).parent / "cdlbib"
    done = subprocess.run([str(cdlbib), "--library", str(ROOT), "verify", "--no-citations"], capture_output=True,
                          text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    lines = done.stdout.splitlines()
    assert lines[-1] == "looks good!" and "format: looks good!" in lines
    named = [i for i, line in enumerate(lines) if "written in a form a house rule now changes" in line]
    assert len(named) == (1 if PENDING else 0)
    if PENDING:
        assert [line.split(":")[0] for line in lines[named[0] + 1:named[0] + 1 + len(PENDING)]] == [
            item["key"] for item in PENDING]


# --- long and hostile input ---------------------------------------------------------------------------

LONG = 50_000


def hostile():
    """Long inputs of the kinds that make a careless reader slow: one piece repeated, alone,
    with a tail that matches nothing, and with a character in the middle that breaks the run."""
    pieces = ("A.", "twenty-", " ", "1", "first ", "AB", "{AB}-", "30th ", "A", "Twenty-First ", "(", "th",
              "\\emph{", "{", "}", "$", "$a", "\\a[", "\\\"", "\\emph{a} ", "{{a} b} ", "\\(", "\\", "{a}{b}")
    for piece in pieces:
        text = piece * (LONG // len(piece))
        yield repr(piece), text
        yield repr(piece) + " and a tail", text + "!~"
        yield repr(piece) + " broken in the middle", text[:LONG // 2] + "#" + text[LONG // 2:]


def test_everything_reads_long_hostile_input_in_time_proportional_to_its_length():
    """Titles come from registry records and from what a person types. The tokenizer, each
    rule, each formatter and each pattern the same change relies on elsewhere takes 50,000
    characters of every hostile kind in under a quarter of a second."""
    import re
    import time
    from cdlbib import acl_review, texinstall, verification

    def tokens(text):
        try:
            return helpers.name_tokens(text)
        except helpers.Unbalanced:
            return None
    rules = {"tokens": tokens, "unformattable": helpers.unformattable,
             "book title": helpers.format_booktitle, "edition": helpers.format_edition,
             "journal": helpers.format_journal_name, "publisher": lambda text: helpers.format_journal_name(
                 text, key=helpers.publisher_key, dotted_initials=True),
             "plain ordinals": helpers._plain_ordinals, "meeting ordinals": helpers._meeting_ordinals,
             "two capitals": helpers._two_capitals, "meeting window": helpers._numbers_a_meeting,
             "ordinal_form": verification.ordinal_form, "anthology pages": acl_review.pages,
             "version": texinstall._VERSION.search, "pages": lambda text: re.fullmatch(r"\d+(?:--\d+)?", text)}
    slowest = (0.0, "", "")
    for kind, text in hostile():
        assert len(text) >= LONG - 20
        for name, rule in rules.items():
            started = time.perf_counter()
            rule(text)
            slowest = max(slowest, (time.perf_counter() - started, name, kind))
    assert slowest[0] < 0.25, slowest


def test_a_value_too_long_or_unbalanced_is_left_unchanged_and_reported(tmp_path):
    import time
    assert helpers.MAX_NAME_LENGTH == 5000
    # Too long to be a name: unchanged (a command at its start too), and said to be so.
    long_name = "\\LaTeX Proceedings of the 30th NAACL Conference" + " and" * 1300
    assert len(long_name) > helpers.MAX_NAME_LENGTH
    for formatter in (helpers.format_booktitle, helpers.format_journal_name, helpers.format_edition):
        assert formatter(long_name) == long_name
    assert helpers.unformattable(long_name) == "longer than 5000 characters"
    # At the cap itself the value is read and formatted, quickly.
    at_cap = ("\\LaTeX Proceedings of the 30th NAACL Conference" + " and" * 1300)[:helpers.MAX_NAME_LENGTH - 1].rstrip()
    started = time.perf_counter()
    written = helpers.format_booktitle(at_cap)
    assert time.perf_counter() - started < 0.25
    assert written.startswith("\\LaTeX Proceedings of the 30\\textsuperscript{th} {NAACL} Conference and and")
    # Braces or mathematics that do not balance: unchanged, never guessed at.
    for value, why in (("Proceedings of the {30th NAACL Meeting", "a brace that is never closed"),
                       ("Proceedings of the 30th} NAACL Meeting", "a brace that closes nothing"),
                       ("The $5 NAACL Workshop", "mathematics that is never closed"),
                       ("The \\(x NAACL Workshop", "mathematics that is never closed"),
                       ("\\emph{" * 3 + "NAACL Workshop", "a brace that is never closed")):
        assert helpers.unformattable(value) == why
        for formatter in (helpers.format_booktitle, helpers.format_journal_name, helpers.format_edition):
            assert formatter(value) == value
    assert helpers.unformattable("An escaped \\{ brace, \\$5 and \\} are characters") is None
    # The format check reports such a field, as it reports a page range it cannot read.
    bib = tmp_path / "some.bib"
    text = entries("BauEtal17").replace("Booktitle = {{IEEE} Conference", "Booktitle = {\\emph{IEEE Conference")
    assert text != entries("BauEtal17")
    bib.write_text(text.replace("Pattern Recognition},", "Pattern Recognition}},"), encoding="utf-8")
    assert helpers.unformattable(load_entries(bib)["BauEtal17"]["fields"]["booktitle"]) is None   # balanced: read
    bib.write_text(entries("BauEtal17").replace("Booktitle = {{IEEE} Conference", "Booktitle = {$IEEE Conference"),
                   encoding="utf-8")
    with pytest.raises(Exception, match="cannot be formatted: \nBauEtal17: booktitle: mathematics that is never closed"):
        check(bib)


# --- LaTeX in a name is not re-cased, and no text of a name is mistaken for the formatter's own ------

FROZEN = load_entries(ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib")
COMMAND = __import__("re").compile(r"\\[A-Za-z]+")


def publisher(name):
    return helpers.format_journal_name(name, key=helpers.publisher_key, dotted_initials=True)


def address(name):
    return helpers.format_journal_name(name, key=helpers.address_key, force_caps=helpers.address_codes)


FORMATTERS = {"booktitle": helpers.format_booktitle, "edition": helpers.format_edition,
              "journal": helpers.format_journal_name, "publisher": publisher, "address": address}


def opaque_tokens(text):
    return [part for is_opaque, part in helpers.name_tokens(text) if is_opaque]


def balanced(text):
    depth = 0
    for char in text:
        depth += (char == "{") - (char == "}")
        if depth < 0:
            return False
    return depth == 0


@pytest.mark.parametrize("given, written", [
    # Text that looks like a placeholder is text: it is neither replaced nor does it replace anything.
    ("{qzq0} ABCD Research", "{qzq0} {ABCD} Research"),
    ("{qzq1} Workshop on NLP and {qzq0} Systems", "{qzq1} Workshop on {NLP} and {qzq0} Systems"),
    # The name of a command keeps its case.
    ("\\LaTeX Workshop", "\\LaTeX Workshop"), ("The \\TeX Book of ABCD", "The \\TeX Book of {ABCD}"),
    ("\\O resund Studies", "\\O Resund Studies"),
    # A command of two letters or more keeps its braced arguments as given; so does mathematics.
    ("Studies in \\emph{Drosophila} Biology", "Studies in \\emph{Drosophila} Biology"),
    ("Proceedings of the \\textit{ACM} Meeting", "Proceedings of the \\textit{ACM} Meeting"),
    ("On $L_p$ Spaces and ABCD", "On $L_p$ Spaces and {ABCD}"),
    ("The 30\\textsuperscript{th} and the 31st Meeting", "The 30\\textsuperscript{th} and the 31\\textsuperscript{st} Meeting"),
    # A letter whose lower case is two characters, beside a command: no brace is gained.
    ("\\emph{İ} \\LaTeX Workshop", "\\emph{İ} \\LaTeX Workshop"),
    # A group that holds a group, optional arguments, mathematics with groups and spaces, a hyphen in an argument.
    ("{{MixedCASE} OuterCASE} Workshop", "{{MixedCASE} OuterCASE} Workshop"),
    ("\\textcolor[RGB]{0,0,0}{MiXeD Title} Workshop", "\\textcolor[RGB]{0,0,0}{MiXeD Title} Workshop"),
    ("$L_{AB} + Q$ Workshop", "$L_{AB} + Q$ Workshop"), ("\\(a + B\\) Spaces", "\\(a + B\\) Spaces"),
    ("\\emph{A-B} Workshop", "\\emph{A-B} Workshop"),
    # The ordinal and acronym rules read plain words only: not what a command or a group holds.
    ("\\emph{the 30th NAACL Meeting} of the 31st ACL Meeting",
     "\\emph{the 30th NAACL Meeting} of the 31\\textsuperscript{st} {ACL} Meeting"),
    ("{The Second Workshop on NLP} and the Third Workshop on NLP",
     "{The Second Workshop on NLP} and the 3\\textsuperscript{rd} Workshop on {NLP}"),
    ("$30th$ Meeting of the 30th Society", "$30th$ Meeting of the 30\\textsuperscript{th} Society"),
    # An accented capital at the start of a word is kept (the word rules lower-cased it).
    ('{\\"O}sterreichische NLP Zeitschrift', '{\\"O}sterreichische {NLP} Zeitschrift'),
    ("AT\\&T Labs Workshop", "{AT\\&T} Labs Workshop"),
    # A braced group with a capital beside an unbraced part of a hyphenated word.
    ("Workshop on Tongue-{NLP} Systems", "Workshop on Tongue-{NLP} Systems"),
    # Accents and caps-list words are the rules' own, as before.
    ('S{\\"{a}}mtliche Werke', 'S{\\"{a}}mtliche Werke'), ("{Ieee} Workshop", "{IEEE} Workshop"),
    ("Harvard {University} Press", "Harvard University Press"),
])
def test_commands_mathematics_and_braced_capitals_are_kept_as_given(given, written):
    assert helpers.format_booktitle(given) == written
    assert helpers.format_booktitle(written) == written
    assert [t for t in opaque_tokens(written) if not t.startswith("\\textsuperscript")] == [
        t for t in opaque_tokens(given) if not t.startswith("\\textsuperscript")]
    assert balanced(written)


def test_the_journal_formatter_keeps_a_command_too():
    # The fault was the shared formatter's: every caller has the fix.
    assert helpers.format_journal_name("\\LaTeX Journal of \\emph{Drosophila}") == "\\LaTeX Journal of \\emph{Drosophila}"
    assert publisher("\\TeX Users Group") == "\\TeX Users Group"
    assert helpers.format_journal_name("Journal of $H_2O$ Research") == "Journal of $H_2O$ Research"
    assert helpers.format_journal_name("Proceedings of the 30\\textsuperscript{th} Meeting") == (
        "Proceedings of the 30\\textsuperscript{th} Meeting")


def library_values():
    for name, library in (("cdl.bib", LIBRARY), ("frozen", FROZEN)):
        for key, entry in library.items():
            for field, formatter in FORMATTERS.items():
                value = entry["fields"].get(field)
                if value:
                    yield name, key, field, value, formatter


def test_properties_of_the_formatters_over_every_value_of_both_libraries():
    """Every Booktitle, Edition, Journal and Publisher of cdl.bib and of the frozen library
    fixture, through its formatter: formatting twice is formatting once; no command changes
    its name; balanced braces stay balanced; no brace is doubled; and every value of cdl.bib
    is left exactly as it is."""
    seen = 0
    for name, key, field, value, formatter in library_values():
        once = formatter(value)
        where = (name, key, field, value, once)
        seen += 1
        assert formatter(once) == once, where
        if name == "cdl.bib":
            assert once == value, where
        aliased = field in ("journal", "booktitle") and isinstance(helpers.journal_key.get(value.lower()), str)
        aliased = aliased or (field == "publisher" and isinstance(helpers.publisher_key.get(value.lower()), str))
        if not aliased:
            # (the one command a rule may add is the house ordinal's own)
            assert [c for c in COMMAND.findall(once) if c != "\\textsuperscript"] == [
                c for c in COMMAND.findall(value) if c != "\\textsuperscript"], where
        if balanced(value):
            assert balanced(once), where
        assert once.count("{{") <= value.count("{{") and once.count("}}") <= value.count("}}"), where
        if not aliased and not (field == "address" and isinstance(helpers.address_key.get(value.lower()), str)):
            # every opaque token of the value is in the result, byte for byte and in order
            assert [t for t in opaque_tokens(once) if not t.startswith("\\textsuperscript")] == [
                t for t in opaque_tokens(value) if not t.startswith("\\textsuperscript")], where
    assert seen > 13900


def test_every_title_of_both_libraries_is_read_into_tokens_and_formatted_as_before():
    """Titles go through format_title, which this change does not touch: each title of both
    libraries is readable as tokens (its braces and mathematics balance), keeps its balance,
    and a title of cdl.bib is left exactly as it is."""
    for name, library in (("cdl.bib", LIBRARY), ("frozen", FROZEN)):
        for key, entry in library.items():
            title = entry["fields"].get("title")
            if not title:
                continue
            assert helpers.unformattable(title) is None or len(title) > helpers.MAX_NAME_LENGTH, (name, key)
            once = helpers.format_title(title)
            assert balanced(once), (name, key)
            if name == "cdl.bib":
                assert once == title, (name, key)


def test_the_same_properties_hold_for_names_with_commands_put_in():
    """The library's own names with a command, mathematics or a braced capital put into them:
    what was put in comes out as it went in, and the properties above hold."""
    inserts = ("\\LaTeX", "\\emph{Homo sapiens}", "$E=mc^2$", "{NLP}", "{qzq0}", "\\textbf{ABC}", "\\O")
    names = sorted({e["fields"]["booktitle"] for e in LIBRARY.values() if e["fields"].get("booktitle")})[:120]
    for index, name in enumerate(names):
        if isinstance(helpers.journal_key.get(name.lower()), str):
            continue
        words = name.split(" ")
        insert = inserts[index % len(inserts)]
        for place in (0, len(words) // 2, len(words)):
            given = " ".join(words[:place] + [insert] + words[place:])
            if isinstance(helpers.journal_key.get(given.lower()), str):
                continue
            once = helpers.format_booktitle(given)
            assert insert in once.split(" ") or insert.split(" ")[0] in once.split(" "), (given, once)
            assert insert in once, (given, once)
            assert helpers.format_booktitle(once) == once, (given, once)
            assert COMMAND.findall(once) == COMMAND.findall(given), (given, once)
            assert balanced(once) and once.count("{{") <= given.count("{{"), (given, once)
