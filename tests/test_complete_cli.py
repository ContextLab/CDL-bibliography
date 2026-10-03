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


def terminal(tmp_path, code, answers, editor=None, *, argv=(), columns=80, extra_env=None, timeout=35):
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
    deadline = time.monotonic() + timeout
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


def verify_command(tmp_path, *extra):
    return ['verify', '--reference', str(tmp_path/'reference.bib'), '--database',
            str(tmp_path/'responses.sqlite3'), '--mailto', CONTACT, *extra]


@pytest.mark.parametrize('answer,completed', [('a\n', True), ('s\n', False), ('q\n', False)])
def test_verify_completion_before_missing_field_gate(tmp_path, client, answer, completed):
    ws, item = setup(tmp_path, client)
    stub = '@article{Game62, doi={10.1037/h0041332}}\n'
    ws.bib.write_text(stub)
    (tmp_path/'reference.bib').write_text('@book{Base20, author={A Smith}, title={Baseline}, year={2020}}\n')
    status, out = terminal(tmp_path, 'from cdlbib.cli import main; main()', answer,
                           argv=verify_command(tmp_path))
    assert ('Completed: Game62' in out) is completed, out
    assert (ws.bib.read_text() != stub) is completed
    assert 'format:' in out or 'errors found' in out
    if completed:
        assert status == 0, out
        assert 'looks good!' in out
    else:
        assert status == 1, out


@pytest.mark.parametrize('flag', ['--no-complete', '--no-citations'])
def test_verify_completion_skip_flags(tmp_path, client, flag):
    ws, _ = setup(tmp_path, client)
    stub = '@article{Zoll90, doi={10.1002/tea.3660271011}}\n'
    ws.bib.write_text(stub)
    (tmp_path/'reference.bib').write_text('@book{Base20, author={A Smith}, title={Baseline}, year={2020}}\n')
    status, out = terminal(tmp_path, 'from cdlbib.cli import main; main()', '',
                           argv=verify_command(tmp_path, flag))
    assert status == 1, out
    assert 'Entry:' not in out and ws.bib.read_text() == stub


def test_verify_completion_without_terminal_preserves_bytes(tmp_path, client):
    ws, _ = setup(tmp_path, client)
    original = b'@article{Zoll90, doi={10.1002/tea.3660271011}}\r\n'
    ws.bib.write_bytes(original)
    (tmp_path/'reference.bib').write_text('@book{Base20, author={A Smith}, title={Baseline}, year={2020}}\n')
    result = subprocess.run([sys.executable, '-c', 'from cdlbib.cli import main; main()',
                             *verify_command(tmp_path)], cwd=tmp_path, input='', text=True,
                            capture_output=True, env=dict(os.environ, PYTHONPATH=str(ROOT/'src'), **refused_network()))
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Entry:' in result.stdout and 'nothing was changed' in result.stdout
    assert ws.bib.read_bytes() == original


def test_verify_autofix_output_copy_preserves_original(tmp_path, client):
    ws, item = setup(tmp_path, client)
    original = item.proposed_raw.replace('1990', '90').encode()
    ws.bib.write_bytes(original)
    (tmp_path/'reference.bib').write_text('@book{Base20, author={A Smith}, title={Baseline}, year={2020}}\n')
    output = tmp_path/'review.bib'
    status, out = terminal(tmp_path, 'from cdlbib.cli import main; main()', '',
                           argv=verify_command(tmp_path, '--autofix', '--outfile', str(output)))
    assert status == 1, out
    assert 'Entry:' not in out and ws.bib.read_bytes() == original
    assert output.exists() and output.read_bytes() != b''


def test_verify_unchanged_entry_has_no_completion_output(tmp_path, client):
    ws, item = setup(tmp_path, client)
    ws.bib.write_text(item.proposed_raw)
    (tmp_path/'reference.bib').write_text(item.proposed_raw)
    status, out = terminal(tmp_path, 'from cdlbib.cli import main; main()', '', argv=verify_command(tmp_path))
    assert status == 0, out
    assert 'Entry:' not in out and 'Completed:' not in out
    assert ws.bib.read_text() == item.proposed_raw


