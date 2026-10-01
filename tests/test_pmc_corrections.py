"""A coordinate proposal must preserve identity and pass both complete sources."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bibcheck'))
from auto_review import reassess
from fulltext_review import assess_fulltext
from pmc_corrections import pmc_coordinate_proposal, replace_pmc_coordinates
from verification import load_entries
from test_auto_review import candidate, secondary
from test_fulltext_review import XML
import test_auto_review
sample = test_auto_review.sample


def case(tmp_path, sample):
    fields, record, raw = sample
    record['published-print'] = {'date-parts': [[2019]]}
    fields['pages'] = '123'
    fields['volume'] = '3'
    path = tmp_path / 'sample.bib'
    path.write_text('@article{A,\n' + ',\n'.join(k+'={'+v+'}' for k,v in fields.items() if k not in {'ID','ENTRYTYPE'}) + '}')
    entry = load_entries(path)['A']
    primary = candidate(fields, record)
    source = assess_fulltext(fields, primary, raw, {'body': XML, 'url': 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML', 'retrieved_at': '2026-09-17'})
    previous = {'status': 'needs_review', 'candidates': [primary, secondary(fields, record, raw), source]}
    return path, entry, previous


def test_source_pair_proposes_complete_coordinates_and_rechecks_raw_edit(tmp_path, sample):
    path, entry, previous = case(tmp_path, sample)
    proposal = pmc_coordinate_proposal(entry, previous)
    assert proposal['changes'] == {'pages': {'before': '123', 'after': '123--129'}, 'volume': {'before': '3', 'after': '2'}}
    changed = replace_pmc_coordinates(path.read_text(), entry, proposal)
    path.write_text(changed)
    new = load_entries(path)['A']
    assert new['fingerprint'] != entry['fingerprint']
    assert reassess(new, previous)['status'] == 'metadata_verified'


@pytest.mark.parametrize('change', ['title', 'author', 'medpage', 'medyear', 'medissn', 'notice', 'xmlversion', 'xmldoi', 'xmlissn', 'external', 'number'])
def test_identity_version_and_secondary_conflicts_prohibit_proposal(tmp_path, sample, change):
    _, entry, previous = case(tmp_path, sample)
    src = previous['candidates'][-1]
    if change == 'external':
        previous['external_evidence'] = {'hold': True}
    elif change == 'number':
        entry['fields']['number'] = '99'
        src['raw_xml'] = src['raw_xml'].replace('<issue>3</issue>', '')
    elif change == 'title':
        src['raw_xml'] = src['raw_xml'].replace('A result', 'A different work')
    elif change == 'author':
        src['raw_xml'] = src['raw_xml'].replace('Alice B', 'Alice Q')
    elif change == 'medpage':
        src['medline_record']['pageInfo'] = '123-130'
    elif change == 'medyear':
        src['medline_record']['journalInfo']['yearOfPublication'] = 2021
    elif change == 'medissn':
        src['medline_record']['journalInfo']['journal']['issn'] = '9999-0000'
    elif change == 'notice':
        src['medline_record']['commentCorrectionList'] = {'commentCorrection': [{'type': 'Erratum in', 'reference': 'Notice'}]}
    elif change == 'xmlversion':
        src['raw_xml'] = src['raw_xml'].replace('<article-meta>', '<article-meta><article-version>2</article-version>')
    elif change == 'xmldoi':
        src['raw_xml'] = src['raw_xml'].replace('10.1234/a', '10.1234/b')
    else:
        src['raw_xml'] = src['raw_xml'].replace('1234-5678', '9999-0000')
    assert pmc_coordinate_proposal(entry, previous) is None


def test_missing_given_name_is_added_only_when_both_sources_supply_it(tmp_path, sample):
    path, entry, previous = case(tmp_path, sample)
    entry['fields']['author'] = 'A Smith'
    entry['raw'] = entry['raw'].replace('A B Smith', 'A Smith')
    path.write_text(entry['raw'])
    entry = load_entries(path)['A']
    proposal = pmc_coordinate_proposal(entry, previous, include_authors=True)
    assert proposal and proposal['kind'] == 'pmc_corroborated_given_names'
    assert proposal['changes']['author']['after'] == 'A B Smith'  # house format: initials, no periods
    from pmc_corrections import replace_pmc_given_names
    path.write_text(replace_pmc_given_names(path.read_text(), entry, proposal))
    assert reassess(load_entries(path)['A'], previous)['status'] == 'metadata_verified'


@pytest.mark.parametrize('local', ['Alice C Smith', 'Anna Smith', 'Alice B C Smith', 'Alice B Smyth', 'Alice B Smith, Jr', 'Alice B Smith and A Jones'])
def test_existing_byline_details_cannot_be_removed_or_overridden(local):
    from pmc_corrections import preserves_byline_details
    assert not preserves_byline_details(local, [{'given': 'Alice B', 'family': 'Smith'}])


def test_full_names_cannot_be_shrunk_to_initials():
    from pmc_corrections import preserves_byline_details
    assert not preserves_byline_details('Alice Smith', [{'given': 'A B', 'family': 'Smith'}])
