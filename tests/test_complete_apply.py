"""Accepted writes against real temporary files; no network or mocked I/O."""
import json
import os
import pytest
from cdlbib import api, complete, library
from cdlbib.errors import CdlbibError
from cdlbib.workspace import Workspace
from cdlbib.verification import load_entries
from test_complete_identify import client
from test_complete_duplicates import fields, proposal


def ws_at(tmp_path, text=''):
    ws = Workspace(tmp_path)
    ws.bib.write_bytes(text.encode('utf-8'))
    return ws


def update(raw, key, data):
    item = proposal(key, data)
    item.key_typed, item.typed_raw = key, raw
    return item


@pytest.mark.parametrize('newline,final,bom', [('\n',True,False), ('\r\n',True,True), ('\r\n',False,False), ('\n',False,False)])
def test_preserve_every_untouched_byte(tmp_path, newline, final, bom):
    old = complete.render('article','SmitEtal20',fields()).replace('\n',newline)
    prefix = '% untouched { braces }'+newline+'@string{venue = "Journal"}'+newline+'@preamble{"literal"}'+newline*2
    suffix = newline*2+'@comment{keep SmitEtal20 and {braces}}'+ (newline if final else '')
    ws = ws_at(tmp_path, ('\ufeff' if bom else '')+prefix+old+suffix)
    before = ws.bib.read_bytes()
    item = update(old,'SmitEtal20',fields('Changed title'))
    result = api.apply_proposals(ws,[item])
    new = item.proposed_raw.replace('\n',newline).encode()
    assert result.written == ['SmitEtal20'] and not result.refused and result.backup is None
    assert before.replace(old.encode(),b'',1) == ws.bib.read_bytes().replace(new,b'',1)
    assert load_entries(ws.bib)['SmitEtal20']['fields']['title'] == 'Changed title'


def test_refuse_stale_and_continue(tmp_path):
    ws=ws_at(tmp_path)
    first=proposal('SmitEtal20',fields())
    stale=update('gone','Other20',fields(author='A. Other'))
    third=proposal('Brow20',fields('Third paper',author='C Brown'))
    result=complete.apply(ws,[first,stale,third])
    assert result.written == ['SmitEtal20','Brow20']
    assert result.refused == [('Other20','changed on disk')]
    assert len(load_entries(ws.bib)) == 2
    assert not ws.bib.read_bytes().endswith(b'\n')


def test_exact_text_twice_in_comment_refused(tmp_path):
    raw=complete.render('article','SmitEtal20',fields())
    ws=ws_at(tmp_path,raw+'\n@comment{'+raw+'}')
    before=ws.bib.read_bytes()
    result=complete.apply(ws,[update(raw,'SmitEtal20',fields('Changed'))])
    assert result.refused == [('SmitEtal20','appears 2 times')]
    assert ws.bib.read_bytes()==before


def test_accepted_only_replanning_and_coherent_batch_rename(tmp_path):
    ws=ws_at(tmp_path)
    first=proposal('SmitEtal20',fields())
    second=proposal('SmitEtal20b',fields('Second'))
    second.renames={'SmitEtal20':'SmitEtal20a'}
    result=complete.apply(ws,[second])
    assert result.refused and not result.written and ws.bib.read_bytes()==b''
    result=complete.apply(ws,[first,second])
    assert result.written==['SmitEtal20a','SmitEtal20b'] and not result.refused
    assert set(load_entries(ws.bib))==set(result.written)
    records=json.loads(ws.key_renames.read_text())
    assert records[0]['commit'] is None
    assert records[0]['old_key']=='SmitEtal20'


def test_rename_only_key_token_and_preserve_ledger(tmp_path):
    raw=complete.render('book','Smit20',dict(editor='A. Smith',year='2020',title='Smit20 book'))
    ws=ws_at(tmp_path,'% Smit20\n'+raw+'\n')
    ws.key_renames.parent.mkdir()
    prior={'old_key':'Previous','new_key':'Current','commit':'existing'}
    ws.key_renames.write_text(json.dumps([prior]))
    item=proposal('Smit20b',fields('New paper',author='A. Smith'))
    item.renames={'Smit20':'Smit20a'}
    result=complete.apply(ws,[item])
    assert not result.refused
    assert ws.bib.read_text().startswith('% Smit20\n'+raw.replace('@book{Smit20,','@book{Smit20a,')+'\n')
    assert json.loads(ws.key_renames.read_text())[0]==prior


