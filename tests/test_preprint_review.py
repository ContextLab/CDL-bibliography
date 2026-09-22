"""Real repository evidence, adverse metadata, notice persistence and cache reuse."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bibcheck'))
import preprint_review as p
import verification as v
from auto_review import POLICY, RESOLVER_VERSION, reassess, secondary_notice_flags
from verification_cli import DeferredClient

DATA = json.loads((Path(__file__).parent/'fixtures/biorxiv_preprints.json').read_text())


def source():
    return deepcopy(DATA['LeeEtal19'])


def assess(case):
    return p.assess_preprint(case['entry']['fields'], case['api'], case['html'], case['primary'])


def body_edit(source, action):
    data = json.loads(source['body']); action(data)
    source['body'] = json.dumps(data)
    source['document_sha256'] = hashlib.sha256(source['body'].encode()).hexdigest()


def html_edit(source, old, new):
    assert old in source['body']
    source['body'] = source['body'].replace(old, new)
    source['document_sha256'] = hashlib.sha256(source['body'].encode()).hexdigest()


def test_actual_preprint_matches_repository_version_not_later_journal():
    c = source(); result = assess(c)
    assert result['status'] == 'metadata_verified' and result['accepted_version'] == 1
    assert result['accepted_doi'] == '10.1101/615203'
    assert p.valid_preprint_approval(result)
    assert reassess(c['entry'], result)['status'] == 'metadata_verified'
    # HTML has a synthetic Jan 1 publication date; the actual repository
    # version date, rather than that placeholder, is the checked date.
    assert result['candidates'][0]['evidence']['year']['source'] == '2019-04-22'


def test_actual_uppercase_linked_doi_matches_without_changing_cited_version():
    c = deepcopy(DATA['SilvEtal19'])
    result = assess(c)
    assert result['status'] == 'metadata_verified'
    assert result['accepted_doi'] == '10.1101/511782'
    assert p.valid_preprint_approval(result)
    body_edit(c['api'], lambda d: d['collection'][0].update(published='10.1523/JNEUROSCI.9999-19.2019'))
    assert assess(c)['status'] == 'needs_review'


def test_case_variant_self_relation_is_not_a_journal_link():
    c = source()
    doi = c['primary']['DOI']
    c['primary']['relation'] = {'is-preprint-of': [{'id': doi.upper(), 'id-type': 'doi'}]}
    body_edit(c['api'], lambda d: d['collection'][0].update(published=doi))
    assert assess(c)['status'] == 'needs_review'


@pytest.mark.parametrize('change', [
    {'author': 'J Lee and J Briguglio and S Romani and A K Lee'},
    {'author': 'J S Lee and S Romani and J Briguglio and A K Lee'},
    {'author': 'J S Lee and J Briguglio and S Romani'},
    {'year': '2020'}, {'journal': 'Cell'}, {'volume': '10.1101/999999'},
    {'doi': '10.1016/j.cell.2020.09.024'}, {'number': '1'}, {'address': 'USA'},
    {'title': 'Statistical structure of the hippocampal code'}, {'pages': '1--31'},
    {'volume': '10.1101/615203v2'}, {'ENTRYTYPE': 'misc'},
])
def test_every_bibliographic_field_and_version_remains_binding(change):
    c = source(); c['entry']['fields'].update(change)
    assert assess(c)['status'] == 'needs_review'


@pytest.mark.parametrize('change', ['url','hash','doi','version','date','missing-version','withdrawn','server','author-order','title','status','malformed'])
def test_bad_history_cannot_supply_an_approval(change):
    c = source()
    if change == 'url': c['api']['url'] = 'https://example.com/evidence'
    elif change == 'hash': c['api']['document_sha256'] = '0'*64
    elif change == 'malformed': c['api']['body'] = '<html>Unavailable</html>'
    else:
        def edit(d):
            r = d['collection'][0]
            if change == 'doi': r['doi'] = '10.1101/999999'
            elif change == 'version': r['version'] = '2'
            elif change == 'date': r['date'] = '2019-02-31'
            elif change == 'missing-version': d['collection'] = []
            elif change == 'withdrawn': r['type'] = 'withdrawn'
            elif change == 'server': r['server'] = 'medRxiv'
            elif change == 'author-order': r['authors'] = 'Briguglio, J.; Lee, J. S.; Romani, S.; Lee, A. K.'
            elif change == 'title': r['title'] += ' revised'
            else: d['messages'][0]['status'] = 'error'
        body_edit(c['api'], edit)
    assert assess(c)['status'] == 'needs_review'


@pytest.mark.parametrize('change', ['doi','id','version-url','date','author','title','journal','section','publisher-conflict','hash'])
def test_version_page_is_bound_by_head_metadata(change):
    c = source()
    if change == 'hash': c['html']['document_sha256'] = '0'*64
    elif change == 'publisher-conflict': c['entry']['fields']['publisher'] = 'Other Press'
    else:
        old,new = {
            'doi': ('name="citation_doi" content="10.1101/615203"', 'name="citation_doi" content="10.1101/999999"'),
            'id': ('name="citation_id" content="615203v1"','name="citation_id" content="615203v2"'),
            'version-url': ('https://www.biorxiv.org/content/10.1101/615203v1"','https://www.biorxiv.org/content/10.1101/615203v2"'),
            'date': ('name="citation_date" content="2019-04-22"','name="citation_date" content="2019-04-23"'),
            'author': ('name="citation_author" content="John Briguglio"','name="citation_author" content="James Briguglio"'),
            'title': ('name="citation_title" content="The statistical', 'name="citation_title" content="A statistical'),
            'journal': ('name="citation_journal_title" content="bioRxiv"','name="citation_journal_title" content="Cell"'),
            'section': ('name="citation_section" content="New Results"','name="citation_section" content="Withdrawn"'),
        }[change]
        html_edit(c['html'], old, new)
    assert assess(c)['status'] == 'needs_review'


@pytest.mark.parametrize('change', ['journal-type','missing-subtype','author','notice','first-date','relationship'])
def test_registry_must_correspond_to_this_preprint(change):
    c = source(); r = c['primary']
    if change == 'journal-type': r['type'] = 'journal-article'
    elif change == 'missing-subtype': r.pop('subtype')
    elif change == 'author': r['author'][1]['given'] = 'James'
    elif change == 'notice': r['update-to'] = [{'DOI':r['DOI']}]
    elif change == 'first-date': r['published']['date-parts'] = [[2020,4,22]]
    else: r['relation'] = {'is-preprint-of':[{'id-type':'doi','id':'10.1234/other'}]}
    assert assess(c)['status'] == 'needs_review'


def test_actual_withdrawal_is_seen_even_when_original_title_is_unchanged():
    api = DATA['withdrawn']; doi = '10.1101/2020.01.30.927871'
    rows = p.versions(api, doi)
    assert rows[0]['title'] == rows[1]['title'] and rows[1]['type'] == 'withdrawn'
    candidate = {'source':p.SOURCE,'doi':doi,'raw_record':{'api':api}}
    assert secondary_notice_flags([candidate]) == {doi}


def seed(tmp_path):
    c=source(); bib=tmp_path/'library.bib';bib.write_text(c['entry']['raw'])
    cache=v.Cache(tmp_path/'cache.sqlite3');entry=v.load_entries(bib)['LeeEtal19']
    primary={'source':'crossref','doi':c['primary']['DOI'],'record':c['primary'],'issues':['preprint'], 'evidence':{}}
    previous=v.outcome('needs_review',['No journal approval'],[primary])
    previous['auto_review']={'policy':POLICY,'resolver_version':RESOLVER_VERSION,'epmc_checked':True,'fulltext_checked':True}
    cache.put(bib,entry,previous)
    cache.save_response('biorxiv-details-v1:'+c['primary']['DOI'],c['api'])
    cache.save_response('biorxiv-html-v1:'+c['html']['url'],c['html'])
    return c,bib,cache


def test_cached_route_repeat_restore_key_rename_and_substantive_edit(tmp_path):
    c,bib,cache=seed(tmp_path);client=DeferredClient(cache,None,1.0,False)
    result=p.run_preprint_review(bib,cache,client,tmp_path/'report');assert result['LeeEtal19']['status']=='metadata_verified'
    n=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert p.run_preprint_review(bib,cache,client,tmp_path/'report')==result and client.requests==0
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==n
    snapshot=tmp_path/'snapshot.gz';v.export_snapshot(bib,cache,snapshot)
    fresh=v.Cache(tmp_path/'fresh.sqlite3');assert v.import_snapshot(bib,fresh,snapshot)==1
    assert v.current_results(bib,fresh)==result and v.import_snapshot(bib,fresh,snapshot)==0
    bib.write_text(bib.read_text().replace('LeeEtal19,','Renamed,'))
    assert v.current_results(bib,fresh)['Renamed']['status']=='metadata_verified'
    bib.write_text(bib.read_text().replace('2019','2020'))
    assert v.current_results(bib,fresh)['Renamed']['status']=='pending'
    cache.close();fresh.close()


def test_later_withdrawal_survives_edit_and_clean_restore_without_repeat_writes(tmp_path):
    c,bib,cache=seed(tmp_path);client=DeferredClient(cache,None,1.0,False)
    p.run_preprint_review(bib,cache,client,tmp_path/'report')
    api=deepcopy(c['api'])
    def withdraw(d):
        r=deepcopy(d['collection'][0]);r.update(version='2',type='withdrawn',date='2020-01-01');d['collection'].append(r)
    body_edit(api,withdraw)
    notice={'source':p.SOURCE,'doi':c['primary']['DOI'],'raw_record':{'api':api}}
    cache.remember_notices([notice])
    held=v.current_results(bib,cache);assert held['LeeEtal19']['status']=='needs_review'
    n=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert v.current_results(bib,cache)==held and cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==n
    snapshot=tmp_path/'snapshot.gz';v.export_snapshot(bib,cache,snapshot)
    fresh=v.Cache(tmp_path/'fresh.sqlite3');assert v.import_snapshot(bib,fresh,snapshot)==1
    assert fresh.db.execute('SELECT count(*) FROM source_notices').fetchone()[0]==1
    bib.write_text(bib.read_text().replace('2019','2020'));entry=v.load_entries(bib)['LeeEtal19']
    stale=assess(c);fresh.put(bib,entry,stale)
    assert v.current_results(bib,fresh)['LeeEtal19']['status']=='needs_review'
    cache.close();fresh.close()


def test_normal_cli_uses_real_cached_repository_evidence(tmp_path):
    from typer.testing import CliRunner
    from verification_cli import app
    c,bib,cache=seed(tmp_path);database=cache.path if hasattr(cache,'path') else tmp_path/'cache.sqlite3';cache.close()
    args=['verify',str(bib),'--database',str(database),'--report',str(tmp_path/'report'),'--auto-review']
    first=CliRunner().invoke(app,args);assert first.exit_code==0,first.output
    assert 'network requests: 0' in first.output.lower()
    cache=v.Cache(database);before=v.current_results(bib,cache);n=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0];cache.close()
    repeat=CliRunner().invoke(app,args);assert repeat.exit_code==0,repeat.output
    cache=v.Cache(database);assert v.current_results(bib,cache)==before and cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==n;cache.close()


def test_multiversion_requires_explicit_pin_and_cannot_bypass_withdrawal():
    c=source()
    def revise(d):
        r=deepcopy(d['collection'][0]);r.update(version='2',date='2020-01-01');d['collection'].append(r)
    body_edit(c['api'],revise)
    assert assess(c)['status']=='needs_review'
    c['entry']['fields']['volume']='10.1101/615203v1'
    assert assess(c)['status']=='metadata_verified'
    body_edit(c['api'],lambda d:d['collection'][1].update(type='withdrawn'))
    assert assess(c)['status']=='needs_review'


def test_competing_registry_notice_and_external_hold_cannot_be_overridden():
    c=source();result=assess(c)
    notice={'source':'crossref','doi':result['accepted_doi'],'record':dict(c['primary'],**{'update-to':[{'DOI':result['accepted_doi']}]}),'issues':['notice']}
    result['candidates'].append(notice)
    assert not p.valid_preprint_approval(result)
    assert p.reassess_saved_preprint(c['entry']['fields'],result)['status']=='needs_review'
    result=assess(c);result['external_evidence']=[{'hold':'source conflict'}]
    assert not p.valid_preprint_approval(result)
    assert reassess(c['entry'],result)['status']=='needs_review'


@pytest.mark.parametrize('status,body',[(301,''),(503,''),(200,'<html>Unavailable</html>')])
def test_failed_transport_or_malformed_history_is_not_cached(tmp_path,status,body):
    cache=v.Cache(tmp_path/'cache.sqlite3');client=SimpleNamespace(interval=1.0,refresh=False)
    response=SimpleNamespace(status_code=status,url=p.api_url('10.1101/615203'),iter_content=lambda n:[body.encode()],close=lambda:None)
    def request(*args,**kwargs):
        assert client.interval>=3.1 and kwargs['allow_redirects'] is False
        return response
    client.source_request=request
    with pytest.raises((v.ProviderError,ValueError)):
        p.fetch_document(cache,client,response.url,'test',validate=lambda s:p.versions(s,'10.1101/615203'))
    assert client.interval==1.0 and cache.db.execute('SELECT count(*) FROM responses').fetchone()[0]==0
    cache.close()
