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


# --- a chapter's editors are those of the book's own record (owner's decision 2026-10-06) ---------
#
# The chapters are entries of the frozen library; their Crossref records are in
# type_responses.json. The lookups of each one's BOOK by the chapter's ISBN (Crossref's records
# of a book type, then the Library of Congress catalogue: container_titles.book_editors) were
# recorded once on 2026-10-06 into rule_responses.json.

KAHANA, BOBROW = "10.1093/oxfordhb/9780190917982.013.2", "10.1016/b978-0-12-108550-6.50010-0"
BOOKS_CROSSREF = "crossref (the book's own Crossref record)"
BOOKS_CATALOGUE = "loc-catalogue (the book's Library of Congress record)"


def test_a_chapter_is_built_with_the_books_editors_written_and_verified(client, tmp_path, monkeypatch):
    from cdlbib import api, container_titles
    from cdlbib.verification import load_entries, verify_entry
    from cdlbib.workspace import Workspace
    from test_complete_cli import refused_network
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)
    record = saved_record(KAHANA)
    assert "editor" not in record and record["ISBN"] == ["9780190917982", "9780190918019"]
    # found: the book's own record, of a book type, with the chapter's ISBN and the book's title
    found = container_titles.book_editors(record, client)
    (source,) = found["sources"]
    assert (source["source"], source["doi"], source["isbn"], source["type"]) == (
        "crossref-book-record", "10.1093/oxfordhb/9780190917982.001.0001", "9780190917982", "edited-book")
    assert source["title"] == record["container-title"][0] == "The Oxford Handbook of Human Memory, Two Volume Pack"
    assert [(p["given"], p["family"]) for p in found["editor"]] == [("Michael J.", "Kahana"), ("Anthony D.", "Wagner")]
    # built
    ws = Workspace(tmp_path / "library")
    ws.root.mkdir()
    ws.bib.write_text("", encoding="utf-8")
    proposal = complete.propose(complete.Query.parse(KAHANA), client, client.cache, ws=ws)
    assert change(proposal, "editor") == complete.FieldChange("editor", None, "M J Kahana and A D Wagner", BOOKS_CROSSREF, "filled")
    assert proposal.status == "metadata_verified" and proposal.issues == [] and not proposal.needs_decision
    # written
    assert api.apply_proposals(ws, [proposal]).written == ["KahaEtal24"]
    entry = load_entries(ws.bib)["KahaEtal24"]
    assert entry["fields"]["editor"] == "M J Kahana and A D Wagner" == LIBRARY["KahaEtal24"]["fields"]["editor"]
    # verified: the verifier looks the book's record up by the same rule and keeps it with the candidate
    result = verify_entry(entry, client)
    assert result["status"] == "metadata_verified" and result["issues"] == []
    (candidate,) = result["candidates"]
    assert candidate["evidence"]["editor"]["match"] is True
    assert candidate["evidence"]["editor"]["source_record"] == {
        "source": "crossref-book-record", "doi": "10.1093/oxfordhb/9780190917982.001.0001", "isbn": "9780190917982",
        "title": "The Oxford Handbook of Human Memory, Two Volume Pack"}
    # ... and the saved candidate is judged again from what it holds, with no request (offline reassessment)
    from cdlbib.auto_review import reassess
    again = reassess(entry, result)
    assert again["status"] == "metadata_verified" and again["candidates"][0]["evidence"] == candidate["evidence"]
    assert client.requests == 0


