import sys, json, sqlite3
sys.path.insert(0, '/Users/jmanning/CDL-bibliography/bibcheck')
from verification import load_entries, POLICY, normalize_doi
from fulltext_review import assess_fulltext
BIB='/Users/jmanning/CDL-bibliography/cdl.bib'
entries=load_entries(BIB)
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
rows={r['key']:r for r in json.load(open('/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/doiconf/identity_rows.json'))}
for key in sys.argv[1:]:
    e=entries[key]; f=e['fields']; r=rows[key]
    prev=json.loads(db.execute("select result from reviews where bibliography=? and key=? and fingerprint=? and policy=? order by id desc limit 1",(BIB,key,e['fingerprint'],POLICY)).fetchone()[0])
    src=[c for c in prev['candidates'] if c.get('source')=='pmc-jats' and normalize_doi(c['doi'])==r['doi']][0]
    prim=[c for c in prev['candidates'] if c.get('source')=='crossref' and c.get('doi')==src['doi']][0]
    a=assess_fulltext(f,prim,src['medline_record'],{"body": src["raw_xml"], "url": src["url"], "retrieved_at": src["retrieved_at"], "document_sha256": src.get("xml_sha256")})
    print('==',key,'bib author:',f.get('author')); print('  title:',f.get('title'))
    print('  jats authors:',[(p.get('family'),p.get('given')) for p in a['record'].get('author',[])])
    print('  cr authors:',[(p.get('family'),p.get('given')) for p in prim['record'].get('author',[])])
    med=src['medline_record']; print('  med title:',med.get('title'),'| med authors:',[x.get('fullName') for x in med.get('authorList',{}).get('author',[])])
    print('  jats issues:',a['issues'])
