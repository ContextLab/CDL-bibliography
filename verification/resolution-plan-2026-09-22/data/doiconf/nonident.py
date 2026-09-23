import sys, json, sqlite3
sys.path.insert(0, '/Users/jmanning/CDL-bibliography/bibcheck')
from verification import load_entries, POLICY, normalize_doi
SP='/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/'
d=json.load(open(SP+'doiconf/extract.json'))
BIB='/Users/jmanning/CDL-bibliography/cdl.bib'
entries=load_entries(BIB)
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
res={}
for o in d:
    idconf=[x for x in o['coord_conflict_dois']+o['suffix_conflict_dois'] if o['dois'].get(x,{}).get('cr',{}).get('match',{}).get('title')]
    if idconf: continue
    key=o['key']; e=entries[key]
    prev=json.loads(db.execute("select result from reviews where bibliography=? and key=? and fingerprint=? and policy=? order by id desc limit 1",(BIB,key,e['fingerprint'],POLICY)).fetchone()[0])
    ids=[]
    for c in prev['candidates']:
        if c.get('source')=='crossref' and c.get('evidence',{}).get('title',{}).get('match'):
            ids.append((normalize_doi(c['doi']), [i[:55] for i in c.get('issues',[])]))
    ids=list(dict((a,b) for a,b in ids).items())
    others=[c.get('source') for c in prev['candidates'] if c.get('source') not in ('crossref','europepmc','pmc-jats')]
    res[key]={'identity':ids,'other_sources':sorted(set(others)),'fields':{k:o['fields'].get(k) for k in ('ENTRYTYPE','journal','year','volume','pages')},'ext':bool(prev.get('external_evidence'))}
    print(key, o['fields'].get('journal'), o['fields'].get('year'), '| id:', ids if ids else 'NONE', sorted(set(others)))
json.dump(res,open(SP+'doiconf/nonident.json','w'),indent=1)
print(len(res), sum(1 for v in res.values() if v['identity']))
