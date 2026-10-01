"""PubMed full-name suffixes survive mapping, edits, and portable caching.

User decision 2026-09-24/25 (verification/resolution-plan-2026-09-22/README.md,
"Spot-check completed"): name suffixes (Jr, Sr, II, III, IV) are never added and
the comparator ignores them on both sides. Suffix witnesses are still parsed,
retained and exported, but they no longer block a match or yield a proposal.
"""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
import pytest
from cdlbib import verification as v
from cdlbib.auto_review import epmc_record, pubmed_author_suffix, reassess, select_result


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


def test_same_doi_suffix_no_longer_blocks_an_otherwise_matching_registry_record(tmp_path):
    _,entry,primary,secondary,clean=setup(tmp_path)
    assert epmc_record(secondary['raw_record'],primary['record'])['author'][0]['suffix']=='Jr'
    before=deepcopy(secondary)
    result=select_result(entry['fields'],[primary,secondary],[])
    assert result['status']=='metadata_verified' and not any('suffix' in i for i in result['issues'])
    assert secondary==before
    # Negative control: a surname conflict in the registry record still blocks.
    other=deepcopy(primary);other['record']['author'][0]['family']='Jones'
    other['evidence'],other['issues']=v.compare_record(entry['fields'],other['record'])
    assert select_result(entry['fields'],[other,secondary],[])['status']=='needs_review'
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
    stored=cache.put(bib,edited,clean)
    # The witness is still retained across the edit and rename, but a suffix
    # no longer blocks (suffixes are ignored on both sides).
    assert stored['status']=='metadata_verified'
    assert any(c.get('source')=='europepmc' for c in stored['candidates'])
    before=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert cache.get(bib,edited)['status']=='metadata_verified'
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==before
    cache.close()


def test_suffix_history_migration_and_snapshot_without_matching_entries(tmp_path):
    bib,entry,_,secondary,clean=setup(tmp_path)
    cache=v.Cache(tmp_path/'cache.sqlite3')
    # Simulate a pre-fix approval whose raw source already contained the suffix.
    old=dict(clean,candidates=clean['candidates']+[secondary],policy=v.POLICY,key=entry['key'],fingerprint=entry['fingerprint'],checked_at='2026-01-01')
    cache.store(bib,entry,old)
    cache.index_notices()
    assert cache.get(bib,entry)['status']=='metadata_verified'
    rows=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    cache.index_notices()
    assert cache.get(bib,entry)['status']=='metadata_verified'
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]==rows
    snapshot=tmp_path/'snapshot.gz'
    v.export_snapshot(bib,cache,snapshot)
    bib.write_text(bib.read_text().replace('Test,','Renamed,').replace('Year =','Year  ='))
    restored=v.Cache(tmp_path/'restored.sqlite3')
    assert v.import_snapshot(bib,restored,snapshot)==0
    assert restored.put(bib,v.load_entries(bib)['Renamed'],clean)['status']=='metadata_verified'
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


def test_cited_suffix_needs_no_pubmed_supplement(tmp_path):
    # Before 2026-09-25 a cited 'Smith, Jr, Alice' verified only through the
    # PubMed suffix supplement. Suffixes are now ignored on both sides, so the
    # registry names match directly and nothing is supplemented.
    _,entry,primary,secondary,clean=setup(tmp_path)
    entry['fields']['author']='Smith, Jr, Alice'
    secondary['raw_record']['authorList']['author'][0]['firstName']='A'
    result=reassess(entry,dict(clean,candidates=[primary,secondary]))
    assert result['status']=='metadata_verified'
    c=next(c for c in result['candidates'] if c['source']=='crossref')
    assert c['evidence']['author']['match'] and c['issues']==[]
    assert c['record']['author'][0]==({'given':'Alice','family':'Smith'})


