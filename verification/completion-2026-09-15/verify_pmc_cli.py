"""Exercise normal incremental CLI with real pre-PMC evidence in an isolated cache."""
import gzip
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bibcheck'))
from typer.testing import CliRunner
from verification import Cache, load_entries, current_results
from verification_cli import app

HERE = Path(__file__).parent
WORK = ROOT / '.bibcheck' / HERE.name
with gzip.open(WORK / 'before-pmc-metadata-002.jsonl.gz', 'rt') as stream:
    old = next(row for row in map(json.loads, stream) if row.get('key') == 'BassSuzu17')
assert old['status'] == 'needs_review'
entry = load_entries(ROOT / 'cdl.bib')['BassSuzu17']
live = Cache(ROOT / '.bibcheck/verification.sqlite3')
try:
    response = live.response('pmc-front-v1:PMC5928534', 30 * 86400)
finally:
    live.close()
assert response
with tempfile.TemporaryDirectory(prefix='bibcheck-pmc-cli-') as directory:
    directory = Path(directory)
    bib = directory / 'sample.bib'
    bib.write_text(entry['raw'] + '\n')
    database = directory / 'cache.sqlite3'
    cache = Cache(database)
    cache.put(bib, load_entries(bib)['BassSuzu17'], old)
    cache.save_response('pmc-front-v1:PMC5928534', response)
    cache.close()
    runs = []
    for cycle in ('run', 'repeat'):
        result = CliRunner().invoke(app, ['verify', str(bib), '--database', str(database), '--auto-review'])
        print(result.output, flush=True)
        assert result.exit_code == 0, repr(result.exception)
        assert 'network requests: 0' in result.output.lower()
        cache = Cache(database)
        current = current_results(bib, cache)['BassSuzu17']
        writes = cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
        cache.close()
        assert current['status'] == 'metadata_verified' and current['accepted_source'] == 'pmc-jats'
        runs.append({'cycle': cycle, 'network_requests': 0, 'review_records': writes, 'status': current['status']})
        if cycle == 'repeat':
            assert current == first and writes == runs[0]['review_records']
        first = current
    (HERE / 'pmc-cli-results.json').write_text(json.dumps(runs, indent=2) + '\n')
