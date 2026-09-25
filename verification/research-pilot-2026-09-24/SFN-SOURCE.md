# SfN abstract source: how to verify a Society for Neuroscience abstract

Tested 2026-09-25 on the SfN 2012 (New Orleans) planner. It found both 2012 abstracts
that the pilot had marked `no_source` (RamaEtal12b = Program 800.09, SommEtal12 = Program 746.04).

## Which archive holds which year

| Years | Where | Scriptable? |
|-|-|-|
| 2000-2005 | SfN's own archive, `https://www.sfn.org/meetings/past-and-future-sfn-meetings/abstract-archive` (search form, POST with anti-forgery token); single abstracts at `.../abstract-archive-details?absID=<n>&absyear=<yyyy>` | Detail pages are plain HTML (GET, no JS). The search is a server-side form and was not scripted here. |
| about 2006-2015 | "OASIS" classic planner at `https://www.abstractsonline.com/Plan/` (ASP.NET WebForms) | **Yes, with no JavaScript.** Method below. |
| later years | abstractsonline "pp8" single-page app (`https://www.abstractsonline.com/pp8/#!/<meetingId>/presentation/<id>`) | JavaScript front end. Its JSON API (`/oe3/Program/<id>/...`) answers "A valid Backpack key needs to be included in the header", so it needs a session key the SPA gets first. **Not scripted.** Use a browser (Playwright) or the Wayback Machine. |
| any | `https://archive.sfn.org/` ("Abstract Archive PDFs") | TLS certificate **expired** (checked 2026-09-25); not usable as evidence. |

Year-to-meeting keys for OASIS: each meeting has an `mKey` GUID. **SfN 2012 = `{70007181-01C9-4DE9-A0A2-EEBFA14CD9F1}`** (internal mID 2964).
To find another year's mKey, find any OASIS abstract link for that year (web search for
`abstractsonline.com/Plan/ViewAbstract.aspx "<year> Neuroscience Meeting Planner"`, lab
publication pages, and Wikipedia citations often link them). The mKey is the `mKey=` parameter. Confirm
the year from the page footer: `Program No. XXX.XX. 2012 Neuroscience Meeting Planner. New Orleans, LA: Society for Neuroscience, 2012.`
Add each mKey you confirm to the table here.

## OASIS method (no JavaScript)

1. **User-Agent.** The AWS load balancer returns **HTTP 403** to `curl`'s default UA and to `Mozilla/5.0`,
   and **503** to `Python-urllib`. Send a full browser UA string, e.g.
   `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36`.
   Any evidence validator that fetches these URLs has to send such a UA too.
2. **Session.** `GET /Plan/start.aspx?mkey=%7B<GUID>%7D` with a cookie jar. It sets the meeting in the
   ASP.NET session (`Planner_ASP.NET_SessionState` cookie). `start.aspx?mID=2964` does **not** work.
3. **Search.** `GET /Plan/AdvancedSearch.aspx`, copy every form field (`__VIEWSTATE`, `__EVENTVALIDATION`,
   default checkboxes and selects), fill in the fields, then POST back to `AdvancedSearch.aspx` with
   `...uiSearchButton2=Search`. Field names (prefix `ctl00$MainContentPlaceHolder$uiAdvancedSearchControl$`):
   - `ctl07$uiAuthorLastName1TextBox` / `ctl07$uiAuthorInitial1TextBox` (up to 3 authors): **the most reliable search**
   - `ctl04$txtInputSearch`: presentation number (e.g. `800.09`), exact
   - `ctl06$txtInputSearch`: presentation title. This matches **any** word, so results are broad and paginated. Avoid it.
   - `ctl10$txtInputSearch`: abstract body; `ctl08$txtInputSearch`: institution
4. **Author disambiguation.** An author search lands on `AuthorsIntermediate.aspx` (a list of name and
   institution variants). Tick every checkbox and POST the "Continue" submit button. The results then load at
   `SSResults.aspx`.
5. **Results.** Every hit is an `<a href="ViewAbstract.aspx?sKey=..&cKey=..&mKey=..">` whose text gives
   `<day/time><program#>/<poster#> - <title>`.
6. **Evidence URL.** `https://www.abstractsonline.com/Plan/ViewAbstract.aspx?sKey=<s>&cKey=<c>&mKey=%7B<GUID>%7D`
   is a plain GET that works **without** a session (browser UA only). Its text has `Program#/Poster#:`,
   `Presentation Title:`, `Authors:` (with superscript affiliation numbers between names, so quote the
   `Disclosures:` line for the author list, e.g. `A.G. Ramayya: None. K.A. Zaghloul: None. ...`), `Abstract:`
   and the sample-citation footer (city, state, year).
   Watch for typographic ligatures in titles (`ﬁ` U+FB01 in "ﬁeld"). Quote around them or from the keyword line.
7. **Fallback.** The Wayback Machine has captures of many ViewAbstract URLs
   (`http://archive.org/wayback/available?url=<ViewAbstract URL>`), useful if OASIS is retired.

**Rate limits:** none observed at about 1 request per second across ~20 requests. None are documented. Keep a
1-second pause between requests and cache pages.

**Limits:** coverage is only as good as the planner (withdrawn abstracts are absent). Title search is
OR-matched and paginated (only page 1 is parsed). The mKey must be known per year. Years on the pp8 SPA need a
browser. The planner prints names in capitals without diacritics (`BUZSAKI`), so accents need another source.

## House format for a verified SfN abstract (from existing cdl.bib entries, e.g. KrauEtal12)

