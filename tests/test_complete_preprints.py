"""Preprints of bioRxiv, medRxiv, the OSF servers and the other Crossref-registered servers:
built in the house form by ``complete.build_preprint`` and judged by each server's route of the
citation check (``preprint_review``, ``osf_review``, ``posted_review``).

Nothing here is invented. Every lookup is a real response fetched once on 2026-11-09
(tests/fixtures/completion/preprint_responses.json, written by
tests/fixtures/completion/record_preprint_responses.py; the README beside it lists them),
replayed through the project's real client over a real response cache with a transport that
refuses every request (the ``client`` fixture of test_complete_identify.py). So
``client.requests == 0`` shows that nothing was fetched. Where a test changes a saved
document, it says which value it changes and why; the change is made in the test's own copy.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from cdlbib import complete, osf_review, posted_review, preprint_review
from cdlbib.verification import load_entries

from test_complete_identify import client, library_entry, propose, typed_entry  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SAVED = json.loads((ROOT / "tests/fixtures/completion/preprint_responses.json").read_text(encoding="utf-8"))

ONE_KD = "10.64898/2026.03.19.712982"
ONE_KD_AUTHORS = ("H Raviv and L Hasenfratz and K Gousios and M Faryna and R Beaty and D Johnson and B Chen and "
                  "A Altenhof and B Ryan and C A Greenberg and Z Hong and G Assayag and A Tsyhanov and V Malakhov "
                  "and T Rosenwein and O Raviv and C Lew-Williams and U Hasson")
ONE_KD_TITLE = ("The first 1,000 days ({1kD}) project - collecting and analyzing an ultra-dense naturalistic "
                "dataset of human baby development")


def saved(key):
    """The saved response or document whose request (cache key) is ``key`` or starts with it."""
    for item in SAVED:
        request = item["request"]
        text = request if isinstance(request, str) else request[0]
        if text == key or text.startswith(key):
            return deepcopy(item["response"])
    raise KeyError(key)


def crossref(doi):
    """The Crossref record saved for ``doi`` (the client's trimmed record)."""
    from urllib.parse import quote
    return saved("https://api.crossref.org/works/" + quote(doi, safe=""))["body"]["message"]


def entry(text, tmp_path):
    return typed_entry(tmp_path, text)["fields"]


def rehash(document, old, new):
    """A changed copy of a saved document, its hash computed again over the changed body."""
    assert old in document["body"]
    document["body"] = document["body"].replace(old, new)
    document["document_sha256"] = hashlib.sha256(document["body"].encode()).hexdigest()
    return document


# --- bioRxiv ------------------------------------------------------------------------------------

def test_a_biorxiv_doi_of_the_2026_prefix_is_built_in_the_house_form_and_verified(client):
    proposal = propose(client, ONE_KD)
    assert proposal.proposed_raw == (
        "@article{RaviEtal26,\n\tAuthor = {" + ONE_KD_AUTHORS + "},\n\tDoi = {10.64898/2026.03.19.712982},\n"
        "\tJournal = {{bioRxiv}},\n\tTitle = {" + ONE_KD_TITLE + "},\n"
        "\tVolume = {10.64898/2026.03.19.712982},\n\tYear = {2026}}")
    assert proposal.status == "metadata_verified" and proposal.complete and not proposal.needs_decision
    assert proposal.unsupported is None and proposal.issues == [] and proposal.unfilled == []
    assert proposal.record_source == "crossref+biorxiv" and proposal.key_proposed == "RaviEtal26"
    assert [(c.field, c.kind, c.source) for c in proposal.changes] == [
        ("author", "filled", "crossref+biorxiv"), ("doi", "kept", "typed"), ("journal", "filled", "house rule"),
        ("title", "filled", "crossref+biorxiv"), ("volume", "filled", "biorxiv"),
        ("year", "filled", "biorxiv+crossref")]
    assert client.requests == 0


def test_the_hand_typed_1kd_entry_is_held_on_its_title_only(client, tmp_path):
    # The entry typed by hand (2026-11-09) writes ": collecting" where the registered title has
    # " - Collecting"; every other field is verified, and the typed title is kept.
    typed = ("@article{RaviEtal26,\n\tAuthor = {" + ONE_KD_AUTHORS + "},\n\tDoi = {10.64898/2026.03.19.712982},\n"
             "\tJournal = {{bioRxiv}},\n\tTitle = {The {First 1,000 Days (1kD) Project}: collecting and analyzing "
             "an ultra-dense naturalistic dataset of human baby development},\n"
             "\tVolume = {10.64898/2026.03.19.712982},\n\tYear = {2026}}")
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, typed)), client, client.cache)
    assert proposal.proposed_raw == typed and proposal.status == "needs_review" and proposal.needs_decision
    assert "title: missing evidence or mismatch" in proposal.issues
    judged = preprint_review.assess_preprint(entry(typed, tmp_path), saved("biorxiv-details-v1:" + ONE_KD),
                                             saved("biorxiv-html-v1:"), crossref(ONE_KD))
    assert judged["issues"] == ["title: missing evidence or mismatch"]
    evidence = judged["candidates"][0]["evidence"]
    assert all(evidence[name]["match"] for name in ("author", "year", "journal", "doi", "volume"))
    assert client.requests == 0


