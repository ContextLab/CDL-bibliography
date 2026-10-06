"""Entry completion beyond journal articles (issue #95, milestone M7): papers in proceedings
(``@inproceedings`` from a Crossref ``proceedings-article``) and chapters (``@incollection``
from a ``book-chapter``), and the types that stay unbuilt from a Crossref record. (A book is
built from its Library of Congress record since 2026-10-06: tests/test_complete_books.py.)

Nothing here is invented. Every lookup is a real response fetched once on 2026-10-05 and
saved in tests/fixtures/completion/type_responses.json (the README beside it lists each
request); it is replayed through the real client over a real cache with a transport that
refuses every request (the ``client`` fixture of test_complete_identify.py), so
``client.requests == 0`` shows that nothing was fetched. A built entry is compared with the
same work's entry in the frozen library fixture, and each difference is spelled out in the
test that finds it: a difference is a finding, not something a rule here hides.

Why these two types and no other (``complete.KINDS``):
- the verifier accepts a Crossref record for an entry only in four pairings
  (``verification.compare_record``): article/journal-article, inproceedings/
  proceedings-article, incollection/book-chapter and book/book;
- it answers "no deterministic verifier for this field" to address, edition, series,
  school, institution, type, howpublished, organization and chapter, so an entry with one
  of them is never verified from a record (an ``editor`` field is compared with the
  record's editors since 2026-10-06: tests/test_complete_rules.py);
- the record the client keeps (``verification.RECORD_FIELDS``) has no place of publication
  and no edition.
"""
from copy import deepcopy
import inspect
import json
from pathlib import Path

import pytest

from cdlbib import complete
from cdlbib.errors import CompletionRefused
from cdlbib.verification import RECORD_FIELDS, compare_record, load_entries

