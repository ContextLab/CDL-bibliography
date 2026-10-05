"""cdlbib.desk through cdlbib.api: browse, search, one entry with its evidence, the review
queue, the revision value and the state of the library.

Real files in tmp_path built from small house-format text, a real SQLite verification cache
seeded with the verifier's own results (verify_entry over the suite's frozen offline client,
Cache.put, record_approval, record_revocation), real git checkouts and a local bare upstream.
Nothing reads the repository's cdl.bib or the real data folder; nothing is mocked.
"""
import os
from pathlib import Path

import pytest

import conftest
from cdlbib import api, complete, desk, library
from cdlbib.errors import CdlbibError, UpdateNeedsDecision
from cdlbib.verification import (Cache, load_entries, record_approval, record_revocation, result_advisories,
                                 verify_entry)
from cdlbib.verification_cli import closest_candidate
from cdlbib.workspace import Origin, Workspace

from test_complete_identify import client, library_entry  # noqa: F401 - the frozen offline client fixture
from test_library import managed  # noqa: F401 - a data folder and an upstream of the test's own
from test_publish import checkout, git  # noqa: F401 - a real clone with a bare remote

ZOLL90 = conftest.ZOLL90
KAHA12 = ("@book{Kaha12,\n\tAddress = {New York, {NY}},\n\tAuthor = {M J Kahana},\n\tPublisher = {Oxford University "
          "Press},\n\tTitle = {Foundations of human memory},\n\tYear = {2012}}")
GLOC08 = complete.render("article", "GlocBets08", dict(
    author='A Gl{\\"o}ckner and T Betsch', title="Multiple-reason decision making based on automatic processing",
    journal="Journal of Experimental Psychology: Learning, Memory, and Cognition", year="2008", volume="34",
    number="5", pages="1055--1075"))
TENE11 = complete.render("article", "TeneEtal11", dict(
    author="J B Tenenbaum and C Kemp and T L Griffiths and N D Goodman",
    title="How to grow a mind: statistics, structure, and abstraction", journal="Science", year="2011",
    volume="331", number="6022", pages="1279--1285", doi="10.1126/science.1192788"))
GAME62 = library_entry("Game62")      # the frozen library's entry; the saved responses verify it
TEXT = "% the lab's library\n" + "\n\n".join([ZOLL90, KAHA12, GLOC08, TENE11]) + "\n"


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "cdl.bib").write_text(TEXT, encoding="utf-8")
    return Workspace(root)


def keys(found):
    return [item.key for item in found]


def tree(root):
    """Every file of the folder with its bytes (git's own folder apart)."""
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(Path(root).rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(root).parts}


# --- browse ------------------------------------------------------------------------------------

def test_entries_are_summaries_in_file_order_and_reading_creates_nothing(ws):
    before = tree(ws.root)
    found = api.entries(ws)
    assert keys(found) == ["Zoll90", "Kaha12", "GlocBets08", "TeneEtal11"]
    zoller, book = found[0], found[1]
    assert (zoller.type, zoller.authors, zoller.year, zoller.venue, zoller.doi) == (
        "article", "U Zoller", "1990", "Journal of Research in Science Teaching", "10.1002/tea.3660271011")
    assert zoller.title.startswith("Students' misunderstandings")
    assert (book.type, book.venue, book.doi) == ("book", "Oxford University Press", "")
    assert {item.status for item in found} == {"pending"} and zoller.issues == ("New, edited, or policy-invalidated entry",)
    assert tree(ws.root) == before            # no .bibcheck, no database, no lock


def test_an_empty_library_has_no_entries_and_an_unreadable_one_is_a_cdlbib_error(tmp_path):
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    assert api.entries(ws) == [] and api.search(ws, "anything") == [] and api.review_queue(ws, all_entries=True) == []
    ws.bib.write_text("@article{Broken, title = {never closed}", encoding="utf-8")
    with pytest.raises(CdlbibError, match="could not be read"):
        api.entries(ws)


def test_parsing_is_cached_by_the_files_stat_and_results_are_read_every_time(ws):
    first = desk.parsed(ws)
    assert desk.parsed(ws) is first and first == load_entries(ws.bib)
    cache = Cache(ws.database, ledger=ws.revocations)
    try:                                       # a result arrives; the file does not change
        record_approval(cache, ws.bib, "Kaha12", first["Kaha12"]["fingerprint"],
                        dict(reviewer="@fixture", source="the book itself", note="title page checked"))
    finally:
        cache.close()
    assert desk.parsed(ws) is first
    assert {item.key: item.status for item in api.entries(ws)}["Kaha12"] == "human_verified"
    ws.bib.write_text(TEXT.replace("Foundations of human memory", "Foundations of human memory, 2nd edition"),
                      encoding="utf-8")
    again = desk.parsed(ws)
    assert again is not first and again == load_entries(ws.bib)
    assert {item.key: item.status for item in api.entries(ws)}["Kaha12"] == "pending"     # the content changed


