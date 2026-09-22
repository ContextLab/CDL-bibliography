"""Collect and apply the frozen, assistant-inspected book-field corrections.

Documentary source checks are recorded in bookfields-proposals.json and the
source audit. The production verifier independently checks the complete edited
entry against newly queried (or query-identical cached) catalogue evidence.
"""
from collections import Counter
import argparse
import gzip
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bibcheck'))
from catalogue_discovery import fetch_search, search_query
from catalogue_review import assess_catalogue, run_catalogue_review
from correction_proposals import replace_field
from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries, run_lock, run_verification
from pagination import earlier
from reassess import export_queue

HERE = Path(__file__).parent
WORK = ROOT / '.bibcheck' / HERE.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['collect', 'apply'])
    parser.add_argument('--batch', default='bookfields')
    args = parser.parse_args(); action = args.action; batch = args.batch
    if not batch.isalnum():
        parser.error('Use an alphanumeric batch')
    proposals = json.loads((HERE / f'{batch}-proposals.json').read_text())
    entries = load_entries(ROOT / 'cdl.bib')
    keys = {p['key'] for p in proposals}
    assert len(keys) == len(proposals)
    sources_path = HERE / f'{batch}-sources.json'
    if action == 'collect':
        cache = Cache(WORK / 'catalogue.sqlite3')
        main_cache = Cache(ROOT / '.bibcheck/verification.sqlite3')
        try:
            configured = earlier.client_for(main_cache)
            from verification import PoliteClient
            client = PoliteClient(cache, configured.mailto, interval=3.1)
            results = []
            for p in proposals:
                entry = entries[p['key']]
                assert entry['fingerprint'] == p['fingerprint']
                fields = dict(entry['fields'], **{k: c['after'] for k, c in p['changes'].items()})
                response = fetch_search(cache, client, fields, include_year=p.get('year_filtered', False))
                result = assess_catalogue(fields, response)
                results.append(dict(key=p['key'], source=response, assessment=result))
                sources_path.write_text(json.dumps(results, indent=2) + '\n')
                print(p['key'], result['status'], result.get('accepted_record_id'), flush=True)
                assert result['status'] == 'metadata_verified', p['key']
            print(json.dumps({'entries':len(results),'requests':client.requests}), flush=True)
        finally:
            cache.close(); main_cache.close()
        return
    sources = {r['key']:r for r in json.loads(sources_path.read_text())}
    assert sources.keys() == keys
    cache = Cache(ROOT / '.bibcheck/verification.sqlite3')
    try:
        with run_lock(cache):
            before = current_results(ROOT / 'cdl.bib', cache, entries)
            backup = WORK / f'before-{batch}.bib'
            if not backup.exists():
                text = (ROOT / 'cdl.bib').read_text(); modified = text
                for p in proposals:
                    key = p['key']; entry = entries[key]
                    assert before[key]['status'] == 'needs_review' and not before[key].get('external_evidence')
                    modified = replace_field(modified, entry, p)
                staging = WORK / f'{batch}-staged.bib'; staging.write_text(modified)
                staged = load_entries(staging)
                assert staged.keys() == entries.keys()
                for key, entry in entries.items():
                    if key not in keys:
                        assert staged[key] == entry
                for p in proposals:
                    key = p['key']; entry = staged[key]
                    assert entry['fingerprint'] != entries[key]['fingerprint']
                    assert entry['fields'] == dict(entries[key]['fields'], **{f:c['after'] for f,c in p['changes'].items()})
                    checked = assess_catalogue(entry['fields'], sources[key]['source'])
                    assert checked == sources[key]['assessment'] and checked['status'] == 'metadata_verified'
                # Exact key exceptions preserve manuscript references after the
                # corrected year and complete author list change key generation.
                override_path = ROOT / 'bibcheck/key_overrides.json'
                original_overrides = override_path.read_text()
                overrides = json.loads(original_overrides)
                if batch == 'bookfields':
                    overrides.update({'Rasm06':'RasmWill06', 'ThruEtal06':'ThruEtal05'})
                import helpers
                helpers.key_overrides = overrides
                errors, _ = helpers.check_bib(staging, verbose=False)
                assert not errors, errors
                export_snapshot(ROOT / 'cdl.bib', cache, WORK / f'before-{batch}.jsonl.gz')
                (WORK / f'before-{batch}-key-overrides.json').write_text(original_overrides)
                backup.write_text(text)
                override_path.write_text(json.dumps(overrides, indent=2) + '\n')
                (ROOT / 'cdl.bib').write_text(modified)
                print(f'Applied {len(keys)} inspected {batch} corrections; all keys preserved', flush=True)
            else:
                for p in proposals:
                    assert all(entries[p['key']]['fields'][f] == c['after'] for f,c in p['changes'].items())
                with gzip.open(WORK / f'before-{batch}.jsonl.gz', 'rt') as f:
                    before = {r['key']:r for r in map(json.loads, f) if 'key' in r}
            for p in proposals:
                fields = dict(entries[p['key']]['fields'], **{f:c['after'] for f,c in p['changes'].items()})
                response = sources[p['key']]['source']
                assert response['query'] == search_query(fields, include_year=p.get('year_filtered', False))
                cache.save_response('loc-sru-v1:10:'+response['query'], response)
        client = earlier.client_for(cache); stages=[]
        for cycle in ('run','repeat'):
            start=time.monotonic(); calls=client.requests
            count=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
            report=WORK/f'{batch}-report.jsonl'
            run_verification(ROOT/'cdl.bib',cache,client,report,keys=keys)
            after=run_catalogue_review(ROOT/'cdl.bib',cache,client,report,keys=keys)
            assert all(after[k]==r for k,r in before.items() if r['status'] in ACCEPTED)
            stage={'cycle':cycle,'seconds':round(time.monotonic()-start,2),'network_requests':client.requests-calls,
                   'review_writes':cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]-count,
                   'statuses':dict(Counter(r['status']for r in after.values()))}
            print(json.dumps(stage),flush=True)
            if cycle=='repeat':assert after==first and stage['network_requests']==stage['review_writes']==0
            first=after;stages.append(stage)
            (HERE/f'{batch}-results.json').write_text(json.dumps({'stages':stages,
                'entries':{k:{'status':after[k]['status'],'fingerprint':after[k]['fingerprint']}for k in sorted(keys)}},indent=2)+'\n')
        assert all(after[k]['status']=='metadata_verified'for k in keys)
        export_snapshot(ROOT/'cdl.bib',cache,ROOT/'verification/baseline.jsonl.gz')
        export_queue(load_entries(ROOT/'cdl.bib'),after)
    finally:cache.close()


if __name__ == '__main__':main()
