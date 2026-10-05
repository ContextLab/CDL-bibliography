"""The workflows the command line shares with the interactive front ends: completion offers,
choosing a candidate, checking chosen keys through the one citation gate, the send a front
end may make, and the wording that moved to cdlbib.prompts.

Lookups are the suite's saved responses replayed through the real client and cache, with the
network refused by an unreachable proxy (environment only); the gate runs for real on tmp
libraries and real git checkouts; one test asks the live Crossref API, as tests/test_api.py
does. No mocks.
"""
import inspect

import pytest

import conftest
from cdlbib import api, cli, prompts, publish, verification_cli
from cdlbib.errors import CdlbibError, GateFailed, PublishRefused
from cdlbib.verification import Cache, load_entries, record_approval
from cdlbib.workspace import Workspace

from test_complete_cli import refused_network
from test_complete_identify import client, CONTACT, library_entry  # noqa: F401
from test_machinery_2026_09_25 import RAME72, crossref_contact
from test_publish import checkout, state  # noqa: F401

ZOLL90 = conftest.ZOLL90
GAME62 = library_entry("Game62")
BASE = "@book{Base20, author={A Smith}, title={Baseline}, year={2020}}\n"
REVIEW = dict(reviewer="@fixture", source="the journal's page", note="every field checked", github_login="fixture",
              github_id=1)


@pytest.fixture
def offline(monkeypatch):
    for name, value in refused_network().items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def stubs(tmp_path, client, offline):
    """A library of two typed stubs and a reference that has neither; the saved responses."""
    ws = Workspace(tmp_path)
    ws.bib.write_text("@article{Zoll90, doi={10.1002/tea.3660271011}}\n@article{Game62, doi={10.1037/h0041332}}\n",
                      encoding="utf-8")
    reference = tmp_path / "reference.bib"
    reference.write_text(BASE, encoding="utf-8")
    return ws, dict(reference=str(reference), database=str(client.cache.path), mailto=CONTACT)


# --- the wording moved, the names stayed ---------------------------------------------------------

def test_prompts_are_one_set_of_objects_under_the_old_names():
    for name in ("ANSWERS", "MOVED", "answers", "unsent_question", "CHOSEN_BY"):
        assert getattr(cli, name) is getattr(prompts, name)
    assert prompts.ANSWERS["discard"][0] == "d" and prompts.MOVED["discard"][0] == "m"
    assert set(prompts.CHOSEN_BY) == {"named", "--library", "CDLBIB_LIBRARY", "found", "managed"}
    assert verification_cli.settle_unsent is cli.settle_unsent


# --- completion offers ---------------------------------------------------------------------------

def test_offers_come_one_at_a_time_from_the_library_as_it_then_is(stubs):
    ws, where = stubs
    before = ws.bib.read_bytes()
    offers = api.completion_offers(ws, **where)
    first = next(offers)
    assert first.key == "Zoll90" and first.error is None and len(first.proposals) == 1
    proposal = first.proposals[0]
    assert proposal.complete and proposal.key_typed == "Zoll90" and api.worth_showing(proposal)
    assert not api.proposal_failed(proposal) and "Title = {Students' misunderstandings" in proposal.proposed_raw
    assert ws.bib.read_bytes() == before                         # nothing is written by offering
    applied = api.apply_proposals(ws, [proposal])                 # the decision is written before the next offer
    assert applied.written == ["Zoll90"] and applied.saved_copy.read_bytes() == before
    second = next(offers)
    assert second.key == "Game62" and second.proposals[0].typed_raw == "@article{Game62, doi={10.1037/h0041332}}"
    assert api.apply_proposals(ws, second.proposals).written == ["Game62"]
    assert list(offers) == []
    assert set(load_entries(ws.bib)) == {"Zoll90", "Game62"} and GAME62 in ws.bib.read_text(encoding="utf-8")