# --- search ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("", ["Zoll90", "Kaha12", "GlocBets08", "TeneEtal11"]),
    ("glockner", ["GlocBets08"]),                        # a TeX accent in the file, none in the query
    ("Glöckner", ["GlocBets08"]),                   # the accented letter itself
    ("GLOCKNER betsch", ["GlocBets08"]),                 # case, and two words
    ("betsch glockner", ["GlocBets08"]),                 # in any order
    ("glockner kahana", []),                             # every word must be found
    ("memory", ["Kaha12", "GlocBets08"]),                # title of one, journal of the other
    ("title:memory", ["Kaha12"]),
    ("venue:memory", ["GlocBets08"]),
    ("journal:science", ["Zoll90", "TeneEtal11"]),
    ("journal:science year:2011", ["TeneEtal11"]),
    ('title:"human memory"', ["Kaha12"]),
    ('"memory human"', []),                              # quoted words are found together, in that order
    ("author:kahana 2012", ["Kaha12"]),
    ("author:tenenbaum", ["TeneEtal11"]),
    ("author:science", []),
    ("type:book", ["Kaha12"]),
    ("book", []),                                        # the type is searched only when asked for
    ("type:article 1990", ["Zoll90"]),
    ("key:etal", ["TeneEtal11"]),
    ("doi:10.1126", ["TeneEtal11"]),
    ("10.1002/TEA.3660271011", ["Zoll90"]),
    ("status:pending zoller", ["Zoll90"]),
    ("status:human_verified", []),
    ("mind: statistics,", ["TeneEtal11"]),               # punctuation is part of the text
    ("nosuchfield:memory", []),                          # not a field: looked for as it is written
])
def test_search(ws, text, expected):
    assert keys(api.search(ws, text)) == expected


def test_search_reads_braces_and_accents_alike_and_filters_by_status(tmp_path):
    ws = Workspace(tmp_path)
    ws.bib.write_text(complete.render("article", "Mull20", dict(
        author="K M{\\\"u}ller and J Fr{\\'e}chet and S {\\O}stby", title="{B}ayesian models of {fMRI} in {N}ew {Y}ork",
        journal="Neuro{I}mage", year="2020")) + "\n", encoding="utf-8")
    for text in ("muller", "Müller", "frechet", "ostby", "Østby", "bayesian fmri", "new york", "neuroimage",
                 "author:mÜLLER title:FMRI"):
        assert keys(api.search(ws, text)) == ["Mull20"], text
    summaries = api.entries(ws)
    ws.bib.unlink()                              # a list of summaries is searched without reading anything
    assert keys(api.search(summaries, "bayesian")) == ["Mull20"]
    assert keys(api.search(summaries, "bayesian", status="pending")) == ["Mull20"]
    assert api.search(summaries, "bayesian", status="human_verified") == []
    assert keys(api.search(summaries, "", status=("human_verified", "pending"))) == ["Mull20"]


# --- one entry ---------------------------------------------------------------------------------

def verified(ws, client, text):
    """A library holding ``text``, with the verifier's own result for each entry stored as
    the gate stores it (verify_entry over the saved responses, Cache.put)."""
    ws.bib.write_text(text, encoding="utf-8")
    found = load_entries(ws.bib)
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        return {key: cache.put(ws.bib, item, verify_entry(item, client)) for key, item in found.items()}
    finally:
        cache.close()


