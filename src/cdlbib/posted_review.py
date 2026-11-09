"""Verify preprints on servers that register their DOIs with Crossref and have no route
of their own: Research Square, SSRN, ChemRxiv, Preprints.org, EcoEvoRxiv, TechRxiv and
Authorea (``SERVERS``).

bioRxiv and medRxiv (``preprint_review``), the OSF servers (``osf_review``) and arXiv
(``arxiv_review``) are checked against their own repositories and are never judged here.

The source is the Crossref record of the cited DOI, which must be a posted-content record
of subtype preprint. Each of these servers gives every version its own DOI (Research
Square ``.../v2``, ChemRxiv ``/v2``, Preprints.org ``.v2``) or has one version, so the DOI
names the version cited. Compared: the server (the cited journal, by the DOI's prefix),
the DOI (and ``volume``, which in the house form repeats it), the title, the complete
ordered byline and the year of posting. A record that names a published version
(``is-preprint-of``) is a replacement candidate and never verifies (house rule: cite the
published version); one that names other versions (``has-version``, ``is-version-of``)
needs a person to choose the latest; a correction or retraction notice blocks approval.

The Crossref response is saved with the result, so ``valid_posted_approval`` rechecks it
offline.
"""
from copy import deepcopy
import json
import re
from urllib.parse import quote

from .verification import (author_evidence, normalize_doi, normalize_title, normalized, outcome)

POSTED_POLICY = '1'
SOURCE = 'crossref-preprint'
# DOI prefix -> the server's name as cited (the journal of the house entry).
SERVERS = {'10.21203': 'Research Square', '10.2139': 'SSRN', '10.26434': 'ChemRxiv',
           '10.20944': 'Preprints', '10.32942': 'EcoEvoRxiv', '10.36227': 'TechRxiv',
           '10.22541': 'Authorea'}
# Relations that say nothing about which work or version this is.
BENIGN = {'has-review', 'has-comment', 'references', 'is-referenced-by', 'is-supplement-to',
          'is-supplemented-by', 'has-related-material', 'is-related-material'}
VERSIONS = {'has-version', 'is-version-of'}


def server_name(doi):
    """The server whose DOI prefix ``doi`` has, or None."""
    try:
        prefix = normalize_doi(doi).split('/', 1)[0]
    except (ValueError, TypeError, AttributeError):
        return None
    return SERVERS.get(prefix)


def _doi(value):
    text = str(value or '').strip()
    text = re.sub(r'^(?:https?://)?(?:dx\.)?doi\.org/', '', text, flags=re.I)
    text = re.sub(r'^doi:\s*', '', text, flags=re.I)
    return normalize_doi(text)


def identifier(fields):
    """(DOI, identity fields) of an explicitly cited preprint of a server in ``SERVERS``.

    Raises ValueError when the entry is not such a citation: it must be an article whose
    journal is the server its DOI's prefix belongs to."""
    if fields.get('ENTRYTYPE') != 'article' or not fields.get('doi'):
        raise ValueError('This route requires an article citation with the preprint DOI')
    doi = _doi(fields['doi'])
    name = server_name(doi)
    try:
        cited = normalized(fields.get('journal', ''))
    except ValueError:
        cited = None
    if name is None or cited != normalized(name):
        raise ValueError('The cited journal is not the preprint server of this DOI')
    found = ['doi']
    if 'volume' in fields:
        found.append('volume')
    return doi, found


def applicable(fields):
    try:
        identifier(fields)
        return True
    except ValueError:
        return False


def record_url(doi):
    return 'https://api.crossref.org/works/' + quote(doi, safe='')


def registry_record(raw, doi):
    """The Crossref record saved in ``raw`` for ``doi``."""
    response = raw['crossref']
    if response.get('http_status', 200) != 200 or response.get('url') != record_url(doi):
        raise ValueError('Missing or failed Crossref response for this DOI')
    body = response['body']
    record = (json.loads(body) if isinstance(body, str) else body)['message']
    if normalize_doi(record.get('DOI', '')) != doi:
        raise ValueError('Crossref record belongs to another DOI')
    return record


def posted_year(record):
    """The year of posting: the record's ``published`` date (the posting date of a
    posted-content record), corroborated by ``issued`` when given."""
    years = set()
    for name in ('published', 'issued', 'posted'):
        parts = (record.get(name) or {}).get('date-parts') or []
        if parts and parts[0] and re.fullmatch(r'[1-9]\d{3}', str(parts[0][0])):
            years.add(str(parts[0][0]))
    if len(years) != 1:
        raise ValueError('Missing or conflicting posting dates')
    return years.pop()


def published_dois(record):
    relation = record.get('relation') or {}
    links = relation.get('is-preprint-of') if isinstance(relation, dict) else None
    return sorted({normalize_doi(x['id']) for x in links or [] if isinstance(x, dict)
                   and x.get('id-type') == 'doi' and x.get('id')})


