"""Verify a frozen repository-source batch through the production route."""
import argparse,hashlib,json,sys,time
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'bibcheck'))
from verification import ACCEPTED,Cache,current_results,export_snapshot,load_entries,run_lock
from arxiv_review import run_arxiv_review
from preprint_review import checked_body
from verification_cli import DeferredClient
from reassess import export_queue
HERE=Path(__file__).parent;WORK=ROOT/'.bibcheck'/HERE.name

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',required=True);a=p.parse_args();assert a.batch.isalnum()
 sources=json.loads((HERE/f'arxiv-{a.batch}-sources.json').read_text());entries=load_entries(ROOT/'cdl.bib')
 assert all(entries[r['key']]['fingerprint']==r['fingerprint'] for r in sources)
 cache=Cache(ROOT/'.bibcheck/verification.sqlite3')
 try:
  print(json.dumps({'phase':'read_current_results','batch':a.batch}),flush=True)
  before=current_results(ROOT/'cdl.bib',cache,entries)
  backup=WORK/f'before-arxiv-{a.batch}.jsonl.gz'
  if not backup.exists():
   print(json.dumps({'phase':'backup','batch':a.batch}),flush=True)
   export_snapshot(ROOT/'cdl.bib',cache,backup)
  for row in sources:
   for source in row['raw_record'].values():
    if isinstance(source,dict) and 'url' in source:
     checked_body(source,source['url']);cache.save_response('arxiv-source-v1:'+source['url'],source)
  holds_path=HERE/f'arxiv-{a.batch}-holds.json'
  holds=json.loads(holds_path.read_text()) if holds_path.exists() else {}
  assert set(holds)<={r['key'] for r in sources}
  with run_lock(cache):
   for key,finding in holds.items():
    previous=cache.get(ROOT/'cdl.bib',entries[key]);assert previous['status']=='needs_review'
    if previous.get('external_evidence')!=finding:
     cache.put(ROOT/'cdl.bib',entries[key],dict(previous,status='needs_review',external_evidence=finding,issues=['Direct PDF/source conflict requires adjudication']))
     print(json.dumps({'phase':'source_hold','key':key}),flush=True)
  client=DeferredClient(cache,None,1.0,False);keys={r['key'] for r in sources};stages=[]
  for cycle in ('run','repeat'):
   print(json.dumps({'phase':'verify','cycle':cycle,'batch':a.batch}),flush=True)
   start=time.monotonic();calls=client.requests;n=cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]
   after=run_arxiv_review(ROOT/'cdl.bib',cache,client,WORK/f'arxiv-{a.batch}-report.jsonl',keys=keys)
   assert all(after[k]==r for k,r in before.items() if r['status'] in ACCEPTED)
   stage={'cycle':cycle,'seconds':round(time.monotonic()-start,2),'network_requests':client.requests-calls,'review_writes':cache.db.execute('SELECT count(*) FROM reviews').fetchone()[0]-n,'library_statuses':dict(Counter(r['status'] for r in after.values())),'batch_statuses':{k:after[k]['status'] for k in sorted(keys)}}
   if cycle=='repeat':assert after==first and stage['network_requests']==stage['review_writes']==0
   first=after;stages.append(stage);print(json.dumps(stage),flush=True)
  print(json.dumps({'phase':'export','batch':a.batch}),flush=True)
  export_snapshot(ROOT/'cdl.bib',cache,ROOT/'verification/baseline.jsonl.gz');export_queue(entries,after)
  (HERE/f'arxiv-{a.batch}-verification.json').write_text(json.dumps({'stages':stages,'new_approvals':{k:after[k].get('accepted_doi') for k in keys if after[k]['status'] in ACCEPTED and before[k]['status'] not in ACCEPTED}},indent=2)+'\n')
  print(json.dumps({'phase':'complete','batch':a.batch}),flush=True)
 finally:cache.close()
if __name__=='__main__':main()
