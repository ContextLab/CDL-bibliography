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



# ---------------------------------------------------------------------------
# Policy-7 widened grammar. DERIVED holds real LC records from the cached
# searches (.bibcheck/verification.sqlite3, retrieved 2026-09), trimmed to the
# control fields and the 020/100/111/245/250/260/264/500/700/710/711/776
# datafields in a compact 'TAG I1I2 ‡aValue‡bValue' form, with record ids kept.
# Every record of each cached search is kept, so uniqueness is tested too.
# ---------------------------------------------------------------------------

DERIVED = json.loads(r"""{
 "Broa58": {
  "fields": {
   "year": "1958",
   "title": "Perception and communication",
   "publisher": "Pergamon Press",
   "author": "D E Broadbent",
   "address": "New York, {NY}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 00927cam a22003011  4500",
    "001 4529843",
    "008 730313s1958    nyua     b    000 0 eng  ",
    "1001  ‡aBroadbent, Donald E.‡q(Donald Eric)",
    "24510 ‡aPerception and communication.",
    "260   ‡aNew York,‡bPergamon Press,‡c1958."
   ]
  ]
 },
 "GreeSwet66": {
  "fields": {
   "year": "1966",
   "title": "Signal detection theory and psychophysics",
   "publisher": "Wiley",
   "author": "D M Green and J A Swets",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01183cam a2200325   4500",
    "001 322116",
    "008 740926r1974    nyua     b    001 0 eng  ",
    "020   ‡a0882751395",
    "020   ‡a9780882751399",
    "1001  ‡aGreen, David Marvin,‡d1932-",
    "24510 ‡aSignal detection theory and psychophysics‡c[by] David M. Green [and] John A. Swets.",
    "260   ‡aHuntington, N.Y.,‡bR. E. Krieger Pub. Co.‡c[1974, c1966]",
    "500   ‡aReprint of the ed. published by Wiley, New York; with new pref. and bibliography.",
    "7001  ‡aSwets, John A.,‡d1928-‡ejoint author."
   ],
   [
    "LDR 01016cam a22003011  4500",
    "001 1697383",
    "008 731212s1966    nyua     b    000 0 eng  ",
    "1001  ‡aGreen, David Marvin,‡d1932-",
    "24510 ‡aSignal detection theory and psychophysics‡c[by] David M. Green [and] John A. Swets.",
    "260   ‡aNew York,‡bWiley‡c[1966]",
    "7001  ‡aSwets, John A.,‡d1928-‡ejoint author."
   ]
  ]
 },
 "Torg58": {
  "fields": {
   "year": "1958",
   "title": "Theory and methods of scaling",
   "publisher": "Wiley",
   "author": "W S Torgerson",
   "address": "New York, {NY}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 00878cam a22002891  4500",
    "001 4529830",
    "008 730220s1958    nyua     b    000 0 eng  ",
    "1001  ‡aTorgerson, Warren S.",
    "24510 ‡aTheory and methods of scaling.",
    "260   ‡aNew York,‡bWiley‡c[1958]"
   ],
   [
    "LDR 01068pam a2200325 a 4500",
    "001 4715614",
    "008 831025r19851958flua     b    001 0 eng  ",
    "020   ‡a0898747228",
    "020   ‡a9780898747225",
    "1001  ‡aTorgerson, Warren S.",
    "24510 ‡aTheory and methods of scaling /‡cWarren S. Torgerson.",
    "260   ‡aMalabar, Fla. :‡bR.E. Krieger Pub. Co.,‡c1985, c1958.",
    "500   ‡aReprint. Originally published: New York : J. Wiley, 1958.",
    "500   ‡aIncludes index."
   ]
  ]
 },
 "BishEtal75": {
  "fields": {
   "year": "1975",
   "title": "Discrete multivariate analysis: theory and practice",
   "publisher": "{MIT} Press",
   "author": "Y M M Bishop and S E Fienberg and P W Holland",
   "address": "Cambridge, {MA}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01216pam a2200325   4500",
    "001 2677514",
    "008 740319s1974    maua     b    001 0 eng  ",
    "020   ‡a0262021137",
    "020   ‡a9780262021135",
    "1001  ‡aBishop, Yvonne M. M.‡q(Yvonne Millicent Mahala)",
    "24510 ‡aDiscrete multivariate analysis :‡btheory and practice‡c[by] Yvonne M. M. Bishop, Stephen E. Fienberg and Paul W. Holland. With the collaboration of Richard J. Light and Frederick Mosteller.",
    "260   ‡aCambridge, Mass.,‡bMIT Press‡c[1975]",
    "7001  ‡aFienberg, Stephen E.,‡ejoint author.",
    "7001  ‡aHolland, Paul W.‡ejoint author."
   ]
  ]
 },
 "Huth13": {
  "fields": {
   "year": "2013",
   "title": "Lost art of finding our way",
   "publisher": "Belknap Press",
   "author": "John Edward Huth",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01760cam a2200325 i 4500",
    "001 17547296",
    "008 121203s2013    mauab    b    001 0 eng  ",
    "020   ‡a9780674072824",
    "1001  ‡aHuth, John Edward.",
    "24514 ‡aThe lost art of finding our way /‡cJohn Edward Huth.",
    "264 1 ‡aCambridge, Massachusetts :‡bThe Belknap Press of Harvard University Press,‡c2013."
   ]
  ]
 },
 "Paiv86": {
  "fields": {
   "year": "1986",
   "title": "Mental representations: a dual coding approach",
   "publisher": "{Oxford} {University} Press",
   "author": "A Paivio",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01313cam a2200349 a 4500",
    "001 4278322",
    "008 850725s1986    nyu      b    001 0 eng  ",
    "020   ‡a019503936X :",
    "1001  ‡aPaivio, Allan.",
    "24510 ‡aMental representations :‡ba dual coding approach /‡cAllan Paivio.",
    "260   ‡aNew York :‡bOxford University Press ;‡aOxford [Oxfordshire] :‡bClarendon Press,‡c1986.",
    "500   ‡aIncludes indexes."
   ]
  ]
 },
 "Tulv83": {
  "fields": {
   "year": "1983",
   "title": "Elements of episodic memory",
   "publisher": "{Oxford} {University} Press",
   "author": "E Tulving",
   "address": "New York, {NY}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01286pam a2200373 a 4500",
    "001 2332201",
    "008 820528s1983    enka     b    001 0 eng  ",
    "020   ‡a9780198521020",
    "020   ‡a0198521022",
    "020   ‡a9780198521259",
    "020   ‡a0198521251",
    "1001  ‡aTulving, Endel,‡d1927-",
    "24510 ‡aElements of episodic memory /‡cEndel Tulving.",
    "260   ‡aOxford [Oxfordshire] :‡bClarendon Press ;‡aNew York :‡bOxford University Press,‡c1983.",
    "500   ‡aIncludes indexes."
   ]
  ]
 },
 "Crow76": {
  "fields": {
   "year": "1976",
   "title": "Principles of learning and memory",
   "publisher": "Erlbaum",
   "author": "R G Crowder",
   "address": "Hillsdale, {NJ}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01130nam a2200337 i 4500",
    "001 3178550",
    "008 760719s1976    njua     b    001 0 eng  ",
    "020   ‡a0470150270",
    "020   ‡a9780470150276",
    "1001  ‡aCrowder, Robert G.",
    "24510 ‡aPrinciples of learning and memory /‡cRobert G. Crowder.",
    "260   ‡aHillsdale, N.J. :‡bLawrence Erlbaum Associates ;‡aNew York :‡bdistributed by the Halsted Press,‡c1976.",
    "500   ‡aIncludes indexes."
   ]
  ]
 },
 "Murd74": {
  "fields": {
   "year": "1974",
   "title": "Human memory: theory and data",
   "publisher": "Erlbaum",
   "author": "B B Murdock",
   "address": "Potomac, {MD}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01160cam a2200349   4500",
    "001 315439",
    "008 740130s1974    mdua     b    001 0 eng  ",
    "020   ‡a0470625252",
    "020   ‡a9780470625255",
    "1001  ‡aMurdock, Bennet B.‡q(Bennet Bronson)",
    "24510 ‡aHuman memory: theory and data,‡cby Bennet B. Murdock, Jr.",
    "260   ‡aPotomac, Md.,‡bLawrence Erlbaum Associates; distributed by Halsted Press Division, Wiley, New York,‡c1974."
   ]
  ]
 },
 "Kaha12": {
  "fields": {
   "year": "2012",
   "title": "Foundations of human memory",
   "publisher": "{Oxford} {University} Press",
   "author": "M J Kahana",
   "address": "New York, {NY}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01375cam a22003614a 4500",
    "001 17200404",
    "008 120308s2012    nyua     b    001 0 eng  ",
    "020   ‡a9780195333244",
    "020   ‡a0195333241",
    "1001  ‡aKahana, Michael J.",
    "24510 ‡aFoundations of human memory /‡cMichael Jacob Kahana.",
    "260   ‡aNew York :‡bOxford University Press,‡cc2012."
   ]
  ]
 },
 "HorcDhil04": {
  "fields": {
   "year": "2004",
   "title": "Neuroprosthetics theory and practice",
   "publisher": "World Scientific",
   "author": "K W Horch and G S Dhillon",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01451cam a22003977a 4500",
    "001 13613083",
    "008 040603s2004    njua     b    000 0 eng d",
    "24500 ‡aNeuroprosthetics theory and practice /‡ceditors: Kenneth W. Horch [and] Gurpreet S. Dhillon.",
    "260   ‡aRiver Edge, N.J. :‡bWorld Scientific,‡cc2004.",
    "7001  ‡aHorch, Kenneth W.",
    "7001  ‡aDhillon, Gurpreet S."
   ]
  ]
 },
 "TulvDona72": {
  "fields": {
   "year": "1972",
   "title": "Organization of memory",
   "publisher": "Academic Press",
   "author": "E Tulving and W Donaldson",
   "address": "Oxford, {UK}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01433cam a2200349   4500",
    "001 2674587",
    "008 720504s1972    nyua     b    101 0 eng  ",
    "020   ‡a0127036504",
    "020   ‡a9780127036502",
    "24500 ‡aOrganization of memory.‡cEdited by Endel Tulving and Wayne Donaldson. Contributors: Gordon H. Bower [and others]",
    "260   ‡aNew York,‡bAcademic Press,‡c1972.",
    "500   ‡a\"This book ... grew out of a two-day conference held at the University of Pittsburgh in March 1971. The conference was sponsored by the Personnel and Training Research Programs, Psychological Sciences Division, Office of Naval Research, under Contract Nonr-624(18).\"",
    "7001  ‡aTulving, Endel,‡d1927-‡eed.",
    "7001  ‡aDonaldson, Wayne,‡eed.",
    "7001  ‡aBower, Gordon H.",
    "7101  ‡aUnited States.‡bOffice of Naval Research."
   ]
  ]
 },
 "ConwEtal07": {
  "fields": {
   "year": "2007",
   "title": "Variation in working memory",
   "publisher": "{Oxford} {University} Press",
   "author": "A Conway and C Jarrold and M Kane and A Miyake and J Towse",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01744cam a22004094a 4500",
    "001 14310439",
    "008 060322s2007    enkaf    b    001 0 eng  ",
    "020   ‡a0195168631",
    "020   ‡a9780195168631",
    "24500 ‡aVariation in working memory /‡cedited by Andrew R.A. Conway ... [et al.].",
    "260   ‡aOxford ;‡aNew York :‡bOxford University Press,‡c2007.",
    "7001  ‡aConway, Andrew R. A."
   ]
  ]
 },
 "RiekEtal97": {
  "fields": {
   "year": "1997",
   "title": "Spikes: exploring the neural code",
   "publisher": "{MIT} Press",
   "author": "F Rieke and D Warland and R {de Ruyter van Steveninck} and W Bialek",
   "address": "Cambridge, {MA}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01369cam a2200373 a 4500",
    "001 2562525",
    "008 951019s1997    maua     b    001 0 eng  ",
    "020   ‡a0262181746",
    "020   ‡a9780262181747",
    "24500 ‡aSpikes :‡bexploring the neural code /‡cFred Rieke ... [et al.].",
    "260   ‡aCambridge, Mass. :‡bMIT Press,‡cc1997.",
    "500   ‡a\"A Bradford book.\"",
    "7001  ‡aRieke, Fred."
   ]
  ]
 },
 "Semo23": {
  "fields": {
   "year": "1923",
   "title": "Mnemic psychology",
   "publisher": "George, Allen, and Unwin",
   "author": "R W Semon",
   "address": "London, {UK}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01108cam a22003251  4500",
    "001 9197683",
    "008 780706s1923    enka          000 0 eng  ",
    "1001  ‡aSemon, Richard Wolfgang,‡d1859-1918.",
    "24510 ‡aMnemic psychology,‡cby Richard Semon. Translated from the German by Bella Duffy, with an introduction by Vernon Lee [pseud.]",
    "260   ‡aLondon,‡bG. Allen & Unwin, ltd.‡c[1923].",
    "7001  ‡aDuffy, Bella,‡etr.",
    "7001  ‡aLee, Vernon,‡d1856-1935."
   ]
  ]
 },
 "TalaTour88": {
  "fields": {
   "year": "1988",
   "title": "Co-planar stereotaxic atlas of the human brain",
   "publisher": "Verlag",
   "author": "J Talairach and P Tournoux",
   "address": "Stuttgart, Germany",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01941cam a2200445 a 4500",
    "001 16107192",
    "008 100225s1988    gw a     b    001 u eng  ",
    "020   ‡a0865772932",
    "020   ‡a9780865772939",
    "020   ‡a3137117011",
    "020   ‡a9783137117018",
    "1001  ‡aTalairach, J.‡q(Jean)",
    "24510 ‡aCo-planar stereotaxic atlas of the human brain :‡b3-dimensional proportional system : an approach to cerebral imaging /‡cby Jean Talairach and Pierre Tournoux ; translated by Mark Rayport.",
    "260   ‡aStuttgart ;‡aNew York :‡bGeorg Thieme,‡c1988.",
    "500   ‡a\"Translated from the French original manuscript by Mark Rayport\"--T.p. verso.",
    "7001  ‡aTournoux, Pierre."
   ]
  ]
 },
 "Munn50": {
  "fields": {
   "year": "1950",
   "title": "Handbook of psychological research on the rat; an introduction to animal psychology",
   "publisher": "Houghton Mifflin",
   "author": "N L Munn",
   "address": "Boston, {MA}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01236cam a22003611  4500",
    "001 6021786",
    "008 711019r19501933maua     b    000 0 eng  ",
    "1001  ‡aMunn, Norman Leslie,‡d1902-",
    "24510 ‡aHandbook of psychological research on the rat;‡ban introduction to animal psychology.",
    "260   ‡aBoston,‡bHoughton Mifflin‡c[1950]",
    "500   ‡aFirst ed. published in 1933 under title: An introduction to animal psychology."
   ]
  ]
 },
 "DudaEtal01": {
  "fields": {
   "year": "2001",
   "title": "Pattern classification, second edition",
   "publisher": "Wiley",
   "author": "R O Duda and P E Hart and D G Stork",
   "address": "New York, {NY}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01899cam a22004094a 4500",
    "001 13474594",
    "008 040130s2004    njua     b    001 0 eng  ",
    "020   ‡a0471429775",
    "020   ‡a9780471429777",
    "1001  ‡aStork, David G.",
    "24510 ‡aComputer manual in MATLAB to accompany Pattern classification, second edition /‡cDavid G. Stork, Elad Yom-Tov.",
    "260   ‡aHoboken, N.J. :‡bJohn Wiley & Sons,‡cc2004.",
    "500   ‡a\"A Wiley-Interscience publication.\"",
    "7001  ‡aYom-Tov, Elad.",
    "7001  ‡aDuda, Richard O.‡tPattern classification.‡s2nd ed."
   ]
  ]
 },
 "Wear16": {
  "fields": {
   "year": "2016",
   "title": "The psychology of time perception",
   "publisher": "Springer",
   "author": "J Wearden",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 03517cam a22005535i 4500",
    "001 22023443",
    "008 160609s2016    xxk|||| o    |||| 0|eng  ",
    "020   ‡a9781137408839",
    "1001  ‡aWearden, John,‡eauthor.",
    "24514 ‡aThe Psychology of Time Perception /‡cby John Wearden.",
    "250   ‡a1st ed. 2016.",
    "264 1 ‡aLondon :‡bPalgrave Macmillan UK :‡bImprint: Palgrave Macmillan,‡c2016.",
    "77608 ‡iPrint version:‡tThe psychology of time perception‡w(DLC)  2016938827",
    "77608 ‡iPrinted edition:‡z9781137408822",
    "77608 ‡iPrinted edition:‡z9781349681280",
    "77608 ‡iPrinted edition:‡z9781349681297"
   ]
  ]
 },
 "Rams07": {
  "fields": {
   "year": "2007",
   "title": "Representation reconsidered",
   "publisher": "Cambridge {University} Press",
   "author": "W M Ramsey",
   "address": "Cambridge, {UK}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01857cam a2200349 a 4500",
    "001 14703968",
    "008 070119s2007    enka     b    001 0 eng  ",
    "020   ‡a9780521859875",
    "020   ‡a0521859875",
    "1001  ‡aRamsey, William M.,‡d1960-",
    "24510 ‡aRepresentation reconsidered /‡cWilliam M. Ramsey.",
    "260   ‡aCambridge ;‡aNew York :‡bCambridge University Press,‡c2007."
   ]
  ]
 },
 "MillEtal60": {
  "fields": {
   "year": "1960",
   "title": "Plans and the structure of behavior",
   "publisher": "Holt, Rinehart, and Winston",
   "author": "G A Miller and E Galanter and K H Pribram",
   "address": "New York, {NY}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 00973cam a22003011  4500",
    "001 4530370",
    "008 720601s1960    nyua     b    000 0 eng  ",
    "1001  ‡aMiller, George A.‡q(George Armitage),‡d1920-2012.",
    "24510 ‡aPlans and the structure of behavior‡c[by] George A. Miller, Eugene Galanter [and] Karl H. Pribram.",
    "260   ‡aNew York,‡bHolt‡c[1960]"
   ],
   [
    "LDR 01353cam a2200373 a 4500",
    "001 1462216",
    "008 860923r19861960nyua     b    001 0 eng  ",
    "020   ‡a0937431001 :",
    "020   ‡a9780937431009",
    "1001  ‡aMiller, George A.‡q(George Armitage),‡d1920-2012.",
    "24510 ‡aPlans and the structure of behavior /‡cGeorge A. Miller, Eugene Galanter, Karl H. Pribram ; with a foreword by Donald E. Broadbent.",
    "260   ‡aNew York :‡bAdams-Bannister-Cox,‡cc1986.",
    "500   ‡aReprint. Originally published: New York : Holt, Rinehart and Winston, 1960.",
    "7001  ‡aGalanter, Eugene.",
    "7001  ‡aPribram, Karl H.,‡d1919-"
   ]
  ]
 },
 "Koff35": {
  "fields": {
   "year": "1935",
   "title": "Principles of {G}estalt psychology",
   "publisher": "Harcourt, Brace, and World",
   "author": "K Koffka",
   "address": "New York, {NY}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01156cam a22003251  4500",
    "001 6423590",
    "008 760716s1935    nyuag         000 0 eng  ",
    "1001  ‡aKoffka, Kurt,‡d1886-1941.",
    "24500 ‡aPrinciples of Gestalt psychology,‡cby K. Koffka.",
    "260   ‡aLondon,‡bK. Paul, Trench, Trubner;‡aNew York,‡bHarcourt, Brace,‡c1935.",
    "500   ‡a\"Printed in the United States of America.\""
   ],
   [
    "LDR 01143cam a22003371  4500",
    "001 7827792",
    "008 740628s1935    nyuag    b    000 0 eng  ",
    "1001  ‡aKoffka, Kurt,‡d1886-1941.",
    "24510 ‡aPrinciples of gestalt psychology,‡cby K. Koffka ...",
    "260   ‡aNew York,‡bHarcourt, Brace and Company,‡c1935.",
    "500   ‡a\"First edition.\""
   ]
  ]
 },
 "Fodo83": {
  "fields": {
   "year": "1983",
   "title": "The modularity of mind",
   "publisher": "{MIT} Press",
   "author": "J A Fodor",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01162cam a2200361 a 4500",
    "001 4697972",
    "008 821221s1983    mau      b    000 0 eng  ",
    "020   ‡a0262060841",
    "020   ‡a0262560259",
    "020   ‡a9780262060844",
    "020   ‡a9780262560252",
    "1001  ‡aFodor, Jerry A.",
    "24514 ‡aThe modularity of mind :‡ban essay on faculty psychology /‡cJerry A. Fodor.",
    "260   ‡aCambridge, Mass. :‡bMIT Press,‡cc1983.",
    "500   ‡a\"A Bradford book.\""
   ]
  ]
 },
 "Scha01": {
  "fields": {
   "year": "2001",
   "title": "Forgotten ideas, neglected pioneers: {Richard} {Semon} and the story of memory",
   "publisher": "Psychology Press",
   "author": "D L Schacter",
   "address": "New York, {NY}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01327cam a2200313 a 4500",
    "001 12288051",
    "008 010124s2001    paua     b    001 0beng  ",
    "020   ‡a184169052X",
    "1001  ‡aSchacter, Daniel L.",
    "24510 ‡aForgotten ideas, neglected pioneers :‡bRichard Semon and the story of memory /‡cDaniel L. Schacter.",
    "260   ‡aPhiladelphia, PA :‡bPsycholoby Press,‡cc2001."
   ]
  ]
 },
 "Feyn65": {
  "fields": {
   "year": "1965",
   "title": "The character of physical law",
   "publisher": "{MIT} Press",
   "author": "Richard Feynman",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01028cam a22002891  4500",
    "001 2644162",
    "008 710924s1965    maua          000 0 eng  ",
    "1001  ‡aFeynman, Richard P.‡q(Richard Phillips),‡d1918-1988.",
    "24514 ‡aThe character of physical law‡c[by] Richard Feynman.",
    "260   ‡aCambridge,‡bM.I.T. Press‡c[1965]"
   ],
   [
    "LDR 01286cam a2200313 a 4500",
    "001 12541358",
    "008 010921r19941965nyua          000 0 eng  ",
    "020   ‡a0679601279",
    "020   ‡a9780679601272",
    "1001  ‡aFeynman, Richard P.‡q(Richard Phillips),‡d1918-1988.",
    "24514 ‡aThe character of physical law /‡cRichard Feynman ; introduction by James Gleick.",
    "250   ‡aModern Library ed.",
    "260   ‡aNew York :‡bModern Library,‡c1994.",
    "500   ‡a\"Originally published in hardcover by the British Broadcasting Corporation in 1965 and in paperback by M.I.T. Press in 1967\"--T.p. verso."
   ],
   [
    "LDR 01058cam a22002771  4500",
    "001 762568",
    "008 710521s1965    enka          000 0 eng  ",
    "1001  ‡aFeynman, Richard P.‡q(Richard Phillips),‡d1918-1988.",
    "24514 ‡aThe character of physical law‡c[by] Richard Feynman.",
    "260   ‡a[London]‡bBritish Broadcasting Corp.‡c[1965]",
    "500   ‡a\"A series of lectures recorded by the BBC at Cornell University, U.S.A., and televised on BBC-2.\"",
    "500   ‡aLectures [originally] presented as the Messenger lectures at Cornell University.\""
   ],
   [
    "LDR 02934cam a2200349 i 4500",
    "001 19250155",
    "008 160823t20172017maua          000 0 eng c",
    "020   ‡a9780262533416",
    "020   ‡a0262533413",
    "1001  ‡aFeynman, Richard P.‡q(Richard Phillips),‡d1918-1988,‡eauthor.",
    "24514 ‡aThe character of physical law /‡cRichard Feynman with new foreword by Frank Wilczek.",
    "264 1 ‡aCambridge, Massachusetts ;‡aLondon, England :‡bThe MIT Press,‡c[2017]",
    "264 4 ‡c©2017",
    "7001  ‡aWilczek, Frank,‡ewriter of foreword."
   ],
   [
    "LDR 01111cgm a2200277u  4500",
    "001 10463776",
    "008 860513s1965    xx ---            m|eng  ",
    "24500 ‡aProbability & uncertainty:‡bthe quantum mechanical view of nature‡h(Motion picture)",
    "260   ‡aBritish Broadcasting Corp.‡aTelevision,‡aLondon,‡b1964. Released in the U. S. by Education Development Center,‡c1965?",
    "7001  ‡aFeynman, Richard P.‡q(Richard Phillips),‡d1918-1988.‡tCharacter of physical law.",
    "7102  ‡aBritish Broadcasting Corporation.‡bTelevision Service.",
    "7102  ‡aEducation Development Center."
   ]
  ]
 },
 "Carr93": {
  "fields": {
   "year": "1993",
   "title": "Human cognitive abilities: a survey of factor-analytic studies",
   "publisher": "Cambridge {University} Press",
   "author": "J D Carroll",
   "address": "New York, {NY}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01723cam a2200409 a 4500",
    "001 4395028",
    "008 920318s1993    enka     b    001 0 eng  ",
    "020   ‡a0521382750",
    "020   ‡a0521387124",
    "020   ‡a9780521382755",
    "020   ‡a9780521387125",
    "1001  ‡aCarroll, John B.‡q(John Bissell),‡d1916-2003.",
    "24510 ‡aHuman cognitive abilities :‡ba survey of factor-analytic studies /‡cJohn B. Carroll.",
    "260   ‡aCambridge ;‡aNew York :‡bCambridge University Press,‡c1993."
   ]
  ]
 },
 "HawkBlak05": {
  "fields": {
   "year": "2005",
   "title": "On intelligence",
   "publisher": "St. Martin's Griffin",
   "author": "J Hawkins and S Blakeslee",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01829cam a22004214a 4500",
    "001 13593104",
    "008 040514s2004    nyu      b    001 0 eng  ",
    "020   ‡a0805074562",
    "020   ‡a9780805074567",
    "1001  ‡aHawkins, Jeff,‡d1957-",
    "24510 ‡aOn intelligence /‡cJeff Hawkins with Sandra Blakeslee.",
    "250   ‡a1st ed.",
    "260   ‡aNew York :‡bTimes Books,‡c2004.",
    "7001  ‡aBlakeslee, Sandra."
   ],
   [
    "LDR 03719nam a22004818i 4500",
    "001 in00024508826",
    "008 260313t20262026flu     ob    001 0 eng  ",
    "020   ‡a9781003683308",
    "1001  ‡aHawkins, Jane,‡d1954-‡eauthor‡4aut‡4http://id.loc.gov/vocabulary/relators/aut",
    "24510 ‡aMathematics for artificial intelligence /‡cJane Hawkins.",
    "250   ‡aFirst edition.",
    "264 1 ‡aBoca Raton, FL ;‡aAbingdon, Oxon :‡bCRC Press,‡c2026.",
    "264 4 ‡c©2026",
    "7761  ‡iPrint version:‡tMathematics for artificial intelligence‡bFirst edition.‡dBoca Raton, FL ; Abingdon, Oxon : CRC Press, 2026‡z9781041161981‡w(DLC) 2025045267"
   ],
   [
    "LDR 03905cam a2200481 i 4500",
    "001 in00024496027",
    "008 260313t20262026flua     b    001 0 eng  ",
    "020   ‡a9781041161981",
    "020   ‡a9781041161974",
    "1001  ‡aHawkins, Jane,‡d1954-‡eauthor‡4aut‡4http://id.loc.gov/vocabulary/relators/aut",
    "24510 ‡aMathematics for artificial intelligence /‡cJane Hawkins.",
    "250   ‡aFirst edition.",
    "264 1 ‡aBoca Raton, FL ;‡aAbingdon, Oxon :‡bCRC Press,‡c2026.",
    "264 4 ‡c©2026",
    "7761  ‡iOnline version‡4http://id.loc.gov/entities/relationships/onlineversion‡aHawkins, Jane, 1954-‡tMathematics for artificial intelligence‡bFirst edition‡dBoca Raton, FL; Abingdon, Oxon: CRC Press, 2026‡w(DLC)2025045268‡z9781003683308"
   ],
   [
    "LDR 03810cam a22003618i 4500",
    "001 21691444",
    "008 200826s2021    nyu      b    001 0 eng  ",
    "020   ‡a9781541675810",
    "1001  ‡aHawkins, Jeff,‡d1957-‡eauthor.",
    "24512 ‡aA thousand brains :‡ba new theory of intelligence /‡cJeff Hawkins ; with a foreword by Richard Dawkins.",
    "250   ‡aFirst edition.",
    "264 1 ‡aNew York :‡bBasic Books,‡c2021."
   ],
   [
    "LDR 01636cam a2200397 a 4500",
    "001 4962787",
    "008 970619s1997    azua     b    000 0 eng  ",
    "020   ‡a1569760756",
    "020   ‡a9781569760758",
    "1001  ‡aBowen, Jean,‡d1935-",
    "24510 ‡aSquare pegs :‡bbuilding success in school and life through multiple intelligences /‡cJean Bowen, Marianne Hawkins, Carol King.",
    "260   ‡aTucson, AZ :‡bZephyr Press,‡cc1997.",
    "7001  ‡aHawkins, Marianne,‡d1944-",
    "7001  ‡aKing, Carol,‡d1952-"
   ]
  ]
 },
 "Mitc96": {
  "fields": {
   "year": "1996",
   "title": "An introduction to genetic algorithms",
   "publisher": "{MIT} Press",
   "author": "M Mitchell",
   "address": "Cambridge, {MA}",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01427cam a2200373 a 4500",
    "001 2087853",
    "008 950623s1996    maua     b    001 0 eng  ",
    "020   ‡a0262133164",
    "020   ‡a9780262133166",
    "1001  ‡aMitchell, Melanie‡c(Computer scientist)",
    "24513 ‡aAn introduction to genetic algorithms /‡cMelanie Mitchell.",
    "260   ‡aCambridge, Mass. :‡bMIT Press,‡cc1996.",
    "500   ‡a\"A Bradford book\"."
   ]
  ]
 },
 "Fish25": {
  "fields": {
   "year": "1925",
   "title": "Statistical methods for research workers",
   "publisher": "Oliver and Boyd",
   "author": "R A Fisher",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 00871cam a2200265u  4500",
    "001 10139950",
    "008 830624s1925    stka          000 0 eng  ",
    "1001  ‡aFisher, Ronald Aylmer,‡cSir,‡d1890-",
    "24510 ‡aStatistical methods for research workers,",
    "260   ‡aEdinburgh,‡aLondon,‡bOliver and Boyd,‡c1925."
   ]
  ]
 },
 "Kint70": {
  "fields": {
   "year": "1970",
   "title": "Learning, memory, and conceptual processes",
   "publisher": "Wiley",
   "author": "Kintsch",
   "ENTRYTYPE": "book"
  },
  "records": [
   [
    "LDR 01093cam a2200337   4500",
    "001 1764054",
    "008 700427s1970    nyua     b    001 0 eng  ",
    "020   ‡a0471480703",
    "020   ‡a9780471480709",
    "1001  ‡aKintsch, Walter,‡d1932-",
    "24510 ‡aLearning, memory, and conceptual processes.",
    "260   ‡aNew York,‡bWiley‡c[1970]",
    "500   ‡aSecond ed. published (c1977) under title: Memory and cognition."
   ]
  ]
 }
}
""")


