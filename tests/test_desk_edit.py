"""Editing one entry by hand: api.preview_edit and api.save_edit, and approval/revocation
around an edit.

Real files, a real SQLite cache seeded through the verifier's own record_approval, the real
managed library (local bare upstream) and, where a reviewer's name is needed, the real gh
login (skipped with the reason when nobody is logged in). No mocks; never the live cdl.bib.
"""
import json
from pathlib import Path

import pytest

import conftest
from cdlbib import api, complete, desk, library, writer
from cdlbib.errors import ApprovalRefused, CdlbibError, EditRefused, IdentityUnavailable
from cdlbib.verification import Cache, load_entries, record_approval
from cdlbib.workspace import Workspace

from test_library import managed  # noqa: F401

ZOLL90 = conftest.ZOLL90
KAHA12 = ("@book{Kaha12,\n\tAddress = {New York, {NY}},\n\tAuthor = {M J Kahana},\n\tPublisher = {Oxford University "
          "Press},\n\tTitle = {Foundations of human memory},\n\tYear = {2012}}")
TALK = ("@inproceedings{MannKaha12,\n\tAuthor = {J R Manning and M J Kahana},\n\tBooktitle = {Proceedings of the "
        "Annual Meeting of the Cognitive Science Society},\n\tTitle = {Interpreting semantic clustering effects in "
        "free recall},\n\tYear = {2012}}")
PREFIX = "% Maintained by hand: {braces} and Zoll90 are mentioned here\n@comment{keep @article{Zoll90, and this}}\n\n"
SUFFIX = "\n\n% trailing note\n"
TEXT = PREFIX + ZOLL90 + "\n\n" + KAHA12 + "\n\n" + TALK + SUFFIX
REVIEW = dict(reviewer="@fixture", source="the journal's page", note="every field checked against the issue",
              github_login="fixture", github_id=1)


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "cdl.bib").write_text(TEXT, encoding="utf-8")
    return Workspace(root)


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(Path(root).rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(root).parts}


def fingerprint(ws, key):
    return load_entries(ws.bib)[key]["fingerprint"]


def approve(ws, key):
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        return record_approval(cache, ws.bib, key, fingerprint(ws, key), REVIEW)
    finally:
        cache.close()


def status(ws, key):
    return {item.key: item.status for item in api.entries(ws)}[key]


# --- preview -----------------------------------------------------------------------------------

def test_preview_shows_the_diff_and_the_formatters_values_and_writes_nothing(ws):
    before = tree(ws.root)
    edited = (ZOLL90.replace("1053--1065", "1053-1065").replace("Students' misunderstandings", "students' Misunderstandings")
              .replace("\tYear = {1990}", "\tAbstract = {not kept},\n\tYear = {1990}"))
    preview = api.preview_edit(ws, "Zoll90", edited)
    assert preview.ok and preview.problems == [] and preview.changed
    assert (preview.key, preview.new_key, preview.key_change, preview.duplicate_of) == ("Zoll90", "Zoll90", None, None)
    assert preview.fingerprint == fingerprint(ws, "Zoll90") and preview.new_fingerprint != preview.fingerprint
    lines = preview.diff.splitlines()
    assert lines[:2] == ["--- Zoll90", "+++ Zoll90"]
    assert "-\tPages = {1053--1065}," in lines and "+\tPages = {1053-1065}," in lines
    assert "+\tAbstract = {not kept}," in lines and " \tVolume = {27}," in lines
    found = {item.field: (item.current, item.corrected) for item in preview.format}
    assert found == {"pages": ("1053-1065", "1053--1065"), "abstract": ("not kept", None),
                     "title": ("students' Misunderstandings and misconceptions in college freshman chemistry (general "
                               "and organic)", "Students' misunderstandings and misconceptions in college freshman "
                               "chemistry (general and organic)")}
    assert preview.corrected_raw == ZOLL90                       # what the house formatter would write
    assert (preview.status_now, preview.status, preview.invalidates, preview.affected) == ("pending", "pending", None, [])
    assert tree(ws.root) == before                               # not even a lock or a database


def test_preview_of_the_text_as_it_is(ws):
    preview = api.preview_edit(ws, "Kaha12", "\n" + KAHA12 + "\n\n")
    assert preview.ok and not preview.changed and preview.diff == "" and preview.format == []
    assert preview.new_fingerprint == preview.fingerprint and preview.corrected_raw == KAHA12