def test_a_biorxiv_preprint_with_two_versions_cites_the_latest_pinned_in_volume(client):
    proposal = propose(client, "10.1101/2021.05.10.443308")
    # XieEtal21 of the frozen library has the same authors, journal, title and year.
    assert proposal.proposed_raw == (
        "@article{XieEtal21,\n\tAuthor = {T Xie and J H Cheong and J R Manning and A M Brandt and J P Aronson and "
        "B C Jobst and K A Bujarski and L J Chang},\n\tDoi = {10.1101/2021.05.10.443308},\n\tJournal = {{bioRxiv}},\n"
        "\tTitle = {Minimal functional alignment of ventromedial prefrontal cortex intracranial {EEG} signals during "
        "naturalistic viewing},\n\tVolume = {10.1101/2021.05.10.443308v2},\n\tYear = {2021}}")
    library = library_entry("XieEtal21").split("\n")
    assert [line for line in library if not line.startswith("\tPages")] == [
        line for line in proposal.proposed_raw.split("\n") if not line.startswith(("\tDoi", "\tVolume"))]
    assert proposal.status == "metadata_verified" and not proposal.needs_decision
    assert client.requests == 0


def test_a_biorxiv_version_page_that_cannot_be_read_leaves_the_registry_and_history(tmp_path):
    fields = entry(propose_text(ONE_KD), tmp_path)
    api, primary = saved("biorxiv-details-v1:" + ONE_KD), crossref(ONE_KD)
    refused = {"unavailable": "Preprint source HTTP 403", "url": preprint_review.html_url(ONE_KD, 1)}
    for html in ({}, refused):
        result = preprint_review.assess_preprint(fields, api, html, primary)
        assert result["status"] == "metadata_verified" and result["accepted_version"] == 1
        assert result["candidates"][0]["version_page"] == "not read"
        assert preprint_review.valid_preprint_approval(result)
    # With the page, it is the page's byline that is compared.
    read = preprint_review.assess_preprint(fields, api, saved("biorxiv-html-v1:"), primary)
    assert read["status"] == "metadata_verified" and "version_page" not in read["candidates"][0]
    # Without the page, an earlier version is not checked against the current registry record.
    two = deepcopy(fields)
    two["volume"] = ONE_KD + "v1"
    revised = deepcopy(api)
    body = json.loads(revised["body"])
    body["collection"].append(dict(body["collection"][0], version="2", date="2026-04-01"))
    revised["body"] = json.dumps(body)
    revised["document_sha256"] = hashlib.sha256(revised["body"].encode()).hexdigest()
    assert preprint_review.assess_preprint(two, revised, {}, primary)["status"] == "needs_review"


def propose_text(doi):
    """The text the builder proposes for ``doi``, rebuilt from the saved documents."""
    return {ONE_KD: ("@article{RaviEtal26,\n\tAuthor = {" + ONE_KD_AUTHORS + "},\n"
                     "\tDoi = {10.64898/2026.03.19.712982},\n\tJournal = {{bioRxiv}},\n\tTitle = {" + ONE_KD_TITLE
                     + "},\n\tVolume = {10.64898/2026.03.19.712982},\n\tYear = {2026}}")}[doi]


