import json, sqlite3, sys, re
import xml.etree.ElementTree as ET
sys.path.insert(0, '/Users/jmanning/CDL-bibliography/bibcheck')
from auto_review import secondary_notice_flags
from verification import normalize_doi
S='/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/'
group=json.load(open(S+'group-notices.json'))
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
FIELDS=['author','title','journal','year','volume','number','pages']
out=[]
for g in group:
    k=g['key']
    row=db.execute("select id,result from reviews where key=? and policy='2' order by id desc limit 1",(k,)).fetchone()
    r=json.loads(row[1]); cands=r.get('candidates',[])
    flagged=set()
    for c in cands:
        try: flagged|={normalize_doi(d) for d in secondary_notice_flags([c])}
        except Exception as e: pass
    # per-DOI match summary (best across sources)
    per={}
    for c in cands:
        if not c.get('doi'): continue
        try: d=normalize_doi(c['doi'])
        except Exception: continue
        ev=c.get('evidence') or {}
        m={f:ev.get(f,{}).get('match') for f in ev}
        p=per.setdefault(d,{'sources':set(),'best_matchcount':-1,'best':None,'issues':set()})
        p['sources'].add(c.get('source'))
        n=sum(1 for v in m.values() if v)
        if n>p['best_matchcount']: p['best_matchcount']=n; p['best']=m; p['bestsrc']=c.get('source')
        p['issues'].update(c.get('issues') or [])
    notices=[]
    for c in cands:
        try: d=normalize_doi(c['doi'])
        except Exception: continue
        if d not in flagged: continue
        src=c.get('source')
        if src=='europepmc':
            raw=c.get('raw_record',{})
            types=raw.get('pubTypeList',{}).get('pubType',[])
            rel=raw.get('commentCorrectionList',{}).get('commentCorrection',[])
            notices.append({'doi':d,'src':'europepmc','pmid':raw.get('id'),'title':raw.get('title'),'isRetracted':raw.get('isRetracted'),'pubTypes':types,
              'relations':[{kk:x.get(kk) for kk in ('type','reference','id','source','note','orderIn')} for x in rel]})
        elif src=='pmc-jats':
            try:
                root=ET.fromstring(c['raw_xml']); meta=root.find('./front/article-meta')
                ra=[{'type':x.get('related-article-type'),'href':x.get('{http://www.w3.org/1999/xlink}href'),'ext':x.get('ext-link-type'),'text':(''.join(x.itertext()) or '').strip()[:200]} for x in meta.findall('./related-article')]
                notices.append({'doi':d,'src':'pmc-jats','article_type':root.get('article-type'),'related':ra})
            except Exception as e:
                notices.append({'doi':d,'src':'pmc-jats','err':str(e)})
        elif src in ('arxiv-repository','biorxiv-preprint'):
            notices.append({'doi':d,'src':src})
    crossref_rel={}
    for c in cands:
        if c.get('source')=='crossref' and c.get('doi'):
            d=normalize_doi(c['doi']); rec=c.get('record',{})
            if d in flagged or any(x for x in ('update-to','updated-by','relation') if rec.get(x)):
                crossref_rel[d]={'title':rec.get('title'),'type':rec.get('type'),'update-to':rec.get('update-to'),'updated-by':rec.get('updated-by'),
                   'relation':{kk:v for kk,v in (rec.get('relation') or {}).items()}}
    # target DOI: full match on all compared fields in some source
    target=[d for d,p in per.items() if p['best'] and all(p['best'].values()) and p['best_matchcount']>=3]
    out.append({'key':k,'review_id':row[0],'status':r.get('status'),'issues':r.get('issues'),'fields':g['fields'],'flagged':sorted(flagged),
      'targets':target,'per_doi':{d:{'sources':sorted(p['sources']),'best':p['best'],'issues':sorted(p['issues'])} for d,p in per.items() if d in flagged or d in target},
      'notices':notices,'crossref_rel':crossref_rel})
json.dump(out,open(S+'notices/extracted.json','w'),indent=1,default=list)
print(len(out))
