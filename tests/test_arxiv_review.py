"""Real arXiv documents, deliberate errors, portable decisions and notice history."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bibcheck'))
import arxiv_review as a
import verification as v
from auto_review import POLICY, RESOLVER_VERSION, reassess, secondary_notice_flags
from verification_cli import DeferredClient

DATA = json.loads((Path(__file__).parent/'fixtures/arxiv_preprints.json').read_text())


def case(key='PianHill22'):
    return deepcopy(DATA[key])


def assess(c):
    return a.assess_arxiv(c['fields'], c['raw'])


def text_edit(source, old, new):
    assert old in source['body']
    source['body'] = source['body'].replace(old, new)
    source['document_sha256'] = hashlib.sha256(source['body'].encode()).hexdigest()


def json_edit(source, change):
    data = json.loads(source['body']); change(data['data']['attributes'])
    source['body'] = json.dumps(data)
    source['document_sha256'] = hashlib.sha256(source['body'].encode()).hexdigest()


@pytest.mark.parametrize('key', ['PianHill22','WietKiel19','CarlWagn18'])
def test_actual_sources_approve_matching_citation(key):
    c=case(key); result=assess(c)
    assert result['status']=='metadata_verified',result['issues']
    assert result['accepted_version'] in {1,2}
    assert a.valid_arxiv_approval(result)
    assert a.reassess_saved_arxiv(c['fields'],result)['status']=='metadata_verified'


@pytest.mark.parametrize('change', [
    {'author':'S Piantadosi and F Hill'}, {'author':'F Hill and S T Piantadosi'},
    {'author':'S T Piantadosi'}, {'author':'S T Piantadosi and others'},
    {'title':'Meaning in language models'}, {'year':'2023'}, {'journal':'Nature'},
    {'volume':'2208.02958'}, {'pages':'1--12'}, {'number':'2'}, {'ENTRYTYPE':'book'},
    {'doi':'10.48550/arXiv.2208.02958'}, {'publisher':'Another Press'},
    {'volume':'2208.02957v1'}, {'archiveprefix':'bioRxiv'}, {'note':'A substantive note'},
])
def test_all_citation_fields_are_binding(change):
    c=case();c['fields'].update(change)
    assert assess(c)['status']=='needs_review'


@pytest.mark.parametrize('value', ['2208.02957','arXiv:2208.02957','https://arxiv.org/abs/2208.02957','doi.org/10.48550/arXiv.2208.02957'])
def test_legacy_identifier_slots_are_explicit_repository_identifiers(value):
    c=case();c['fields']['volume']=value
    assert assess(c)['status']=='metadata_verified'


def test_split_identifier_and_journal_embedded_identifier():
    c=case();c['fields'].update(volume='2208',number='02957')
    assert assess(c)['status']=='metadata_verified'
    c['fields'].pop('volume');c['fields'].pop('number');c['fields']['journal']='{arXiv} Preprint {arXiv}:2208.02957'
    assert assess(c)['status']=='metadata_verified'


@pytest.mark.parametrize('value', ['2208.2957','2013.00001','1301.12345','2208.02957v0','2208.02957v01','2208.02957 garbage','https://evil.test/2208.02957'])
def test_incomplete_or_malformed_identifiers_rejected(value):
    with pytest.raises(ValueError):a.parse_id(value)


@pytest.mark.parametrize('change', ['hash','url','duplicate','different-id','version','title','author','order','date','incomplete','malformed','withdrawal'])
def test_atom_is_a_bound_complete_identity_record(change):
    c=case();s=c['raw']['latest_api']
    if change=='hash':s['document_sha256']='0'*64
    elif change=='url':s['url']=a.api_url('2208.02958')
    elif change=='malformed':text_edit(s,'</feed>','')
    else:
        old,new={
            'duplicate':('</feed>','<entry><id>another</id></entry></feed>'),
            'different-id':('abs/2208.02957v2','abs/2208.02958v2'),
            'version':('abs/2208.02957v2','abs/2208.02957v3'),
            'title':('Meaning without reference','Meaning with reference'),
            'author':('Steven T. Piantadosi','Steven R. Piantadosi'),
            'order':('<name>Steven T. Piantadosi</name>','<name>Felix Hill</name>'),
            'date':('2022-08-12T15:36:46Z','2021-08-12T15:36:46Z'),
            'incomplete':('<opensearch:totalResults>1','<opensearch:totalResults>2'),
            'withdrawal':('<summary>','<summary>This paper has been withdrawn. '),
        }[change]
        text_edit(s,old,new)
    assert assess(c)['status']=='needs_review'


@pytest.mark.parametrize('change', ['og-version','id','title','author','date','updated','missing-history','history-date','history-gap','withdrawal','body-only'])
def test_html_head_and_complete_history_must_agree(change):
    c=case();s=c['raw']['latest_html']
    old,new={
        'og-version':('property="og:url" content="https://arxiv.org/abs/2208.02957v2"','property="og:url" content="https://arxiv.org/abs/2208.02957v3"'),
        'id':('name="citation_arxiv_id" content="2208.02957"','name="citation_arxiv_id" content="2208.02958"'),
        'title':('name="citation_title" content="Meaning without','name="citation_title" content="Meaning with'),
        'author':('content="Piantadosi, Steven T."','content="Piantadosi, Steven R."'),
        'date':('name="citation_date" content="2022/08/05"','name="citation_date" content="2021/08/05"'),
        'updated':('name="citation_online_date" content="2022/08/12"','name="citation_online_date" content="2022/08/11"'),
        'missing-history':('class="submission-history"','class="unrelated"'),
        'history-date':('Fri, 12 Aug 2022 15:36:46 UTC','Fri, 12 Aug 2022 15:36:45 UTC'),
        'history-gap':('<strong>[v2]</strong>','<strong>[v3]</strong>'),
        'withdrawal':('<strong>[v2]</strong>','<strong>[v2]</strong> withdrawn '),
        'body-only':('<head>','<body>'),
    }[change]
    text_edit(s,old,new)
    assert assess(c)['status']=='needs_review'


@pytest.mark.parametrize('change', ['doi','url','publisher','state','version','type','title','byline','name-split','year','date','incomplete','relationship','withdrawal'])
def test_registry_record_must_corroborate_current_version(change):
    c=case()
    def edit(attrs):
        if change in {'doi','url','publisher','state','version','publicationYear'}:
            attrs[change]={'doi':'10.48550/arxiv.2208.02958','url':'https://arxiv.org/abs/2208.02958','publisher':'Other repository','state':'registered','version':'1'}[change]
        elif change=='type':attrs['types']['resourceType']='Dataset'
        elif change=='title':attrs['titles'][0]['title']='Different title'
        elif change=='byline':attrs['creators'].reverse()
        elif change=='name-split':attrs['creators'][0]['givenName']='Steven R.'
        elif change=='year':attrs['publicationYear']=2023
        elif change=='date':attrs['dates'][0]['date']='2022-08-04T02:48:26Z'
        elif change=='incomplete':attrs['dates'].pop(0)
        elif change=='relationship':attrs['relatedIdentifiers']=[{'relationType':'IsObsoletedBy','relatedIdentifierType':'DOI','relatedIdentifier':'10.1234/new'}]
        elif change=='withdrawal':attrs['dates'][0]['dateType']='Withdrawn'
    json_edit(c['raw']['datacite'],edit)
    assert assess(c)['status']=='needs_review'


def test_real_withdrawal_persists_despite_unchanged_title_and_old_version():
    raw=deepcopy(DATA['withdrawn']);record=a.atom(raw['latest_api'],raw['base'])
    assert record['title']=='Predicting Graph Categories from Structural Properties'
    candidate={'source':a.SOURCE,'doi':a.doi_for(raw['base']),'raw_record':raw}
    assert secondary_notice_flags([candidate])=={candidate['doi']}
    fields={'ENTRYTYPE':'article','journal':'arXiv','volume':raw['base']+'v1','title':record['title'],
            'author':' and '.join(record['authors']),'year':'2018'}
    earlier=a.atom(raw['selected_api'],raw['base']+'v1')
    assert not a.NOTICE.search(earlier['summary'] + earlier['comment'])
    assert earlier['title']==record['title']
    assert a.assess_arxiv(fields,raw)['status']=='needs_review'


def test_real_explicit_earlier_version_uses_its_own_sources():
    c=case();c['fields']['volume']='2208.02957v1'
    # v1 actually misspells Piantadosi as Piantasodi. The correct current
    # citation cannot borrow v2's repaired name while claiming to cite v1.
    assert assess(c)['status']=='needs_review'
    # A synthetic citation reproducing v1 metadata tests the positive branch;
    # this spelling is never applied to the real bibliography.
    c['fields']['author']='Steven T. Piantasodi and Felix Hill'
    result=assess(c)
    assert result['status']=='metadata_verified',result['issues']
    assert result['accepted_version']==1
    assert a.valid_arxiv_approval(result)
    text_edit(c['raw']['selected_api'],'<name>Felix Hill</name>','<name>Felix Hall</name>')
    assert assess(c)['status']=='needs_review'


def test_unversioned_does_not_silently_choose_an_old_byline():
    c=case()
    # Earlier-version documents are present and remain matching, but an
    # unversioned citation is bound to the current version's byline.
    text_edit(c['raw']['latest_api'],'<name>Felix Hill</name>','<name>Felix Hall</name>')
    assert assess(c)['status']=='needs_review'


def seed(tmp_path):
    c=case();bib=tmp_path/'library.bib';f=c['fields']
    bib.write_text('@article{PianHill22,\n'+',\n'.join(k+'={'+value+'}' for k,value in f.items() if k not in {'ID','ENTRYTYPE'})+'\n}')
    cache=v.Cache(tmp_path/'cache.sqlite3');entry=v.load_entries(bib)['PianHill22']
    previous=v.outcome('needs_review',['Repository evidence needed'],[])
    previous['auto_review']={'policy':POLICY,'resolver_version':RESOLVER_VERSION,'epmc_checked':True,'fulltext_checked':True}
    cache.put(bib,entry,previous)
    for s in c['raw'].values():
        if isinstance(s,dict) and 'url' in s:cache.save_response('arxiv-source-v1:'+s['url'],s)
    return c,bib,cache


def test_repeat_snapshot_key_rename_and_substantive_edit(tmp_path):
    c,bib,cache=seed(tmp_path);client=DeferredClient(cache,None,1.0,False)
    result=a.run_arxiv_review(bib,cache,client,tmp_path/'report');assert result['PianHill22']['status']=='metadata_verified'
    n=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert a.run_arxiv_review(bib,cache,client,tmp_path/'report')==result and client.requests==0
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==n
    snapshot=tmp_path/'snapshot.gz';v.export_snapshot(bib,cache,snapshot)
    fresh=v.Cache(tmp_path/'fresh.sqlite3');assert v.import_snapshot(bib,fresh,snapshot)==1
    assert v.current_results(bib,fresh)==result and v.import_snapshot(bib,fresh,snapshot)==0
    bib.write_text(bib.read_text().replace('PianHill22,','Renamed,'));assert v.current_results(bib,fresh)['Renamed']['status']=='metadata_verified'
    bib.write_text(bib.read_text().replace('2022','2023'));assert v.current_results(bib,fresh)['Renamed']['status']=='pending'
    cache.close();fresh.close()


def test_notice_survives_edit_without_doi_or_candidates_and_restore(tmp_path):
    c,bib,cache=seed(tmp_path);client=DeferredClient(cache,None,1.0,False)
    a.run_arxiv_review(bib,cache,client,tmp_path/'report')
    raw=deepcopy(c['raw']);text_edit(raw['latest_api'],'<summary>','<summary>This paper has been withdrawn. ')
    cache.remember_notices([{'source':a.SOURCE,'doi':a.doi_for(raw['base']),'raw_record':raw}])
    held=v.current_results(bib,cache);assert held['PianHill22']['status']=='needs_review'
    n=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert v.current_results(bib,cache)==held and cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==n
    snapshot=tmp_path/'snapshot.gz';v.export_snapshot(bib,cache,snapshot)
    fresh=v.Cache(tmp_path/'fresh.sqlite3');v.import_snapshot(bib,fresh,snapshot)
    bib.write_text(bib.read_text().replace('2022','2023'));entry=v.load_entries(bib)['PianHill22']
    fresh.put(bib,entry,v.outcome('needs_review',['new entry revision'],[]))
    assert secondary_notice_flags(v.current_results(bib,fresh)['PianHill22']['candidates'])=={a.doi_for(raw['base'])}
    cache.close();fresh.close()


def test_normal_cli_uses_source_route_and_unchanged_repeat(tmp_path):
    from typer.testing import CliRunner
    from verification_cli import app
    c,bib,cache=seed(tmp_path);cache.close();database=tmp_path/'cache.sqlite3'
    args=['verify',str(bib),'--database',str(database),'--report',str(tmp_path/'report'),'--auto-review']
    first=CliRunner().invoke(app,args);assert first.exit_code==0,first.output
    assert 'network requests: 0' in first.output.lower()
    cache=v.Cache(database);before=v.current_results(bib,cache);n=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0];cache.close()
    repeat=CliRunner().invoke(app,args);assert repeat.exit_code==0,repeat.output
    cache=v.Cache(database);assert v.current_results(bib,cache)==before and cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==n;cache.close()


def test_source_hold_and_registry_notice_cannot_be_overridden():
    c=case();result=assess(c)
    result['candidates'].append({'source':'crossref','doi':result['accepted_doi'],'record':{'updated-by':[{'DOI':result['accepted_doi']}]},'issues':['notice']})
    assert not a.valid_arxiv_approval(result)
    assert a.reassess_saved_arxiv(c['fields'],result)['status']=='needs_review'
    result=assess(c);result['external_evidence']=[{'hold':'conflict'}]
    assert not a.valid_arxiv_approval(result)
    assert reassess({'fields':c['fields']},result)['status']=='needs_review'


def test_registry_notice_description_is_retained_and_issued_year_is_checked():
    c=case()
    json_edit(c['raw']['datacite'],lambda d:d.update(descriptions=[{'description':'This preprint has been retracted.','descriptionType':'Other'}]))
    result=assess(c)
    assert result['status']=='needs_review'
    assert secondary_notice_flags(result['candidates'])=={a.doi_for(c['raw']['base'])}
    c=case()
    def change(d):
        next(x for x in d['dates'] if x['dateType']=='Issued')['date']='2023'
    json_edit(c['raw']['datacite'],change)
    assert assess(c)['status']=='needs_review'


@pytest.mark.parametrize('body', ['<html>unavailable</html>','<feed>truncated', '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>error</id></entry></feed>'])
def test_malformed_atom_is_not_cached(tmp_path,body):
    cache=v.Cache(tmp_path/'cache.sqlite3');client=SimpleNamespace(interval=1.0,refresh=False)
    url=a.api_url('2208.02957');response=SimpleNamespace(status_code=200,url=url,iter_content=lambda n:[body.encode()],close=lambda:None)
    client.source_request=lambda *args,**kwargs:response
    with pytest.raises((ValueError,a.ET.ParseError)):
        a.fetch_document(cache,client,url,'test',validate=lambda s:a.atom(s,'2208.02957'))
    assert cache.db.execute('SELECT count(*) FROM responses').fetchone()[0]==0
    assert client.interval==1.0;cache.close()