@pytest.mark.parametrize('conflict', ['given','family','order','missing_given','year','pages'])
def test_ignored_suffix_cannot_hide_other_conflicts(tmp_path,conflict):
    _,entry,primary,secondary,clean=setup(tmp_path)
    entry['fields']['author']='Smith, Jr, Alice'
    record=primary['record'];p=record['author'][0]
    if conflict=='given':p['given']='Ann'
    elif conflict=='family':p['family']='Jones'
    elif conflict=='order':record['author'].append({'given':'Bob','family':'Other'})
    elif conflict=='missing_given':
        p.pop('given');a=secondary['raw_record']['authorList']['author'][0];a.pop('firstName');a.pop('initials')
    elif conflict=='year':record['published']={'date-parts':[[2021]]}
    else:record['page']='3-4'
    primary['evidence'],primary['issues']=v.compare_record(entry['fields'],record)
    assert reassess(entry,dict(clean,candidates=[primary,secondary]))['status']=='needs_review'


def test_sources_that_differ_only_by_suffix_are_compatible(tmp_path):
    # Suffixes are ignored on both sides (user decision 2026-09-24/25).
    _,entry,primary,secondary,clean=setup(tmp_path)
    entry['fields']['author']='Smith, Jr, Alice'
    primary['record']['author'][0]['suffix']='Sr'
    assert reassess(entry,dict(clean,candidates=[primary,secondary]))['status']=='metadata_verified'


@pytest.mark.parametrize('source,expected', [('Smith, Jr., Alice B.','Smith, Jr, Alice B'),
    ('Murdock, Jr, B.B.','Murdock, Jr, B B'), ('Smith, II, A.','Smith, II, A'),
    ('de la Cruz, III, A. B.','de la Cruz, III, A B')])
def test_formatter_preserves_explicit_bibtex_suffixes(source,expected):
    from cdlbib.helpers import reformat_author,last_names_from_str
    from bibtexparser.customization import splitname
    formatted=reformat_author(source)
    assert formatted==expected
    assert reformat_author(formatted)==formatted
    assert splitname(formatted)['jr']==splitname(expected)['jr']
    assert last_names_from_str(formatted)==last_names_from_str(source)


def test_no_suffix_is_ever_proposed_and_the_cited_byline_verifies(tmp_path):
    from cdlbib.correction_proposals import suffix_proposal
    bib,entry,primary,secondary,clean=setup(tmp_path)
    previous=dict(clean,status='needs_review',candidates=[primary,secondary])
    assert suffix_proposal(entry,previous) is None
    assert reassess(entry,previous)['status']=='metadata_verified'


def test_suffix_present_in_both_sources_is_still_not_proposed(tmp_path):
    from cdlbib.correction_proposals import suffix_proposal
    _, entry, primary, secondary, clean = setup(tmp_path)
    primary['record']['author'][0]['suffix'] = 'Jr.'
    primary['issues'] = ['author: Author suffix differs']
    entry['fields']['author'] = 'Alice Smith'
    secondary['raw_record']['authorList']['author'][0]['firstName'] = 'A'
    assert suffix_proposal(entry, dict(clean, status='needs_review', candidates=[primary, secondary])) is None


@pytest.mark.parametrize('conflict',['hold','page','given','surname','duplicate'])
def test_suffix_correction_rejects_ambiguous_or_conflicting_evidence(tmp_path,conflict):
    from cdlbib.correction_proposals import suffix_proposal
    _,entry,primary,secondary,clean=setup(tmp_path)
    previous=dict(clean,status='needs_review',candidates=[primary,secondary])
    if conflict=='hold':previous['external_evidence']=[{'issue':'unresolved identity'}]
    elif conflict=='page':secondary['raw_record']['pageInfo']='99-100'
    elif conflict=='given':secondary['raw_record']['authorList']['author'][0]['firstName']='Bob'
    elif conflict=='surname':secondary['raw_record']['authorList']['author'][0]['lastName']='Jones'
    else:secondary['raw_record']['authorList']['author'].append(deepcopy(secondary['raw_record']['authorList']['author'][0]))
    assert suffix_proposal(entry,previous) is None


