"""The Library state, Send and Setup views by key presses: the banner for new upstream commits,
the update with unsent edits (the core's question and its answers), backups and undo, a send
that the checks refuse, the TeX link and a paper's export.

The real app over the real core: a managed library cloned from a local bare upstream, real
git, real TeX programs (skipped by name where they are not installed). Files are compared
afterwards. No mocks.
"""
import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="the terminal interface needs the optional package textual (pip install 'cdlbib[tui]')")

import conftest  # noqa: E402
import texhelpers  # noqa: E402
import tui_support as T  # noqa: E402
from cdlbib import api, deps, prompts  # noqa: E402
from cdlbib.errors import UpdateNeedsDecision  # noqa: E402
from test_update import BASE, MINE, THEIRS, everything, git, managed, unsent  # noqa: E402,F401
from texhelpers import nothing_of_the_users_touched  # noqa: E402,F401 - the user's own TeX link is compared

ZOLL90 = conftest.ZOLL90


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    T.isolate(monkeypatch, tmp_path)
    T.offline(monkeypatch)
    yield
    deps.set_ask(False)
    conftest.no_real_library_touched()


def name(app):
    return type(app.screen).__name__


def backups(app):
    return [key.value for key in app.screen.query_one("#backups").rows]


# --- the managed library: banner, update, backups, undo -----------------------------------------------

def test_the_banner_names_new_upstream_commits_and_the_state_says_how_the_library_was_chosen(managed):
    home, upstream, ws, new = unsent(managed)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            banner = T.shown(app, "#banner")
            assert "2 new upstream commits" in banner and "F7 Library state, then u updates" in banner
            assert "2 new upstream commits" in T.screen_text(app)
            await T.press(pilot, "f7")
            state = T.shown(app, "#state-now")
            assert f"Library: {ws.root}" in state
            assert "chosen by: no library named or found; this is the copy cdlbib downloads and manages" in state
            assert "upstream: 2 new commits (u updates)" in state and "branch: master" in state
            assert "unsent changes: cdl.bib, verification/notes/my new file.jsonl, verification/tracked.txt" in state
            assert f"no backups of {ws.root} yet" in T.shown(app, "#backups-head")
    before, state = everything(ws.root), (home / "state.json").read_bytes()
    T.run(journey())
    assert everything(ws.root) == before and not list((home / "backups").glob("*"))    # looking changes nothing
    assert git("rev-parse", "HEAD", cwd=ws.root) != new                     # in particular, it does not update


