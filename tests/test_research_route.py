"""Research route (bibcheck/research_route.py): re-checking saved research approvals.

`crossref restore` re-validates every research-evidence approval in the snapshot from
the row alone (valid_research_approval). The fixtures are real and frozen (2026-10-01):
tests/fixtures/research_approvals/rows.jsonl.gz holds 14 rows of
verification/baseline.jsonl.gz as committed at f2a8581, one or more per kind of saved
evidence (plain quotes, quotes read in a browser or from a scan, a chapter's start page
only, and each notice class the route settles); entries.bib holds the same entries as
cdl.bib printed them; bodies/ holds validate.py's fetched bodies for the quotes of
Tulv74, YingEtal93 and Gomu53. No test reads the live cdl.bib, the baseline or .bibcheck/.

The tests of the code that built approvals from the research folders (load_evidence,
run_research_approve and the `research-approve` command) and their fixture,
tests/fixtures/research_route/, are in the archive repository ContextLab/CDL-bibliography-stacks.
"""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
from cdlbib import research_route as R  # noqa: E402
from cdlbib import verification as v  # noqa: E402

FIX = ROOT / 'tests/fixtures/research_approvals'
BODIES = FIX / 'bodies'
ROWS = [json.loads(line) for line in gzip.open(FIX / 'rows.jsonl.gz', 'rt', encoding='utf-8')]
BY_KEY = {r['key']: r for r in ROWS}
WITH_BODIES = ['Tulv74', 'YingEtal93', 'Gomu53']


def own(result):
    return [c for c in result['candidates'] if c.get('source') == R.SOURCE][0]


def body(url, root=BODIES):
    return root / (hashlib.sha256(url.encode()).hexdigest() + '.txt')


def quoted_urls(result):
    return sorted({e['url'] for f in own(result)['fields'].values() for e in f.get('evidence', [])
                   if e.get('found')})


@pytest.fixture
def no_body_cache(monkeypatch, tmp_path):
    # A fresh clone or CI: no .bibcheck/research-pilot/, so the recorded quote results count.
    monkeypatch.setattr(R, 'BODY_DIR', tmp_path / 'absent')


@pytest.fixture
def frozen_bodies(monkeypatch):
    monkeypatch.setattr(R, 'BODY_DIR', BODIES)


def test_validator_registered_and_cli_imports_route():
    assert R.valid_research_approval in v.APPROVAL_VALIDATORS
    from cdlbib import verification_cli
    assert verification_cli.research_route is R
    assert 'research-approve' not in [c.name for c in verification_cli.app.registered_commands]
    assert R.validator().__name__ == 'cdlbib.research_quotes' and R.postcheck().__name__ == 'cdlbib.research_forms'
    # the code that read the archived research folders is gone
    for name in ('load_evidence', 'run_research_approve', 'evidence_files', 'uncommitted_evidence',
                 'merge', 'reason_class', 'rename_walk', 'renames_when_committed'):
        assert not hasattr(R, name), name


def test_fixture_covers_every_kind_of_saved_evidence():
    flags = {f for r in ROWS for f in own(r).get('flags', [])}
    assert {'pages: browser_or_scan', 'identity: browser_or_scan', 'pages: pages_start_only',
            'notice: notice_content_only', 'notice: notice_unread', 'notice: notice_metadata_correction',
            'notice: notice_new_version', 'notice: notice_none', 'notice: notice_unrelated',
            'notice: notice_crossref_wins', 'notice: notice_is_the_cited_work'} <= flags
    assert any(r.get('notices_accounted') for r in ROWS) and any(not r.get('notices_accounted') for r in ROWS)
    assert any(own(r)['checked_fields'].get('doi') for r in ROWS)
    assert any(not own(r)['checked_fields'].get('doi') for r in ROWS)
    assert all(r['status'] == 'metadata_verified' and r['accepted_source'] == R.SOURCE for r in ROWS)


@pytest.mark.parametrize('key', sorted(BY_KEY))
def test_saved_approval_revalidates_without_a_body_cache(no_body_cache, key):
    result = deepcopy(BY_KEY[key])
    assert R.valid_research_approval(result)
    assert v.route_approval_valid(result)
    assert R.research_rejection_reason(result) is None
    # the saved candidate re-assesses to itself from its own record
    checked = R.recheck(own(result), R.SavedBodies(own(result)))
    assert checked['status'] == 'metadata_verified'
    assert checked['accepted_record_id'] == result['accepted_record_id'] == R.evidence_id(own(result))
    assert checked['candidates'][0] == own(result)


@pytest.mark.parametrize('key', WITH_BODIES)
def test_saved_approval_revalidates_against_the_saved_bodies(frozen_bodies, key):
    result = deepcopy(BY_KEY[key])
    for url in quoted_urls(result):
        assert body(url).exists(), url
    assert R.valid_research_approval(result)
    assert R.research_rejection_reason(result) is None


