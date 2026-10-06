r"""The builder under the house rules decided on 2026-10-06: a chapter's editors, ordinals
and acronyms in the name of a book or of proceedings, and the pages of an ACL Anthology paper.

Nothing here is invented. Every lookup is a real response fetched once on 2026-10-06 and
saved in tests/fixtures/completion/rule_responses.json (``record_rule_responses.py`` beside
it made the file; the README lists each request). It is replayed through the real client
over a real cache with a transport that refuses every request (the ``client`` fixture of
test_complete_identify.py), so ``client.requests == 0`` shows that nothing was fetched, and a
lookup the files do not hold is a refused request.

The works:
- 10.1515/9783110858778-003: M. Minsky, "A Framework For Representing Knowledge", in Frame
  Conceptions and Text Understanding (De Gruyter, 1979). Its Crossref record names the
  book's editor, Dieter Metzing. (The library's Mins75 is the same text in another book.)
- 10.1093/med/9780197549469.003.0016: a chapter of Jasper's Basic Mechanisms of the
  Epilepsies (2024); its record names the four editors, one with a particle (de Curtis).
- 10.1117/12.2309486: a paper of the Tenth International Conference on Machine Vision (SPIE,
  2018); its record names the volume's four editors.
- 10.18653/v1/d19-1410 (the library's ReimGure19) and 10.18653/v1/d19-6607 (ClanEtal19):
  papers of the ACL Anthology, with the Anthology's own BibTeX record of each.
"""
from copy import deepcopy
import json

import pytest

from cdlbib import complete
from cdlbib.acl_review import assess_acl
from cdlbib.verification import author_evidence, compare_record, dumps

from test_complete_identify import CONTACT, RULES, client, propose, typed_entry  # noqa: F401
from test_complete_types import LIBRARY, change, library, record_of as saved_record, unfilled

MINSKY, JASPER, SPIE = "10.1515/9783110858778-003", "10.1093/med/9780197549469.003.0016", "10.1117/12.2309486"
REIMERS, CLANCY = "10.18653/v1/d19-1410", "10.18653/v1/d19-6607"
MINS79 = ("@incollection{Mins79,\n\tAuthor = {M Minsky},\n\tBooktitle = {Frame Conceptions and Text Understanding},\n"
          "\tDoi = {10.1515/9783110858778-003},\n\tEditor = {D Metzing},\n\tPages = {1--25},\n"
          "\tPublisher = {De Gruyter},\n\tTitle = {A framework for representing knowledge},\n\tYear = {1979}}")
ADDRESS = complete.Unfilled("address", "address: no source record states it", {})


def record_of(doi):
    """The Crossref record of a DOI saved for these tests, as the client cached it."""
    for item in RULES:
        body = item["response"].get("body")
        if isinstance(body, dict) and str((body.get("message") or {}).get("DOI", "")).lower() == doi.lower():
            return deepcopy(body["message"])
    return saved_record(doi)


def anthology(name):
    """The saved Anthology document of a paper, as ``acl_review.collect`` returns it."""
    key = f"acl-source-v1:https://aclanthology.org/{name}.bib"
    return {"anthology_id": name, "record": next(item["response"] for item in RULES if item["request"] == key)}


def fields_of(proposal, tmp_path):
    return typed_entry(tmp_path, proposal.proposed_raw)["fields"]


# --- editors: the builder -------------------------------------------------------------------------

def test_a_chapter_whose_record_names_its_editor_is_built_with_it(client):
    record = record_of(MINSKY)
    assert record["type"] == "book-chapter"
    assert [(p["given"], p["family"]) for p in record["editor"]] == [("Dieter", "Metzing")]
    proposal = propose(client, MINSKY)
    assert proposal.proposed_raw == MINS79
    assert change(proposal, "editor") == complete.FieldChange("editor", None, "D Metzing", "crossref", "filled")
    assert proposal.status == "metadata_verified" and proposal.issues == [] and proposal.unfilled == [ADDRESS]
    assert proposal.complete is True and proposal.needs_decision is False
    assert client.requests == 0