from test_complete_identify import CONTACT, SAVED, TYPES, client, propose, typed_entry  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = load_entries(ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib")

ADDRESS = complete.Unfilled("address", "address: no source record states it", {})
EDITOR = complete.Unfilled("editor", "editor: no source record states it", {})


def library(key):
    """The exact text of an entry in the frozen library fixture."""
    return LIBRARY[key]["raw"]


def without(text, *names):
    """An entry's text without the lines of the named fields."""
    return "\n".join(line for line in text.splitlines() if not line.startswith(tuple(f"\t{n} = " for n in names)))


def record_of(doi):
    """The Crossref record of a saved DOI lookup, as the client cached it."""
    for item in TYPES + SAVED:
        body = item["response"].get("body")
        if isinstance(body, dict) and str((body.get("message") or {}).get("DOI", "")).lower() == doi.lower():
            return deepcopy(body["message"])
    raise KeyError(doi)


def change(proposal, name):
    return next(c for c in proposal.changes if c.field == name)


def unfilled(proposal, name):
    return next(u for u in proposal.unfilled if u.field == name)


# --- what is built, and from which record ------------------------------------------------------

def test_the_built_types_are_the_pairings_the_verifier_accepts():
    assert {name: kind.record for name, kind in complete.KINDS.items()} == {
        "article": "journal-article", "inproceedings": "proceedings-article", "incollection": "book-chapter"}
    source = inspect.getsource(compare_record)
    for name, kind in complete.KINDS.items():
        assert f'"{name}": "{kind.record}"' in source
    # A book is the verifier's fourth pairing and is not built from a Crossref record: see the tests of
    # books below. It is built from its catalogue record (book_build; tests/test_complete_books.py).
    assert '"book": "book"' in source and "book" not in complete.KINDS
    # Nothing a chapter or a paper is built with is a field the verifier cannot check.
    # (An editor field is one it checks since 2026-10-06, so a chapter's editors are built.)
    covered = {"title", "author", "year", "journal", "booktitle", "volume", "number", "pages", "publisher", "doi",
               "editor"}
    for kind in complete.KINDS.values():
        assert set(kind.built) <= covered and not set(kind.unverified) & covered
        assert all(f'"{name}"' in source for name in kind.built)
    # The record the client keeps states no place and no edition.
    assert not {"publisher-location", "edition-number", "event"} & RECORD_FIELDS


# --- papers in proceedings ---------------------------------------------------------------------

def test_a_paper_in_proceedings_is_built_byte_for_byte_as_the_library_has_it(client):
    # BauEtal17. Crossref: "2017 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)".
    record = record_of("10.1109/cvpr.2017.354")
    assert record["type"] == "proceedings-article"
    assert record["container-title"] == ["2017 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)"]
    proposal = propose(client, "10.1109/cvpr.2017.354")
    assert proposal.proposed_raw == library("BauEtal17")
    assert proposal.entry_type == "inproceedings" and proposal.unsupported is None
    assert proposal.status == "metadata_verified" and proposal.issues == [] and proposal.unfilled == []
    assert proposal.complete is True and proposal.needs_decision is False
    assert change(proposal, "booktitle") == complete.FieldChange(
        "booktitle", None, "{IEEE} Conference on Computer Vision and Pattern Recognition", "crossref", "filled")
    assert client.requests == 0


def test_proceedings_papers_differ_from_the_library_only_where_the_format_checker_differs(client):
    # XiaoEtal10: the library braces the acronym in the title; the format checker's
    # format_title, which is all the builder uses, writes "Sun".
    xiao = propose(client, "10.1109/cvpr.2010.5539970")
    assert xiao.proposed_raw == library("XiaoEtal10").replace("{SUN} database", "Sun database")
    assert xiao.status == "metadata_verified" and not xiao.needs_decision
    # NguyEtal18: the same in the title. The library writes the ordinal 16\textsuperscript{th}
    # (house rule: ordinals are numerals with a superscript suffix), and since 2026-10-06 the
    # format checker's formatter for a book title writes it so too: Crossref's "16th" is built
    # as the library has it. Crossref gives the title and the subtitle apart; they are joined
    # as the verifier joins them.
    record = record_of("10.1145/3210240.3210322")
    assert (record["title"], record["subtitle"]) == (["TYTH-Typing On Your Teeth"],
                                                     ["Tongue-Teeth Localization for Human-Computer Interface"])
    assert record["container-title"] == ["Proceedings of the 16th Annual International Conference on Mobile Systems, "
                                         "Applications, and Services"]
    nguyen = propose(client, "10.1145/3210240.3210322")
    assert "Proceedings of the 16\\textsuperscript{th} Annual International Conference" in library("NguyEtal18")
    assert nguyen.proposed_raw == library("NguyEtal18").replace("{TYTH}-typing", "Tyth-typing")
    assert nguyen.status == "metadata_verified" and nguyen.complete and not nguyen.needs_decision
    assert client.requests == 0


def test_a_typed_paper_without_a_doi_is_found_by_its_title_and_pubmed_is_not_asked(client, tmp_path):
    # The library's BauEtal17 without its DOI. Crossref's search is the one lookup: no PubMed
    # response is saved for it, so a PubMed request would be refused and fail the test.
    typed = without(library("BauEtal17"), "Doi")
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, typed)), client, client.cache)
    assert proposal.proposed_raw == library("BauEtal17") and proposal.status == "metadata_verified"
    assert change(proposal, "doi") == complete.FieldChange("doi", None, "10.1109/cvpr.2017.354", "crossref", "filled")
    assert {c.kind for c in proposal.changes if c.field != "doi"} == {"kept"}
    assert proposal.notes == ["One record matches the title, the first author and the year: 10.1109/cvpr.2017.354."]
    assert client.requests == 0


