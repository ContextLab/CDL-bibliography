"""A pinned, documented edition can resolve its imprint, never another book."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bibcheck'))
from catalogue_imprint import EDITIONS,assess_catalogue_imprint,catalogue_publisher
from auto_review import reassess
from verification import Cache,load_entries,export_snapshot,import_snapshot


def fixture():
    return json.loads((ROOT/'tests/fixtures/catalogue_imprint.json').read_text())


def test_original_imprint_is_read_from_catalogue_and_all_chapter_fields_rechecked():
    data=fixture(); checked=assess_catalogue_imprint(data['fields'],data['primary'])
    assert checked['issues']==[]
    assert checked['record']['publisher']=='Plenum Press'
    assert checked['evidence']['publisher']['registry_publisher']=='Springer US'
    row=reassess({'fields':data['fields']},{'status':'needs_review','candidates':[data['primary']]})
    assert row['status']=='metadata_verified' and row['accepted_source']=='catalogue-imprint'
    checked['raw_marcxml']=checked['raw_marcxml'].replace('Plenum Press','Wrong Press')
    assert reassess({'fields':data['fields']},{'status':'needs_review','candidates':[data['primary'],checked]})['status']=='needs_review'


@pytest.mark.parametrize('change',['title','author','pages','year','booktitle','publisher','doi','isbn','type','registry-publisher','registry-isbn','registry-title','registry-year','registry-type','registry-doi'])
def test_other_fields_and_edition_identity_cannot_be_overridden(change):
    d=fixture();f,p=d['fields'],d['primary'];r=p['record']
    if change=='type':f['ENTRYTYPE']='book'
    elif change=='registry-publisher':r['publisher']='Another Press'
    elif change=='registry-isbn':r['ISBN']=['9780306406430']
    elif change=='registry-title':r['container-title']=['Different book']
    elif change=='registry-year':r['published-print']={'date-parts':[[1982]]}
    elif change=='registry-type':r['type']='posted-content'
    elif change=='registry-doi':p['doi']=r['DOI']='10.1007/978-1-4684-1083-8_9'
    else:f[change]={'title':'Wrong chapter','author':'A Smith','pages':'121--129','year':'2012','booktitle':'Wrong book','publisher':'Springer US','doi':'10.1234/wrong','isbn':'9780306406430'}[change]
    assert assess_catalogue_imprint(f,p)['issues']


@pytest.mark.parametrize('change',['body','url','hash','doctype','html'])
def test_unpinned_or_non_catalogue_response_does_not_supply_evidence(change):
    d=fixture();r=deepcopy(EDITIONS[0])
    if change=='body':r['raw_marcxml']=r['raw_marcxml'].replace('80028692','80028693')
    elif change=='url':r['catalogue_url']='https://example.com/marcxml'
    elif change=='hash':r['document_sha256']='0'*64
    elif change=='doctype':r['raw_marcxml']='<!DOCTYPE record>'+r['raw_marcxml']
    else:r['raw_marcxml']='<html>Service unavailable</html>'
    assert assess_catalogue_imprint(d['fields'],d['primary'],r)['issues']


def test_catalogue_binding_survives_snapshot_restore_and_edit_rechecks(tmp_path):
    d=fixture();f=d['fields'];bib=tmp_path/'sample.bib'
    text='@incollection{A, '+','.join(k+'={'+v+'}' for k,v in f.items() if k not in {'ID','ENTRYTYPE'})+'}'
    bib.write_text(text);cache=Cache(tmp_path/'cache.sqlite3');entry=load_entries(bib)['A']
    accepted=cache.put(bib,entry,reassess(entry,{'status':'needs_review','candidates':[d['primary']]}))
    assert accepted['status']=='metadata_verified'
    export_snapshot(bib,cache,tmp_path/'baseline.gz');fresh=Cache(tmp_path/'fresh.sqlite3')
    assert import_snapshot(bib,fresh,tmp_path/'baseline.gz')==1
    assert fresh.get(bib,entry)==accepted
    bib.write_text(text.replace('121--128','121--129'));new=load_entries(bib)['A']
    assert fresh.get(bib,new) is None
    assert reassess(new,accepted)['status']=='needs_review'
    cache.close();fresh.close()


@pytest.mark.parametrize('change',['record-id','lccn','title','date-type','date-year','statement-year','subtitle','edition','distributor','duplicate-statement','serial-type'])
def test_catalogue_parser_rejects_ambiguous_publication_roles_and_editions(change):
    import hashlib
    import xml.etree.ElementTree as ET
    from catalogue_imprint import M
    edition=deepcopy(EDITIONS[0]);root=ET.fromstring(edition['raw_marcxml'])
    def field(tag):return next(n for n in root.findall(M+'datafield') if n.get('tag')==tag)
    def sub(tag,code):return next(n for n in field(tag).findall(M+'subfield') if n.get('code')==code)
    if change=='record-id':next(n for n in root.findall(M+'controlfield') if n.get('tag')=='001').text='999'
    elif change=='lccn':sub('010','a').text='80028693'
    elif change=='title':sub('245','a').text='A different book /'
    elif change in {'date-type','date-year'}:
        node=next(n for n in root.findall(M+'controlfield') if n.get('tag')=='008')
        node.text=node.text[:6]+('r' if change=='date-type' else 's')+('1982' if change=='date-year' else '1981')+node.text[11:]
    elif change=='statement-year':sub('260','c').text='c1982.'
    elif change=='subtitle':ET.SubElement(field('245'),M+'subfield',{'code':'b'}).text='A subtitle'
    elif change=='edition':ET.SubElement(root,M+'datafield',{'tag':'250'})
    elif change=='distributor':sub('260','b').text='Distributed by Plenum Press,'
    elif change=='duplicate-statement':root.append(deepcopy(field('260')))
    else:root.find(M+'leader').text='01590cas a2200397 i 4500'
    xml=ET.tostring(root,encoding='unicode');edition['document_sha256']=hashlib.sha256(xml.encode()).hexdigest()
    with pytest.raises(ValueError):catalogue_publisher(xml,edition)