def test_offers_pass_over_what_was_seen_what_is_gone_and_what_is_accepted(stubs):
    ws, where = stubs
    found = load_entries(ws.bib)
    seen = {(str(ws.bib), "Zoll90", found["Zoll90"]["fingerprint"])}
    assert [offer.key for offer in api.completion_offers(ws, seen=seen, **where)] == ["Game62"]
    offers = api.completion_offers(ws, **where)
    ws.bib.write_text("@article{Zoll90, doi={10.1002/tea.3660271011}}\n", encoding="utf-8")   # Game62 is deleted meanwhile
    assert [offer.key for offer in offers] == ["Zoll90"]
    cache = Cache(where["database"], ledger=ws.revocations)
    try:
        record_approval(cache, ws.bib, "Zoll90", load_entries(ws.bib)["Zoll90"]["fingerprint"], REVIEW)
    finally:
        cache.close()
    assert list(api.completion_offers(ws, **where)) == []         # an accepted entry is never offered


def test_a_complete_entry_no_source_would_change_is_not_offered(tmp_path, client, offline):
    ws = Workspace(tmp_path)
    ws.bib.write_text(GAME62 + "\n", encoding="utf-8")
    reference = tmp_path / "reference.bib"
    reference.write_text(BASE, encoding="utf-8")
    where = dict(reference=str(reference), database=str(client.cache.path), mailto=CONTACT)
    assert api.completion_keys(ws, reference=where["reference"], database=where["database"]) == ["Game62"]
    offers = list(api.completion_offers(ws, **where))
    assert [(offer.key, offer.proposals, offer.error) for offer in offers] == [("Game62", [], None)]
    shown = api.propose(ws, keys=["Game62"], database=where["database"], mailto=CONTACT)
    assert len(shown) == 1 and shown[0].complete and not api.worth_showing(shown[0])


def test_a_lookup_that_fails_is_an_offer_that_says_so_and_the_others_still_come(tmp_path, client, offline):
    ws = Workspace(tmp_path)
    ws.bib.write_text("@article{Fail20, doi={10.5555/unavailable}}\n@article{Game62, doi={10.1037/h0041332}}\n",
                      encoding="utf-8")
    reference = tmp_path / "reference.bib"
    reference.write_text(BASE, encoding="utf-8")
    offers = list(api.completion_offers(ws, reference=str(reference), database=str(client.cache.path), mailto=CONTACT))
    assert [offer.key for offer in offers] == ["Fail20", "Game62"]
    failed = offers[0]
    assert failed.error is not None or api.proposal_failed(failed.proposals[0])
    assert failed.error is None or (isinstance(failed.error, str) and failed.error_kind.endswith("Error"))
    assert offers[1].error is None and offers[1].proposals[0].complete


def test_offers_for_a_library_that_cannot_be_read_or_selected(tmp_path, client, offline):
    ws = Workspace(tmp_path)
    ws.bib.write_text("@article{Broken, title = {never closed}", encoding="utf-8")
    assert list(api.completion_offers(ws, reference=str(tmp_path / "missing.bib"))) == []     # the gate reports it
    ws.bib.write_text(GAME62 + "\n", encoding="utf-8")
    with pytest.raises(CdlbibError, match="Entries could not be selected for completion"):
        api.completion_offers(ws, reference=str(tmp_path / "missing.bib"), database=str(client.cache.path))


# --- choosing a candidate ------------------------------------------------------------------------

def test_choosing_a_candidate_for_a_query_and_for_a_typed_entry(tmp_path, client, offline):
    from cdlbib import complete
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    where = dict(mailto=CONTACT, database=str(client.cache.path))
    picked = {"title": "A factorial analysis of verbal learning tasks", "doi": "10.1037/h0041332"}
    chosen = api.choose_candidate(ws, complete.Proposal(candidates=[picked]), picked, **where)
    assert chosen.complete and not api.proposal_failed(chosen)
    assert (chosen.key_proposed, chosen.key_typed, chosen.typed_raw) == ("Game62", None, None)
    assert chosen.proposed_raw == GAME62 and ws.bib.read_text(encoding="utf-8") == ""

    typed = "@article{MyKey, title={A factorial analysis of verbal learning tasks}, note={mine}}"
    kept = api.choose_candidate(ws, complete.Proposal(key_typed="MyKey", typed_raw=typed, candidates=[picked]), picked, **where)
    assert (kept.key_typed, kept.typed_raw) == ("MyKey", typed) and "10.1037/h0041332" in kept.proposed_raw

    missing = api.choose_candidate(ws, complete.Proposal(), {"doi": "10.9999/completion-cli-missing"}, **where)
    assert api.proposal_failed(missing) and missing.issues


