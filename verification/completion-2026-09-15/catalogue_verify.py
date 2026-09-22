"""Apply the production catalogue layer to a frozen, inspected source batch."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bibcheck'))
from catalogue_discovery import parse_search, search_query
from catalogue_review import run_catalogue_review
from verification import ACCEPTED, Cache, current_results, export_snapshot, load_entries
from verification_cli import DeferredClient
from reassess import export_queue

HERE = Path(__file__).parent
WORK = ROOT / '.bibcheck' / HERE.name


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',required=True)
    parser.add_argument('--label',help='Distinct artifact label when reassessing a completed source batch')
    args=parser.parse_args()
    assert args.batch.isalnum()
    label=args.label or args.batch
    assert label.isalnum()
    selected=json.loads((HERE/f'catalogue-{args.batch}-manifest.json').read_text())
    sources=json.loads((HERE/f'catalogue-{args.batch}-sources.json').read_text())
    assert len(selected)==len(sources) and [r['key']for r in selected]==[r['key']for r in sources]
    entries=load_entries(ROOT/'cdl.bib')
    assert all(entries[r['key']]['fingerprint']==r['fingerprint']for r in selected)
    cache=Cache(ROOT/'.bibcheck/verification.sqlite3')
    try:
        before=current_results(ROOT/'cdl.bib',cache,entries)
        backup=WORK/f'before-catalogue-{label}.jsonl.gz'
        if not backup.exists():export_snapshot(ROOT/'cdl.bib',cache,backup)
        for row in sources:
            response=row['source'];query=response['query'];fields=entries[row['key']]['fields']
            assert query in {search_query(fields,include_year=year,fold_diacritics=fold)
                            for year in (False,True) for fold in (False,True)}
            assert hashlib.sha256(response['raw_xml'].encode()).hexdigest()==response['document_sha256']
            parse_search(response['raw_xml'],query)
            cache.save_response('loc-sru-v1:10:'+query,response)
        client=DeferredClient(cache,None,1.0,False)
        keys={r['key']for r in selected};stages=[]
        for cycle in ('run','repeat'):
            start=time.monotonic();calls=client.requests
            writes=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
            after=run_catalogue_review(ROOT/'cdl.bib',cache,client,WORK/f'catalogue-{label}-report.jsonl',keys=keys)
            assert all(after[k]==r for k,r in before.items()if r['status']in ACCEPTED)
            stage={'cycle':cycle,'seconds':round(time.monotonic()-start,2),'network_requests':client.requests-calls,
                   'review_writes':cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]-writes,
                   'statuses':dict(Counter(r['status']for r in after.values()))}
            if cycle=='repeat':assert after==first and stage['network_requests']==stage['review_writes']==0
            first=after;stages.append(stage);print(json.dumps(stage),flush=True)
        export_snapshot(ROOT/'cdl.bib',cache,ROOT/'verification/baseline.jsonl.gz');export_queue(entries,after)
        (HERE/f'catalogue-{label}-verification.json').write_text(json.dumps({'stages':stages,
            'new_approvals':{k:r.get('accepted_record_id')for k,r in after.items()if r['status']in ACCEPTED and before[k]['status']not in ACCEPTED}},indent=2)+'\n')
    finally:cache.close()


if __name__=='__main__':main()