@pytest.mark.parametrize("field, value", [
    ("author", ONE_KD_AUTHORS.replace("L Hasenfratz and K Gousios", "K Gousios and L Hasenfratz")),
    ("author", ONE_KD_AUTHORS.replace(" and U Hasson", "")),
    ("author", ONE_KD_AUTHORS.replace("C A Greenberg", "C B Greenberg")),
    ("year", "2025"), ("title", "The first 1,000 days project"), ("journal", "{medRxiv}"),
    ("volume", "10.64898/2026.03.19.712982v2"), ("volume", "10.1101/2026.03.19.712982"), ("pages", "1--20"),
])
def test_every_field_of_a_preprint_without_its_page_remains_binding(tmp_path, field, value):
    fields = entry(propose_text(ONE_KD), tmp_path)
    fields[field] = value
    result = preprint_review.assess_preprint(fields, saved("biorxiv-details-v1:" + ONE_KD), {}, crossref(ONE_KD))
    assert result["status"] == "needs_review"


@pytest.mark.parametrize("change", ["registry-author", "registry-order", "registry-title", "registry-date",
                                    "history-server"])
def test_without_the_page_history_and_registry_must_agree(tmp_path, change):
    fields = entry(propose_text(ONE_KD), tmp_path)
    api, primary = saved("biorxiv-details-v1:" + ONE_KD), crossref(ONE_KD)
    if change == "registry-author":
        primary["author"][3]["family"] = "Farina"
    elif change == "registry-order":
        primary["author"][0], primary["author"][1] = primary["author"][1], primary["author"][0]
    elif change == "registry-title":
        primary["title"] = [primary["title"][0] + " revisited"]
    elif change == "registry-date":
        primary["published"] = {"date-parts": [[2026, 3, 24]]}
    else:  # the same history read as medRxiv's
        api = rehash(api, '"server":"bioRxiv"', '"server":"medRxiv"')
    assert preprint_review.assess_preprint(fields, api, {}, primary)["status"] == "needs_review"


def test_a_preprint_whose_history_names_its_article_offers_the_article(client):
    # The bioRxiv preprint of ChenEtal21: its Crossref record names no published version, and
    # its bioRxiv history does (Current Biology, 2021). Before 2026-11-09 this DOI was left as
    # typed ("A record of type posted-content is not built automatically").
    proposal = propose(client, "10.1101/2020.01.27.922062")
    assert proposal.proposed_raw == library_entry("ChenEtal21")
    assert proposal.issues[0] == (
        "The DOI 10.1101/2020.01.27.922062 is a preprint; its bioRxiv record names 10.1016/j.cub.2021.07.061 as the "
        "published version, which is proposed here (house rule: cite the published version).")
    assert proposal.needs_decision and proposal.status == "metadata_verified"
    assert [(c["doi"], c["type"]) for c in proposal.candidates] == [
        ("10.1016/j.cub.2021.07.061", "journal-article"), ("10.1101/2020.01.27.922062", "posted-content")]
    assert client.requests == 0


# --- medRxiv ------------------------------------------------------------------------------------

MEDRXIV = "10.1101/2025.06.01.25328748"


def test_a_medrxiv_preprint_is_built_in_the_house_form_and_verified(client):
    proposal = propose(client, MEDRXIV)
    assert proposal.proposed_raw == (
        "@article{LemmEtal25,\n\tAuthor = {D A Lemma and L A Tema and M B Mena and H C Koyra},\n"
        "\tDoi = {10.1101/2025.06.01.25328748},\n\tJournal = {{medRxiv}},\n"
        "\tTitle = {Effect of therapeutic inertia on treatment outcomes in type 2 diabetes patients at a tertiary care "
        "hospital in southern ethiopia: A retrospective cohort study},\n"
        "\tVolume = {10.1101/2025.06.01.25328748},\n\tYear = {2025}}")
    assert proposal.status == "metadata_verified" and not proposal.needs_decision
    assert proposal.record_source == "crossref+medrxiv"
    assert client.requests == 0


def test_a_medrxiv_preprint_whose_history_and_registry_titles_differ_is_held(client, tmp_path):
    proposal = propose(client, "10.1101/2025.05.29.25327068")
    assert proposal.status == "needs_review" and proposal.needs_decision and not proposal.complete
    title = next(u for u in proposal.unfilled if u.field == "title")
    assert title.reason == "title: sources disagree" and title.source_values == {
        "crossref": "Predictors of outpatient hysteroscopy pain: A role for retrospective cervical screening pain "
                    "estimates? A service evaluation",
        "medrxiv": "Identifying predictors of outpatient hysteroscopy pain: A role for retrospective cervical "
                   "screening pain estimates? A service evaluation"}
    assert "Preprint unresolved: Repository and registry preprint titles conflict" in proposal.issues
    assert client.requests == 0


