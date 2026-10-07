"""Shared API failures and evidence retention with real scanner/files/cache."""
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

import pytest

from cdlbib import api, complete
from cdlbib.errors import CdlbibError, EditedEntryParseError
from cdlbib.verification import dumps
from cdlbib.workspace import Workspace
from test_complete_identify import client, CONTACT
from test_complete_build import sources, RECORDS


def workspace(tmp_path,client):
    ws=Workspace(tmp_path)
    ws.bib.write_text('')
    proposal=complete.propose(complete.Query.parse('10.1002/tea.3660271011'),client,client.cache,ws=ws)
    return ws,proposal


@pytest.mark.parametrize('raw',['@article{broken', '@comment{only comment}',
                               '@article{One,title={First}}\n@article{Two,title={Second}}'])
def test_api_parse_errors_are_typed_and_leave_original_intact(tmp_path,client,raw,capsys):
    ws,item=workspace(tmp_path,client)
    before=deepcopy(item)
    with pytest.raises(EditedEntryParseError):
        api.recheck_proposal(ws,item,raw,mailto=CONTACT,database=tmp_path/'responses.sqlite3')
    assert item==before and ws.bib.read_text()==''
    assert capsys.readouterr().out==''


@pytest.mark.parametrize('failure',['missing-library','malformed-library','database-directory','invalid-contact'])
def test_api_operational_failures_are_cdlbib_errors(tmp_path,client,failure,capsys):
    ws,item=workspace(tmp_path,client)
    before=deepcopy(item)
    database=tmp_path/'responses.sqlite3'
    contact=CONTACT
    if failure=='missing-library':
        ws=Workspace(tmp_path/'absent')
    elif failure=='malformed-library':
        ws.bib.write_text('@article{broken')
    elif failure=='database-directory':
        database=tmp_path/'folder';database.mkdir()
    else:
        contact='invalid'
    with pytest.raises(CdlbibError,match='Edited entry could not be rechecked') as caught:
        api.recheck_proposal(ws,item,item.proposed_raw,mailto=contact,database=database)
    assert not isinstance(caught.value,EditedEntryParseError)
    assert item==before and capsys.readouterr().out==''


def seed_record(client,record):
    """Store a recorded real Crossref deposit with its actual request identity."""
    doi=record['DOI']
    url='https://api.crossref.org/works/'+quote(doi,safe='')
    client.cache.save_response(dumps([url,{},False]),
                               {'body':{'message':record},'url':url,'http_status':200,
                                'retrieved_at':'2026-10-02T00:00:00+00:00'})


def test_recheck_retains_sources_and_marks_actual_edits(tmp_path,client):
    ws,item=workspace(tmp_path,client)
    raw=item.proposed_raw.replace('misunderstandings','confusions')
    revised=api.recheck_proposal(ws,item,raw,mailto=CONTACT,database=tmp_path/'responses.sqlite3')
    original={c.field:c for c in item.changes}
    after={c.field:c for c in revised.changes}
    assert after['author']==original['author'] and after['journal']==original['journal']
    assert after['title'].source=='user edit' and after['title'].typed==original['title'].proposed
    assert revised.proposed_raw==raw and not item.edited_fields


def test_unfilled_source_reason_survives_unrelated_recheck(tmp_path,client):
    ws=Workspace(tmp_path);ws.bib.write_text('')
    record,_=sources('AlyTurk16')
    seed_record(client,record)
    item=complete.build({'doi':record['DOI']},record)
    complete._plan_proposal(ws,item,complete.Query.parse(record['DOI']),())
    missing=next(u for u in item.unfilled if u.field=='pages')
    revised=api.recheck_proposal(ws,item,item.proposed_raw+'\n',mailto=CONTACT,database=tmp_path/'responses.sqlite3')
    assert missing in revised.unfilled
    assert next(c for c in revised.changes if c.field=='journal').source==next(c for c in item.changes if c.field=='journal').source


def test_resolved_surname_retains_other_source_evidence(tmp_path,client):
    ws=Workspace(tmp_path);ws.bib.write_text('')
    record,mapped=sources('CleeMcCl91')
    seed_record(client,record)
    item=complete.build(RECORDS['CleeMcCl91']['typed'],record,mapped)
    fields=complete._completion_fields(item)
    fields['author']=next(c.proposed for c in item.changes if c.field=='author')
    raw=complete.render(item.entry_type,item.key_typed,fields)
    revised=api.recheck_proposal(ws,item,raw,mailto=CONTACT,database=tmp_path/'responses.sqlite3',resolved_fields=('author',))
    assert next(c for c in revised.changes if c.field=='author').source=='user edit'
    assert next(c for c in revised.changes if c.field=='journal')==next(c for c in item.changes if c.field=='journal')
    assert revised.complete
