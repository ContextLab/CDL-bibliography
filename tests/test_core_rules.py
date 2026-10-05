"""Core rules both interfaces rely on: no Force field reaches the file or passes the gate;
model evidence survives a failed store; the writer says what it did with each accepted
proposal; one name-by-name choice; one install/fork decision; what completion would look at;
an entry without a title is a finding, not a crash; shared wording.

Real files, real checkouts, the real writer and checker, the saved responses with the network
refused, a real (failing) package installation. No mocks.
"""
import json
import stat
from pathlib import Path

import pytest

import conftest
from cdlbib import api, cli, complete, deps, intake, prompts
from cdlbib.errors import (CdlbibError, CompletionRefused, EditRefused, GateFailed, MissingDependency,
                           NeedsConfirmation, PublishRefused)
from cdlbib.verification import load_entries
from cdlbib.workspace import Workspace

from test_complete_cli import refused_network
from test_complete_identify import client, CONTACT, library_entry  # noqa: F401
from test_desk import KAHA12, TEXT
from test_publish import checkout, state  # noqa: F401

ZOLL90 = conftest.ZOLL90
GAME62 = library_entry("Game62")
FORCED = ZOLL90.replace("\tYear = {1990}", "\tForce = {true},\n\tYear = {1990}")


@pytest.fixture
def offline(monkeypatch):
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "cdl.bib").write_text(TEXT, encoding="utf-8")
    return Workspace(root)


# --- 1. no Force ---------------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["Force = {true}", "force = {True}", "FORCE = {yes}", 'Force = "true"', "fOrCe = {0}"])
def test_an_edit_that_adds_a_force_field_is_a_problem_and_is_not_saved(ws, field):
    edited = ZOLL90.replace("\tYear = {1990}", f"\t{field},\n\tPages = {{1053-1065}},\n\tYear = {{1990}}").replace(
        "\tPages = {1053--1065},\n", "")
    before = ws.bib.read_bytes()
    preview = api.preview_edit(ws, "Zoll90", edited)
    assert not preview.ok and preview.problems == [f"Zoll90: {prompts.FORCE_REFUSED}"]
    assert "Force field is not allowed" in preview.problems[0]
    with pytest.raises(EditRefused, match="Force field is not allowed") as refused:
        api.save_edit(ws, "Zoll90", edited, preview.fingerprint)
    assert refused.value.problems == preview.problems and ws.bib.read_bytes() == before
    new = api.preview_edit(ws, None, edited.replace("{Zoll90,", "{Other90,"))
    assert new.problems == [f"Other90: {prompts.FORCE_REFUSED}"]
    with pytest.raises(EditRefused):
        api.save_edit(ws, None, edited.replace("{Zoll90,", "{Other90,"))
    assert ws.bib.read_bytes() == before


def test_a_title_that_mentions_force_is_not_a_force_field(ws):
    edited = KAHA12.replace("Foundations of human memory", "Foundations of human memory: force = mass times acceleration")
    preview = api.preview_edit(ws, "Kaha12", edited)
    assert preview.ok and api.save_edit(ws, "Kaha12", edited, preview.fingerprint).written == ["Kaha12"]


def test_a_recheck_and_the_writer_refuse_a_force_field(tmp_path, client, offline):
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    where = dict(mailto=CONTACT, database=str(client.cache.path))
    built = complete.propose(complete.Query.parse("10.1037/h0041332"), client, client.cache, ws=ws)
    forced = built.proposed_raw.replace("\tYear = {1962}", "\tForce = {true},\n\tYear = {1962}")
    assert forced != built.proposed_raw
    with pytest.raises(CompletionRefused, match="Game62: a Force field is not allowed"):
        api.recheck_proposal(ws, built, forced, **where)
    # a proposal carrying the field, however it was made, is refused by the writer itself
    from dataclasses import replace
    clean = complete._completion_fields(built)
    smuggled = replace(built, proposed_raw=forced, edited_fields=dict(clean))
    assert not complete.has_force(complete._completion_fields(smuggled))       # its own account of its fields is clean
    applied = api.apply_proposals(ws, [smuggled, replace(built, edited_fields=dict(clean, force="true"))])
    assert applied.written == [] and ws.bib.read_text(encoding="utf-8") == ""
    assert [(o.index, o.key, o.status, o.reason) for o in applied.outcomes] == [
        (0, "Game62", "refused", prompts.FORCE_REFUSED), (1, "Game62", "refused", prompts.FORCE_REFUSED)]
    with pytest.raises(CdlbibError, match="cannot have a 'force' field"):
        api.draft_manual(ws, {"title": "A title", "author": "A Smith", "year": "2020", "Force": "true"})
    assert api.apply_proposals(ws, [built]).written == ["Game62"]                # the same proposal without it is written


