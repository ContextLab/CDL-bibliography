"""Year refinement narrows discovery without replacing edition evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bibcheck'))
import catalogue_review as cr
from catalogue_discovery import M, S, search_query
import verification as v
from verification_cli import DeferredClient

CASES = json.loads((Path(__file__).parent / 'fixtures/catalogue_dated_books.json').read_text())


def changed(response, action):
    result = deepcopy(response)
    root = ET.fromstring(result['raw_xml'])
    action(root)
    result['raw_xml'] = ET.tostring(root, encoding='unicode')
    result['document_sha256'] = hashlib.sha256(result['raw_xml'].encode()).hexdigest()
    return result


def competing_broad_response(case):
    """The real broad search with its later edition made an unparseable
    same-year rival (a second publication statement and 008 date 2005).

    Policy 7 parses the real 2014 record and sees that it is another year,
    so the real broad search no longer needs refinement. This derived rival
    still cannot be excluded, so it keeps the refinement path exercised."""
    def edit(root):
        record = root.findall('.//' + M + 'record')[1]
        node = record.find(M+"controlfield[@tag='008']"); node.text = node.text[:7]+'2005'+node.text[11:]
        imprint = record.find(M+"datafield[@tag='264'][@ind2='1']")
        record.append(deepcopy(imprint))
    return changed(case['broad_response'], edit)


def test_actual_first_edition_is_not_blocked_by_unparsed_later_edition():
    case = CASES['Luck05']; fields = case['entry']['fields']
    # Policy 7: the later (2014, RDA 264) edition now parses and is rejected
    # on its own year, publisher and edition, so the first edition is unique.
    broad = cr.assess_catalogue(fields, case['broad_response'])
    assert broad['status'] == 'metadata_verified' and broad['accepted_record_id'] == '13859415'
    later = next(c for c in broad['candidates'] if c['record_id'] == '17917778')
    assert later['record']['catalogue_grammar'] == cr.WIDENED_GRAMMAR
    assert {'year: missing evidence or mismatch', 'edition: missing evidence or mismatch'} <= set(later['issues'])
    assert cr.valid_catalogue_approval(broad)
    # An unparseable rival of the SAME year still blocks the broad search.
    assert cr.assess_catalogue(fields, competing_broad_response(case))['status'] == 'needs_review'
    result = cr.assess_catalogue(fields, case['response'])
    assert result['status'] == 'metadata_verified' and result['accepted_record_id'] == '13859415'
    assert cr.valid_catalogue_approval(result)
    assert cr.reassess_saved_catalogue(fields, result) == result
    assert cr.assess_catalogue(dict(fields, year='2014'), case['response'])['status'] == 'needs_review'


@pytest.mark.parametrize('key', ['Badd90', 'BorgGroe05', 'NoceWrig06', 'SuttBart98'])
def test_narrowing_does_not_fix_missing_editions_or_author_details(key):
    case = CASES[key]
    assert cr.assess_catalogue(case['entry']['fields'], case['response'])['status'] == 'needs_review'


def test_fust05_accented_title_page_confirms_initials_without_losing_the_accent():
    # Diagnosis (plan-books.md R2 f): the LC heading 'Fuster, Joaquin M.' lacks
    # the accent that the title-page transcription 'Joaquín M. Fuster' (NFD)
    # carries. Policy 7 relates the two LC fields diacritic-insensitively and
    # takes the printed form, accent intact, as the byline to compare.
    case = CASES['Fust05']; fields = case['entry']['fields']
    result = cr.assess_catalogue(fields, case['response'])
    assert result['status'] == 'metadata_verified' and cr.valid_catalogue_approval(result)
    person = result['candidates'][0]['record']['author'][0]
    assert v.normalized(person['given']) == 'joaquín m.' and person['family'] == 'Fuster'
    for author in ('Joaquin M Fuster', 'Joaquím M Fuster', 'J Fuster', 'J M A Fuster', 'M J Fuster', 'J M Foster'):
        assert cr.assess_catalogue(dict(fields, author=author), case['response'])['status'] == 'needs_review', author
    assert cr.assess_catalogue(dict(fields, author='Joaquín M Fuster'), case['response'])['status'] == 'metadata_verified'


@pytest.mark.parametrize('key', ['BorgGroe05', 'NoceWrig06'])
def test_explicit_second_edition_requires_matching_number_and_complete_fields(key):
    case = CASES[key]
    for edition in ('2', 'second', '2nd ed.', 'Second edition'):
        fields = dict(case['entry']['fields'], edition=edition)
        result = cr.assess_catalogue(fields, case['response'])
        assert result['status'] == 'metadata_verified'
        assert cr.valid_catalogue_approval(result)
    for edition in ('1', '3', '12', '2st', 'revised second edition', '2nd ed., corrected', ''):
        assert cr.assess_catalogue(dict(case['entry']['fields'], edition=edition), case['response'])['status'] == 'needs_review'


def test_supplied_edition_must_not_be_inferred_when_source_omits_it():
    case = CASES['Luck05']
    assert cr.assess_catalogue(dict(case['entry']['fields'], edition='1'), case['response'])['status'] == 'needs_review'


def test_bibliography_polishing_preserves_the_edition_that_was_verified(tmp_path):
    from correction_proposals import replace_field
    import helpers
    case = CASES['NoceWrig06']; entry = case['entry']
    proposal = {'key': entry['key'], 'fingerprint': entry['fingerprint'],
                'changes': {'edition': {'before': None, 'after': '2'}}}
    path = tmp_path/'citation.bib'; path.write_text(replace_field(entry['raw'], entry, proposal))
    edited = v.load_entries(path)[entry['key']]
    polished, removed = helpers.polish_database({entry['key']: edited['fields']}, {}, autofix=True, verbose=False, return_removed=True)
    assert not removed and len(polished) == 1
    assert polished[0]['ID'] == entry['key'] and polished[0]['edition'] == '2'
    assert cr.assess_catalogue(polished[0], case['response'])['status'] == 'metadata_verified'


@pytest.mark.parametrize('change', ['query-year', 'query-author', 'year', 'electronic', 'duplicate', 'incomplete'])
def test_refined_query_still_checks_identity_dates_format_and_completeness(change):
    case = CASES['Luck05']
    def edit(root):
        record = root.find('.//' + M + 'record')
        if change.startswith('query-'):
            node = root.find(S+'echoedSearchRetrieveRequest/'+S+'query')
            node.text = node.text.replace('2005', '2006') if change == 'query-year' else node.text.replace('luck', 'other')
        elif change == 'year':
            record.find(M+"datafield[@tag='260']/"+M+"subfield[@code='c']").text = 'c2014.'
        elif change == 'electronic':
            node = record.find(M+"controlfield[@tag='008']"); node.text = node.text[:23]+'o'+node.text[24:]
        elif change == 'duplicate':
            wrapper = deepcopy(root.find(S+'records/'+S+'record'))
            wrapper.find(S+'recordPosition').text = '2'
            wrapper.find(S+'recordData/'+M+'record/'+M+"controlfield[@tag='001']").text = 'another-edition'
            root.find(S+'records').append(wrapper)
            root.find(S+'numberOfRecords').text = '2'
        else:
            root.find(S+'numberOfRecords').text = '2'
    assert cr.assess_catalogue(case['entry']['fields'], changed(case['response'], edit))['status'] == 'needs_review'


def test_cached_refinement_runs_once_and_restores_without_network(tmp_path):
    case = CASES['Luck05']; bib = tmp_path/'library.bib'; bib.write_text(case['entry']['raw'])
    cache = v.Cache(tmp_path/'live.sqlite3'); entry = v.load_entries(bib)['Luck05']
    cache.put(bib, entry, v.outcome('needs_review', ['No registry approval']))
    for response in (competing_broad_response(case), case['response']):
        cache.save_response('loc-sru-v1:10:'+response['query'], response)
    client = DeferredClient(cache, None, 1.0, False)
    result = cr.run_catalogue_review(bib, cache, client, tmp_path/'report')
    assert result['Luck05']['status'] == 'metadata_verified' and client.requests == 0
    assert len(result['Luck05']['catalogue_review']['queries']) == 2
    count = cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
    assert cr.run_catalogue_review(bib, cache, client, tmp_path/'report') == result
    assert cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0] == count
    snapshot = tmp_path/'snapshot.gz'; v.export_snapshot(bib, cache, snapshot)
    fresh = v.Cache(tmp_path/'fresh.sqlite3')
    assert v.import_snapshot(bib, fresh, snapshot) == 1
    assert v.current_results(bib, fresh) == result
    assert v.import_snapshot(bib, fresh, snapshot) == 0
    cache.close(); fresh.close()


def test_empty_refinement_preserves_broader_source_evidence(tmp_path, monkeypatch):
    case = CASES['Luck05']; bib = tmp_path/'library.bib'; bib.write_text(case['entry']['raw'])
    def empty(root):
        root.find(S+'numberOfRecords').text = '0'
        root.remove(root.find(S+'records'))
    narrowed = changed(case['response'], empty)
    narrowed.update(records=[], total_records=0, truncated=False)
    calls = []
    def fetch(cache, client, fields, *, include_year=False):
        calls.append(include_year)
        return narrowed if include_year else competing_broad_response(case)
    monkeypatch.setattr(cr, 'fetch_search', fetch)
    cache = v.Cache(tmp_path/'live.sqlite3'); entry = v.load_entries(bib)['Luck05']
    cache.put(bib, entry, v.outcome('needs_review', ['No registry approval']))
    result = cr.run_catalogue_review(bib, cache, object(), tmp_path/'report')
    assert result['Luck05']['status'] == 'needs_review'
    assert result['Luck05']['catalogue_review']['query'] == search_query(entry['fields'])
    assert len(result['Luck05']['candidates']) == 2 and calls == [False, True]
    assert cr.run_catalogue_review(bib, cache, object(), tmp_path/'report') == result
    assert calls == [False, True]
    cache.close()
