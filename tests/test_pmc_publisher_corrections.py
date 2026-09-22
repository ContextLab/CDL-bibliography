"""Publisher repairs require agreeing raw front matter and complete identity."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bibcheck'))
from auto_review import reassess
from correction_proposals import replace_field
from pmc_corrections import pmc_publisher_proposal
from verification import load_entries


CASES = json.loads((Path(__file__).parent / 'fixtures/pmc_publishers.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['entry']['key'])
def test_real_front_matter_and_registry_repair_publisher_only(tmp_path, case):
    entry, previous = case['entry'], case['previous']
    p = pmc_publisher_proposal(entry, previous)
    assert p['changes'] == {'publisher': {'before': entry['fields']['publisher'], 'after': 'National Academy of Sciences'}}
    path = tmp_path / 'citation.bib'
    path.write_text(replace_field(entry['raw'], entry, p))
    edited = load_entries(path)[entry['key']]
    assert edited['fingerprint'] != entry['fingerprint']
    assert edited['fields'] == dict(entry['fields'], publisher='National Academy of Sciences')
    assert reassess(edited, previous)['status'] == 'metadata_verified'


@pytest.mark.parametrize('change', ['xmlpublisher', 'registrypublisher', 'missingpublisher', 'title', 'author',
    'pages', 'medpages', 'year', 'xmldoi', 'localdoi', 'manuscript', 'notice', 'external', 'referenceonly', 'duplicateprimary'])
def test_disagreement_and_incomplete_identity_prevent_repair(change):
    data = deepcopy(CASES[0])
    entry, previous = data['entry'], data['previous']
    source = next(c for c in previous['candidates'] if c['source'] == 'pmc-jats')
    primary = next(c for c in previous['candidates'] if c['source'] == 'crossref' and c['doi'] == source['doi'])
    if change == 'xmlpublisher':
        source['raw_xml'] = source['raw_xml'].replace('National Academy of Sciences</publisher-name>', 'Other Press</publisher-name>')
    elif change == 'registrypublisher':
        primary['record']['publisher'] = 'Other Press'
    elif change == 'missingpublisher':
        primary['record'].pop('publisher')
    elif change in {'title', 'author', 'pages', 'year'}:
        entry['fields'][change] = {'title': 'Different work', 'author': 'J Smith', 'pages': '5903--5910', 'year': '2010'}[change]
    elif change == 'medpages':
        source['medline_record']['pageInfo'] = '5903-5910'
    elif change == 'xmldoi':
        source['raw_xml'] = source['raw_xml'].replace(source['doi'], '10.1234/other')
    elif change == 'localdoi':
        entry['fields']['doi'] = '10.1234/other'
    elif change == 'manuscript':
        source['raw_xml'] = source['raw_xml'].replace('<article-meta>', '<article-meta><article-id pub-id-type="manuscript">ABC</article-id>')
    elif change == 'notice':
        source['medline_record']['commentCorrectionList'] = {'commentCorrection': [{'type': 'Erratum in', 'reference': 'Notice'}]}
    elif change == 'external':
        previous['external_evidence'] = {'hold': True}
    elif change == 'referenceonly':
        tag = '<publisher><publisher-name>National Academy of Sciences</publisher-name></publisher>'
        source['raw_xml'] = source['raw_xml'].replace(tag, '').replace('</article>', '<back><ref-list><ref>'+tag+'</ref></ref-list></back></article>')
    else:
        previous['candidates'].append(deepcopy(primary))
    assert pmc_publisher_proposal(entry, previous) is None
