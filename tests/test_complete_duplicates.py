"""Local duplicate and key previews: real parsed temporary BibTeX, no transport."""
import pytest
from cdlbib import complete
from cdlbib.workspace import Workspace
from cdlbib.verification import load_entries

AUTHORS = 'A. Smith and B. Jones and C. Brown'

def fields(title='First paper', **extra):
    return dict(dict(author=AUTHORS, title=title, year='2020'), **extra)

def library(tmp_path, entries=()):
    path = tmp_path / 'cdl.bib'
    path.write_text('\n'.join(complete.render('article', key, data) for key, data in entries))
    return Workspace(tmp_path)

def proposal(key, data):
    return complete.Proposal(key_proposed=key, entry_type='article',
        proposed_raw=complete.render('article', key, data),
        changes=[complete.FieldChange(k, None, v, 'fixture', 'filled') for k, v in data.items()])

@pytest.mark.parametrize('given', ['10.1234/ABC', 'https://doi.org/10.1234/abc'])
def test_doi(tmp_path, given):
    ws = library(tmp_path, [('Other20', fields(doi='10.1234/abc'))])
    assert complete.duplicates(ws, complete.Query(doi=given)) == 'Other20'

def test_title_surnames_and_different_work(tmp_path):
    ws = library(tmp_path, [('Other20', fields(title='{FIRST} paper'))])
    assert complete.duplicates(ws, complete.Query(fields=fields(title='first PAPER', author='X. Smith and Y. Jones and Z. Brown'))) == 'Other20'
    assert complete.duplicates(ws, complete.Query(fields=fields(title='Another paper'))) is None

def test_typed_self_and_elsewhere(tmp_path):
    ws = library(tmp_path, [('SmitEtal20', fields()), ('Other20', fields())])
    query = complete.Query.from_entry(load_entries(ws.bib)['SmitEtal20'])
    assert complete.duplicates(ws, query) == 'Other20'
    ws = library(tmp_path, [('SmitEtal20', fields())])
    assert complete.duplicates(ws, query) is None

@pytest.mark.parametrize('author,key', [('A. Smith','Smit20'), ('A. Smith and B. Jones','SmitJone20'), (AUTHORS,'SmitEtal20'), ('{World Health Organization}','Worl20')])
def test_house_keys(tmp_path, author, key):
    assert complete.plan_key(library(tmp_path), fields(author=author)).key == key

def test_suffixes(tmp_path):
    ws = library(tmp_path, [('SmitEtal20', fields())])
    plan = complete.plan_key(ws, fields('Second paper'))
    assert (plan.key, plan.renames) == ('SmitEtal20b', {'SmitEtal20':'SmitEtal20a'})
    ws = library(tmp_path, [('SmitEtal20a', fields()), ('SmitEtal20b', fields('Second paper'))])
    assert complete.plan_key(ws, fields('Third paper')).key == 'SmitEtal20c'
    assert complete.plan_key(ws, fields('Third paper')).renames == {}

def test_batch_preview(tmp_path):
    ws = library(tmp_path)
    first = proposal('SmitEtal20', fields(doi='10.1234/abc'))
    assert complete.duplicates(ws, complete.Query(doi='10.1234/ABC'), batch=[first]) == 'SmitEtal20'
    plan = complete.plan_key(ws, fields('Second paper'), batch=[first])
    assert (plan.key, plan.renames) == ('SmitEtal20b', {'SmitEtal20':'SmitEtal20a'})
    assert first.key_proposed == 'SmitEtal20'  # previews do not mutate earlier proposals
    second = proposal(plan.key, fields('Second paper'))
    second.renames = plan.renames
    third = complete.plan_key(ws, fields('Third paper'), batch=[first, second])
    assert (third.key, third.renames) == ('SmitEtal20c', {})
    assert complete.plan_key(ws, fields('Second paper')).key == 'SmitEtal20'

@pytest.mark.parametrize('stored,query', [({'pmid':'12345'},complete.Query(pmid='12345')), ({'journal':'arXiv','volume':'2208.02957v1'},complete.Query(arxiv='2208.02957'))])
def test_other_identifiers(tmp_path, stored, query):
    assert complete.duplicates(library(tmp_path, [('Other20', fields(**stored))]), query) == 'Other20'

# Replay saved provider responses through the real offline client/cache, with requests
# disabled by its real transport. This also exercises propose -> checked -> local plan.
from test_complete_identify import client

