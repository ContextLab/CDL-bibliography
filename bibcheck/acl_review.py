"""Verify ACL Anthology proceedings papers against the Anthology's own BibTeX.

The Anthology record (``https://aclanthology.org/<id>.bib``) is the
publisher's metadata: title, ordered authors, booktitle, year, pages, DOI.
It outranks a conflicting Crossref page range (ReimGure19: Crossref deposits
3980-3990; the Anthology, and the paper, give 3982--3992).

House booktitle rule (user, 2026-09-25): proceedings names omit the year.
The house form of an Anthology booktitle drops the year token and the
trailing parenthetical acronym; the ordinal edition number derived from the
year ("9th") may also be omitted. Anything else must match exactly.

Anthology IDs come from the citation (DOI 10.18653/v1/<id>, an Anthology
URL) or, for citations with neither, from an OpenAlex title search whose
location URLs name exactly one Anthology paper. Discovery only nominates a
candidate: title, authors, pages and year must then match the Anthology
record itself, so a discovered paper can never verify on the search alone.
"""
from copy import deepcopy
import json
import re
from urllib.parse import urlencode

import bibtexparser
from bibtexparser.bparser import BibTexParser

from preprint_review import checked_body, fetch_document, people
from verification import author_evidence, normalize_doi, normalize_title, normalized, outcome, split_authors
from osf_review import classify, run_route

ACL_POLICY = '1'
SOURCE = 'acl-anthology'
OLD_ID = r'[A-Z]\d{2}-\d{4}'
NEW_ID = r'\d{4}\.[a-z0-9-]+\.\d+'
ANTHOLOGY_ID = '(' + OLD_ID + '|' + NEW_ID + ')'
VENUE = re.compile(r'computational linguistics|natural language processing|\b(?:ACL|NAACL|EACL|EMNLP|CoNLL|COLING|AACL|IJCNLP)\b', re.I)


def parse_id(value):
    text = value.strip()
    for pattern in (r'(?:https?://(?:dx\.)?doi\.org/)?10\.(?:18653|3115)/v1/' + ANTHOLOGY_ID,
                    r'https?://(?:www\.)?aclanthology\.org/' + ANTHOLOGY_ID + r'(?:\.pdf|/)?',
                    r'https?://(?:www\.)?aclweb\.org/anthology/(?:[A-Z]/[A-Z]\d{2}/)?' + ANTHOLOGY_ID + r'(?:\.pdf|/)?'):
        match = re.fullmatch(pattern, text, re.I)
        if match:
            found = match[1]
            return found.upper() if re.fullmatch(OLD_ID, found, re.I) else found.lower()
    raise ValueError('Not an ACL Anthology identifier')


def venue(fields):
    return ' '.join(fields.get(f, '') for f in ('booktitle', 'journal', 'publisher', 'organization'))


def identifier(fields):
    """(anthology id, identity fields) or (None, []) for title discovery."""
    if fields.get('ENTRYTYPE') not in ('inproceedings', 'conference', 'article'):
        raise ValueError('This route requires a proceedings citation')
    supplied = []
    for field in ('doi', 'url'):
        if field in fields:
            try:
                supplied.append((field, parse_id(fields[field])))
            except ValueError:
                if field == 'doi' and fields['doi'].lower().startswith(('10.18653/', '10.3115/')):
                    raise
    if len({s[1] for s in supplied}) > 1:
        raise ValueError('Conflicting ACL Anthology identifiers')
    if supplied:
        return supplied[0][1], [s[0] for s in supplied]
    if 'doi' in fields or not VENUE.search(venue(fields)):
        raise ValueError('Not an ACL Anthology venue citation')
    if fields.get('ENTRYTYPE') == 'article' and not re.search(r'^\s*proceedings\b', fields.get('journal', ''), re.I):
        raise ValueError('Journal articles are not Anthology proceedings')
    return None, []


def bib_url(anthology_id):
    return 'https://aclanthology.org/' + anthology_id + '.bib'


def search_url(title):
    return 'https://api.openalex.org/works?' + urlencode(
        {'filter': 'title.search:' + ' '.join(re.sub(r'[^\w\s-]', ' ', title.replace('{', '').replace('}', '')).split()), 'select': 'id,title,locations,primary_location',
         'per-page': '25'})


