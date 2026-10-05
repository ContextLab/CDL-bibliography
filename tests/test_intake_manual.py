"""Manual drafts (``intake.draft_manual``): typed fields in house format, never verified.

Real operations throughout: the entry goes through the real format checker
(``helpers.check_bib`` on a one-entry file), ``complete.plan_key`` and
``complete.duplicates`` against a library file of the test's own.
"""
import pytest

from cdlbib import api, complete, intake
from cdlbib.errors import CdlbibError
from cdlbib.verification import ACCEPTED, load_entries

from conftest import ZOLL90
from intake_support import library

TYPED = {"title": "the neural basis of Imaginary things: a study", "author": "Ada Q. Example and Glöckner, Bo",
         "year": "2031", "journal": "annals of improbable lattices", "volume": "12", "pages": "45-67",
         "note": "typed by hand"}
HOUSE = ("@article{ExamGloc31,\n\tAuthor = {Ada Q Example and Bo Gl{\\\"o}ckner},\n"
         "\tJournal = {Annals of Improbable Lattices},\n\tPages = {45--67},\n"
         "\tTitle = {The neural basis of imaginary things: a study},\n\tVolume = {12},\n\tYear = {2031}}")


def test_typed_fields_are_written_in_house_format(tmp_path):
    ws = library(tmp_path / "lib", ZOLL90)
    proposal = intake.draft_manual(ws, TYPED)
    assert proposal.proposed_raw == HOUSE
    assert (proposal.manual, proposal.status, proposal.needs_decision, proposal.complete) == (True, "needs_review", True, True)
    assert proposal.status not in ACCEPTED and proposal.record_source is None and proposal.typed_raw is None
    assert (proposal.key_proposed, proposal.renames, proposal.duplicate_of) == ("ExamGloc31", {}, None)
    assert proposal.issues == [] and proposal.unfilled == [] and proposal.notes[0] == intake.NO_SOURCE
    assert {c.field: (c.typed, c.proposed, c.source, c.kind) for c in proposal.changes} == {
        "author": (TYPED["author"], 'Ada Q Example and Bo Gl{\\"o}ckner', "house format", "changed"),
        "journal": (TYPED["journal"], "Annals of Improbable Lattices", "house format", "changed"),
        "note": ("typed by hand", None, "house format", "dropped"),
        "pages": ("45-67", "45--67", "house format", "changed"),
        "title": (TYPED["title"], "The neural basis of imaginary things: a study", "house format", "changed"),
        "volume": ("12", "12", "typed", "kept"),
        "year": ("2031", "2031", "typed", "kept"),
    }
    # the text reads back as one entry, and the format checker has nothing left to change in it
    path = tmp_path / "one.bib"
    path.write_text(proposal.proposed_raw + "\n", encoding="utf-8")
    assert list(load_entries(path)) == ["ExamGloc31"]
    assert api.check_format(library(tmp_path / "one", proposal.proposed_raw)).errors == []
    assert ws.bib.read_text(encoding="utf-8") == ZOLL90 + "\n\n"  # nothing is written
    assert api.draft_manual(ws, TYPED).proposed_raw == HOUSE


def test_an_entry_already_in_house_format_is_kept_as_typed(tmp_path):
    typed = {"author": "U Zoller", "title": "A second paper on freshman chemistry", "year": "1990",
             "journal": "Journal of Research in Science Teaching"}
    proposal = intake.draft_manual(library(tmp_path / "lib"), typed)
    assert all(c.kind == "kept" and c.source == "typed" and c.typed == c.proposed for c in proposal.changes)
    assert proposal.key_proposed == "Zoll90"
    assert [u.field for u in proposal.unfilled] == ["pages", "volume"]  # expected of an article, not given


