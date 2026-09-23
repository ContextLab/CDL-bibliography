import sys, json, sqlite3, socket
def _blocked(*a, **k): raise RuntimeError('network blocked')
socket.socket.connect = _blocked
sys.path.insert(0, '/Users/jmanning/CDL-bibliography/bibcheck')
from verification import load_entries, POLICY, normalize_doi
from auto_review import reassess
SP='/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/'
rows=json.load(open(SP+'doiconf/identity_rows.json'))
BIB='/Users/jmanning/CDL-bibliography/cdl.bib'
entries=load_entries(BIB)
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
out={}
for r in rows:
    key=r['key']; e=dict(entries[key]); e['key']=key
    prev=json.loads(db.execute("select result from reviews where bibliography=? and key=? and fingerprint=? and policy=? order by id desc limit 1",(BIB,key,e['fingerprint'],POLICY)).fetchone()[0])
    jv,jp=r['jats']; issue=r['cr'][1]
    f=dict(e['fields']); f['volume']=jv; f['pages']=jp.replace('-','--')
    if issue: f['number']=issue
    else: f.pop('number',None)
    res=reassess(dict(e,fields=f),prev)
    idc=[c for c in res['candidates'] if c.get('doi') and normalize_doi(c['doi'])==r['doi']]
    out[key]={'status':res['status'],'accepted':res.get('accepted_doi'),'issues':res['issues'],
      'cand_issues':{c['source']:c.get('issues') for c in idc},'proposed':{k:f.get(k) for k in ('volume','number','pages')}}
    print(key,res['status'],res.get('accepted_doi')==r['doi'], '' if res['status']=='metadata_verified' else {c['source']:[i[:60] for i in c.get('issues',[])] for c in idc})
json.dump(out,open(SP+'doiconf/simulate.json','w'),indent=1)
import collections; print(collections.Counter(v['status'] for v in out.values()))
