import json, sqlite3, sys
sys.path.insert(0,'/Users/jmanning/CDL-bibliography/bibcheck')
from verification import normalize_doi
S='/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/notices/'
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
ids=[int(l.split('|')[1]) for l in open(S+'latest.txt')]
out=[]
for i in ids:
    k,res=db.execute('select key,result from reviews where id=?',(i,)).fetchone()
    low=res.lower()
    if 'retract' not in low and 'expression_of_concern' not in low and 'expression of concern' not in low: continue
    r=json.loads(res)
    acc=r.get('accepted_doi')
    for c in r.get('candidates',[]):
        d=c.get('doi'); rec=c.get('record',{}) or {}; raw=c.get('raw_record',{}) or {}
        ev=c.get('evidence') or {}
        tm=bool(ev.get('title',{}).get('match')) and bool(ev.get('author',{}).get('match'))
        flags=[]
        for u in (rec.get('updated-by') or [])+(rec.get('update-to') or []):
            if u.get('type') in ('retraction','expression_of_concern','withdrawal','removal'): flags.append(('crossref',u.get('type'),u.get('DOI')))
        for kk in ('retraction','expression-of-concern'):
            if (rec.get('relation') or {}).get(kk): flags.append(('crossref-rel',kk))
        if isinstance(raw,dict):
            if raw.get('isRetracted')=='Y': flags.append(('epmc','isRetracted'))
            for rel in (raw.get('commentCorrectionList') or {}).get('commentCorrection',[]):
                t=rel.get('type','')
                if 'Retract' in t or 'Concern' in t: flags.append(('epmc',t,rel.get('reference')))
            for t in (raw.get('pubTypeList') or {}).get('pubType',[]):
                if 'Retract' in t or 'Concern' in t: flags.append(('epmc-pt',t))
        if flags: out.append({'key':k,'status':r.get('status'),'accepted':acc,'doi':d,'src':c.get('source'),'title_author_match':tm,'flags':flags,'title':(rec.get('title') or [''])[0] if isinstance(rec.get('title'),list) else rec.get('title')})
json.dump(out,open(S+'retscan.json','w'),indent=1)
seen=set()
for o in out:
    t=(o['key'],o['doi'],str(o['flags']))
    if t in seen: continue
    seen.add(t); print(o['key'],o['status'],o['accepted'],o['doi'],o['src'],o['title_author_match'],o['flags'],str(o['title'])[:70])
