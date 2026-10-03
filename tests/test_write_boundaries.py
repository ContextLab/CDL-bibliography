"""Real local files, processes, PTYs and bare git; no remote provider or GitHub calls."""
import os
from pathlib import Path
import select
import subprocess
import sys
import time

import pytest

from cdlbib import api, complete, library, publish
from cdlbib.errors import CdlbibError, PublishRefused
from cdlbib.workspace import Workspace
from cdlbib.verification import load_entries
from test_complete_duplicates import fields, proposal
from test_complete_identify import client, CONTACT
from test_complete_cli import terminal, refused_network
from test_library import managed
from test_publish import checkout, git, state, GIT_ENV


def child(code, cwd):
    return subprocess.Popen([sys.executable, '-u', '-c', code], cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=dict(os.environ, **GIT_ENV))


def line(process):
    assert select.select([process.stdout], [], [], 15)[0], 'child did not reach checkpoint'
    return process.stdout.readline().strip()


PROPOSAL = '''
from cdlbib import complete, library
from cdlbib.workspace import Workspace
fields=dict(author='A Smith', title='A new paper', journal='Nature', year='2020')
item=complete.Proposal(key_proposed='Smit20', entry_type='article',
    proposed_raw=complete.render('article','Smit20',fields),
    changes=[complete.FieldChange(k,None,v,'fixture','filled') for k,v in fields.items()])
ws=Workspace(library.path())
'''


def test_update_owns_read_through_completion_replacement(managed):
    ws = Workspace(library.download())
    upstream = Path(os.environ['CDLBIB_UPSTREAM'])
    source = upstream.parent / 'upstream-work'
    (source / 'cdl.bib').write_text(ws.bib.read_text() + '% upstream must survive\n')
    git(source, 'add', 'cdl.bib'); git(source, 'commit', '-qm', 'upstream edit')
    git(source, 'push', '-q', str(upstream), 'master')
    with library.transaction(ws):
        process = child(PROPOSAL + "print('ready', flush=True)\nprint(complete.apply(ws,[item]).written)\n", ws.root)
        try:
            assert line(process) == 'ready'
            time.sleep(.25)
            assert process.poll() is None and not list(ws.root.glob('.cdl.bib-*'))
            assert library.update(ws, force=True).action == 'updated'
            assert 'upstream must survive' in ws.bib.read_text()
        except BaseException:
            process.kill(); process.wait()
            raise
    out, err = process.communicate(timeout=20)
    assert process.returncode == 0, err
    assert "['Smit20']" in out
    assert 'upstream must survive' in ws.bib.read_text()
    assert 'Smit20' in load_entries(ws.bib)


def test_real_kill_between_bibliography_and_rename_ledger_recovers(managed):
    ws = Workspace(library.download())
    raw = complete.render('article', 'Smit20', fields(author='A Smith'))
    ws.bib.write_text(raw + '\n')
    before = ws.bib.read_bytes()
    code = PROPOSAL + '''
import sys, os, signal
item.key_proposed='Smit20b'
item.proposed_raw=complete.render('article','Smit20b',fields)
item.renames={'Smit20':'Smit20a'}
def audit(event,args):
    if event == 'os.rename' and str(args[1]) == str(ws.key_renames):
        print('between replacements',flush=True)
        signal.pause()
sys.addaudithook(audit)
complete.apply(ws,[item])
'''
    process = child(code, ws.root)
    try:
        assert line(process) == 'between replacements'
        assert ws.bib.read_bytes() != before and not ws.key_renames.exists()
        process.kill(); process.wait(timeout=5)
        stamp = library.interrupted()
        assert stamp
        with pytest.raises(CdlbibError, match='interrupted'):
            complete.apply(ws, [])
        restored, _ = library.undo(ws)
        assert restored.stamp == stamp and ws.bib.read_bytes() == before
        assert not ws.key_renames.exists() and library.interrupted() is None
    finally:
        if process.poll() is None:
            process.kill(); process.wait()


