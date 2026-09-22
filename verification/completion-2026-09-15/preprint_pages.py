"""Collect exact repository version pages into the separate preprint cache."""
import argparse,importlib.util,json,sqlite3,sys,time
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'bibcheck'))
from verification import Cache,PoliteClient,load_entries,run_lock
from preprint_review import fetch_document,html_url,identifier,versions
HERE=Path(__file__).parent;WORK=ROOT/'.bibcheck'/HERE.name

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',required=True);a=p.parse_args();assert a.batch.isalnum()
 sources=json.loads((HERE/f'preprint-{a.batch}-sources.json').read_text());entries=load_entries(ROOT/'cdl.bib')
 cache=Cache(WORK/'preprints.sqlite3')
 spec=importlib.util.spec_from_file_location('earlier',HERE.parent/'resolution-2026-09-15/run.py');earlier=importlib.util.module_from_spec(spec);spec.loader.exec_module(earlier)
 ro=sqlite3.connect(f'file:{ROOT}/.bibcheck/verification.sqlite3?mode=ro',uri=True);client=PoliteClient(cache,earlier.client_for(SimpleNamespace(db=ro)).mailto,interval=3.1);ro.close()
 try:
  with run_lock(cache):
   summaries=[]
   for cycle in ('run','repeat'):
    start=time.monotonic();calls=client.requests;rows=[]
    for row in sources:
     e=entries[row['key']];assert e['fingerprint']==row['fingerprint']
     doi,explicit,_=identifier(e['fields']);history=versions(row['source'],doi);version=explicit or (1 if len(history)==1 else None)
     if not version:continue
     url=html_url(doi,version);html=fetch_document(cache,client,url,'biorxiv-html-v1:'+url)
     rows.append(dict(row,html=html));(HERE/f'preprint-{a.batch}-pages.json').write_text(json.dumps(rows,indent=2)+'\n');print(cycle,row['key'],len(html['body']),flush=True)
    summary={'cycle':cycle,'pages':len(rows),'seconds':round(time.monotonic()-start,2),'network_requests':client.requests-calls}
    if cycle=='repeat':assert rows==first and summary['network_requests']==0
    first=rows;summaries.append(summary);(HERE/f'preprint-{a.batch}-pages-results.json').write_text(json.dumps(summaries,indent=2)+'\n');print(json.dumps(summary),flush=True)
 finally:cache.close()
if __name__=='__main__':main()