def test_the_pages_of_an_acl_anthology_paper_are_a_question_when_the_anthology_is_not_read():
    # ReimGure19. Crossref deposits 3980-3990; the Anthology and the paper give 3982--3992
    # (cdlbib.acl_review), which is what the library has. ``build`` reads no source: given the
    # Crossref record alone, the pages are Crossref's and a question. (``propose`` reads the
    # Anthology since 2026-10-06 and fills its pages: tests/test_complete_rules.py.)
    record = record_of("10.18653/v1/d19-1410")
    assert record["page"] == "3980-3990"
    assert "\tPages = {3982--3992}," in library("ReimGure19")
    proposal = complete.build({"doi": record["DOI"]}, record)
    assert change(proposal, "pages") == complete.FieldChange("pages", None, "3980--3990", "crossref", "question")
    assert proposal.issues == ["pages: 10.18653/v1/d19-1410 is an ACL Anthology paper; the Anthology's record "
                               "outranks Crossref's page range and was not read, so the pages are not confirmed"]
    assert proposal.needs_decision is True
    # The other differences from the library: the title's capitals (format_title) and "the 9th"
    # in the proceedings' name, which the library's entry omits and the formatter writes as the
    # house ordinal.
    assert proposal.proposed_raw == library("ReimGure19").replace("3982--3992", "3980--3990").replace(
        "Sentence-{BERT}: sentence embeddings using {S}iamese {BERT}-networks",
        "Sentence-bert: sentence embeddings using siamese bert-networks").replace(
        "and the International Joint", "and the 9\\textsuperscript{th} International Joint")


def test_a_paper_whose_record_has_no_date_is_not_complete(client):
    # Kais90: Crossref's record has no publication date at all.
    record = record_of("10.1109/icassp.1990.115702")
    assert record["issued"] == {"date-parts": [[None]]} and "published" not in record
    proposal = propose(client, "10.1109/icassp.1990.115702")
    assert proposal.proposed_raw == without(library("Kais90"), "Year").replace("{Kais90,", "{KeyNeeded,").replace(
        "of a signal},", "of a signal}}")
    assert unfilled(proposal, "year").reason == "year: no source record states it"
    assert proposal.complete is False and proposal.needs_decision is True and proposal.status == "needs_review"


def test_a_typed_publisher_or_address_on_a_paper_is_kept_and_the_verifier_says_what_it_cannot_check():
    record = record_of("10.1109/cvpr.2017.354")
    typed = {"ENTRYTYPE": "inproceedings", "ID": "BauEtal17", "doi": "10.1109/cvpr.2017.354", "publisher": "{IEEE}",
             "address": "Honolulu, {HI}"}
    proposal = complete.build(typed, record)
    assert change(proposal, "publisher").kind == "kept" and change(proposal, "address").kind == "kept"
    assert "\tAddress = {Honolulu, {HI}},\n" in proposal.proposed_raw and "\tPublisher = {{IEEE}},\n" in proposal.proposed_raw
    _, issues = compare_record(dict(typed, **{c.field: c.proposed for c in proposal.changes}), record)
    assert issues == ["address: no deterministic verifier for this field"]


# --- chapters ----------------------------------------------------------------------------------

def test_a_chapter_is_built_byte_for_byte_as_the_library_has_it(client):
    # BobrNorm75, one of the three chapters of the library the verifier accepts from Crossref.
    assert record_of("10.1016/b978-0-12-108550-6.50010-0")["title"] == ["SOME PRINCIPLES OF MEMORY SCHEMATA"]
    proposal = propose(client, "10.1016/b978-0-12-108550-6.50010-0")
    assert proposal.proposed_raw == library("BobrNorm75")
    assert proposal.entry_type == "incollection" and proposal.status == "metadata_verified"
    assert proposal.complete is True and proposal.needs_decision is False and proposal.issues == []
    # What the record cannot supply is listed, and is no reason for a decision. (The editor
    # is a field the builder fills when the record names one, so it is listed in its place
    # among the built fields, before the address.)
    assert proposal.unfilled == [EDITOR, ADDRESS]
    assert client.requests == 0