def test_checkpoint_survives_twelve_acceptances_and_retention(managed):
    ws = Workspace(library.download())
    before = ws.bib.read_bytes()
    with library.completion_batch(ws) as batch:
        for n in range(12):
            item = proposal(f'Smit{20+n}', fields(f'Distinct paper {n}', author='A Smith', year=str(2020+n)))
            result = api.apply_proposals(ws, [item], batch=batch)
            assert result.written == [f'Smit{20+n}'] and not result.refused
            assert result.backup == batch.checkpoint
            # Real backup/prune pressure while the command's checkpoint remains active.
            library.backup(ws)
        # An acceptance re-designates the command checkpoint even after another backup.
        result = api.apply_proposals(ws, [proposal('Smit32', fields('Last', author='A Smith', year='2032'))], batch=batch)
        checkpoint = batch.checkpoint
    assert checkpoint.path.is_dir()
    chosen, _ = library.undo(ws)
    assert chosen.stamp == checkpoint.stamp and ws.bib.read_bytes() == before


@pytest.mark.parametrize('ending', ['stop', 'outage', 'finish'])
def test_actual_managed_command_undo_is_whole_batch(managed, tmp_path, client, ending):
    ws = Workspace(library.download())
    ws.bib.write_text('')
    before = ws.bib.read_bytes()
    queries = ['10.1002/tea.3660271011', '10.1037/h0041332']
    answers = 'a\na\n'
    if ending == 'stop':
        queries += ['10.1523/jneurosci.0360-19.2019']; answers += 'q\n'
    elif ending == 'outage':
        queries += ['10.9999/no-record']; answers += 's\n'
    status, out = terminal(tmp_path, 'from cdlbib.cli import main; main()', answers, argv=[
        '--library', str(ws.root), 'add', *queries, '--database', str(client.cache.path), '--mailto', CONTACT])
    assert status == (1 if ending == 'outage' else 0), out
    assert out.count('Added:') == 2 and out.count('Batch backup:') == 1
    assert set(load_entries(ws.bib)) == {'Zoll90', 'Game62'}
    restored, _ = library.undo(ws)
    assert restored.stamp in out and ws.bib.read_bytes() == before


@pytest.mark.parametrize('choice,removed', [('r', True), ('k', False)])
def test_typed_duplicate_explicit_terminal_removal_and_keep(managed, tmp_path, client, choice, removed):
    ws = Workspace(library.download())
    raw = ws.bib.read_text().strip().replace('@article{Zoll90,', '@article{New90,')
    ws.bib.write_text('% prefix\n' + ws.bib.read_text() + '\n' + raw + '\n% suffix\n')
    before = ws.bib.read_bytes()
    code = f'''
from cdlbib import api, cli, complete, extra_sources, library
from cdlbib.workspace import Workspace
from cdlbib.verification import load_entries
ws=Workspace({str(ws.root)!r})
client=extra_sources.make_client({str(client.cache.path)!r},contact={CONTACT!r},offline=True)
query=complete.Query.from_entry(load_entries(ws.bib)['New90'])
item=complete.propose(query,client,client.cache,ws=ws)
accepted=cli.decide([item])
result=api.apply_proposals(ws,accepted)
print('REMOVED',result.removed,'REFUSED',result.refused)
'''
    status, out = terminal(tmp_path, code, choice+'\n')
    assert status == 0, out
    assert '[r] remove this typed duplicate' in out and '[k] keep both for the formatter' in out
    assert ws.bib.read_bytes() == (before.replace(raw.encode(), b'', 1) if removed else before)
    if removed:
        assert "REMOVED ['New90'] REFUSED []" in out
        library.undo(ws)
        assert ws.bib.read_bytes() == before
    else:
        assert 'REMOVED []' in out and not api.check_format(ws).ok


