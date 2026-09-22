"""Collect frozen arXiv evidence in a separate cache; no approvals or BibTeX edits."""
import argparse,importlib.util,json,sqlite3,sys,time
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'bibcheck'))
from verification import Cache,PoliteClient,load_entries,run_lock
from arxiv_review import identifier,collect,assess_arxiv
from preprint_review import checked_body
HERE=Path(__file__).parent;WORK=ROOT/'.bibcheck'/HERE.name

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',required=True);p.add_argument('--keys',nargs='+',required=True);a=p.parse_args();assert a.batch.isalnum()
 entries=load_entries(ROOT/'cdl.bib');manifest=[{'key':k,'fingerprint':entries[k]['fingerprint'],'identifier':identifier(entries[k]['fields'])[0]} for k in a.keys]
 path=HERE/f'arxiv-{a.batch}-manifest.json'
 if path.exists():assert json.loads(path.read_text())==manifest
 else:path.write_text(json.dumps(manifest,indent=2)+'\n')
 cache=Cache(WORK/'preprints.sqlite3')
 spec=importlib.util.spec_from_file_location('earlier',HERE.parent/'resolution-2026-09-15/run.py');earlier=importlib.util.module_from_spec(spec);spec.loader.exec_module(earlier)
 ro=sqlite3.connect(f'file:{ROOT}/.bibcheck/verification.sqlite3?mode=ro',uri=True);client=PoliteClient(cache,earlier.client_for(SimpleNamespace(db=ro)).mailto,interval=3.1);ro.close()
 try:
  with run_lock(cache):
   for row in json.loads((HERE/'arxiv-source-probe.json').read_text()):
    if row['key'] not in a.keys:continue
    for source in row['sources'].values():
     checked_body(source,source['url']);cache.save_response('arxiv-source-v1:'+source['url'],source)
   stages=[]
   for cycle in ('run','repeat'):
    start=time.monotonic();calls=client.requests;rows=[]
    for item in manifest:
     raw=collect(cache,client,entries[item['key']]['fields']);result=assess_arxiv(entries[item['key']]['fields'],raw)
     rows.append(dict(item,raw_record=raw,preflight={'status':result['status'],'issues':result['issues']}))
     (HERE/f'arxiv-{a.batch}-sources.json').write_text(json.dumps(rows,indent=2)+'\n');print(cycle,item['key'],result['status'],result['issues'],flush=True)
    stage={'cycle':cycle,'entries':len(rows),'seconds':round(time.monotonic()-start,2),'network_requests':client.requests-calls}
    if cycle=='repeat':assert rows==first and stage['network_requests']==0
    first=rows;stages.append(stage);(HERE/f'arxiv-{a.batch}-results.json').write_text(json.dumps(stages,indent=2)+'\n');print(json.dumps(stage),flush=True)
 finally:cache.close()
if __name__=='__main__':main()