def test_preview_of_a_changed_key_is_a_rename_or_a_collision(ws):
    rename = api.preview_edit(ws, "Zoll90", ZOLL90.replace("{Zoll90,", "{Zoller1990,"))
    assert rename.ok and rename.key_change == desk.KeyChange("Zoll90", "Zoller1990", "rename")
    assert rename.new_fingerprint == rename.fingerprint          # the key is not part of the content
    assert [(item.field, item.current, item.corrected) for item in rename.format] == [("key", "Zoller1990", "Zoll90")]
    assert rename.diff.splitlines()[:4] == ["--- Zoll90", "+++ Zoller1990", "@@ -1,4 +1,4 @@", "-@article{Zoll90,"]
    clash = api.preview_edit(ws, "Zoll90", ZOLL90.replace("{Zoll90,", "{Kaha12,"))
    assert not clash.ok and clash.key_change == desk.KeyChange("Zoll90", "Kaha12", "collision")
    assert clash.problems == ["The key Kaha12 already belongs to another entry"]
    assert clash.status is None and clash.new_fingerprint is None and clash.status_now == "pending"


def test_preview_of_a_new_entry_names_a_duplicate_and_a_key_in_use(ws):
    again = ZOLL90.replace("{Zoll90,", "{Zoll90b,")
    twin = api.preview_edit(ws, None, again)
    assert twin.ok and twin.duplicate_of == "Zoll90" and twin.key is None and twin.new_key == "Zoll90b"
    assert twin.fingerprint is None and twin.status_now is None and twin.status == "pending"
    assert twin.diff.splitlines()[:2] == ["--- (new entry)", "+++ Zoll90b"]
    retitled = again.replace("\tDoi = {10.1002/tea.3660271011},\n", "").replace("Students' misunderstandings", "More")
    assert api.preview_edit(ws, None, retitled).duplicate_of is None
    taken = api.preview_edit(ws, None, ZOLL90)
    assert not taken.ok and taken.key_change == desk.KeyChange("Zoll90", "Zoll90", "collision")
    assert taken.problems == ["The key Zoll90 is already in use; a new entry needs a key of its own"]
    same_title = api.preview_edit(ws, "Kaha12", KAHA12.replace(
        "Foundations of human memory", "Interpreting semantic clustering effects in free recall").replace(
        "M J Kahana", "X Manning and Y Kahana"))
    assert same_title.duplicate_of == "MannKaha12"               # same title and surnames, no identifier needed


@pytest.mark.parametrize("raw,said", [
    (ZOLL90[:-1], "Unterminated entry"),
    (ZOLL90.replace("Volume = {27}", "Volume = {27"), "cannot be read as one entry"),
    (ZOLL90.replace("\tNumber = {10},\n", "\tNumber = {10},\n\tNumber = {11},\n"), "Duplicate field in Zoll90"),
    (ZOLL90 + "\n\n" + KAHA12.replace("Kaha12", "Other12"), "exactly one entry"),
    ("% a remark\n" + ZOLL90, "must be one BibTeX entry"),
    ("just some words", "must be one BibTeX entry"),
    ("", "must be one BibTeX entry"),
    ("@comment{Zoll90, hidden}", "must be one BibTeX entry"),
    ("@string{jrst = {Journal of Research in Science Teaching}}", "must be one BibTeX entry"),
])
def test_text_that_is_not_one_entry_is_a_problem_not_an_exception(ws, raw, said):
    before = tree(ws.root)
    preview = api.preview_edit(ws, "Zoll90", raw)
    assert not preview.ok and len(preview.problems) == 1 and said in preview.problems[0]
    assert preview.status is None and preview.format == [] and preview.status_now == "pending"
    with pytest.raises(EditRefused) as refused:
        api.save_edit(ws, "Zoll90", raw, fingerprint(ws, "Zoll90"))
    assert said in str(refused.value) and refused.value.problems == preview.problems
    assert tree(ws.root)["cdl.bib"] == before["cdl.bib"]


def test_preview_of_an_entry_that_is_gone(ws):
    preview = api.preview_edit(ws, "Nope99", ZOLL90)
    assert preview.problems == ["Nope99 is no longer in the library"] and preview.fingerprint is None