@pytest.mark.parametrize("left,right,same,ignored", [
    ("Jr", "Jr.", True, True), ("Sr.", "Sr", True, True), ("III", "III.", True, True),
    ("Jr", "Sr.", False, True), ("Jr.", "", False, True), ("II", "III.", False, True),
    ("IV", "", False, True),
    # Not a recognized suffix: never erased, so identity is kept.
    ("Jr..", "Jr", False, False), ("Unrecognized.", "Unrecognized", False, False),
])
def test_recognized_suffixes_are_ignored_and_nothing_else_is(left, right, same, ignored):
    from cdlbib.verification import author_evidence, normalize_author_suffix
    from cdlbib.auto_review import compatible_authors
    assert (normalize_author_suffix(left) == normalize_author_suffix(right)) is same
    first = {"author": [{"given": "Alice", "family": "Smith", "suffix": left}]}
    second = {"author": [{"given": "A", "family": "Smith", "suffix": right}]}
    assert compatible_authors(first, second) is ignored
    assert author_evidence("Smith, " + left + ", Alice", [{"given": "Alice", "family": "Smith", "suffix": right}])[0] is ignored
    # Negative control: a different given name is never hidden by a suffix.
    assert not author_evidence("Smith, " + left + ", Bob", [{"given": "Alice", "family": "Smith", "suffix": right}])[0]


@pytest.mark.parametrize("cited,person", [
    ("Alice Smith", {"given": "Alice", "family": "Smith", "suffix": "Jr"}),
    ("Smith, III, Alice", {"given": "Alice", "family": "Smith"}),
    ("A Jr Smith", {"given": "Alice", "family": "Smith"}),
    ("A Smith", {"given": "Alice Jr.", "family": "Smith"}),
])
def test_suffix_on_either_side_or_among_given_names_is_ignored(cited, person):
    from cdlbib.verification import author_evidence
    assert author_evidence(cited, [person])[0]
    assert not author_evidence(cited.replace("Smith", "Smyth"), [person])[0]


# Real cached cases (tests/fixtures/apply-2026-09-25-cases.json.gz: cdl.bib entries
# and their latest review rows, read-only, frozen before the rule change) -------

def stage1_case(key):
    root = Path(__file__).resolve().parents[1]
    data = json.loads(gzip.open(root / 'tests/fixtures/apply-2026-09-25-cases.json.gz').read())
    case = deepcopy(data['cases'][key])
    return case['entry'], case['previous']


@pytest.mark.parametrize('key,surname', [('BrodMurd77', 'Murdock'), ('CalvEtal73', 'Ward'),
                                         ('RoedKarp06a', 'Roediger'), ('RoedKarp06b', 'Roediger')])
def test_real_bylines_without_the_source_suffix_verify(key, surname, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    entry, previous = stage1_case(key)
    assert previous['status'] == 'needs_review'  # frozen under the old rule
    assert 'Jr' not in entry['fields']['author'] and 'III' not in entry['fields']['author']
    result = reassess(entry, previous)
    assert result['status'] == 'metadata_verified', result['issues']
    assert not any('suffix' in i for i in result['issues'])
    # Negative control: a misspelt surname still blocks the same record.
    wrong = deepcopy(entry)
    wrong['fields']['author'] = entry['fields']['author'].replace(surname, surname[:-1] + 'x')
    assert reassess(wrong, previous)['status'] == 'needs_review'


def test_real_source_suffix_is_never_written_into_a_proposal(monkeypatch):
    from cdlbib.correction_proposals import house_byline, source_authors
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    entry, previous = stage1_case('BrodMurd77')
    record = next(c['record'] for c in previous['candidates'] if c.get('source') == 'crossref'
                  and any(p.get('suffix') for p in c['record'].get('author', [])))
    assert source_authors(record) == 'D A Brodie and B B Murdock'
    assert house_byline([{'given': 'Henry L.', 'family': 'Roediger', 'suffix': 'III'}]) == 'H L Roediger'
