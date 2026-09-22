"""Restore exact approvals altered only by unrelated DOI notice attachment."""
import gzip
import json
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bibcheck'))
from verification import ACCEPTED, Cache, load_entries, run_lock
HERE = Path(__file__).parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--batch', default='003')
batch = parser.parse_args().batch
assert batch.isalnum()
with gzip.open(ROOT / f'.bibcheck/completion-2026-09-15/before-pmc-metadata-{batch}.jsonl.gz', 'rt') as f:
    before = {r['key']: r for r in map(json.loads, f) if 'key' in r}
cache = Cache(ROOT / '.bibcheck/verification.sqlite3')
changes = []
try:
    with run_lock(cache):
        entries = load_entries(ROOT / 'cdl.bib')
        for key, old in before.items():
            if old['status'] not in ACCEPTED:
                continue
            current = cache.get(ROOT / 'cdl.bib', entries[key])
            if current == old:
                continue
            assert {k for k in set(old) | set(current) if old.get(k) != current.get(k)} <= {'checked_at', 'candidates'}, key
            assert all(c in current['candidates'] for c in old['candidates']), key
            added = [c for c in current['candidates'] if c not in old['candidates']]
            accepted = old.get('accepted_doi')
            if not accepted:
                direct = {c['doi'] for c in old['candidates'] if c.get('source') == 'crossref' and c.get('issues') == []}
                assert len(direct) == 1, key
                accepted = next(iter(direct))
            assert added and all(c.get('source') == 'pmc-jats' and c['doi'] != accepted for c in added), key
            assert cache.retain_notices(entries[key], old) == old, key
            cache.store(ROOT / 'cdl.bib', entries[key], old)
            assert cache.get(ROOT / 'cdl.bib', entries[key]) == old
            changes.append({'key': key, 'accepted_doi': accepted, 'unrelated_notice_dois': sorted({c['doi'] for c in added}), 'restored_checked_at': old['checked_at']})
        path = HERE / ('unrelated-notice-audit-repair.json' if batch == '003' else f'unrelated-notice-audit-repair-{batch}.json')
        if not path.exists():
            path.write_text(json.dumps(changes, indent=2) + '\n')
        print(json.dumps(changes), flush=True)
finally:
    cache.close()