def test_entry_shows_the_stored_result_and_its_evidence(ws, client):
    stored = verified(ws, client, ZOLL90 + "\n\n" + GAME62 + "\n")
    assert stored["Game62"]["status"] == "metadata_verified" and client.requests == 0
    detail = api.entry(ws, "Game62")
    found = load_entries(ws.bib)["Game62"]
    assert (detail.key, detail.raw, detail.fingerprint) == ("Game62", GAME62, found["fingerprint"])
    assert detail.fields == found["fields"] and detail.fields["volume"] == "63"
    assert detail.result == stored["Game62"] and detail.status == "metadata_verified"
    assert detail.candidates == stored["Game62"]["candidates"] and detail.candidates[0]["source"] == "crossref"
    assert detail.candidates[0]["doi"] == "10.1037/h0041332" and len(detail.attempts) == 1
    assert detail.attempts == stored["Game62"]["attempts"]
    assert detail.issues == [] and detail.closest is None and detail.format == []
    assert detail.human_review is None and detail.revoked_approval is None and detail.external_evidence is None
    assert detail.advisories == result_advisories(found["fields"], stored["Game62"])
    assert {item.key: item.status for item in api.entries(ws)} == {"Zoll90": stored["Zoll90"]["status"],
                                                                  "Game62": "metadata_verified"}
    assert keys(api.search(ws, "status:metadata_verified games")) == ["Game62"]
    assert keys(api.review_queue(ws, all_entries=True)) == ["Zoll90"]


def test_entry_shows_what_a_source_disagrees_with_then_an_approval_then_its_revocation(ws, client):
    stored = verified(ws, client, GAME62.replace("Volume = {63}", "Volume = {36}") + "\n")["Game62"]
    assert stored["status"] == "needs_review" and stored["issues"] == ["volume: missing evidence or mismatch"]
    detail = api.entry(ws, "Game62")
    assert detail.status == "needs_review" and detail.issues == stored["issues"]
    assert detail.closest == closest_candidate(detail.fields, stored) == stored["candidates"][0]
    assert detail.closest["issues"] == ["volume: missing evidence or mismatch"]
    assert keys(api.review_queue(ws, all_entries=True)) == ["Game62"]

    review = dict(reviewer="@fixture", source="the journal's page", note="volume 36 is what the issue prints",
                  github_login="fixture", github_id=1)
    evidence = dict(pdf_sha256="0" * 64, fields={"volume": {"page": 1, "quote": "Vol. 36"}})
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        cache.put(ws.bib, load_entries(ws.bib)["Game62"], dict(stored, external_evidence=evidence))
        record_approval(cache, ws.bib, "Game62", detail.fingerprint, review)
        approved = api.entry(ws, "Game62")
        assert approved.status == "human_verified" and approved.human_review == review
        assert approved.external_evidence == evidence and approved.candidates == stored["candidates"]
        assert api.review_queue(ws, all_entries=True) == []
        records, status = record_revocation(cache, ws.bib, "Game62", "the volume was misread", "@fixture")
    finally:
        cache.close()
    revoked = api.entry(ws, "Game62")
    assert len(records) == 1 and status == "needs_review" == revoked.status
    assert revoked.human_review is None and revoked.revoked_approval["human_review"] == review
    assert revoked.revoked_approval["reason"] == "the volume was misread" and "revoked" in revoked.issues[0]
    assert revoked.external_evidence == evidence
    assert keys(api.review_queue(ws, all_entries=True)) == ["Game62"]


def test_entry_gives_the_format_findings_field_by_field(tmp_path):
    ws = Workspace(tmp_path)
    book = KAHA12.replace("New York, {NY}", "New York, NY").replace("Year = {2012}", "Abstract = {x},\n\tYear = {2012}")
    ws.bib.write_text(ZOLL90.replace("1053--1065", "1053-1065") + "\n\n" + book + "\n", encoding="utf-8")
    found = {item.field: item for item in api.entry(ws, "Kaha12").format}
    assert set(found) == {"address", "abstract"}
    assert (found["address"].current, found["address"].corrected) == ("New York, NY", "New York, {NY}")
    assert (found["abstract"].current, found["abstract"].corrected) == ("x", None)
    assert "remove" in found["abstract"].message
    pages = api.entry(ws, "Zoll90").format
    assert [(item.field, item.current, item.corrected) for item in pages] == [("pages", "1053-1065", "1053--1065")]
    with pytest.raises(CdlbibError, match="no entry Nope99"):
        api.entry(ws, "Nope99")


def test_key_findings_count_the_other_entries_with_the_same_authors_and_year(tmp_path):
    ws = Workspace(tmp_path)
    second = ZOLL90.replace("{Zoll90,", "{Zoll90b,").replace("Students' misunderstandings", "More misunderstandings")
    second = second.replace("\tDoi = {10.1002/tea.3660271011},\n", "")
    ws.bib.write_text(ZOLL90.replace("{Zoll90,", "{Zoll90a,") + "\n\n" + second + "\n", encoding="utf-8")
    assert api.entry(ws, "Zoll90a").format == [] and api.entry(ws, "Zoll90b").format == []
    ws.bib.write_text(ZOLL90.replace("{Zoll90,", "{Zoll90a,") + "\n", encoding="utf-8")     # alone: no suffix
    assert [(item.field, item.current, item.corrected) for item in api.entry(ws, "Zoll90a").format] == [
        ("key", "Zoll90a", "Zoll90")]