def test_update_with_unsent_edits_asks_in_the_cores_words_and_each_answer_does_what_it_says(managed):
    home, upstream, ws, new = unsent(managed)
    root = ws.root
    before = everything(root)
    with pytest.raises(UpdateNeedsDecision) as raised:
        api.update(ws, force=True)
    question = prompts.unsent_question(raised.value)
    assert everything(root) == before

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f7", "u")
            answers = {f"  [{letter}] {text}" for letter, text in (prompts.ANSWERS[c] for c in raised.value.choices)}
            assert name(app) == "ChoiceScreen"                               # the core's question; its answers are the buttons
            assert T.shown(app, "#question") == "\n".join(line for line in question.splitlines() if line not in answers)
            assert "What would you like to do?" in T.shown(app, "#question") and len(answers) == 4
            assert "A newer version of the bibliography is available (2 new commits)" in T.screen_text(app)
            labels = [str(button.label) for button in app.screen.query("Button")]
            assert labels == [f"[{letter}] {text}" for letter, text in (prompts.ANSWERS[c] for c in raised.value.choices)]
            assert everything(root) == before                                # asking changes nothing

            await T.press(pilot, "escape")                                   # no answer: nothing is changed
            assert name(app) != "ChoiceScreen" and everything(root) == before
            assert "Nothing was changed: no answer was given." in T.shown(app, "#state-result")

            await T.press(pilot, "u")                                        # (the question comes when the job has asked)
            await T.press(pilot, "k")                                        # keep working
            assert everything(root) == before
            assert "the bibliography was not updated and your changes are as they were" in T.shown(app, "#state-result")
            assert backups(app) == []

            await T.press(pilot, "u")
            await T.press(pilot, "u")                                        # update and keep my changes
            result = T.shown(app, "#state-result")
            assert "updated the bibliography: 2 new commits, with your changes kept" in result
            assert (root / "cdl.bib").read_bytes() == (THEIRS + MINE).encode()
            assert git("rev-parse", "HEAD", cwd=root) == new
            assert len(backups(app)) == 1 and backups(app)[0] in result
            assert "1 backup of" in T.shown(app, "#backups-head")
            assert T.shown(app, "#banner") == "" and "upstream: nothing new" in T.shown(app, "#state-now")
            await T.press(pilot, "f2")
            assert "2 of 2 entries" in T.screen_text(app) and "Mine26" in T.screen_text(app)

            await T.press(pilot, "f7")                                       # undo: back to the state before
            app.screen.query_one("#backups").focus()
            await T.press(pilot, "z")
            assert name(app) == "ConfirmScreen" and "Put the library back as it was at backup" in T.shown(app, "#question")
            await T.press(pilot, "n")
            assert (root / "cdl.bib").read_bytes() == (THEIRS + MINE).encode()
            await T.press(pilot, "z", "y")
            assert everything(root) == before
            assert "restored backup" in T.shown(app, "#state-result") and len(backups(app)) == 2
            assert "2 new upstream commits" in T.shown(app, "#banner")

            await T.press(pilot, "u")
            await T.press(pilot, "d")                                        # discard my changes and update
            assert (root / "cdl.bib").read_bytes() == THEIRS.encode()
            assert "updated the bibliography" in T.shown(app, "#state-result") and len(backups(app)) == 3
    T.run(journey())
    api.undo_update()                                                        # the discarded changes are in the backup
    assert (root / "cdl.bib").read_bytes() == (BASE + MINE).encode()


def test_a_library_that_is_not_the_managed_one_offers_no_update_and_says_why(tmp_path):
    ws = T.library(tmp_path / "lib", ZOLL90)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f7")
            state = T.shown(app, "#state-now")
            assert f"Library: {ws.root}" in state and "chosen by: the file you named" in state
            assert ("This library was chosen by the file you named, so cdlbib does not update it: update (u), backups "
                    "(b) and undo (z) are for the copy cdlbib downloads and manages, and are not offered here.") in state
            assert prompts.CHOSEN_BY["named"] == "the file you named"
            assert "is not a git checkout of its own, so there is no branch and nothing to send" in state
            assert app.screen.query_one("#state-update").disabled and app.screen.query_one("#state-undo").disabled
            await T.press(pilot, "u")
            assert name(app) != "ChoiceScreen" and "(kept for the library cdlbib manages" in T.shown(app, "#backups-head")
            assert any("This library was chosen by the file you named" in note for note in app.notices)
            await T.press(pilot, "z")
            assert name(app) != "ConfirmScreen" and "update the library" not in [label for label, _, _ in app.jobs.history]
    T.run(journey())
    assert not Path(os.environ["CDLBIB_HOME"], "library").exists()            # nothing was downloaded for it
    assert ws.bib.read_text(encoding="utf-8") == ZOLL90 + "\n"


