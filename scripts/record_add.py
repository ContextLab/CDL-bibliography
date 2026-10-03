#!/usr/bin/env python3
"""Record the add/edit tutorial against frozen responses and an empty scratch library.

Run with the development environment's Python. --prepare-only creates the isolated
fixture and launchers but does not run add or VHS. The normal run records add.gif
and retains the fixture directory for inspection; no library or provider network
request is permitted. The launcher uses the real CLI and real offline client.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix='cdlbib-add-recording-')).resolve()
    seed = scratch / 'seed'
    seed.mkdir()
    (seed / 'cdl.bib').write_text('', encoding='utf-8')
    environment = dict(os.environ, CDLBIB_HOME=str(scratch / 'home'),
                       CDLBIB_UPSTREAM=str(scratch / 'upstream.git'),
                       CROSSREF_MAILTO='valid@example.org',
                       GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
                       PYTHONPATH=str(repo / 'src'))
    environment.pop('CDLBIB_LIBRARY', None)
    for command in (['git', 'init', '-b', 'master'],
                    ['git', 'config', 'user.name', 'Documentation fixture'],
                    ['git', 'config', 'user.email', 'fixture@example.invalid'],
                    ['git', 'add', 'cdl.bib'], ['git', 'commit', '-m', 'Empty tutorial library'],
                    ['git', 'clone', '--bare', str(seed), str(scratch / 'upstream.git')]):
        subprocess.run(command, cwd=seed, env=environment, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    from cdlbib import library, extra_sources
    from cdlbib.verification import dumps
    # All download/update paths point at the local bare upstream, even if a
    # recorder command unexpectedly falls back to the managed library.
    old = {name: os.environ.get(name) for name in ('CDLBIB_HOME', 'CDLBIB_UPSTREAM')}
    os.environ.update({name: environment[name] for name in old})
    try:
        managed = library.download()
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    database = managed / '.bibcheck' / 'verification.sqlite3'
    client = extra_sources.make_client(database, contact='valid@example.org', offline=True)
    try:
        for row in json.loads((repo / 'tests/fixtures/completion/responses.json').read_text()):
            key = row['request']
            if isinstance(key, list):
                url, params, xml = key
                key = dumps([url, {name: 'valid@example.org' if value == 'CONTACT' else value
                                   for name, value in params.items()}, xml])
            client.cache.save_response(key, row['response'])
        cases = json.loads((repo / 'tests/fixtures/arxiv_preprints.json').read_text())
        for case in cases.values():
            for document in case.get('raw', case).values():
                if isinstance(document, dict) and 'url' in document:
                    client.cache.save_response('arxiv-source-v1:' + document['url'], document)
    finally:
        client.cache.close()
    commands = scratch / 'bin'
    commands.mkdir()
    launcher = commands / 'cdlbib'
    launcher.write_text(f'#!{sys.executable}\n' + '''
from cdlbib import cli, extra_sources
make_client = extra_sources.make_client
def offline_client(*args, **kwargs):
    kwargs['offline'] = True
    return make_client(*args, **kwargs)
extra_sources.make_client = offline_client
cli.main()
''', encoding='utf-8')
    launcher.chmod(0o700)
    editor = commands / 'tutorial-editor'
    editor.write_text(f'#!{sys.executable}\n' + '''
from pathlib import Path
import sys
path = Path(sys.argv[1])
original = path.read_text(encoding='utf-8')
lines = original.splitlines(keepends=True)
saved = ''.join(line for line in lines if not line.lstrip().lower().startswith('number ='))
path.write_text(saved, encoding='utf-8')
print(chr(27) + '[2J' + chr(27) + '[H', end='')
print('Saved entry.bib with the optional issue number omitted.')
''', encoding='utf-8')
    editor.chmod(0o700)
    environment['EDITOR'] = str(editor)
    environment.pop('VISUAL', None)
    environment['PATH'] = str(commands) + os.pathsep + environment['PATH']
    manifest = {'scratch': str(scratch), 'library': str(managed), 'database': str(database),
                'environment': {name: environment[name] for name in
                                ('CDLBIB_HOME', 'CDLBIB_UPSTREAM', 'CROSSREF_MAILTO',
                                 'EDITOR', 'PYTHONPATH', 'PATH')},
                'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
                'provider_mode': 'real response cache; real client offline=True; uncached requests refused',
                'editor_change': 'omit the optional issue number; preserve the remaining proposal text'}
    (scratch / 'recording.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(scratch)
    if args.prepare_only:
        return
    output = (args.output_dir or repo / 'docs/media').resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(['vhs', '-o', str(output / 'add.gif'), str(repo / 'scripts/add.tape')],
                   cwd=managed, env=environment, check=True)
    print(output / 'add.gif')


if __name__ == '__main__':
    main()