def test_check_format_exposes_the_formatters_values_and_keeps_its_fields(tmp_path):
    ws = Workspace(tmp_path)
    ws.bib.write_text(ZOLL90.replace("1053--1065", "1053-1065") + "\n\n"
                      + KAHA12.replace("New York, {NY}", "New York, NY") + "\n", encoding="utf-8")
    result = api.check_format(ws)
    assert not result.ok and sorted(result.errors) == ["Kaha12", "Zoll90"] and result.failure == ""
    assert result.corrections == {"Zoll90": {"pages": "1053--1065"}, "Kaha12": {"address": "New York, {NY}"}}
    ws.bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    clean = api.check_format(ws)
    assert clean.ok and clean.errors == [] and clean.corrections == {}


# --- the review queue --------------------------------------------------------------------------

def test_review_queue_is_the_changed_entries_that_are_not_accepted(ws, tmp_path):
    reference = tmp_path / "reference.bib"
    renamed = ZOLL90.replace("{Zoll90,", "{Zoller1990,")              # a key-only difference is not a change
    reference.write_text(renamed + "\n\n" + KAHA12 + "\n", encoding="utf-8")
    queue = api.review_queue(ws, reference=str(reference))
    assert keys(queue) == ["GlocBets08", "TeneEtal11"]
    assert queue[0].status == "pending" and queue[0].raw == GLOC08 and queue[0].format is None
    assert queue[0].fingerprint == load_entries(ws.bib)["GlocBets08"]["fingerprint"]
    assert keys(api.review_queue(ws, all_entries=True)) == ["Zoll90", "Kaha12", "GlocBets08", "TeneEtal11"]
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        record_approval(cache, ws.bib, "GlocBets08", queue[0].fingerprint,
                        dict(reviewer="@fixture", source="publisher page", note="all fields checked"))
    finally:
        cache.close()
    assert keys(api.review_queue(ws, reference=str(reference))) == ["TeneEtal11"]
    with pytest.raises(CdlbibError, match="could not be selected"):
        api.review_queue(ws, reference=str(tmp_path / "missing.bib"))


# --- revision ----------------------------------------------------------------------------------

def test_revision_changes_with_the_bibliography_the_database_and_the_ledger(ws):
    start = api.revision(ws)
    assert api.revision(ws) == start and start[1:] == (None, None, None)
    ws.bib.write_text(TEXT + "% a note\n", encoding="utf-8")
    edited = api.revision(ws)
    assert edited != start and edited[1:] == start[1:]
    fingerprint = load_entries(ws.bib)["Kaha12"]["fingerprint"]
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        review = dict(reviewer="@fixture", source="the book itself", note="title page checked")
        record_approval(cache, ws.bib, "Kaha12", fingerprint, review)
        approved = api.revision(ws)
        assert approved[0] == edited[0] and approved[1] is not None and approved != edited
        from cdlbib.verification import revocation_ledger
        record_revocation(cache, ws.bib, "Kaha12", "wrong edition", "@fixture")
        assert revocation_ledger(str(ws.bib)).is_file()
        revoked = api.revision(ws)
        assert revoked[3] is not None and approved[3] is None and revoked != approved
    finally:
        cache.close()


# --- the state of the library ------------------------------------------------------------------

def test_state_of_a_folder_that_is_not_a_checkout(ws):
    state = api.library_state(ws)
    assert (state.root, state.managed, state.origin) == (ws.root, False, Origin.NAMED)
    assert state.branch is None and state.pending is None and state.unrelated is None
    assert state.new_commits is None and state.interrupted is None and state.pull_request is None
    assert any("not a git checkout of its own" in note for note in state.notes)
    refreshed = api.library_state(ws, refresh=True)                 # nothing to ask anyone about
    assert not refreshed.refreshed and refreshed.pull_request is None