def test_choosing_a_candidate_for_an_entry_of_the_library_reads_it_from_the_file(stubs):
    from cdlbib import complete
    ws, where = stubs
    where = dict(mailto=where["mailto"], database=where["database"])
    stub = "@article{Game62, doi={10.1037/h0041332}}"
    item = complete.Proposal(key_typed="Game62", typed_raw=stub, candidates=[{"doi": "10.1037/h0041332"}])
    chosen = api.choose_candidate(ws, item, item.candidates[0], in_library=True, **where)
    assert (chosen.key_typed, chosen.typed_raw, chosen.complete) == ("Game62", stub, True)
    assert api.apply_proposals(ws, [chosen]).written == ["Game62"]
    gone = complete.Proposal(key_typed="Elsewhere99", typed_raw=stub, candidates=item.candidates)
    with pytest.raises(CdlbibError, match="The selected entry changed on disk; review a new proposal"):
        api.choose_candidate(ws, gone, item.candidates[0], in_library=True, **where)


# --- checking chosen keys ------------------------------------------------------------------------

def approved_library(tmp_path, text, keys):
    ws = Workspace(tmp_path)
    ws.bib.write_text(text, encoding="utf-8")
    found = load_entries(ws.bib)
    cache = Cache(ws.database, ledger=ws.revocations)
    try:
        for key in keys:
            record_approval(cache, ws.bib, key, found[key]["fingerprint"], REVIEW)
    finally:
        cache.close()
    return ws


def test_check_keys_runs_the_one_gate_on_exactly_those_keys(tmp_path, offline):
    """Zoll90 holds an approval, so the gate settles it from the cache; Game62 is new and
    unverified but was not chosen, so nothing is asked about it (the network is refused)."""
    ws = approved_library(tmp_path, ZOLL90 + "\n\n" + GAME62 + "\n", ["Zoll90"])
    lines = []
    check = api.check_keys(ws, ["Zoll90"], progress=lines.append, mailto=CONTACT)
    assert check.ok and check.format.ok and check.citations.ok and check.citations.unresolved == {}
    assert lines == check.citations.lines
    # (the review layers' own progress lines come first, as in every gate run)
    assert [text for text in lines if text.startswith("citations:")] == [
        "citations: 1 of 1 chosen entries verified; network requests: 0"]
    assert lines[-1] == "library: 2 entries: human_verified=1, pending=1"
    assert set(check.citations.checked) == {"Zoll90"}
    assert check.citations.checked["Zoll90"]["status"] == "human_verified"
    assert check.citations.checked["Zoll90"]["human_review"] == REVIEW
    assert api.entry(ws, "Zoll90").result == check.citations.checked["Zoll90"]        # the refreshed, stored result


def test_check_keys_is_the_gate_with_keys_passed_in(tmp_path, offline):
    ws = approved_library(tmp_path, ZOLL90 + "\n\n" + GAME62 + "\n", ["Zoll90", "Game62"])
    said = []
    result = verification_cli.citation_gate(str(ws.bib), keys=["Game62"], echo=said.append, mailto=CONTACT)
    assert result == (True, {}, {"human_verified": 2})
    assert said[0] == "citations: 1 of 1 chosen entries verified; network requests: 0"
    assert "keys" in inspect.signature(verification_cli.citation_gate).parameters
    assert "keys" in inspect.signature(api.check_citations).parameters
    both = api.check_keys(ws, iter(["Game62", "Zoll90"]), mailto=CONTACT)
    assert both.ok and set(both.citations.checked) == {"Zoll90", "Game62"}
    everything = said[:]
    del said[:]
    verification_cli.citation_gate(str(ws.bib), all_entries=True, echo=said.append, mailto=CONTACT)   # as it always was
    assert said[0] == "citations: 2 of 2 entries verified; network requests: 0" and said[1:] == everything[1:]