def test_an_entry_that_already_has_force_fails_the_gate_by_name(checkout, offline):
    ws, remote = checkout
    ws.bib.write_text(FORCED.replace("1053--1065", "1053-1065") + "\n\n" + GAME62 + "\n", encoding="utf-8")
    fmt = api.check_format(ws)
    assert not fmt.ok and fmt.forced == ["Zoll90"] and fmt.errors == ["Zoll90"] and fmt.failure == ""
    assert fmt.corrections == {"Zoll90": {"force": None}}       # the checker itself skipped the entry (its pages too)
    assert f"Zoll90: {prompts.FORCE_REFUSED}\n" in fmt.log
    check = api.check_library(ws, citations=False)
    assert not check.ok and check.format.forced == ["Zoll90"]
    found = {item.field: item for item in api.entry(ws, "Zoll90").format}
    assert set(found) == {"force"} and found["force"].message == prompts.FORCE_REFUSED and found["force"].corrected is None
    assert api.entry(ws, "Game62").format == []
    before, reports = state(ws.root), []
    with pytest.raises(GateFailed, match="not sent: fix the format errors") as failed:
        api.send_checked(ws, report=reports.append)
    assert failed.value.check.format.forced == ["Zoll90"] and reports[0].format.forced == ["Zoll90"]
    assert state(ws.root) == before
    # the command line names the entry
    from typer.testing import CliRunner
    shown = CliRunner().invoke(cli.app, ["--library", str(ws.root), "verify", "--no-citations"])
    assert shown.exit_code == 1 and f"Zoll90: {prompts.FORCE_REFUSED}" in shown.output
    # removing the field is the way through (and then the entry is checked like any other)
    opened = api.entry(ws, "Zoll90")
    api.save_edit(ws, "Zoll90", ZOLL90, opened.fingerprint)
    assert api.check_format(ws).ok and api.check_format(ws).forced == []


def test_the_frozen_library_fixture_holds_nineteen_force_entries_and_each_fails(tmp_path):
    import shutil
    ws = Workspace(tmp_path)
    shutil.copy(conftest.FROZEN_LIBRARY, ws.bib)
    fmt = api.check_format(ws)
    assert len(fmt.forced) == 19 and set(fmt.forced) <= set(fmt.errors)
    assert all(fmt.corrections[key]["force"] is None for key in fmt.forced)


# --- 2. model evidence that could not be stored ---------------------------------------------------

def model_draft(ws):
    """A hand-typed draft carrying model evidence of a (named, not read) PDF, as a model
    reading attaches it: enough for the real writer and the real evidence store."""
    draft = api.draft_manual(ws, {"title": "A typed paper on recall", "author": "Example, Ada", "year": "2001",
                                  "journal": "Memory"})
    draft.evidence = {"pdf_sha256": "ab" * 32, "reviewer": "model: test selection",
                      "fields": {"year": {"page": 1, "quote": "Published 2001"}}}
    return draft, intake.PdfIntake(path=Path("paper.pdf"), sha256="ab" * 32)