def test_duplicates_are_flagged_by_identifier_and_by_title(tmp_path):
    ws = library(tmp_path / "lib", ZOLL90, HOUSE)
    by_doi = intake.draft_manual(ws, {"title": "Typed differently", "author": "Zoller, Uri", "year": "1990",
                                      "journal": "J Res Sci Teach", "doi": "https://doi.org/10.1002/TEA.3660271011"})
    assert by_doi.duplicate_of == "Zoll90" and by_doi.needs_decision
    assert "This work is already in the library or batch as Zoll90" in by_doi.issues
    by_title = intake.draft_manual(ws, TYPED)
    assert by_title.duplicate_of == "ExamGloc31"


def test_key_collision_shows_the_renames(tmp_path):
    other = ("@article{ExamGloc31,\n\tAuthor = {A Example and B Gl{\\\"o}ckner},\n\tJournal = {Other Journal},\n"
             "\tTitle = {A different paper of the same year},\n\tYear = {2031}}")
    proposal = intake.draft_manual(library(tmp_path / "lib", other), TYPED)
    assert proposal.duplicate_of is None
    assert proposal.renames == {"ExamGloc31": "ExamGloc31a"} and proposal.key_proposed == "ExamGloc31b"
    assert proposal.proposed_raw == HOUSE.replace("{ExamGloc31,", "{ExamGloc31b,")
    assert complete.plan_key(library(tmp_path / "lib2", other), complete._completion_fields(proposal)).key == "ExamGloc31b"


def test_without_author_or_year_no_key_is_made(tmp_path):
    proposal = intake.draft_manual(library(tmp_path / "lib"), {"title": "Only a title was typed"})
    assert proposal.proposed_raw == "@article{KeyNeeded,\n\tTitle = {Only a title was typed}}"
    assert proposal.key_proposed is None and not proposal.complete and proposal.needs_decision
    assert proposal.issues == ["No citation key can be made without an author and a year"]
    assert [u.field for u in proposal.unfilled] == ["author", "journal", "pages", "volume", "year"]


def test_prefill_supplies_what_was_not_typed_and_is_marked(tmp_path):
    read = {"title": "A title read from the PDF", "doi": "10.1234/abc.5678", "year": "1999"}
    proposal = intake.draft_manual(library(tmp_path / "lib"), {"author": "Example, Ada", "year": "2001", "volume": " "},
                                   prefill=read)
    by_field = {c.field: c for c in proposal.changes}
    # the formatter lowers "PDF" in a title; the field still says where its value came from
    assert (by_field["title"].proposed, by_field["title"].source, by_field["title"].kind) == (
        "A title read from the pdf", "read from the PDF (not typed); house format", "changed")
    assert (by_field["doi"].proposed, by_field["doi"].source) == ("10.1234/abc.5678", "read from the PDF (not typed)")
    assert (by_field["year"].proposed, by_field["year"].source) == ("2001", "typed")  # what was typed wins
    assert "volume" not in by_field and proposal.key_proposed == "Exam01" and proposal.doi == "10.1234/abc.5678"


def test_other_entry_types_follow_the_same_formatter(tmp_path):
    proposal = intake.draft_manual(library(tmp_path / "lib"), {
        "title": "A book of things", "author": "Example, Ada", "year": "2001", "publisher": "MIT press",
        "address": "cambridge, ma"}, entry_type="Book")
    assert proposal.proposed_raw == ("@book{Exam01,\n\tAddress = {Cambridge, {MA}},\n\tAuthor = {Ada Example},\n"
                                     "\tPublisher = {{MIT} Press},\n\tTitle = {A book of things},\n\tYear = {2001}}")
    assert proposal.entry_type == "book" and proposal.unfilled == [] and proposal.manual
    assert proposal.unsupported is None and proposal.status == "needs_review"


def test_a_character_with_no_latex_form_is_asked_about(tmp_path):
    proposal = intake.draft_manual(library(tmp_path / "lib"), {
        "title": "Memory for 記憶 in recall", "author": "Example, Ada", "year": "2001", "journal": "Memory"})
    assert any(issue.startswith("title: no LaTeX form is known for") for issue in proposal.issues)
    assert "記憶" in proposal.proposed_raw  # left as typed, never replaced by a lookalike