def test_completion_stop_and_outage_keep_first_write(tmp_path, client):
    ws, _ = setup(tmp_path, client)
    (tmp_path/'reference.bib').write_text('@book{Base20, author={A Smith}, title={Baseline}, year={2020}}\n')
    ws.bib.write_text('@article{Zoll90, doi={10.1002/tea.3660271011}}\n'
                      '@article{Fail20, doi={10.5555/unavailable}}\n'
                      '@article{Last21, doi={10.5555/also-unavailable}}\n')
    status, out = terminal(tmp_path, 'from cdlbib.cli import main; main()', 'a\nq\n', argv=verify_command(tmp_path))
    assert status == 1, out
    assert 'Completed: Zoll90' in out and 'unavailable' in out
    assert 'errors found' in out  # gate still runs against accepted plus untouched entries
    from cdlbib.verification import load_entries
    entries = load_entries(ws.bib)
    assert 'title' in entries['Zoll90']['fields']
    assert entries['Fail20']['raw'] == '@article{Fail20, doi={10.5555/unavailable}}'
    assert entries['Last21']['raw'] == '@article{Last21, doi={10.5555/also-unavailable}}'


def test_send_completion_gate_runs_before_any_publication(tmp_path, client):
    ws, _ = setup(tmp_path, client)
    ws.bib.write_text('@article{Zoll90, doi={10.1002/tea.3660271011}}\n')
    reference = tmp_path/'reference.bib'
    reference.write_text('@book{Base20, author={A Smith}, title={Baseline}, year={2020}}\n')
    subprocess.run(['git','init','-q'],cwd=tmp_path,check=True)
    subprocess.run(['git','add','cdl.bib'],cwd=tmp_path,check=True)
    subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.org',
                    'commit','-qm','Local isolated fixture'],cwd=tmp_path,check=True)
    status, out = terminal(tmp_path, 'from cdlbib.cli import main; main()', 'a\n', argv=[
        'send', '--reference', str(reference), '--database', str(tmp_path/'responses.sqlite3'), '--mailto', CONTACT])
    assert status == 1, out
    assert 'Completed: Zoll90' in out and 'not sent:' in out
    assert 'pull request:' not in out
    assert 'Title' in ws.bib.read_text()


@pytest.mark.parametrize('status', ['human_verified', 'metadata_verified'])
def test_verify_current_accepted_entry_never_offered(tmp_path, client, status):
    from cdlbib.verification import load_entries
    ws, item = setup(tmp_path, client)
    # Isolated verdict fixture for these exact bytes, never a real-library approval.
    typed = item.proposed_raw.replace('misunderstandings', 'typed alternative')
    ws.bib.write_text(typed)
    (tmp_path/'reference.bib').write_text('@book{Base20, author={A Smith}, title={Baseline}, year={2020}}\n')
    from cdlbib.verification import Cache
    cache = Cache(tmp_path/'responses.sqlite3', ledger=ws.revocations)
    cache.put(ws.bib, load_entries(ws.bib)['Zoll90'], {'status': status})
    cache.close()
    status_code, out = terminal(tmp_path, 'from cdlbib.cli import main; main()', '', argv=verify_command(tmp_path))
    assert 'Entry:' not in out and 'Completed:' not in out, out
    assert ws.bib.read_text() == typed


def test_completion_retry_keeps_handled_unaccepted_fingerprint(tmp_path, client):
    ws, _ = setup(tmp_path, client)
    ws.bib.write_text('@article{Zoll90, doi={10.1002/tea.3660271011}}\n')
    reference = tmp_path/'reference.bib'
    reference.write_text('@book{Base20, author={A Smith}, title={Baseline}, year={2020}}\n')
    code = f'''
from pathlib import Path
from cdlbib import cli
from cdlbib.workspace import Workspace
cli._completion_seen = set()
ws=Workspace(Path.cwd())
for attempt in range(2):
    cli.offer_completion(ws, reference={str(reference)!r}, database={str(tmp_path/'responses.sqlite3')!r}, mailto={CONTACT!r})
'''
    status, out = terminal(tmp_path, code, 'a\n')
    assert status == 0, out
    assert out.count('Your choice [a/e/s/A/q]') == 1
    assert out.count('Completed: Zoll90') == 1


