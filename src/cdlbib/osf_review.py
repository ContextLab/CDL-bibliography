"""Verify PsyArXiv (OSF) preprint citations against the OSF API.

User rules (verification/resolution-plan-2026-09-22/README.md):
* a preprint cites its LATEST version; the year is that version's date;
* a published (peer-reviewed) version replaces the preprint (new key, user
  approval), so an OSF ``doi`` (article) relation is always flagged as a
  replacement candidate and never verifies silently;
* DOIs are recorded whenever available (the DOI moves out of ``volume``);
* authors are written as initials, all initials the source gives, no suffixes.

"Latest version" on OSF has two layers. Versioned preprints (``<id>_vN``,
2024-) each have their own record and DOI; older preprints have one record
whose primary file was revised in place (file versions). The latest version's
date is the later of the latest record's ``date_published`` and the newest
revision of its primary file (ZimaEtal23: record 2019, file revision 3 dated
2023-04-10, which the user confirmed as the citation year).

Raw OSF API documents are saved with the result, so every decision can be
reconstructed offline and re-checked by ``valid_osf_approval``.
"""
from copy import deepcopy
from datetime import datetime
import json
import re
from urllib.parse import urlencode

from .preprint_review import checked_body, context_issues, fetch_document, people
from .verification import (author_evidence, current_results, export_snapshot, load_entries,
                          normalize_title, normalized, outcome, run_lock,
                          validate_output_path, write_report)

OSF_POLICY = '1'
SOURCE = 'osf-repository'
API = 'https://api.osf.io/v2/'
PROVIDERS = {'psyarxiv': ('10.31234', 'psyarxiv')}  # provider id: (DOI prefix, cited journal)
ID = r'[a-z0-9]{5}'
PREPRINT_FIELDS = ('title,version,is_latest_version,date_published,date_withdrawn,reviews_state,'
                   'doi,is_published,public,date_created,provider,primary_file')
USER_FIELDS = 'full_name,given_name,middle_names,family_name,suffix'


def parse_id(value):
    """(base id, version or None) from an OSF/PsyArXiv DOI or URL."""
    text = normalized(value).strip()
    text = re.sub(r'^(?:https?://)?(?:dx\.)?doi\.org/', '', text)
    text = re.sub(r'^doi:\s*', '', text)
    match = (re.fullmatch(r'10\.31234/osf\.io/(' + ID + r')(?:_v([1-9]\d*))?', text)
             or re.fullmatch(r'(?:https?://)?(?:www\.)?(?:osf\.io/preprints/psyarxiv/|psyarxiv\.com/|osf\.io/)('
                             + ID + r')(?:_v([1-9]\d*))?/?', text))
    if not match:
        raise ValueError('Not a PsyArXiv/OSF preprint identifier')
    return match[1], int(match[2]) if match[2] else None


def identifier(fields):
    """(base, cited version, identity fields) or (None, None, []) for title discovery.

    Raises ValueError when the entry is not a PsyArXiv article or its
    identifiers conflict."""
    if fields.get('ENTRYTYPE') != 'article' or normalized(fields.get('journal', '')) != 'psyarxiv':
        raise ValueError('This route requires a PsyArXiv article citation')
    supplied = []
    for field in ('doi', 'volume', 'url', 'eprint', 'pages', 'number'):
        if field in fields:
            try:
                supplied.append((field, *parse_id(fields[field])))
            except ValueError:
                if field in ('doi', 'url', 'eprint'):
                    raise
    if len({s[1] for s in supplied}) > 1 or len({s[2] for s in supplied if s[2]}) > 1:
        raise ValueError('Conflicting PsyArXiv identifiers/versions')
    if not supplied:
        return None, None, []
    return supplied[0][1], next((s[2] for s in supplied if s[2]), None), [s[0] for s in supplied]


def versions_url(base):
    return API + 'preprints/' + base + '/versions/?' + urlencode(
        {'page[size]': '100', 'fields[preprints]': PREPRINT_FIELDS})


def contributors_url(preprint_id):
    return API + 'preprints/' + preprint_id + '/bibliographic_contributors/?' + urlencode(
        {'page[size]': '100', 'fields[users]': USER_FIELDS})


def file_versions_url(file_id):
    return API + 'files/' + file_id + '/versions/?' + urlencode({'page[size]': '100'})


def search_url(title, provider='psyarxiv'):
    return API + 'preprints/?' + urlencode({'filter[provider]': provider, 'filter[title]': title,
                                            'page[size]': '100', 'fields[preprints]': PREPRINT_FIELDS})


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def page(source, url):
    data = json.loads(checked_body(source, url))
    if not isinstance(data.get('data'), list) or data.get('links', {}).get('next'):
        raise ValueError('Missing or paginated OSF listing')
    total = data.get('links', {}).get('meta', {}).get('total')
    if total != len(data['data']):
        raise ValueError('Incomplete OSF listing')
    return data['data']