def record(source, anthology_id):
    text = checked_body(source, bib_url(anthology_id))
    parser = BibTexParser(common_strings=True, interpolate_strings=True)
    parser.ignore_nonstandard_types = False
    entries = bibtexparser.loads(text, parser=parser).entries
    if len(entries) != 1:
        raise ValueError('Anthology BibTeX is missing or ambiguous')
    item = entries[0]
    if parse_id(item.get('url', '').rstrip('/') + '/') != anthology_id:
        raise ValueError('Anthology BibTeX names another paper')
    if item.get('doi') and not normalize_doi(item['doi']).endswith('/' + anthology_id.lower()):
        raise ValueError('Anthology DOI names another paper')
    for field in ('title', 'author', 'booktitle', 'year'):
        if not item.get(field, '').strip():
            raise ValueError('Anthology record lacks ' + field)
    return item


def anthology_people(item):
    out = []
    for name in split_authors(re.sub(r'\s+', ' ', item['author'])):
        family, sep, given = name.partition(',')
        if not sep or not family.strip() or not given.strip():
            raise ValueError('Unsupported Anthology author form: ' + name)
        out.append({'given': given.strip(), 'family': family.strip().strip('{}'), 'suffix': ''})
    return out


def house_booktitle(value):
    """Anthology booktitle -> house forms (year removed; acronym removed; ordinal optional)."""
    text = re.sub(r'\s+', ' ', value).strip()
    text = re.sub(r'\s*\([A-Z][A-Za-z-]*[A-Z](?:[- ](?:19|20)\d{2})?\)\s*$', '', text)  # trailing (EMNLP-IJCNLP)
    text = re.sub(r'\s*\b(?:19|20)\d{2}\b(?!\))', '', text)  # "the 2019 Conference", "COLING 2014,"
    text = re.sub(r'\s+([,:])', r'\1', text)
    plain = re.sub(r'\s+', ' ', text).strip()
    no_ordinal = re.sub(r'\s+', ' ', re.sub(r'\b\d+(?:st|nd|rd|th)\s+', '', plain)).strip()
    return plain, no_ordinal


def pages(value):
    return re.sub(r'\s*[-–—]+\s*', '--', (value or '').strip())


def assess_acl(fields, raw):
    candidate = {'source': SOURCE, 'doi': None, 'raw_record': raw, 'checked_fields': deepcopy(fields),
                 'issues': [], 'evidence': {}, 'proposal': None, 'category': 'held'}
    try:
        anthology_id, identity_fields = identifier(fields)
        if anthology_id is None:
            if normalize_title(raw.get('search_title', '')) != normalize_title(fields.get('title', '')):
                raise ValueError('No saved discovery search for this title')
            anthology_id = discover(json.loads(checked_body(raw['search'], search_url(raw['search_title']))), fields)
        if raw.get('anthology_id') != anthology_id:
            raise ValueError('Saved Anthology source belongs to another paper')
        item = record(raw['record'], anthology_id)
        authors = anthology_people(item)
        candidate.update(anthology_id=anthology_id, doi=normalize_doi(item['doi']) if item.get('doi') else None,
                         url='https://aclanthology.org/' + anthology_id + '/')
        evidence, issues, proposal = candidate['evidence'], candidate['issues'], {}

        def check(field, source, matches, fix=None):
            evidence[field] = {'local': fields.get(field), 'source': source, 'match': bool(matches)}
            if not matches:
                issues.append(field + ': missing evidence or mismatch')
                if fix is not None:
                    proposal[field] = fix

        title_ok = normalize_title(fields.get('title', '')) == normalize_title(item['title'])
        check('title', item['title'], title_ok)
        ok, _ = author_evidence(fields.get('author', ''), authors)
        fix = None
        if not ok:
            from correction_proposals import house_byline
            try:
                fix = house_byline(authors, fields.get('author'))
            except ValueError as exc:
                issues.append('author: source byline has no certain house form: ' + str(exc))
        check('author', item['author'], ok, fix)
        forms = house_booktitle(item['booktitle'])
        cited = fields.get('booktitle') or (fields.get('journal') if fields.get('ENTRYTYPE') == 'article' else None)
        try:
            venue_ok = bool(cited) and normalized(cited) in {normalized(f) for f in forms}
        except ValueError:
            venue_ok = False
        check('booktitle', {'anthology': item['booktitle'], 'house': forms[0]}, venue_ok, forms[0])
        check('year', item['year'], fields.get('year') == item['year'].strip(), item['year'].strip())
        if item.get('pages'):
            check('pages', {'pages': pages(item['pages']), 'role': 'Anthology (outranks Crossref)'},
                  pages(fields.get('pages')) == pages(item['pages']), pages(item['pages']))
        elif 'pages' in fields:
            issues.append('pages: Anthology record has no pages')
        if candidate['doi']:
            check('doi', candidate['doi'], bool(fields.get('doi')) and normalize_doi(fields['doi']) == candidate['doi'], item['doi'])
        elif 'doi' in fields:
            issues.append('doi: Anthology record has no DOI')
        if fields.get('ENTRYTYPE') != 'inproceedings':
            issues.append('ENTRYTYPE: Anthology proceedings papers are @inproceedings')
            proposal['ENTRYTYPE'] = 'inproceedings'
            if 'journal' in fields:
                proposal.setdefault('remove', []).append('journal')
                issues.append('journal: proceedings name belongs in booktitle')
        for field in ('publisher', 'address', 'editor'):
            if field in fields:
                try:
                    same = normalized(fields[field]) == normalized(item.get(field, ''))
                except ValueError:
                    same = False
                if field == 'editor' and not same:
                    same = author_evidence(fields[field], anthology_people({'author': item.get('editor', '')}))[0] if item.get('editor') else False
                check(field, item.get(field), same)
        for field in set(fields) - {'ENTRYTYPE', 'ID', 'title', 'author', 'booktitle', 'journal', 'year', 'pages',
                                    'doi', 'url', 'publisher', 'address', 'editor'}:
            issues.append(field + ': no Anthology verifier for this field')
        candidate['category'], candidate['proposal'] = classify(fields, issues, proposal, title_ok,
                                                                discovered=not identity_fields, authors=authors)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        candidate['issues'].append('ACL Anthology unresolved: ' + str(exc))
    candidate['issues'] = list(dict.fromkeys(candidate['issues']))
    result = outcome('needs_review' if candidate['issues'] else 'metadata_verified', candidate['issues'], [candidate])
    if not candidate['issues']:
        result.update(accepted_source=SOURCE, accepted_doi=candidate['doi'], accepted_record_id=candidate['anthology_id'])
    return result