def test_send_completed_entry_inside_guarded_own_fork(tmp_path, client, monkeypatch):
    """REMOTE MUTATION: controller runs explicitly; only the logged-in user's guarded fork."""
    import datetime
    import json
    from cdlbib import publish
    from cdlbib.verification import load_entries
    from test_publish import (my_fork, fork_clone, clean_up, open_prs, git,
                              TEST_BASE, ZOLL90)
    login, fork = my_fork()
    if login is None:
        pytest.skip(fork)
    # All remote lifecycle machinery and safety guards are the existing publish fixtures.
    monkeypatch.setenv('DEVELOPER_DIR', '/Library/Developer/CommandLineTools')
    work = fork_clone(tmp_path, monkeypatch, fork)
    ws = Workspace(work)
    reference = tmp_path/'completion-base.bib'
    reference.write_text(ZOLL90 + '\n', encoding='utf-8')
    ws.bib.write_text(ZOLL90 + '\n\n@article{Game62, doi={10.1037/h0041332}}\n', encoding='utf-8')
    database = tmp_path/'responses.sqlite3'
    result_path = tmp_path/'send-result.json'
    summary = f'cdlbib completion test {os.getpid()}: please ignore'
    branch = publish.branch_name(login, summary, datetime.date.today())
    publish.assert_safe_test_target(fork, TEST_BASE)
    publish.assert_safe_test_target(fork, branch)
    # Only source lookups use the helper's deliberately unavailable proxy. Restore the
    # caller's original proxy configuration before real guarded GitHub git/gh operations.
    proxy_names = tuple(refused_network())
    original_proxies = {name: os.environ.get(name) for name in proxy_names}
    code = f"""
import json, os
from pathlib import Path
from cdlbib import api, cli
from cdlbib.workspace import Workspace
ws=Workspace(Path.cwd())
cli.offer_completion(ws, reference={str(reference)!r}, database={str(database)!r}, mailto={CONTACT!r})
for name, value in {original_proxies!r}.items():
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
result=api.send(ws, summary={summary!r}, reference={str(reference)!r},
                database={str(database)!r}, mailto={CONTACT!r}, upstream={fork!r},
                fork={fork!r}, base={TEST_BASE!r}, _test_inside_own_fork=True)
Path({str(result_path)!r}).write_text(json.dumps(dict(url=result.url, branch=result.branch, files=result.files)))
print('GUARDED_PULL_REQUEST', result.url)
"""
    url = None
    try:
        status, out = terminal(work, code, 'a\n', timeout=120)
        if result_path.exists():
            result = json.loads(result_path.read_text())
            url = result['url']
        assert status == 0, out
        assert out.count('Completed: Game62') == 1, out
        assert result['branch'] == branch and result['files'] == ['cdl.bib']
        assert url.startswith(f'https://github.com/{fork}/pull/')
        found = open_prs(fork, branch)
        assert [item['url'] for item in found] == [url]
        assert found[0]['baseRefName'] == TEST_BASE
        remote_sha = git(work, 'ls-remote', f'https://github.com/{fork}.git', f'refs/heads/{branch}').split()[0]
        assert remote_sha == git(work, 'rev-parse', 'HEAD')
        # Fetch the actual pushed SHA, then read its blob, rather than trusting the worktree.
        git(work, 'fetch', '-q', 'origin', remote_sha)
        pushed = git(work, 'show', f'{remote_sha}:cdl.bib')
        pushed_file = tmp_path/'pushed-completion.bib'
        pushed_file.write_text(pushed + '\n', encoding='utf-8')
        completed = load_entries(pushed_file)['Game62']
        assert completed['fields']['doi'] == '10.1037/h0041332'
        assert all(completed['fields'].get(field) for field in ('author', 'title', 'year', 'journal'))
        assert pushed == ws.bib.read_text().strip()
    finally:
        # A timeout/failure may occur after opening the PR but before saving its URL.
        # Discover only this test's deterministic owned head, then reuse fixture cleanup.
        try:
            owned = open_prs(fork, branch) if url is None else []
            for item in owned:
                clean_up(work, item['url'], branch)
        finally:
            clean_up(work, url, branch)