def test_a_chapter_whose_book_has_editors_is_built_without_them(client):
    # KahaEtal24, in The Oxford Handbook of Human Memory (edited by Kahana and Wagner). The
    # chapter's Crossref record names no editor, so none is written.
    record = record_of("10.1093/oxfordhb/9780190917982.013.2")
    assert "editor" not in record and "\tEditor = {M J Kahana and A D Wagner},\n" in library("KahaEtal24")
    assert record["container-title"] == ["The Oxford Handbook of Human Memory, Two Volume Pack"]
    proposal = propose(client, "10.1093/oxfordhb/9780190917982.013.2")
    # Against the frozen library: no editor, and no braces around Oxford and University. The
    # braces are the fixture's age: the format checker now writes both names without them.
    assert proposal.proposed_raw == without(library("KahaEtal24"), "Editor").replace(
        "{Oxford}", "Oxford").replace("{University}", "University")
    from cdlbib import helpers
    assert helpers.format_journal_name("The {Oxford} Handbook of Human Memory") == "The Oxford Handbook of Human Memory"
    assert proposal.unfilled == [EDITOR, ADDRESS]
    assert proposal.status == "metadata_verified" and proposal.complete and not proposal.needs_decision
    assert client.requests == 0


def test_typed_editors_are_kept_and_the_verifier_says_the_record_names_none(client):
    # Since 2026-10-06 the verifier compares an editor field with the record's editors. This
    # chapter's record names none, so the typed editors are kept, listed as stated by no
    # source, and the verifier says what it could not compare them with.
    proposal = complete.propose(complete.Query.from_entry(LIBRARY["KahaEtal24"]), client, client.cache)
    assert change(proposal, "editor") == complete.FieldChange(
        "editor", "M J Kahana and A D Wagner", "M J Kahana and A D Wagner", "typed", "kept")
    assert proposal.unfilled == [EDITOR, ADDRESS]
    assert proposal.status == "needs_review" and proposal.needs_decision is True
    assert ("crossref 10.1093/oxfordhb/9780190917982.013.2: editor: the citation names editors and the source "
            "record names none") in proposal.issues
    assert not [issue for issue in proposal.issues if "no deterministic verifier" in issue]
    assert client.requests == 0


def test_editors_a_record_names_are_written_in_house_form():
    # The real record of KahaEtal24 with one part added: the book's editors, as Crossref
    # deposits editors on the chapter records that carry them. Since 2026-10-06 they are
    # written, in the house name form, as the library's entry has them. (Real chapter records
    # that name their editors: tests/test_complete_rules.py.)
    record = record_of("10.1093/oxfordhb/9780190917982.013.2")
    record["editor"] = [{"given": "Michael J.", "family": "Kahana"}, {"given": "Anthony D.", "family": "Wagner"}]
    proposal = complete.build({"doi": record["DOI"]}, record)
    assert change(proposal, "editor") == complete.FieldChange(
        "editor", None, "M J Kahana and A D Wagner", "crossref", "filled")
    assert "\tEditor = {M J Kahana and A D Wagner},\n" in proposal.proposed_raw
    assert "\tEditor = {M J Kahana and A D Wagner},\n" in library("KahaEtal24")
    assert proposal.unfilled == [ADDRESS] and proposal.complete and not proposal.needs_decision
    _, issues = compare_record(dict({c.field: c.proposed for c in proposal.changes}, ENTRYTYPE="incollection"), record)
    assert issues == []


def test_a_series_number_after_a_book_title_is_not_part_of_it(client):
    # Klee56: Crossref's "Automata Studies. (AM-34)" (verification.book_title_forms).
    assert record_of("10.1515/9781400882618-002")["container-title"] == ["Automata Studies. (AM-34)"]
    proposal = propose(client, "10.1515/9781400882618-002")
    assert proposal.proposed_raw == without(library("Klee56"), "Address", "Editor").replace("{University}", "University")
    assert proposal.status == "metadata_verified" and proposal.unfilled == [EDITOR, ADDRESS]