def marc(lines):
    record = ET.Element(M + 'record')
    for line in lines:
        tag, rest = line[:3], line[4:]
        if tag == 'LDR':
            ET.SubElement(record, M + 'leader').text = rest
        elif tag in ('001', '008'):
            ET.SubElement(record, M + 'controlfield', tag=tag).text = rest
        else:
            node = ET.SubElement(record, M + 'datafield', tag=tag, ind1=line[3], ind2=line[4])
            for part in line[6:].split('‡')[1:]:
                ET.SubElement(node, M + 'subfield', code=part[0]).text = part[1:]
    return record


def derived(key, fields=None, edit=None):
    """A complete SRU envelope around the derived records, echoing the query."""
    case = deepcopy(DERIVED[key])
    fields = dict(case['fields'], **(fields or {}))
    fields = {k: x for k, x in fields.items() if x is not None}
    records = [marc(lines) for lines in case['records']]
    if edit:
        edit(records)
    root = ET.Element(S + 'searchRetrieveResponse')
    ET.SubElement(root, S + 'version').text = '1.1'
    ET.SubElement(root, S + 'numberOfRecords').text = str(len(records))
    wrappers = ET.SubElement(root, S + 'records')
    for position, record in enumerate(records, 1):
        wrapper = ET.SubElement(wrappers, S + 'record')
        ET.SubElement(wrapper, S + 'recordSchema').text = 'marcxml'
        ET.SubElement(wrapper, S + 'recordPacking').text = 'xml'
        ET.SubElement(wrapper, S + 'recordData').append(record)
        ET.SubElement(wrapper, S + 'recordPosition').text = str(position)
    echo = ET.SubElement(root, S + 'echoedSearchRetrieveRequest')
    ET.SubElement(echo, S + 'query').text = cr.search_query(fields)
    xml = ET.tostring(root, encoding='unicode')
    return fields, {'url': 'https://lx2.loc.gov/sru/lcdb?operation=searchRetrieve', 'raw_xml': xml,
                    'retrieved_at': '2026-09-15T00:00:00+00:00',
                    'document_sha256': hashlib.sha256(xml.encode()).hexdigest()}