def test_empty_or_partial_body_cache_uses_the_recorded_results(monkeypatch, tmp_path):
    # 2026-09-30: an empty .bibcheck/research-pilot/ rejected every research approval. A
    # body the cache does not hold uses the recorded quote result.
    (tmp_path / 'empty').mkdir()
    monkeypatch.setattr(R, 'BODY_DIR', tmp_path / 'empty')
    for row in ROWS:
        assert R.valid_research_approval(deepcopy(row)), row['key']
    result = deepcopy(BY_KEY['Gomu53'])
    urls = [u for u in quoted_urls(result) if body(u).exists()]
    assert len(urls) >= 2
    shutil.copytree(BODIES, tmp_path / 'partial')
    body(urls[0], tmp_path / 'partial').unlink()
    monkeypatch.setattr(R, 'BODY_DIR', tmp_path / 'partial')
    assert R.valid_research_approval(result)
    # a changed body the cache holds fails, and the restore error names the URL and the cause
    other = body(urls[1], tmp_path / 'partial')
    other.write_text(other.read_text() + '\n')
    assert not R.valid_research_approval(result)
    why = v.approval_rejection_reason(result)
    assert urls[1] in why and 'holds a different body' in why, why


@pytest.mark.parametrize('key', ['Tulv74', 'HartWong79', 'DamaEtal96', 'RescWagn72', 'ShapPale70'])
def test_tampered_value_is_rejected(no_body_cache, key):
    result = BY_KEY[key]
    field = 'title'
    for mutate in (
            lambda r: own(r)['checked_fields'].update({field: own(r)['checked_fields'][field] + ' revised'}),
            lambda r: own(r)['fields'][field].update(value=own(r)['fields'][field]['value'] + ' revised'),
            lambda r: own(r)['checked_fields'].update(year='1899'),
            lambda r: own(r)['fields'].pop(field)):
        bad = deepcopy(result)
        mutate(bad)
        assert not R.valid_research_approval(bad), key
        assert R.research_rejection_reason(bad), key
        bad['accepted_record_id'] = R.evidence_id(own(bad))   # even with a recomputed id
        assert not R.valid_research_approval(bad), key
    assert R.valid_research_approval(deepcopy(result))


@pytest.mark.parametrize('key', ['Tulv74', 'YingEtal93', 'DamaEtal96'])
def test_tampered_quote_is_rejected(no_body_cache, key):
    result = BY_KEY[key]
    found = [(name, i) for name, f in own(result)['fields'].items()
             for i, e in enumerate(f.get('evidence', [])) if e.get('found')]
    assert found
    for name, i in found:
        bad = deepcopy(result)
        item = own(bad)['fields'][name]['evidence'][i]
        item['quote'] = 'a sentence no source printed for this work'
        assert not R.valid_research_approval(bad), (key, name)
        # a forger who also recomputes the evidence id is caught by the re-assessment
        bad['accepted_record_id'] = R.evidence_id(own(bad))
        assert not R.valid_research_approval(bad), (key, name)
        assert R.research_rejection_reason(bad).startswith(('re-assessing', 'the re-assessed')), (key, name)
        bad = deepcopy(result)
        own(bad)['fields'][name]['evidence'][i]['found'] = False
        assert not R.valid_research_approval(bad), (key, name)


def test_tampered_quote_is_rejected_against_a_saved_body(frozen_bodies):
    result = BY_KEY['Tulv74']
    name, i = next((n, i) for n, f in own(result)['fields'].items()
                   for i, e in enumerate(f.get('evidence', [])) if e.get('found'))
    bad = deepcopy(result)
    own(bad)['fields'][name]['evidence'][i]['quote'] = 'a sentence no source printed for this work'
    assert not R.valid_research_approval(bad)


def test_tampered_record_is_rejected(no_body_cache):
    result = BY_KEY['YingEtal93']
    for mutate in (lambda r: r.update(accepted_record_id='research:0'),
                   lambda r: r.update(accepted_source='crossref'),
                   lambda r: r.update(accepted_doi='10.1000/other'),
                   lambda r: r.update(external_evidence={'x': 1}),
                   lambda r: r['candidates'].append(deepcopy(own(r))),
                   lambda r: own(r).update(issues=['x']),
                   lambda r: own(r).update(category='needs_review'),
                   lambda r: own(r)['identity'].update(found=False, body_sha256=None)):
        bad = deepcopy(result)
        mutate(bad)
        assert not R.valid_research_approval(bad)
    assert R.valid_research_approval(deepcopy(result))


def test_minimal_requirements_still_refuse_tampering(no_body_cache, monkeypatch):
    # CI restores the baseline with requirements-verification.txt only: no pandas for the
    # post-check's normalisers. The saved record's self-consistency still decides.
    def missing():
        raise ImportError('No module named pandas')
    monkeypatch.setattr(R, 'postcheck', missing)
    result = BY_KEY['YingEtal93']
    assert R.valid_research_approval(deepcopy(result))
    for mutate in (lambda c: c['checked_fields'].update(year='1999'),
                   lambda c: c['fields'].pop('title'),
                   lambda c: c['fields']['title'].update(value='Another title'),
                   lambda c: [e.update(found=False) for e in c['fields']['title']['evidence']],
                   lambda c: c['identity'].update(found=False),
                   lambda c: c.update(issues=['x'])):
        bad = deepcopy(result)
        mutate(own(bad))
        assert not R.valid_research_approval(bad)