def test_a_record_that_names_a_series_and_a_book_has_the_book_title_looked_up(client):
    # Scha03: the record does not say which of its two container titles is the book. Until 2026-10-06 the
    # book title was left unfilled ("booktitle: no single registry title"); by the owner's decision of that
    # day it is looked for, first in the book's own Crossref record (container_titles;
    # tests/test_complete_booktitle.py). That record's saved response is added to this client's cache.
    from intake_support import load_saved
    load_saved(client, "chapters.json.gz")
    record = record_of("10.1007/978-0-387-21579-2_9")
    assert record["container-title"] == ["Lecture Notes in Statistics", "Nonlinear Estimation and Classification"]
    proposal = propose(client, "10.1007/978-0-387-21579-2_9")
    assert proposal.proposed_raw == library("Scha03")
    assert change(proposal, "booktitle") == complete.FieldChange(
        "booktitle", None, "Nonlinear Estimation and Classification", "crossref (the book's own Crossref record)",
        "filled")
    assert "booktitle" not in {u.field for u in proposal.unfilled}
    # The publisher formatter turns "Springer New York" into "Springer", which is not the
    # name the verifier would compare: it is not written (the library's entry has none).
    assert unfilled(proposal, "publisher") == complete.Unfilled(
        "publisher", "publisher: formatter changes the registry name", {"crossref": "Springer New York"})
    assert proposal.complete is True and proposal.needs_decision is False and proposal.status == "metadata_verified"
    # Typed with its book title, as the library has it: every field is kept, and it is verified.
    typed = complete.propose(complete.Query.from_entry(LIBRARY["Scha03"]), client, client.cache)
    assert typed.proposed_raw == library("Scha03") and {c.kind for c in typed.changes} == {"kept"}
    assert typed.status == "metadata_verified" and typed.complete and not typed.needs_decision
    assert client.requests == 0


def test_a_publisher_name_the_formatter_respells_is_not_written(client):
    # AherBeat81: Crossref's publisher is "Springer US", which the publisher formatter writes
    # "Springer Us". The book's imprint is Plenum Press (the library's entry, confirmed from
    # the Library of Congress record bound in data/book_editions.json), which no Crossref
    # record states.
    from cdlbib import helpers
    assert helpers.format_journal_name("Springer US", key=helpers.publisher_key, dotted_initials=True) == "Springer Us"
    proposal = propose(client, "10.1007/978-1-4684-1083-9_9")
    assert proposal.proposed_raw == without(library("AherBeat81"), "Publisher")
    assert unfilled(proposal, "publisher") == complete.Unfilled(
        "publisher", "publisher: formatter changes the registry name", {"crossref": "Springer US"})
    assert proposal.status == "metadata_verified" and proposal.complete


def test_a_chapter_needs_its_book_title_not_a_journal():
    record = record_of("10.1016/b978-0-12-108550-6.50010-0")
    del record["container-title"]
    proposal = complete.build({"doi": record["DOI"]}, record)
    assert unfilled(proposal, "booktitle").reason == "booktitle: no source record states it"
    assert all(u.field != "journal" for u in proposal.unfilled)
    assert proposal.complete is False and proposal.needs_decision is True


# --- the guards, on the new types --------------------------------------------------------------

def test_a_doi_whose_record_is_a_different_chapter_fills_nothing(client, tmp_path):
    # The library's Mann24 typed with the DOI of KahaEtal24, another chapter of the same book.
    wrong = library("Mann24").replace("10.1093/oxfordhb/9780190917982.013.38", "10.1093/oxfordhb/9780190917982.013.2")
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, wrong)), client, client.cache)
    assert proposal.issues[0] == (
        "doi: the DOI 10.1093/oxfordhb/9780190917982.013.2 resolves to a different work than the typed title and "
        "authors (the record: \"Laws of Human Memory\", by Kahana, Diamond, Aka); nothing was filled from it")
    assert proposal.proposed_raw == wrong and proposal.needs_decision is True
    assert change(proposal, "doi").kind == "question"
    assert change(proposal, "title") == complete.FieldChange(
        "title", "Context reinstatement", "Laws of human memory", "crossref", "question")
    assert all(c.kind in ("kept", "question") for c in proposal.changes)
    assert proposal.status != "metadata_verified"
    assert client.requests == 0