def test_state_of_a_users_own_checkout_lists_unsent_and_unrelated_changes(checkout):
    ws, _ = checkout
    state = api.library_state(ws)
    assert (state.branch, state.pending, state.unrelated, state.managed) == ("master", [], [], False)
    ws.bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    (ws.root / "verification" / "note.json").write_text("{}\n", encoding="utf-8")
    (ws.root / "README.md").write_text("mine\n", encoding="utf-8")
    api.entries(ws)
    api.save_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"), api.entry(ws, "Zoll90").fingerprint)   # makes .bibcheck/
    state = api.library_state(ws)
    assert state.pending == ["cdl.bib", "verification/note.json"] and state.unrelated == ["README.md"]
    assert state.new_commits is None and state.notes == []          # no upstream is tracked for a library of the user's
    git(ws.root, "switch", "-q", "--detach")
    assert api.library_state(ws).branch is None


def test_state_of_the_managed_library_counts_new_upstream_commits_as_update_does(managed):
    home, upstream = managed
    ws = Workspace(library.download())
    assert api.is_managed(ws)
    state = api.library_state(ws)
    assert (state.managed, state.origin, state.branch) == (True, Origin.MANAGED, "master")
    assert (state.new_commits, state.new_entries, state.local_commits, state.pending) == (0, 0, 0, [])
    assert state.interrupted is None and state.notes == [] and not state.refreshed

    source = Path(upstream).parent / "upstream-work"                # two new commits, one new entry
    (source / "cdl.bib").write_text(ZOLL90 + "\n\n" + KAHA12 + "\n", encoding="utf-8")
    git(source, "add", "cdl.bib"); git(source, "commit", "-qm", "add a book")
    (source / "cdl.bib").write_text(ZOLL90 + "\n\n" + KAHA12 + "\n% tidy\n", encoding="utf-8")
    git(source, "add", "cdl.bib"); git(source, "commit", "-qm", "a comment")
    git(source, "push", "-q", str(upstream), "master")

    before, checked = tree(ws.root), library.read_state().last_check
    stale = api.library_state(ws)                                   # nothing is fetched unless asked
    assert (stale.new_commits, stale.new_entries, stale.refreshed) == (0, 0, False)
    lines = []
    fresh = api.library_state(ws, refresh=True, progress=lines.append)
    assert (fresh.new_commits, fresh.new_entries, fresh.local_commits, fresh.refreshed) == (2, 1, 0, True)
    assert fresh.notes == [] and lines == [] and fresh.pull_request is None
    assert tree(ws.root) == before and git(ws.root, "status", "--porcelain") == ""          # the library is as it was
    assert library.read_state().last_check == checked and library.backups() == []           # and no check was recorded
    assert api.library_state(ws).new_commits == 2                    # the refs now say so without asking again
    assert library.behind(ws).new_commits == 2

    ws.bib.write_text(ZOLL90.replace("{27}", "{28}") + "\n", encoding="utf-8")              # an unsent edit
    unsent = api.library_state(ws)
    assert unsent.pending == ["cdl.bib"] and unsent.unrelated == [] and unsent.new_commits == 2
    with pytest.raises(UpdateNeedsDecision) as asked:               # update counts with the same helper
        api.update(ws, force=True)
    assert asked.value.new_commits == unsent.new_commits == 2 and asked.value.changed == unsent.pending
    result = api.update(ws, decision="discard", force=True, seen=asked.value.seen)
    assert result.action == "updated" and result.new_commits == 2
    after = api.library_state(ws)
    assert (after.new_commits, after.new_entries, after.pending) == (0, 0, [])
    assert after.last_check is not None


def test_state_says_when_the_upstream_cannot_be_asked(managed):
    home, upstream = managed
    ws = Workspace(library.download())
    git(ws.root, "remote", "set-url", "origin", str(Path(upstream).parent / "gone.git"))
    state = api.library_state(ws, refresh=True)
    assert not state.refreshed and state.new_commits == 0
    assert any(note.startswith("the upstream was not asked: git fetch failed") for note in state.notes)


def test_behind_is_only_for_the_managed_library(ws, managed):
    library.download()
    with pytest.raises(CdlbibError, match="Only the library cdlbib manages"):
        library.behind(ws)
    state = api.library_state(ws)
    assert state.new_commits is None and state.last_check is None


def test_the_desk_never_prints(ws, capsys):
    api.entries(ws); api.search(ws, "memory"); api.entry(ws, "Kaha12"); api.review_queue(ws, all_entries=True)
    api.preview_edit(ws, "Kaha12", KAHA12.replace("2012", "2013")); api.library_state(ws); api.revision(ws)
    api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "2013"), api.entry(ws, "Kaha12").fingerprint)
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
    assert os.environ["CDLBIB_HOME"] and conftest.no_real_library_touched() is None