def test_an_addition_to_the_managed_library_names_its_backup_and_undo_takes_it_back(managed, monkeypatch):
    home, upstream, ws = managed
    before = ws.bib.read_bytes()
    T.seed_responses(ws, T.COMPLETION)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f4", "escape", "right", "enter")
            await T.type_text(pilot, "10.1037/h0041332")
            await T.press(pilot, "enter")
            await T.press(pilot, "a")
            assert "Added: Game62" in app.log_lines and b"@article{Game62," in ws.bib.read_bytes()
            stamp = next(line for line in app.log_lines if line.startswith("Batch backup: ")).split()[2].rstrip(";")
            assert (f"Batch backup: {stamp}; cdlbib update --undo restores the state before this command’s accepted "
                    "changes.") in T.shown(app, "#i-message")              # as the command line says it
            assert not list((home / "completion-batches").glob("*"))         # the batch was closed with the proposals
            await T.press(pilot, "f7")
            assert backups(app) == [stamp] and "unsent changes: cdl.bib" in T.shown(app, "#state-now")
            app.screen.query_one("#backups").focus()
            await T.press(pilot, "z", "y")
            assert ws.bib.read_bytes() == before and "restored backup " + stamp in T.shown(app, "#state-result")
            await T.press(pilot, "f2")
            assert "1 of 1 entries" in T.screen_text(app)
            assert [key.value for key in app.screen.query_one("#entries").rows] == ["Zoll90"]
    T.run(journey())


def test_quitting_from_a_proposal_closes_what_it_held_open(managed):
    home, upstream, ws = managed
    T.seed_responses(ws, T.COMPLETION)
    from cdlbib.tui import CdlbibApp

    async def journey():
        app = CdlbibApp(ws)
        async with app.run_test(size=T.SIZE) as pilot:
            await T.settle(pilot)
            await T.press(pilot, "f4", "escape", "right", "enter")
            await T.type_text(pilot, "10.1037/h0041332 10.1002/tea.3660271011")
            await T.press(pilot, "enter")
            await T.press(pilot, "a")
            assert name(app) == "ProposalScreen" and len(list((home / "completion-batches").glob("*"))) == 1
            await pilot.press("ctrl+q")
            for _ in range(200):
                await pilot.pause(0.05)
                if app.return_code is not None:
                    break
            assert app.return_code == 0
    T.run(journey())
    assert not list((home / "completion-batches").glob("*")) and b"@article{Game62," in ws.bib.read_bytes()


# --- send ----------------------------------------------------------------------------------------------

def test_send_shows_what_would_go_and_a_send_the_gate_refuses_makes_no_commit_and_no_branch(managed):
    """The edit holds an entry that is not in house format (a single hyphen in its pages), so
    the gate's format check, which needs no network, refuses the send."""
    bad = MINE.replace("\tTitle = {My own entry},\n", "\tPages = {1-2},\n\tTitle = {My own entry},\n")
    home, upstream, ws, new = unsent(managed, mine=BASE + bad)
    root = ws.root
    before, head = everything(root), git("rev-parse", "HEAD", cwd=root)
    branches = git("branch", "--list", "--all", cwd=root)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f6")
            state = T.shown(app, "#send-state")
            assert "Will be sent" in state and "  cdl.bib" in state and "verification/tracked.txt" in state
            assert "Branch\n  master" in state
            await T.press(pilot, "s")
            assert name(app) == "ConfirmScreen" and "as a pull request from your fork?" in T.shown(app, "#question")
            assert "Completion is offered for new or edited entries first" in T.shown(app, "#question")
            await T.press(pilot, "n")
            assert everything(root) == before and app.jobs.idle
            await T.press(pilot, "s", "y")
            await T.settle(pilot, timeout=300)
            result = T.shown(app, "#send-result")
            assert result.startswith("Not sent.")
            assert "not sent: fix the format errors and resolve every new/edited entry first" in result   # the gate's refusal
            assert "House format\n  Mine26" in result and "pull request:" not in result
            assert any(line.startswith("Completion unavailable:") for line in app.log_lines)   # GitHub's copy is out of reach
            assert "format: errors found in Mine26" in app.log_lines
            assert "  Mine26: pages: the formatter writes 1--2" in app.log_lines
            lines = len(app.log_lines)
            await T.press(pilot, "S")                                        # the same send, the offers skipped
            assert "Completion offers are skipped; the checks run" in T.shown(app, "#question")
            await T.press(pilot, "y")
            await T.settle(pilot, timeout=300)
            said = app.log_lines[lines:]
            assert "completion offers skipped (as `cdlbib send --no-complete`)" in said
            assert not any("ompletion unavailable" in line for line in said)
            assert "not sent: fix the format errors" in T.shown(app, "#send-result")
    T.run(journey())
    assert git("rev-parse", "HEAD", cwd=root) == head and git("symbolic-ref", "--short", "HEAD", cwd=root) == "master"
    assert git("branch", "--list", "--all", cwd=root) == branches and git("stash", "list", cwd=root) == ""
    assert everything(root) == before                                        # no commit, no branch, every byte as it was


