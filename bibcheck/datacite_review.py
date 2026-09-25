"""Verify software/dataset citations (Zenodo etc.) against the DataCite registry.

Compared fields: title, creators (all of them, in order, including creators
that are not people, written as printed and braced), version (as part of the
house software title), year (``publicationYear``) and DOI. User rules
(verification/resolution-plan-2026-09-22/README.md): ``@misc`` software is
verified by a registry match; DOIs everywhere; initials; no suffixes.

House software title (see the cdl-bib-cite note): ``{Owner}/repo: {vX.Y}``.
It is accepted when it equals the registry title, or when it is exactly the
repository part of the registry title (``Owner/repo``, which must also be the
GitHub repository of the record's ``IsSupplementTo`` link) followed by the
registry ``version`` string. Nothing else about the title is relaxed.

A cited concept DOI (one whose record ``HasVersion`` children) is accepted:
DataCite serves the latest version's metadata under it. Raw registry JSON is
saved with the result, so ``valid_datacite_approval`` can recheck it offline.
"""
from copy import deepcopy
import json
import re
from urllib.parse import quote, urlencode

from preprint_review import checked_body, fetch_document, people
from verification import author_evidence, normalize_doi, normalize_title, normalized, outcome
from osf_review import classify, run_route

DATACITE_POLICY = '1'
SOURCE = 'datacite-registry'
API = 'https://api.datacite.org/dois/'
# DataCite-registered repositories whose records this route reads. Crossref
# DOIs are never looked up here.
PREFIXES = {'10.5281': 'zenodo', '10.6084': 'figshare', '10.5061': 'dryad', '10.7910': 'dataverse',
            '10.18112': 'openneuro', '10.17605': 'osf'}
# Registry resource types cited as @misc (course books on Zenodo are InteractiveResource).
TYPES = {'Software', 'Dataset', 'InteractiveResource'}


def parse_doi(value):
    text = normalized(value).strip()
    text = re.sub(r'^(?:https?://)?(?:dx\.)?doi\.org/', '', text)
    text = re.sub(r'^https?://zenodo\.org/(?:record|records)/(\d+)(?:\\?#.*)?$', r'10.5281/zenodo.\1', text)
    doi = normalize_doi(text)
    if doi.split('/')[0] not in PREFIXES:
        raise ValueError('Not a DataCite repository DOI')
    return doi


def identifier(fields):
    """(doi, identity fields) or (None, []) for a registry title search."""
    if fields.get('ENTRYTYPE') not in ('misc', 'article') or (
            fields.get('ENTRYTYPE') == 'article' and normalized(fields.get('journal', '')) not in set(PREFIXES.values())):
        raise ValueError('This route requires @misc software/data or a repository article citation')
    supplied = []
    for field in ('doi', 'volume', 'url'):
        if field in fields:
            try:
                supplied.append((field, parse_doi(fields[field])))
            except ValueError:
                if field == 'doi':
                    raise
    if len({s[1] for s in supplied}) > 1:
        raise ValueError('Conflicting repository DOIs')
    if supplied:
        return supplied[0][1], [s[0] for s in supplied]
    named = ' '.join(fields.get(f, '') for f in ('publisher', 'journal', 'howpublished')).lower()
    if not any(re.search(r'\b' + name + r'\b', named) for name in set(PREFIXES.values()) - {'osf'}):
        raise ValueError('No DataCite repository DOI or named repository')
    return None, []


def record_url(doi):
    return API + quote(doi, safe='/')


def search_url(title):
    return API + '?' + urlencode({'query': 'titles.title:"%s"' % title.replace('"', ''), 'page[size]': '25'})


def record(source, doi):
    data = json.loads(checked_body(source, record_url(doi)))['data']
    attrs = data['attributes']
    if data['type'] != 'dois' or normalize_doi(data['id']) != doi or normalize_doi(attrs['doi']) != doi:
        raise ValueError('DataCite returned another DOI')
    if attrs.get('state') != 'findable':
        raise ValueError('DataCite record is not findable')
    return attrs


def creators(attrs):
    """Ordered creators: people as {given, family}, others as printed ({name})."""
    out = []
    for c in attrs.get('creators') or []:
        name = re.sub(r'\s+', ' ', c.get('name') or '').strip()
        given, family = (c.get('givenName') or '').strip(), (c.get('familyName') or '').strip()
        if not name:
            raise ValueError('Unnamed DataCite creator')
        if given and family:
            out.append({'given': given, 'family': family, 'suffix': ''})
        elif c.get('nameType') == 'Organizational' or (' ' not in name and ',' not in name):
            out.append({'name': name})  # printed as a single unit, e.g. "Claude"
        elif ',' in name:
            family, _, given = name.partition(',')
            if not family.strip() or not given.strip():
                raise ValueError('Incomplete DataCite creator name: ' + name)
            out.append({'given': given.strip(), 'family': family.strip(), 'suffix': ''})
        else:
            out.append(people([name])[0])  # "Jeremy R. Manning": BibTeX First Last
    if not out:
        raise ValueError('DataCite record has no creators')
    return out


