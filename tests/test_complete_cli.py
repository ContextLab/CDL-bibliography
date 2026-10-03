"""Real PTY decisions, real editor executables and frozen response-cache lookups."""
import os
import pty
import subprocess
import sys
from pathlib import Path

import pytest
from cdlbib import api, complete
from cdlbib.workspace import Workspace
from test_complete_identify import client, CONTACT

ROOT = Path(__file__).resolve().parents[1]


def terminal(tmp_path, code, answers, editor=None):
    master, slave = pty.openpty()
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    if editor:
        env['EDITOR'] = str(editor)
        env.pop('VISUAL', None)
    os.write(master, answers.encode())
    try:
        process = subprocess.Popen([sys.executable, '-c', code], cwd=tmp_path, env=env,
                                   stdin=slave, stderr=slave, stdout=subprocess.PIPE, text=True)
        os.close(slave)
        slave = None
        out, _ = process.communicate(timeout=30)
        return process.returncode, out
    finally:
        if slave is not None:
            os.close(slave)
        os.close(master)


def setup(tmp_path, client):
    ws = Workspace(tmp_path)
    ws.bib.write_text('')
    item = complete.propose(complete.Query.parse('10.1002/tea.3660271011'), client, client.cache, ws=ws)
    assert item.complete
    return ws, item


def driver(database, extra=''):
    return f'''
from pathlib import Path
from cdlbib import api, cli, complete, extra_sources
from cdlbib.workspace import Workspace
ws=Workspace(Path.cwd())
client=extra_sources.make_client({str(database)!r},contact={CONTACT!r},offline=True)
item=complete.propose(complete.Query.parse('10.1002/tea.3660271011'),client,client.cache,ws=ws)
{extra}
def recheck(item,raw):
    return api.recheck_proposal(ws,item,raw,mailto={CONTACT!r},database={str(database)!r})
accepted=cli.decide([item],recheck=recheck)
result=api.apply_proposals(ws,accepted)
print('WRITTEN', result.written, 'REFUSED', result.refused)
client.cache.close()
'''


@pytest.mark.parametrize('answer,written', [('a\n',True),('s\n',False),('q\n',False),('A\n',True)])
def test_real_terminal_decisions(tmp_path, client, answer, written):
    ws, item = setup(tmp_path, client)
    code, out = terminal(tmp_path, driver(tmp_path / 'responses.sqlite3'), answer)
    assert code == 0, out
    assert bool(ws.bib.read_text()) is written
    assert 'Verification:' in out


def test_without_terminal_prints_and_writes_nothing(tmp_path, client):
    ws, _ = setup(tmp_path, client)
    result = subprocess.run([sys.executable, '-c',driver(tmp_path/'responses.sqlite3')],
                            cwd=tmp_path, input='', text=True, capture_output=True,
                            env=dict(os.environ,PYTHONPATH=str(ROOT/'src')))
    assert result.returncode == 0, result.stderr
    assert 'nothing was changed' in result.stdout and ws.bib.read_text() == ''


@pytest.mark.parametrize('body,answers,expected', [
    ('pass', 'e\ns\n', 'unchanged'),
    ("p.write_text(p.read_text().replace('Misunderstandings','Confusions').replace('misunderstandings','confusions'))", 'e\na\n', 'confusions'),
])
def test_real_editor(tmp_path, client, body, answers, expected):
    ws, _ = setup(tmp_path, client)
    editor = tmp_path/'editor'
    editor.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nimport sys\np=Path(sys.argv[1])\n{body}\n')
    editor.chmod(0o700)
    code,out=terminal(tmp_path,driver(tmp_path/'responses.sqlite3'),answers,editor)
    assert code == 0,out
    if expected == 'unchanged':
        assert expected in out and not ws.bib.read_text()
    else:
        assert expected in ws.bib.read_text().lower()


