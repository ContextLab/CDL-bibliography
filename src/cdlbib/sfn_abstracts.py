"""Verify Society for Neuroscience abstracts against the SfN abstract planner.

Method: verification/research-pilot-2026-09-24/SFN-SOURCE.md. The classic
"OASIS" planner (abstractsonline.com/Plan, ASP.NET, no JavaScript) serves the
SfN meetings whose meeting keys are listed in ``MEETINGS``; each key was
confirmed on 2026-09-25 from an abstract page of that meeting (the page's
citation footer or its presentation date and SfN venue). Other years are
reported as unsupported, never silently skipped:
* before 2009 no OASIS meeting key is known (2000-2005 abstracts are in SfN's
  own archive, which is not scripted); 2016 and later use the JavaScript
  "pp8" planner, which needs a browser session key.

Evidence is the public ViewAbstract page (plain GET, browser User-Agent; the
load balancer rejects short agents): program number, presentation title,
ordered authors (the Disclosures line prints mixed-case names in byline
order; the Authors line prints capitals), and the meeting year and city.
The author search that locates the page is cached as its own document.

House form (SFN-SOURCE.md): @inproceedings, Booktitle "Society for
Neuroscience Abstracts", Number = program number, Organization "Society for
Neuroscience", Address = meeting city, Title, Author (planner order), Year.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import re
import unicodedata
from urllib.parse import quote, urlencode, urljoin

import requests

from .preprint_review import checked_body
from .verification import ProviderError, author_evidence, normalize_title, normalized, outcome, split_authors
from .osf_review import classify, run_route

SFN_POLICY = '1'
SOURCE = 'sfn-abstract-planner'
BASE = 'https://www.abstractsonline.com/Plan/'
BOOKTITLE = 'Society for Neuroscience Abstracts'
# year: (OASIS meeting key, meeting city as printed in the planner footer)
MEETINGS = {
    2009: ('081F7976-E4CD-4F3D-A0AF-E8387992A658', 'Chicago, IL'),
    2010: ('E5D5C83F-CE2D-4D71-9DD6-FC7231E090FB', 'San Diego, CA'),
    2011: ('8334BE29-8911-4991-8C31-32B32DD5E6C8', 'Washington, DC'),
    2012: ('70007181-01C9-4DE9-A0A2-EEBFA14CD9F1', 'New Orleans, LA'),
    2013: ('8D2A5BEC-4825-4CD6-9439-B42BB151D1CF', 'San Diego, CA'),
    2014: ('54C85D94-6D69-4B09-AFAA-502C0E680CA7', 'Washington, DC'),
    2015: ('D0FF4555-8574-4FBB-B9D4-04EEC8BA0C84', 'Chicago, IL'),
}
BROWSER = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'
FORM = 'ctl00$MainContentPlaceHolder$uiAdvancedSearchControl$'
MAX_BYTES = 3_000_000


def unsupported(year):
    if year < 2009:
        return ('SfN abstract planner: %d is unsupported (no OASIS meeting key is known before 2009; '
                '2000-2005 abstracts are in SfN\'s own archive, which is not scripted)' % year)
    return ('SfN abstract planner: %d is unsupported (2016 and later use the JavaScript pp8 planner, '
            'which needs a browser session key)' % year)


def applicable(fields):
    text = ' '.join(fields.get(f, '') for f in ('booktitle', 'journal', 'publisher', 'organization')).lower()
    if 'society for neuroscience' not in text or 'journal of neuroscience' in text:
        return False
    return (normalized(fields.get('booktitle', '')) == normalized(BOOKTITLE)
            or normalized(fields.get('journal', '')) == normalized(BOOKTITLE)
            or (fields.get('ENTRYTYPE') in ('conference', 'inproceedings') and 'journal' not in fields))


def cited_year(fields):
    if not re.fullmatch(r'\d{4}', fields.get('year', '')):
        raise ValueError('SfN abstract citation has no year')
    return int(fields['year'])


def first_author(fields):
    from .name_parsing import splitname
    names = split_authors(fields.get('author', ''))
    parts = splitname(names[0], strict_mode=True)
    family = ' '.join(parts['von'] + parts['last'])
    family = unicodedata.normalize('NFKD', re.sub(r'[{}\\\'"`^~]', '', family)).encode('ascii', 'ignore').decode()
    initial = (parts['first'] or [''])[0][:1]
    if not family or not initial:
        raise ValueError('SfN search needs the first author surname and initial')
    return family, initial


def search_key(year, family, initial):
    return BASE + 'AdvancedSearch.aspx?' + urlencode({'mKey': MEETINGS[year][0], 'author': family + ',' + initial})


def view_url(skey, ckey, mkey):
    return BASE + 'ViewAbstract.aspx?sKey=' + skey + '&cKey=' + ckey + '&mKey=%7B' + mkey + '%7D'


def envelope(url, body, final_url):
    return {'url': url, 'final_url': final_url, 'body': body,
            'document_sha256': hashlib.sha256(body.encode()).hexdigest(),
            'retrieved_at': datetime.now(timezone.utc).isoformat()}


class Planner:
    """One polite browser-like session; every request is counted and paced by ``client``."""

    def __init__(self, client):
        self.client = client
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': BROWSER + ' bibcheck/2.0 (+https://github.com/ContextLab/CDL-bibliography; mailto:'
                          + client.mailto + ')', 'Accept': 'text/html'})

    def request(self, method, url, data=None):
        real = self.client
        if hasattr(real, 'options'):  # DeferredClient: materialize the paced client
            real.session
            real = real.client
        real.sleep(max(0, real.next_request - real.clock()))
        real.requests += 1
        try:
            response = self.session.request(method, url, data=data, timeout=(10, 60), allow_redirects=True)
        except requests.RequestException as exc:
            raise ProviderError('SfN planner request failed: ' + str(exc)) from exc
        finally:
            real.next_request = real.clock() + max(real.interval, 1.5)
        if response.status_code != 200 or len(response.content) > MAX_BYTES:
            raise ProviderError('SfN planner HTTP %d' % response.status_code)
        return response.url, response.content.decode('utf-8', 'replace')


def form_fields(page):
    fields = {}
    for tag in re.findall(r'<input\b[^>]*>', page, re.I):
        name = re.search(r'\bname="([^"]+)"', tag); kind = re.search(r'\btype="([^"]+)"', tag, re.I)
        value = re.search(r'\bvalue="([^"]*)"', tag)
        kind = kind[1].lower() if kind else 'text'
        if not name:
            continue
        if kind in ('hidden', 'text'):
            fields[html.unescape(name[1])] = html.unescape(value[1]) if value else ''
        elif kind == 'checkbox' and re.search(r'\bchecked\b', tag, re.I):
            fields[html.unescape(name[1])] = 'on'
    for name, body in re.findall(r'<select\b[^>]*name="([^"]+)"[^>]*>(.*?)</select>', page, re.I | re.S):
        options = re.findall(r'<option\b([^>]*)>', body, re.I)
        chosen = next((o for o in options if 'selected' in o.lower()), options[0] if options else '')
        value = re.search(r'value="([^"]*)"', chosen)
        fields[html.unescape(name)] = html.unescape(value[1]) if value else ''
    return fields


def search(cache, client, year, family, initial):
    """Cached author search on one meeting; returns the results-page envelope."""
    key = search_key(year, family, initial)
    saved = cache.response('sfn-search-v1:' + key, 3650 * 86400)
    if saved is not None and not client.refresh:
        checked_body(saved, key)
        return saved
    planner = Planner(client)
    planner.request('GET', BASE + 'start.aspx?mkey=' + quote('{' + MEETINGS[year][0] + '}'))
    url, page = planner.request('GET', BASE + 'AdvancedSearch.aspx')
    form = form_fields(page)
    form[FORM + 'ctl07$uiAuthorLastName1TextBox'] = family
    form[FORM + 'ctl07$uiAuthorInitial1TextBox'] = initial
    form[FORM + 'uiSearchButton2'] = 'Search'
    url, page = planner.request('POST', urljoin(url, 'AdvancedSearch.aspx'), form)
    if 'AuthorsIntermediate' in url:
        form = form_fields(page)
        for tag in re.findall(r'<input\b[^>]*type="checkbox"[^>]*>', page, re.I):
            name = re.search(r'\bname="([^"]+)"', tag)
            if name:
                form[html.unescape(name[1])] = 'on'
        buttons = [b for b in re.findall(r'<input\b[^>]*type="submit"[^>]*>', page, re.I) if 'ontinue' in b]
        if len(buttons) != 1:
            raise ProviderError('SfN planner author list has no Continue button')
        form[html.unescape(re.search(r'name="([^"]+)"', buttons[0])[1])] = html.unescape(re.search(r'value="([^"]*)"', buttons[0])[1])
        action = html.unescape(re.search(r'<form\b[^>]*action="([^"]+)"', page, re.I)[1])
        url, page = planner.request('POST', urljoin(url, action), form)
    saved = envelope(key, page, url)
    cache.save_response('sfn-search-v1:' + key, saved)
    return saved


def hits(source, key):
    page = checked_body(source, key)
    out = []
    for href, text in re.findall(r'href="([^"]*ViewAbstract\.aspx\?[^"]+)"[^>]*>(.*?)</a>', page, re.S | re.I):
        href = html.unescape(href)
        s, c = re.search(r'sKey=([0-9a-f-]{36})', href, re.I), re.search(r'cKey=([0-9a-f-]{36})', href, re.I)
        label = unicodedata.normalize('NFKC', html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', text)))).strip()
        if s and c:
            out.append((s[1].lower(), c[1].lower(), label))
    return out


def fetch_view(cache, client, url):
    saved = cache.response('sfn-source-v1:' + url, 3650 * 86400)
    if saved is not None and not client.refresh:
        checked_body(saved, url)
        return saved
    final, page = Planner(client).request('GET', url)
    saved = envelope(url, page, final)
    cache.save_response('sfn-source-v1:' + url, saved)
    return saved


def rows(page):
    found = {}
    last = None
    for label, value in re.findall(r"<td[^>]*class='ViewAbstractDataLabel'[^>]*>(.*?)</td>\s*<td[^>]*class='ViewAbstractData'[^>]*>(.*?)</td>",
                                   page, re.S | re.I):
        label = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', label))).strip().rstrip(':')
        if label:
            found.setdefault(label, value); last = label
        elif last:
            found[last] += ' ' + value
    return found


def text(value):
    return unicodedata.normalize('NFKC', re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', value)))).strip()


def abstract(source, url, year):
    page = checked_body(source, url)
    data = rows(page)
    # 2009 pages label the title "Title" and the time "Presentation Time".
    for new, old in (('Presentation Title', 'Title'), ('Presentation time', 'Presentation Time')):
        if new not in data and old in data:
            data[new] = data[old]
    for label in ('Program#/Poster#', 'Presentation Title', 'Authors', 'Disclosures'):
        if label not in data:
            raise ValueError('SfN abstract page lacks ' + label)
    program = text(data['Program#/Poster#']).split('/')[0].strip()
    if not re.fullmatch(r'\d{1,4}\.\d{1,2}', program):
        raise ValueError('SfN program number is not a poster/slide number: ' + program)
    footer = re.search(r'(\d{4}) Neuroscience Meeting Planner\.\s+(.+?): Society for Neuroscience, (\d{4})', text(page))
    when = re.search(r'\b(\d{4})\b', text(data.get('Presentation time', '')))
    if footer:
        if not footer[1] == footer[3] == str(year):
            raise ValueError('SfN planner footer names another meeting year')
        city = footer[2].strip()
    elif when and int(when[1]) == year and MEETINGS[year][0].lower() in url.lower():
        city = MEETINGS[year][1]
    else:
        raise ValueError('SfN abstract page does not confirm the meeting year')
    byline = re.sub(r'<sup>.*?</sup>', '', data['Authors'].split(';')[0], flags=re.S)
    capitals = [n.strip().lstrip('*').strip() for n in text(byline).split(',') if n.strip()]
    # "R. J. ROBINSON, II": a name suffix is its own comma item; suffixes are never cited (user rule).
    capitals = [n for n in capitals if n.rstrip('.').upper() not in ('JR', 'SR', 'II', 'III', 'IV')]
    # "<b>A.G. Ramayya:</b> None." (2010-) or "<b>J.R. Manning</b>, None;" (2009)
    disclosed = [text(n) for n in re.findall(r'<b>\s*([^<]+?)\s*:?\s*</b>', data['Disclosures'])]
    disclosed = [n.rstrip(':').strip() for n in disclosed]
    if not capitals or len(capitals) != len(disclosed):
        raise ValueError('SfN Authors and Disclosures lines disagree on the byline')
    authors = []
    for caps, name in zip(capitals, disclosed):
        m = re.fullmatch(r'((?:[A-Z]\.\s*|[A-Z]-[A-Z]\.\s*)+)(.+)', name)
        if not m:
            raise ValueError('Unsupported SfN disclosure name: ' + name)
        given, family = ' '.join(re.findall(r'[A-Z](?:-[A-Z])?\.', m[1])), m[2].strip()
        if normalized(caps).replace(' ', '') != normalized(m[1] + family).replace(' ', ''):
            raise ValueError('SfN Authors/Disclosures name mismatch: %s / %s' % (caps, name))
        authors.append({'given': given, 'family': family, 'suffix': ''})
    return {'program': program, 'title': text(data['Presentation Title']), 'authors': authors,
            'year': year, 'city': city}


def house_address(city):
    place, sep, state = city.rpartition(', ')
    return place + ', {' + state + '}' if sep and re.fullmatch(r'[A-Z]{2}', state) else city


def assess_sfn(fields, raw):
    candidate = {'source': SOURCE, 'doi': None, 'raw_record': raw, 'checked_fields': deepcopy(fields),
                 'issues': [], 'evidence': {}, 'proposal': None, 'category': 'held'}
    try:
        if not applicable(fields):
            raise ValueError('Not a Society for Neuroscience abstract citation')
        year = cited_year(fields)
        if year not in MEETINGS:
            candidate['unsupported_year'] = year
            raise ValueError(unsupported(year))
        family, initial = first_author(fields)
        key = search_key(year, family, initial)
        if raw.get('search', {}).get('url') != key:
            raise ValueError('Saved SfN search is for another meeting or author')
        wanted = normalize_title(unicodedata.normalize('NFKC', fields.get('title', '')))
        matches = []
        for s, c, label in hits(raw['search'], key):
            title = re.sub(r'^.*?\d{1,4}\.\d{1,2}(?:/\S+)?\s+-\s+', '', label)
            try:
                if normalize_title(title) == wanted:
                    matches.append(view_url(s, c, MEETINGS[year][0]))
            except ValueError:
                continue
        if len(set(matches)) != 1:
            raise ValueError('SfN planner: %d abstracts by %s, %s with this exact title (first results page)'
                             % (len(set(matches)), family, initial))
        url = matches[0]
        if raw.get('view', {}).get('url') != url:
            raise ValueError('Saved SfN abstract page is another abstract')
        item = abstract(raw['view'], url, year)
        candidate.update(url=url, program=item['program'])
        evidence, issues, proposal = candidate['evidence'], candidate['issues'], {}

        def check(field, source, ok, fix=None):
            evidence[field] = {'local': fields.get(field), 'source': source, 'match': bool(ok)}
            if not ok:
                issues.append(field + ': missing evidence or mismatch')
                if fix is not None:
                    proposal[field] = fix

        title_ok = normalize_title(item['title']) == wanted
        check('title', item['title'], title_ok)
        ok, _ = author_evidence(fields.get('author', ''), item['authors'])
        fix = None
        if not ok:
            from .correction_proposals import house_byline
            try:
                fix = house_byline(item['authors'], fields.get('author'))
            except ValueError as exc:
                issues.append('author: planner byline has no certain house form: ' + str(exc))
        check('author', item['authors'], ok, fix)
        check('year', year, True)
        check('number', item['program'], fields.get('number') == item['program'], item['program'])
        check('booktitle', BOOKTITLE, normalized(fields.get('booktitle', '')) == normalized(BOOKTITLE), BOOKTITLE)
        try:
            same_city = normalized(fields.get('address', '').replace('{', '').replace('}', '')) == normalized(item['city'])
        except ValueError:
            same_city = False
        check('address', item['city'], same_city, house_address(item['city']))
        check('organization', 'Society for Neuroscience',
              normalized(fields.get('organization', '')) == 'society for neuroscience', 'Society for Neuroscience')
        if fields.get('ENTRYTYPE') != 'inproceedings':
            issues.append('ENTRYTYPE: SfN abstracts are @inproceedings (house form)')
            proposal['ENTRYTYPE'] = 'inproceedings'
        for field in set(fields) & {'journal', 'publisher', 'volume', 'pages'}:
            issues.append(field + ': not part of the SfN house form')
            proposal.setdefault('remove', []).append(field)
        for field in set(fields) - {'ENTRYTYPE', 'ID', 'title', 'author', 'year', 'number', 'booktitle', 'address',
                                    'organization', 'journal', 'publisher', 'volume', 'pages'}:
            issues.append(field + ': no SfN planner verifier for this field')
        candidate['category'], candidate['proposal'] = classify(fields, issues, proposal, title_ok, authors=item['authors'],
                                                                source=url)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        candidate['issues'].append(str(exc) if str(exc).startswith('SfN') else 'SfN planner unresolved: ' + str(exc))
    candidate['issues'] = list(dict.fromkeys(candidate['issues']))
    if 'unsupported_year' in candidate:
        candidate['category'] = 'unsupported'
    result = outcome('needs_review' if candidate['issues'] else 'metadata_verified', candidate['issues'], [candidate])
    if not candidate['issues']:
        result.update(accepted_source=SOURCE, accepted_record_id=candidate['url'])
    return result


def valid_sfn_approval(result):
    if result.get('accepted_source') != SOURCE or result.get('external_evidence'):
        return False
    try:
        saved = [c for c in result['candidates'] if c.get('source') == SOURCE]
        if len(saved) != 1:
            return False
        c = saved[0]; checked = assess_sfn(c['checked_fields'], c['raw_record'])
        return (checked['status'] == 'metadata_verified' and checked['accepted_record_id'] == result['accepted_record_id']
                and checked['candidates'][0] == c)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def collect(cache, client, fields):
    """Search the meeting by first author, then fetch the one exact-title abstract.

    Unsupported years and entries without a usable first author make no request."""
    raw = {}
    try:
        year = cited_year(fields)
        family, initial = first_author(fields)
    except (ValueError, IndexError):
        return raw
    if year not in MEETINGS:
        return raw
    raw['search'] = search(cache, client, year, family, initial)
    wanted = normalize_title(unicodedata.normalize('NFKC', fields.get('title', '')))
    urls = set()
    for s, c, label in hits(raw['search'], raw['search']['url']):
        try:
            if normalize_title(re.sub(r'^.*?\d{1,4}\.\d{1,2}(?:/\S+)?\s+-\s+', '', label)) == wanted:
                urls.add(view_url(s, c, MEETINGS[year][0]))
        except ValueError:
            continue
    if len(urls) == 1:
        raw['view'] = fetch_view(cache, client, urls.pop())
    return raw


def run_sfn_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    return run_route(filename, cache, client, report, limit, snapshot, keys, name='sfn_review',
                     policy=SFN_POLICY, source=SOURCE, applicable=applicable, collect=collect,
                     assess=assess_sfn, attempt_url=lambda raw: raw.get('view', raw.get('search', {})).get('url'))


from .verification import register_approval_validator  # noqa: E402  (hook contract 2026-09-25)
register_approval_validator(valid_sfn_approval)