def test_stale_duplicate_removal_and_new_add_duplicate_cannot_delete(tmp_path):
    ws = Workspace(tmp_path)
    raw = complete.render('article', 'New20', fields())
    other = complete.render('article', 'Smit20', fields())
    ws.bib.write_text(other + '\n' + raw)
    item = proposal('New20', fields())
    item.typed_raw, item.key_typed, item.duplicate_of, item.remove_duplicate = raw, 'New20', 'Smit20', True
    ws.bib.write_text(other + '\n' + raw.replace('Title', 'title'))
    before = ws.bib.read_bytes()
    assert complete.apply(ws, [item]).refused
    item.typed_raw = None
    assert complete.apply(ws, [item]).refused
    assert ws.bib.read_bytes() == before


@pytest.mark.parametrize('alias', ['bib', 'reference', 'database', 'evidence', 'git', 'symlink', 'hardlink', 'git-hardlink'])
def test_summary_alias_refused_before_gate_or_write(checkout, tmp_path, alias):
    ws, _ = checkout
    reference = tmp_path / 'reference.bib'; reference.write_bytes(ws.bib.read_bytes())
    ws.database.parent.mkdir(); ws.database.write_bytes(b'cache bytes')
    evidence = ws.key_renames
    destinations = dict(bib=ws.bib, reference=reference, database=ws.database, evidence=evidence,
                        git=ws.root/'.git'/'config')
    if alias in ('symlink', 'hardlink', 'git-hardlink'):
        dest = tmp_path / alias
        target = ws.root/'.git'/'config' if alias == 'git-hardlink' else ws.bib
        dest.symlink_to(target) if alias == 'symlink' else os.link(target, dest)
    else:
        dest = destinations[alias]
    before = {p: p.read_bytes() for p in [ws.bib, reference, ws.database, evidence, ws.root/'.git'/'config']}
    with pytest.raises(CdlbibError, match='Summary output'):
        api.send(ws, reference=str(reference), outfile=str(dest), citations=False)
    assert {p: p.read_bytes() for p in before} == before


def test_named_send_rejected_before_completion_cli(checkout, tmp_path):
    ws, _ = checkout
    other = ws.root/'other.bib'; other.write_text('@article{New, doi={10.1/a}}')
    before = other.read_bytes()
    with pytest.raises(PublishRefused, match='canonical tracked'):
        api.send(Workspace.for_bib(other), citations=False)
    status, out = terminal(ws.root, 'from cdlbib.cli import main; main()', '', argv=['send', '--fname', str(other)])
    assert status != 0 and 'canonical tracked' in out and 'Your choice' not in out
    assert other.read_bytes() == before


@pytest.mark.parametrize('deleted,resumed', [(False, False), (True, False), (False, True), (True, True)])
def test_entire_outgoing_history_refuses_private_commits(checkout, deleted, resumed):
    ws, remote = checkout
    branch = 'cdlbib/test/history'
    if resumed:
        git(ws.root, 'switch', '-c', branch)
    secret = ws.root/'private-notes.txt'; secret.write_text('not for publication\n')
    git(ws.root, 'add', secret.name); git(ws.root, 'commit', '-qm', 'private notes')
    if deleted:
        git(ws.root, 'rm', secret.name); git(ws.root, 'commit', '-qm', 'remove notes')
    ws.bib.write_text('% candidate\n')
    before = state(ws.root)
    with pytest.raises(PublishRefused, match='Outgoing commit.*private-notes'):
        publish.deliver(ws, branch, 'candidate', str(remote))
    assert state(ws.root) == before
    assert not git(remote, 'for-each-ref', '--format=%(refname)', 'refs/heads/cdlbib/')