def byline(authors, citation):
    from correction_proposals import house_byline
    names = []
    for i, a in enumerate(authors):
        names.append('{' + a['name'] + '}' if 'name' in a else house_byline([a]))
    text = ' and '.join(names)
    if citation:
        from verification import split_authors
        cited = split_authors(citation)
        if len(cited) == len(names):  # keep cited surname text equal up to case/braces
            text = ' and '.join(n if 'name' in a else house_byline([a], c)
                                for n, a, c in zip(names, authors, cited))
    return text


def author_match(value, authors):
    return author_evidence(value, [dict(a, name=a['name']) if 'name' in a else a for a in authors])


def github_repo(attrs):
    repos = set()
    for r in attrs.get('relatedIdentifiers') or []:
        m = re.fullmatch(r'https?://github\.com/([^/\s]+/[^/\s]+?)(?:/tree/(.+))?/?', r.get('relatedIdentifier', ''))
        if r.get('relationType') == 'IsSupplementTo' and m:
            repos.add((m[1].lower(), m[2]))
    return repos


def house_title(attrs):
    titles = [t['title'] for t in attrs.get('titles') or [] if not t.get('titleType')]
    if len(titles) != 1:
        raise ValueError('Missing or ambiguous DataCite main title')
    forms = {normalize_title(titles[0])}
    repo, sep, _ = titles[0].partition(':')
    version = attrs.get('version')
    if sep and version and any(r == repo.strip().lower() for r, _ in github_repo(attrs)):
        forms.add(normalize_title(repo.strip() + ': ' + version))
        return titles[0], forms, repo.strip() + ': {' + version + '}'
    return titles[0], forms, None


def discover(hits, fields):
    """The one registry DOI with the cited title and first-author surname.

    A concept DOI and its own versions count as one work; the concept DOI
    (which serves the latest version) is returned. Anything else is ambiguous."""
    from bibtexparser.customization import splitname
    from verification import split_authors
    first = splitname(split_authors(fields.get('author', ''))[0], strict_mode=True)
    surname = normalized(' '.join(first['von'] + first['last']))
    found = {}
    for h in hits:
        a = h['attributes']
        try:
            if not any(normalize_title(t.get('title', '')) == normalize_title(fields.get('title', '')) for t in a.get('titles') or []):
                continue
        except ValueError:
            continue
        try:
            lead = creators(a)[0]
        except ValueError:
            continue
        if normalized(lead.get('family', lead.get('name', ''))) == surname:
            found[h['id'].lower()] = a
    concepts = [d for d, a in found.items()
                if set(found) - {d} <= {normalize_doi(r['relatedIdentifier']) for r in a.get('relatedIdentifiers') or []
                                         if r.get('relationType') == 'HasVersion' and r.get('relatedIdentifierType') == 'DOI'}]
    if len(found) == 1 or len(concepts) == 1:
        return next(iter(found)) if len(found) == 1 else concepts[0]
    raise ValueError('Registry title search is missing or ambiguous')


