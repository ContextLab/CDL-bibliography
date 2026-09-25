"""PsyArXiv/OSF route: real OSF API documents (verification/routes-2026-09-25/fixtures).

Positive cases, correctable citations, published-version replacements and
negative controls (older version cited, withdrawn preprint, a different work
under a real identifier), plus offline resumability with zero requests.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bibcheck'))
import osf_review as o  # noqa: E402
import verification as v  # noqa: E402

DATA = json.loads((ROOT / 'verification/routes-2026-09-25/fixtures/osf_review.json').read_text())
CONTACT = 'jeremy.r.manning@dartmouth.edu'  # the project's real Crossref contact


def case(key):
    return deepcopy(DATA[key])


def assess(c):
    return o.assess_osf(c['fields'], c['raw'])


def apply(fields, proposal):
    out = dict(fields, **{k: val for k, val in proposal.items() if k != 'remove'})
    for name in proposal.get('remove', []):
        out.pop(name)
    return out


def test_hook_contract_is_available():
    # CONTRACT (2026-09-25): verification.register_approval_validator(fn).
    assert callable(v.register_approval_validator)
    assert o.valid_osf_approval in v.APPROVAL_VALIDATORS


@pytest.mark.parametrize('key', ['FitzEtal26a', 'FranLiu18'])
def test_latest_version_citations_verify(key):
    result = assess(case(key))
    assert result['status'] == 'metadata_verified', result['issues']
    assert result['accepted_source'] == o.SOURCE
    assert o.valid_osf_approval(result) and v.route_approval_valid(result)


def test_fitzetal26a_matches_versioned_doi_and_ordered_byline():
    result = assess(case('FitzEtal26a'))
    c = result['candidates'][0]
    assert result['accepted_doi'] == '10.31234/osf.io/mhxtd_v1' and c['version'] == 1
    assert [p['family'] for p in c['evidence']['author']['source']] == ['Fitzpatrick', 'Tahir', 'Xu', 'Park', 'Manning']


def test_legacy_file_revision_sets_the_latest_year():
    """ZimaEtal23: OSF record published 2019; primary file revision 3 dated 2023 (user-confirmed year)."""
    c = case('ZimaEtal23')
    result = assess(c)
    cand = result['candidates'][0]
    assert cand['category'] == 'proposal' and cand['file_revisions'] == 3
    assert cand['latest_date'].startswith('2023-04-10') and cand['evidence']['year']['match']
    assert cand['proposal'] == {'doi': '10.31234/osf.io/2ps6e', 'remove': ['volume']}
    fixed = apply(c['fields'], cand['proposal'])
    after = o.assess_osf(fixed, c['raw'])
    assert after['status'] == 'metadata_verified', after['issues']
    stale = dict(fixed, year='2019')  # the first-version year is not the latest version's year
    assert o.assess_osf(stale, c['raw'])['status'] == 'needs_review'


@pytest.mark.parametrize('key,published', [('GralFinn21', '10.1093/scan/nsac019'),
                                           ('LuriEtal18', '10.1162/netn_a_00116'),
                                           ('NussEtal18', '10.1037/xge0000753')])
def test_published_version_is_a_replacement_candidate_never_silent(key, published):
    c = case(key)
    result = assess(c)
    cand = result['candidates'][0]
    assert result['status'] == 'needs_review' and cand['category'] == 'replacement'
    assert cand['proposal']['replace_with_doi'] == published
    assert any('replacement candidate' in i for i in result['issues'])
    # Even with every preprint field repaired, the relation still blocks approval.
    repaired = apply(c['fields'], cand['proposal']['preprint_fields'])
    again = o.assess_osf(repaired, c['raw'])
    assert again['status'] == 'needs_review' and again['candidates'][0]['category'] == 'replacement'


def test_title_discovery_proposes_the_doi_and_then_verifies():
    c = case('MannEtal23a')
    assert 'doi' not in c['fields'] and c['raw']['discovered_by'] == 'title'
    cand = assess(c)['candidates'][0]
    assert cand['category'] == 'proposal' and cand['proposal'] == {'doi': '10.31234/osf.io/erzfp'}
    assert o.assess_osf(apply(c['fields'], cand['proposal']), c['raw'])['status'] == 'metadata_verified'


def test_control_older_version_is_corrected_to_the_latest():
    c = case('ControlOsfVersion')
    from correction_proposals import house_byline
    c['fields']['author'] = house_byline(o.contributors(c['raw']['contributors'], 'vbc87_v2'))
    result = assess(c)
    cand = result['candidates'][0]
    assert result['status'] == 'needs_review'
    assert 'version: citation pins v1; latest is v2' in result['issues']
    assert cand['category'] == 'proposal' and cand['proposal']['doi'] == '10.31234/osf.io/vbc87_v2'
    assert o.assess_osf(apply(c['fields'], cand['proposal']), c['raw'])['status'] == 'metadata_verified'


def test_control_withdrawn_preprint_is_held():
    result = assess(case('ControlOsfWithdrawn'))
    assert result['status'] == 'needs_review' and result['candidates'][0]['category'] == 'held'
    assert result['issues'] == ['OSF unresolved: OSF preprint is withdrawn']


def test_control_other_work_under_a_real_identifier_is_held():
    result = assess(case('ControlOsfOtherWork'))
    assert result['candidates'][0]['category'] == 'held' and 'title: missing evidence or mismatch' in result['issues']


def test_altered_source_body_or_foreign_envelope_is_rejected():
    c = case('FitzEtal26a')
    c['raw']['versions']['body'] += ' '  # any byte change breaks the saved SHA-256
    assert assess(c)['status'] == 'needs_review'
    c = case('FitzEtal26a'); c['raw']['base'] = '2ps6e'
    assert assess(c)['status'] == 'needs_review'


def test_tampered_approval_is_not_valid():
    result = assess(case('FitzEtal26a'))
    result['candidates'][0]['checked_fields']['year'] = '2025'
    assert not o.valid_osf_approval(result)


def seed(cache, raw):
    for value in raw.values():
        if isinstance(value, dict) and 'body' in value:
            cache.save_response('osf-source-v1:' + value['url'], value)


def test_collect_from_saved_documents_makes_no_requests(tmp_path):
    cache = v.Cache(tmp_path / 'routes.sqlite3')
    try:
        c = case('ZimaEtal23'); seed(cache, c['raw'])
        client = v.PoliteClient(cache, CONTACT)
        assert o.collect(cache, client, c['fields']) == c['raw'] and client.requests == 0
    finally:
        cache.close()


def test_run_route_verifies_then_repeats_with_zero_requests(tmp_path):
    c = case('FitzEtal26a')
    bib = tmp_path / 'test.bib'
    bib.write_text('@article{FitzEtal26a,\n\tAuthor = {%s},\n\tDoi = {%s},\n\tJournal = {{PsyArXiv}},\n\tTitle = {%s},\n\tYear = {%s}}\n'
                   % (c['fields']['author'], c['fields']['doi'], c['fields']['title'], c['fields']['year']))
    cache = v.Cache(tmp_path / 'routes.sqlite3')
    try:
        seed(cache, c['raw'])
        entry = v.load_entries(bib)['FitzEtal26a']
        cache.put(str(bib), entry, v.outcome('needs_review', ['No unambiguous, fully supported metadata match']))
        client = v.PoliteClient(cache, CONTACT)
        results = o.run_osf_review(str(bib), cache, client, str(tmp_path / 'report.jsonl'))
        assert results['FitzEtal26a']['status'] == 'metadata_verified' and client.requests == 0
        assert results['FitzEtal26a']['osf_review'] == {'policy': o.OSF_POLICY, 'category': 'verified'}
        again = o.run_osf_review(str(bib), cache, client, str(tmp_path / 'report.jsonl'))
        assert again == results and client.requests == 0
    finally:
        cache.close()


def test_non_psyarxiv_citations_do_not_apply():
    assert not o.applicable({'ENTRYTYPE': 'article', 'journal': 'bioRxiv', 'doi': '10.1101/123'})
    assert not o.applicable({'ENTRYTYPE': 'misc', 'journal': '{PsyArXiv}'})
    with pytest.raises(ValueError):
        o.identifier({'ENTRYTYPE': 'article', 'journal': '{PsyArXiv}', 'doi': '10.31234/osf.io/2ps6e',
                      'volume': '10.31234/osf.io/xbmyn'})