def test_typed_editors_that_are_not_the_books_need_review_with_the_reason(client, tmp_path):
    typed = library("KahaEtal24").replace("{M J Kahana and A D Wagner}", "{M J Kahana and A D Wagoner}")
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, typed)), client, client.cache)
    assert change(proposal, "editor") == complete.FieldChange(
        "editor", "M J Kahana and A D Wagoner", "M J Kahana and A D Wagner", BOOKS_CROSSREF, "question")
    assert "\tEditor = {M J Kahana and A D Wagoner},\n" in proposal.proposed_raw   # the typed value stays until decided
    assert proposal.status == "needs_review" and proposal.needs_decision is True
    assert proposal.issues[0].startswith("editor: surname mismatch (crossref (the book's own Crossref record)): "
                                         "cited 'A D Wagoner', source 'A D Wagner'")
    assert f"crossref {KAHANA}: editor: Editor surnames/order differ (the book's own record)" in proposal.issues
    # the other order, one editor too few, and a wrong initial
    for editors, said in (("A D Wagner and M J Kahana", "editor: Editor surnames/order differ (the book's own record)"),
                          ("M J Kahana", "editor: Missing editors or different editor counts (the book's own record)"),
                          ("M J Kahana and B D Wagner", "editor: Editor given names differ (the book's own record)")):
        fields = dict(LIBRARY["KahaEtal24"]["fields"], editor=editors)
        record = dict(saved_record(KAHANA))
        from cdlbib import container_titles
        record[container_titles.BOOK_RECORD] = container_titles.book_editors(record, client)
        assert said in compare_record(fields, record)[1], editors
    assert client.requests == 0


def test_a_chapter_whose_record_states_no_isbn_has_its_editors_left_unfilled_with_the_reason(client):
    # Whitehouse 2004, in Progress in Brain Research (10.1016/s0079-6123(03)45022-x): the record of
    # tests/fixtures/intake/chapters.json.gz carries no ISBN, so no record of the book can be looked up.
    from intake_support import load_saved
    load_saved(client, "chapters.json.gz")
    doi = "10.1016/s0079-6123(03)45022-x"
    record = client.crossref_doi(doi)["body"]["message"]
    assert record["type"] == "book-chapter" and not record.get("ISBN") and not record.get("editor")
    proposal = complete.propose(complete.Query.parse(doi), client, client.cache, allow_model=False)
    assert unfilled(proposal, "editor") == complete.Unfilled(
        "editor", "editor: the chapter's record states no ISBN, so the book's record cannot be looked up", {})
    assert "Editor" not in (proposal.proposed_raw or "")
    assert client.requests == 0


def test_the_catalogue_names_the_editors_when_crossrefs_book_record_names_none(client):
    # BobrNorm75: Crossref's record of the book (10.1016/c2009-0-22090-3) names no editor; the
    # Library of Congress record (LCCN 75021630) names two.
    from cdlbib import container_titles
    found = container_titles.book_editors(saved_record(BOBROW), client)
    assert [(s["source"], len(s["editor"])) for s in found["sources"]] == [("crossref-book-record", 0), ("loc-catalogue", 2)]
    assert found["by"] == "loc-catalogue" and found["sources"][1]["lccn"] == "75021630"
    proposal = propose(client, BOBROW)
    assert change(proposal, "editor") == complete.FieldChange("editor", None, "D G Bobrow and A Collins", BOOKS_CATALOGUE, "filled")
    assert proposal.status == "metadata_verified" and client.requests == 0


def test_when_crossrefs_book_record_and_the_catalogue_disagree_no_editors_are_written(client):
    """The two real records of BobrNorm75's book, with one part added in this test's own cache:
    Crossref's book record, which names no editor, is given the catalogue's two in the other
    order. Neither is chosen: the editors are unfilled, with both lists, and it is a decision.
    An entry typed with either list is not verified by such a record."""
    from cdlbib import container_titles
    key = dumps(["https://api.crossref.org/works",
                 {"filter": "isbn:9780121085506,type:book,type:edited-book,type:monograph,type:reference-book", "rows": 5},
                 False])
    saved = client.cache.response(key, float("inf"))
    (item,) = saved["body"]["message"]["items"]
    assert item["DOI"] == "10.1016/c2009-0-22090-3" and not item.get("editor")
    item["editor"] = [{"given": "Allan", "family": "Collins"}, {"given": "Daniel G.", "family": "Bobrow"}]
    client.cache.save_response(key, saved)

    record = saved_record(BOBROW)
    found = container_titles.book_editors(record, client)
    assert "editor" not in found and found["disagreement"] is True
    assert found["reason"] == ("the book's Crossref record and its Library of Congress record name different editors, "
                               "and neither is chosen")
    proposal = propose(client, BOBROW)
    assert "Editor" not in proposal.proposed_raw
    assert unfilled(proposal, "editor") == complete.Unfilled(
        "editor", "editor: " + found["reason"],
        {"crossref-book-record": "Allan Collins; Daniel G. Bobrow", "loc-catalogue": "Daniel G. Bobrow; Allan Collins"})
    assert proposal.needs_decision is True and any(i.startswith("editor: " + found["reason"]) for i in proposal.issues)
    fields = dict({c.field: c.proposed for c in proposal.changes}, ENTRYTYPE="incollection")
    for editors in ("D G Bobrow and A Collins", "A Collins and D G Bobrow"):
        _, issues = compare_record(dict(fields, editor=editors), dict(record, **{container_titles.BOOK_RECORD: found}))
        assert issues == ["editor: the citation names editors and the source record names none; " + found["reason"]]
    assert client.requests == 0