def test_check_keys_reports_a_format_finding_on_a_chosen_key(tmp_path, offline):
    bad = GAME62.replace("1--11", "1-11")
    ws = approved_library(tmp_path, ZOLL90 + "\n\n" + bad + "\n", ["Zoll90", "Game62"])
    chosen = api.check_keys(ws, ["Game62"], mailto=CONTACT)
    assert not chosen.ok and chosen.citations.ok and chosen.format.corrections == {"Game62": {"pages": "1--11"}}
    other = api.check_keys(ws, ["Zoll90"], mailto=CONTACT)        # a finding on another entry is reported, not held against it
    assert other.ok and not other.format.ok and other.format.errors == ["Game62"]


def test_check_keys_refuses_keys_the_library_does_not_have(tmp_path, offline):
    ws = approved_library(tmp_path, ZOLL90 + "\n", ["Zoll90"])
    for keys in (["Nope99"], ["Zoll90", "Nope99"], []):
        with pytest.raises(GateFailed, match="citation keys absent from the bibliography"):
            api.check_keys(ws, keys, mailto=CONTACT)


def test_check_keys_cannot_verify_an_unverified_key_without_its_sources(tmp_path, offline):
    ws = approved_library(tmp_path, ZOLL90 + "\n\n" + GAME62 + "\n", ["Zoll90"])
    with pytest.raises(GateFailed, match="citation check failed"):
        api.check_keys(ws, ["Game62"], mailto=CONTACT)
    assert api.entry(ws, "Game62").status == "provider_error"     # recorded as the gate records it, never accepted


def test_check_keys_verifies_a_chosen_entry_against_crossref(tmp_path):
    """The live Crossref API, as tests/test_api.py: the right volume verifies, and the entry
    that was not chosen is left pending."""
    ws = Workspace(tmp_path)
    ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n", encoding="utf-8")
    lines = []
    check = api.check_keys(ws, ["Rame72"], progress=lines.append, mailto=crossref_contact())
    assert check.ok and set(check.citations.checked) == {"Rame72"}
    assert check.citations.checked["Rame72"]["status"] == "metadata_verified"
    assert [text.split(";")[0] for text in lines if text.startswith("citations:")] == [
        "citations: 1 of 1 chosen entries verified"]
    assert {item.key: item.status for item in api.entries(ws)} == {"Zoll90": "pending", "Rame72": "metadata_verified"}
    ws.bib.write_text(ZOLL90 + "\n\n" + RAME72 % "2" + "\n", encoding="utf-8")     # Crossref: volume 1
    wrong = api.check_keys(ws, ["Rame72"], mailto=crossref_contact())
    assert not wrong.ok and "Rame72" in wrong.citations.unresolved


# --- the send a front end may make ---------------------------------------------------------------

def test_send_checked_takes_nothing_that_could_weaken_or_redirect_a_send():
    assert list(inspect.signature(api.send_checked).parameters) == [
        "ws", "summary", "progress", "report", "allow_fork_creation"]
    assert all(parameter.kind is not inspect.Parameter.VAR_KEYWORD and parameter.kind is not inspect.Parameter.VAR_POSITIONAL
               for parameter in inspect.signature(api.send_checked).parameters.values())


@pytest.mark.parametrize("bypass", [dict(citations=False), dict(reference="mine.bib"), dict(database="other.sqlite3"),
                                    dict(upstream="someone/else"), dict(fork="someone/fork"), dict(base="dev"),
                                    dict(outfile="summary.txt"), dict(mailto="x@example.org"), dict(verbose=True),
                                    dict(bars=None), dict(_test_inside_own_fork=True), dict(autofix=True)])