def version_rows(source, base):
    rows = page(source, versions_url(base))
    parsed = []
    for row in rows:
        a = row.get('attributes', {})
        match = re.fullmatch('(' + ID + r')_v([1-9]\d*)', row.get('id', ''))
        if row.get('type') != 'preprints' or not match or match[1] != base or int(match[2]) != a.get('version'):
            raise ValueError('OSF version listing names another preprint')
        provider = row.get('relationships', {}).get('provider', {}).get('data', {}).get('id')
        if provider not in PROVIDERS:
            raise ValueError('Unsupported OSF preprint provider')
        parsed.append(row)
    parsed.sort(key=lambda r: r['attributes']['version'])
    if not parsed or [r['attributes']['version'] for r in parsed] != list(range(1, len(parsed) + 1)):
        raise ValueError('Noncontiguous OSF preprint versions')
    latest = [r for r in parsed if r['attributes'].get('is_latest_version')]
    if len(latest) != 1 or latest[0] is not parsed[-1]:
        raise ValueError('OSF latest-version flag conflicts with the version history')
    return parsed


def contributors(source, preprint_id):
    rows = page(source, contributors_url(preprint_id))
    if [r.get('attributes', {}).get('index') for r in rows] != list(range(len(rows))) or not rows:
        raise ValueError('Unordered or empty OSF byline')
    authors = []
    for row in rows:
        a = row['attributes']
        if row.get('type') != 'contributors' or not row.get('id', '').startswith(preprint_id + '-') or a.get('bibliographic') is not True:
            raise ValueError('OSF byline contains another preprint or a non-bibliographic contributor')
        user = row.get('embeds', {}).get('users', {}).get('data', {}).get('attributes', {})
        if a.get('unregistered_contributor'):
            person = people([re.sub(r'\s+', ' ', a['unregistered_contributor'])])[0]
            if not person['given'] or not person['family']:
                raise ValueError('Unparseable OSF unregistered contributor name')
        else:
            given = ' '.join(x for x in (user.get('given_name', ''), user.get('middle_names', '')) if x and x.strip())
            if not given.strip() or not (user.get('family_name') or '').strip():
                raise ValueError('Incomplete OSF contributor name')
            person = {'given': given.strip(), 'family': user['family_name'].strip(), 'suffix': user.get('suffix') or ''}
        authors.append(person)
    return authors


def file_dates(source, file_id):
    rows = page(source, file_versions_url(file_id))
    if not rows:
        raise ValueError('OSF primary file has no versions')
    return sorted(stamp(r['attributes']['date_created']) for r in rows)


def version_doi(base, row, rows):
    """Versioned records carry ``_vN`` DOIs; legacy single records the bare DOI."""
    prefix = PROVIDERS[row['relationships']['provider']['data']['id']][0]
    link = normalized(row.get('links', {}).get('preprint_doi') or '')
    bare, pinned = prefix + '/osf.io/' + base, prefix + '/osf.io/' + base + '_v' + str(row['attributes']['version'])
    for doi in (pinned, bare):
        if link.endswith('doi.org/' + doi):
            return doi
    raise ValueError('OSF record DOI link missing or conflicting')


def house_initials_byline(authors, citation):
    from .correction_proposals import house_byline
    return house_byline(authors, citation)


def classify(fields, issues, proposal, title_ok, published=None, discovered=False, authors=None, source=None):
    """(category, proposal) shared by the 2026-09-25 routes.

    verified: no issue. replacement: a published version exists (user
    approval). proposal: the title matches (identity) and every issue is
    repaired by a source value in ``proposal``, with no surname change (a surname
    mismatch is the user's to resolve, user rule 2026-09-30). held: anything else
    (identity, an uncertain source form, or a surname mismatch)."""
    if not issues:
        return 'verified', None
    if published:
        return 'replacement', {'replace_with_doi': published, 'preprint_fields': proposal}
    fixable = set(proposal) | set(proposal.get('remove', [])) | ({'version'} if 'doi' in proposal else set())
    if not title_ok or not proposal or {i.split(':')[0] for i in issues} - fixable:
        return 'held', None
    if 'author' in proposal:
        from .correction_proposals import surname_change_hold, surname_changes
        if discovered and surname_changes(fields.get('author'), proposal['author']):
            issues.append('author: surname change on a title-discovered record')
            return 'held', None
        from .correction_proposals import byline_loses_detail
        if authors is not None and byline_loses_detail(fields.get('author', ''), authors):
            issues.append('author: the source byline has less detail than the citation (initials/people/accents)')
            return 'held', None
        hold = surname_change_hold(fields.get('ID', ''), fields.get('author'), proposal['author'], source=source)
        if hold:
            issues.append(hold)
            return 'held', None
    return 'proposal', proposal


