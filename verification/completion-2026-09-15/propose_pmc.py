"""Freeze PMC/PubMed coordinate repairs for individual source inspection."""
import json
import argparse
from pathlib import Path
import sys
from collections import Counter
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bibcheck'))
from verification import Cache, current_results, load_entries
from pmc_corrections import pmc_coordinate_proposal
HERE = Path(__file__).parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--batch', default='pmccoordinates')
parser.add_argument('--given-names', action='store_true')
args = parser.parse_args()
assert args.batch.isalnum()
path = HERE / (args.batch + '-proposals-initial.json')
assert not path.exists(), 'This frozen proposal set already exists'
held = set()
for file in HERE.glob('*audit-exclusions.json'):
    data = json.loads(file.read_text())
    held.update(data if isinstance(data, dict) else (p['key'] for p in data))
cache = Cache(ROOT / '.bibcheck/verification.sqlite3')
try:
    entries = load_entries(ROOT / 'cdl.bib')
    rows = current_results(ROOT / 'cdl.bib', cache, entries)
    proposals = []
    for key, row in rows.items():
        if key in held or row['status'] != 'needs_review':
            continue
        p = pmc_coordinate_proposal(entries[key], row, include_authors=args.given_names)
        if p:
            proposals.append(p)
            print(json.dumps({k: p[k] for k in ('key','doi','changes')}, ensure_ascii=False), flush=True)
    path.write_text(json.dumps(proposals, indent=2) + '\n')
    print(json.dumps({'proposals': len(proposals), 'changed_fields': dict(Counter(f for p in proposals for f in p['changes']))}), flush=True)
finally:
    cache.close()
