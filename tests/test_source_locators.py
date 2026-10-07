"""A sparse registry cannot erase known, corroborated article coordinates."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

import pytest

from cdlbib import verification as v
from cdlbib.auto_review import reassess, select_result
from cdlbib.source_locators import locator_dois, source_coordinates

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/article_locator.json').read_text())


def setup(tmp_path):
    f = deepcopy(FIXTURE)
    bib = tmp_path / 'source.bib'; bib.write_text(f['entry']['raw'])
    entry = v.load_entries(bib)['NewmEtal12']
    primary = f['primary']
    primary['evidence'], primary['issues'] = v.compare_record(entry['fields'], primary['record'])
    assert not primary['issues']  # This registry deposit omits the article number.
    clean = select_result(entry['fields'], [primary], [])
    assert clean['status'] == 'metadata_verified'
    return bib, entry, primary, f['publisher'], clean


def test_actual_publisher_and_medline_locator_overrides_sparse_registry(tmp_path):
    _, entry, primary, publisher, clean = setup(tmp_path)
    assert source_coordinates(publisher) == ('10.3389/fnbeh.2012.00024', '6', '24')
    # Decisions are rebuilt from raw sources, not old match flags or mapped data.
    publisher['evidence'] = {}; publisher['issues'] = []; publisher['record'] = {}
    previous = dict(clean, candidates=[primary, publisher])
    assert reassess(entry, previous)['status'] == 'needs_review'
    for pages in ('24', '24--24'):
        corrected = dict(entry, fields=dict(entry['fields'], pages=pages))
        assert reassess(corrected, previous)['status'] == 'metadata_verified'
    for changes in ({'pages':'25'}, {'volume':'7','pages':'24'}):
        assert reassess(dict(entry,fields=dict(entry['fields'],**changes)),previous)['status']=='needs_review'


@pytest.mark.parametrize('change', ['doi','medline-doi','page','volume','issn','manuscript','related','references','type','malformed'])
def test_only_identified_final_article_coordinates_are_retained(tmp_path, change):
    _, _, _, p, _ = setup(tmp_path)
    if change=='doi': p['doi']='10.1234/other'
    elif change=='medline-doi': p['medline_record']['doi']='10.1234/other'
    elif change=='page': p['medline_record']['pageInfo']='999'
    elif change=='volume': p['medline_record']['journalInfo']['volume']='999'
    elif change=='issn': p['medline_record']['journalInfo']['journal']={'title':'Other','issn':'0000-0000'}
    elif change=='manuscript': p['raw_xml']=p['raw_xml'].replace('<article-meta>', '<article-meta><article-id pub-id-type="manuscript-id">NIHMS1</article-id>')
    elif change=='related': p['raw_xml']=p['raw_xml'].replace('<article-meta>', '<article-meta><related-article/>')
    elif change=='references': p['raw_xml']=p['raw_xml'].replace('<front>','<back>').replace('</front>','</back>')
    elif change=='type': p['raw_xml']=p['raw_xml'].replace('article-type="review-article"','article-type="correction"')
    else: p['raw_xml']='<broken'
    assert not locator_dois([p])


def test_edit_rename_restore_and_incremental_history_keep_negative_evidence(tmp_path):
    bib, entry, primary, publisher, clean = setup(tmp_path)
    cache=v.Cache(tmp_path/'cache.sqlite3')
    # Pre-fix result whose audit already carried the missing article number.
    old=dict(clean,candidates=[primary,publisher],policy=v.POLICY,key=entry['key'],fingerprint=entry['fingerprint'],checked_at='old')
    cache.store(bib,entry,old)
    cache.index_notices()
    assert cache.get(bib,entry)['status']=='needs_review'
    rows=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    cache.index_notices();cache.get(bib,entry)
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==rows
    retained=json.loads(cache.db.execute('SELECT candidate FROM source_article_locators').fetchone()[0])
    assert retained['evidence']=={} and 'record' not in retained
    snapshot=tmp_path/'snapshot.gz';v.export_snapshot(bib,cache,snapshot)
    bib.write_text(bib.read_text().replace('NewmEtal12,','Renamed,').replace('Year =','Year  ='))
    edited=v.load_entries(bib)['Renamed'];assert edited['fingerprint']!=entry['fingerprint']
    assert cache.put(bib,edited,clean)['status']=='needs_review'
    fresh=v.Cache(tmp_path/'fresh.sqlite3')
    assert v.import_snapshot(bib,fresh,snapshot)==0
    assert fresh.put(bib,edited,clean)['status']=='needs_review'
    rows=fresh.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert fresh.get(bib,edited)['status']=='needs_review'
    assert fresh.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==rows
    cache.close();fresh.close()


def test_invalid_locator_snapshot_rejected_before_writes(tmp_path):
    bib, entry, primary, publisher, clean=setup(tmp_path)
    cache=v.Cache(tmp_path/'cache.sqlite3')
    cache.put(bib,entry,dict(clean,candidates=[primary,publisher]))
    snapshot=tmp_path/'snapshot.gz';v.export_snapshot(bib,cache,snapshot)
    with gzip.open(snapshot,'rt')as f:rows=list(map(json.loads,f))
    rows[0]['source_article_locators'].append({'source':'invented'})
    with gzip.open(snapshot,'wt')as f:f.write('\n'.join(json.dumps(r)for r in rows)+'\n')
    fresh=v.Cache(tmp_path/'fresh.sqlite3')
    with pytest.raises(ValueError,match='locator'):v.import_snapshot(bib,fresh,snapshot)
    assert fresh.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==0
    assert fresh.db.execute('SELECT count(*) FROM source_article_locators').fetchone()[0]==0
    cache.close();fresh.close()


def test_unrelated_source_does_not_rewrite_existing_approval(tmp_path):
    bib, entry, primary, publisher, clean=setup(tmp_path)
    cache=v.Cache(tmp_path/'cache.sqlite3')
    primary['doi']=primary['record']['DOI']='10.1234/unrelated'
    clean=select_result(entry['fields'],[primary],[])
    original=cache.put(bib,entry,clean)
    cache.remember_notices([publisher])
    rows=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert cache.get(bib,entry)==original
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==rows
    cache.close()


def test_later_matching_coordinates_do_not_add_positive_evidence_or_recheck(tmp_path):
    bib, _, primary, publisher, _=setup(tmp_path)
    bib.write_text(bib.read_text()[:-1]+',\nPages = {24}}')
    entry=v.load_entries(bib)['NewmEtal12']
    primary['record']['page']='24'
    primary['evidence'],primary['issues']=v.compare_record(entry['fields'],primary['record'])
    assert not primary['issues']
    cache=v.Cache(tmp_path/'cache.sqlite3')
    original=cache.put(bib,entry,select_result(entry['fields'],[primary],[]))
    cache.remember_notices([publisher])
    rows=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert cache.get(bib,entry)==original
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==rows
    cache.close()