def discover(data, fields):
    """The single Anthology ID named by OpenAlex works with the exact cited title."""
    ids = set()
    for work in data.get('results', []):
        try:
            if normalize_title(work.get('title') or '') != normalize_title(fields.get('title', '')):
                continue
        except ValueError:
            continue  # an index title with markup (e.g. a literal "\\n") is never a match
        for loc in (work.get('locations') or []) + [work.get('primary_location') or {}]:
            for url in (loc.get('landing_page_url'), loc.get('pdf_url'), loc.get('raw_source_name')):
                if url:
                    url = re.sub(r'^http://', 'https://', url)
                    url = re.sub(r'https://anthology\.aclweb\.org/', 'https://aclweb.org/anthology/', url)
                    url = url.replace('/anthology-new/', '/anthology/')
                    try:
                        ids.add(parse_id(url))
                    except ValueError:
                        pass
    if len(ids) != 1:
        raise ValueError('Discovery names no or several Anthology papers')
    return ids.pop()


def valid_acl_approval(result):
    if result.get('accepted_source') != SOURCE or result.get('external_evidence'):
        return False
    try:
        saved = [c for c in result['candidates'] if c.get('source') == SOURCE]
        if len(saved) != 1:
            return False
        c = saved[0]; checked = assess_acl(c['checked_fields'], c['raw_record'])
        return (checked['status'] == 'metadata_verified' and checked.get('accepted_doi') == result.get('accepted_doi')
                and checked['accepted_record_id'] == result['accepted_record_id'] and checked['candidates'][0] == c)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def applicable(fields):
    try:
        identifier(fields)
        return True
    except ValueError:
        return False


def collect(cache, client, fields):
    anthology_id, _ = identifier(fields)
    fetch = lambda url, check: fetch_document(cache, client, url, 'acl-source-v1:' + url, validate=check)
    raw = {}
    if anthology_id is None:
        title = fields.get('title', '')
        raw.update(search_title=title, search=fetch(search_url(title), lambda s: json.loads(checked_body(s, search_url(title)))['results']))
        try:
            anthology_id = discover(json.loads(raw['search']['body']), fields)
        except ValueError:
            raw['anthology_id'] = None
            return raw
    raw['anthology_id'] = anthology_id
    raw['record'] = fetch(bib_url(anthology_id), lambda s: record(s, anthology_id))
    return raw


def run_acl_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    return run_route(filename, cache, client, report, limit, snapshot, keys, name='acl_review',
                     policy=ACL_POLICY, source=SOURCE, applicable=applicable, collect=collect,
                     assess=assess_acl, attempt_url=lambda raw: raw.get('record', raw.get('search', {})).get('url'))


from verification import register_approval_validator  # noqa: E402  (hook contract 2026-09-25)
register_approval_validator(valid_acl_approval)
