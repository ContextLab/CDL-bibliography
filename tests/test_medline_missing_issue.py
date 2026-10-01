"""Keep a verified registry issue when MED only resolves the print year."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from cdlbib import verification as v
from cdlbib.auto_review import assess_epmc, reassess, run_auto_review

CASE = json.loads((Path(__file__).parent / 'fixtures/medline_missing_issue.json').read_text())


def assess(case):
    primary = case['primary']
    primary['evidence'], primary['issues'] = v.compare_record(case['entry']['fields'], primary['record'])
    secondary = case['secondary']
    return assess_epmc(case['entry']['fields'], primary, secondary['raw_record'],
                       secondary['retrieved_at'], secondary['request_url'])


def test_real_salzinger_print_issue_is_retained_without_inventing_med_metadata():
    case = deepcopy(CASE); result = assess(case)
    assert not result['issues']
    assert result['evidence']['year']['source_name'] == 'europepmc'
    assert result['evidence']['number']['source_name'] == 'crossref'
    assert result['evidence']['number']['source'] == ['1']
    assert not result['record']['issue']
    assert 'issue' not in result['raw_record']['journalInfo']


@pytest.mark.parametrize('field,value', [
    ('issue', '2'), ('issue', None), ('issue', ''), ('volume', '62'),
    ('yearOfPublication', 1960),
])
def test_present_or_conflicting_med_coordinates_are_not_erased(field, value):
    case = deepcopy(CASE); case['secondary']['raw_record']['journalInfo'][field] = value
    assert assess(case)['issues']


@pytest.mark.parametrize('field,value', [
    ('doi', '10.1234/other'), ('title', 'Another paper'), ('pageInfo', '95-105'),
    ('authorList', {'author': [{'firstName': 'Alice', 'lastName': 'Other'}]}),
    ('pubTypeList', {'pubType': ['Published Erratum']}), ('isRetracted', 'Y'),
    ('commentCorrectionList', {'commentCorrection': [{'type': 'Erratum in', 'source': 'MED', 'id': '999'}]}),
])
def test_identity_notice_and_version_guards(field, value):
    case = deepcopy(CASE); case['secondary']['raw_record'][field] = value
    assert assess(case)['issues']


@pytest.mark.parametrize('field,value', [('issue', '2'), ('issue', None),
    ('published-print', {'date-parts': [[2010]]}), ('title', ['Another title']),
    ('ISSN', ['9999-9999']), ('type', 'proceedings-article')])
def test_registry_must_independently_support_issue_and_identity(field, value):
    case = deepcopy(CASE); case['primary']['record'][field] = value
    assert assess(case)['issues']


def test_absent_secondary_field_cannot_resolve_other_blockers():
    case = deepcopy(CASE)
    case['entry']['fields']['publisher'] = 'Wrong publisher'
    assert assess(case)['issues']
    case = deepcopy(CASE)
    case['entry']['fields']['note'] = 'Unchecked additional metadata'
    assert assess(case)['issues']


def test_raw_source_rechecked_after_edit_rename_and_clean_restore(tmp_path):
    bib = tmp_path / 'source.bib'; bib.write_text(CASE['entry']['raw'])
    entry = v.load_entries(bib)['Salz59']
    cache = v.Cache(tmp_path / 'cache.sqlite3')
    try:
        cache.put(bib, entry, {'status': 'needs_review', 'issues': ['held'],
                              'candidates': [CASE['primary'], CASE['secondary']]})
        first = run_auto_review(bib, cache, tmp_path / 'report.jsonl')
        assert first['Salz59']['status'] == 'metadata_verified'
        count = cache.db.execute('select count(*) from reviews').fetchone()[0]
        assert run_auto_review(bib, cache, tmp_path / 'report.jsonl') == first
        assert cache.db.execute('select count(*) from reviews').fetchone()[0] == count
        snapshot = tmp_path / 'baseline.jsonl.gz'; v.export_snapshot(bib, cache, snapshot)
        fresh = v.Cache(tmp_path / 'fresh.sqlite3')
        try:
            assert v.import_snapshot(bib, fresh, snapshot) == 1
            assert v.current_results(bib, fresh) == first
        finally:
            fresh.close()
        bib.write_text(CASE['entry']['raw'].replace('Salz59', 'Renamed59', 1))
        renamed = v.load_entries(bib)['Renamed59']
        assert renamed['fingerprint'] == entry['fingerprint']
        assert cache.get(bib, renamed)['status'] == 'metadata_verified'
        edited = deepcopy(entry); edited['fields']['number'] = '2'
        assert reassess(edited, first['Salz59'])['status'] == 'needs_review'
        tampered = deepcopy(first['Salz59'])
        next(c for c in tampered['candidates'] if c['source']=='europepmc')['raw_record']['journalInfo']['issue'] = '2'
        assert reassess(entry, tampered)['status'] == 'needs_review'
    finally:
        cache.close()
