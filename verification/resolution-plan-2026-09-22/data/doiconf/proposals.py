import sys, json, sqlite3, socket, time
def _blocked(*a, **k): raise RuntimeError('network blocked')
socket.socket.connect = _blocked; socket.create_connection=_blocked
sys.path.insert(0, '/Users/jmanning/CDL-bibliography/bibcheck')
from verification import load_entries, POLICY
import correction_proposals as cp, pmc_corrections as pc
from auto_review import reassess
SP='/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/'
group=json.load(open(SP+'group-doi_conflicts.json'))
BIB='/Users/jmanning/CDL-bibliography/cdl.bib'
entries=load_entries(BIB)
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
fns={'pagination':cp.pagination_proposal,'suffix':cp.suffix_proposal,'issue_year':cp.issue_year_proposal,
 'coordinates':cp.coordinate_proposal,'publication':cp.publication_proposal,
 'publication_id':lambda e,p: cp.publication_proposal(e,p,include_identity_fields=True),
 'pmc_coord':pc.pmc_coordinate_proposal,'pmc_names':lambda e,p: pc.pmc_coordinate_proposal(e,p,include_authors=True),
 'pmc_publisher':pc.pmc_publisher_proposal}
for f in ('volume','number','year','author','journal','title'):
    fns['field_'+f]=(lambda f: lambda e,p: cp.field_proposal(e,p,f))(f)
out={}
for g in group:
    key=g['key']; e=dict(entries[key]); e['key']=key
    row=db.execute("select result from reviews where bibliography=? and key=? and fingerprint=? and policy=? order by id desc limit 1",(BIB,key,e['fingerprint'],POLICY)).fetchone()
    prev=json.loads(row[0])
    re_=reassess(e,prev)
    res={'reassess_status':re_['status'],'ext':bool(prev.get('external_evidence'))}
    for n,fn in fns.items():
        try:
            p=fn(e,prev)
        except Exception as ex:
            res[n]='ERR '+repr(ex)[:80]; continue
        if p: res[n]={'kind':p.get('kind'),'doi':p.get('doi'),'changes':p.get('changes')}
    out[key]=res
json.dump(out,open(SP+'doiconf/proposals.json','w'),indent=1)
import collections
c=collections.Counter()
for k,r in out.items():
    hits=[n for n,v in r.items() if isinstance(v,dict)]
    c[tuple(hits)]+=1
    if hits: print(k,{n:r[n]['changes'] for n in hits})
print(c); print(collections.Counter(r['ext'] for r in out.values()), collections.Counter(r['reassess_status'] for r in out.values()))
print([ (k,[v for v in r.values() if isinstance(v,str) and v.startswith('ERR')]) for k,r in out.items() if any(isinstance(v,str) and v.startswith('ERR') for v in r.values())][:5])