def status(key, fields=None, edit=None):
    return cr.assess_catalogue(*derived(key, fields, edit))['status']


def verified(key, fields=None, record_id=None, edit=None):
    fields, response = derived(key, fields, edit)
    result = cr.assess_catalogue(fields, response)
    assert result['status'] == 'metadata_verified', [c['issues'] for c in result['candidates']]
    assert record_id is None or result['accepted_record_id'] == record_id
    assert cr.valid_catalogue_approval(result)
    assert cr.reassess_saved_catalogue(fields, result) == result
    return result


def field(record, tag):
    return next(n for n in record.findall(M + 'datafield') if n.get('tag') == tag)


# (a) Bracketed / copyright dates bound to 008 --------------------------------

@pytest.mark.parametrize('key,record_id', [('GreeSwet66', '1697383'), ('Torg58', '4529830')])
def test_bracketed_year_equal_to_008_verifies_and_reissue_does_not_compete(key, record_id):
    result = verified(key, record_id=record_id)
    reissue = [c for c in result['candidates'] if c['record_id'] != record_id]
    assert reissue and all('Not a competing edition' in ' '.join(c['issues']) for c in reissue)


@pytest.mark.parametrize('value', ['[1965]', '[1966?]', '[1966-67]', '1966, c1965', '[ca. 1966]', '[1966'])
def test_bracketed_year_must_equal_the_008_year_exactly(value):
    def edit(records):
        for sub in field(records[1], '260').findall(M + 'subfield'):
            if sub.get('code') == 'c':
                sub.text = value
    assert status('GreeSwet66', edit=edit) == 'needs_review'


