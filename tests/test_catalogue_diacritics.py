"""A live LC search defect must broaden discovery without weakening identity."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unicodedata
import xml.etree.ElementTree as ET

import pytest

from cdlbib import catalogue_review as cr
from cdlbib.catalogue_discovery import M, S, search_query
from cdlbib import verification as v
from cdlbib.verification_cli import DeferredClient

CASE = json.loads((Path(__file__).parent/'fixtures/catalogue_diacritics.json').read_text())


def test_actual_gardenfors_edition_matches_without_losing_author_accents():
    case = json.loads((Path(__file__).parent/'fixtures/catalogue_gardenfors.json').read_text())
    fields = case['entry']['fields']
    result = cr.assess_catalogue(fields, case['response'])
    assert result['status'] == 'metadata_verified'
    assert result['accepted_record_id'] == '11782992'
    assert cr.valid_catalogue_approval(result)
    assert cr.reassess_saved_catalogue(fields, result) == result
    assert cr.assess_catalogue(dict(fields, author='P Gardenfors'), case['response'])['status'] == 'needs_review'
    assert cr.assess_catalogue(dict(fields, year='2004'), case['response'])['status'] == 'needs_review'


def test_folded_query_preserves_citation_and_unicode_normalization():
    fields = deepcopy(CASE['entry']['fields']); original = deepcopy(fields)
    assert search_query(fields).endswith('dc.author="buzsáki"')
    assert search_query(fields, fold_diacritics=True) == CASE['folded_response']['query']
    decomposed = {k: unicodedata.normalize('NFD', x) for k, x in fields.items()}
    assert search_query(decomposed, fold_diacritics=True) == search_query(fields, fold_diacritics=True)
    assert fields == original


def test_real_recovered_record_pairs_initial_heading_with_printed_byline():
    # Policy 6 rejected this record: heading 'Buzsaki, G.' vs 245c 'György
    # Buzsáki'. Policy 7 relates the two LC fields (initial G = György) and
    # compares the citation with the printed byline, accents intact.
    fields = CASE['entry']['fields']
    assert CASE['broad_response']['total_records'] == 0
    result = cr.assess_catalogue(fields, CASE['folded_response'])
    assert len(result['candidates']) == 1
    candidate = result['candidates'][0]
    assert candidate['record']['catalogue_grammar'] == cr.WIDENED_GRAMMAR
    # Verbatim transcription (LC sends decomposed accents); compared as NFC.
    assert [{k: unicodedata.normalize('NFC', x) for k, x in p.items()} for p in candidate['record']['author']] \
        == [{'given': 'György', 'family': 'Buzsáki', 'suffix': ''}]
    assert candidate['evidence']['author']['match']
    # The cited place is New York, but LC's first place is Oxford (008 enk):
    # the address remains the only blocker and is not guessed.
    assert result['status'] == 'needs_review'
    assert candidate['issues'] == ['address: missing evidence or mismatch']
    without = {k: x for k, x in fields.items() if k != 'address'}
    assert cr.assess_catalogue(without, CASE['folded_response'])['status'] == 'metadata_verified'
    for author in ('Gyorgy Buzsaki', 'G Buzsaki', r"Gyorgy Buzs{\'a}ki", r"G A Buzs{\'a}ki"):
        assert cr.assess_catalogue(dict(without, author=author), CASE['folded_response'])['status'] == 'needs_review', author
    assert cr.assess_catalogue(dict(without, author=r"G Buzs{\'a}ki"), CASE['folded_response'])['status'] == 'metadata_verified'


@pytest.mark.parametrize('heading', ['Buzsáki, Z.', 'Buzsaky, G.', 'Buzsáki, G., $ceditor'])
def test_conflicting_heading_initial_or_surname_still_rejects(heading):
    response = deepcopy(CASE['folded_response'])
    root = ET.fromstring(response['raw_xml'])
    node = root.find('.//'+M+"datafield[@tag='100']")
    name, _, extra = heading.partition(', $c')
    node.find(M+"subfield[@code='a']").text = name
    if extra:
        ET.SubElement(node, M+'subfield', code='e').text = extra
    response['raw_xml'] = ET.tostring(root, encoding='unicode')
    response['document_sha256'] = hashlib.sha256(response['raw_xml'].encode()).hexdigest()
    without = {k: x for k, x in CASE['entry']['fields'].items() if k != 'address'}
    assert cr.assess_catalogue(without, response)['status'] == 'needs_review'


def test_folded_search_is_bound_to_the_original_full_citation():
    # Supply the complete given name in this synthetic heading to isolate
    # search fallback from the separate real-world MARC heading deficiency.
    response = deepcopy(CASE['folded_response'])
    root = ET.fromstring(response['raw_xml'])
    root.find('.//'+M+"datafield[@tag='100']/"+M+"subfield[@code='a']").text = 'Buzsáki, György.'
    response['raw_xml'] = ET.tostring(root, encoding='unicode')
    response['document_sha256'] = hashlib.sha256(response['raw_xml'].encode()).hexdigest()
    fields = deepcopy(CASE['entry']['fields']); fields['address'] = 'New York'
    positive = cr.assess_catalogue(fields, response)
    assert positive['status'] == 'metadata_verified'
    assert cr.valid_catalogue_approval(positive)
    for change in ({'author': 'Gyorgy Buzsaki'}, {'title': 'Rhythms of the brains'},
                   {'year': '2007'}, {'publisher': 'Other Press'}):
        assert cr.assess_catalogue(dict(fields, **change), response)['status'] == 'needs_review'
    unrelated = deepcopy(response)
    root.find(S+'echoedSearchRetrieveRequest/'+S+'query').text = 'dc.title="unrelated"'
    unrelated['raw_xml'] = ET.tostring(root, encoding='unicode')
    unrelated['document_sha256'] = hashlib.sha256(unrelated['raw_xml'].encode()).hexdigest()
    assert cr.assess_catalogue(fields, unrelated)['status'] == 'needs_review'


def test_cached_fallback_runs_once_and_survives_restore(tmp_path):
    bib = tmp_path/'library.bib'; bib.write_text(CASE['entry']['raw'])
    cache = v.Cache(tmp_path/'live.sqlite3'); entry = v.load_entries(bib)['Buzs06']
    cache.put(bib, entry, dict(v.outcome('needs_review', ['No registry approval']),
                             catalogue_review={'policy': '5'}))
    for response in (CASE['broad_response'], CASE['folded_response']):
        cache.save_response('loc-sru-v1:10:'+response['query'], response)
    client = DeferredClient(cache, None, 1.0, False)
    result = cr.run_catalogue_review(bib, cache, client, tmp_path/'report')
    assert result['Buzs06']['status'] == 'needs_review'
    assert len(result['Buzs06']['catalogue_review']['queries']) == 2
    assert len(result['Buzs06']['candidates']) == 1 and client.requests == 0
    count = cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert cr.run_catalogue_review(bib, cache, client, tmp_path/'report') == result
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0] == count
    snapshot = tmp_path/'snapshot.gz'; v.export_snapshot(bib, cache, snapshot)
    fresh = v.Cache(tmp_path/'fresh.sqlite3')
    assert v.import_snapshot(bib, fresh, snapshot) == 1
    assert v.current_results(bib, fresh) == result
    assert v.import_snapshot(bib, fresh, snapshot) == 0
    cache.close(); fresh.close()