def test_what_cannot_be_drafted_is_refused(tmp_path):
    ws = library(tmp_path / "lib")
    for fields, message in (({}, "nothing to draft"), ({"title": "  "}, "nothing to draft"),
                            ({"ti tle": "x"}, "Not a field name"),
                            ({"title": "A title", "force": "true"}, "cannot have a 'force' field")):
        with pytest.raises(CdlbibError, match=message):
            intake.draft_manual(ws, fields)
    with pytest.raises(CdlbibError, match="Not an entry type"):
        intake.draft_manual(ws, {"title": "A title"}, entry_type="art{icle")


def test_an_entry_the_formatter_cannot_judge_is_written_as_given_and_says_so(tmp_path):
    proposal = intake.draft_manual(library(tmp_path / "lib"), {
        "title": "A title", "author": "Example, Ada", "year": "2001", "journal": "Memory", "pages": "12-3-4-x"})
    assert any(issue.startswith("The format check could not run on this entry") for issue in proposal.issues)
    assert "\tPages = {12-3-4-x}" in proposal.proposed_raw and proposal.needs_decision and proposal.manual


# --- a value cannot change the structure of the entry -------------------------------------------

@pytest.mark.parametrize("value, why", [
    ("A title}, note = {smuggled", "closing brace with no opening brace"),
    ("A title}}\n@article{Evil,\n\tTitle = {An entry nobody checked", "closing brace with no opening brace"),
    ("A title with an {open brace", "opening brace that is never closed"),
    ("}{", "closing brace with no opening brace"),
    ("A title ending in a backslash\\", "backslash at the end"),
    ("A title @article{Evil, title = {x}} inside", "start of a BibTeX entry"),
    ("A title with a \x00 byte", "control character"),
])
def test_a_value_that_would_change_the_entrys_structure_is_refused(tmp_path, value, why):
    ws = library(tmp_path / "lib")
    typed = {"title": "A plain title", "author": "Example, Ada", "year": "2001", "journal": "Memory"}
    for name in ("title", "author", "journal", "note", "doi"):
        with pytest.raises(CdlbibError, match=f"{name}: the value has .*{why}"):
            intake.draft_manual(ws, dict(typed, **{name: value}))
    with pytest.raises(CdlbibError, match=why):
        intake.draft_manual(ws, typed, prefill={"volume": value})
    assert intake.structure_problem("A {B}alanced title with {\\\"o} and 100\\% and an @ sign") is None
    assert ws.bib.read_text(encoding="utf-8") == ""


def test_the_rendered_text_reads_back_as_exactly_the_checked_fields(tmp_path):
    ws = library(tmp_path / "lib")
    proposal = intake.draft_manual(ws, dict(TYPED, title="Braces {A}nd \"quotes\", commas, = signs and @ signs"))
    path = tmp_path / "one.bib"
    path.write_text(proposal.proposed_raw + "\n", encoding="utf-8")
    (entry,) = load_entries(path).values()
    fields = {k: v for k, v in entry["fields"].items() if k not in ("ENTRYTYPE", "ID")}
    good = complete._completion_fields(proposal)
    assert fields == good and set(fields) == {"author", "journal", "pages", "title", "volume", "year"}
    # the proof itself: text with a field or an entry that was not checked is refused, not repaired
    intake._proved(proposal.proposed_raw, "article", good)
    for raw, why in ((proposal.proposed_raw[:-1] + ",\n\tNote = {smuggled}}", "note"),
                     (proposal.proposed_raw + "\n\n@article{Evil,\n\tTitle = {x}}", "2 entries"),
                     (proposal.proposed_raw.replace("{2031}", "{1999}"), "year"),
                     ("@article{Broken,\n\tTitle = {x", "does not read back")):
        with pytest.raises(CdlbibError, match=why):
            intake._proved(raw, "article", good)
    with pytest.raises(CdlbibError, match="entry type"):
        intake._proved(proposal.proposed_raw, "book", good)