def test_send_checked_refuses_every_bypass_argument_before_doing_anything(checkout, bypass):
    ws, _ = checkout
    ws.bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    before = state(ws.root), ws.bib.read_bytes()
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        api.send_checked(ws, **bypass)
    with pytest.raises(TypeError):
        api.send_checked(ws, None, None, None, False, "github")   # nor positionally
    assert (state(ws.root), ws.bib.read_bytes()) == before and not ws.work.exists()


def test_send_checked_runs_the_gate_and_a_failed_gate_sends_nothing(checkout):
    ws, remote = checkout
    with pytest.raises(PublishRefused, match="There are no changes"):
        api.send_checked(ws)
    ws.bib.write_text(ZOLL90.replace("1053--1065", "1053-1065") + "\n", encoding="utf-8")
    before, reports, lines = state(ws.root), [], []
    with pytest.raises(GateFailed, match="not sent: fix the format errors") as failed:
        api.send_checked(ws, summary="a bad entry", progress=lines.append, report=reports.append, allow_fork_creation=True)
    assert len(reports) == 1 and reports[0] == failed.value.check and not reports[0].format.ok
    assert reports[0] is not failed.value.check                   # a callback is given a copy of the gate's result
    assert reports[0].format.corrections == {"Zoll90": {"pages": "1053--1065"}} and lines == []
    assert state(ws.root) == before and publish.current_branch(ws) == "master"
    from test_publish import git
    assert git(remote, "for-each-ref", "--format=%(refname)", "refs/heads/cdlbib/") == ""


@pytest.mark.parametrize("tamper,said", [
    (lambda check: setattr(check, "citations_due", False), "citation check failed"),     # the citations still run
    (lambda check: setattr(check, "ok", True), "citation check failed"),
])
def test_a_report_callback_cannot_switch_the_citation_check_off(checkout, offline, tamper, said):
    """A changed, unverified entry with the network refused: were the citation check skipped
    the send would go on to the fork lookup; it must stop at the check instead."""
    ws, remote = checkout
    ws.bib.write_text(ZOLL90 + "\n", encoding="utf-8")
    before, seen = state(ws.root), []

    def report(check):
        seen.append((check.citations_due, check.ok))
        tamper(check)

    with pytest.raises(GateFailed, match=said):
        api.send_checked(ws, report=report)
    assert seen == [(True, True)] and state(ws.root) == before and publish.current_branch(ws) == "master"


@pytest.mark.parametrize("tamper", [
    lambda check: setattr(check, "ok", True),
    lambda check: (setattr(check, "ok", True), setattr(check.format, "errors", []), setattr(check.format, "failure", "")),
    lambda check: setattr(check, "citations_due", False),
])
def test_a_report_callback_cannot_pass_a_format_failure(checkout, offline, tamper):
    ws, remote = checkout
    ws.bib.write_text(ZOLL90.replace("1053--1065", "1053-1065") + "\n", encoding="utf-8")
    before = state(ws.root)
    with pytest.raises(GateFailed, match="not sent: fix the format errors") as failed:
        api.send_checked(ws, report=tamper)
    assert failed.value.check.format.errors == ["Zoll90"] and not failed.value.check.ok
    assert state(ws.root) == before and publish.current_branch(ws) == "master"


# --- one rule from a candidate to a query ----------------------------------------------------------

