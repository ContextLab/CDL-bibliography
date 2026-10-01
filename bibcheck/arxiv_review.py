"""Verify cited arXiv records against Atom, repository HTML and DataCite.

Unversioned arXiv identifiers denote the current version (arXiv's documented
semantics); the approval records that version. Explicit versions remain binding.
Raw source documents are portable and all decisions can be reconstructed.
"""
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
from urllib.parse import quote
import xml.etree.ElementTree as ET

from publisher_metadata import PublisherMetadata
from preprint_review import checked_body, fetch_document, people, context_issues
from verification import (author_evidence, current_results, export_snapshot, load_entries,
                          normalize_doi, normalize_title, normalized, outcome, run_lock,
                          validate_output_path, write_report)

ARXIV_POLICY = '1'
SOURCE = 'arxiv-repository'
NS = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom',
      'o': 'http://a9.com/-/spec/opensearch/1.1/'}
ID_PATTERN = r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})'
NOTICE = re.compile(r'\b(?:withdrawn|withdrawal|retracted|retraction|erratum|corrigendum)\b|expression of concern', re.I)


def parse_id(value):
    text = normalized(value)
    text = re.sub(r'^(?:https?://)?(?:dx\.)?doi\.org/', '', text)
    text = re.sub(r'^(?:doi:\s*)?10\.48550/arxiv\.', '', text)
    text = re.sub(r'^https?://arxiv\.org/(?:abs|pdf)/', '', text)
    text = re.sub(r'^arxiv:\s*', '', text)
    match = re.fullmatch('(' + ID_PATTERN + r')(?:v([1-9]\d*))?', text)
    if not match:
        raise ValueError('Not a complete arXiv identifier')
    base = match[1]
    digits = base.split('/')[-1].split('.')[0]
    if not 1 <= int(digits[2:4]) <= 12:
        raise ValueError('Invalid arXiv identifier month')
    if '/' not in base:
        if int(digits) < 704 or len(base.split('.')[1]) != (4 if int(digits) < 1501 else 5):
            raise ValueError('Invalid modern arXiv identifier format')
    elif '.' in base.split('/')[0]:
        archive, suffix = base.split('/', 1)
        archive, category = archive.split('.')
        base = archive + '.' + category.upper() + '/' + suffix
    return base, int(match[2]) if match[2] else None


def identifier(fields):
    if fields.get('ENTRYTYPE') != 'article':
        raise ValueError('This route requires an arXiv article citation')
    journal = normalized(fields.get('journal', ''))
    supplied = []
    if journal != 'arxiv':
        match = re.fullmatch(r'arxiv preprint (arxiv:.+)', journal)
        if not match:
            raise ValueError('Citation does not name the arXiv repository')
        supplied.append(('journal', *parse_id(match[1])))
    split = ('number' in fields and re.fullmatch(r'\d{4}', fields.get('volume', ''))
             and re.fullmatch(r'\d{4,5}(?:v[1-9]\d*)?', fields['number']))
    if split:
        base, version = parse_id(fields['volume'] + '.' + fields['number'])
        supplied.extend([('volume', base, version), ('number', base, version)])
    for field in ('doi', 'volume', 'pages', 'eprint', 'url'):
        if field in fields and not (split and field == 'volume'):
            supplied.append((field, *parse_id(fields[field])))
    if not supplied or len({s[1] for s in supplied}) != 1 or len({s[2] for s in supplied if s[2]}) > 1:
        raise ValueError('Missing or conflicting arXiv identifiers/versions')
    if 'number' in fields and not split:
        raise ValueError('Uncorroborated arXiv number field')
    return supplied[0][1], next((s[2] for s in supplied if s[2]), None), [s[0] for s in supplied]


def doi_for(base):
    return '10.48550/arxiv.' + base.lower()


def api_url(identifier):
    return 'https://export.arxiv.org/api/query?id_list=' + quote(identifier, safe='/')


def html_url(identifier):
    return 'https://arxiv.org/abs/' + identifier


def registry_url(base):
    return 'https://api.datacite.org/dois/10.48550/arXiv.' + base