def test_a_record_of_another_type_than_the_typed_entry_fills_nothing(client, tmp_path):
    # A CVPR paper typed as an @article (the library has such entries: GatyEtal16).
    assert LIBRARY["GatyEtal16"]["fields"]["ENTRYTYPE"] == "article"
    typed = "@article{BauEtal17,\n\tDoi = {10.1109/cvpr.2017.354}}"
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, typed)), client, client.cache)
    assert proposal.unsupported == "proceedings-article" and proposal.proposed_raw is None
    assert proposal.entry_type == "article" and proposal.typed_raw == typed and proposal.status is None
    assert proposal.issues == ["A record of type proceedings-article is not built as an entry of type article; "
                               "the entry is left as typed"]
    assert client.requests == 0


def test_a_retracted_chapter_needs_a_decision_and_a_notice_is_refused():
    record = record_of("10.1016/b978-0-12-108550-6.50010-0")
    record["updated-by"] = [{"type": "retraction", "DOI": "10.1016/retraction-notice"}]
    proposal = complete.build({"doi": record["DOI"]}, record)
    assert proposal.issues[0] == ("The work was retracted (the retraction notice: 10.1016/retraction-notice); it is "
                                  "not added without a decision")
    assert proposal.needs_decision is True and proposal.entry_type == "incollection"
    notice = record_of("10.1109/cvpr.2017.354")
    notice["update-to"] = [{"type": "retraction", "DOI": "10.1109/the-paper"}]
    with pytest.raises(CompletionRefused, match="is a retraction of 10.1109/the-paper"):
        complete.build({"doi": notice["DOI"]}, notice)


def test_a_name_damaged_at_the_source_is_asked_about_on_a_paper_too():
    record = record_of("10.1109/cvpr.2017.354")
    record["author"][0]["family"] = "O??Reilly"
    proposal = complete.build({"doi": record["DOI"]}, record)
    assert change(proposal, "author").kind == "question" and "O??Reilly" in change(proposal, "author").proposed
    assert proposal.issues == ["author: the source text looks damaged ('O??Reilly'); written as the source has it"]
    assert proposal.needs_decision is True and proposal.complete is False


# --- conference abstracts ------------------------------------------------------------------------

def test_a_meeting_abstract_deposited_as_a_proceedings_paper_is_not_taken_without_a_decision(client):
    # Not in the library: abstract 3 of the Preventing Overdiagnosis 2023 meeting (BMJ
    # Evidence-Based Medicine 28, suppl 1), which Crossref types proceedings-article.
    record = record_of("10.1136/ebm-2023-pod.3")
    assert record["type"] == "proceedings-article" and record["page"] == "A1.3-A2"
    assert record["container-title"] == ["Preventing overdiagnosis meeting abstracts"]
    assert complete._abstract_sign(record) == ("venue", "Preventing overdiagnosis meeting abstracts")
    said = ("The record 10.1136/ebm-2023-pod.3 may be a conference abstract: its venue is \"Preventing overdiagnosis "
            "meeting abstracts\". A conference abstract is not cited (house rule), so it is not taken without a "
            "decision.")
    # Its DOI was given, so its record is the record: what it looks like is said, and a person decides.
    proposal = propose(client, "10.1136/ebm-2023-pod.3")
    assert proposal.issues[0] == said and proposal.needs_decision is True
    assert proposal.status != "metadata_verified"
    assert "H T{\\\"a}htinen" in change(proposal, "author").proposed  # Tähtinen, in the library's LaTeX form
    # Found by a title search, it is never the record: a candidate, with the reason.
    fields = {"ENTRYTYPE": "article", "title": record["title"][0], "author": "L Holopainen", "year": "2023"}
    judged = complete._judged(fields, record, "crossref", "holopainen", "2023", None, set(complete.RECORD_KINDS))
    assert judged["match"] is True and judged["strict"] is False and judged["demoted"] == said
    assert client.requests == 0


