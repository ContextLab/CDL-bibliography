"""ACL Anthology route: real Anthology BibTeX and OpenAlex discovery documents.

ReimGure19 verifies on the Anthology's pages 3982--3992 even though Crossref
deposits 3980-3990 (the Anthology outranks Crossref). MikoEtal13b and Etha19
have no identifier; OpenAlex nominates the Anthology paper and the Anthology
record decides. Controls: the Crossref page range, and a different paper's
title under a real DOI.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bibcheck'))
import acl_review as a  # noqa: E402
import verification as v  # noqa: E402

DATA = json.loads((ROOT / 'verification/routes-2026-09-25/fixtures/acl_review.json').read_text())
CONTACT = 'jeremy.r.manning@dartmouth.edu'


def case(key):
    return deepcopy(DATA[key])


def assess(c):
    return a.assess_acl(c['fields'], c['raw'])


def apply(fields, proposal):
    out = dict(fields, **{k: val for k, val in proposal.items() if k != 'remove'})
    for name in proposal.get('remove', []):
        out.pop(name)
    return out


def test_validator_registered_through_hook():
    assert a.valid_acl_approval in v.APPROVAL_VALIDATORS


def test_reimgure19_verifies_with_anthology_pages_and_house_booktitle():
    result = assess(case('ReimGure19'))
    assert result['status'] == 'metadata_verified', result['issues']
    c = result['candidates'][0]
    assert c['anthology_id'] == 'D19-1410' and result['accepted_doi'] == '10.18653/v1/d19-1410'
    assert c['evidence']['pages']['source']['pages'] == '3982--3992'
    assert '2019' in c['evidence']['booktitle']['source']['anthology']  # the house form omits it
    assert a.valid_acl_approval(result) and v.route_approval_valid(result)


def test_control_crossref_page_range_is_corrected_to_the_anthology():
    c = case('ControlAclCrossrefPages')
    result = assess(c)
    assert result['status'] == 'needs_review'
    assert result['candidates'][0]['proposal'] == {'pages': '3982--3992'}


def test_control_other_paper_title_under_real_doi_is_held():
    result = assess(case('ControlAclOtherWork'))
    assert result['candidates'][0]['category'] == 'held' and 'title: missing evidence or mismatch' in result['issues']


def test_mikoetal13b_discovered_and_converted_to_inproceedings():
    c = case('MikoEtal13b')
    cand = assess(c)['candidates'][0]
    assert c['raw']['anthology_id'] == 'N13-1090' and cand['category'] == 'proposal'
    assert cand['proposal']['ENTRYTYPE'] == 'inproceedings' and cand['proposal']['remove'] == ['journal']
    assert cand['proposal']['booktitle'].startswith('Proceedings of the Conference of the North')
    assert '2013' not in cand['proposal']['booktitle']
    after = a.assess_acl(apply(c['fields'], cand['proposal']), c['raw'])
    assert after['status'] == 'metadata_verified', after['issues']


def test_etha19_discovery_skips_index_titles_with_markup():
    c = case('Etha19')
    cand = assess(c)['candidates'][0]
    assert c['raw']['anthology_id'] == 'D19-1006' and cand['category'] == 'proposal'
    assert cand['proposal']['doi'] == '10.18653/v1/D19-1006'


def test_house_booktitle_forms():
    assert a.house_booktitle('Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing '
                             'and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)')[1] == (
        'Proceedings of the Conference on Empirical Methods in Natural Language Processing and the International '
        'Joint Conference on Natural Language Processing')
    # A volume label is not an acronym and is kept.
    assert a.house_booktitle('Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics '
                             '(Volume 3: System Demonstrations)')[0].endswith('(Volume 3: System Demonstrations)')


def test_tampered_record_is_rejected():
    c = case('ReimGure19'); c['raw']['record']['body'] = c['raw']['record']['body'].replace('3982', '3980')
    assert assess(c)['status'] == 'needs_review'


def test_collect_from_saved_documents_makes_no_requests(tmp_path):
    cache = v.Cache(tmp_path / 'routes.sqlite3')
    try:
        for key in ('ReimGure19', 'MikoEtal13b'):
            c = case(key)
            for value in c['raw'].values():
                if isinstance(value, dict) and 'body' in value:
                    cache.save_response('acl-source-v1:' + value['url'], value)
            client = v.PoliteClient(cache, CONTACT)
            assert a.collect(cache, client, c['fields']) == c['raw'] and client.requests == 0
    finally:
        cache.close()


@pytest.mark.parametrize('value,expected', [
    ('10.18653/v1/D19-1410', 'D19-1410'), ('10.3115/v1/P15-1162', 'P15-1162'),
    ('https://aclanthology.org/2022.naacl-main.60/', '2022.naacl-main.60'),
    ('https://aclweb.org/anthology/N/N13/N13-1090.pdf', 'N13-1090')])
def test_identifier_forms(value, expected):
    assert a.parse_id(value) == expected


def test_journal_articles_do_not_apply():
    assert not a.applicable({'ENTRYTYPE': 'article', 'journal': 'Computational Linguistics', 'title': 'x'})