def test_edit_reopens_bad_save(tmp_path, client):
    ws,item=setup(tmp_path,client)
    original=tmp_path/'good.bib';original.write_text(item.proposed_raw)
    editor=tmp_path/'editor'
    editor.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nimport sys\np=Path(sys.argv[1]); marker=p.with_suffix(".once")\nif not marker.exists():\n marker.touch();p.write_text("@article{{broken")\nelse:\n p.write_text(Path({str(original)!r}).read_text()+"\\n")\n')
    editor.chmod(0o700)
    code,out=terminal(tmp_path,driver(tmp_path/'responses.sqlite3'),'e\na\n',editor)
    assert code==0,out
    assert 'Reopening' in out and ws.bib.read_text()


def test_stop_keeps_earlier_acceptance_and_all_still_asks(tmp_path, client):
    ws,_=setup(tmp_path,client)
    code=driver(tmp_path/'responses.sqlite3').replace('accepted=cli.decide([item],recheck=recheck)', '''
from dataclasses import replace
second=replace(item,needs_decision=True,issues=['Requires review'])
accepted=cli.decide([item,second],recheck=recheck)
''')
    status,out=terminal(tmp_path,code,'A\nq\n')
    assert status==0,out
    assert 'Requires review' in out and ws.bib.read_text()


def test_edit_missing_required_and_collision_are_not_accepted(tmp_path, client):
    ws,item=setup(tmp_path,client)
    ws.bib.write_text(item.proposed_raw)
    colliding=api.recheck_proposal(ws, item,item.proposed_raw,mailto=CONTACT,database=tmp_path/'responses.sqlite3')
    assert colliding.duplicate_of or any('already exists' in x for x in colliding.issues)
    ws.bib.write_text('')
    raw=complete.render('article',item.key_proposed,{'author':'U Zoller','year':'1990','journal':'Journal','doi':'10.1002/tea.3660271011'})
    missing=api.recheck_proposal(ws,item,raw,mailto=CONTACT,database=tmp_path/'responses.sqlite3')
    assert not missing.complete and any('format check' in x for x in missing.issues)


def test_actual_add_from_file_and_stdin_without_terminal(tmp_path, client):
    ws,item=setup(tmp_path,client)
    identifiers=tmp_path/'queries.txt'
    identifiers.write_text('10.1002/tea.3660271011\n'*3)
    for args,stdin in [(['--from',str(identifiers)],''),([],item.proposed_raw)]:
        result=subprocess.run([sys.executable,'-c','from cdlbib.cli import main; main()',
                               'add',*args,'--mailto',CONTACT,'--database',str(tmp_path/'responses.sqlite3')],
                              cwd=tmp_path,input=stdin,text=True,capture_output=True,
                              env=dict(os.environ,PYTHONPATH=str(ROOT/'src')))
        assert result.returncode==0,result.stdout+result.stderr
        assert 'nothing was changed' in result.stdout and ws.bib.read_text()==''


@pytest.mark.parametrize('answer,writes',[('1\na\n',True),('0\n',False)])
def test_candidate_selection_and_none(tmp_path,client,answer,writes):
    ws,_=setup(tmp_path,client)
    code=driver(tmp_path/'responses.sqlite3').replace('accepted=cli.decide([item],recheck=recheck)', '''
item.candidates=[{'title':'Frozen Zoller record','doi':item.doi}]
def choose(item,candidate):
 return complete.propose(complete.Query.parse(candidate['doi']),client,client.cache,ws=ws)
accepted=cli.decide([item],recheck=recheck,choose_candidate=choose)
''')
    status,out=terminal(tmp_path,code,answer)
    assert status==0,out
    assert 'Frozen Zoller record' in out and bool(ws.bib.read_text())==writes


def test_existing_entry_edit_exact_text(tmp_path,client):
    ws,item=setup(tmp_path,client)
    ws.bib.write_text(item.proposed_raw)
    item.typed_raw,item.key_typed=item.proposed_raw,item.key_proposed
    raw=item.proposed_raw.replace('misunderstandings','confusions')+'\n'
    revised=api.recheck_proposal(ws,item,raw,mailto=CONTACT,database=tmp_path/'responses.sqlite3')
    assert not revised.duplicate_of and not any('already exists' in x for x in revised.issues)
    assert api.apply_proposals(ws,[revised]).written==[item.key_typed]
    assert ws.bib.read_text()==raw