```
@inproceedings{Key,
	Address = {New Orleans, {LA}},
	Author = {...order exactly as in the planner...},
	Booktitle = {Society for Neuroscience Abstracts},
	Number = {800.09},            % program number (not the poster board)
	Organization = {Society for Neuroscience},
	Title = {...},
	Year = {2012}}
```

## Script (tested 2026-09-25)

Usage: `python oasis_search.py 70007181-01C9-4DE9-A0A2-EEBFA14CD9F1 --author Ramayya` (also `--author Sommer,F`,
`--number 800.09`). It prints one `ViewAbstract URL | link text` line per hit.

```python
"""Search a classic OASIS meeting planner (abstractsonline.com/Plan, SfN 2008-2015 era).
usage: python oasis_search.py <mKey-guid> [--author LAST[,I]]... [--title WORDS] [--body WORDS] [--number 123.45]
Prints one line per hit: ViewAbstract URL | link text.
Needs a full browser User-Agent (the AWS load balancer 403s short UAs). No JavaScript needed.
"""
import sys, re, html, time, argparse, urllib.request, urllib.parse, http.cookiejar
from html.parser import HTMLParser
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
BASE = "https://www.abstractsonline.com/Plan/"
P = "ctl00$MainContentPlaceHolder$uiAdvancedSearchControl$"
ap = argparse.ArgumentParser()
ap.add_argument("mkey"); ap.add_argument("--author", action="append", default=[])
ap.add_argument("--title"); ap.add_argument("--body"); ap.add_argument("--number")
a = ap.parse_args()
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("User-Agent", UA), ("Accept", "text/html")]
def fetch(url, data=None):
    r = op.open(url, data=urllib.parse.urlencode(data).encode() if data is not None else None, timeout=90)
    return r.geturl(), r.read().decode("utf-8", "replace")

class Form(HTMLParser):
    def __init__(s): super().__init__(); s.f = {}; s.sel = None
    def handle_starttag(s, tag, at):
        at = dict(at)
        if tag == "input" and at.get("name"):
            t = at.get("type", "text")
            if t in ("hidden", "text"): s.f[at["name"]] = at.get("value", "")
            elif t == "checkbox" and "checked" in at: s.f[at["name"]] = "on"
        elif tag == "select": s.sel = at.get("name"); s.first = True
        elif tag == "option" and s.sel:
            if s.first or "selected" in at: s.f[s.sel] = at.get("value", ""); s.first = False
    def handle_endtag(s, tag):
        if tag == "select": s.sel = None

fetch(BASE + "start.aspx?mkey=" + urllib.parse.quote("{%s}" % a.mkey))   # sets the meeting in the session
time.sleep(1)
url, page = fetch(BASE + "AdvancedSearch.aspx")
fp = Form(); fp.feed(page); form = fp.f
for i, au in enumerate(a.author[:3], 1):
    last, _, ini = au.partition(",")
    form[P + "ctl07$uiAuthorLastName%dTextBox" % i] = last
    form[P + "ctl07$uiAuthorInitial%dTextBox" % i] = ini
if a.number: form[P + "ctl04$txtInputSearch"] = a.number
if a.title: form[P + "ctl06$txtInputSearch"] = a.title
if a.body: form[P + "ctl10$txtInputSearch"] = a.body
form[P + "uiSearchButton2"] = "Search"
time.sleep(1)
url2, res = fetch(urllib.parse.urljoin(url, "AdvancedSearch.aspx"), form)
if "AuthorsIntermediate" in url2:   # author search: tick every matching name, press Continue
    fp = Form(); fp.feed(res); f2 = fp.f
    for n in re.findall(r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"', res) + re.findall(r'<input[^>]*name="([^"]+)"[^>]*type="checkbox"', res):
        f2[n] = "on"
    btn = re.findall(r'<input[^>]*type="submit"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', res)
    cont = [b for b in btn if "ontinue" in b[1]]
    if cont: f2[cont[0][0]] = cont[0][1]
    act = html.unescape(re.search(r'<form name="aspnetForm" method="post" action="([^"]+)"', res).group(1))
    time.sleep(1)
    url2, res = fetch(urllib.parse.urljoin(url2, act), f2)
print("RESULT URL:", url2, file=sys.stderr)
hits = re.findall(r'href="([^"]*ViewAbstract\.aspx\?[^"]+)"[^>]*>(.*?)</a>', res, re.S)
for h, txt in hits:
    print(urllib.parse.urljoin(url2, html.unescape(h)), "|", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", txt))).strip())
if not hits:
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", "", res, flags=re.S))))
    i = t.find("result"); print("NO HITS; page text:", t[max(0, i-300):i+700], file=sys.stderr)
```

## Results for the pilot entries

| Key | Program/poster | URL |
|-|-|-|
| RamaEtal12b | 800.09 / BBB40, Wed Oct 17 2012 | https://www.abstractsonline.com/Plan/ViewAbstract.aspx?sKey=7e782cce-865f-4776-818d-306dc2f9f8e5&cKey=1671e297-ad00-44f3-957e-81aa69af3082&mKey=%7B70007181-01C9-4DE9-A0A2-EEBFA14CD9F1%7D |
| SommEtal12 | 746.04 / D27, Wed Oct 17 2012 | https://www.abstractsonline.com/Plan/ViewAbstract.aspx?sKey=bc702170-2269-4b8a-bbc5-3f72c7ec7bac&cKey=ce65da50-3fbe-4236-8a2c-9722072dd724&mKey=%7B70007181-01C9-4DE9-A0A2-EEBFA14CD9F1%7D |