def test_evidence_that_cannot_be_stored_is_kept_on_disk_and_stored_by_a_retry(ws, tmp_path):
    draft, pdf = model_draft(ws)
    blocked = tmp_path / "a-folder-not-a-database"
    blocked.mkdir()
    done = api.accept_draft(ws, draft, pdf, database=blocked)             # the entry is written; the store cannot open
    assert done.written and done.key == "Exam01" and done.evidence_stored is False
    record = ws.work / "pending-evidence" / "Exam01.json"
    assert json.loads(record.read_text(encoding="utf-8")) == {"key": "Exam01", "fingerprint": done.fingerprint,
                                                               "evidence": done.evidence}
    assert stat.S_IMODE(record.stat().st_mode) == 0o600
    assert api.pending_evidence(ws) == [api.PendingEvidence("Exam01", done.fingerprint, False)]
    assert "external_evidence" not in api.entry(ws, "Exam01").result
    still = api.retry_evidence(ws, "Exam01", database=blocked)            # the same failure: kept
    assert still.evidence_stored is False and still.evidence_error and record.is_file() and still.applied is None
    again = api.retry_evidence(ws, "Exam01")
    assert (again.key, again.fingerprint, again.evidence, again.evidence_stored) == ("Exam01", done.fingerprint, done.evidence, True)
    assert api.entry(ws, "Exam01").result["external_evidence"] == done.evidence
    assert api.entry(ws, "Exam01").status == "needs_review"               # evidence is not an approval
    assert not record.exists() and not record.parent.exists() and api.pending_evidence(ws) == []
    with pytest.raises(CdlbibError, match="No model evidence is waiting to be stored for Exam01"):
        api.retry_evidence(ws, "Exam01")


def test_evidence_that_is_stored_leaves_no_record_and_prepare_retries_what_waits(ws, tmp_path):
    draft, pdf = model_draft(ws)
    done = api.accept_draft(ws, draft, pdf)
    assert done.evidence_stored is True and not (ws.work / "pending-evidence").exists()
    other = Workspace(tmp_path / "other")
    other.root.mkdir()
    other.bib.write_text(KAHA12 + "\n", encoding="utf-8")
    draft, pdf = model_draft(other)
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    done = api.accept_draft(other, draft, pdf, database=blocked)
    assert done.evidence_stored is False and len(api.pending_evidence(other)) == 1
    lines = []
    api.prepare(other, progress=lines.append)
    assert "model evidence for Exam01: stored" in lines
    assert api.pending_evidence(other) == [] and api.entry(other, "Exam01").result["external_evidence"] == done.evidence
    quiet = []
    api.prepare(other, progress=quiet.append)
    assert not any(text.startswith("model evidence") for text in quiet)


def test_evidence_for_an_entry_that_changed_is_stale_and_is_never_stored(ws, tmp_path):
    draft, pdf = model_draft(ws)
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    done = api.accept_draft(ws, draft, pdf, database=blocked)
    opened = api.entry(ws, "Exam01")
    api.save_edit(ws, "Exam01", opened.raw.replace("2001", "2002"), opened.fingerprint)
    assert api.pending_evidence(ws) == [api.PendingEvidence("Exam01", done.fingerprint, True)]
    lines = []
    api.prepare(ws, progress=lines.append)
    assert "model evidence for Exam01: not stored: the entry has changed since the evidence was read" in lines
    stale = api.retry_evidence(ws, "Exam01")
    assert stale.evidence_stored is False and "has changed since the evidence was read" in stale.evidence_error
    assert "external_evidence" not in api.entry(ws, "Exam01").result
    # records that are not what the writer keeps are ignored, and a link is never followed
    folder = ws.work / "pending-evidence"
    (folder / "Other99.json").write_text(json.dumps({"key": "Elsewhere", "fingerprint": "x", "evidence": {}}), encoding="utf-8")
    (folder / "Broken.json").write_text("{", encoding="utf-8")
    victim = tmp_path / "victim.json"
    victim.write_text(json.dumps({"key": "Linked", "fingerprint": "x", "evidence": {}}), encoding="utf-8")
    (folder / "Linked.json").symlink_to(victim)
    assert [item.key for item in api.pending_evidence(ws)] == ["Exam01"]


# --- 3. one outcome per accepted proposal -----------------------------------------------------------

