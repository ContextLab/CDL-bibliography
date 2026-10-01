"""PMC fallback behavior across edits, failures, selection, and cache restore."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bibcheck'))
import pmc_metadata as pmc
from verification import Cache, PoliteClient, ProviderError, current_results, load_entries, export_snapshot, import_snapshot
from verification_cli import DeferredClient
from test_auto_review import candidate, secondary
from test_pmc_metadata import Response, Session
import test_auto_review

sample = test_auto_review.sample


def setup(tmp_path, sample, response=None):
    fields, record, raw = sample
    raw.update(id='456', pmcid='PMC123', isOpenAccess='N')
    # Registry and MED cannot settle this date without publisher front matter.
    record['published-print'] = {'date-parts': [[2019]]}
    bib = tmp_path / 'sample.bib'
    text = '@article{A,\n' + ',\n'.join(k + '={' + v + '}' for k, v in fields.items() if k not in {'ID', 'ENTRYTYPE'}) + '}\n'
    bib.write_text(text)
    cache = Cache(tmp_path / 'cache.sqlite3')
    previous = {'status': 'needs_review', 'candidates': [candidate(fields, record), secondary(fields, record, raw)],
                'attempts': [], 'discovery_review': {'checked': True}}
    cache.put(bib, load_entries(bib)['A'], previous)
    session = Session(response or Response())
    client = PoliteClient(cache, 'test@example.org', session=session, sleep=lambda _: None)
    return bib, cache, client, previous, text


def run(bib, cache, client, **kwargs):
    return pmc.run_pmc_metadata_review(bib, cache, client, bib.parent / 'report.jsonl', **kwargs)


def test_non_oa_metadata_verifies_once_and_key_rename_is_free(tmp_path, sample):
    bib, cache, client, previous, text = setup(tmp_path, sample)
    first = run(bib, cache, client)
    assert first['A']['status'] == 'metadata_verified' and client.requests == 1
    assert first['A']['discovery_review'] == previous['discovery_review']
    writes = cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert run(bib, cache, client) == first
    bib.write_text(text.replace('{A,', '{Renamed,'))
    assert run(bib, cache, client)['Renamed'] == dict(first['A'], key='Renamed')
    assert client.requests == 1 and cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0] == writes
    cache.close()


def test_changed_fields_are_reassessed_using_cached_document(tmp_path, sample):
    bib, cache, client, previous, text = setup(tmp_path, sample)
    assert run(bib, cache, client)['A']['status'] == 'metadata_verified'
    bib.write_text(text.replace('123--129', '123--130'))
    entry = load_entries(bib)['A']
    assert current_results(bib, cache)['A']['status'] == 'pending'
    # Mimic normal registry/secondary stages for the new fingerprint.
    from auto_review import reassess
    cache.put(bib, entry, reassess(entry, previous))
    result = run(bib, cache, client)['A']
    assert result['status'] == 'needs_review'
    assert any('pages:' in issue for c in result['candidates'] if c['source'] == 'pmc-jats' for issue in c['issues'])
    assert client.requests == 1
    cache.close()


@pytest.mark.parametrize('status', [404, 429])
def test_negative_and_failure_checkpoints(tmp_path, sample, status):
    bib, cache, client, _, _ = setup(tmp_path, sample, Response(status, 'unavailable'))
    if status == 429:
        with pytest.raises(ProviderError):
            run(bib, cache, client)
        assert not cache.get(bib, load_entries(bib)['A']).get('auto_review', {}).get('pmc_metadata_checked')
        assert cache.response('pmc-front-v1:PMC123', 86400) is None
    else:
        first = run(bib, cache, client)
        assert first['A']['status'] == 'needs_review'
        assert run(bib, cache, client) == first
    assert client.requests == 1
    assert (tmp_path / 'report.jsonl').exists()
    cache.close()


def test_empty_selection_and_approved_entries_do_not_create_client(tmp_path, sample):
    bib, cache, _, _, _ = setup(tmp_path, sample)
    client = DeferredClient(cache, None, 1.0, False)
    run(bib, cache, client, keys=set())
    assert client.client is None
    entry = load_entries(bib)['A']
    cache.put(bib, entry, {'status': 'metadata_verified', 'candidates': []})
    run(bib, cache, client)
    assert client.client is None
    cache.close()


def test_source_checkpoint_survives_clean_snapshot_restore(tmp_path, sample):
    bib, cache, client, _, _ = setup(tmp_path, sample, Response(404, 'missing'))
    first = run(bib, cache, client)
    export_snapshot(bib, cache, tmp_path / 'snapshot.gz')
    cache.close()
    fresh = Cache(tmp_path / 'fresh.sqlite3')
    import_snapshot(bib, fresh, tmp_path / 'snapshot.gz')
    deferred = DeferredClient(fresh, None, 1.0, False)
    assert run(bib, fresh, deferred) == first
    assert deferred.client is None
    fresh.close()


def test_conflicting_pmc_to_pubmed_mapping_cannot_pick_first(tmp_path, sample):
    bib, cache, client, previous, _ = setup(tmp_path, sample)
    extra = deepcopy(previous['candidates'][1])
    extra['raw_record']['id'] = '789'
    previous['candidates'].append(extra)
    cache.put(bib, load_entries(bib)['A'], previous)
    assert run(bib, cache, client)['A']['status'] == 'needs_review'
    assert client.requests == 0
    cache.close()


def test_bulk_hours_checked_before_network_but_cache_hits_are_allowed(tmp_path, sample, monkeypatch):
    bib, cache, client, _, text = setup(tmp_path, sample)
    # Distinct raw entry content prevents fingerprint reuse across the batch.
    bib.write_text(''.join(text.replace('{A,', '{A' + str(i) + ',').replace('title=', 'title' + ' ' * i + '=') for i in range(101)))
    entry = load_entries(bib)['A0']
    # Original A and A0 share content; all remaining entries are pending.
    def forbidden():
        raise ProviderError('off-peak required')
    monkeypatch.setattr(pmc, 'check_bulk_hours', forbidden)
    with pytest.raises(ProviderError, match='off-peak'):
        run(bib, cache, client, limit=1)
    assert client.requests == 0
    pmc.fetch_front(cache, client, 'PMC123')
    assert run(bib, cache, client, limit=1)['A0']['status'] == 'metadata_verified'
    assert client.requests == 1
    cache.close()


def test_deferred_client_applies_and_restores_pmc_pacing(tmp_path, monkeypatch):
    cache = Cache(tmp_path / 'cache.sqlite3')
    import verification_cli
    observed = []
    class ObservedSession(Session):
        def get(self, *args, **kwargs):
            observed.append(deferred.client.interval)
            return super().get(*args, **kwargs)
    def factory(*args, **kwargs):
        return PoliteClient(*args, **kwargs, session=ObservedSession(Response()), sleep=lambda _: None)
    monkeypatch.setattr(verification_cli, 'PoliteClient', factory)
    deferred = DeferredClient(cache, 'test@example.org', 1.0, False)
    pmc.fetch_front(cache, deferred, 'PMC123')
    assert observed == [3.1]
    assert deferred.interval == deferred.client.interval == 1.0
    cache.close()


@pytest.mark.parametrize('candidate', [{'source': 'research', 'title': 'No DOI'}, {'source': 'crossref', 'doi': ''}, {'source': 'europepmc', 'raw_record': None}, {'source': 'europepmc', 'doi': 'invalid', 'raw_record': {}}, {'source': 'europepmc', 'doi': '10.1234/a', 'raw_record': {'source':'MED','doi':'10.1234/a','id':'456','pmcid':None}}])
def test_unidentified_candidates_are_not_pmc_lookup_targets(candidate):
    assert pmc.metadata_targets({'candidates': [candidate]}) == {}
