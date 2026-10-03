"""Real PTY decisions, real editor executables and frozen response-cache lookups."""
import os
import pty
import subprocess
import sys
import select
import struct
import termios
import time
import fcntl
from pathlib import Path

import pytest
from cdlbib import api, complete
from cdlbib.workspace import Workspace
from test_complete_identify import client, CONTACT

ROOT = Path(__file__).resolve().parents[1]


def terminal(tmp_path, code, answers, editor=None, *, argv=(), columns=80, extra_env=None):
    """Capture stdout and prompts from a real terminal, without mocked streams."""
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, columns, 0, 0))
    modes = termios.tcgetattr(slave)
    modes[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, modes)
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), COLUMNS=str(columns), LINES='30')
    env.update(refused_network())
    env.update(extra_env or {})
    if editor:
        env['EDITOR'] = str(editor)
        env.pop('VISUAL', None)
    os.write(master, answers.encode())
    process = subprocess.Popen([sys.executable, '-c', code, *argv], cwd=tmp_path, env=env,
                               stdin=slave, stderr=slave, stdout=slave)
    os.close(slave)
    chunks = []
    deadline = time.monotonic() + 35
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            elif process.poll() is not None:
                break
        else:
            process.kill()
            raise AssertionError('PTY timed out: ' + b''.join(chunks).decode(errors='replace'))
        return process.wait(timeout=5), b''.join(chunks).decode(errors='replace').replace('\r\n','\n')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
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
def recheck(item,raw,resolved_fields=()):
    return api.recheck_proposal(ws,item,raw,mailto={CONTACT!r},database={str(database)!r},resolved_fields=resolved_fields)
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


def add_args(tmp_path, *queries):
    return ('add', *queries, '--mailto', CONTACT, '--database', str(tmp_path/'responses.sqlite3'))


ADD = 'from cdlbib.cli import main; main()'


def real_editor(tmp_path, body):
    path=tmp_path/'real-editor'
    path.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nimport sys\np=Path(sys.argv[1])\n{body}\n')
    path.chmod(0o700)
    return path


@pytest.mark.parametrize('edit,finding', [
    ("p.write_text(p.read_text().replace('@article{Zoll90,','@article{Existing90,'))", 'edited key Existing90 already exists'),
    ("p.write_text('\\n'.join(line for line in p.read_text().splitlines() if not line.lstrip().startswith('Title =')))", 'format check could not run'),
])
def test_actual_add_editor_refuses_collision_and_deleted_title(tmp_path,client,edit,finding):
    ws,_=setup(tmp_path,client)
    ws.bib.write_text('@article{Existing90, Author={E Existing}, Title={Other work}, Journal={Journal}, Year={1990}}')
    before=ws.bib.read_bytes()
    editor=real_editor(tmp_path,edit)
    status,out=terminal(tmp_path,ADD,'e\na\ns\n',editor,
                        argv=add_args(tmp_path,'10.1002/tea.3660271011'))
    assert status==0,out
    assert finding in out and 'Cannot accept:' in out
    assert out.count('Your choice [a/e/s/A/q]') == 3
    assert ws.bib.read_bytes()==before and 'Traceback' not in out


@pytest.mark.parametrize('answers,expected', [('1\na\n','Added: SilvEtal19'),('0\n',None)])
def test_actual_add_selected_source_callback(tmp_path,client,answers,expected):
    ws,_=setup(tmp_path,client)
    status,out=terminal(tmp_path,ADD,answers,argv=add_args(tmp_path,'10.1101/511782'))
    assert status==0,out
    assert '[0] none of these' in out and 'Your choice [0/1/2]' in out
    if expected:
        assert expected in out and '10.1523/jneurosci.0360-19.2019' in ws.bib.read_text()
        assert '10.1101/511782' not in ws.bib.read_text()
    else:
        assert ws.bib.read_text()==''


def test_actual_add_unsupported_is_visible_and_refused(tmp_path,client):
    ws,_=setup(tmp_path,client)
    status,out=terminal(tmp_path,ADD,'a\ns\n',argv=add_args(tmp_path,'10.1101/2020.01.27.922062'))
    assert status==1,out
    assert 'Unsupported: posted-content' in out and 'Cannot accept:' in out
    assert out.count('Your choice [a/e/s/A/q]')==2 and not ws.bib.read_text()


def test_actual_add_from_three_distinct_identifiers(tmp_path,client):
    ws,_=setup(tmp_path,client)
    identifiers=tmp_path/'distinct.txt'
    identifiers.write_text('10.1002/tea.3660271011\n10.1037/h0041332\n10.1523/jneurosci.0360-19.2019\n')
    status,out=terminal(tmp_path,ADD,'a\na\na\n',argv=add_args(tmp_path,'--from',str(identifiers)))
    assert status==0,out
    assert out.count('Added:')==3 and out.count('Your choice [a/e/s/A/q]')==3
    from cdlbib.verification import load_entries
    assert set(load_entries(ws.bib))=={'Zoll90','Game62','SilvEtal19'}


def refused_network():
    """Use an unavailable loopback proxy: real requests fail without a provider connection."""
    proxy='http://127.0.0.1:1'
    return {'HTTP_PROXY':proxy,'HTTPS_PROXY':proxy,'ALL_PROXY':proxy,'NO_PROXY':'',
            'http_proxy':proxy,'https_proxy':proxy,'all_proxy':proxy,'no_proxy':''}