def test_real_bracketed_year_disagreeing_with_008_stays_unresolved():
    # BishEtal75: 008 s1974 but 260c '[1975]'; the plan's negative control.
    assert status('BishEtal75') == 'needs_review'
    assert status('BishEtal75', {'year': '1974'}) == 'needs_review'


def test_same_year_unparseable_reissue_still_blocks():
    # records[0] is the Krieger reissue (008 r19741966); recoded as a 1966
    # record it can no longer be excluded as another year, so it blocks.
    def edit(records):
        node = records[0].find(M + "controlfield[@tag='008']")
        node.text = node.text[:6] + 's1966    ' + node.text[15:]
    assert status('GreeSwet66', edit=edit) == 'needs_review'


# (b) RDA 264 publication statements ------------------------------------------

def test_rda_264_publication_statement_verifies_with_the_exact_publisher():
    verified('Huth13', {'title': 'The lost art of finding our way',
                        'publisher': 'The Belknap Press of Harvard University Press'}, '17547296')
    assert status('Huth13') == 'needs_review'  # cited 'Belknap Press' / title without 'The'


@pytest.mark.parametrize('change', ['second-264-1', '264-0', 'plus-260', 'only-copyright'])
def test_rda_264_ambiguity_is_rejected(change):
    fields = {'title': 'The lost art of finding our way', 'publisher': 'The Belknap Press of Harvard University Press'}
    def edit(records):
        node = field(records[0], '264')
        if change == 'second-264-1':
            records[0].append(deepcopy(node))
        elif change == '264-0':
            node.set('ind2', '0')
        elif change == 'plus-260':
            extra = deepcopy(node); extra.set('tag', '260'); extra.set('ind2', ' '); records[0].append(extra)
        else:
            node.set('ind2', '4')
    assert status('Huth13', fields, edit) == 'needs_review'


