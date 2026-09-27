"""SfN abstract planner route: real OASIS search results and abstract pages (SfN 2012).

RamaEtal12b (program 800.09; the planner lists Baltuch before Kahana) and
SommEtal12 (746.04; cited as @conference with a publisher) become house-form
proposals that verify once applied. KrauEtal12 is held (surname consensus).
Unsupported years are reported explicitly with no request.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bibcheck'))
import sfn_abstracts as s  # noqa: E402
import verification as v  # noqa: E402

DATA = json.loads((ROOT / 'verification/routes-2026-09-25/fixtures/sfn_abstracts.json').read_text())
CONTACT = 'jeremy.r.manning@dartmouth.edu'


@pytest.fixture(autouse=True)
def frozen_library(monkeypatch):
    # The surname-consensus check reads the library; use the bibliography as frozen before
    # the research waves were applied, so correcting an entry never changes these tests.
    import correction_proposals as cp
    monkeypatch.setattr(cp, 'LIBRARY_BIB', ROOT / 'tests/fixtures/cdl-prewave1-2026-09-26.bib')


def case(key):
    return deepcopy(DATA[key])


def assess(c):
    return s.assess_sfn(c['fields'], c['raw'])


def apply(fields, proposal):
    out = dict(fields, **{k: val for k, val in proposal.items() if k != 'remove'})
    for name in proposal.get('remove', []):
        out.pop(name)
    return out


def test_validator_registered_through_hook():
    assert s.valid_sfn_approval in v.APPROVAL_VALIDATORS


def test_ramaetal12b_proposal_reorders_authors_and_adds_program_number():
    c = case('RamaEtal12b')
    result = assess(c)
    cand = result['candidates'][0]
    assert cand['category'] == 'proposal' and cand['program'] == '800.09'
    assert cand['proposal'] == {
        'author': 'A G Ramayya and K A Zaghloul and B C Lega and C T Weidemann and G H Baltuch and M J Kahana',
        'number': '800.09'}
    after = s.assess_sfn(apply(c['fields'], cand['proposal']), c['raw'])
    assert after['status'] == 'metadata_verified', after['issues']
    assert s.valid_sfn_approval(after) and v.route_approval_valid(after)


def test_sommetal12_proposal_is_the_house_form():
    c = case('SommEtal12')
    cand = assess(c)['candidates'][0]
    assert cand['category'] == 'proposal' and cand['program'] == '746.04'
    assert cand['proposal'] == {'number': '746.04', 'booktitle': 'Society for Neuroscience Abstracts',
                                'address': 'New Orleans, {LA}', 'organization': 'Society for Neuroscience',
                                'ENTRYTYPE': 'inproceedings', 'remove': ['publisher']}
    fixed = apply(c['fields'], cand['proposal'])
    assert s.assess_sfn(fixed, c['raw'])['status'] == 'metadata_verified'
    # Negative controls on the fixed entry: wrong program number, wrong author order.
    assert s.assess_sfn(dict(fixed, number='746.05'), c['raw'])['status'] == 'needs_review'
    swapped = dict(fixed, author='G Buzsaki and F T Sommer and G Agarwal')
    assert s.assess_sfn(swapped, c['raw'])['status'] == 'needs_review'


def test_ligature_title_matches_after_compatibility_normalization():
    c = case('RamaEtal12b')
    assert 'ﬁ' in c['raw']['view']['body'] or '&#64257;' in c['raw']['view']['body']
    assert assess(c)['candidates'][0]['evidence']['title']['match']


def test_control_other_abstract_by_the_same_author_is_held():
    c = case('RamaEtal12b')
    c['fields'] = dict(c['fields'], title='A non-linear relation between human neuronal spiking and broadband '
                                         'high frequency power in the local field potential')
    result = assess(c)
    assert result['status'] == 'needs_review' and result['candidates'][0]['category'] == 'held'


def test_control_wrong_year_uses_another_meeting():
    c = case('RamaEtal12b'); c['fields'] = dict(c['fields'], year='2011')
    result = assess(c)
    assert result['status'] == 'needs_review'
    assert 'Saved SfN search is for another meeting or author' in result['issues'][0]


def test_held_on_surname_consensus():
    result = assess(case('KrauEtal12'))
    assert result['candidates'][0]['category'] == 'held'
    assert any('library consensus' in i for i in result['issues'])


@pytest.mark.parametrize('year', ['2006', '2003', '2017'])
def test_unsupported_years_are_reported_without_requests(tmp_path, year):
    c = case('DerdEtal06'); c['fields'] = dict(c['fields'], year=year)
    cache = v.Cache(tmp_path / 'routes.sqlite3')
    try:
        client = v.PoliteClient(cache, CONTACT)
        raw = s.collect(cache, client, c['fields'])
        assert raw == {} and client.requests == 0
    finally:
        cache.close()
    result = s.assess_sfn(c['fields'], raw)
    assert result['candidates'][0]['category'] == 'unsupported'
    assert result['issues'][0].startswith('SfN abstract planner: %s is unsupported' % year)


def test_journal_of_neuroscience_articles_do_not_apply():
    assert not s.applicable({'ENTRYTYPE': 'misc', 'journal': 'The Journal of Neuroscience', 'publisher': 'Society for Neuroscience'})
    assert s.applicable(case('SommEtal12')['fields'])


def test_collect_from_saved_documents_makes_no_requests(tmp_path):
    cache = v.Cache(tmp_path / 'routes.sqlite3')
    try:
        c = case('SommEtal12')
        cache.save_response('sfn-search-v1:' + c['raw']['search']['url'], c['raw']['search'])
        cache.save_response('sfn-source-v1:' + c['raw']['view']['url'], c['raw']['view'])
        client = v.PoliteClient(cache, CONTACT)
        assert s.collect(cache, client, c['fields']) == c['raw'] and client.requests == 0
    finally:
        cache.close()


def test_tampered_page_is_rejected():
    c = case('SommEtal12'); c['raw']['view']['body'] = c['raw']['view']['body'].replace('746.04', '746.05')
    assert assess(c)['candidates'][0]['category'] == 'held'


def test_2009_page_layout_and_one_digit_program_number():
    """SfN 2009 pages label "Title", print "<b>J.R. Manning</b>, None;" and number posters 279.3."""
    c = case('MannEtal09b')
    item = s.abstract(c['raw']['view'], c['raw']['view']['url'], 2009)
    assert item['program'] == '279.3' and item['city'] == 'Chicago, IL'
    assert [p['family'] for p in item['authors']] == ['Manning', 'Polyn', 'Kahana']
    # The cited undotted "JR" is not the planner's "J. R.": held, never rewritten.
    result = assess(c)
    assert result['candidates'][0]['category'] == 'held' and any('less detail' in i for i in result['issues'])


def test_route_merge_accepts_an_approval_without_a_doi():
    # SfN abstracts have no DOI; the shared route merge used to read result['accepted_doi']
    # and raised KeyError for a verified SfN result (stage 2C, RamaEtal12b).
    from osf_review import merge
    c = case('RamaEtal12b')
    cand = assess(c)['candidates'][0]
    after = s.assess_sfn(apply(c['fields'], cand['proposal']), c['raw'])
    assert after['status'] == 'metadata_verified' and 'accepted_doi' not in after
    merged = merge({'candidates': [], 'attempts': []}, after, s.SOURCE, 'https://www.abstractsonline.com/')
    assert merged['status'] == 'metadata_verified'
    assert s.valid_sfn_approval(merged)