def assess_osf(fields, raw):
    """Classify one citation: verified, proposal (correctable), replacement or held."""
    candidate = {'source': SOURCE, 'doi': None, 'raw_record': raw, 'checked_fields': deepcopy(fields),
                 'issues': [], 'evidence': {}, 'proposal': None, 'category': 'held'}
    try:
        base, cited_version, identity_fields = identifier(fields)
        if base is None:
            if raw.get('discovered_by') != 'title' or not raw.get('base'):
                raise ValueError('No PsyArXiv identifier and no title discovery envelope')
            hits = [r for r in page(raw['search'], search_url(raw['search_title']))
                    if normalize_title(r['attributes'].get('title', '')) == normalize_title(fields.get('title', ''))]
            if normalize_title(raw['search_title']) != normalize_title(fields.get('title', '')):
                raise ValueError('Saved title search is for another title')
            if len({h['id'].split('_')[0] for h in hits}) != 1:
                raise ValueError('Title discovery is missing or ambiguous')
            base = hits[0]['id'].split('_')[0]
        if raw.get('base') != base:
            raise ValueError('Saved OSF source belongs to another preprint')
        rows = version_rows(raw['versions'], base)
        latest = rows[-1]; attrs = latest['attributes']
        if any(r['attributes'].get('date_withdrawn') or r['attributes'].get('reviews_state') == 'withdrawn' for r in rows):
            raise ValueError('OSF preprint is withdrawn')
        if attrs.get('reviews_state') not in ('accepted', None) or attrs.get('is_published') is not True or attrs.get('public') is False:
            raise ValueError('Latest OSF version is not publicly published')
        if cited_version and cited_version > len(rows):
            raise ValueError('Cited version is absent from the OSF history')
        authors = contributors(raw['contributors'], latest['id'])
        file_id = latest['relationships']['primary_file']['data']['id']
        if raw.get('file_id') != file_id:
            raise ValueError('Saved OSF file history belongs to another file')
        dates = file_dates(raw['file_versions'], file_id)
        released = max(stamp(attrs['date_published']), dates[-1])
        doi = version_doi(base, latest, rows)
        candidate.update(doi=doi, version=attrs['version'], latest_date=released.isoformat(),
                         file_revisions=len(dates), url='https://osf.io/preprints/psyarxiv/' + latest['id'])
        evidence, issues = candidate['evidence'], candidate['issues']
        proposal = {}

        def check(field, source, matches, fix=None):
            evidence[field] = {'local': fields.get(field), 'source': source, 'match': bool(matches)}
            if not matches:
                issues.append(field + ': missing evidence or mismatch')
                if fix is not None:
                    proposal[field] = fix

        title_ok = normalize_title(fields.get('title', '')) == normalize_title(attrs['title'])
        check('title', attrs['title'], title_ok)
        by_ok, why = author_evidence(fields.get('author', ''), authors)
        byline = None
        if not by_ok:
            try:
                byline = house_initials_byline(authors, fields.get('author'))
            except ValueError as exc:
                issues.append('author: source byline has no certain house form: ' + str(exc))
        check('author', authors, by_ok, byline)
        check('year', {'year': released.year, 'role': 'latest version date', 'version': attrs['version']},
              fields.get('year') == str(released.year), str(released.year))
        check('journal', 'PsyArXiv', True)
        cited_doi = fields.get('doi')
        check('doi', doi, bool(cited_doi) and normalized(cited_doi) == doi, doi)
        if cited_version and cited_version != attrs['version']:
            issues.append('version: citation pins v%d; latest is v%d' % (cited_version, attrs['version']))
        for field in identity_fields:
            if field != 'doi':
                issues.append(field + ': repository identifier belongs in doi')
                proposal.setdefault('remove', []).append(field)
        for field in set(fields) - {'ENTRYTYPE', 'ID', 'journal', 'title', 'author', 'year', 'doi'} - set(identity_fields):
            issues.append(field + ': no OSF verifier for this field')
        published = attrs.get('doi')
        if published:
            candidate['published_doi'] = normalized(published)
            issues.append('published version exists (DOI %s): replacement candidate for user approval' % normalized(published))
        candidate['category'], candidate['proposal'] = classify(fields, issues, proposal, title_ok,
                                                                published, discovered=not identity_fields,
                                                                authors=authors, source=candidate.get('url') or SOURCE)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        candidate['issues'].append('OSF unresolved: ' + str(exc))
    candidate['issues'] = list(dict.fromkeys(candidate['issues']))
    result = outcome('needs_review' if candidate['issues'] else 'metadata_verified', candidate['issues'], [candidate])
    if not candidate['issues']:
        result.update(accepted_source=SOURCE, accepted_doi=candidate['doi'], accepted_version=candidate['version'])
    return result