@pytest.mark.parametrize("candidate,expected", [
    ({"source": "arxiv", "arxiv": "2208.02957", "doi": "10.48550/arXiv.2208.02957"}, ("arxiv", "2208.02957")),
    ({"source": "arxiv", "arxiv": "https://arxiv.org/abs/2208.02957v2"}, ("arxiv", "2208.02957v2")),
    ({"source": "crossref", "doi": "10.1037/h0041332", "arxiv": "2208.02957", "pmid": "1"}, ("doi", "10.1037/h0041332")),
    ({"doi": "10.1037/h0041332", "title": "A title"}, ("doi", "10.1037/h0041332")),
    ({"source": "pubmed", "pmid": 13946309, "title": "A title"}, ("pmid", "13946309")),
    ({"source": "pubmed", "arxiv": "2208.02957"}, ("arxiv", "2208.02957")),
    ({"title": "A factorial analysis of verbal learning tasks"}, ("title", "A factorial analysis of verbal learning tasks")),
])
def test_one_rule_names_a_candidate(candidate, expected):
    from cdlbib.complete import Query
    query = Query.from_candidate(candidate)
    name, value = expected
    assert getattr(query, name) == value
    assert [other for other in ("doi", "pmid", "arxiv", "title") if getattr(query, other)] == [name]


def test_a_candidate_with_nothing_to_look_up_is_refused(tmp_path):
    from cdlbib import complete
    with pytest.raises(ValueError, match="no DOI, PMID, arXiv id or title"):
        complete.Query.from_candidate({"source": "crossref", "authors": "A Smith"})
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    with pytest.raises(CdlbibError, match="no DOI, PMID, arXiv id or title"):
        api.choose_candidate(ws, complete.Proposal(), {"authors": "A Smith"})


# --- a manual draft stays writable after it is edited -------------------------------------------------

@pytest.mark.parametrize("kind,fields,edit", [
    ("book", dict(author="M J Kahana", title="Foundations of human memory", publisher="Oxford University Press",
                  address="New York, NY", year="2012"), ("2012", "2013")),
    ("incollection", dict(author="J R Manning and M J Kahana", title="Interpreting semantic clustering effects in free recall",
                          booktitle="The Oxford handbook of human memory", publisher="Oxford University Press",
                          editor="M J Kahana and A D Wagner", pages="1--20", year="2024"), ("1--20", "1--22")),
])
def test_a_manual_draft_of_any_type_is_written_after_an_edit(tmp_path, client, offline, kind, fields, edit):
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    draft = api.draft_manual(ws, fields, entry_type=kind)
    assert draft.manual and draft.proposed_raw and not draft.unsupported
    edited = draft.proposed_raw.replace(*edit)
    assert edited != draft.proposed_raw
    again = api.recheck_proposal(ws, draft, edited, mailto=CONTACT, database=str(client.cache.path))
    assert again.manual and again.unsupported is None and again.entry_type.lower() == kind
    applied = api.apply_proposals(ws, [again])
    assert applied.written == [again.key_proposed] and applied.refused == []
    # (an edited year changes the house key; the accepted key plan is what is written)
    assert ws.bib.read_text(encoding="utf-8") == edited.replace("{" + draft.key_proposed + ",", "{" + again.key_proposed + ",")
    assert api.entry(ws, again.key_proposed).status == "pending"       # written, and still unverified


def test_a_builder_proposal_edited_into_another_type_is_still_unsupported(tmp_path, client, offline):
    from cdlbib import complete
    ws = Workspace(tmp_path)
    ws.bib.write_text("", encoding="utf-8")
    built = complete.propose(complete.Query.parse("10.1037/h0041332"), client, client.cache, ws=ws)
    assert not built.manual
    as_book = api.recheck_proposal(ws, built, built.proposed_raw.replace("@article{", "@book{"), mailto=CONTACT,
                                   database=str(client.cache.path))
    assert as_book.unsupported and api.apply_proposals(ws, [as_book]).refused


# --- everything a front end receives is plain data ---------------------------------------------------