def test_send_and_state_list_an_approval_that_waits_when_no_file_has_changed(managed):
    """No file of the library has changed; one human approval, recorded under a GitHub login,
    is in the verification database and not in verification/approvals.jsonl. The Send view
    lists it as what will be sent and its question names it; the Library state view lists it
    as unsent. Looking adds nothing to the ledger."""
    from cdlbib import verification as v
    home, upstream, ws = managed
    root = ws.root
    cache = v.Cache(str(ws.database), ledger=ws.revocations)
    try:
        v.record_approval(cache, str(ws.bib), "Zoll90", v.load_entries(str(ws.bib))["Zoll90"]["fingerprint"],
                          {"reviewer": "@octocat", "source": "https://doi.org/10.1002/tea.3660271011",
                           "note": "Compared every field with the printed article.", "github_login": "octocat",
                           "github_id": 583231})
    finally:
        cache.close()
    assert api.library_state(ws).pending == []
    before = everything(root)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f6")
            state = T.shown(app, "#send-state")
            assert "Will be sent" in state and "(no changed file)" not in state
            assert ("Approvals that will be sent (the send adds them to verification/approvals.jsonl)\n"
                    "  Zoll90, approved by @octocat") in state
            await T.press(pilot, "s")
            assert name(app) == "ConfirmScreen"
            assert "Send the approval of Zoll90 as a pull request from your fork?" in T.shown(app, "#question")
            await T.press(pilot, "n")
            await T.press(pilot, "f7")
            state = T.shown(app, "#state-now")
            assert "unsent approvals: Zoll90 (@octocat)" in state and "unsent changes: none" not in state
    T.run(journey())
    after = everything(root)
    # The library's files, branches and commits are as they were. (The verification database
    # under .bibcheck/, which reading a stored result opens, is the one thing not compared.)
    assert {part: found for part, found in after.items() if part != "outside"} == {
        part: found for part, found in before.items() if part != "outside"}
    assert not ws.approvals.exists() and api.library_state(ws).pending == []


def test_the_send_of_the_interface_is_the_checked_send_and_no_other():
    import re
    package = Path(conftest.ROOT, "src/cdlbib/tui")
    calls = set()
    for path in package.glob("*.py"):
        calls |= set(re.findall(r"api\.(send\w*)\(", path.read_text(encoding="utf-8")))
    assert calls == {"send_checked"}
    imported = set()
    for path in package.glob("*.py"):
        for found in re.findall(r"^from \.\. import ([\w, ]+)$", path.read_text(encoding="utf-8"), flags=re.M):
            imported |= {item.strip() for item in found.split(",")}
        imported |= set(re.findall(r"^from \.\.(\w+) import", path.read_text(encoding="utf-8"), flags=re.M))
    assert imported <= {"api", "theme", "prompts", "deps", "errors", "workspace"}, imported


# --- setup: features, the TeX link, export ---------------------------------------------------------------