def assess_posted(fields, raw):
    candidate = {'source': SOURCE, 'doi': None, 'raw_record': raw, 'checked_fields': deepcopy(fields),
                 'issues': [], 'evidence': {}}
    try:
        doi, identity_fields = identifier(fields)
        candidate['doi'] = doi
        record = registry_record(raw, doi)
        if record.get('type') != 'posted-content' or record.get('subtype') != 'preprint':
            raise ValueError('The DOI is not registered as a preprint')
        if record.get('update-to') or record.get('updated-by'):
            raise ValueError('DOI registry notice requires adjudication')
        relation = record.get('relation') or {}
        if not isinstance(relation, dict):
            raise ValueError('Unreadable registry relations')
        unknown = set(relation) - BENIGN - VERSIONS - {'is-preprint-of'}
        if unknown:
            raise ValueError('DOI registry relationship requires adjudication: ' + ', '.join(sorted(unknown)))
        titles = record.get('title') or []
        if len(titles) != 1 or record.get('subtitle'):
            raise ValueError('Registry preprint title is missing or ambiguous')
        name = server_name(doi)
        evidence, issues = candidate['evidence'], candidate['issues']

        def check(field, source, match):
            evidence[field] = {'local': fields.get(field), 'source': source, 'match': bool(match)}
            if not match:
                issues.append(field + ': missing evidence or mismatch')

        check('ENTRYTYPE', 'repository preprint', True)
        check('journal', name, True)
        check('doi', record['DOI'], True)
        if 'volume' in identity_fields:
            try:
                same = _doi(fields['volume']) == doi
            except ValueError:
                same = False
            check('volume', {'doi': doi, 'role': 'repository identifier'}, same)
        check('title', titles[0], normalize_title(fields.get('title', '')) == normalize_title(titles[0]))
        people = record.get('author') or []
        try:
            matched, detail = author_evidence(fields.get('author', ''), people)
        except (ValueError, KeyError) as exc:
            matched, detail = False, str(exc)
        check('author', people, matched)
        if not matched:
            issues[-1] = 'author: ' + detail
        year = posted_year(record)
        check('year', {'year': year, 'role': 'posting date'}, fields.get('year') == year)
        for field in set(fields) - {'ID', 'ENTRYTYPE', 'journal', 'title', 'author', 'year'} - set(identity_fields):
            issues.append(field + ': no preprint verifier for this field')
        published = published_dois(record)
        if published:
            candidate['published_doi'] = published
            issues.append('published version exists (DOI %s): replacement candidate for user approval'
                          % ', '.join(published))
        if set(relation) & VERSIONS:
            issues.append('version: the registry names other versions of this preprint; cite the latest')
        candidate.update(url='https://doi.org/' + doi, retrieved_at=raw['crossref'].get('retrieved_at'))
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        candidate['issues'].append('Preprint unresolved: ' + str(exc))
    candidate['issues'] = list(dict.fromkeys(candidate['issues']))
    result = outcome('needs_review' if candidate['issues'] else 'metadata_verified', candidate['issues'], [candidate])
    if not candidate['issues']:
        result.update(accepted_source=SOURCE, accepted_doi=candidate['doi'])
    return result


def valid_posted_approval(result):
    from .preprint_review import context_issues
    if result.get('accepted_source') != SOURCE or result.get('external_evidence'):
        return False
    try:
        saved = [c for c in result['candidates'] if c.get('source') == SOURCE]
        if len(saved) != 1 or context_issues(saved[0]['checked_fields'], result['candidates'], result['accepted_doi']):
            return False
        c = saved[0]
        checked = assess_posted(c['checked_fields'], c['raw_record'])
        return (checked['status'] == 'metadata_verified' and checked['accepted_doi'] == result['accepted_doi']
                and checked['candidates'][0] == c)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def collect(cache, client, fields):
    """The Crossref response for the cited DOI, as the client caches it."""
    doi, _ = identifier(fields)
    response = client.crossref_doi(doi)
    saved = {k: response.get(k) for k in ('retrieved_at', 'http_status', 'body')}
    # The request URL without its query: the polite-pool contact address is not kept.
    saved['url'] = str(response.get('url') or '').split('?', 1)[0]
    return {'crossref': saved}


def run_posted_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    from .osf_review import run_route
    return run_route(filename, cache, client, report, limit, snapshot, keys, name='posted_review',
                     policy=POSTED_POLICY, source=SOURCE, applicable=applicable, collect=collect,
                     assess=assess_posted, attempt_url=lambda raw: raw.get('crossref', {}).get('url'))


from .verification import register_approval_validator  # noqa: E402  (hook contract 2026-09-25)
register_approval_validator(valid_posted_approval)
