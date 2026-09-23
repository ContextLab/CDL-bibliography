import json,sys,re,collections
sys.path.insert(0,'/Users/jmanning/CDL-bibliography/bibcheck')
from auto_review import expanded_pages
from verification import normalized
d=json.load(open('extract.json'))
rows=[]
def ep(x):
    try: return expanded_pages(x or '')
    except Exception: return None
for o in d:
    f=o['fields']
    for x in o['coord_conflict_dois']:
        v=o['dois'].get(x,{}); cr=v.get('cr',{})
        if not cr.get('match',{}).get('title'): continue
        _,jv,jp=v['jats_coords']
        bv=normalized(f.get('volume','') or ''); bp=ep(f.get('pages','')); bn=(f.get('number') or '')
        crp=ep(cr.get('page') or cr.get('artno') or '')
        vol_ok = bv==jv
        pg_ok = bp==jp
        cls=[]
        if not vol_ok: cls.append('vol-missing' if not bv else 'vol-differs')
        if not pg_ok:
            if not bp: cls.append('pages-missing')
            elif 'doi.org' in (f.get('pages') or ''): cls.append('pages=doi-url')
            elif '-' not in jp and bn.strip()==jp: cls.append('artno-in-number,pages=' + ('1-N' if re.fullmatch(r'1-\d+',bp) else 'other'))
            elif '-' not in jp: cls.append('e-locator-vs-pages')
            elif '-' not in bp and jp.startswith(bp+'-'): cls.append('start-page-only')
            elif '-' in bp and bp.split('-')[0]==jp.split('-')[0]: cls.append('end-page-differs')
            else: cls.append('page-range-differs')
        crv=normalized(cr.get('volume') or '')
        agree = (crv==jv and crp==jp)
        rows.append(dict(key=o['key'],doi=x,cls='+'.join(cls),bib=(f.get('volume'),f.get('number'),f.get('pages'),f.get('year')),
            jats=(jv,jp),cr=(cr.get('volume'),cr.get('issue'),cr.get('page'),cr.get('artno')),cr_agree=agree,
            cr_print=cr.get('print'),cr_online=cr.get('online'),other_cr_mismatch=sorted(k for k,w in cr.get('match',{}).items() if not w and k not in('volume','pages','number'))))
json.dump(rows,open('identity_rows.json','w'),indent=1)
c=collections.Counter(r['cls'] for r in rows)
for k,v in c.most_common(): print(v,k)
print('cr agrees with jats+med:',collections.Counter(r['cr_agree'] for r in rows))
print('other mismatches:',collections.Counter(tuple(r['other_cr_mismatch']) for r in rows))
for r in rows: print(r['key'],r['cls'],r['bib'],r['jats'],r['cr'],r['cr_agree'],r['other_cr_mismatch'])