def test_several_editors_are_written_complete_and_in_order_in_the_house_name_form(client):
    record = record_of(JASPER)
    assert [(p["given"], p["family"]) for p in record["editor"]] == [
        ("Massimo", "Avoli"), ("Marco", "de Curtis"), ("Christophe", "Bernard"), ("Ivan", "Soltesz")]
    proposal = propose(client, JASPER)
    assert "\tEditor = {M Avoli and M de Curtis and C Bernard and I Soltesz},\n" in proposal.proposed_raw
    assert "\tAuthor = {E M Merricks and C A Schevon},\n" in proposal.proposed_raw
    assert change(proposal, "editor").kind == "filled" and change(proposal, "editor").source == "crossref"
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    # The format checker's own formatter for editors leaves the built names as they are.
    from cdlbib import helpers
    assert helpers.reformat_author(change(proposal, "editor").proposed) == change(proposal, "editor").proposed
    assert client.requests == 0


def test_the_editors_of_a_paper_in_proceedings_are_not_filled(client):
    # The record names the volume's editors; a paper in proceedings is built without them
    # (the owner's decision fills editors for chapters). Typed, they are kept and verified.
    record = record_of(SPIE)
    assert record["type"] == "proceedings-article" and len(record["editor"]) == 4
    proposal = propose(client, SPIE)
    assert "Editor" not in proposal.proposed_raw and all(c.field != "editor" for c in proposal.changes)
    assert all(u.field != "editor" for u in proposal.unfilled)
    # Its name of the proceedings: "Tenth International Conference on Machine Vision (ICMV 2017)".
    assert record["container-title"] == ["Tenth International Conference on Machine Vision (ICMV 2017)"]
    assert change(proposal, "booktitle").proposed == "10\\textsuperscript{th} International Conference on Machine Vision"
    assert proposal.status == "metadata_verified"
    assert client.requests == 0


def test_an_editor_the_house_form_cannot_be_made_of_is_listed_and_not_written():
    # The real record with one part replaced: an organization as its editor.
    record = record_of(MINSKY)
    record["editor"] = [{"name": "The Frame Group"}]
    proposal = complete.build({"doi": record["DOI"]}, record)
    assert "Editor" not in proposal.proposed_raw
    assert unfilled(proposal, "editor") == complete.Unfilled(
        "editor", "editor: Incomplete or corporate source byline", {"crossref": "The Frame Group"})
    # And a part that is not in the form Crossref documents is left out and said so.
    record["editor"] = "Dieter Metzing"
    proposal = complete.build({"doi": record["DOI"]}, record)
    assert unfilled(proposal, "editor").reason == "editor: the record's editor is not in the expected form"


# --- editors: typed, and the verifier -------------------------------------------------------------

def test_typed_editors_the_record_names_are_kept_and_verified(client, tmp_path):
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, MINS79)), client, client.cache)
    assert proposal.proposed_raw == MINS79 and {c.kind for c in proposal.changes} == {"kept"}
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    # Given names in full, as the record has them, are the same editor.
    full = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, MINS79.replace("{D Metzing}", "{Dieter Metzing}"))),
                            client, client.cache)
    assert full.status == "metadata_verified" and change(full, "editor") == complete.FieldChange(
        "editor", "Dieter Metzing", "Dieter Metzing", "typed", "kept")
    assert client.requests == 0


def test_typed_editors_that_are_not_the_records_need_review_with_the_reason(client, tmp_path):
    # P H Winston edited the other book the chapter is in (the library's Mins75).
    assert LIBRARY["Mins75"]["fields"]["editor"] == "P H Winston"
    other = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, MINS79.replace("{D Metzing}", "{P H Winston}"))),
                             client, client.cache)
    assert other.status == "needs_review" and other.needs_decision is True
    assert change(other, "editor") == complete.FieldChange("editor", "P H Winston", "D Metzing", "crossref", "question")
    assert "\tEditor = {P H Winston},\n" in other.proposed_raw          # the typed value stays until it is decided
    assert other.issues[0].startswith("editor: surname mismatch (crossref): cited 'P H Winston', source 'D Metzing'")
    assert f"crossref {MINSKY}: editor: Editor surnames/order differ" in other.issues

    more = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, MINS79.replace(
        "{D Metzing}", "{D Metzing and P H Winston}"))), client, client.cache)
    assert more.status == "needs_review" and more.needs_decision is True
    assert f"crossref {MINSKY}: editor: Missing editors or different editor counts" in more.issues
    assert client.requests == 0


def test_an_entry_without_an_editor_field_is_compared_exactly_as_before():
    """The record names editors; the entry does not: nothing is asked of it. The evidence
    and the issues are those of the same comparison against the record without its editors."""
    for doi, kind in ((MINSKY, "incollection"), (JASPER, "incollection"), (SPIE, "inproceedings")):
        record = record_of(doi)
        built = complete.build({"doi": doi}, record)
        fields = dict({c.field: c.proposed for c in built.changes if c.field != "editor"}, ENTRYTYPE=kind)
        assert "editor" not in fields and record["editor"]
        evidence, issues = compare_record(fields, record)
        bare = {k: v for k, v in record.items() if k != "editor"}
        assert (evidence, issues) == compare_record(fields, bare)
        assert "editor" not in evidence and not [i for i in issues if i.startswith("editor")]