def test_preview_says_which_approval_an_edit_loses_and_finds_an_earlier_result_again(ws):
    approve(ws, "Zoll90")
    edited = ZOLL90.replace("{27}", "{28}")
    preview = api.preview_edit(ws, "Zoll90", edited)
    assert (preview.status_now, preview.status, preview.invalidates) == ("human_verified", "pending", "human_verified")
    spaced = api.preview_edit(ws, "Zoll90", ZOLL90.replace("\tVolume = {27}", "\tVolume  =  {27}"))
    assert spaced.invalidates == "human_verified"                # the fingerprint covers the exact text
    renamed = api.preview_edit(ws, "Zoll90", ZOLL90.replace("{Zoll90,", "{Zoll90x,"))
    assert (renamed.status, renamed.invalidates) == ("human_verified", None)      # but not the key
    api.save_edit(ws, "Zoll90", edited, preview.fingerprint)
    assert status(ws, "Zoll90") == "pending" and api.entry(ws, "Zoll90").human_review is None
    back = api.preview_edit(ws, "Zoll90", ZOLL90)                 # exactly the approved content again
    assert (back.status_now, back.status, back.invalidates) == ("pending", "human_verified", None)
    api.save_edit(ws, "Zoll90", ZOLL90, back.fingerprint)
    assert status(ws, "Zoll90") == "human_verified" and api.entry(ws, "Zoll90").human_review == REVIEW


PARENT = "@book{Proc12,\n\tEditor = {N Miyake and D Peebles},\n\tPublisher = {Cognitive Science Society},\n\tTitle = {Proceedings of the 34th meeting},\n\tYear = {2012}}"
CHILD = "@incollection{MannKaha12,\n\tAuthor = {J R Manning and M J Kahana},\n\tCrossref = {Proc12},\n\tTitle = {Interpreting semantic clustering effects in free recall}}"


def test_preview_names_the_other_entries_whose_fingerprint_changes(tmp_path):
    ws = Workspace(tmp_path)
    ws.bib.write_text(PARENT + "\n\n" + CHILD + "\n\n" + ZOLL90 + "\n", encoding="utf-8")
    approve(ws, "MannKaha12")
    child = fingerprint(ws, "MannKaha12")
    preview = api.preview_edit(ws, "Proc12", PARENT.replace("34th", "34th annual"))
    assert preview.ok and preview.affected == [desk.Affected("MannKaha12", "human_verified", "pending")]
    assert api.preview_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}")).affected == []
    orphaned = api.preview_edit(ws, "Proc12", PARENT.replace("{Proc12,", "{Proc2012,"))
    assert not orphaned.ok and "Missing inherited entry Proc12 for MannKaha12" in orphaned.problems[0]
    with pytest.raises(EditRefused, match="Missing inherited entry"):
        api.save_edit(ws, "Proc12", PARENT.replace("{Proc12,", "{Proc2012,"), preview.fingerprint)
    api.save_edit(ws, "Proc12", PARENT.replace("34th", "34th annual"), preview.fingerprint)
    assert fingerprint(ws, "MannKaha12") != child and status(ws, "MannKaha12") == "pending"
    assert desk.parsed(ws) == load_entries(ws.bib)


def test_a_library_with_string_definitions_is_previewed_and_saved_exactly(tmp_path):
    ws = Workspace(tmp_path)
    text = '@string{jrst = "Journal of Research in Science Teaching"}\n\n' + ZOLL90.replace(
        "{Journal of Research in Science Teaching}", "jrst") + "\n\n" + KAHA12 + "\n"
    ws.bib.write_text(text, encoding="utf-8")
    edited = KAHA12.replace("2012", "2013")
    preview = api.preview_edit(ws, "Kaha12", edited)
    api.save_edit(ws, "Kaha12", edited, preview.fingerprint)
    assert ws.bib.read_text(encoding="utf-8") == text.replace(KAHA12, edited)
    assert preview.new_fingerprint == fingerprint(ws, "Kaha12") and desk.parsed(ws) == load_entries(ws.bib)


# --- save --------------------------------------------------------------------------------------

@pytest.mark.parametrize("newline,final,bom", [("\n", True, False), ("\r\n", True, True), ("\r\n", False, False),
                                               ("\n", False, True)])