def test_a_paper_in_proceedings_with_no_pages_may_be_an_abstract(client):
    # HeusMann18 (Conference on Cognitive Computational Neuroscience 2018): no pages in the record.
    proposal = propose(client, "10.32470/ccn.2018.1267-0")
    assert proposal.issues == ["The record 10.32470/ccn.2018.1267-0 may be a conference abstract: it has no pages and "
                               "no article number. A conference abstract is not cited (house rule), so it is not "
                               "taken without a decision."]
    assert proposal.needs_decision is True and unfilled(proposal, "pages").reason == "pages: no source record states it"
    # Against the library: the record gives no middle initials ("Andrew Heusser", "Jeremy
    # Manning"), states no pages (the library has the poster number PS-2B.16), and its name
    # has no "Proceedings of the" (the library's current entry has none either).
    assert proposal.proposed_raw == without(library("HeusMann18"), "Pages").replace(
        "A C Heusser and J R Manning", "A Heusser and J Manning").replace("{Proceedings of the Conference", "{Conference")


def test_a_meeting_is_what_proceedings_are_and_is_no_sign_of_an_abstract():
    # "Meeting" in a journal's name is a sign; in the name of proceedings it is not.
    record = record_of("10.1109/cvpr.2017.354")
    record["container-title"] = ["Proceedings of the 57th Annual Meeting of the Association for Computational Linguistics"]
    assert complete._abstract_sign(record) is None
    record["type"] = "journal-article"
    assert complete._abstract_sign(record)[0] == "venue"
    # A chapter's pages are not read as a sign; a book that names abstracts is.
    chapter = record_of("10.1016/b978-0-12-108550-6.50010-0")
    chapter["page"] = "131"
    assert complete._abstract_sign(chapter) is None
    chapter["container-title"] = ["Abstracts of the Psychonomic Society"]
    assert complete._abstract_sign(chapter) == ("venue", "Abstracts of the Psychonomic Society")


def test_known_gap_the_record_of_a_journal_of_vision_abstract_is_that_of_an_article(client):
    """KNOWN GAP, not closed: the Crossref record does not let the two be told apart. A
    Vision Sciences Society abstract (10.1167/15.12.782, the library's MartJohn15) and an
    article of the same journal and year (10.1167/15.11.1) have records with the same
    fields: the same type, a volume, an issue, and one page that is the end of the DOI. The
    one thing the lookups show that differs is that PubMed indexes the article and not the
    abstract, which is true of every article in a journal PubMed does not index, so it is
    no sign."""
    abstract, article = record_of("10.1167/15.12.782"), record_of("10.1167/15.11.1")
    for record in (abstract, article):
        assert record["type"] == "journal-article" and record["container-title"] == ["Journal of Vision"]
        assert record["volume"] == "15" and record["DOI"].endswith("." + record["page"])
        assert not record.get("subtype") and record["relation"] == {} and "update-to" not in record
        assert complete._abstract_sign(record) is None
    assert {k for k, v in abstract.items() if v not in ([], {}, None)} == {k for k, v in article.items() if v not in ([], {}, None)}
    built = propose(client, "10.1167/15.11.1")
    assert built.record_source == "crossref+pubmed" and built.status == "metadata_verified"
    assert propose(client, "10.1167/15.12.782").record_source == "crossref"
    assert client.requests == 0


# --- types that stay unbuilt ---------------------------------------------------------------------

def test_a_book_is_not_built_and_its_record_states_no_edition(client):
    # GelmEtal13: the library cites the third edition; the record cannot say which edition it is.
    assert "\tEdition = {3\\textsuperscript{rd}},\n" in library("GelmEtal13")
    record = record_of("10.1201/b16018")
    assert record["type"] == "book" and not [k for k in record if "edition" in k.lower()]
    proposal = propose(client, "10.1201/b16018")
    assert proposal.unsupported == "book" and proposal.proposed_raw is None and proposal.status is None
    assert proposal.issues == ["A record of type book is not built automatically; the entry is left as typed"]
    # The library's own entry is not one the verifier accepts from this record.
    _, issues = compare_record(LIBRARY["GelmEtal13"]["fields"], record)
    assert issues == ["edition: no deterministic verifier for this field"]
    assert client.requests == 0