# (c) Two-publisher imprints: a place only with its own publisher -------------

def test_dual_imprint_pairs_each_place_with_its_own_publisher():
    verified('Paiv86', record_id='4278322')
    verified('Tulv83', {'address': 'New York'}, '2332201')
    verified('Tulv83', {'publisher': 'Clarendon Press', 'address': 'Oxford'}, '2332201')
    # Never mix one publisher's place with the other publisher.
    assert status('Tulv83', {'address': 'Oxford'}) == 'needs_review'
    assert status('Tulv83', {'publisher': 'Clarendon Press', 'address': 'New York'}) == 'needs_review'
    assert status('Tulv83', {'publisher': 'Oxford University Press ; Clarendon Press'}) == 'needs_review'


# (d) Distributor clauses ---------------------------------------------------

def test_distributor_clause_is_not_a_publisher():
    verified('Crow76', {'publisher': 'Lawrence Erlbaum Associates', 'address': 'Hillsdale, NJ'}, '3178550')
    assert status('Crow76', {'publisher': 'Halsted Press'}) == 'needs_review'
    assert status('Crow76', {'publisher': 'Lawrence Erlbaum Associates', 'address': 'New York'}) == 'needs_review'
    # Inline 'publisher; distributed by ...' in a single $b (Murd74), with the
    # printed 'Jr.' suffix and the coded Maryland place.
    verified('Murd74', {'author': 'Murdock, Jr., B B', 'publisher': 'Lawrence Erlbaum Associates',
                        'address': 'Potomac, MD'})
    assert status('Murd74', {'publisher': 'Lawrence Erlbaum Associates', 'address': 'Potomac, MD'}) == 'needs_review'
    assert status('Murd74', {'author': 'Murdock, Jr., B B', 'publisher': 'Halsted Press',
                             'address': 'Potomac, MD'}) == 'needs_review'