def test_outcomes_are_one_per_accepted_proposal_in_order(tmp_path, capsys):
    from test_complete_duplicates import fields, proposal
    ws = Workspace(tmp_path)
    raw = complete.render("article", "Dupl20", fields())
    twin = complete.render("article", "SmitEtal20", fields())
    ws.bib.write_text(twin + "\n\n" + raw + "\n", encoding="utf-8")
    remove = proposal("Dupl20", fields())
    remove.typed_raw, remove.key_typed, remove.duplicate_of, remove.remove_duplicate = raw, "Dupl20", "SmitEtal20", True
    second = proposal("SmitEtal20b", fields("Second paper"))
    second.renames = {"SmitEtal20": "SmitEtal20a"}
    stale = proposal("Brow20", fields("Third", author="C Brown"))
    stale.typed_raw, stale.key_typed = "@article{Gone20, title={gone}}", "Gone20"      # typed as Gone20, proposed as Brow20
    third = proposal("Jone21", fields("Fourth", author="D Jones", year="2021"))
    applied = api.apply_proposals(ws, [stale, remove, second, third])
    assert [(o.index, o.key, o.status) for o in applied.outcomes] == [
        (0, "Gone20", "refused"), (1, "Dupl20", "removed"), (2, "SmitEtal20b", "written"), (3, "Jone21", "written")]
    assert applied.outcomes[0].reason == "changed on disk" and applied.refused == [("Gone20", "changed on disk")]
    assert applied.written == ["SmitEtal20b", "Jone21"] and applied.removed == ["Dupl20"]
    # matching on the proposed key would have called the refused one written: outcomes[i] is accepted[i]
    assert applied.outcomes[0].status == "refused" and stale.key_proposed == "Brow20"
    assert set(load_entries(ws.bib)) == {"SmitEtal20a", "SmitEtal20b", "Jone21"}
    assert cli.report_applied(applied, "Added") is True
    assert capsys.readouterr().out == ("Removed duplicate: Dupl20\nAdded: SmitEtal20b\nAdded: Jone21\n"
                                       "Not written Gone20: changed on disk\n")
    # a later proposal that renames an earlier one's entry: the earlier outcome follows the rename
    ws.bib.write_text("", encoding="utf-8")
    first = proposal("SmitEtal20", fields())
    applied = api.apply_proposals(ws, [first, second])
    assert [(o.index, o.key, o.status) for o in applied.outcomes] == [(0, "SmitEtal20a", "written"), (1, "SmitEtal20b", "written")]
    assert applied.written == ["SmitEtal20a", "SmitEtal20b"]
    assert api.as_data(applied)["outcomes"][0] == {"index": 0, "key": "SmitEtal20a", "status": "written", "reason": ""}


# --- 4. one name-by-name choice --------------------------------------------------------------------

def test_name_choices_and_resolve_names_are_what_the_command_line_uses(tmp_path):
    item = complete.Proposal(key_typed="SmitJone20", entry_type="article", proposed_raw="@article{SmitJone20}", changes=[
        complete.FieldChange("author", "A Smith and B Jones", "Alan Smith and B Jones", "crossref", "question"),
        complete.FieldChange("editor", "C Brown", "C Brown and D Green", "crossref", "question"),      # not name for name
        complete.FieldChange("title", "A", "B", "crossref", "question")])
    assert api.name_choices(item) == [("author", ["A Smith", "B Jones"], ["Alan Smith", "B Jones"])]
    seen = []

    def recheck(proposal, raw, resolved_fields=()):
        seen.append((raw, resolved_fields))
        return proposal

    item.edited_fields = {"author": "A Smith and B Jones", "title": "A", "year": "2020"}
    assert api.resolve_names(None, item, "author", ["Alan Smith", "B Jones"], recheck=recheck) is item
    assert seen == [(complete.render("article", "SmitJone20", dict(item.edited_fields, author="Alan Smith and B Jones")),
                     ("author",))]
    import inspect
    source = inspect.getsource(cli.decide)
    assert "api.name_choices(item)" in source and "api.resolve_names(" in source and "split(' and ')" not in source


# --- 5. one install / fork decision ------------------------------------------------------------------

@pytest.fixture
def asking():
    was = deps.ask()
    yield deps.set_ask
    deps.set_ask(was)


def test_consent_goes_on_and_says_so_or_asks_with_the_command_lines_own_question(asking):
    missing = MissingDependency("textual", "tui", "the terminal interface")
    fork = PublishRefused("@someone has no fork of owner/Library.", needs_fork=True, upstream="owner/Library")
    asking(False)
    lines = []
    assert api.consent(missing, progress=lines.append) is True and api.consent(fork, progress=lines.append) is True
    assert lines == ["installing textual (needed for: the terminal interface) ...", "creating your fork someone/Library ..."]
    assert lines == [prompts.install_line(missing), prompts.fork_line(fork)]
    assert api.consent(missing, allow=False) is False and api.consent(fork, allow=True) is True
    asking(True)
    with pytest.raises(NeedsConfirmation) as ask:
        api.consent(missing, progress=lines.append)
    assert (ask.value.kind, ask.value.package, ask.value.extra, ask.value.feature) == (
        "install", "textual", "tui", "the terminal interface")
    assert ask.value.question == "the terminal interface needs 'textual'. Install it now?" == prompts.install_question(missing)
    assert ask.value.__cause__ is missing and len(lines) == 2
    with pytest.raises(NeedsConfirmation) as ask:
        api.consent(fork)
    assert (ask.value.kind, ask.value.upstream) == ("fork", "owner/Library")
    assert ask.value.question == "@someone has no fork of owner/Library. Create one now?" == str(ask.value)
    assert api.consent(fork, allow=True) is True and api.consent(missing, allow=False) is False      # an answer is an answer
    assert api.as_data(ask.value)["error_kind"] == "NeedsConfirmation"