def timestamp(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Repository timestamp has no timezone')
    return stamp.astimezone(timezone.utc)


def atom(source, requested):
    try:
        root = ET.fromstring(checked_body(source, api_url(requested)))
    except ET.ParseError as exc:
        raise ValueError('Malformed arXiv Atom response') from exc
    entries = root.findall('a:entry', NS)
    if (root.tag != '{' + NS['a'] + '}feed' or len(entries) != 1
            or root.findtext('o:totalResults', namespaces=NS) != '1'
            or root.findtext('o:startIndex', namespaces=NS) != '0'):
        raise ValueError('Missing, ambiguous or incomplete arXiv API result')
    item = entries[0]
    def one(tag):
        values = item.findall(tag, NS)
        if len(values) != 1 or not (values[0].text or '').strip():
            raise ValueError('Missing or ambiguous arXiv API ' + tag)
        return values[0].text.strip()
    uri = one('a:id')
    if not re.fullmatch(r'https?://arxiv\.org/abs/.+', uri):
        raise ValueError('Unexpected arXiv API identity URL')
    base, version = parse_id(uri.split('/abs/', 1)[1]); wanted, explicit = parse_id(requested)
    if base != wanted or version is None or (explicit and version != explicit):
        raise ValueError('arXiv API returned a different identifier/version')
    authors = []
    for author in item.findall('a:author', NS):
        names = author.findall('a:name', NS)
        if len(names) != 1 or not (names[0].text or '').strip():
            raise ValueError('Missing arXiv author name')
        authors.append(names[0].text.strip())
    if not 1 <= len(authors) <= 1000:
        raise ValueError('Incomplete arXiv author list')
    people(authors)
    published, updated = timestamp(one('a:published')), timestamp(one('a:updated'))
    if updated < published or (version == 1 and updated != published):
        raise ValueError('Inconsistent arXiv version dates')
    result = {'base': base, 'version': version, 'title': one('a:title'), 'authors': authors,
              'published': published, 'updated': updated, 'summary': one('a:summary')}
    for name in ('comment', 'doi'):
        values = item.findall('x:' + name, NS)
        if len(values) > 1:
            raise ValueError('Ambiguous arXiv ' + name)
        result[name] = (values[0].text or '').strip() if values else ''
    return result


class ArxivPage(PublisherMetadata):
    def __init__(self):
        super().__init__()
        self.og_urls = []; self.history = []; self.depth = 0; self.history_count = 0

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attrs = dict(attrs)
        if tag == 'meta' and self.in_head and attrs.get('property') == 'og:url':
            self.og_urls.append(attrs.get('content'))
        if tag == 'div':
            if self.depth:
                self.depth += 1
            elif 'submission-history' in attrs.get('class', '').split():
                self.depth = 1; self.history_count += 1

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == 'div' and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.history.append(data)


def page(source, requested):
    parser = ArxivPage(); parser.feed(checked_body(source, html_url(requested)))
    if parser.history_count != 1 or parser.depth:
        raise ValueError('Missing or malformed arXiv submission history')
    return parser


def registry(source, base):
    data = json.loads(checked_body(source, registry_url(base)))['data']
    attrs = data['attributes']
    if (data['type'] != 'dois' or normalize_doi(data['id']) != doi_for(base)
            or normalize_doi(attrs['doi']) != doi_for(base)
            or attrs['url'] != html_url(base) or attrs['state'] != 'findable'
            or normalized(attrs['publisher']) != 'arxiv'):
        raise ValueError('DataCite does not identify the same public arXiv record')
    return attrs


def notice_dois(candidate):
    if candidate.get('source') != SOURCE:
        return set()
    raw = candidate.get('raw_record', {}); base = raw.get('base')
    if not base or candidate.get('doi') != doi_for(base):
        return set()
    try:
        latest = atom(raw['latest_api'], base)
        if any(NOTICE.search(latest[k]) for k in ('title', 'summary', 'comment')):
            return {doi_for(base)}
        if NOTICE.search(' '.join(page(raw['latest_html'], base).history)):
            return {doi_for(base)}
        attrs = registry(raw['datacite'], base)
        if any(NOTICE.search(x.get('description', '')) for x in attrs.get('descriptions', [])):
            return {doi_for(base)}
        if any(NOTICE.search(x.get('dateType', '') + ' ' + x.get('dateInformation', '')) for x in attrs['dates']):
            return {doi_for(base)}
        if any(x.get('relationType') in {'IsObsoletedBy', 'Obsoletes'} for x in attrs.get('relatedIdentifiers', [])):
            return {doi_for(base)}
    except (ValueError, KeyError, TypeError, AttributeError, ET.ParseError):
        pass
    return set()


def check_page(source, requested, record):
    parser = page(source, requested); meta = parser.source_metadata()
    def one(name):
        values = meta.get('citation_' + name, [])
        if len(values) != 1:
            raise ValueError('Missing or ambiguous arXiv HTML ' + name)
        return values[0]
    exact = record['base'] + 'v' + str(record['version'])
    if (parser.og_urls != [html_url(exact)] or one('arxiv_id') != record['base']
            or one('date') != record['published'].strftime('%Y/%m/%d')
            or one('online_date') != record['updated'].strftime('%Y/%m/%d')
            or normalize_title(one('title')) != normalize_title(record['title'])
            or not author_evidence(' and '.join(record['authors']), people(meta.get('citation_author', [])))[0]):
        raise ValueError('arXiv HTML and API identity, dates, title or authors conflict')
    history = ' '.join(parser.history)
    stamps = re.findall(r'\[v([1-9]\d*)\]\s+([A-Za-z]{3}, \d{1,2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} UTC)', history)
    if not stamps or len(stamps) != len(re.findall(r'\[v\d+\]', history)):
        raise ValueError('Incomplete arXiv HTML version dates')
    dates = [parsedate_to_datetime(s).astimezone(timezone.utc) for _, s in stamps]
    if [int(v) for v, _ in stamps] != list(range(1, len(stamps) + 1)) or dates != sorted(dates):
        raise ValueError('Noncontiguous arXiv HTML version history')
    if dates[0] != record['published'] or record['version'] > len(dates) or dates[record['version']-1] != record['updated']:
        raise ValueError('API version dates conflict with HTML history')
    if NOTICE.search(history):
        raise ValueError('arXiv history contains notice evidence')
    return dates, meta


def assess_arxiv(fields, raw):
    candidate = {'source': SOURCE, 'doi': doi_for(raw.get('base', '')), 'raw_record': raw,
                 'checked_fields': deepcopy(fields), 'issues': [], 'evidence': {}}
    try:
        base, explicit, identity_fields = identifier(fields)
        if raw['base'] != base:
            raise ValueError('Saved arXiv source belongs to another work')
        if notice_dois(candidate):
            raise ValueError('arXiv withdrawal or notice requires adjudication')
        latest = atom(raw['latest_api'], base)
        history, _ = check_page(raw['latest_html'], base, latest)
        if len(history) != latest['version']:
            raise ValueError('arXiv current version conflicts with complete history')
        selected = latest
        if explicit:
            requested = base + 'v' + str(explicit)
            selected = atom(raw['selected_api'], requested)
            other_history, _ = check_page(raw['selected_html'], requested, selected)
            if other_history != history or selected['published'] != latest['published']:
                raise ValueError('Selected and latest arXiv histories conflict')
            if any(NOTICE.search(selected[k]) for k in ('title', 'summary', 'comment')):
                raise ValueError('Selected arXiv version contains notice evidence')
        attrs = registry(raw['datacite'], base)
        if (attrs.get('version') != str(latest['version'])
                or attrs.get('types', {}).get('resourceType') != 'Article'
                or attrs.get('types', {}).get('resourceTypeGeneral') not in {'Preprint', 'Text'}):
            raise ValueError('DataCite type or version conflicts with arXiv')
        titles = attrs.get('titles', [])
        if len(titles) != 1 or normalize_title(titles[0]['title']) != normalize_title(latest['title']):
            raise ValueError('DataCite title conflicts with latest arXiv version')
        creators = attrs['creators']; authors = []
        for creator in creators:
            if creator.get('nameType') != 'Personal' or not creator.get('givenName') or not creator.get('familyName'):
                raise ValueError('Incomplete or unsupported DataCite creator')
            author = {'given': creator['givenName'], 'family': creator['familyName']}
            if not author_evidence(creator['name'], [author])[0]:
                raise ValueError('Conflicting DataCite name representations')
            authors.append(author)
        if not author_evidence(' and '.join(latest['authors']), authors)[0]:
            raise ValueError('DataCite ordered byline conflicts with latest arXiv version')
        submitted = [x for x in attrs['dates'] if x.get('dateType') == 'Submitted']
        issued = [x.get('date') for x in attrs['dates'] if x.get('dateType') == 'Issued']
        if (len(submitted) != len(history)
                or [x.get('dateInformation') for x in submitted] != ['v'+str(i) for i in range(1,len(history)+1)]
                or [timestamp(x['date']) for x in submitted] != history
                or attrs.get('publicationYear') != latest['published'].year
                or issued != [str(attrs['publicationYear'])]):
            raise ValueError('DataCite publication year/version dates conflict')
        for relation in attrs.get('relatedIdentifiers', []):
            if (relation.get('relationType') not in {'IsIdenticalTo', 'IsPreprintOf', 'IsVersionOf'}
                    or relation.get('relatedIdentifierType') != 'DOI'
                    or not latest['doi']
                    or normalize_doi(relation['relatedIdentifier']) != normalize_doi(latest['doi'])
                    or normalize_doi(relation['relatedIdentifier']) == doi_for(base)):
                raise ValueError('DataCite relationship requires adjudication')
        evidence = candidate['evidence']
        def check(field, source, matches):
            evidence[field] = {'local': fields.get(field), 'source': source, 'match': bool(matches)}
            if not matches:
                candidate['issues'].append(field + ': missing evidence or mismatch')
        check('ENTRYTYPE', 'arXiv repository article', True)
        check('journal', 'arXiv', True)
        check('title', selected['title'], normalize_title(fields.get('title', '')) == normalize_title(selected['title']))
        check('author', people(selected['authors']), author_evidence(fields.get('author', ''), people(selected['authors']))[0])
        year = selected['updated'].year if explicit else attrs['publicationYear']
        check('year', {'year': year, 'role': 'selected-version date' if explicit else 'DataCite publication year'}, fields.get('year') == str(year))
        for field in identity_fields:
            check(field, {'identifier': base, 'version': selected['version'], 'role': 'repository identifier'}, True)
        for field in ('publisher', 'archiveprefix'):
            if field in fields:
                check(field, 'arXiv', normalized(fields[field]) == 'arxiv')
        for field in set(fields) - {'ENTRYTYPE','ID','force','journal','title','author','year','publisher','archiveprefix'} - set(identity_fields):
            candidate['issues'].append(field + ': no arXiv verifier for this field')
        candidate.update(version=selected['version'], url=html_url(base+'v'+str(selected['version'])), retrieved_at=raw['latest_api']['retrieved_at'])
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, ET.ParseError) as exc:
        candidate['issues'].append('arXiv unresolved: ' + str(exc))
    result = outcome('needs_review' if candidate['issues'] else 'metadata_verified', candidate['issues'], [candidate])
    if not candidate['issues']:
        result.update(accepted_source=SOURCE, accepted_doi=doi_for(base), accepted_version=selected['version'])
    return result