def test_as_data_makes_every_result_plain_and_loses_nothing(tmp_path, client, offline, checkout):
    import dataclasses
    import datetime
    import json
    from pathlib import Path
    from cdlbib import complete, library
    ws = approved_library(tmp_path / "lib", ZOLL90 + "\n\n" + GAME62 + "\n", ["Zoll90"]) if (tmp_path / "lib").mkdir() is None else None
    reference = tmp_path / "reference.bib"
    reference.write_text(BASE, encoding="utf-8")
    where = dict(database=str(client.cache.path), mailto=CONTACT)
    summaries = api.entries(ws)
    detail = api.entry(ws, "Zoll90")
    preview = api.preview_edit(ws, "Game62", GAME62.replace("{Game62,", "{Games1962,").replace("1--11", "1-11"))
    saved = api.save_edit(ws, "Game62", GAME62.replace("{Game62,", "{Games1962,"), api.entry(ws, "Game62").fingerprint)
    proposals = api.propose_new(ws, ["10.9999/completion-cli-missing", "10.1037/h0041332"], **where)
    offers = list(api.completion_offers(ws, reference=str(reference), **where))
    failed = api.CompletionOffer("Key20", [], "no such record", "CdlbibError")
    results = dict(
        summaries=summaries, detail=detail, queue=api.review_queue(ws, all_entries=True), preview=preview, saved=saved,
        state=api.library_state(checkout[0]), prepared=api.prepare(ws), revision=api.revision(ws),
        check=api.check_keys(ws, ["Zoll90"], mailto=CONTACT), format=api.check_format(ws), proposals=proposals,
        offers=offers, failed=failed, where=api.where(str(ws.bib)), behind=library.Behind("master", "a" * 40, "master", ""),
        status=api.status(ws), revoke=api.RevokeResult([{"key": "Zoll90"}], "needs_review"),
        update=library.UpdateResult("up_to_date", message="up to date"),
        error=api.as_data(CdlbibError("a failure")), mixed={1: (Path("/tmp/x"), {"b", "a"}), "when": datetime.date(2026, 10, 5)})
    data = api.as_data(results)
    text = json.dumps(data)                                       # no default= needed: it is all plain
    assert json.loads(text) == data
    # nothing is lost: each dataclass keeps every field, by name
    assert data["summaries"][0] == dataclasses.asdict(summaries[0]) | {"issues": list(summaries[0].issues)}
    assert set(data["detail"]) == {f.name for f in dataclasses.fields(detail)}
    assert data["detail"]["result"] == detail.result and data["detail"]["fingerprint"] == detail.fingerprint
    assert data["preview"]["key_change"] == {"old": "Game62", "new": "Games1962", "kind": "rename"}
    assert data["preview"]["format"] and set(data["preview"]["format"][0]) == {"field", "current", "corrected", "message"}
    assert data["saved"]["written"] == ["Games1962"] and data["saved"]["renamed"] == {"Game62": "Games1962"}
    assert data["saved"]["saved_copy"] == str(saved.saved_copy)
    assert data["state"]["root"] == str(checkout[0].root) and data["state"]["branch"] == "master"
    assert data["prepared"]["entries"] == 2 and isinstance(data["revision"], list)
    assert data["check"]["citations"]["checked"]["Zoll90"]["status"] == "human_verified" and data["check"]["ok"] is True
    assert set(data["proposals"]) == {"items", "errors"} and len(data["proposals"]["items"]) == 2
    assert data["proposals"]["errors"] == [list(item) for item in proposals.errors] and proposals.errors
    assert data["proposals"]["items"][1]["proposed_raw"] == proposals[1].proposed_raw
    assert data["proposals"]["items"][1]["changes"][0] == dataclasses.asdict(proposals[1].changes[0])
    assert data["failed"] == {"key": "Key20", "proposals": [], "error": "no such record", "error_kind": "CdlbibError"}
    assert all(set(offer) == {"key", "proposals", "error", "error_kind"} for offer in data["offers"])
    assert data["error"] == {"error_kind": "CdlbibError", "error": "a failure"}
    assert data["mixed"] == {"1": ["/tmp/x", ["a", "b"]], "when": "2026-10-05"}
    assert data["where"]["root"] == str(ws.bib) and data["update"]["action"] == "up_to_date"
    # and the plainer route the web layer may take also works on each of them
    for value in results.values():
        if dataclasses.is_dataclass(value):
            json.dumps(dataclasses.asdict(value), default=str)
    assert isinstance(complete.Proposal(), object)
