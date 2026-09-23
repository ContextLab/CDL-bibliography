import sys, json, sqlite3
sys.path.insert(0, '/Users/jmanning/CDL-bibliography/bibcheck')
from verification import load_entries, POLICY, normalize_doi, split_authors
from bibtexparser.customization import splitname
BIB='/Users/jmanning/CDL-bibliography/cdl.bib'
entries=load_entries(BIB)
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
D='/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/doiconf/'
rows={r['key']:r for r in json.load(open(D+'identity_rows.json'))}
sim=json.load(open(D+'simulate.json'))
out={}
for key,s in sim.items():
    if s['status']=='metadata_verified': continue
    e=entries[key]; f=e['fields']; doi=rows[key]['doi']
    prev=json.loads(db.execute("select result from reviews where bibliography=? and key=? and fingerprint=? and policy=? order by id desc limit 1",(BIB,key,e['fingerprint'],POLICY)).fetchone()[0])
    cr=[c for c in prev['candidates'] if c.get('source')=='crossref' and normalize_doi(c['doi'])==doi][0]['record']
    med=[c for c in prev['candidates'] if c.get('source')=='pmc-jats' and normalize_doi(c['doi'])==doi][0]['medline_record']
    loc=[]
    for n in split_authors(f.get('author','')):
        p=splitname(n,strict_mode=True); loc.append((' '.join(p['von']+p['last']),' '.join(p['first']),' '.join(p['jr'])))
    crn=[(a.get('family') or a.get('name'),a.get('given'),a.get('suffix')) for a in cr.get('author',[])]
    mdn=[a.get('fullName') or a.get('collectiveName') for a in med.get('authorList',{}).get('author',[])]
    res=sorted({i.split(':',1)[0] for c in s['cand_issues'].values() for i in (c or [])})
    print('==',key,'residual:',res)
    print('   bib:',[f'{a[1]} {a[0]}'+(f' {a[2]}' if a[2] else '') for a in loc])
    print('   cr :',[f'{a[1]} {a[0]}'+(f' {a[2]}' if a[2] else '') for a in crn])
    print('   med:',mdn)
    print('   journal bib/cr/med:',f.get('journal'),'|',cr.get('container-title'),'|',med.get('journalInfo',{}).get('journal',{}).get('title'), '| year',f.get('year'),cr.get('published-print',{}).get('date-parts'),cr.get('published-online',{}).get('date-parts'),med.get('journalInfo',{}).get('yearOfPublication'),'| pub',f.get('publisher'),cr.get('publisher'))