def test_a_distributor_only_statement_leaves_no_publisher():
    def edit(records):
        node = field(records[0], '260')
        for sub in list(node):
            if sub.get('code') == 'b' and 'Erlbaum' in sub.text:
                node.remove(sub)
            if sub.get('code') == 'a' and 'Hillsdale' in sub.text:
                node.remove(sub)
    assert status('Crow76', {'publisher': 'Halsted Press', 'address': 'New York'}, edit) == 'needs_review'


# (e) No statement of responsibility ------------------------------------------

@pytest.mark.parametrize('key,record_id', [('Broa58', '4529843'), ('Fish25', '10139950')])
def test_single_main_entry_without_245c_supplies_the_byline(key, record_id):
    verified(key, record_id=record_id)


@pytest.mark.parametrize('change', ['added-heading', 'no-given', 'wrong-initial', 'extra-initial'])
def test_absent_245c_requires_exactly_one_complete_heading(change):
    fields = {}
    def edit(records):
        if change == 'added-heading':
            node = ET.SubElement(records[0], M + 'datafield', tag='700', ind1='1', ind2=' ')
            ET.SubElement(node, M + 'subfield', code='a').text = 'Other, Anne.'
        elif change == 'no-given':
            field(records[0], '100').find(M + "subfield[@code='a']").text = 'Broadbent.'
    if change == 'wrong-initial':
        fields = {'author': 'D F Broadbent'}
    elif change == 'extra-initial':
        fields = {'author': 'D E A Broadbent'}
    assert status('Broa58', fields, edit) == 'needs_review'