def assess_datacite(fields, raw):
    candidate = {'source': SOURCE, 'doi': raw.get('doi'), 'raw_record': raw, 'checked_fields': deepcopy(fields),
                 'issues': [], 'evidence': {}, 'proposal': None, 'category': 'held'}
    try:
        doi, identity_fields = identifier(fields)
        if doi is None:
            if normalize_title(raw.get('search_title', '')) != normalize_title(fields.get('title', '')):
                raise ValueError('No saved registry search for this title')
            doi = discover(json.loads(checked_body(raw['search'], search_url(raw['search_title'])))['data'], fields)
        if raw.get('doi') != doi:
            raise ValueError('Saved DataCite source belongs to another DOI')
        attrs = record(raw['record'], doi)
        kind = (attrs.get('types') or {}).get('resourceTypeGeneral')
        if kind not in TYPES:
            raise ValueError('DataCite resource type %r is not software or data' % kind)
        if any(r.get('relationType') in ('IsObsoletedBy', 'IsPreviousVersionOf') for r in attrs.get('relatedIdentifiers') or []):
            raise ValueError('DataCite record is superseded; adjudicate the version')
        authors = creators(attrs)
        evidence, issues, proposal = candidate['evidence'], candidate['issues'], {}

        def check(field, source, matches, fix=None):
            evidence[field] = {'local': fields.get(field), 'source': source, 'match': bool(matches)}
            if not matches:
                issues.append(field + ': missing evidence or mismatch')
                if fix is not None:
                    proposal[field] = fix

        title, forms, house = house_title(attrs)
        title_ok = normalize_title(fields.get('title', '')) in forms
        check('title', {'title': title, 'version': attrs.get('version')}, title_ok)
        ok, _ = author_match(fields.get('author', ''), authors)
        fix = None
        if not ok:
            try:
                fix = byline(authors, fields.get('author'))
            except ValueError as exc:
                issues.append('author: source creators have no certain house form: ' + str(exc))
        check('author', authors, ok, fix)
        check('year', attrs.get('publicationYear'), fields.get('year') == str(attrs.get('publicationYear')),
              str(attrs.get('publicationYear')))
        check('doi', doi, bool(fields.get('doi')) and normalized(fields['doi']) == doi, doi)
        if 'howpublished' in fields:
            m = re.fullmatch(r'\\url\{https?://github\.com/([^/\s}]+/[^/\s}]+?)/?\}', fields['howpublished'].strip())
            check('howpublished', sorted(r for r, _ in github_repo(attrs)),
                  bool(m) and any(m[1].lower() == r for r, _ in github_repo(attrs)))
        if fields.get('ENTRYTYPE') != 'misc':
            issues.append('ENTRYTYPE: registry software/data is cited as @misc')
            proposal['ENTRYTYPE'] = 'misc'
            if 'journal' in fields:
                proposal.setdefault('remove', []).append('journal')
        for field in identity_fields:
            if field != 'doi':
                issues.append(field + ': repository identifier belongs in doi')
                proposal.setdefault('remove', []).append(field)
        for field in ('publisher', 'journal'):
            if field in fields:
                if normalized(fields[field]) == normalized(attrs.get('publisher', '')):
                    evidence[field] = {'local': fields[field], 'source': attrs.get('publisher'), 'match': True}
                else:
                    issues.append(field + ': missing evidence or mismatch')
        for field in set(fields) - {'ENTRYTYPE', 'ID', 'title', 'author', 'year', 'doi', 'howpublished',
                                    'publisher', 'journal'} - set(identity_fields):
            issues.append(field + ': no DataCite verifier for this field')
        candidate.update(version=attrs.get('version'), resource_type=kind,
                         concept=any(r.get('relationType') == 'HasVersion' for r in attrs.get('relatedIdentifiers') or []))
        if house and not title_ok:
            candidate['house_title'] = house
        candidate['category'], candidate['proposal'] = classify(fields, issues, proposal, title_ok,
                                                                discovered=not identity_fields, authors=authors)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        candidate['issues'].append('DataCite unresolved: ' + str(exc))
    candidate['issues'] = list(dict.fromkeys(candidate['issues']))
    result = outcome('needs_review' if candidate['issues'] else 'metadata_verified', candidate['issues'], [candidate])
    if not candidate['issues']:
        result.update(accepted_source=SOURCE, accepted_doi=candidate['doi'], accepted_version=candidate['version'])
    return result


def valid_datacite_approval(result):
    if result.get('accepted_source') != SOURCE or result.get('external_evidence'):
        return False
    try:
        saved = [c for c in result['candidates'] if c.get('source') == SOURCE]
        if len(saved) != 1:
            return False
        c = saved[0]; checked = assess_datacite(c['checked_fields'], c['raw_record'])
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
    doi, _ = identifier(fields)
    fetch = lambda url, check: fetch_document(cache, client, url, 'datacite-source-v1:' + url, validate=check)
    raw = {}
    if doi is None:
        title = fields.get('title', '')
        raw.update(search_title=title, search=fetch(search_url(title), lambda s: json.loads(checked_body(s, search_url(title)))['data']))
        try:
            doi = discover(json.loads(raw['search']['body'])['data'], fields)
        except ValueError:
            raw['doi'] = None
            return raw
    raw['doi'] = doi
    raw['record'] = fetch(record_url(doi), lambda s: record(s, doi))
    return raw


def run_datacite_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    return run_route(filename, cache, client, report, limit, snapshot, keys, name='datacite_review',
                     policy=DATACITE_POLICY, source=SOURCE, applicable=applicable, collect=collect,
                     assess=assess_datacite, attempt_url=lambda raw: raw.get('record', raw.get('search', {})).get('url'))


from verification import register_approval_validator  # noqa: E402  (hook contract 2026-09-25)
register_approval_validator(valid_datacite_approval)