def test_save_replaces_exactly_one_entrys_bytes(tmp_path, newline, final, bom):
    ws = Workspace(tmp_path)
    text = (TEXT if final else TEXT.rstrip("\n")).replace("\n", newline)
    ws.bib.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    before = ws.bib.read_bytes()
    edited = KAHA12.replace("Foundations of human memory", "Foundations of human memory: 2nd edition")
    old, new = KAHA12.replace("\n", newline).encode(), edited.replace("\n", newline).encode()
    assert before.count(old) == 1
    applied = api.save_edit(ws, "Kaha12", "\n" + edited + "\n", fingerprint(ws, "Kaha12"))
    assert (applied.written, applied.renamed, applied.refused, applied.backup, applied.notes) == (["Kaha12"], {}, [], None, [])
    assert ws.bib.read_bytes() == before.replace(old, new)       # every other byte, comments included, as it was
    assert applied.saved_copy.read_bytes() == before and applied.saved_copy.parent == ws.work / "edits"
    found = load_entries(ws.bib)
    assert found["Kaha12"]["raw"] == edited.replace("\n", newline)
    for key in ("Zoll90", "MannKaha12"):
        assert found[key]["raw"].encode() in before
    assert desk.parsed(ws) == found and not ws.key_renames.exists()
    assert not list(tmp_path.glob(".cdl.bib-*")) and not (ws.work / "edits" / writer.PENDING).exists()


def test_save_refuses_a_stale_fingerprint_and_writes_nothing(ws):
    opened = api.entry(ws, "Zoll90")
    ws.bib.write_text(TEXT.replace("Volume = {27}", "Volume = {29}"), encoding="utf-8")     # someone else edited it
    before = tree(ws.root)
    with pytest.raises(EditRefused, match="Zoll90 was changed since it was opened; nothing was written"):
        api.save_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"), opened.fingerprint)
    with pytest.raises(EditRefused, match="changed since it was opened"):
        api.save_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"))                         # no fingerprint is not a pass
    assert tree(ws.root)["cdl.bib"] == before["cdl.bib"] and not (ws.work / "edits").exists()
    with pytest.raises(EditRefused, match="Nope99 is no longer in the library"):
        api.save_edit(ws, "Nope99", ZOLL90, opened.fingerprint)
    api.save_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"), api.entry(ws, "Zoll90").fingerprint)
    assert "Volume = {28}" in ws.bib.read_text(encoding="utf-8")


def test_an_edit_of_another_entry_does_not_make_this_one_stale(ws):
    opened = api.entry(ws, "Zoll90")
    api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "2013"), fingerprint(ws, "Kaha12"))
    applied = api.save_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"), opened.fingerprint)
    assert applied.written == ["Zoll90"]


@pytest.mark.parametrize("key,old,new", [
    ("Kaha12", KAHA12, KAHA12.replace("Oxford University Press", "Oxford University Press, USA")),
    ("MannKaha12", TALK, TALK.replace("Year = {2012}", "Pages = {1--6},\n\tYear = {2012}")),
])
def test_entries_of_any_type_are_saved(ws, key, old, new):
    applied = api.save_edit(ws, key, new, fingerprint(ws, key))
    assert applied.written == [key] and ws.bib.read_text(encoding="utf-8") == TEXT.replace(old, new)


def test_save_does_not_wait_for_the_format_check_and_never_touches_other_keys(ws):
    """A second work by the same author and year: the format checker would now want Zoll90a and
    Zoll90b. The save writes the text as typed and leaves the other entry's key alone."""
    second = ZOLL90.replace("{Zoll90,", "{Zoll90b,").replace("Students' misunderstandings", "Further misunderstandings")
    second = second.replace("\tDoi = {10.1002/tea.3660271011},\n", "").replace("1053--1065", "1053-1065")
    preview = api.preview_edit(ws, None, second)
    assert preview.ok and {item.field for item in preview.format} == {"pages"}
    applied = api.save_edit(ws, None, second)
    assert (applied.written, applied.renamed) == (["Zoll90b"], {}) and not ws.key_renames.exists()
    assert ws.bib.read_text(encoding="utf-8") == TEXT + "\n" + second + "\n"
    assert [(item.field, item.corrected) for item in api.entry(ws, "Zoll90").format] == [("key", "Zoll90a")]
    assert not api.check_format(ws).ok                           # the gate, not the editor, holds a send back


