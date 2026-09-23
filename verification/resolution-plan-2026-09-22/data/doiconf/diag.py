import sys, json, sqlite3, socket, re
socket.socket.connect = lambda *a,**k: (_ for _ in ()).throw(RuntimeError('net'))
sys.path.insert(0, '/Users/jmanning/CDL-bibliography/bibcheck')
from verification import load_entries, POLICY, normalize_doi
from auto_review import epmc_record, expanded_pages, safe_compare, reassess
from fulltext_review import assess_fulltext
SP='/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/'
rows={r['key']:r for r in json.load(open(SP+'doiconf/identity_rows.json'))}
sim=json.load(open(SP+'doiconf/simulate.json'))
BIB='/Users/jmanning/CDL-bibliography/cdl.bib'
entries=load_entries(BIB)
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
out={}
for key,r in rows.items():
    e=entries[key]; fields=e['fields']
    prev=json.loads(db.execute("select result from reviews where bibliography=? and key=? and fingerprint=? and policy=? order by id desc limit 1",(BIB,key,e['fingerprint'],POLICY)).fetchone()[0])
    src=[c for c in prev['candidates'] if c.get('source')=='pmc-jats' and normalize_doi(c['doi'])==r['doi']][0]
    prim=[c for c in prev['candidates'] if c.get('source')=='crossref' and c.get('doi')==src['doi']]
    reason=[]
    import hashlib
    if len(prim)!=1: reason.append(f'{len(prim)} crossref primaries, distinct records={len({json.dumps(p["record"],sort_keys=True) for p in prim})}')
    primary=prim[0]
    med=src['medline_record']
    resp={"body": src["raw_xml"], "url": src["url"], "retrieved_at": src["retrieved_at"], "document_sha256": src.get("xml_sha256")}
    a=assess_fulltext(fields,primary,med,resp)
    bad=[i for i in a['issues'] if i.split(':',1)[0] not in {'year','volume','number','pages'}]
    if bad: reason.append('non-coord jats issues: '+'; '.join(i[:50] for i in bad))
    rec=a['record']
    values={"volume": str(rec.get("volume") or ""),"number": str(rec.get("issue") or ""),"pages": expanded_pages(rec.get("page") or rec.get("article-number") or "").replace("-", "--")}
    changed={i.split(':',1)[0] for i in a['issues']} & {'year','volume','number','pages'}
    for f in changed:
        if f in values and not values[f]: reason.append(f'{f} would be emptied (source has none; bib has {fields.get(f)!r})')
    if not re.fullmatch(r"[a-z]{0,3}\d+(?:--[a-z]{0,3}\d+(?:\.e\d+)?)?", values["pages"]): reason.append('pages regex rejects '+values['pages'])
    try: mapped=epmc_record(med,primary["record"])
    except ValueError as ex: reason.append("MED: "+str(ex)[:60]); mapped={}
    oe=safe_compare(fields,mapped)[0]
    for fld in ('title','author'):
        if not oe.get(fld,{}).get('match'): reason.append(f'MED {fld} mismatch')
    out[key]={'sim':sim[key]['status'],'reasons':reason,'jats_issues':a['issues']}
    print(key, sim[key]['status'][:8], reason)
json.dump(out,open(SP+'doiconf/diag.json','w'),indent=1)