def test_no_saved_comparison_of_an_entry_without_editors_is_changed_by_a_records_editors():
    """Every Crossref record with editors among the candidates saved in the committed
    baseline (verification/baseline.jsonl.gz), against the library entry it was saved for:
    when the entry has no editor field, the comparison is the one made against the same
    record without its editors. When it has one, only the editor's own evidence and issue
    differ, and the issue is never "no deterministic verifier" for the three types compared."""
    import gzip
    from cdlbib.auto_review import safe_compare
    from cdlbib.verification import EDITOR_KINDS, load_entries
    from test_complete_types import ROOT
    entries = load_entries(ROOT / "cdl.bib")
    without, with_editors = 0, 0
    with gzip.open(ROOT / "verification/baseline.jsonl.gz", "rt", encoding="utf-8") as lines:
        for line in lines:
            if '"editor"' not in line:
                continue
            row = json.loads(line)
            fields = entries.get(row.get("key"), {}).get("fields")
            for candidate in row.get("candidates", []) if fields else []:
                record = candidate.get("record") or {}
                if candidate.get("source") != "crossref" or not record.get("editor"):
                    continue
                evidence, issues = safe_compare(fields, record, candidate.get("doi_alias"))
                bare = safe_compare(fields, {k: v for k, v in record.items() if k != "editor"}, candidate.get("doi_alias"))
                if "editor" not in fields:
                    without += 1
                    assert (evidence, issues) == bare, row["key"]
                    continue
                with_editors += 1
                about = [i for i in issues if i.startswith("editor:")]
                assert [i for i in issues if i not in about] == [i for i in bare[1] if not i.startswith("editor:")]
                if fields["ENTRYTYPE"].lower() in EDITOR_KINDS and evidence:
                    assert about == ([] if evidence["editor"]["match"] else ["editor: " + evidence["editor"]["detail"]])
                    assert {k: v for k, v in evidence.items() if k != "editor"} == {
                        k: v for k, v in bare[0].items() if k != "editor"}
    assert without > 200 and with_editors > 100, (without, with_editors)


def test_editors_are_compared_as_authors_are():
    """The same list of people as the citation's authors and as its editors: the same verdict
    at every step, and the wording differs only in the name of the role."""
    record = record_of(JASPER)
    people = record["editor"]
    cases = {
        "M Avoli and M de Curtis and C Bernard and I Soltesz": (True, "Complete {} list in order; citation initials agree with source names"),
        "Massimo Avoli and Marco de Curtis and Christophe Bernard and Ivan Soltesz": (True, "Complete {} list in order; citation initials agree with source names"),
        "M de Curtis and M Avoli and C Bernard and I Soltesz": (False, "{} surnames/order differ"),
        "M Avoli and M de Curtis and C Bernard": (False, "Missing {}s or different {} counts"),
        "M Avoli and M de Curtis and C Bernard and I Soltesz and A Nother": (False, "Missing {}s or different {} counts"),
        "M Avoli and M Curtis and C Bernard and I Soltesz": (False, "{} surnames/order differ"),
        "M Avoli and M de Curtis and K Bernard and I Soltesz": (False, "{} given names differ"),
        "M Avoli and M de Curtis and C Bernard and Soltesz, Jr, I": (True, "Complete {} list in order; citation initials agree with source names"),
        "M Avoli and M de Curtis and C Bernard and Soltesz": (False, "Missing or incomplete given names"),
        "M Avoli and M de Curtis and C Bernard and {Soltesz Group}": (False, "Corporate {} differs or is not represented as an organization"),
    }
    for byline, (same, wording) in cases.items():
        as_authors = author_evidence(byline, people)
        as_editors = author_evidence(byline, people, role="editor")

        def worded(role):
            text = wording.format(*[role] * wording.count("{}"))
            return text[0].upper() + text[1:] if wording.startswith("{}") else text
        assert as_authors == (same, worded("author")), byline
        assert as_editors == (same, worded("editor")), byline

        fields = {"ENTRYTYPE": "incollection", "title": record["title"][0], "author": "E M Merricks and C A Schevon",
                  "booktitle": record["container-title"][0], "year": "2024", "pages": "325--350", "editor": byline}
        evidence, issues = compare_record(fields, record)
        assert evidence["editor"] == {"local": byline, "source": people, "match": same, "detail": as_editors[1]}
        assert issues == ([] if same else ["editor: " + as_editors[1]]), byline
        # ... and the same people as the record's authors and the citation's: the author rule's own verdict.
        swapped = dict(record, author=people)
        _, author_issues = compare_record(dict(fields, author=byline, editor=fields["editor"]), swapped)
        assert ("author: " + as_authors[1] in author_issues) is (not same), byline