def test_readonly_prepare_leaves_bib_and_ledger(tmp_path):
    raw=complete.render('article','SmitEtal20',fields())
    ws=ws_at(tmp_path,raw)
    ws.key_renames.parent.mkdir()
    ws.key_renames.write_text('[]\n')
    item=proposal('SmitEtal20b',fields('Second'))
    item.renames={'SmitEtal20':'SmitEtal20a'}
    ws.key_renames.parent.chmod(0o555)
    try:
        with pytest.raises(CdlbibError):
            complete.apply(ws,[item])
        assert ws.bib.read_bytes()==raw.encode()
        assert ws.key_renames.read_bytes()==b'[]\n'
        assert not list(tmp_path.glob('.cdl.bib-*'))
    finally:
        ws.key_renames.parent.chmod(0o755)


def test_real_managed_backup_and_undo():
    library.download()
    ws=Workspace(library.path())
    before=ws.bib.read_bytes()
    item=proposal('SmitEtal20',fields())
    result=complete.apply(ws,[item])
    assert result.backup.path.exists() and result.written==['SmitEtal20']
    library.undo(ws,result.backup.stamp)
    assert ws.bib.read_bytes()==before


def test_frozen_proposal_write_verifier_status(client,tmp_path):
    ws=ws_at(tmp_path)
    item=complete.propose(complete.Query.parse('10.1002/tea.3660271011'),client,client.cache,ws=ws)
    result=complete.apply(ws,[item])
    assert result.written==['Zoll90']
    assert api.check_format(ws).ok
    checked=complete.checked(item,client)
    assert checked.status==item.status and client.requests==0


def test_known_journal_quoted_multiline_workspace(tmp_path):
    ws=ws_at(tmp_path,'@article{X, journal = "Unlisted\n   Local Venue", title={X}}')
    assert complete._known_journal('Unlisted Local Venue',ws.bib)
    other_path=tmp_path / 'other'
    other_path.mkdir()
    other=ws_at(other_path,'@article{Y, title={Other}}')
    assert not complete._known_journal('Unlisted Local Venue',other.bib)


def test_api_incremental_lookup_failure_keeps_success(client,tmp_path):
    ws=ws_at(tmp_path)
    lines=[]
    results=api._proposals(ws,[('good','10.1002/tea.3660271011'),('bad','10.9999/missing')],
                           progress=lines.append,client=client)
    assert len(results)==2 and results[0].proposed_raw
    assert results[1].status=='provider_error' and results.errors[0][0]=='bad'
    assert len(lines)==2 and client.requests==1
    assert not client.session.by_host  # offline transport refused before any network request
    assert ws.bib.read_bytes()==b''


def test_named_library_no_managed_backup(tmp_path):
    ws=Workspace(tmp_path,bib=tmp_path/'named.bib')
    ws.bib.write_bytes(b'')
    result=complete.apply(ws,[proposal('SmitEtal20',fields())])
    assert result.backup is None and not result.refused
    assert not (tmp_path/'cdl.bib').exists()


def test_managed_named_target_refused():
    library.download()
    ws=Workspace(library.path(),bib=library.path()/'other.bib')
    ws.bib.write_bytes(b'')
    try:
        with pytest.raises(CdlbibError,match='cannot protect'):
            complete.apply(ws,[proposal('SmitEtal20',fields())])
        assert ws.bib.read_bytes()==b''
    finally:
        ws.bib.unlink()


def test_api_public_propose_and_new_frozen_cache(client,tmp_path,capsys):
    ws=ws_at(tmp_path)
    results=api.propose_new(ws,['10.1002/tea.3660271011'],mailto='valid@example.org',database=client.cache.path)
    assert len(results)==1 and results[0].status=='metadata_verified' and not results.errors
    # Incomplete typed entry is selected by a real reference bibliography/key-list.
    ws.bib.write_text('@article{Zoll90, Doi = {10.1002/tea.3660271011}}')
    keyfile=tmp_path/'keys.txt'
    keyfile.write_text('Zoll90\n')
    results=api.propose(ws,keys=keyfile,mailto='valid@example.org',database=client.cache.path)
    assert len(results)==1 and results[0].key_typed=='Zoll90' and not results.errors
    assert client.requests==0
    captured=capsys.readouterr()
    assert captured.out==captured.err==''