def test_existing_branch_different_bibliography_is_not_sent(checkout):
    ws, remote = checkout
    branch = 'cdlbib/test/older'
    git(ws.root, 'switch', '-c', branch)
    ws.bib.write_text('% unchecked branch content\n')
    git(ws.root, 'add', 'cdl.bib'); git(ws.root, 'commit', '-qm', 'other bibliography')
    git(ws.root, 'switch', 'master')
    (ws.root/'verification'/'new.json').write_text('{}\n')
    checked = publish.candidate(ws)
    before = state(ws.root)
    with pytest.raises(PublishRefused, match='changed after the gate'):
        publish.deliver(ws, branch, 'evidence only', str(remote), expected=checked)
    assert state(ws.root) == before and publish.candidate(ws) == checked
    assert not git(remote, 'for-each-ref', '--format=%(refname)', 'refs/heads/cdlbib/')


def test_commit_hook_cannot_publish_unchecked_bytes(checkout):
    ws, remote = checkout
    ws.bib.write_text('% checked\n')
    hook = ws.root/'.git'/'hooks'/'pre-commit'
    hook.write_text("#!/bin/sh\nprintf '%s\\n' '% hook changed candidate' > cdl.bib\ngit add cdl.bib\n")
    hook.chmod(0o755)
    with pytest.raises(PublishRefused, match='changed after the gate'):
        publish.deliver(ws, 'cdlbib/test/hook', 'candidate', str(remote))
    assert not git(remote, 'for-each-ref', '--format=%(refname)', 'refs/heads/cdlbib/')


@pytest.mark.parametrize('input_args,stdin', [(['--from', 'absent.txt'], ''), ([], 'malformed @article{')])
def test_input_errors_are_concise(tmp_path, input_args, stdin):
    (tmp_path/'cdl.bib').write_text('')
    run = subprocess.run([sys.executable, '-c', 'from cdlbib.cli import main; main()', 'add', *input_args],
                         cwd=tmp_path, input=stdin, text=True, capture_output=True, env=dict(os.environ, **refused_network()))
    assert run.returncode != 0 and 'Could not read entry input' in run.stderr
    assert 'Traceback' not in run.stderr


def test_gate_rejects_evidence_changed_by_frontend_progress(checkout, tmp_path):
    from conftest import ZOLL90
    ws, _ = checkout
    ws.bib.write_text(ZOLL90 + '\n')
    reference = tmp_path/'reference.bib'; reference.write_text(ZOLL90 + '\n')
    def progress(line):
        if line.startswith('checks passed'):
            ws.database.parent.mkdir(exist_ok=True)
            ws.database.write_bytes(b'changed evidence after checks')
    with pytest.raises(PublishRefused, match='database or reference changed after the gate'):
        api.send(ws, citations=False, reference=str(reference), progress=progress)
    assert publish.current_branch(ws) == 'master'


def test_selected_key_disappears_between_real_reads_is_typed(tmp_path, client):
    from conftest import ZOLL90
    ws = Workspace(tmp_path)
    ws.bib.write_text(ZOLL90 + '\n@book{Remain, title={Other}, year={2020}}\n')
    code = f'''
import sys
from pathlib import Path
from cdlbib import api
from cdlbib.errors import CdlbibError
from cdlbib.workspace import Workspace
ws=Workspace({str(ws.root)!r})
reads=0
def audit(event,args):
    global reads
    if event=='open' and str(args[0])==str(ws.bib) and args[1]=='r':
        reads+=1
        if reads==2:
            ws.bib.write_text('@book{{Remain, title={{Other}}, year={{2020}}}}')
sys.addaudithook(audit)
try:
    api.propose(ws,keys=['Zoll90'],database={str(client.cache.path)!r},mailto={CONTACT!r})
except CdlbibError as exc:
    print(type(exc).__name__,str(exc))
else:
    raise AssertionError('Expected selection failure')
'''
    run = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, capture_output=True, text=True,
                         env=dict(os.environ, **refused_network()))
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'CdlbibError Entries could not be selected for completion' in run.stdout
    assert 'Traceback' not in run.stderr


def test_empty_decisions_are_silent(tmp_path):
    run = subprocess.run([sys.executable, '-c', 'from cdlbib.cli import decide; assert decide([])==[]'],
                         cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0 and run.stdout == '' and run.stderr == ''