def test_citation_without_given_names_is_not_verified_by_a_lone_heading():
    assert status('Kint70') == 'needs_review'  # cited 'Kintsch'
    verified('Kint70', {'author': 'W Kintsch'})


# (f) Full printed names confirm cited initials --------------------------------

def test_full_printed_given_names_confirm_initials():
    verified('Kaha12', record_id='17200404')
    verified('Kaha12', {'author': 'Michael Jacob Kahana'})
    verified('Kaha12', {'author': 'Michael J Kahana'})
    for author in ('M K Kahana', 'M Kahana', 'Michael Kahana', 'M J A Kahana', 'Michael James Kahana'):
        assert status('Kaha12', {'author': author}) == 'needs_review', author


def test_heading_qualifier_in_parentheses_is_not_a_role():
    verified('Mitc96', record_id='2087853')  # 'Mitchell, Melanie $c(Computer scientist)'
    def edit(records):
        ET.SubElement(field(records[0], '100'), M + 'subfield', code='c').text = 'Jr.'
    assert status('Mitc96', edit=edit) == 'needs_review'


def test_first_author_heading_only_accepts_simple_later_printed_names():
    verified('MillEtal60', {'publisher': 'Holt'}, '4530370')
    assert status('MillEtal60', {'publisher': 'Holt', 'author': 'G A Miller and E Galanter'}) == 'needs_review'
    assert status('MillEtal60', {'publisher': 'Holt', 'author': 'G A Miller and E Galanter and K Pribram'}) == 'needs_review'
    def particle(records):
        sub = field(records[0], '245').find(M + "subfield[@code='c']")
        sub.text = sub.text.replace('Karl H. Pribram', 'Karl H. van Pribram')
    assert status('MillEtal60', {'publisher': 'Holt', 'author': 'G A Miller and E Galanter and K H {van Pribram}'},
                  particle) == 'needs_review'


# (g) Edited volumes ------------------------------------------------------------

