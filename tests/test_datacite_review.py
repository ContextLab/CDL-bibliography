"""DataCite route: real Zenodo/OSF registry records (verification/routes-2026-09-25/fixtures).

Positive: Spee22 (version DOI, registry title). Proposals: Mann26 (the second
creator DataCite lists, a non-person printed as "Claude"), Mann21b (DOI out of
volume, @misc). Held: FitzEtal25 (registry byline has fewer initials),
Mann21d (discovered concept DOI; GitHub link not in the record). Controls: a
different release of the same software, and a different work with the same title.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bibcheck'))
import datacite_review as d  # noqa: E402
import verification as v  # noqa: E402

DATA = json.loads((ROOT / 'verification/routes-2026-09-25/fixtures/datacite_review.json').read_text())
CONTACT = 'jeremy.r.manning@dartmouth.edu'


def case(key):
    return deepcopy(DATA[key])


def assess(c):
    return d.assess_datacite(c['fields'], c['raw'])


def apply(fields, proposal):
    out = dict(fields, **{k: val for k, val in proposal.items() if k != 'remove'})
    for name in proposal.get('remove', []):
        out.pop(name)
    return out


def test_validator_registered_through_hook():
    assert d.valid_datacite_approval in v.APPROVAL_VALIDATORS


def test_spee22_verifies_on_registry_title_creator_year_doi_and_repository():
    result = assess(case('Spee22'))
    assert result['status'] == 'metadata_verified', result['issues']
    c = result['candidates'][0]
    assert result['accepted_doi'] == '10.5281/zenodo.7199437' and c['version'] == 'v3.0.2'
    assert c['evidence']['howpublished']['match'] and c['resource_type'] == 'Software'
    assert d.valid_datacite_approval(result) and v.route_approval_valid(result)


def test_mann26_proposal_adds_the_second_creator_as_printed():
    c = case('Mann26')
    result = assess(c)
    cand = result['candidates'][0]
    assert cand['category'] == 'proposal' and cand['proposal'] == {'author': 'J R Manning and {Claude}'}
    assert cand['concept'] is True  # the cited concept DOI serves the latest version
    # House software title: Owner/repo from the registry title + the registry version string.
    assert cand['evidence']['title']['match'] and cand['evidence']['title']['source']['version'] == 'v1.0-winter2026'
    after = d.assess_datacite(apply(c['fields'], cand['proposal']), c['raw'])
    assert after['status'] == 'metadata_verified', after['issues']


def test_house_title_needs_the_registry_version():
    c = case('Mann26')
    c['fields'] = dict(c['fields'], title='{ContextLab}/llm-course: {v1.1}', author='J R Manning and {Claude}')
    assert 'title: missing evidence or mismatch' in assess(c)['issues']


def test_mann21b_moves_doi_out_of_volume_and_cites_misc():
    c = case('Mann21b')
    cand = assess(c)['candidates'][0]
    assert cand['category'] == 'proposal'
    assert cand['proposal'] == {'doi': '10.5281/zenodo.5123310', 'ENTRYTYPE': 'misc', 'remove': ['journal', 'volume']}
    assert d.assess_datacite(apply(c['fields'], cand['proposal']), c['raw'])['status'] == 'metadata_verified'


def test_less_detailed_registry_byline_is_held():
    result = assess(case('FitzEtal25'))
    assert result['candidates'][0]['category'] == 'held'
    assert any('less detail' in i for i in result['issues'])


def test_discovered_concept_doi_without_repository_evidence_is_held():
    c = case('Mann21d')
    cand = assess(c)['candidates'][0]
    assert cand['doi'] == '10.5281/zenodo.5182774' and cand['category'] == 'held'
    assert 'howpublished: missing evidence or mismatch' in cand['issues']


def test_control_different_release_is_held():
    result = assess(case('ControlDataciteVersion'))
    assert result['status'] == 'needs_review' and result['candidates'][0]['category'] == 'held'
    assert 'title: missing evidence or mismatch' in result['issues']


def test_control_different_work_same_title_is_held():
    result = assess(case('ControlDataciteOtherWork'))
    assert result['candidates'][0]['category'] == 'held'
    assert "StudyRegistration" in result['issues'][0]


def test_tampered_record_or_approval_is_rejected():
    c = case('Spee22'); c['raw']['record']['body'] += ' '
    assert assess(c)['status'] == 'needs_review'
    result = assess(case('Spee22')); result['candidates'][0]['checked_fields']['author'] = 'R Speerr'
    assert not d.valid_datacite_approval(result)


def test_collect_from_saved_documents_makes_no_requests(tmp_path):
    cache = v.Cache(tmp_path / 'routes.sqlite3')
    try:
        for key in ('Spee22', 'Mann21d'):
            c = case(key)
            for value in c['raw'].values():
                if isinstance(value, dict) and 'body' in value:
                    cache.save_response('datacite-source-v1:' + value['url'], value)
            client = v.PoliteClient(cache, CONTACT)
            assert d.collect(cache, client, c['fields']) == c['raw'] and client.requests == 0
    finally:
        cache.close()


@pytest.mark.parametrize('fields,expected', [
    ({'ENTRYTYPE': 'misc', 'doi': '10.5281/zenodo.1'}, True),
    ({'ENTRYTYPE': 'misc', 'publisher': 'Zenodo', 'title': 'x'}, True),
    ({'ENTRYTYPE': 'article', 'journal': 'Psychology and Aging', 'title': 'The DRYAD theory'}, False),
    ({'ENTRYTYPE': 'misc', 'doi': '10.1037/a0026411'}, False),  # a Crossref DOI is never looked up here
])
def test_applicability(fields, expected):
    assert d.applicable(fields) is expected
