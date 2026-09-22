"""Collect bounded, cached repository evidence; never approve or edit citations."""
import argparse,hashlib,importlib.util,json,re,sqlite3,sys,time
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'bibcheck'))
from verification import Cache,PoliteClient,ProviderError,load_entries,normalized,now,run_lock
from preprint_review import identifier
HERE=Path(__file__).parent;WORK=ROOT/'.bibcheck'/HERE.name

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',required=True);p.add_argument('--keys',nargs='+',required=True);a=p.parse_args()
 assert a.batch.isalnum()
 entries=load_entries(ROOT/'cdl.bib'); manifest=[]
 for key in a.keys:
  e=entries[key];f=e['fields'];assert normalized(f['journal'])=='biorxiv'
  doi,_,_=identifier(f)
  manifest.append({'key':key,'fingerprint':e['fingerprint'],'doi':doi})
 mp=HERE/f'preprint-{a.batch}-manifest.json'
 if mp.exists():assert json.loads(mp.read_text())==manifest
 else:mp.write_text(json.dumps(manifest,indent=2)+'\n')
 cache=Cache(WORK/'preprints.sqlite3')
 spec=importlib.util.spec_from_file_location('earlier',HERE.parent/'resolution-2026-09-15/run.py');earlier=importlib.util.module_from_spec(spec);spec.loader.exec_module(earlier)
 ro=sqlite3.connect(f'file:{ROOT}/.bibcheck/verification.sqlite3?mode=ro',uri=True)
 client=PoliteClient(cache,earlier.client_for(SimpleNamespace(db=ro)).mailto,interval=3.1);ro.close()
 try:
  with run_lock(cache):
   summaries=[]
   for cycle in ('run','repeat'):
    start=time.monotonic();calls=client.requests;rows=[]
    for item in manifest:
     doi=item['doi'];url='https://api.biorxiv.org/details/biorxiv/'+doi+'/na/json';identity='biorxiv-details-v1:'+doi
     source=cache.response(identity,30*86400)
     if source is None:
      r=client.source_request(url,timeout=(10,45),allow_redirects=False,stream=True)
      try:
       if r.status_code!=200:raise ProviderError(f'bioRxiv HTTP {r.status_code}')
       raw=bytearray()
       for chunk in r.iter_content(65536):
        raw.extend(chunk)
        if len(raw)>2_000_000:raise ProviderError('Oversize bioRxiv response')
       body=bytes(raw).decode('utf-8-sig');data=json.loads(body)
       if not isinstance(data,dict) or not isinstance(data.get('messages'),list) or not isinstance(data.get('collection'),list):raise ProviderError('Malformed bioRxiv envelope')
       if len(data['messages'])!=1 or data['messages'][0].get('status')!='ok':raise ProviderError('bioRxiv lookup did not succeed')
       source={'url':r.url,'doi':doi,'body':body,'document_sha256':hashlib.sha256(body.encode()).hexdigest(),'retrieved_at':now()};cache.save_response(identity,source)
      finally:r.close()
     assert hashlib.sha256(source['body'].encode()).hexdigest()==source['document_sha256']
     data=json.loads(source['body']);rows.append(dict(item,source=source))
     (HERE/f'preprint-{a.batch}-sources.json').write_text(json.dumps(rows,indent=2)+'\n')
     print(cycle,item['key'],len(data['collection']),'versions',flush=True)
    summary={'cycle':cycle,'entries':len(rows),'seconds':round(time.monotonic()-start,2),'network_requests':client.requests-calls};summaries.append(summary)
    if cycle=='repeat':assert rows==first and summary['network_requests']==0
    first=rows;(HERE/f'preprint-{a.batch}-results.json').write_text(json.dumps(summaries,indent=2)+'\n');print(json.dumps(summary),flush=True)
 finally:cache.close()
if __name__=='__main__':main()
