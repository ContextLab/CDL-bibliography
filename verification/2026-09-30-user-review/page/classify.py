import json,re,unicodedata,sys
from pylatexenc.latex2text import LatexNodes2Text
L=LatexNodes2Text()
d=json.load(open('/Users/jmanning/CDL-bibliography/verification/2026-09-30-user-review/surnames.json'))
SUFFIX={'jr','sr','ii','iii','iv'}
def plain(s):
    try: s=L.latex_to_text(s)
    except Exception: pass
    s=re.sub(r'\$[^$]*\$','',s)
    s=unicodedata.normalize('NFKD',s); s=''.join(c for c in s if not unicodedata.combining(c))
    return s
def squash(s): return re.sub(r'[^a-z]','',plain(s).lower())
def words(s): return [w for w in re.split(r'[^a-z]+',plain(s).lower()) if w]
out={'format':[],'words':[],'spelling':[]}
for r in d:
    e,s=r['entry_spelling'],r['source_spelling']
    se,ss=squash(e),squash(s)
    for suf in SUFFIX:
        if ss.endswith(suf) and ss[:-len(suf)]==se: ss=se
    if se==ss: c='format'
    else:
        we,ws=set(words(e)),set(words(s))
        c='words' if (we and ws and (we<=ws or ws<=we)) else 'spelling'
    r['class']=c; out[c].append(r)
for c,v in out.items():
    print('==',c,len(v)); [print('  ',x['key'],x['position'],'|',x['entry_spelling'],'|',x['source_spelling']) for x in v]
json.dump(d,open('/private/tmp/claude-501/-Users-jmanning-CDL-bibliography/0ff7c242-39c2-48fa-9e7f-9dfa04593cb5/scratchpad/userpage/surnames-classified.json','w'),ensure_ascii=False,indent=1)