def reassess_saved_arxiv(fields, previous):
    saved = [c for c in previous.get('candidates', []) if c.get('source') == SOURCE and 'checked_fields' in c]
    if not saved:
        return None
    if len(saved) != 1:
        return outcome('needs_review', ['Conflicting arXiv source envelopes'], previous['candidates'])
    result = assess_arxiv(fields, saved[0]['raw_record'])
    result['attempts'] = previous.get('attempts', [])
    result['candidates'] = [c for c in previous['candidates'] if c is not saved[0]] + result['candidates']
    issues = context_issues(fields, result['candidates'], saved[0]['doi'])
    if issues:
        result.update(status='needs_review', issues=issues)
        for name in ('accepted_doi','accepted_source','accepted_version'):
            result.pop(name, None)
    return result


def valid_arxiv_approval(result):
    if result.get('accepted_source') != SOURCE or result.get('external_evidence'):
        return False
    try:
        saved = [c for c in result['candidates'] if c.get('source') == SOURCE]
        if len(saved) != 1 or context_issues(saved[0]['checked_fields'], result['candidates'], result['accepted_doi']):
            return False
        c = saved[0]; checked = assess_arxiv(c['checked_fields'], c['raw_record'])
        return (checked['status'] == 'metadata_verified' and checked['accepted_doi'] == result['accepted_doi']
                and checked['accepted_version'] == result['accepted_version'] and checked['candidates'][0] == c)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def collect(cache, client, fields):
    base, explicit, _ = identifier(fields)
    raw = {'base': base}
    requests = [('latest_api', api_url(base), lambda s: atom(s, base)),
                ('latest_html', html_url(base), lambda s: page(s, base)),
                ('datacite', registry_url(base), lambda s: registry(s, base))]
    if explicit:
        selected = base + 'v' + str(explicit)
        requests.extend([('selected_api', api_url(selected), lambda s: atom(s, selected)),
                         ('selected_html', html_url(selected), lambda s: page(s, selected))])
    for name, url, validate in requests:
        raw[name] = fetch_document(cache, client, url, 'arxiv-source-v1:' + url, validate=validate)
    return raw


def run_arxiv_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    with run_lock(cache):
        entries = load_entries(filename); count = 0
        if keys is not None and set(keys) - entries.keys():
            raise ValueError('arXiv keys must name existing citations')
        try:
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
                previous = cache.get(filename, entry)
                if (not previous or previous['status'] != 'needs_review' or previous.get('external_evidence')
                        or previous.get('arxiv_review', {}).get('policy') == ARXIV_POLICY):
                    continue
                try:
                    identifier(entry['fields'])
                except ValueError:
                    continue
                if limit is not None and count >= limit:
                    break
                raw = collect(cache, client, entry['fields'])
                initial = assess_arxiv(entry['fields'], raw)
                initial['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != SOURCE] + initial['candidates']
                initial['attempts'] = previous.get('attempts', []) + [{'source': SOURCE, 'url': raw['latest_api']['url']}]
                result = reassess_saved_arxiv(entry['fields'], initial)
                for name in ('auto_review','discovery_review','catalogue_review','preprint_review','research_attempt'):
                    if name in previous:
                        result[name] = deepcopy(previous[name])
                result['arxiv_review'] = {'policy': ARXIV_POLICY}
                cache.put(filename, entry, result); count += 1
        finally:
            write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
        return current_results(filename, cache, entries)