def test_a_new_entry_is_appended_and_needs_a_key_of_its_own(tmp_path):
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    assert api.save_edit(ws, None, KAHA12).written == ["Kaha12"]
    assert ws.bib.read_text(encoding="utf-8") == KAHA12
    assert api.save_edit(ws, None, TALK + "\n").written == ["MannKaha12"]
    assert ws.bib.read_text(encoding="utf-8") == KAHA12 + "\n\n" + TALK
    before = ws.bib.read_bytes()
    with pytest.raises(EditRefused, match="The key Kaha12 is already in use"):
        api.save_edit(ws, None, KAHA12.replace("2012", "2013"))
    assert ws.bib.read_bytes() == before and status(ws, "MannKaha12") == "pending"


def test_a_changed_key_is_a_rename_recorded_in_the_ledger(ws):
    ws.key_renames.parent.mkdir()
    prior = {"old_key": "Previous", "new_key": "Current", "commit": "existing"}
    ws.key_renames.write_text(json.dumps([prior]), encoding="utf-8")
    approve(ws, "Zoll90")
    renamed = ZOLL90.replace("{Zoll90,", "{Zoller1990,")
    applied = api.save_edit(ws, "Zoll90", renamed, fingerprint(ws, "Zoll90"))
    assert (applied.written, applied.renamed) == (["Zoller1990"], {"Zoll90": "Zoller1990"})
    assert ws.bib.read_text(encoding="utf-8") == TEXT.replace(ZOLL90, renamed)
    assert "% Maintained by hand: {braces} and Zoll90 are mentioned here" in ws.bib.read_text(encoding="utf-8")
    records = json.loads(ws.key_renames.read_text(encoding="utf-8"))
    assert records[0] == prior and len(records) == 2
    assert (records[1]["old_key"], records[1]["new_key"], records[1]["commit"]) == ("Zoll90", "Zoller1990", None)
    assert records[1]["reason"] == "Citation key edited by hand"
    assert status(ws, "Zoller1990") == "human_verified"          # the approval is of the content, not the key
    with pytest.raises(EditRefused, match="The key Kaha12 already belongs to another entry"):
        api.save_edit(ws, "Zoller1990", renamed.replace("{Zoller1990,", "{Kaha12,"), fingerprint(ws, "Zoller1990"))
    assert len(json.loads(ws.key_renames.read_text(encoding="utf-8"))) == 2


def test_the_same_text_writes_nothing(ws):
    before = tree(ws.root)
    applied = api.save_edit(ws, "Kaha12", KAHA12, fingerprint(ws, "Kaha12"))
    assert applied.written == [] and applied.saved_copy is None
    assert applied.notes == ["the text is what the library already holds; nothing was written"]
    assert tree(ws.root)["cdl.bib"] == before["cdl.bib"] and not (ws.work / "edits").exists()


def test_text_that_is_twice_in_the_file_is_not_replaced(tmp_path):
    ws = Workspace(tmp_path)
    ws.bib.write_text(ZOLL90 + "\n@comment{" + ZOLL90 + "}\n", encoding="utf-8")
    before = ws.bib.read_bytes()
    preview = api.preview_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"))
    assert preview.problems == ["The text of Zoll90 appears 2 times in the file, so it cannot be replaced safely"]
    with pytest.raises(EditRefused, match="appears 2 times"):
        api.save_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"), preview.fingerprint)
    assert ws.bib.read_bytes() == before


def test_the_newest_twenty_copies_are_kept_and_each_holds_the_state_before(ws):
    states = []
    for number in range(23):
        states.append(ws.bib.read_bytes())
        applied = api.save_edit(ws, "Kaha12", KAHA12.replace("2012", str(1990 + number)), fingerprint(ws, "Kaha12"))
        assert applied.saved_copy.read_bytes() == states[-1]
    copies = sorted(path for path in (ws.work / "edits").iterdir())
    assert len(copies) == writer.KEEP_EDITS == 20 and all(path.name.endswith("-cdl.bib") for path in copies)
    assert [path.read_bytes() for path in copies] == states[3:]