@pytest.mark.parametrize("doi, named, key", [
    ("10.1017/CBO9780511802843", "monograph", "DaviHink97"),         # a book, typed monograph by Crossref
    ("10.4135/9781452257044.n183", "reference-entry", "KahaMill13"),  # an encyclopedia entry
])
def test_a_record_of_a_type_that_is_not_built_is_named(client, doi, named, key):
    assert LIBRARY[key]["fields"]["doi"] == doi
    proposal = propose(client, doi)
    assert proposal.unsupported == named and proposal.proposed_raw is None and proposal.status is None
    assert proposal.issues == [f"A record of type {named} is not built automatically; the entry is left as typed"]
    assert client.requests == 0


@pytest.mark.parametrize("key", ["Spee22", "Mann11", "Shan20"])
def test_a_typed_entry_of_a_type_that_is_not_built_makes_no_lookup(client, key):
    # Until 2026-10-06 a typed @book (GelmEtal13) was among these; by the owner's decision of that day a
    # typed book is completed from its catalogue record (tests/test_complete_books.py).
    kind = LIBRARY[key]["fields"]["ENTRYTYPE"]
    assert kind in ("misc", "phdthesis", "techreport")
    proposal = complete.propose(complete.Query.from_entry(LIBRARY[key]), client, client.cache)
    assert proposal.unsupported == kind and proposal.proposed_raw is None and proposal.typed_raw == library(key)
    assert proposal.issues == [f"An entry of type {kind} is not built automatically; the entry is left as typed"]
    assert proposal.status is None and client.requests == 0


def test_the_software_title_of_the_library_is_not_one_the_format_checker_makes():
    # Why @misc stays unbuilt although the DataCite check verifies it: the house title of a
    # software release ("{rspeer}/wordfreq: {v3.0}", Spee22; datacite_review.house_title gives
    # "rspeer/wordfreq: {v3.0}") is not what format_title writes from the registry's title.
    from cdlbib import helpers
    assert LIBRARY["Spee22"]["fields"]["title"] == "{rspeer}/wordfreq: {v3.0}"
    assert helpers.format_title("rspeer/wordfreq: {v3.0}") == "Rspeer/wordfreq: {v3.0}"


# --- an edited proposal ----------------------------------------------------------------------------

def test_an_edited_paper_is_rechecked_and_a_book_is_still_unsupported(client, tmp_path, monkeypatch):
    from cdlbib import api
    from cdlbib.workspace import Workspace
    from test_complete_cli import refused_network
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    built = complete.propose(complete.Query.parse("10.1109/cvpr.2017.354"), client, client.cache, ws=ws)
    assert built.proposed_raw == library("BauEtal17") and built.status == "metadata_verified"
    edited = built.proposed_raw.replace("3319--3327", "3319--3328")
    again = api.recheck_proposal(ws, built, edited, mailto=CONTACT, database=str(client.cache.path))
    assert again.unsupported is None and again.entry_type == "inproceedings"
    assert again.status == "needs_review" and again.needs_decision is True
    assert "crossref 10.1109/cvpr.2017.354: pages: missing evidence or mismatch" in again.issues
    same = api.recheck_proposal(ws, built, built.proposed_raw, mailto=CONTACT, database=str(client.cache.path))
    assert same.unsupported is None and same.status == "metadata_verified" and same.complete
    assert api.apply_proposals(ws, [same]).written == ["BauEtal17"]
    assert ws.bib.read_text(encoding="utf-8").strip() == library("BauEtal17")
    as_book = api.recheck_proposal(ws, built, built.proposed_raw.replace("@inproceedings{", "@book{"), mailto=CONTACT,
                                   database=str(client.cache.path))
    assert as_book.unsupported == "book"
