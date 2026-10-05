"""Five things a person following the tutorials ran into: a first lookup in a library that
was never checked and no contact address; a bare title that only finds records about the
paper; the OpenAI route's missing model name; a record with a consortium among its authors
(no key can be made); and "cannot accept" without the reasons.

Real commands in subprocesses, real files, the saved source records and two recorded Crossref
responses (tests/fixtures/completion/title_only.json) replayed through the real client with
the network refused. No mocks.
"""
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

import conftest
from cdlbib import api, complete, extra_sources, intake
from cdlbib.errors import CdlbibError
from cdlbib.workspace import Workspace

from test_complete_build import RECORDS
from test_complete_cli import refused_network, terminal
from test_complete_identify import client, CONTACT, SAVED  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
TITLE_ONLY = json.loads((ROOT / "tests/fixtures/completion/title_only.json").read_text(encoding="utf-8"))
ALPHAFOLD = "Highly accurate protein structure prediction with AlphaFold"


@pytest.fixture
def offline(monkeypatch):
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)


# --- A. the first lookup in a library that was never checked ---------------------------------------

def test_a_first_lookup_without_a_contact_address_says_that_and_how_to_set_it(tmp_path, monkeypatch, offline):
    ws = Workspace(tmp_path)
    ws.bib.write_text(conftest.ZOLL90 + "\n", encoding="utf-8")
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)
    assert not ws.work.exists()
    said = "No contact email: set CROSSREF_MAILTO to your email address"
    with pytest.raises(CdlbibError, match="Entry completion could not start: " + said) as stopped:
        api.propose_new(ws, ["10.1007/978-3-319-10590-1_53"])
    assert "export CROSSREF_MAILTO=you@example.org" in str(stopped.value) and "--mailto" in str(stopped.value)
    assert "unable to open database file" not in str(stopped.value)
    with pytest.raises(CdlbibError, match=said):
        api.propose(ws, keys=["Zoll90"], reference=None)
    with pytest.raises(CdlbibError, match="Edited entry could not be rechecked: " + said):
        api.recheck_proposal(ws, complete.Proposal(entry_type="article", key_proposed="Zoll90", proposed_raw=conftest.ZOLL90),
                             conftest.ZOLL90.replace("{27}", "{28}"))
    with pytest.raises(ValueError, match=said):
        extra_sources.contact_email(ws.database)                # no cache at all
    with pytest.raises(ValueError, match=said):
        extra_sources.contact_email(None)
    env = {k: v for k, v in os.environ.items() if k != "CROSSREF_MAILTO"}
    run = subprocess.run([sys.executable, "-c", "from cdlbib.cli import main; main()", "--library", str(tmp_path), "add",
                          "10.1007/978-3-319-10590-1_53"], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert run.returncode == 1 and said in run.stdout + run.stderr, run.stdout + run.stderr
    assert "unable to open database file" not in run.stdout + run.stderr and "Traceback" not in run.stderr


def test_with_a_contact_address_the_first_lookup_makes_its_own_folder(tmp_path, monkeypatch, offline):
    """The address given: the cache is made (the folder with it) and the lookup goes as far as
    the refused network, which is what it then reports; and an address already used in the
    cache is found again when the variable is not set."""
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    monkeypatch.setenv("CROSSREF_MAILTO", CONTACT)
    found = api.propose_new(ws, ["10.1007/978-3-319-10590-1_53"])
    assert ws.database.is_file() and found.errors and "unable to open database file" not in found.errors[0][1]
    assert found[0].status == "provider_error"
    monkeypatch.delenv("CROSSREF_MAILTO")
    with pytest.raises(ValueError, match="No contact email"):
        extra_sources.contact_email(ws.database)                # a cache that holds no Crossref response yet
    from cdlbib.verification import Cache
    cache = Cache(ws.database)
    cache.save_response("a request", {"url": "https://api.crossref.org/works/10.1/x?mailto=someone%40example.org", "body": {}})
    cache.close()
    assert extra_sources.contact_email(ws.database) == "someone@example.org"


# --- B. a title alone --------------------------------------------------------------------------------

@pytest.fixture
def titled(client):
    for item in TITLE_ONLY:
        client.cache.save_response(item["request"], item["response"])
    return client


def test_a_bare_title_that_finds_only_records_about_the_paper_offers_the_paper(tmp_path, titled, offline):
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    proposal = complete.propose(complete.Query.parse(ALPHAFOLD), titled, titled.cache, ws=ws)
    assert titled.requests == 0 and proposal.proposed_raw is None and proposal.needs_decision
    assert [(c["doi"], c["title"], c["type"]) for c in proposal.candidates] == [
        ("10.1038/s41586-021-03819-2", ALPHAFOLD, "journal-article")]
    assert proposal.issues == ["1 record has this title. A title alone is not taken as the work: choose the record, "
                               "or give the first author as well"]
    assert not any("No record" in issue for issue in proposal.issues)
    query = complete.Query.from_candidate(proposal.candidates[0])       # choosing it is the existing candidate choice
    assert query.doi == "10.1038/s41586-021-03819-2"
    # at the terminal the candidate is listed and can be chosen (0: none of these)
    database = titled.cache.path
    status, out = terminal(tmp_path, "from cdlbib.cli import main; main()", "0\n",
                           argv=["add", ALPHAFOLD, "--mailto", CONTACT, "--database", str(database)])
    assert f"[1] " in out and "10.1038/s41586-021-03819-2" in out and "[0] none of these" in out, out
    assert "No record in Crossref or PubMed matches" not in out and ws.bib.read_text(encoding="utf-8") == ""


def test_the_title_search_is_made_only_when_records_about_the_title_were_found(tmp_path, client, offline):
    """A bare title whose search finds nothing like it: no second request, the note as before."""
    assert complete._mentioned(ALPHAFOLD, [{"title": ["Faculty Opinions recommendation of " + ALPHAFOLD + "."]}])
    assert not complete._mentioned(ALPHAFOLD, [{"title": [ALPHAFOLD]}, {"title": ["Protein structure prediction"]}, {}])
    from intake_support import offline_client
    from test_intake_pdf import pdfs
    saved = offline_client(tmp_path / "cache", "pdf_lookups.json.gz") if (ROOT / "tests/fixtures/intake/pdf_lookups.json.gz").exists() else None
    if saved is None:
        pytest.skip("the recorded lookup of a title that matches nothing is not in this checkout")
    try:
        found = complete.identify(complete.Query.parse(pdfs.UNKNOWN_TITLE), saved, saved.cache)
        assert saved.requests == 0 and found.candidates == []
        assert found.note == "No record in Crossref or PubMed matches the title; the entry is left as typed"
    finally:
        saved.cache.close()


# --- C. the OpenAI route ------------------------------------------------------------------------------

def test_the_openai_route_says_exactly_what_is_missing(monkeypatch):
    key = {"OPENAI_API_KEY": "sk-test-do-not-print-0123456789"}
    routes = {route.name: route for route in intake.model_routes(environ=key)}
    assert routes["openai"].available is False
    assert routes["openai"].detail == ("the model to use is not named: the environment variable BIBCHECK_RESEARCH_MODEL "
                                       "is not set")
    assert "BIBCHECK_RESEARCH_MODEL" in routes["openai"].how
    ready = {route.name: route for route in intake.model_routes(environ=dict(key, BIBCHECK_RESEARCH_MODEL="a-model"))}
    assert (ready["openai"].available, ready["openai"].detail) == (True, "")
    unset = {route.name: route for route in intake.model_routes(environ={})}
    assert unset["openai"].available is None and unset["openai"].detail.startswith("not checked: OPENAI_API_KEY is not set")
    assert unset["dartmouth"].detail.startswith("not checked: ")
    spaced = intake.route_state("openai", {"OPENAI_API_KEY": "two words", "BIBCHECK_RESEARCH_MODEL": "m"})
    assert spaced == (False, "the environment variable OPENAI_API_KEY holds whitespace; a key is a single token")
    assert intake.route_state("dartmouth", {"DARTMOUTH_CHAT_API_KEY": "k"})[0] in (True, None)
    # the rule model_routes shows is the rule that decides (one function)
    assert intake.route_state("openai", key)[0] is False and intake.route_state("openai", dict(key, BIBCHECK_RESEARCH_MODEL="m"))[0]
    # features() reports the key itself, as it did; the route's state is model_routes' to tell
    for name, value in key.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("BIBCHECK_RESEARCH_MODEL", raising=False)
    feature = {item.name: item for item in api.features()}["OpenAI key"]
    assert feature.available is True and feature.detail == "set in the environment variable OPENAI_API_KEY"
    shown = {route.name: route for route in api.model_routes()}["openai"]
    assert shown.available is False and "BIBCHECK_RESEARCH_MODEL is not set" in shown.detail
    assert "sk-test" not in json.dumps(api.intake_data(shown))


# --- D. a record with a consortium among its authors ----------------------------------------------------

def scipy_proposal(client):
    built = complete.build({"doi": "10.1038/s41592-019-0686-2"}, deepcopy(RECORDS["corporate-author"]["crossref"]["record"]))
    return complete.checked(built, client)


def test_a_proposal_without_authors_says_no_key_can_be_made_and_is_not_acceptable(tmp_path, client, offline):
    proposal = scipy_proposal(client)
    assert proposal.key_proposed is None and proposal.key_typed is None and not proposal.complete
    assert [(u.field, u.reason) for u in proposal.unfilled if u.field in ("author", "ID")] == [
        ("author", "Incomplete or corporate source byline"), ("ID", "a key needs the authors and the year")]
    assert complete.NO_KEY_YET in proposal.issues and complete.NO_KEY_YET.startswith("No key can be made until the authors")
    assert not any("would write the key as" in issue for issue in proposal.issues)      # not "write the key as 20"
    assert not api.acceptable(proposal)
    why = api.why_not_acceptable(proposal)
    assert why[:2] == ["it has no key yet (a key is made from the authors and the year)",
                       "author is missing (required for an entry of type article)"]
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    applied = api.apply_proposals(ws, [proposal])
    assert applied.written == [] and applied.outcomes[0].status == "refused" and ws.bib.read_text(encoding="utf-8") == ""


def test_entering_the_authors_plans_the_key(tmp_path, client, offline):
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    proposal = scipy_proposal(client)
    assert proposal.proposed_raw.startswith("@article{KeyNeeded,\n\tDoi = ")
    edited = proposal.proposed_raw.replace("@article{KeyNeeded,", "@article{KeyNeeded,\n\tAuthor = {P Virtanen and R Gommers and T E Oliphant},")
    again = api.recheck_proposal(ws, proposal, edited, mailto=CONTACT, database=str(client.cache.path))
    assert again.key_proposed == "VirtEtal20" and again.complete
    assert again.proposed_raw == edited.replace("{KeyNeeded,", "{VirtEtal20,")
    assert complete.NO_KEY_YET not in again.issues and not any("key plan" in issue or "the key as" in issue for issue in again.issues)
    assert api.why_not_acceptable(again) == [] and api.acceptable(again)
    # a key the person typed themselves is not replaced: only the placeholder is
    own = api.recheck_proposal(ws, proposal, edited.replace("{KeyNeeded,", "{MyOwnKey,"), mailto=CONTACT,
                               database=str(client.cache.path))
    assert any("The edited key MyOwnKey does not match the key plan VirtEtal20" in issue for issue in own.issues)
    assert own.proposed_raw.startswith("@article{MyOwnKey,")
    assert api.apply_proposals(ws, [again]).written == ["VirtEtal20"]
    assert ws.bib.read_text(encoding="utf-8").startswith("@article{VirtEtal20,\n\tAuthor = {P Virtanen and R Gommers and T E Oliphant},")


# --- E. why a proposal cannot be accepted ---------------------------------------------------------------

def test_why_not_acceptable_names_each_reason_and_is_the_same_predicate(tmp_path):
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    chapter = api.draft_manual(ws, dict(author="J R Manning and M J Kahana", title="Interpreting semantic clustering effects",
                                        publisher="Oxford University Press", year="2024"), entry_type="incollection")
    assert "booktitle" in complete.KINDS["incollection"].required and not chapter.complete
    why = api.why_not_acceptable(chapter)
    assert "booktitle is missing (required for an entry of type incollection)" in why and not api.acceptable(chapter)
    whole = api.draft_manual(ws, dict(author="M J Kahana", title="Foundations of human memory", year="2012",
                                      publisher="Oxford University Press", address="New York, NY"), entry_type="book")
    assert api.acceptable(whole) == (api.why_not_acceptable(whole) == [])
    from dataclasses import replace
    cases = {
        "no entry is proposed": complete.Proposal(issues=["nothing found"]),
        "it is the same work as Kaha12, which is already in the library": replace(whole, complete=True, duplicate_of="Kaha12", issues=[]),
        "an entry of type dataset is not written from a source record": replace(whole, complete=True, unsupported="dataset", issues=[]),
        "format: the format checker would write pages as 1--2": replace(whole, complete=True, issues=["format: the format checker would write pages as 1--2", "a remark"]),
        "The edited key X does not match the key plan Kaha12; edit the key before accepting": replace(
            whole, complete=True, issues=["The edited key X does not match the key plan Kaha12; edit the key before accepting"]),
        "title is still a question: choose between what was typed and what the source has": replace(
            whole, complete=False, issues=[], changes=[complete.FieldChange("title", "a", "b", "crossref", "question")]),
    }
    for reason, proposal in cases.items():
        assert reason in api.why_not_acceptable(proposal), reason
        assert not api.acceptable(proposal)
    fine = replace(whole, complete=True, issues=["a remark that is not about the key or the format"])
    assert api.why_not_acceptable(fine) == [] and api.acceptable(fine)


def test_the_command_line_prints_the_reasons_after_its_sentence(tmp_path):
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    code = f'''
from cdlbib import api, cli
from cdlbib.workspace import Workspace
ws = Workspace({str(tmp_path)!r})
chapter = api.draft_manual(ws, dict(author="J R Manning and M J Kahana", title="Interpreting semantic clustering effects",
                                    publisher="Oxford University Press", year="2024"), entry_type="incollection")
print("ACCEPTED", cli.decide([chapter]))
'''
    status, out = terminal(tmp_path, code, "a\ns\n")
    assert status == 0, out
    sentence = "Cannot accept: complete required fields and resolve duplicate or unsupported entries first."
    assert sentence in out and "ACCEPTED []" in out
    after = out[out.index(sentence):].splitlines()
    assert "  - booktitle is missing (required for an entry of type incollection)" in after[1:6], after[:6]