def test_propose_integrates_library_and_batch(client, tmp_path):
    ws = library(tmp_path)
    query = complete.Query.parse('10.1002/tea.3660271011')
    first = complete.propose(query, client, client.cache, ws=ws)
    assert first.key_proposed == 'Zoll90'
    assert first.renames == {} and first.duplicate_of is None
    second = complete.propose(query, client, client.cache, ws=ws, batch=[first])
    assert second.duplicate_of == 'Zoll90'
    assert second.needs_decision
    ws.bib.write_text(first.proposed_raw)
    third = complete.propose(query, client, client.cache, ws=ws)
    assert third.duplicate_of == 'Zoll90'
    assert client.requests == 0

def test_propose_exact_typed_self(client, tmp_path):
    ws = library(tmp_path)
    first = complete.propose(complete.Query.parse('10.1002/tea.3660271011'), client, client.cache, ws=ws)
    ws.bib.write_text(first.proposed_raw)
    query = complete.Query.from_entry(load_entries(ws.bib)['Zoll90'])
    result = complete.propose(query, client, client.cache, ws=ws)
    assert result.duplicate_of is None
    assert result.key_proposed == 'Zoll90' and result.renames == {}
    assert not any('typed key' in issue for issue in result.issues)
    assert client.requests == 0

def test_typed_key_conflict_independent_of_duplicate(client, tmp_path):
    ws = library(tmp_path, [('TypedKey', fields())])
    query = complete.Query(doi='10.1002/tea.3660271011', key='TypedKey', raw='new typed entry',
        fields={'ENTRYTYPE':'article','ID':'TypedKey','doi':'10.1002/tea.3660271011'})
    result = complete.propose(query, client, client.cache, ws=ws)
    assert result.duplicate_of is None
    assert result.key_proposed == 'Zoll90'
    assert result.needs_decision
    assert any('typed key TypedKey already exists' in issue for issue in result.issues)
    assert client.requests == 0

def test_edited_same_work_key_conflict_still_duplicate(client, tmp_path):
    ws = library(tmp_path, [('TypedKey', fields(doi='10.1002/tea.3660271011'))])
    query = complete.Query(doi='10.1002/tea.3660271011', key='TypedKey', raw='edited entry',
        fields={'ENTRYTYPE':'article','ID':'TypedKey','doi':'10.1002/tea.3660271011'})
    result = complete.propose(query, client, client.cache, ws=ws)
    assert result.duplicate_of == 'TypedKey'
    assert any('typed key TypedKey already exists' in issue for issue in result.issues)
    assert client.requests == 0

def test_unrelated_key_collision_refused(tmp_path):
    ws = library(tmp_path, [('SmitEtal20', fields(author='A. Different'))])
    with pytest.raises(ValueError, match='already belongs'):
        complete.plan_key(ws, fields())

def test_batch_requires_explicit_proposals(tmp_path):
    with pytest.raises(TypeError, match='Proposal objects'):
        complete.plan_key(library(tmp_path), fields(), batch=[fields()])

def test_typed_self_after_preview_rename(tmp_path):
    ws = library(tmp_path, [('SmitEtal20', fields())])
    query = complete.Query.from_entry(load_entries(ws.bib)['SmitEtal20'])
    earlier = proposal('SmitEtal20b', fields('Second paper'))
    earlier.renames = {'SmitEtal20':'SmitEtal20a'}
    assert complete.duplicates(ws, query, batch=[earlier]) is None

def test_unicode_and_latex_title(tmp_path):
    ws = library(tmp_path, [('Other20', fields(title='The {\\"o}ther paper'))])
    assert complete.duplicates(ws, complete.Query(fields=fields(title='The öther paper'))) == 'Other20'

def test_suffix_beyond_z_and_existing_gap(tmp_path):
    from cdlbib.helpers import get_key_suffixes
    entries = [('SmitEtal20'+suffix, fields('Paper '+suffix)) for suffix in get_key_suffixes(26)]
    ws = library(tmp_path, entries)
    assert complete.plan_key(ws, fields('New paper')).key == 'SmitEtal20aa'
    ws = library(tmp_path, [('SmitEtal20a', fields()), ('SmitEtal20c', fields('Second paper'))])
    assert complete.plan_key(ws, fields('Third paper')).key == 'SmitEtal20b'

@pytest.mark.parametrize('author', [None, ''])
def test_editor_only_book_shares_article_key_base(tmp_path, author):
    ws = library(tmp_path)
    book = {'editor': 'A. Smith', 'title': 'Edited book', 'year': '2020'}
    if author is not None:
        book['author'] = author
    ws.bib.write_text(complete.render('book', 'Smit20', book))
    before = ws.bib.read_bytes()
    plan = complete.plan_key(ws, fields(author='A. Smith'))
    assert (plan.key, plan.renames) == ('Smit20b', {'Smit20': 'Smit20a'})
    assert ws.bib.read_bytes() == before