def test_a_library_that_cannot_be_written_is_a_cdlbib_error_and_stays_whole(ws):
    opened = fingerprint(ws, "Kaha12")
    before = ws.bib.read_bytes()
    ws.root.chmod(0o555)
    try:
        with pytest.raises(CdlbibError):
            api.save_edit(ws, "Kaha12", KAHA12.replace("2012", "2013"), opened)
        assert ws.bib.read_bytes() == before
    finally:
        ws.root.chmod(0o755)
    assert not list(ws.root.glob(".cdl.bib-*"))


def test_a_save_in_the_managed_library_is_backed_up_and_undone(managed):
    ws = Workspace(library.download())
    before = ws.bib.read_bytes()
    edited = ZOLL90.replace("{27}", "{28}")
    applied = api.save_edit(ws, "Zoll90", edited, fingerprint(ws, "Zoll90"))
    assert applied.written == ["Zoll90"] and applied.saved_copy is None and applied.backup.path.is_dir()
    assert ws.bib.read_bytes() == before.replace(ZOLL90.encode(), edited.encode())
    assert not (ws.work / "edits").exists() and not (ws.work / "lock").exists()      # the managed lock and backups
    assert library.interrupted() is None and api.completion_undo_checkpoint() == applied.backup.stamp
    restored = api.undo()
    assert restored.restored.stamp == applied.backup.stamp and ws.bib.read_bytes() == before
    other = ws.root / "other.bib"
    other.write_text(KAHA12 + "\n", encoding="utf-8")
    with pytest.raises(CdlbibError, match="managed backup cannot protect this named bibliography"):
        api.save_edit(Workspace.for_bib(other), "Kaha12", KAHA12.replace("2012", "2013"),
                      load_entries(other)["Kaha12"]["fingerprint"])
    assert other.read_text(encoding="utf-8") == KAHA12 + "\n"


# --- approval and revocation around an edit ------------------------------------------------------

@pytest.fixture
def reviewer():
    from cdlbib import identity
    try:
        return identity.current()
    except IdentityUnavailable as exc:
        pytest.skip(f"no GitHub login for a real approval: {exc}")


def test_approve_then_edit_is_pending_and_an_approval_needs_the_current_fingerprint(ws, reviewer):
    opened = api.entry(ws, "Zoll90")
    stored = api.approve(ws, "Zoll90", opened.fingerprint, "the journal's page", "all fields checked")
    assert stored["human_review"]["reviewer"] == reviewer.handle and stored["human_review"]["github_id"] == reviewer.id
    approved = api.entry(ws, "Zoll90")
    assert approved.status == "human_verified" and approved.human_review["source"] == "the journal's page"
    api.save_edit(ws, "Zoll90", ZOLL90.replace("{27}", "{28}"), opened.fingerprint)
    edited = api.entry(ws, "Zoll90")
    assert edited.status == "pending" and edited.human_review is None and edited.fingerprint != opened.fingerprint
    with pytest.raises(ApprovalRefused, match="Entry changed since review; approval rejected"):
        api.approve(ws, "Zoll90", opened.fingerprint, "the journal's page", "approved from a stale screen")
    assert api.entry(ws, "Zoll90").status == "pending"


def test_revoke_compares_the_fingerprint_it_was_shown(ws, reviewer):
    opened = api.entry(ws, "Kaha12")
    api.approve(ws, "Kaha12", opened.fingerprint, "the book itself", "title page checked")
    with pytest.raises(ApprovalRefused, match="Entry changed since review; revocation rejected"):
        api.revoke(ws, "Kaha12", "shown an older text", expected_fingerprint="v2:" + "0" * 64)
    assert api.entry(ws, "Kaha12").status == "human_verified"
    result = api.revoke(ws, "Kaha12", "wrong edition", expected_fingerprint=opened.fingerprint)
    assert len(result.records) == 1 and result.status == "needs_review"
    revoked = api.entry(ws, "Kaha12")
    assert revoked.status == "needs_review" and revoked.revoked_approval["reason"] == "wrong edition"
    assert revoked.revoked_approval["revoked_by"] == reviewer.handle
    assert [item.key for item in api.review_queue(ws, all_entries=True)][:2] == ["Zoll90", "Kaha12"]
    with pytest.raises(ApprovalRefused):                          # the revoked approval cannot be replayed
        api.approve(ws, "Kaha12", opened.fingerprint, "the book itself", "title page checked")
    assert api.revoke(ws, "Kaha12", "again").records == []        # without a fingerprint: as before
