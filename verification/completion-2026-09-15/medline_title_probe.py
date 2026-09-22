"""Collect title-indexed MED records missed by DOI-only lookup; never approve."""
import importlib.util
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bibcheck'))
from verification import Cache, PoliteClient, load_entries
from auto_review import EPMC_URL

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('earlier', HERE.parent / 'resolution-2026-09-15/run.py')
earlier = importlib.util.module_from_spec(spec); spec.loader.exec_module(earlier)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnose', action='store_true')
    args = parser.parse_args()
    entries = load_entries(ROOT / 'cdl.bib')
    cache = Cache(ROOT / '.bibcheck/completion-2026-09-15/medline-titles.sqlite3')
    try:
        main_cache = Cache(ROOT / '.bibcheck/verification.sqlite3')
        try:
            contact = earlier.client_for(main_cache).mailto
        finally:
            main_cache.close()
        client = PoliteClient(cache, contact)
        if args.diagnose:
            title = entries['FritCarl80']['fields']['title']
            response = client.source_request(EPMC_URL, params={'query': 'TITLE:"' + title + '" AND SRC:MED AND PUB_YEAR:1980',
                'format': 'json', 'resultType': 'core', 'pageSize': 100}, timeout=(10,40))
            body = response.json()
            (HERE / 'medline-title-diagnostic.json').write_text(json.dumps(body, indent=2)+'\n')
            print(json.dumps({'http_status': response.status_code, 'keys': list(body),
                              'hitCount': body.get('hitCount'), 'resultList': body.get('resultList'),
                              'error': body.get('errMsg')}), flush=True)
            return
        results = []
        for key in ('Box76', 'Salz59', 'Bous53', 'FritCarl80', 'PaolEtal10', 'BiswEtal95'):
            title = entries[key]['fields']['title'].replace('{', '').replace('}', '')
            assert '"' not in title and '\\' not in title
            year = entries[key]['fields']['year']
            assert year.isdigit() and len(year) == 4
            response = client.get(EPMC_URL, {'query': 'TITLE:"' + title + '" AND SRC:MED AND PUB_YEAR:' + year,
                                          'format': 'json', 'resultType': 'core', 'pageSize': 100})
            assert response['http_status'] == 200
            body = response['body']; records = body.get('resultList', {}).get('result')
            assert isinstance(records, list) and body['hitCount'] == len(records)
            results.append({'key': key, 'fingerprint': entries[key]['fingerprint'], 'response': response})
            (HERE / 'medline-title-probe.json').write_text(json.dumps(results, indent=2) + '\n')
            print(json.dumps({'key': key, 'records': [{'id': r['id'], 'doi': r.get('doi'), 'title': r.get('title'),
                                                      'year': r.get('pubYear')} for r in records],
                              'requests': client.requests}), flush=True)
    finally:
        cache.close()


if __name__ == '__main__':
    main()