def test_a_medrxiv_citation_is_judged_against_the_medrxiv_history_only(tmp_path):
    text = ("@article{LemmEtal25,\n\tAuthor = {D A Lemma and L A Tema and M B Mena and H C Koyra},\n"
            "\tDoi = {10.1101/2025.06.01.25328748},\n\tJournal = {{medRxiv}},\n"
            "\tTitle = {Effect of therapeutic inertia on treatment outcomes in type 2 diabetes patients at a tertiary "
            "care hospital in southern ethiopia: A retrospective cohort study},\n"
            "\tVolume = {10.1101/2025.06.01.25328748},\n\tYear = {2025}}")
    fields = entry(text, tmp_path)
    api, primary = saved("medrxiv-details-v1:" + MEDRXIV), crossref(MEDRXIV)
    result = preprint_review.assess_preprint(fields, api, {}, primary)
    assert result["status"] == "metadata_verified" and result["candidates"][0]["url"].startswith(
        "https://www.medrxiv.org/content/")
    assert preprint_review.valid_preprint_approval(result)
    assert preprint_review.notice_dois(result["candidates"][0]) == set()
    # Cited as bioRxiv, the same history does not verify it.
    assert preprint_review.assess_preprint(dict(fields, journal="{bioRxiv}"), api, {}, primary)["status"] == "needs_review"
    # A withdrawal in the history blocks it.
    withdrawn = rehash(deepcopy(api), '"type":"PUBLISHAHEADOFPRINT"', '"type":"WITHDRAWN"')
    assert preprint_review.assess_preprint(fields, withdrawn, {}, primary)["status"] == "needs_review"


# --- PsyArXiv and the other OSF servers --------------------------------------------------------

def test_a_psyarxiv_preprint_is_built_as_the_library_cites_it(client):
    proposal = propose(client, "10.31234/osf.io/mhxtd_v1")
    assert proposal.proposed_raw == library_entry("FitzEtal26a").replace("FitzEtal26a,", "FitzEtal26,")
    assert proposal.status == "metadata_verified" and not proposal.needs_decision
    assert proposal.record_source == "osf+crossref"
    assert [(c.field, c.kind, c.source) for c in proposal.changes] == [
        ("author", "filled", "osf"), ("doi", "kept", "typed"), ("journal", "filled", "house rule"),
        ("title", "filled", "osf"), ("year", "filled", "osf")]
    # An unversioned DOI of a preprint whose latest version is its first.
    older = propose(client, "10.31234/osf.io/erzfp")
    assert older.proposed_raw == library_entry("MannEtal23a").replace("MannEtal23a,", "MannEtal23,").replace(
        "\tJournal = {{PsyArXiv}},", "\tDoi = {10.31234/osf.io/erzfp},\n\tJournal = {{PsyArXiv}},")
    assert older.status == "metadata_verified"
    assert client.requests == 0


def test_a_socarxiv_preprint_is_built_and_verified_through_the_osf_api(client, tmp_path):
    proposal = propose(client, "10.31235/osf.io/kv2qc")
    assert proposal.proposed_raw == (
        "@article{BurnEver24,\n\tAuthor = {K Burnell and P Everill},\n\tDoi = {10.31235/osf.io/kv2qc},\n"
        "\tJournal = {{SocArXiv}},\n\tTitle = {Excavating the past and (re)finding myself: why and in what ways do "
        "veterans and providers believe archaeology supports mental health and wellbeing?},\n\tYear = {2024}}")
    assert proposal.status == "metadata_verified"
    fields = entry(proposal.proposed_raw, tmp_path)
    assert osf_review.identifier(fields) == ("kv2qc", None, ["doi"])
    # The same DOI cited as PsyArXiv is not a PsyArXiv identifier.
    with pytest.raises(ValueError):
        osf_review.identifier(dict(fields, journal="{PsyArXiv}"))
    assert osf_review.doi_provider("10.31235/osf.io/kv2qc") == "socarxiv"
    assert osf_review.doi_provider("10.31234/osf.io/erzfp") == "psyarxiv"
    assert client.requests == 0


