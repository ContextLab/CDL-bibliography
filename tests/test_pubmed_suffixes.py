"""PubMed full-name suffixes survive mapping, edits, and portable caching."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bibcheck'))
import verification as v
from auto_review import epmc_record, pubmed_author_suffix, reassess, select_result


@pytest.mark.parametrize('tail', ['Jr', 'Sr', 'II', 'III', 'IV', 'Jr.'])
def test_explicit_full_name_suffix(tail):
    person = {'lastName':'Smith', 'firstName':'Alice B', 'initials':'AB', 'fullName':'Smith AB ' + tail}
    assert pubmed_author_suffix(person) == tail.rstrip('.')


def test_suffix_extraction_requires_the_structured_name_prefix():
    assert not pubmed_author_suffix({'lastName':'Jones','initials':'AB','fullName':'Smith AB Jr'})
    assert not pubmed_author_suffix({'lastName':'Smith','initials':'AB','fullName':'Smith AB Other'})
    with pytest.raises(ValueError, match='Conflicting'):
        pubmed_author_suffix({'lastName':'Smith','initials':'AB','fullName':'Smith AB Jr','suffix':'Sr'})


def setup(tmp_path):
    bib = tmp_path/'source.bib'
    bib.write_text('@article{Test,\nAuthor = {A Smith},\nTitle = {A finding},\nYear = {2020},\nJournal = {Journal},\nVolume = {1},\nPages = {1--2}}')
    entry = v.load_entries(bib)['Test']
    record = {'DOI':'10.1234/test','type':'journal-article','title':['A finding'],
              'author':[{'given':'Alice','family':'Smith'}], 'published':{'date-parts':[[2020]]},
              'container-title':['Journal'],'volume':'1','page':'1-2','ISSN':['1234-5678']}
    evidence, issues = v.compare_record(entry['fields'],record)
    assert not issues
    primary = {'source':'crossref','doi':record['DOI'],'record':record,'evidence':evidence,'issues':[]}
    raw = {'source':'MED','id':'123','doi':record['DOI'],'title':'A finding.',
           'authorList':{'author':[{'firstName':'Alice','initials':'A','lastName':'Smith','fullName':'Smith A Jr'}]},
           'journalInfo':{'yearOfPublication':2020,'volume':'1','journal':{'title':'Journal','issn':'1234-5678'}},
           'pageInfo':'1-2','pubTypeList':{'pubType':['Journal Article']}}
    secondary = {'source':'europepmc','doi':record['DOI'],'raw_record':raw,'url':'https://europepmc.org/article/MED/123',
                 'retrieved_at':'2026-09-16', 'request_url':'https://www.ebi.ac.uk/europepmc/webservices/rest/search'}
    clean = select_result(entry['fields'],[primary],[])
    assert clean['status']=='metadata_verified'
    return bib,entry,primary,secondary,clean


def test_same_doi_suffix_blocks_an_otherwise_matching_registry_record(tmp_path):
    _,entry,primary,secondary,clean=setup(tmp_path)
    assert epmc_record(secondary['raw_record'],primary['record'])['author'][0]['suffix']=='Jr'
    before=deepcopy(secondary)
    result=select_result(entry['fields'],[primary,secondary],[])
    assert result['status']=='needs_review' and any('suffix' in i for i in result['issues'])
    assert secondary==before
    entry['fields']['author']='Smith, Jr, A'
    primary['record']['author'][0]['suffix']='Jr'
    previous=dict(clean,candidates=[primary,secondary])
    assert reassess(entry,previous)['status']=='metadata_verified'


def test_suffix_witness_survives_edit_and_key_rename(tmp_path):
    bib,entry,_,secondary,clean=setup(tmp_path)
    cache=v.Cache(tmp_path/'cache.sqlite3')
    cache.put(bib,entry,v.outcome('needs_review',['suffix'],[secondary]))
    bib.write_text(bib.read_text().replace('Test,','Renamed,').replace('Year =','Year  ='))
    edited=v.load_entries(bib)['Renamed']
    assert edited['fingerprint']!=entry['fingerprint']
    assert cache.put(bib,edited,clean)['status']=='needs_review'
    before=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert cache.get(bib,edited)['status']=='needs_review'
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==before
    cache.close()


def test_suffix_history_migration_and_snapshot_without_matching_entries(tmp_path):
    bib,entry,_,secondary,clean=setup(tmp_path)
    cache=v.Cache(tmp_path/'cache.sqlite3')
    # Simulate a pre-fix approval whose raw source already contained the suffix.
    old=dict(clean,candidates=clean['candidates']+[secondary],policy=v.POLICY,key=entry['key'],fingerprint=entry['fingerprint'],checked_at='2026-01-01')
    cache.store(bib,entry,old)
    cache.index_notices()
    assert cache.get(bib,entry)['status']=='needs_review'
    rows=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    cache.index_notices()
    assert cache.get(bib,entry)['status']=='needs_review'
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==rows
    snapshot=tmp_path/'snapshot.gz'
    v.export_snapshot(bib,cache,snapshot)
    bib.write_text(bib.read_text().replace('Test,','Renamed,').replace('Year =','Year  ='))
    restored=v.Cache(tmp_path/'restored.sqlite3')
    assert v.import_snapshot(bib,restored,snapshot)==0
    assert restored.put(bib,v.load_entries(bib)['Renamed'],clean)['status']=='needs_review'
    assert restored.db.execute('SELECT count(*) FROM source_author_suffixes').fetchone()[0]==1
    restored.close();cache.close()


def test_invalid_suffix_snapshot_is_atomic(tmp_path):
    bib,entry,_,secondary,_=setup(tmp_path)
    cache=v.Cache(tmp_path/'cache.sqlite3')
    cache.put(bib,entry,v.outcome('needs_review',['suffix'],[secondary]))
    snapshot=tmp_path/'snapshot.gz';v.export_snapshot(bib,cache,snapshot)
    with gzip.open(snapshot,'rt') as f:records=[json.loads(s) for s in f]
    records[0]['source_author_suffixes'].append({'source':'invented'})
    with gzip.open(snapshot,'wt') as f:f.write('\n'.join(json.dumps(r) for r in records)+'\n')
    restored=v.Cache(tmp_path/'restored.sqlite3')
    with pytest.raises(ValueError,match='suffix'):v.import_snapshot(bib,restored,snapshot)
    assert restored.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==0
    assert restored.db.execute('SELECT count(*) FROM source_author_suffixes').fetchone()[0]==0
    restored.close();cache.close()


def test_source_suffix_supplement_preserves_full_registry_given_names(tmp_path):
    _,entry,primary,secondary,clean=setup(tmp_path)
    entry['fields']['author']='Smith, Jr, Alice'
    secondary['raw_record']['authorList']['author'][0]['firstName']='A'
    result=reassess(entry,dict(clean,candidates=[primary,secondary]))
    assert result['status']=='metadata_verified'
    c=next(c for c in result['candidates'] if c['source']=='europepmc')
    assert c['evidence']['author']['source']==[{'given':'Alice','family':'Smith','suffix':'Jr'}]
    assert c['evidence']['author']['name_source']=='crossref'
    assert c['record']['author'][0]['given']=='A'


@pytest.mark.parametrize('conflict', ['given','family','suffix','order','missing_given','year','pages'])
def test_suffix_supplement_cannot_hide_other_source_conflicts(tmp_path,conflict):
    _,entry,primary,secondary,clean=setup(tmp_path)
    entry['fields']['author']='Smith, Jr, Alice'
    raw=secondary['raw_record'];p=raw['authorList']['author'][0]
    if conflict=='given':p['firstName']='Ann'
    elif conflict=='family':p['lastName']='Jones'
    elif conflict=='suffix':primary['record']['author'][0]['suffix']='Sr'
    elif conflict=='order':raw['authorList']['author'].append(deepcopy(p))
    elif conflict=='missing_given':p.pop('firstName');p.pop('initials')
    elif conflict=='year':raw['journalInfo']['yearOfPublication']=2021
    else:raw['pageInfo']='3-4'
    assert reassess(entry,dict(clean,candidates=[primary,secondary]))['status']=='needs_review'


@pytest.mark.parametrize('source,expected', [('Smith, Jr., Alice B.','Smith, Jr, Alice B'),
    ('Murdock, Jr, B.B.','Murdock, Jr, B B'), ('Smith, II, A.','Smith, II, A'),
    ('de la Cruz, III, A. B.','de la Cruz, III, A B')])
def test_formatter_preserves_explicit_bibtex_suffixes(source,expected):
    from helpers import reformat_author,last_names_from_str
    from bibtexparser.customization import splitname
    formatted=reformat_author(source)
    assert formatted==expected
    assert reformat_author(formatted)==formatted
    assert splitname(formatted)['jr']==splitname(expected)['jr']
    assert last_names_from_str(formatted)==last_names_from_str(source)


def test_suffix_correction_retains_original_given_names_and_raw_source(tmp_path):
    from correction_proposals import suffix_proposal,replace_field
    bib,entry,primary,secondary,clean=setup(tmp_path)
    previous=dict(clean,status='needs_review',candidates=[primary,secondary])
    proposal=suffix_proposal(entry,previous)
    assert proposal['changes']=={'author':{'before':'A Smith','after':'Smith, Jr, A'}}
    assert proposal['secondary']==secondary
    bib.write_text(replace_field(bib.read_text(),entry,proposal))
    corrected=v.load_entries(bib)['Test']
    assert corrected['fingerprint']!=entry['fingerprint']
    assert reassess(corrected,previous)['status']=='metadata_verified'


def test_suffix_correction_can_use_suffix_present_in_both_sources(tmp_path):
    from correction_proposals import suffix_proposal
    _, entry, primary, secondary, clean = setup(tmp_path)
    primary['record']['author'][0]['suffix'] = 'Jr.'
    primary['issues'] = ['author: Author suffix differs']
    entry['fields']['author'] = 'Alice Smith'
    secondary['raw_record']['authorList']['author'][0]['firstName'] = 'A'
    proposal = suffix_proposal(entry, dict(clean, status='needs_review', candidates=[primary, secondary]))
    assert proposal['changes'] == {'author': {'before': 'Alice Smith', 'after': 'Smith, Jr, Alice'}}
    secondary['raw_record']['authorList']['author'][0]['firstName'] = 'Bob'
    assert suffix_proposal(entry, dict(clean, status='needs_review', candidates=[primary, secondary])) is None


@pytest.mark.parametrize('conflict',['hold','page','given','surname','duplicate'])
def test_suffix_correction_rejects_ambiguous_or_conflicting_evidence(tmp_path,conflict):
    from correction_proposals import suffix_proposal
    _,entry,primary,secondary,clean=setup(tmp_path)
    previous=dict(clean,status='needs_review',candidates=[primary,secondary])
    if conflict=='hold':previous['external_evidence']=[{'issue':'unresolved identity'}]
    elif conflict=='page':secondary['raw_record']['pageInfo']='99-100'
    elif conflict=='given':secondary['raw_record']['authorList']['author'][0]['firstName']='Bob'
    elif conflict=='surname':secondary['raw_record']['authorList']['author'][0]['lastName']='Jones'
    else:secondary['raw_record']['authorList']['author'].append(deepcopy(secondary['raw_record']['authorList']['author'][0]))
    assert suffix_proposal(entry,previous) is None
@pytest.mark.parametrize("left,right,expected", [
    ("Jr", "Jr.", True), ("Sr.", "Sr", True), ("III", "III.", True),
    ("Jr", "Sr.", False), ("Jr.", "", False), ("II", "III.", False),
    ("Jr..", "Jr", False), ("Unrecognized.", "Unrecognized", False),
])
def test_suffix_punctuation_is_narrow_and_never_erases_identity(left, right, expected):
    from verification import author_evidence, normalize_author_suffix
    from auto_review import compatible_authors
    assert (normalize_author_suffix(left) == normalize_author_suffix(right)) is expected
    first = {"author": [{"given": "Alice", "family": "Smith", "suffix": left}]}
    second = {"author": [{"given": "A", "family": "Smith", "suffix": right}]}
    assert compatible_authors(first, second) is expected
    assert author_evidence("Smith, " + left + ", Alice", [{"given": "Alice", "family": "Smith", "suffix": right}])[0] is expected
