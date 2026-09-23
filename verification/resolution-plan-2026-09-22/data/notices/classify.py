import json,collections
ex=json.load(open('extracted.json')); de=json.load(open('detail.json'))
N3={'VirtEtal20':'author list count differs','delaEtal16':'entry lacks 5th author (Yarkoni)','JahaEtal13':'author surnames/order differ; number','BisbBurg14':'pages 760--766 vs source 21-27','WildRugg96':'pages 889--906 vs 889-905','VargEtal97':'author "Connely" vs source "Connelly"','SkraChiu03':'title separator lost ("meaningbehavioral")','RebeEtal02':'source author "Gitleman" vs entry "Gitelman"','MarsEtal06':'year 2006 vs source 2000','LohnKaha13':'title "word frequency effect" vs source','KossEtal99':'source has extra author token "L."'}
LOCALFIX={'PalaEtal21':'pages holds doi URL; article no. 5475','ColiEtal18':'number holds article no.; pages 1--13','DianEtal07':'volume holds DOI'}
rows=[]
for x in ex:
    k=x['key']; d=de[k]
    extra=[i for i in x['issues'] if i not in ('No unambiguous, fully supported metadata match','DOI-linked source correction/retraction notice requires adjudication')]
    sims={f:v.get('title_sim',0) for f,v in d.items()}
    related=[f for f in d if sims[f]>=0.8]
    main=None
    for f in related:
        mm=d[f]['mismatch']
        if main is None or len(mm)<len(d[main]['mismatch']): main=f
    if not related:
        cls='M'; note='notice belongs to unrelated search candidate: '+'; '.join(f"{f} ({str(d[f]['src_title'])[:60]})" for f in d)
    else:
        mm=d[main]['mismatch']
        if not mm: cls='A'; note='all compared fields match'
        elif k in N3: cls='C'; note=N3[k]
        elif k in LOCALFIX: cls='B'; note='local field error: '+LOCALFIX[k]
        else: cls='B'; note='benign/format: '+', '.join(f"{a}" for a in mm)
        others=[f for f in related if f!=main]
        if others: note+=f"; also flagged erratum-record DOI {', '.join(others)}"
    # notice refs for main
    refs=[]
    for n in x['notices']:
        if main and n['doi']!=main: continue
        if n['src']=='europepmc':
            refs+= [f"{r['type']}: {r['reference']}" + (f" [PMID {r['id']}]" if r.get('id') else '') for r in n['relations'] if r['type'] in ('Erratum in','Erratum for')]
        if n['src']=='pmc-jats':
            refs+= [f"JATS {r['type']}: {r.get('href') or r.get('text')}" for r in n.get('related',[]) if r['type'] in ('correction-forward',)]
    for dd,c in x['crossref_rel'].items():
        if main and dd==main:
            refs+= [f"Crossref updated-by {u.get('type')}: {u.get('DOI')}" for u in (c['updated-by'] or [])]
    rows.append({'key':k,'class':cls,'doi':main or ','.join(d),'title':x['fields'].get('title'),'year':x['fields'].get('year'),'note':note,'extra_issues':extra,'notice_refs':sorted(set(refs)),'targets':x['targets']})
json.dump(rows,open('classified.json','w'),indent=1)
print(collections.Counter(r['class'] for r in rows))
for r in rows:
    if r['extra_issues']: print(r['key'],r['class'],r['extra_issues'])
print(sum(1 for r in rows if any('updated-by' in s for s in r['notice_refs'])), sum(1 for r in rows if r['class']!='M' and not r['notice_refs']))
