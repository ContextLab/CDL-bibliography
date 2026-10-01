"""Catalogue transport must not turn errors or partial results into evidence."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bibcheck"))
from catalogue_discovery import fetch_search, parse_search, search_query
from verification import Cache, ProviderError

FIXTURE = json.loads((Path(__file__).parent / "fixtures/catalogue_search.json").read_text())


def test_real_catalogue_response_and_punctuation_safe_query():
    result = parse_search(FIXTURE['xml'], FIXTURE['query'])
    assert result['total_records'] == 1 and not result['truncated']
    assert '2234092' in result['records'][0]
    assert search_query({'title': 'Language, memory and thought', 'author': 'J R Anderson'}) == 'dc.title="language memory and thought" and dc.author="anderson"'


def test_year_filter_is_explicit_and_keeps_the_ordinary_query_unchanged():
    fields = {'title': 'Language memory and thought', 'author': 'J R Anderson', 'year': '1976'}
    assert search_query(fields, include_year=True) == search_query(fields) + ' and (dc.date="1976" or dc.date="c1976")'
    for year in ('', '1976?', '1976–1977', '[1976]', '1976" or dc.title="x'):
        with pytest.raises(ValueError, match='explicit four-digit year'):
            search_query(dict(fields, year=year), include_year=True)


@pytest.mark.parametrize('change', ['html', 'query', 'schema', 'position', 'count', 'identity', 'entities', 'diagnostic'])
def test_untrusted_envelopes_are_rejected(change):
    xml = FIXTURE['xml']
    if change == 'html':
        xml = '<html><body>No Connections Available</body></html>'
    elif change == 'query':
        xml = xml.replace(FIXTURE['query'], 'other')
    elif change == 'schema':
        xml = xml.replace('<zs:recordSchema>marcxml', '<zs:recordSchema>dc')
    elif change == 'position':
        xml = xml.replace('<zs:recordPosition>1', '<zs:recordPosition>2')
    elif change == 'count':
        xml = xml.replace('<zs:numberOfRecords>1', '<zs:numberOfRecords>2')
    elif change == 'identity':
        xml = xml.replace('<controlfield tag="001">2234092</controlfield>', '')
    elif change == 'entities':
        xml = xml.replace('<?xml version="1.0"?>', '<!DOCTYPE x [<!ENTITY y "z">]>')
    else:
        xml = xml.replace('</zs:searchRetrieveResponse>', '<zs:diagnostics/></zs:searchRetrieveResponse>')
    with pytest.raises(ValueError):
        parse_search(xml, FIXTURE['query'])


def test_truncation_is_retained_and_zero_is_valid():
    xml = FIXTURE['xml'].replace('<zs:numberOfRecords>1', '<zs:numberOfRecords>20')
    assert parse_search(xml, FIXTURE['query'], limit=1)['truncated']
    start, rest = FIXTURE['xml'].split('<zs:records>', 1)
    _, end = rest.split('</zs:records>', 1)
    empty = (start + '<zs:records/>' + end).replace('<zs:numberOfRecords>1', '<zs:numberOfRecords>0')
    assert parse_search(empty, FIXTURE['query']) == {'total_records': 0, 'truncated': False, 'records': []}


@pytest.mark.parametrize('status,body', [(429, ''), (503, ''), (200, '<html>Unavailable</html>'), (200, 'x' * 2_000_001)])
def test_failed_requests_are_not_cached_and_pacing_is_restored(tmp_path, status, body):
    cache = Cache(tmp_path / 'cache.sqlite3')
    response = SimpleNamespace(status_code=status, headers={'Retry-After': '60'}, url='https://lx2.loc.gov/sru/lcdb',
                               iter_content=lambda _: [body.encode()], close=lambda: None)
    client = SimpleNamespace(refresh=False, interval=1.0)
    def request(*args, **kwargs):
        assert client.interval == 3.1
        assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
        return response
    client.source_request = request
    with pytest.raises(ProviderError):
        fetch_search(cache, client, {'title': 'Test', 'author': 'A Writer'})
    assert cache.db.execute('SELECT count(*) FROM responses').fetchone()[0] == 0
    assert client.interval == 1.0
    cache.close()


def test_success_is_cached_and_corrupt_cache_is_rejected(tmp_path):
    cache = Cache(tmp_path / 'cache.sqlite3')
    fields = {'title': 'Language memory and thought', 'author': 'J R Anderson'}
    query = search_query(fields)
    xml = FIXTURE['xml'].replace(FIXTURE['query'], query)
    calls = []
    response = SimpleNamespace(status_code=200, headers={}, url='https://lx2.loc.gov/sru/lcdb',
                               iter_content=lambda _: [xml.encode()], close=lambda: None)
    client = SimpleNamespace(refresh=False, interval=1.0, source_request=lambda *a, **kw: calls.append(a) or response)
    first = fetch_search(cache, client, fields)
    assert fetch_search(cache, client, fields) == first and len(calls) == 1
    first['document_sha256'] = '0' * 64
    cache.save_response('loc-sru-v1:10:' + query, first)
    with pytest.raises(ProviderError, match='hash differs'):
        fetch_search(cache, client, fields)
    cache.close()