def test_saved_book_evidence_is_judged_again_and_never_taken_from_another_book_or_a_series(client):
    from cdlbib import container_titles
    record = saved_record(KAHANA)
    found = container_titles.book_editors(record, client)
    fields = dict(LIBRARY["KahaEtal24"]["fields"])
    fields.pop("address", None)
    good = dict(record, **{container_titles.BOOK_RECORD: found})
    assert compare_record(fields, good)[1] == []
    none = ["editor: the citation names editors and the source record names none"]
    # evidence found under an ISBN that is not the chapter's, under another title, or altered after it was found
    other_isbn = dict(found, sources=[dict(found["sources"][0], isbn="9780387954714")])
    # Since the review of 2026-10-06 the evidence is read again from the source record kept with it
    # (sources[..]["record"]), never from the summary beside it: a summary altered alone changes nothing,
    # and a source record of another title, of a series type, or with a malformed editor list is refused.
    kept = found["sources"][0]["record"]
    assert kept["type"] == "edited-book" and kept["editor"]
    summary_only = dict(found, sources=[dict(found["sources"][0], title="Oxford Handbooks Online", names=["Oxford Handbooks Online"])])
    assert compare_record(fields, dict(record, **{container_titles.BOOK_RECORD: summary_only}))[1] == []
    other_title = dict(found, sources=[dict(found["sources"][0], record=dict(kept, title=["Oxford Handbooks Online"]))])
    a_series = dict(found, sources=[dict(found["sources"][0], record=dict(kept, type="book-series"))])
    malformed = dict(found, sources=[dict(found["sources"][0], record=dict(kept, editor=kept["editor"][:1] + ["Wagner"]))])
    shortened = dict(found, editor=found["editor"][:1],
                     sources=[dict(found["sources"][0], record=dict(kept, editor=kept["editor"][:1] + [None]))])
    no_record = dict(found, sources=[{k: v for k, v in found["sources"][0].items() if k != "record"}])
    altered = dict(found, editor=[{"given": "Someone", "family": "Else"}])
    for bad in (other_isbn, other_title, a_series, malformed, shortened, no_record, altered, {"editor": found["editor"]},
                "Kahana and Wagner"):
        assert compare_record(fields, dict(record, **{container_titles.BOOK_RECORD: bad}))[1] == none, bad
    # the review's own case: a chapter with a series title and a book title, the entry citing the book,
    # and "evidence" that is a series record named by the series title
    two = dict(record, **{"container-title": ["Series Title", "Actual Book"]})
    series_evidence = {"editor": found["editor"], "by": "crossref-book-record", "booktitle": "Series Title", "sources": [
        dict(found["sources"][0], type="book-series", names=["Series Title"], title="Series Title", booktitle="Series Title",
             record=dict(kept, type="book-series", title=["Series Title"]))]}
    assert none[0] in compare_record(dict(fields, booktitle="Actual Book"),
                                     dict(two, **{container_titles.BOOK_RECORD: series_evidence}))[1]
    # ... and even a record of a book type named by the series title is not evidence for the cited book
    book_named_series = {"editor": found["editor"], "by": "crossref-book-record", "booktitle": "Series Title", "sources": [
        dict(found["sources"][0], record=dict(kept, title=["Series Title"]))]}
    assert none[0] in compare_record(dict(fields, booktitle="Actual Book"),
                                     dict(two, **{container_titles.BOOK_RECORD: book_named_series}))[1]
    # a malformed editor list is no evidence when it is found, either
    assert container_titles._people([{"given": "M", "family": "Kahana"}, "Wagner"]) is None
    assert container_titles._people("Kahana") is None and container_titles._people([{"given": "M"}]) is None
    # a record that is not of a book type is never read (a series has the type book-series)
    assert "book-series" not in container_titles.BOOK_TYPES
    # an entry of another type is not given a book's editors
    assert "editor: the citation names editors and the source record names none" in compare_record(
        dict(fields, ENTRYTYPE="inproceedings"), good)[1]
    # and an entry without an editor field is compared as before, whatever was found
    bare = {k: v for k, v in fields.items() if k != "editor"}
    assert compare_record(bare, good) == compare_record(bare, record)