def test_a_psyarxiv_identifier_in_volume_is_dropped_by_the_house_rule(client, tmp_path):
    typed = ("@article{FitzEtal26a,\n\tAuthor = {P C Fitzpatrick and A Tahir and J Xu and S H Park and J R Manning},\n"
             "\tDoi = {10.31234/osf.io/mhxtd_v1},\n\tJournal = {{PsyArXiv}},\n"
             "\tTitle = {Delayed recountings preserve but simplify the semantic geometry of earlier recountings},\n"
             "\tVolume = {10.31234/osf.io/mhxtd_v1},\n\tYear = {2026}}")
    proposal = complete.propose(complete.Query.from_entry(typed_entry(tmp_path, typed)), client, client.cache)
    assert proposal.proposed_raw == library_entry("FitzEtal26a")
    assert complete.FieldChange("volume", "10.31234/osf.io/mhxtd_v1", None,
                                "house rule: a PsyArXiv identifier belongs in doi", "dropped") in proposal.changes
    assert proposal.status == "metadata_verified"
    assert client.requests == 0


# --- other servers, from their Crossref records -------------------------------------------------

@pytest.mark.parametrize("doi, text", [
    ("10.21203/rs.3.rs-4840802/v1",
     "@article{ChioEtal24,\n\tAuthor = {P Chiowchanwisawakit and W Ratta-apha and N Meannui},\n"
     "\tDoi = {10.21203/rs.3.rs-4840802/v1},\n\tJournal = {{Research Square}},\n"
     "\tTitle = {Construct validity and reliability of the thai version of the brief illness perception "
     "questionnaire and its association with overall functioning and health in patients with ankylosing "
     "spondylitis},\n\tVolume = {10.21203/rs.3.rs-4840802/v1},\n\tYear = {2024}}"),
    ("10.2139/ssrn.5238498",
     "@article{SaraEtal25,\n\tAuthor = {S Saravanan and A Bains and C {Ponzoni Carvalho Chanel} and D Vivet},\n"
     "\tDoi = {10.2139/ssrn.5238498},\n\tJournal = {{SSRN}},\n"
     "\tTitle = {Fit-slam 2: efficient 3{D} exploration with fisher information and traversability based adaptive "
     "roadmap},\n\tVolume = {10.2139/ssrn.5238498},\n\tYear = {2025}}"),
])
def test_a_preprint_of_another_server_is_built_from_its_crossref_record(client, doi, text):
    proposal = propose(client, doi)
    assert proposal.proposed_raw == text
    assert proposal.status == "metadata_verified" and not proposal.needs_decision
    assert proposal.record_source == "crossref-preprint"
    assert client.requests == 0


def posted_case(tmp_path, doi="10.21203/rs.3.rs-4840802/v1"):
    from urllib.parse import quote
    response = saved("https://api.crossref.org/works/" + quote(doi, safe=""))
    fields = {"ENTRYTYPE": "article", "ID": "ChioEtal24",
              "author": "P Chiowchanwisawakit and W Ratta-apha and N Meannui", "doi": doi,
              "journal": "{Research Square}", "volume": doi, "year": "2024",
              "title": "Construct validity and reliability of the thai version of the brief illness perception "
                       "questionnaire and its association with overall functioning and health in patients with "
                       "ankylosing spondylitis"}
    return fields, {"crossref": response}


def test_the_posted_preprint_route_verifies_and_rechecks_its_approval(tmp_path):
    fields, raw = posted_case(tmp_path)
    result = posted_review.assess_posted(fields, raw)
    assert result["status"] == "metadata_verified" and result["accepted_source"] == posted_review.SOURCE
    assert posted_review.valid_posted_approval(result)
    tampered = deepcopy(result)
    tampered["candidates"][0]["raw_record"]["crossref"]["body"]["message"]["title"] = ["Another title"]
    assert not posted_review.valid_posted_approval(tampered)


@pytest.mark.parametrize("change", [
    {"year": "2025"}, {"journal": "{SSRN}"}, {"volume": "10.21203/rs.3.rs-4840802/v2"},
    {"author": "P Chiowchanwisawakit and N Meannui and W Ratta-apha"}, {"title": "Construct validity"},
    {"pages": "1--10"}, {"doi": "10.21203/rs.3.rs-4840802/v2"},
])
def test_every_field_of_a_posted_preprint_remains_binding(tmp_path, change):
    fields, raw = posted_case(tmp_path)
    fields.update(change)
    assert posted_review.assess_posted(fields, raw)["status"] == "needs_review"


