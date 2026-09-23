import json, sqlite3, sys, difflib, re
sys.path.insert(0, '/Users/jmanning/CDL-bibliography/bibcheck')
from verification import normalize_doi
S='/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/'
ex=json.load(open(S+'notices/extracted.json'))
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
def fam(src):
    if isinstance(src,list):
        return [ (a.get('family') or a.get('lastName') or a.get('name') or str(a))[:30] if isinstance(a,dict) else str(a)[:30] for a in src]
    return str(src)[:300]
def norm(s): return re.sub(r'[^a-z0-9 ]','',re.sub(r'\\[a-z]+|[{}]','',str(s).lower()))
res={}
for x in ex:
    r=json.loads(db.execute('select result from reviews where id=?',(x['review_id'],)).fetchone()[0])
    det={}
    for f in x['flagged']:
        cs=[c for c in r['candidates'] if c.get('doi') and normalize_doi(c['doi'])==f and c.get('evidence')]
        cs.sort(key=lambda c:-sum(1 for v in c['evidence'].values() if v.get('match')))
        if not cs: det[f]={'none':True}; continue
        c=cs[0]; ev=c['evidence']
        st=c.get('record',{}).get('title'); st=st[0] if isinstance(st,list) and st else st
        sim=difflib.SequenceMatcher(None,norm(x['fields'].get('title','')),norm(st)).ratio()
        mm={}
        for k,v in ev.items():
            if not v.get('match'):
                mm[k]={'local':str(v.get('local'))[:300],'source':fam(v.get('source')),'detail':v.get('detail')}
        det[f]={'src':c['source'],'src_title':st,'title_sim':round(sim,2),'mismatch':mm,'cand_issues':c.get('issues')}
    res[x['key']]=det
json.dump(res,open(S+'notices/detail.json','w'),indent=1)
for k,d in res.items():
    for f,v in d.items():
        print(k,f,v.get('title_sim'),list(v.get('mismatch',{}).keys()))