def test_attempt_retries_once_for_a_fork_and_stops_where_it_must(asking):
    asking(False)
    calls, lines = [], []
    refusal = PublishRefused("@someone has no fork of owner/Library.", needs_fork=True, upstream="owner/Library")

    def send(allow_fork_creation=False):
        calls.append(allow_fork_creation)
        if not allow_fork_creation:
            raise refusal
        return "sent"

    assert api.attempt(send, progress=lines.append) == "sent" and calls == [False, True]
    assert lines == ["creating your fork someone/Library ..."]
    del calls[:]
    with pytest.raises(PublishRefused) as declined:
        api.attempt(send, allow_fork=False)
    assert declined.value is refusal and calls == [False]

    def never(allow_fork_creation=False):
        calls.append(allow_fork_creation)
        raise refusal

    del calls[:]
    with pytest.raises(PublishRefused):
        api.attempt(never, allow_fork=True)
    assert calls == [False, True]                                     # once more, not for ever
    with pytest.raises(PublishRefused, match="no changes"):
        api.attempt(lambda allow_fork_creation: (_ for _ in ()).throw(PublishRefused("There are no changes")))
    asking(True)
    del calls[:]
    with pytest.raises(NeedsConfirmation) as ask:
        api.attempt(send)
    assert ask.value.kind == "fork" and calls == [False]
    assert api.attempt(send, allow_fork=True) == "sent"


def test_attempt_installs_a_missing_package_for_real_and_runs_again_once(asking, tmp_path, monkeypatch):
    """A real installation attempt of a package that does not exist anywhere: deps.install
    runs the installer, which fails, and that failure is what comes back."""
    asking(False)
    monkeypatch.setenv("PIP_INDEX_URL", (tmp_path / "no-index").as_uri())
    monkeypatch.setenv("UV_INDEX_URL", (tmp_path / "no-index").as_uri())
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("UV_OFFLINE", "1")
    calls, lines = [], []
    missing = MissingDependency("cdlbib-no-such-package-5d1c", "no-such-extra", "a feature of this test")

    def run(allow_fork_creation=False):
        calls.append(1)
        raise missing

    with pytest.raises(CdlbibError) as failed:
        api.attempt(run, progress=lines.append)
    assert lines == ["installing cdlbib-no-such-package-5d1c (needed for: a feature of this test) ..."]
    assert calls == [1] and not isinstance(failed.value, MissingDependency)      # the installer's own failure
    with pytest.raises(MissingDependency):
        api.attempt(run, allow_install=False)
    asking(True)
    with pytest.raises(NeedsConfirmation, match="a feature of this test needs 'cdlbib-no-such-package-5d1c'. Install it now"):
        api.attempt(run)
    assert cli.install_wanted.__doc__ and cli.fork_wanted.__doc__


# --- 6. what completion would look at ----------------------------------------------------------------