def test_edited_volume_confirms_the_full_ordered_editor_list():
    result = verified('HorcDhil04', {'author': None, 'editor': 'K W Horch and G S Dhillon'}, '13613083')
    assert result['candidates'][0]['evidence']['editor']['match']
    assert 'author' not in result['candidates'][0]['evidence']
    for editor in ('G S Dhillon and K W Horch', 'K W Horch', 'K W Horch and G S Dhillon and A Other', 'K Horch and G S Dhillon'):
        assert status('HorcDhil04', {'author': None, 'editor': editor}) == 'needs_review', editor
    # Editors are not authors.
    assert status('HorcDhil04') == 'needs_review'
    assert status('HorcDhil04', {'editor': 'K W Horch and G S Dhillon'}) == 'needs_review'


def test_edited_volume_with_contributors_and_sponsor():
    verified('TulvDona72', {'author': None, 'editor': 'E Tulving and W Donaldson', 'address': 'New York'}, '2674587')
    assert status('TulvDona72', {'author': None, 'editor': 'E Tulving and W Donaldson and G H Bower',
                                 'address': 'New York'}) == 'needs_review'
    def author_role(records):
        node = [n for n in records[0].findall(M + 'datafield') if n.get('tag') == '710'][0]
        ET.SubElement(node, M + 'subfield', code='e').text = 'author.'
    assert status('TulvDona72', {'author': None, 'editor': 'E Tulving and W Donaldson', 'address': 'New York'},
                  author_role) == 'needs_review'
    def contributor_as_editor(records):
        node = [n for n in records[0].findall(M + 'datafield') if n.get('tag') == '700'][2]
        ET.SubElement(node, M + 'subfield', code='e').text = 'editor.'
    assert status('TulvDona72', {'author': None, 'editor': 'E Tulving and W Donaldson', 'address': 'New York'},
                  contributor_as_editor) == 'needs_review'


def test_editor_only_citation_is_discoverable_by_its_first_editor():
    assert cr.search_query({'title': 'Organization of memory', 'editor': 'E Tulving and W Donaldson'}) \
        == 'dc.title="organization of memory" and dc.author="tulving"'


# Negative controls that must stay rejected ------------------------------------

@pytest.mark.parametrize('key,fields', [
    ('ConwEtal07', {'author': None, 'editor': 'A R A Conway and C Jarrold and M J Kane and A Miyake and J N Towse'}),
    ('RiekEtal97', {}),
    ('Semo23', {'publisher': 'G. Allen & Unwin, ltd', 'address': 'London'}),
    ('TalaTour88', {'publisher': 'Georg Thieme', 'address': 'Stuttgart'}),
    ('Munn50', {}),
    ('DudaEtal01', {}),
    ('Wear16', {'publisher': 'Palgrave Macmillan UK'}),
    ('HawkBlak05', {}),
])
def test_et_al_translations_reissues_other_works_and_ebooks_stay_rejected(key, fields):
    assert status(key, fields) == 'needs_review'


# Coded jurisdictions ------------------------------------------------------------

def test_england_code_supports_uk_only_for_the_first_place():
    result = verified('Rams07', record_id='14703968')
    assert result['candidates'][0]['evidence']['address']['source_place_code'] == 'enk'
    for address in ('Cambridge, MA', 'New York, UK', 'Cambridge, USA'):
        assert status('Rams07', {'address': address}) == 'needs_review', address


# Pre-ISBD title punctuation ------------------------------------------------------

def test_terminal_comma_title_is_reparsed_and_other_imprint_does_not_match():
    fields = {'title': 'Principles of {G}estalt psychology', 'publisher': 'Harcourt, Brace and Company'}
    result = verified('Koff35', fields, '7827792')
    assert result['candidates'][1]['record']['title'] == ['Principles of gestalt psychology']
    assert status('Koff35') == 'needs_review'  # cited 'Harcourt, Brace, and World'


# Correction proposals (read-only) --------------------------------------------------

def proposal(key):
    fields, response = derived(key)
    return cr.propose_corrections(fields, cr.assess_catalogue(fields, response))


def changes(key):
    return {(c['field'], c['before'], c['after'], c['rule']) for c in proposal(key)['proposal']['changes']}


def test_proposals_from_one_same_edition_record():
    assert changes('HorcDhil04') == {('author', 'K W Horch and G S Dhillon', None, 'edited-volume-author-to-editor'),
                                     ('editor', None, 'K W Horch and G S Dhillon', 'edited-volume-author-to-editor')}
    assert changes('Fodo83') == {('title', 'The modularity of mind', 'The modularity of mind: an essay on faculty psychology',
                                  'title-add-catalogue-subtitle')}
    assert changes('Carr93') == {('author', 'J D Carroll', 'J B Carroll', 'byline-given-names'),
                                 ('address', 'New York, {NY}', 'New York', 'address-state-or-country-suffix')}
    assert changes('Crow76') == {('publisher', 'Erlbaum', 'Lawrence Erlbaum Associates', 'publisher-name-form')}
    assert changes('Kint70') == {('author', 'Kintsch', 'W Kintsch', 'byline-given-names')}


@pytest.mark.parametrize('key,group', [
    ('Scha01', 'catalogue-transcription-typo'),        # LC 'Psycholoby Press'
    ('Feyn65', 'several-plausible-editions'),          # MIT and BBC 1965 printings
    ('HawkBlak05', 'catalogue-different-edition-or-work'),  # 2004 Times Books vs cited 2005 paperback
    ('Munn50', 'catalogue-unparsed'),                  # only a 1950 reissue of the 1933 book
    ('RiekEtal97', 'catalogue-unparsed'),              # '[et al.]'
    ('DudaEtal01', 'catalogue-only-other-editions'),   # the MATLAB companion volume
])
def test_no_proposal_without_a_unique_same_edition_record(key, group):
    assert proposal(key) == {'group': group, 'reason': proposal(key)['reason']}


def test_proposals_never_change_both_year_and_publisher_or_more_than_two_fields():
    # Mutating the record so three fields differ removes the proposal.
    fields, response = derived('Crow76', {'year': '1976', 'title': 'Principles of learning and memory',
                                          'author': 'R Crowder', 'address': 'Boston, {MA}'})
    result = cr.assess_catalogue(fields, response)
    assert 'group' in cr.propose_corrections(fields, result)
