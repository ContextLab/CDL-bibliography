"""Real edition records, adverse metadata, and incremental book verification."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bibcheck'))
import catalogue_review as cr
from catalogue_discovery import M, S
import verification as v
from auto_review import reassess

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/catalogue_books.json').read_text())


def source(key='Albe00'):
    x = deepcopy(FIXTURE[key])
    return x['entry'], x['response']


def mutate(response, action):
    response = deepcopy(response)
    root = ET.fromstring(response['raw_xml'])
    action(root, root.find('.//' + M + 'record'))
    response['raw_xml'] = ET.tostring(root, encoding='unicode')
    response['document_sha256'] = hashlib.sha256(response['raw_xml'].encode()).hexdigest()
    return response


@pytest.mark.parametrize('key', ['Albe00', 'Altm99', 'BraiReyn05', 'CoheEich93',
                               'GallKing09', 'GelmHill07', 'RogeMcCl04', 'DeVaDeVa88', 'ClifOrd73'])
def test_actual_exact_editions_and_portable_provenance(key):
    entry, response = source(key)
    result = cr.assess_catalogue(entry['fields'], response)
    assert result['status'] == 'metadata_verified'
    assert cr.valid_catalogue_approval(result)
    assert cr.reassess_saved_catalogue(entry['fields'], result) == result


@pytest.mark.parametrize('key', ['ThruEtal06', 'Rasm06', 'DudaEtal01', 'SchaTulv94', 'TalaTour88'])
def test_real_wrong_year_missing_author_related_work_editors_and_translation(key):
    entry, response = source(key)
    assert cr.assess_catalogue(entry['fields'], response)['status'] == 'needs_review'


@pytest.mark.parametrize('change', ['reverse-local', 'missing-local', 'extra-local',
    'reverse-byline', 'missing-byline', 'et-al', 'editor', 'translator', 'analytical',
    'related-title', 'duplicate-heading', 'extra-responsibility'])
def test_added_person_headings_require_complete_matching_author_byline(change):
    entry, response = source('BraiReyn05')
    if change == 'reverse-local':
        entry['fields']['author'] = 'V F Reyna and C J Brainerd'
    elif change == 'missing-local':
        entry['fields']['author'] = 'C J Brainerd'
    elif change == 'extra-local':
        entry['fields']['author'] += ' and Anne Other'
    else:
        def edit(root, record):
            heading = record.find(M+"datafield[@tag='700']")
            byline = record.find(M+"datafield[@tag='245']/"+M+"subfield[@code='c']")
            if change == 'reverse-byline': byline.text = 'V.F. Reyna and C.J. Brainerd.'
            elif change == 'missing-byline': byline.text = 'C.J. Brainerd.'
            elif change == 'et-al': byline.text = 'C.J. Brainerd ... [et al.].'
            elif change == 'editor': ET.SubElement(heading, M+'subfield', code='e').text = 'editor.'
            elif change == 'translator': ET.SubElement(heading, M+'subfield', code='4').text = 'trl'
            elif change == 'analytical': heading.set('ind2', '2')
            elif change == 'related-title': ET.SubElement(heading, M+'subfield', code='t').text = 'Other work.'
            elif change == 'duplicate-heading': record.append(deepcopy(heading))
            elif change == 'extra-responsibility': byline.text += ' With the collaboration of Anne Other.'
        response = mutate(response, edit)
    assert cr.assess_catalogue(entry['fields'], response)['status'] == 'needs_review'


def test_three_author_byline_accepts_commas_but_still_checks_every_name():
    entry, response = source('ThruEtal06')
    entry['fields']['year'] = '2005'
    assert cr.assess_catalogue(entry['fields'], response)['status'] == 'metadata_verified'
    entry['fields']['author'] = 'S Thrun and W Burgard and David Fox'
    assert cr.assess_catalogue(entry['fields'], response)['status'] == 'needs_review'


@pytest.mark.parametrize('change', ['missing-particle', 'wrong-surname', 'wrong-given', 'extra-given', 'reversed', 'extra-person'])
def test_heading_supplied_compound_family_grouping_cannot_change_identity(change):
    entry, response = source('DeVaDeVa88')
    def edit(root, record):
        node = record.find(M+"datafield[@tag='245']/"+M+"subfield[@code='c']")
        node.text = {
            'missing-particle': 'Russell L. Valois, Karen K. De Valois.',
            'wrong-surname': 'Russell L. De Smith, Karen K. De Valois.',
            'wrong-given': 'Robert L. De Valois, Karen K. De Valois.',
            'extra-given': 'Russell L. A. De Valois, Karen K. De Valois.',
            'reversed': 'Karen K. De Valois, Russell L. De Valois.',
            'extra-person': 'Russell L. De Valois, Karen K. De Valois, Anne Other.',
        }[change]
    assert cr.assess_catalogue(entry['fields'], mutate(response, edit))['status'] == 'needs_review'


@pytest.mark.parametrize('prefix', ['[edited by]', '[translated by]', '[with]', '[by?]'])
def test_bracketed_responsibility_does_not_guess_author_role(prefix):
    entry, response = source('ClifOrd73')
    def edit(root, record):
        node = record.find(M+"datafield[@tag='245']/"+M+"subfield[@code='c']")
        node.text = node.text.replace('[by]', prefix)
    assert cr.assess_catalogue(entry['fields'], mutate(response, edit))['status'] == 'needs_review'


@pytest.mark.parametrize('value', ['0195050193 (alk. paper) ::', '0195050193 : $34.95',
    '0195050193 (alk. paper) : other', '[0195050193] :', '0195050193? :'])
def test_isbn_terminal_separator_does_not_discard_uncertainty_or_other_text(value):
    entry, response = source('DeVaDeVa88')
    def edit(root, record):
        record.find(M+"datafield[@tag='020']/"+M+"subfield[@code='a']").text = value
    assert cr.assess_catalogue(entry['fields'], mutate(response, edit))['status'] == 'needs_review'


@pytest.mark.parametrize('field,value', [('author','David A Albert'), ('title','Time and change'),
    ('year','2001'), ('publisher','Yale University Press'), ('address','Cambridge, England'),
    ('edition','2nd ed'), ('pages','1--99'), ('editor','Jane Editor'), ('doi','10.1234/book'),
    ('isbn','9780000000000'), ('ENTRYTYPE','inbook')])
def test_each_supplied_field_is_checked(field, value):
    entry, response = source()
    entry['fields'][field] = value
    assert cr.assess_catalogue(entry['fields'], response)['status'] == 'needs_review'


@pytest.mark.parametrize('change', ['reproduction','electronic','date','creator','responsibility',
    'publisher','subtitle','edition','translation','titlepart','duplicate','unparseable-rival',
    'author-suffix','editor-role','family-name'])
def test_wrong_versions_and_unassessable_alternatives_stay_unresolved(change):
    entry, response = source()
    def edit(root, record):
        def add(tag, code, value):
            n=ET.SubElement(record, M+'datafield', tag=tag)
            ET.SubElement(n, M+'subfield', code=code).text=value
        if change in {'reproduction','electronic','date'}:
            n=record.find(M+"controlfield[@tag='008']")
            p=23 if change!='date' else 6
            n.text=n.text[:p]+{'reproduction':'r','electronic':'o','date':'r'}[change]+n.text[p+1:]
        elif change=='creator': add('700','a','Other, Anne')
        elif change=='responsibility': record.find(M+"datafield[@tag='245']/"+M+"subfield[@code='c']").text='David Z Albert and Anne Other.'
        elif change=='publisher': record.find(M+"datafield[@tag='260']/"+M+"subfield[@code='b']").text='distributed by Harvard University Press,'
        elif change=='subtitle': ET.SubElement(record.find(M+"datafield[@tag='245']"), M+'subfield', code='b').text='a revised version /'
        elif change=='edition': add('250','a','Second edition.')
        elif change=='translation': add('500','a','Translation of a different work.')
        elif change=='titlepart': ET.SubElement(record.find(M+"datafield[@tag='245']"), M+'subfield', code='n').text='Part 2'
        elif change=='author-suffix': ET.SubElement(record.find(M+"datafield[@tag='100']"), M+'subfield', code='c').text='Jr.'
        elif change=='editor-role': ET.SubElement(record.find(M+"datafield[@tag='100']"), M+'subfield', code='e').text='editor.'
        elif change=='family-name': record.find(M+"datafield[@tag='100']").set('ind1','3')
        else:
            wrapper=deepcopy(root.find(S+'records/'+S+'record'))
            wrapper.find(S+'recordPosition').text='2'
            second=wrapper.find(S+'recordData/'+M+'record')
            second.find(M+"controlfield[@tag='001']").text='other-edition'
            if change=='unparseable-rival':
                second.remove(second.find(M+"datafield[@tag='260']"))
            root.find(S+'records').append(wrapper)
            root.find(S+'numberOfRecords').text='2'
    assert cr.assess_catalogue(entry['fields'], mutate(response,edit))['status']=='needs_review'


def test_separate_known_years_are_not_merged():
    entry,response=source('Ande95')
    # MARC 008 explicitly identifies New York state for the first place.
    assert cr.assess_catalogue(entry['fields'], response)['status']=='metadata_verified'
    entry['fields']['address']='New York'
    r=cr.assess_catalogue(entry['fields'], response)
    assert r['status']=='metadata_verified' and r['accepted_record_id']=='2068246'
    entry['fields']['year']='2000'
    assert cr.assess_catalogue(entry['fields'], response)['status']=='needs_review'  # missing second edition
    assert cr.assess_catalogue(*[source('Addi02')[0]['fields'],source('Addi02')[1]])['status']=='needs_review'


def test_reassessment_uses_raw_data_not_saved_booleans():
    entry,response=source()
    result=cr.assess_catalogue(entry['fields'],response)
    entry['fields']['year']='1900'
    assert reassess(entry,result)['status']=='needs_review'
    result['candidates'][0]['raw_search_xml']+='<bad/>'
    assert not cr.valid_catalogue_approval(result)


def test_run_once_rename_reuse_edit_invalidation_and_restore(tmp_path, monkeypatch):
    entry,response=source()
    bib=tmp_path/'source.bib';bib.write_text(entry['raw'])
    cache=v.Cache(tmp_path/'cache.sqlite3');entry=v.load_entries(bib)['Albe00']
    v0=cache.put(bib,entry,v.outcome('needs_review',['No Crossref match']))
    calls=[]
    monkeypatch.setattr(cr,'fetch_search',lambda *args: calls.append(1) or response)
    def run(keys=None):return cr.run_catalogue_review(bib,cache,object(),tmp_path/'report.jsonl',keys=keys)
    first=run();assert first['Albe00']['status']=='metadata_verified'
    count=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    bib.write_text(bib.read_text().replace('{Albe00,','{Renamed,'))
    assert run()['Renamed']==dict(first['Albe00'],key='Renamed')
    assert len(calls)==1 and cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==count
    snapshot=tmp_path/'baseline.jsonl.gz';v.export_snapshot(bib,cache,snapshot)
    fresh=v.Cache(tmp_path/'fresh.sqlite3')
    assert v.import_snapshot(bib,fresh,snapshot)==1
    assert v.import_snapshot(bib,fresh,snapshot)==0
    assert v.current_results(bib,fresh)==v.current_results(bib,cache)
    bib.write_text(bib.read_text().replace('2000','2001'))
    edited=v.load_entries(bib)['Renamed']
    assert v.current_results(bib,cache)['Renamed']['status']=='pending'
    cache.put(bib,edited,v0)
    assert run()['Renamed']['status']=='needs_review' and len(calls)==2
    assert run()==run() and len(calls)==2
    assert run(keys=set())==v.current_results(bib,cache)
    cache.close();fresh.close()


def test_snapshot_requires_real_accepted_record_identity(tmp_path):
    entry,response=source()
    bib=tmp_path/'source.bib';bib.write_text(entry['raw']);entry=v.load_entries(bib)['Albe00']
    c=v.Cache(tmp_path/'c.sqlite3');c.put(bib,entry,cr.assess_catalogue(entry['fields'],response))
    path=tmp_path/'snapshot.gz';v.export_snapshot(bib,c,path)
    with gzip.open(path,'rt')as f:rows=list(map(json.loads,f))
    rows[1]['accepted_record_id']='different-edition'
    with gzip.open(path,'wt')as f:f.write('\n'.join(json.dumps(r)for r in rows)+'\n')
    fresh=v.Cache(tmp_path/'fresh.sqlite3')
    with pytest.raises(ValueError,match='missing its source evidence'):v.import_snapshot(bib,fresh,path)
    assert fresh.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==0
    c.close();fresh.close()


def test_normal_cli_uses_cached_catalogue_and_repeat_needs_no_credentials(tmp_path):
    from typer.testing import CliRunner
    from verification_cli import app
    entry,response=source()
    bib=tmp_path/'source.bib';bib.write_text(entry['raw']);entry=v.load_entries(bib)['Albe00']
    database=tmp_path/'cache.sqlite3';cache=v.Cache(database)
    cache.put(bib,entry,v.outcome('needs_review',['No registry match'],[]))
    from catalogue_discovery import search_query
    cache.save_response('loc-sru-v1:10:'+search_query(entry['fields']),response)
    cache.close()
    args=['verify',str(bib),'--database',str(database),'--report',str(tmp_path/'report'), '--auto-review']
    first=CliRunner().invoke(app,args)
    assert first.exit_code==0, first.output
    assert 'network requests: 0' in first.output.lower()
    cache=v.Cache(database);original=v.current_results(bib,cache);count=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0];cache.close()
    repeated=CliRunner().invoke(app,args)
    assert repeated.exit_code==0, repeated.output
    cache=v.Cache(database)
    assert v.current_results(bib,cache)==original and cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==count
    cache.close()


@pytest.mark.parametrize('change', ['wrong-state','wrong-city','unknown-code','contradictory-state','second-place'])
def test_coded_address_never_guesses_city_or_another_place(change):
    entry,response=source('Ande95')
    if change=='wrong-state':entry['fields']['address']='New York, MA'
    elif change=='wrong-city':entry['fields']['address']='Albany, NY'
    else:
        def edit(root, record):
            if change=='unknown-code':
                n=record.find(M+"controlfield[@tag='008']");n.text=n.text[:15]+'xxu'+n.text[18:]
            elif change=='contradictory-state':
                record.find(M+"datafield[@tag='260']/"+M+"subfield[@code='a']").text='New York, Mass. :'
            else:
                n=record.find(M+"datafield[@tag='260']")
                n.find(M+"subfield[@code='a']").text='Albany ;'
                ET.SubElement(n,M+'subfield',code='a').text='New York :'
        response=mutate(response,edit)
    assert cr.assess_catalogue(entry['fields'],response)['status']=='needs_review'


def test_massachusetts_abbreviation_is_supported_by_coded_first_place():
    entry,response=source()
    entry['fields']['address']='Cambridge, MA'
    result=cr.assess_catalogue(entry['fields'],response)
    assert result['status']=='metadata_verified'
    assert result['candidates'][0]['evidence']['address']['source_place_code']=='mau'
    assert cr.valid_catalogue_approval(result)


def test_external_hold_and_irrelevant_doi_notice_are_preserved_separately(tmp_path):
    entry,response=source();result=cr.assess_catalogue(entry['fields'],response)
    assert reassess(entry,dict(result,external_evidence={'note':'explicit review needed'}))['status']=='needs_review'
    from test_jats_notice_cache import setup
    _,cache,_,_,notice=setup(tmp_path)
    # A rejected article DOI is unrelated to the edition's MARC identity.
    result['candidates'].append(notice)
    assert cache.retain_notices(entry,result)==result
    cache.close()