def test_which_entries_have_their_editors_compared():
    record = record_of(SPIE)
    built = complete.build({"doi": SPIE}, record)
    fields = dict({c.field: c.proposed for c in built.changes}, ENTRYTYPE="inproceedings")
    editors = "J Zhou and P Radeva and D Nikolaev and A Verikas"
    # A paper in proceedings: compared with the record's editors.
    assert compare_record(dict(fields, editor=editors), record)[1] == []
    assert compare_record(dict(fields, editor="P Radeva and J Zhou and D Nikolaev and A Verikas"), record)[1] == [
        "editor: Editor surnames/order differ"]
    # A record that names no editors cannot bear the citation's out.
    bare = {k: v for k, v in record.items() if k != "editor"}
    assert compare_record(dict(fields, editor=editors), bare)[1] == [
        "editor: the citation names editors and the source record names none"]
    # An article's editor field has no check, as before.
    article = dict(fields, ENTRYTYPE="article", journal=fields["booktitle"], editor=editors)
    del article["booktitle"]
    assert "editor: no deterministic verifier for this field" in compare_record(article, record)[1]
    assert "editor" not in compare_record(article, record)[0]


# --- ordinals and acronyms in the name of proceedings ---------------------------------------------

def test_an_ordinal_word_in_crossrefs_name_is_built_as_the_house_ordinal_and_verified(client, tmp_path):
    record = record_of(CLANCY)
    assert record["container-title"] == ["Proceedings of the Second Workshop on Fact Extraction and VERification (FEVER)"]
    proposal = propose(client, CLANCY)
    # The year and the final acronym are left out (verification.proceedings_name_forms); the
    # ordinal is the house ordinal; the capitals Crossref gives inside a word are kept, in braces.
    assert change(proposal, "booktitle") == complete.FieldChange(
        "booktitle", None, "Proceedings of the 2\\textsuperscript{nd} Workshop on Fact Extraction and {VERification}",
        "crossref", "filled")
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    # The verifier reads the three spellings as one: against Crossref's record, and against
    # the Anthology's ("Proceedings of the Second Workshop ...").
    fields = fields_of(proposal, tmp_path)
    for spelling in ("2\\textsuperscript{nd}", "2nd", "Second"):
        cited = dict(fields, booktitle=fields["booktitle"].replace("2\\textsuperscript{nd}", spelling))
        assert compare_record(cited, record)[1] == [], spelling
        assert assess_acl(cited, anthology("D19-6607"))["status"] == "metadata_verified", spelling
    wrong = dict(fields, booktitle=fields["booktitle"].replace("2\\textsuperscript{nd}", "3\\textsuperscript{rd}"))
    assert compare_record(wrong, record)[1] == ["booktitle: missing evidence or mismatch"]
    assert assess_acl(wrong, anthology("D19-6607"))["status"] == "needs_review"
    assert client.requests == 0


def test_a_typed_name_with_a_plain_ordinal_is_put_in_house_form(client, tmp_path):
    # The library's NguyEtal18 typed with "16th" where the library has the house ordinal.
    text = library("NguyEtal18")
    assert "16\\textsuperscript{th} Annual" in text
    typed = typed_entry(tmp_path, text.replace("16\\textsuperscript{th}", "16th"))
    proposal = complete.propose(complete.Query.from_entry(typed), client, client.cache)
    assert change(proposal, "booktitle") == complete.FieldChange(
        "booktitle", typed["fields"]["booktitle"], LIBRARY["NguyEtal18"]["fields"]["booktitle"], "house format", "changed")
    assert proposal.status == "metadata_verified"
    assert not [issue for issue in proposal.issues if issue.startswith("format:")]
    assert client.requests == 0


# --- the pages of an ACL Anthology paper ----------------------------------------------------------