@pytest.mark.parametrize("relation, issue", [
    ({"is-preprint-of": [{"id-type": "doi", "id": "10.1186/s41927-025-00000-0", "asserted-by": "subject"}]},
     "published version exists (DOI 10.1186/s41927-025-00000-0): replacement candidate for user approval"),
    ({"has-version": [{"id-type": "doi", "id": "10.21203/rs.3.rs-4840802/v2", "asserted-by": "subject"}]},
     "version: the registry names other versions of this preprint; cite the latest"),
    ({"is-same-as": [{"id-type": "doi", "id": "10.1234/x", "asserted-by": "subject"}]},
     "Preprint unresolved: DOI registry relationship requires adjudication: is-same-as"),
])
def test_a_posted_preprint_with_a_published_or_later_version_does_not_verify(tmp_path, relation, issue):
    # The relation is this test's construction, added to the real record: the saved record names none.
    fields, raw = posted_case(tmp_path)
    raw["crossref"]["body"]["message"]["relation"] = relation
    result = posted_review.assess_posted(fields, raw)
    assert result["status"] == "needs_review" and issue in result["issues"]


def test_routes_claim_only_their_own_servers(tmp_path):
    fields, _ = posted_case(tmp_path)
    assert posted_review.applicable(fields)
    assert not posted_review.applicable(dict(fields, journal="{bioRxiv}"))
    assert not posted_review.applicable(dict(fields, doi=MEDRXIV, journal="{medRxiv}"))
    assert not posted_review.applicable(dict(fields, doi="10.31234/osf.io/erzfp", journal="{PsyArXiv}"))
    assert posted_review.server_name("10.2139/ssrn.5238498") == "SSRN"
    assert posted_review.server_name("10.1101/615203") is None
    assert preprint_review.server({"ENTRYTYPE": "article", "journal": "{medRxiv}"}) == "medrxiv"
    with pytest.raises(ValueError):
        preprint_review.server({"ENTRYTYPE": "article", "journal": "{Research Square}"})


def test_the_gate_runs_the_posted_route_after_the_other_preprint_routes():
    import inspect
    from cdlbib import verification_cli
    source = inspect.getsource(verification_cli.run_review_layers)
    assert source.index("run_preprint_review") < source.index("run_osf_review") < source.index("run_posted_review")
    from cdlbib.verification import APPROVAL_VALIDATORS
    assert posted_review.valid_posted_approval in APPROVAL_VALIDATORS


# --- a title's own capitals ---------------------------------------------------------------------

def test_a_word_with_capitals_of_its_own_keeps_them_in_braces():
    # Registered titles whose words were lowered to "1kd", "Saycam" and "babyview" (2026-11-09).
    from cdlbib.helpers import format_title
    cases = {
        "The First 1,000 Days (1kD) Project - Collecting and Analyzing an Ultra-Dense Naturalistic Dataset of "
        "Human Baby Development":
            "The first 1,000 days ({1kD}) project - collecting and analyzing an ultra-dense naturalistic dataset of "
            "human baby development",
        "SAYCam: A Large, Longitudinal Audiovisual Dataset Recorded From the Infant\u2019s Perspective":
            "{SAYCam}: A large, longitudinal audiovisual dataset recorded from the infant\u2019s perspective",
        "The BabyView dataset: High-resolution egocentric videos of infants' and young children's everyday "
        "experiences":
            "The {BabyView} dataset: high-resolution egocentric videos of infants' and young children's everyday "
            "experiences",
        "Self-Supervised Learning Through the Eyes of a Child": "Self-supervised learning through the eyes of a child",
        "Re-imagining fMRI for awake behaving infants": "Re-imagining {fMRI} for awake behaving infants",
    }
    for source, house in cases.items():
        assert format_title(complete._mixed_case_braced(source)) == house, source


def test_words_without_capitals_of_their_own_are_left_to_the_house_rules():
    assert complete._mixed_case_braced("EEG Collecting {DNA} $x^A$ \\'Etude iPhone-Based") == (
        "EEG Collecting {DNA} $x^A$ \\'Etude {iPhone}-Based")