def valid_osf_approval(result):
    if result.get('accepted_source') != SOURCE or result.get('external_evidence'):
        return False
    try:
        saved = [c for c in result['candidates'] if c.get('source') == SOURCE]
        if len(saved) != 1 or context_issues(saved[0]['checked_fields'], result['candidates'], result['accepted_doi']):
            return False
        c = saved[0]; checked = assess_osf(c['checked_fields'], c['raw_record'])
        return (checked['status'] == 'metadata_verified' and checked['accepted_doi'] == result['accepted_doi']
                and checked['accepted_version'] == result['accepted_version'] and checked['candidates'][0] == c)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def applicable(fields):
    try:
        identifier(fields)
        return True
    except ValueError:
        return False


def collect(cache, client, fields):
    """Fetch (or reuse) every OSF document the assessment needs."""
    base, _, _ = identifier(fields)
    raw = {}
    fetch = lambda url, check: fetch_document(cache, client, url, 'osf-source-v1:' + url, validate=check)
    if base is None:
        title = fields.get('title', '')
        raw.update(discovered_by='title', search_title=title)
        raw['search'] = fetch(search_url(title), lambda s: page(s, search_url(title)))
        hits = {r['id'].split('_')[0] for r in page(raw['search'], search_url(title))
                if normalize_title(r['attributes'].get('title', '')) == normalize_title(title)}
        if len(hits) != 1:
            raw['base'] = None
            return raw
        base = hits.pop()
    raw['base'] = base
    raw['versions'] = fetch(versions_url(base), lambda s: version_rows(s, base))
    latest = version_rows(raw['versions'], base)[-1]
    raw['contributors'] = fetch(contributors_url(latest['id']), lambda s: page(s, contributors_url(latest['id'])))
    raw['file_id'] = ((latest.get('relationships', {}).get('primary_file') or {}).get('data') or {}).get('id')
    if raw['file_id']:  # a withdrawn preprint has no file; the assessment rejects it
        raw['file_versions'] = fetch(file_versions_url(raw['file_id']), lambda s: page(s, file_versions_url(raw['file_id'])))
    return raw


PRESERVED = ('auto_review', 'discovery_review', 'catalogue_review', 'preprint_review', 'arxiv_review',
             'research_attempt', 'datacite_review', 'acl_review', 'sfn_review')


def merge(previous, result, source, attempt_url):
    result['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != source] + result['candidates']
    result['attempts'] = previous.get('attempts', []) + [{'source': source, 'url': attempt_url}]
    if result['status'] == 'metadata_verified':
        issues = context_issues(result['candidates'][-1]['checked_fields'], result['candidates'], result.get('accepted_doi'))
        if issues:
            result.update(status='needs_review', issues=issues)
            for name in ('accepted_doi', 'accepted_source', 'accepted_version'):
                result.pop(name, None)
    for name in PRESERVED:
        if name in previous:
            result[name] = deepcopy(previous[name])
    return result


def run_route(filename, cache, client, report, limit, snapshot, keys, *, name, policy, source,
              applicable, collect, assess, attempt_url):
    """Shared driver for the 2026-09-25 routes (same contract as run_arxiv_review)."""
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    with run_lock(cache):
        entries = load_entries(filename); count = 0
        if keys is not None and set(keys) - entries.keys():
            raise ValueError(name + ' keys must name existing citations')
        try:
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
                previous = cache.get(filename, entry)
                if (not previous or previous['status'] != 'needs_review' or previous.get('external_evidence')
                        or previous.get(name, {}).get('policy') == policy or not applicable(entry['fields'])):
                    continue
                if limit is not None and count >= limit:
                    break
                raw = collect(cache, client, entry['fields'])
                result = merge(previous, assess(entry['fields'], raw), source, attempt_url(raw))
                result[name] = {'policy': policy, 'category': result['candidates'][-1].get('category')}
                cache.put(filename, entry, result); count += 1
        finally:
            write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
        return current_results(filename, cache, entries)


def run_osf_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    return run_route(filename, cache, client, report, limit, snapshot, keys, name='osf_review',
                     policy=OSF_POLICY, source=SOURCE, applicable=applicable, collect=collect,
                     assess=assess_osf, attempt_url=lambda raw: raw.get('versions', raw.get('search', {})).get('url'))


try:
    from .verification import register_approval_validator
except ImportError as exc:  # pragma: no cover - documented contract, see tests
    raise ImportError('verification.register_approval_validator is required (hook contract 2026-09-25)') from exc
register_approval_validator(valid_osf_approval)