def test_batch_third_refused_preserves_first_two(tmp_path):
    ws=ws_at(tmp_path)
    first=proposal('SmitEtal20',fields())
    second=proposal('SmitEtal20b',fields('Second'))
    second.renames={'SmitEtal20':'SmitEtal20a'}
    third=proposal('Wrong20',fields('Unrelated',author='C Brown'))
    result=complete.apply(ws,[first,second,third])
    assert result.written==['SmitEtal20a','SmitEtal20b']
    assert result.refused[0][0]=='Wrong20'
    assert len(load_entries(ws.bib))==2


def test_rename_ambiguous_raw_in_comment_refused(tmp_path):
    raw=complete.render('article','SmitEtal20',fields())
    ws=ws_at(tmp_path,'@comment{'+raw+'}\n'+raw)
    before=ws.bib.read_bytes()
    item=proposal('SmitEtal20b',fields('Second'))
    item.renames={'SmitEtal20':'SmitEtal20a'}
    result=complete.apply(ws,[item])
    assert result.refused and ws.bib.read_bytes()==before


def test_duplicate_rechecked_and_editor_key_conflict(tmp_path):
    ws=ws_at(tmp_path,complete.render('article','Other20',fields(doi='10.1234/work')))
    before=ws.bib.read_bytes()
    item=proposal('SmitEtal20',fields('Different title',doi='10.1234/WORK'))
    result=complete.apply(ws,[item])
    assert 'already in the library' in result.refused[0][1]
    assert ws.bib.read_bytes()==before
    raw=complete.render('book','Smit20',dict(editor='A. Smith',title='Editor book',year='2020'))
    ws.bib.write_text(raw)
    item=proposal('Smit20',fields('New article',author='A. Smith'))
    result=complete.apply(ws,[item])
    assert 'plan changed' in result.refused[0][1]
    assert ws.bib.read_text()==raw


def test_api_invalid_contact_error_and_empty_queries(tmp_path):
    ws=ws_at(tmp_path)
    assert api.propose_new(ws,[])==[]
    with pytest.raises(CdlbibError):
        api.propose_new(ws,['10.1234/a'],mailto='invalid')


@pytest.mark.parametrize('keys', [['Zoll90'], ('Zoll90',), {'Zoll90'}])
def test_api_iterable_keys_frozen_cache(client,tmp_path,keys):
    ws=ws_at(tmp_path,'@article{Zoll90, Doi = {10.1002/tea.3660271011}}')
    results=api.propose(ws,keys=keys,mailto='valid@example.org',database=client.cache.path)
    assert len(results)==1 and results[0].key_typed=='Zoll90' and not results.errors
    assert client.requests==0


@pytest.mark.parametrize('keys',[[],['Absent']])
def test_select_keys_iterable_validation(tmp_path,keys):
    from cdlbib.verification_cli import select_keys
    ws=ws_at(tmp_path,complete.render('article','SmitEtal20',fields()))
    with pytest.raises(ValueError,match='Key list is empty or contains'):
        select_keys(ws.bib,keys=keys)


def test_incremental_empty_query_failure_visible(client,tmp_path):
    ws=ws_at(tmp_path)
    results=api._proposals(ws,[('good','10.1002/tea.3660271011'),('bad',None)],client=client)
    assert len(results)==2 and results[0].proposed_raw
    assert results.errors and results[1].issues and results[1].needs_decision
    assert results[1].status is None and client.requests==0


def test_core_is_silent(tmp_path,capsys):
    ws=ws_at(tmp_path)
    complete.apply(ws,[proposal('SmitEtal20',fields())])
    captured=capsys.readouterr()
    assert captured.out==captured.err==''


def test_malformed_ledger_refuses_without_write(tmp_path):
    raw=complete.render('article','SmitEtal20',fields())
    ws=ws_at(tmp_path,raw)
    ws.key_renames.parent.mkdir()
    ws.key_renames.write_text('{"legacy":"mapping"}')
    item=proposal('SmitEtal20b',fields('Second'))
    item.renames={'SmitEtal20':'SmitEtal20a'}
    with pytest.raises(CdlbibError,match='list of records'):
        complete.apply(ws,[item])
    assert ws.bib.read_bytes()==raw.encode()
    assert ws.key_renames.read_text()=='{"legacy":"mapping"}'