def test_completion_due_names_the_entries_without_asking_any_source(tmp_path, client, offline):
    ws = Workspace(tmp_path)
    ws.bib.write_text("@article{Zoll90, doi={10.1002/tea.3660271011}}\n" + GAME62 + "\n", encoding="utf-8")
    reference = tmp_path / "reference.bib"
    reference.write_text(GAME62 + "\n", encoding="utf-8")
    due = api.completion_due(ws, reference=str(reference), database=str(client.cache.path))
    assert due and due.keys == ["Zoll90"] and due.reachable and due.problem is None and client.requests == 0
    offers = api.completion_offers(ws, reference=str(reference), database=str(client.cache.path), mailto=CONTACT)
    assert [offer.key for offer in offers] == due.keys
    unreachable = api.completion_due(ws, reference=str(tmp_path / "missing.bib"), database=str(client.cache.path))
    assert not unreachable and unreachable.keys == [] and not unreachable.reachable
    assert "Reference bibliography not found" in unreachable.problem
    github = api.completion_due(ws, database=str(client.cache.path))       # the network is refused: said, not raised
    assert not github.reachable and "Cannot download the reference bibliography" in github.problem
    ws.bib.write_text(GAME62 + "\n", encoding="utf-8")
    none = api.completion_due(ws, reference=str(reference), database=str(client.cache.path))
    assert not none and none.keys == [] and none.reachable
    ws.bib.write_text("@article{Broken, title = {never closed}", encoding="utf-8")
    assert api.completion_due(ws, reference=str(reference)).keys == []
    assert api.as_data(due) == {"keys": ["Zoll90"], "reachable": True, "problem": None}
    assert "before \"send\"" in api.completion_due.__doc__ and "--no-complete" in api.completion_due.__doc__


# --- 7. an entry without a title ---------------------------------------------------------------------

@pytest.mark.parametrize("untitled", [
    ZOLL90.replace("\tTitle = {Students' misunderstandings and misconceptions in college freshman chemistry (general and "
                   "organic)},\n", ""),
    ZOLL90.replace("{Students' misunderstandings and misconceptions in college freshman chemistry (general and organic)}", "{}"),
])
def test_an_entry_without_a_title_is_a_finding_not_a_crash(ws, tmp_path, client, offline, untitled):
    assert untitled != ZOLL90
    preview = api.preview_edit(ws, "Zoll90", untitled)
    assert preview.ok and [(item.field, item.corrected, item.message) for item in preview.format] == [
        ("title", None, "title: missing")]
    api.save_edit(ws, "Zoll90", untitled, preview.fingerprint)
    assert [item.message for item in api.entry(ws, "Zoll90").format] == ["title: missing"]
    assert api.entry(ws, "Kaha12").format == []                              # the others are judged as before
    whole = api.check_format(ws)
    assert not whole.ok and whole.failure == "Exception: title: missing: Zoll90"
    empty = Workspace(tmp_path / "empty")
    empty.root.mkdir()
    empty.bib.write_text("", encoding="utf-8")
    built = complete.propose(complete.Query.parse("10.1002/tea.3660271011"), client, client.cache, ws=empty)
    again = api.recheck_proposal(empty, built, untitled, mailto=CONTACT, database=str(client.cache.path))
    assert any("title: missing: Zoll90" in issue for issue in again.issues) and again.needs_decision
    assert not again.complete and not api.acceptable(again)


# --- 8. shared wording --------------------------------------------------------------------------------

def test_the_tex_and_backup_wording_is_one_text(managed_library):
    from cdlbib import library, tex
    ws = managed_library
    status = api.setup_report(ws).tex
    assert isinstance(status, tex.TexStatus)
    lines = prompts.tex_state_lines(status)
    assert lines[0] == f"TeX tree: {status.texmf_home}" and f"state: {prompts.tex_state(status)}" in lines
    assert cli._tex_state(status) == prompts.tex_state(status)
    assert (status.state == "linked") != any(text.startswith("without a link, this shell line") for text in lines)
    assert prompts.tex_state_lines(status, asked=True).count(
        "the link was not made (not confirmed); `cdlbib setup` without --ask makes it") == 1
    backup = library.backup(ws)
    assert cli._backup_line(backup) == prompts.backup_line(backup, api.holds_only_copy(backup))
    assert prompts.backup_line(backup) == f"branch master at {backup.commit[:8]}, 0 changed files"
    assert prompts.backup_line(backup, True).endswith(", holds commits kept nowhere else")


@pytest.fixture
def managed_library(tmp_path, monkeypatch):
    from cdlbib import library, workspace
    monkeypatch.setenv("CDLBIB_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CDLBIB_UPSTREAM", str(conftest.build_upstream(tmp_path / "up")))
    monkeypatch.setenv("TEXMFHOME", str(tmp_path / "texmf"))
    monkeypatch.delenv("CDLBIB_LIBRARY", raising=False)
    workspace.select_library(None)
    yield Workspace(library.download())
    workspace.select_library(None)