# --- review of 2026-10-06, item 7: every matching record of an answer, and a whole answer ---------

def _crossref_books_answer(client, isbn):
    from cdlbib import container_titles
    from cdlbib.verification import dumps
    params = {"filter": f"isbn:{isbn}," + ",".join("type:" + t for t in container_titles.BOOK_TYPES), "rows": 5}
    identity = dumps([container_titles.WORKS, params, False])
    return identity, deepcopy(client.cache.response(identity, 10**9))


def test_a_second_record_with_other_editors_or_an_answer_cut_short_leaves_the_editors_undecided(client):
    from cdlbib import container_titles
    record = saved_record(KAHANA)
    whole = container_titles.book_editors(record, client)
    assert [p["family"] for p in whole["editor"]] == ["Kahana", "Wagner"] and "reason" not in whole
    identity, answer = _crossref_books_answer(client, "9780190917982")
    (item,) = answer["body"]["message"]["items"]
    # the same answer with a second record of the book that names other editors (the first one found would
    # have been taken, and the second never read)
    second = dict(deepcopy(item), DOI="10.1093/oxfordhb/9780190917982.001.0002",
                  editor=[{"given": "Someone", "family": "Else"}])
    two = deepcopy(answer)
    two["body"]["message"].update(items=[item, second])
    two["body"]["message"]["total-results"] = 2
    client.cache.save_response(identity, two)
    found = container_titles.book_editors(record, client)
    assert "editor" not in found and found["disagreement"] is True and len(found["sources"]) == 2
    assert found["reason"] == "the 2 records found for the book name different editors, and none is chosen"
    assert container_titles.valid_book_editors(dict(record, **{container_titles.BOOK_RECORD: found})) is None
    # two records that agree are evidence, and each is kept with its source record
    agreeing = deepcopy(two)
    agreeing["body"]["message"]["items"][1]["editor"] = deepcopy(item["editor"])
    client.cache.save_response(identity, agreeing)
    both = container_titles.book_editors(record, client)
    assert [p["family"] for p in both["editor"]] == ["Kahana", "Wagner"] and all("record" in s for s in both["sources"])
    # an answer Crossref cut short (it counts more records than it returned) decides nothing
    short = deepcopy(answer)
    short["body"]["message"]["total-results"] = 9
    client.cache.save_response(identity, short)
    cut = container_titles.book_editors(record, client)
    assert "editor" not in cut and cut["reason"] == (
        "Crossref counts 9 book records with the ISBN 9780190917982 and returned 1; the editors are not taken from "
        "an incomplete answer")
    # a list with a member that is no person is no evidence, whoever else is in it
    broken = deepcopy(answer)
    broken["body"]["message"]["items"][0]["editor"] = item["editor"][:1] + ["Wagner"]
    client.cache.save_response(identity, broken)
    bad = container_titles.book_editors(record, client)
    assert "editor" not in bad and "is not well formed" in bad["reason"]
    client.cache.save_response(identity, answer)
    assert container_titles.book_editors(record, client)["editor"] == whole["editor"] and client.requests == 0