@pytest.mark.parametrize('first',['', '10.1002/tea.3660271011'])
def test_actual_add_no_network_and_later_failure(tmp_path,client,first):
    ws,_=setup(tmp_path,client)
    env=refused_network()
    missing='10.9999/completion-cli-missing'
    queries=([first] if first else [])+[missing]
    status,out=terminal(tmp_path,ADD,('a\n' if first else '')+'s\n',
                        argv=add_args(tmp_path,*queries),extra_env=env)
    assert status==1,out
    assert 'lookup failed: a source did not answer' in out.lower() and 'ProxyError' in out
    assert 'Verification: provider_error' in out and 'Traceback' not in out
    if first:
        assert 'Added: Zoll90' in out and '10.1002/tea.3660271011' in ws.bib.read_text()
    else:
        assert ws.bib.read_text()==''


@pytest.mark.parametrize('columns',[99,100])
def test_actual_terminal_width_boundary(tmp_path,client,columns):
    setup(tmp_path,client)
    status,out=terminal(tmp_path,driver(tmp_path/'responses.sqlite3'),'s\n',columns=columns)
    assert status==0,out
    if columns==99:
        assert 'Typed:\n' in out and ' | ' not in out
    else:
        rows=[line for line in out.splitlines() if ' | ' in line]
        assert len(rows)>10
        assert all(len(line)<=columns for line in rows)
        assert all(line.index(' | ')==48 for line in rows)


@pytest.mark.parametrize('choice', ['u', 'k'])
def test_per_name_choices_show_retained_sources_at_real_terminal(tmp_path,client,choice):
    from test_complete_build import sources,RECORDS
    from test_complete_recheck import seed_record
    record,mapped=sources('CleeMcCl91')
    seed_record(client,record)
    ws=Workspace(tmp_path);ws.bib.write_text('')
    raw=complete.render('article','CleeMcCl91',dict(RECORDS['CleeMcCl91']['typed'],doi=record['DOI']))
    path=tmp_path/'typed.bib';path.write_text(raw)
    ws.bib.write_text(raw)
    code=f'''
from pathlib import Path
from cdlbib import api,cli,complete,extra_sources
from cdlbib.verification import load_entries
from cdlbib.workspace import Workspace
ws=Workspace(Path.cwd())
client=extra_sources.make_client({str(tmp_path/'responses.sqlite3')!r},contact={CONTACT!r},offline=True)
query=complete.Query.from_entry(next(iter(load_entries('typed.bib').values())))
import json
record=json.loads(Path({str(ROOT / 'tests/fixtures/completion/records.json')!r}).read_text())['CleeMcCl91']['crossref']['record']
item=complete.build(query.fields,record)
item.typed_raw=query.raw
complete._plan_proposal(ws,item,query,())
complete.checked(item,client)
def recheck(item,raw,resolved_fields=()):
 return api.recheck_proposal(ws,item,raw,mailto={CONTACT!r},database={str(tmp_path/'responses.sqlite3')!r},resolved_fields=resolved_fields)
accepted=cli.decide([item],recheck=recheck)
print('WRITTEN',api.apply_proposals(ws,accepted).written)
client.cache.close()
'''
    status,out=terminal(tmp_path,code,choice+'\n'+('a\n' if choice=='u' else 's\n'))
    assert status==0,out
    assert 'Name: [k] keep typed J L McCleeland / [u] use source J L McClelland' in out
    assert 'Your choice [k/u]' in out
    assert 'author:' in out
    assert 'journal:' in out and '(source: typed)' in out
    if choice=='u':
        assert '(source: user edit)' in out
        assert 'McClelland' in ws.bib.read_text() and 'McCleeland' not in ws.bib.read_text()
    else:
        assert '(source: typed (source alternative: crossref:' in out
        assert ws.bib.read_text()==raw


def test_editor_operation_failure_returns_to_choices_without_traceback(tmp_path,client):
    ws,_=setup(tmp_path,client)
    code=driver(tmp_path/'responses.sqlite3').replace(
        'return api.recheck_proposal(ws,item,raw,mailto=',
        "return api.recheck_proposal(Workspace(Path('missing-library')),item,raw,mailto=")
    editor=real_editor(tmp_path,"p.write_text(p.read_text()+'\\n')")
    status,out=terminal(tmp_path,code,'e\ns\n',editor)
    assert status==0,out
    assert 'Edited entry could not be checked:' in out and 'Returning to choices.' in out
    assert out.count('Your choice [a/e/s/A/q]')==2 and 'Traceback' not in out
    assert ws.bib.read_text()==''


def test_editor_executable_failure_is_recoverable_at_real_terminal(tmp_path,client):
    ws,_=setup(tmp_path,client)
    status,out=terminal(tmp_path,ADD,'e\ns\n',tmp_path/'missing-editor',
                        argv=add_args(tmp_path,'10.1002/tea.3660271011'))
    assert status==0,out
    assert 'Set EDITOR to an executable.' in out and 'Could not start or read the editor:' in out
    assert out.count('Your choice [a/e/s/A/q]')==2 and not ws.bib.read_text()