def test_setup_lists_what_was_not_checked_and_checks_on_request(tmp_path, monkeypatch):
    for variable in ("GH_TOKEN", "GITHUB_TOKEN", "DARTMOUTH_CHAT_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "gh-config"))
    ws = T.library(tmp_path / "lib", ZOLL90)

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f8")
            report = T.shown(app, "#setup-report")
            assert f"library: {ws.root}" in report and "chosen by: the file you named" in report
            assert "Available on this computer" in report and "git: yes" in report
            if shutil.which("gh"):
                assert "gh login: not checked" in report
            assert "Dartmouth Chat key: not checked" in report and "OpenAI key: not checked" in report
            assert "textual: yes (installed)" in report
            assert "c checks what was not checked" in report
            assert "Dartmouth Chat (the default): not checked" in report and "OpenAI: not checked" in report
            assert "Create an API key in Dartmouth Chat" in report          # how to set it up, whatever its state
            await T.press(pilot, "c")
            report = T.shown(app, "#setup-report")
            assert "not checked" not in report                               # every one is now yes or no
            assert "Dartmouth Chat key: no" in report and "OpenAI key: no" in report      # no keychain under this HOME
            assert "Store it in the system keychain as 'dartmouth-chat-api-key'" in report
            assert "Dartmouth Chat (the default): not set up" in report
            assert "asking gh who is logged in (gh api user) ..." in app.log_lines or not shutil.which("gh")
    T.run(journey())
    assert ws.bib.read_text(encoding="utf-8") == ZOLL90 + "\n"               # a report: nothing written, nothing linked
    assert not os.path.lexists(Path(os.environ["TEXMFHOME"]) / "bibtex/bib/cdl.bib")
    assert not Path(os.environ["CDLBIB_HOME"], "tex-link.json").exists()


def test_the_tex_link_is_made_and_removed_and_with_ask_only_after_a_yes(tmp_path):
    texhelpers.need("kpsewhich")
    ws = T.library(tmp_path / "lib", ZOLL90)
    link = Path(os.environ["TEXMFHOME"]) / "bibtex/bib/cdl.bib"

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f8")
            assert "state: not linked" in T.shown(app, "#setup-report") and not os.path.lexists(link)
            await T.press(pilot, "l")
            assert os.path.islink(link) and Path(os.readlink(link)) == ws.bib
            report = T.shown(app, "#setup-report")
            assert "state: linked: TeX finds this library's cdl.bib from any folder" in report
            assert f"kpsewhich cdl.bib: {link}" in report or f"kpsewhich cdl.bib: {ws.bib}" in report
            assert "state: linked" in T.shown(app, "#setup-result")
            await T.press(pilot, "x")
            assert name(app) == "ConfirmScreen" and "Remove the link cdlbib made in your TeX tree?" in T.shown(app, "#question")
            await T.press(pilot, "n")
            assert os.path.islink(link)
            await T.press(pilot, "x", "y")
            assert not os.path.lexists(link) and f"removed {link}" in T.shown(app, "#setup-result")
            assert "state: not linked" in T.shown(app, "#setup-report")

            deps.set_ask(True)                                               # as `cdlbib --ask tui`
            await T.press(pilot, "l")
            assert name(app) == "ConfirmScreen" and T.shown(app, "#question") == f"Link {link} to {ws.bib}?"
            await T.press(pilot, "n")
            assert not os.path.lexists(link)
            await T.press(pilot, "l", "y")
            assert os.path.islink(link)
    T.run(journey())


def test_a_file_cdlbib_did_not_put_in_the_tex_tree_is_replaced_only_after_a_yes(tmp_path):
    texhelpers.need("kpsewhich")
    ws = T.library(tmp_path / "lib", ZOLL90)
    link = Path(os.environ["TEXMFHOME"]) / "bibtex/bib/cdl.bib"
    link.parent.mkdir(parents=True)
    link.write_text("% my own file\n", encoding="utf-8")

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f8", "l")
            assert name(app) == "ConfirmScreen" and "Move it aside (it is kept) and make the link?" in T.shown(app, "#question")
            await T.press(pilot, "n")
            assert link.read_text(encoding="utf-8") == "% my own file\n" and not os.path.islink(link)
            await T.press(pilot, "l")
            await T.press(pilot, "y")
            assert os.path.islink(link) and Path(os.readlink(link)) == ws.bib
    T.run(journey())
    kept = [path for path in link.parent.iterdir() if path.name.startswith("cdl.bib.cdlbib-saved-")]
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == "% my own file\n"


def test_export_writes_the_papers_frozen_bib_and_its_bbl(tmp_path):
    ws = T.library(tmp_path / "lib", *texhelpers.LIBRARY.strip().split("\n\n"))
    file = texhelpers.paper(tmp_path / "paper", "Cited: \\cite{Zoll90} and \\cite{FixtA21}.\n\\bibliographystyle{plain}\n"
                                                "\\bibliography{cdl}")
    out = tmp_path / "paper" / "cdl.bib"

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f8", "b")
            assert "Name the paper first" in T.shown(app, "#setup-result") and not out.exists()
            app.screen.query_one("#x-paper").focus()
            await T.type_text(pilot, str(file))
            await T.press(pilot, "escape", "b")
            result = T.shown(app, "#setup-result")
            assert "2 keys" in result and f"wrote {out}: 2 entries from {ws.bib}" in result
            written = out.read_text(encoding="utf-8")
            assert ZOLL90 in written and "@article{FixtA21," in written and "FixtB22" not in written
            await T.press(pilot, "b")                                        # the file is there: not replaced unasked
            assert out.read_text(encoding="utf-8") == written and "wrote" not in T.shown(app, "#setup-result")
            if shutil.which("pdflatex") and shutil.which("bibtex"):
                await T.press(pilot, "B")
                await T.settle(pilot, timeout=300)
                made = tmp_path / "paper" / "main.bbl"
                assert f"wrote {made}: bibtex, style plain" in T.shown(app, "#setup-result")
                assert "Zoller" in made.read_text(encoding="utf-8") and "\\bibitem{Zoll90}" in made.read_text(encoding="utf-8")
    T.run(journey())
    assert out.exists()


def test_a_paper_that_asks_for_lualatex_is_compiled_with_it_only_after_a_yes(tmp_path):
    ws = T.library(tmp_path / "lib", *texhelpers.LIBRARY.strip().split("\n\n"))
    file = texhelpers.paper(tmp_path / "paper", "Cited: \\cite{Zoll90}.\n\\bibliographystyle{plain}\n\\bibliography{cdl}",
                            preamble="\\usepackage{luacode}")
    made = tmp_path / "paper" / "main.bbl"

    async def journey():
        async with T.opened(ws) as pilot:
            app = pilot.app
            await T.press(pilot, "f8")
            app.screen.query_one("#x-paper").focus()
            await T.type_text(pilot, str(file))
            await T.press(pilot, "escape")
            await T.press(pilot, "B")
            await T.settle(pilot, timeout=300)
            if not (shutil.which("pdflatex") or shutil.which("lualatex")):
                assert name(app) != "ConfirmScreen"                      # no TeX: that is the refusal, and no question
                return
            assert name(app) == "ConfirmScreen"
            question = T.shown(app, "#question")
            assert "main.tex asks for lualatex, which is not run unless it is named" in question
            assert question.endswith("Compile this paper with lualatex now?")
            assert "asks for lualatex" in T.shown(app, "#setup-result", screen=app.screen_stack[0])
            await T.press(pilot, "n")
            assert not made.exists() and "write the paper's .bbl with lualatex" not in [l for l, _, _ in app.jobs.history]
            await T.press(pilot, "B")
            await T.press(pilot, "y")
            await T.settle(pilot, timeout=300)
            assert "write the paper's .bbl with lualatex" in [label for label, _, _ in app.jobs.history]
            if shutil.which("lualatex") and shutil.which("bibtex"):
                assert f"wrote {made}: bibtex, style plain, lualatex" in T.shown(app, "#setup-result")
                assert "\\bibitem{Zoll90}" in made.read_text(encoding="utf-8")
            else:
                assert not made.exists() and name(app) != "ConfirmScreen"   # refused again, and not asked again
    T.run(journey())
