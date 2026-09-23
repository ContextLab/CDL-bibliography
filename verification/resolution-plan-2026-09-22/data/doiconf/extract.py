import sys, json, sqlite3
sys.path.insert(0, '/Users/jmanning/CDL-bibliography/bibcheck')
from verification import load_entries, normalize_doi, normalized, split_authors, normalize_author_suffix, POLICY
from source_locators import source_coordinates, locator_conflicts
from auto_review import secondary_suffix_conflicts, pubmed_author_suffix, expanded_pages, PubmedSuffixConflict
from bibtexparser.customization import splitname
SP='/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/'
group=json.load(open(SP+'group-doi_conflicts.json'))
BIB='/Users/jmanning/CDL-bibliography/cdl.bib'
entries=load_entries(BIB)
db=sqlite3.connect('file:/Users/jmanning/CDL-bibliography/.bibcheck/verification.sqlite3?mode=ro', uri=True)
def dp(d):
    try: return '-'.join(str(x) for x in d['date-parts'][0])
    except Exception: return None
out=[]
for g in group:
    key=g['key']; e=entries[key]; f=e['fields']
    row=db.execute("select result from reviews where bibliography=? and key=? and fingerprint=? and policy=? order by id desc limit 1",(BIB,key,e['fingerprint'],POLICY)).fetchone()
    if not row:
        out.append({'key':key,'error':'no current review'}); continue
    r=json.loads(row[0]); cands=r['candidates']
    conf=locator_conflicts(f,cands)
    sconf=secondary_suffix_conflicts(f,cands)
    per={}
    for c in cands:
        try: doi=normalize_doi(c['doi'])
        except Exception: continue
        d=per.setdefault(doi,{'sources':[]})
        d['sources'].append(c['source'])
        if c['source']=='crossref':
            rec=c.get('record',{})
            ev=c.get('evidence',{})
            d['cr']={'title':(rec.get('title') or [''])[0],'container':(rec.get('container-title') or [''])[:1],
                'volume':rec.get('volume'),'issue':rec.get('issue'),'page':rec.get('page'),'artno':rec.get('article-number'),
                'print':dp(rec.get('published-print',{})) ,'online':dp(rec.get('published-online',{})),'issued':dp(rec.get('issued',{})),
                'type':rec.get('type'),'match':{k:v.get('match') for k,v in ev.items()},'issues':c.get('issues')}
        elif c['source']=='europepmc':
            raw=c.get('raw_record',{}); ji=raw.get('journalInfo',{})
            d['med']={'src':raw.get('source'),'id':raw.get('id'),'volume':ji.get('volume'),'issue':ji.get('issue'),'pages':raw.get('pageInfo'),
                'year':ji.get('yearOfPublication'),'printdate':ji.get('printPublicationDate'),'title':raw.get('title'),
                'authors':[(a.get('fullName'),a.get('lastName'),a.get('initials'),a.get('suffix')) for a in raw.get('authorList',{}).get('author',[])],
                'issues':c.get('issues')}
        elif c['source']=='pmc-jats':
            d['jats_coords']=source_coordinates(c)
            med=c.get('medline_record',{}); ji=med.get('journalInfo',{})
            d['jats_med']={'volume':ji.get('volume'),'issue':ji.get('issue'),'pages':med.get('pageInfo'),'year':ji.get('yearOfPublication')}
            d['jats_rec']={k:c.get('record',{}).get(k) for k in ('volume','issue','page','article-number')}
            d['jats_issues']=c.get('issues')
            d['jats_match']={k:v.get('match') for k,v in c.get('evidence',{}).items()}
    # suffix detail
    sdet=[]
    for c in cands:
        if c['source']!='europepmc': continue
        try: doi=normalize_doi(c['doi'])
        except Exception: continue
        if doi not in sconf: continue
        names=split_authors(f.get('author',''))
        people=c['raw_record'].get('authorList',{}).get('author',[])
        for i,(n,p) in enumerate(zip(names,people)):
            parts=splitname(n,strict_mode=True)
            try: suf=pubmed_author_suffix(p)
            except PubmedSuffixConflict: suf='CONFLICT'
            if suf or parts['jr']:
                sdet.append({'doi':doi,'i':i,'local':n,'local_jr':' '.join(parts['jr']),'pm_full':p.get('fullName'),'pm_last':p.get('lastName'),'pm_suffix_field':p.get('suffix'),'pm_suffix':suf,'lenmatch':len(names)==len(people)})
    out.append({'key':key,'fields':{k:v for k,v in f.items() if k in ('title','author','journal','volume','number','pages','year','doi','ENTRYTYPE','month')},
        'issues':r['issues'],'coord_conflict_dois':sorted(conf),'suffix_conflict_dois':sorted(sconf),'suffix_detail':sdet,
        'dois':{k:v for k,v in per.items() if k in conf or k in sconf or ('cr' in v and v['cr']['match'].get('title'))}})
json.dump(out,open(SP+'doiconf/extract.json','w'),indent=1,default=str)
print(len(out), sum('error' in o for o in out))
