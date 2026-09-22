"""Verify a bioRxiv version from repository history, HTML head and DOI metadata.

Repository identifiers in legacy volume/pages slots are checked as identifiers,
never confused with journal publication coordinates. No journal version replaces
an explicitly cited preprint. All source bodies remain portable and recheckable.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
import re

import requests
from bibtexparser.customization import splitname
from publisher_metadata import PublisherMetadata
from verification import (ProviderError, author_evidence, current_results, export_snapshot,
                          load_entries, normalize_doi, normalize_title, normalized, now,
                          outcome, run_lock, validate_output_path, write_report)

PREPRINT_POLICY = '2'
SOURCE = 'biorxiv-preprint'
MAX_BYTES = 2_000_000
BIO_ID = r'10\.1101/(?:\d{4}\.\d{2}\.\d{2}\.)?\d{6,}'


def identifier(fields):
    if fields.get('ENTRYTYPE') != 'article' or normalized(fields.get('journal', '')) != 'biorxiv':
        raise ValueError('This route requires an explicitly cited bioRxiv preprint')
    found = []
    for field in ('doi', 'volume', 'pages'):
        if field not in fields:
            continue
        text = normalized(fields[field])
        text = re.sub(r'^(?:https?://)?(?:dx\.)?doi\.org/', '', text)
        text = re.sub(r'^doi:\s*', '', text)
        if field != 'doi' and re.fullmatch(r'\d{6,}(?:v[1-9]\d*)?', text):
            text = '10.1101/' + text
        match = re.fullmatch('(' + BIO_ID + r')(?:v([1-9]\d*))?', text)
        if not match:
            raise ValueError(field + ': not an unambiguous bioRxiv identifier')
        found.append((field, match[1], int(match[2]) if match[2] else None))
    if not found or len({x[1] for x in found}) != 1 or len({x[2] for x in found if x[2]}) > 1:
        raise ValueError('Missing or conflicting preprint identifiers/versions')
    return found[0][1], next((x[2] for x in found if x[2]), None), [x[0] for x in found]


def api_url(doi):
    if not re.fullmatch(BIO_ID, doi):
        raise ValueError('Invalid bioRxiv DOI')
    return 'https://api.biorxiv.org/details/biorxiv/' + doi + '/na/json'


def html_url(doi, version):
    return 'https://www.biorxiv.org/content/' + doi + 'v' + str(version)


def checked_body(source, url):
    body = source['body']
    if (source['url'] != url or not isinstance(body, str) or len(body.encode()) > MAX_BYTES
            or source.get('http_status', 200) != 200
            or hashlib.sha256(body.encode()).hexdigest() != source['document_sha256']):
        raise ValueError('Invalid preprint source provenance, body or hash')
    return body


def versions(source, doi):
    data = json.loads(checked_body(source, api_url(doi)))
    if (not isinstance(data, dict) or len(data.get('messages', [])) != 1
            or data['messages'][0].get('status') != 'ok'
            or not isinstance(data.get('collection'), list) or not 1 <= len(data['collection']) <= 50):
        raise ValueError('Missing or incomplete repository history')
    rows = data['collection']
    for index, row in enumerate(rows, 1):
        if (row.get('doi') != doi or row.get('server', '').lower() != 'biorxiv'
                or row.get('version') != str(index)
                or any(not isinstance(row.get(k), str) or not row[k].strip()
                       for k in ('title', 'authors', 'date', 'type', 'published'))):
            raise ValueError('Conflicting identity or noncontiguous repository versions')
        if date.fromisoformat(row['date']).isoformat() != row['date']:
            raise ValueError('Invalid repository publication date')
    if any(a['date'] > b['date'] for a, b in zip(rows, rows[1:])):
        raise ValueError('Nonchronological repository versions')
    return rows


def notice_dois(candidate):
    if candidate.get('source') != SOURCE:
        return set()
    try:
        doi = candidate['doi']; rows = versions(candidate['raw_record']['api'], doi)
        if any(re.search(r'withdraw|retract|correct|expression of concern', row['type'], re.I)
               or re.match(r'\s*(?:withdrawn|retracted|correction)\s*:', row['title'], re.I)
               for row in rows):
            return {doi}
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return set()


def people(names):
    result = []
    for name in names:
        if not name.strip() or re.search(r'\bet\s+al\b|\bothers\b', name, re.I):
            raise ValueError('Incomplete repository author list')
        parts = splitname(name.strip(), strict_mode=True)
        result.append({'given': ' '.join(parts['first']), 'family': ' '.join(parts['von'] + parts['last']),
                       'suffix': ' '.join(parts['jr'])})
    return result


def assess_preprint(fields, api, html, primary):
    candidate = {'source': SOURCE, 'doi': api.get('doi'), 'raw_record': {'api': api, 'html': html, 'crossref': primary},
                 'evidence': {}, 'issues': [], 'checked_fields': deepcopy(fields)}
    try:
        doi, explicit, identity_fields = identifier(fields); candidate['doi'] = doi
        rows = versions(api, doi)
        if notice_dois(candidate) or any(row['type'].lower() != 'new results' for row in rows):
            raise ValueError('Repository history contains a withdrawal, notice or unsupported article type')
        if explicit is None and len(rows) != 1:
            raise ValueError('Multiple repository versions require an explicit version identifier')
        version = explicit or 1
        if version > len(rows):
            raise ValueError('Cited version is absent from repository history')
        row = rows[version - 1]
        parser = PublisherMetadata(); parser.feed(checked_body(html, html_url(doi, version)))
        metadata = parser.source_metadata()
        def one(name):
            values = metadata.get('citation_' + name, [])
            if len(values) != 1:
                raise ValueError('Missing or ambiguous repository HTML ' + name)
            return values[0]
        if (one('doi') != doi or one('id') != doi.split('/', 1)[1] + 'v' + str(version)
                or one('public_url') != html_url(doi, version)
                or normalized(one('journal_title')) != 'biorxiv'
                or one('date') != row['date'] or normalized(one('section')) != 'new results'):
            raise ValueError('Repository page identity, version, venue or date conflicts')
        html_people = people(metadata.get('citation_author', []))
        api_names = row['authors'].rstrip(';').split(';')
        if not author_evidence(' and '.join(n.strip() for n in api_names), html_people)[0]:
            raise ValueError('API author order/names conflict with the version page')
        if (primary.get('type') != 'posted-content' or primary.get('subtype') != 'preprint'
                or normalize_doi(primary.get('DOI', '')) != doi
                or primary.get('update-to') or primary.get('updated-by')):
            raise ValueError('DOI registry does not corroborate an unflagged preprint identity')
        if primary.get('published', {}).get('date-parts') != [[int(x) for x in rows[0]['date'].split('-')]]:
            raise ValueError('Registry first-posting date conflicts with repository history')
        relation = primary.get('relation') or {}
        if not isinstance(relation, dict) or set(relation) - {'is-preprint-of'}:
            raise ValueError('DOI registry relationship requires adjudication')
        if relation:
            linked = relation['is-preprint-of']
            if (not isinstance(linked, list) or not linked
                    or any(x.get('id-type') != 'doi'
                           or normalize_doi(x.get('id', '')) != normalize_doi(row['published'])
                           or normalize_doi(x.get('id', '')) == doi for x in linked)):
                raise ValueError('Preprint-to-journal relationship conflicts with repository')
        titles = primary.get('title', [])
        if len(titles) != 1 or primary.get('subtitle'):
            raise ValueError('Registry preprint title is ambiguous')
        if (normalize_title(row['title']) != normalize_title(one('title'))
                or normalize_title(titles[0]) != normalize_title(row['title'])):
            raise ValueError('Repository and registry preprint titles conflict')
        # Require the complete version byline, and registry corroboration. A
        # later registry byline never replaces an earlier repository byline.
        if not author_evidence(' and '.join(metadata.get('citation_author', [])), primary.get('author', []))[0]:
            raise ValueError('Registry author order/names conflict with the version page')
        evidence = candidate['evidence']
        def check(field, source, match):
            evidence[field] = {'local': fields.get(field), 'source': source, 'match': bool(match)}
            if not match:
                candidate['issues'].append(field + ': missing evidence or mismatch')
        check('ENTRYTYPE', 'repository preprint', fields['ENTRYTYPE'] == 'article')
        check('journal', 'bioRxiv', normalized(fields['journal']) == 'biorxiv')
        check('title', row['title'], normalize_title(fields.get('title', '')) == normalize_title(row['title']))
        check('author', html_people, author_evidence(fields.get('author', ''), html_people)[0])
        check('year', row['date'], fields.get('year') == row['date'][:4])
        for field in identity_fields:
            check(field, {'doi': doi, 'version': version, 'role': 'repository identifier'}, True)
        if 'publisher' in fields:
            check('publisher', one('publisher'), normalized(fields['publisher']) == normalized(one('publisher')))
        for field in set(fields) - {'ID', 'force', 'ENTRYTYPE', 'journal', 'title', 'author', 'year', 'publisher'} - set(identity_fields):
            candidate['issues'].append(field + ': no preprint verifier for this field')
        candidate.update(version=version, url=html_url(doi, version), retrieved_at=api['retrieved_at'])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        candidate['issues'].append('Preprint unresolved: ' + str(exc))
    result = outcome('needs_review' if candidate['issues'] else 'metadata_verified', candidate['issues'], [candidate])
    if not candidate['issues']:
        result.update(accepted_source=SOURCE, accepted_doi=doi, accepted_version=version)
    return result


def valid_preprint_approval(result):
    if result.get('accepted_source') != SOURCE or result.get('external_evidence'):
        return False
    try:
        saved = [c for c in result['candidates'] if c.get('source') == SOURCE]
        if len(saved) != 1:
            return False
        c = saved[0]; raw = c['raw_record']
        if context_issues(c['checked_fields'], result['candidates'], result['accepted_doi']):
            return False
        checked = assess_preprint(c['checked_fields'], raw['api'], raw['html'], raw['crossref'])
        return (checked['status'] == 'metadata_verified' and checked['accepted_doi'] == result['accepted_doi']
                and checked['accepted_version'] == result['accepted_version'] and checked['candidates'][0] == c)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def context_issues(fields, candidates, doi):
    from auto_review import secondary_notice_flags, secondary_suffix_conflicts
    from source_locators import locator_conflicts
    if (doi in secondary_notice_flags(candidates) or doi in secondary_suffix_conflicts(fields, candidates)
            or doi in locator_conflicts(fields, candidates)):
        return ['Known DOI-linked source evidence requires adjudication']
    for c in candidates:
        if c.get('source') == 'crossref' and c.get('doi') == doi:
            record = c.get('record', {})
            if record.get('update-to') or record.get('updated-by'):
                return ['DOI registry notice requires adjudication']
    return []


def reassess_saved_preprint(fields, previous):
    saved = [c for c in previous.get('candidates', []) if c.get('source') == SOURCE and 'html' in c.get('raw_record', {})]
    if not saved:
        return None
    if len(saved) != 1:
        return outcome('needs_review', ['Conflicting preprint source envelopes'], previous['candidates'])
    raw = saved[0]['raw_record']; result = assess_preprint(fields, raw['api'], raw['html'], raw['crossref'])
    result['attempts'] = previous.get('attempts', [])
    result['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != SOURCE] + result['candidates']
    issues = context_issues(fields, result['candidates'], saved[0]['doi'])
    if issues:
        result.update(status='needs_review', issues=issues)
        for name in ('accepted_source', 'accepted_doi', 'accepted_version'):
            result.pop(name, None)
    return result


def fetch_document(cache, client, url, identity, validate=None):
    saved = cache.response(identity, 30 * 86400)
    if saved is not None and not client.refresh:
        checked_body(saved, url)
        if validate:
            validate(saved)
        return saved
    interval = client.interval; client.interval = max(interval, 3.1)
    try:
        response = client.source_request(url, timeout=(10, 45), allow_redirects=False, stream=True)
        try:
            if response.status_code != 200:
                raise ProviderError('Preprint source HTTP ' + str(response.status_code))
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ProviderError('Oversize preprint document')
            text = bytes(body).decode('utf-8-sig')
            saved = {'url': response.url, 'body': text, 'document_sha256': hashlib.sha256(text.encode()).hexdigest(), 'retrieved_at': now()}
        finally:
            response.close()
    except (requests.RequestException, UnicodeError) as exc:
        raise ProviderError('Preprint retrieval failed: ' + str(exc)) from exc
    finally:
        client.interval = interval
    checked_body(saved, url)
    if validate:
        validate(saved)
    cache.save_response(identity, saved)
    return saved


def run_preprint_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    with run_lock(cache):
        entries = load_entries(filename)
        if keys is not None and set(keys) - entries.keys():
            raise ValueError('Preprint keys must name existing citations')
        count = 0
        try:
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
                previous = cache.get(filename, entry)
                if (not previous or previous['status'] != 'needs_review' or previous.get('external_evidence')
                        or previous.get('preprint_review', {}).get('policy') == PREPRINT_POLICY):
                    continue
                try:
                    doi, explicit, _ = identifier(entry['fields'])
                except ValueError:
                    continue
                if limit is not None and count >= limit:
                    break
                api = fetch_document(cache, client, api_url(doi), 'biorxiv-details-v1:' + doi,
                                     validate=lambda source: versions(source, doi))
                rows = versions(api, doi)
                selected = explicit or (1 if len(rows) == 1 else None)
                negative = notice_dois({'source': SOURCE, 'doi': doi, 'raw_record': {'api': api}})
                html = {}
                if selected and selected <= len(rows) and not negative:
                    url = html_url(doi, selected)
                    html = fetch_document(cache, client, url, 'biorxiv-html-v1:' + url)
                primaries = [c['record'] for c in previous.get('candidates', [])
                             if c.get('source') == 'crossref' and c.get('doi') == doi]
                if not primaries:
                    response = client.crossref_doi(doi)
                    primary = response.get('body', {}).get('message', {}) if response.get('body') else {}
                else:
                    primary = primaries[0]
                result = assess_preprint(entry['fields'], api, html, primary)
                result['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != SOURCE] + result['candidates']
                issues = context_issues(entry['fields'], result['candidates'], doi)
                if issues:
                    result.update(status='needs_review', issues=issues)
                    for name in ('accepted_source', 'accepted_doi', 'accepted_version'):
                        result.pop(name, None)
                result['attempts'] = previous.get('attempts', []) + [{'source': SOURCE, 'url': api['url']}]
                for name in ('auto_review', 'discovery_review', 'catalogue_review', 'research_attempt'):
                    if name in previous:
                        result[name] = deepcopy(previous[name])
                result['preprint_review'] = {'policy': PREPRINT_POLICY}
                cache.put(filename, entry, result)
                count += 1
        finally:
            write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
        return current_results(filename, cache, entries)