def test_a_retraction_on_the_cited_doi_is_rejected_whatever_is_declared(no_body_cache):
    result = BY_KEY['DamaEtal96']
    doi = own(result)['checked_fields']['doi'].lower()
    bad = deepcopy(result)
    record = next(c for c in bad['candidates'] if c.get('source') == 'crossref' and c.get('doi') == doi
                  and isinstance(c.get('record'), dict))
    record['record']['updated-by'] = [{'type': 'retraction', 'DOI': '10.1038/retraction-test'}]
    assert R.retraction_signals(bad['candidates'], doi)
    assert not R.valid_research_approval(bad)
    assert R.research_rejection_reason(bad)
    # the same retraction on another work's record (a rejected candidate) is not the cited work's
    other = deepcopy(result)
    record = next(c for c in other['candidates'] if c.get('source') == 'crossref' and c.get('doi') != doi
                  and isinstance(c.get('record'), dict))
    record['record']['updated-by'] = [{'type': 'retraction', 'DOI': '10.1038/retraction-test'}]
    assert not R.retraction_signals(other['candidates'], doi)


def test_a_notice_without_its_classification_is_rejected(no_body_cache):
    for key in ('DamaEtal96', 'TompDava17', 'BisbBurg14', 'Fred04'):
        bad = deepcopy(BY_KEY[key])
        own(bad).pop('notice', None)
        assert not R.valid_research_approval(bad), key


def test_notice_declaration_is_the_one_the_saved_records_give():
    for row in ROWS:
        if row.get('notices_accounted'):
            assert row['notices_accounted'] == R.notices_declaration(own(row), row['candidates']), row['key']


def test_restore_revalidates_the_rows_and_refuses_a_tampered_one(no_body_cache, tmp_path):
    header = {'schema': 2, 'policy': v.POLICY, 'created_at': '2026-10-01T00:00:00+00:00', 'entries': len(ROWS),
              'source_notices': [], 'source_author_suffixes': [], 'source_article_locators': [],
              'revocations': []}

    def write(rows, name):
        path = tmp_path / name
        with gzip.open(path, 'wt', encoding='utf-8') as stream:
            stream.write(json.dumps(header) + '\n')
            for row in rows:
                stream.write(json.dumps(row) + '\n')
        return path

    bib = FIX / 'entries.bib'
    cache = v.Cache(tmp_path / 'fresh.sqlite3')
    try:
        assert v.import_snapshot(bib, cache, write(ROWS, 'good.jsonl.gz')) == len(ROWS)
        results = v.current_results(bib, cache)
        assert {k: r['status'] for k, r in results.items()} == {k: 'metadata_verified' for k in BY_KEY}
    finally:
        cache.close()
    tampered = deepcopy(ROWS)
    own(tampered[0])['fields']['title']['evidence'][0]['quote'] = 'a sentence no source printed for this work'
    cache = v.Cache(tmp_path / 'fresh2.sqlite3')
    try:
        with pytest.raises(ValueError, match=tampered[0]['key']):
            v.import_snapshot(bib, cache, write(tampered, 'bad.jsonl.gz'))
    finally:
        cache.close()


def test_house_form_comparison():
    assert R.canon('author', 'G {van Rossum} and {\\L} Langa') == R.canon('author', 'G {van Rossum} and Ł Langa')
    assert R.canon('author', 'Colin Raffel') == R.canon('author', 'C Raffel')
    assert R.canon('author', 'C Raffel') != R.canon('author', 'C A Raffel')
    assert R.canon('pages', '347-76') == R.canon('pages', '347--376')
    assert R.canon('title', 'A — b') == R.canon('title', 'a---b')
    assert R.canon('doi', 'https://doi.org/10.1037/H0034650') == '10.1037/h0034650'
    assert R.canon('entrytype', 'conference') == 'inproceedings'
    assert R.canon('author', 'RNS System in Epilepsy Study Group') != R.canon('author', '{RNS System in Epilepsy Study Group}')
    assert R.canon('author', 'R {La Joie}', groups=R.braced_groups('R {La Joie}')) == R.canon('author', 'R La Joie')
    assert R.braced_groups('R {La Joie} and {Jupyter Development Team}') == {'jupyter development team'}


def test_partial_default_notes():
    for notes in ("RECONCILED: an official contents list confirms the start page",
                  "Pages 64--99 not set: the start page 64 is confirmed by the Google Books contents",
                  "Reconciled (partly-confirmed chapter pages default)",
                  "Left as HEAD (default: start page confirmed keeps the cited range)"):
        assert R.PARTIAL_PAGES.search(notes), notes
    for notes in ("the start page could not be confirmed", "the start page is not confirmed",
                  "pages removed: no source prints them"):
        assert not R.PARTIAL_PAGES.search(notes), notes