def test_the_pages_of_an_acl_anthology_paper_are_the_anthologys(client):
    # ReimGure19. Crossref deposits 3980-3990; the Anthology and the paper give 3982--3992.
    assert record_of(REIMERS)["page"] == "3980-3990"
    assert 'pages = "3982--3992"' in anthology("D19-1410")["record"]["body"]
    assert "\tPages = {3982--3992}," in library("ReimGure19")
    proposal = propose(client, REIMERS)
    assert change(proposal, "pages") == complete.FieldChange("pages", None, "3982--3992", "acl-anthology", "filled")
    assert proposal.issues == [] and proposal.needs_decision is False and proposal.complete is True
    # The Anthology check accepts it, as in the gate (Crossref's record alone does not: its pages differ).
    assert proposal.status == "metadata_verified"
    # Against the library: the title's capitals (format_title) and "the 9th" in the
    # proceedings' name, which the library's entry omits; nothing else.
    assert proposal.proposed_raw == library("ReimGure19").replace(
        "Sentence-{BERT}: sentence embeddings using {S}iamese {BERT}-networks",
        "Sentence-bert: sentence embeddings using siamese bert-networks").replace(
        "and the International Joint", "and the 9\\textsuperscript{th} International Joint")
    assert client.requests == 0


def test_the_anthology_is_read_through_the_verifiers_client_and_cache(client):
    # The document the builder reads is the one the Anthology check reads: the same cache
    # key, the same checks of what was saved (acl_review.collect, acl_review.record).
    from cdlbib import acl_review
    item = complete.anthology_record(client, client.cache, REIMERS)
    assert item["pages"] == "3982--3992" and item["doi"] == "10.18653/v1/D19-1410"
    assert acl_review.collect(client.cache, client, {"ENTRYTYPE": "inproceedings", "doi": REIMERS}) == anthology("D19-1410")
    assert complete.anthology_record(client, client.cache, "10.1109/cvpr.2017.354") is None   # not an Anthology paper
    assert client.requests == 0


def test_the_pages_stay_a_question_when_the_anthology_cannot_be_read(client):
    with client.cache.db:
        client.cache.db.execute("DELETE FROM responses WHERE request=?",
                                ("acl-source-v1:https://aclanthology.org/D19-1410.bib",))
    proposal = propose(client, REIMERS)
    assert change(proposal, "pages") == complete.FieldChange("pages", None, "3980--3990", "crossref", "question")
    assert proposal.issues[0] == (
        "pages: 10.18653/v1/d19-1410 is an ACL Anthology paper; the Anthology's record outranks Crossref's page range "
        "and could not be read (offline: request to aclanthology.org refused), so the pages "
        "are not confirmed")
    assert proposal.needs_decision is True
    assert client.requests >= 1          # the Anthology was asked for, and the transport refused


def test_an_anthology_record_that_is_another_papers_is_not_used(client):
    # The saved document of D19-6607 under the cache key of D19-1410: its own URL and DOI
    # name another paper, so it is refused as the Anthology check refuses it.
    other = dict(anthology("D19-6607")["record"], url="https://aclanthology.org/D19-1410.bib")
    client.cache.save_response("acl-source-v1:https://aclanthology.org/D19-1410.bib", other)
    said = complete.anthology_record(client, client.cache, REIMERS)
    assert said == "Anthology BibTeX names another paper"
    proposal = propose(client, REIMERS)
    assert change(proposal, "pages").kind == "question" and change(proposal, "pages").proposed == "3980--3990"
    assert "could not be read (Anthology BibTeX names another paper)" in proposal.issues[0]


def test_build_fills_the_anthologys_pages_only_from_a_usable_record():
    record = record_of(REIMERS)
    item = {"pages": "3982--3992"}
    assert change(complete.build({"doi": REIMERS}, record, anthology=item), "pages").proposed == "3982--3992"
    for unusable, why in (({"pages": ""}, "was read and states no usable pages"), ({}, "was read and states no usable pages"),
                          ({"pages": "iv+12"}, "was read and states no usable pages"),
                          ("HTTP 404", "could not be read (HTTP 404)"), (None, "was not read")):
        proposal = complete.build({"doi": REIMERS}, record, anthology=unusable)
        assert change(proposal, "pages") == complete.FieldChange("pages", None, "3980--3990", "crossref", "question")
        assert why in proposal.issues[0]
    # A paper that is not the Anthology's is not touched by an Anthology record.
    cvpr = saved_record("10.1109/cvpr.2017.354")
    assert change(complete.build({"doi": cvpr["DOI"]}, cvpr, anthology=item), "pages").proposed == "3319--3327"
