"""Strict edition-level checks for printed books with complete author bylines."""
from copy import deepcopy
import hashlib
import re
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from bibtexparser.customization import splitname
from catalogue_discovery import M, MAX_BYTES, fetch_search, parse_search, search_query
from verification import (author_evidence, compare_record, current_results,
                          export_snapshot, load_entries, normalized, outcome, run_lock,
                          validate_output_path, write_report)

CATALOGUE_POLICY = "6"

# LOC 008/15-17 identifies the first named publication jurisdiction. These
# exact state forms are confined to publication addresses, never paper text.
# https://www.loc.gov/marc/bibliographic/bd008a.html
# https://www.loc.gov/marc/countries/countries_regional.html
STATE_FORMS = {'mau': {'ma', 'mass', 'massachusetts'},
               'nyu': {'ny', 'n.y', 'new york'},
               'cau': {'ca', 'calif', 'california'}}


def normalized_edition(value):
    """Compare explicit edition numbers, retaining qualified/revised labels."""
    text = normalized(value).rstrip('.')
    text = re.sub(r'\s+(?:ed|edition)$', '', text)
    words = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5,
             'sixth': 6, 'seventh': 7, 'eighth': 8, 'ninth': 9, 'tenth': 10}
    if text in words:
        return str(words[text])
    match = re.fullmatch(r'([1-9]\d?)(st|nd|rd|th)?', text)
    if match:
        number = int(match[1])
        suffix = 'th' if 11 <= number % 100 <= 13 else {1:'st',2:'nd',3:'rd'}.get(number % 10, 'th')
        if match[2] in (None, suffix):
            return str(number)
    return normalized(value).rstrip('.')


def coded_address_support(local, record, xml):
    """Use a coded jurisdiction only for the first transcribed place."""
    root = ET.fromstring(xml)
    code = root.findtext(M + "controlfield[@tag='008']", '')[15:18]
    forms = STATE_FORMS.get(code)
    value = normalized(local).rstrip('.')
    if not forms or value.count(',') != 1 or not record.get('address'):
        return None
    city, state = (s.strip().rstrip('.') for s in value.rsplit(',', 1))
    if state not in forms:
        return None
    place = normalized(record['address'][0]).rstrip('.')
    if ',' in place:
        source_city, source_state = (s.strip().rstrip('.') for s in place.rsplit(',', 1))
        if source_state not in forms:
            return None  # A conflicting transcribed state cannot be overridden.
    else:
        source_city = place
    return code if city and city == source_city else None


def marc_book(xml):
    if (not isinstance(xml, str) or len(xml.encode()) > MAX_BYTES
            or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I)):
        raise ValueError("Unsupported catalogue XML")
    root = ET.fromstring(xml)
    if root.tag != M + "record":
        raise ValueError("Expected one MARC edition record")
    def fields(tag):
        return root.findall(M + f"datafield[@tag='{tag}']")
    def subs(node, code):
        return [(n.text or "").strip() for n in node.findall(M + f"subfield[@code='{code}']")]
    def one(tag, code, required=True):
        nodes = fields(tag)
        if not nodes and not required:
            return ""
        values = subs(nodes[0], code) if len(nodes) == 1 else []
        if len(values) != 1 or not values[0]:
            raise ValueError("Missing or ambiguous MARC field " + tag + code)
        return values[0]
    def control(tag):
        nodes = root.findall(M + f"controlfield[@tag='{tag}']")
        if len(nodes) != 1 or not nodes[0].text:
            raise ValueError("Missing or ambiguous MARC control " + tag)
        return nodes[0].text
    leader = root.findtext(M + "leader", "")
    date = control("008")
    if (len(leader) < 8 or leader[6:8] != "am" or len(date) != 40
            or date[6] != "s" or not re.fullmatch(r"[1-9]\d{3}", date[7:11])
            or date[11:15].strip() or date[23] != " "):
        raise ValueError("Not an unambiguous single-year printed monograph")
    if any(fields(tag) for tag in ("110", "111", "130", "710", "711", "765", "767", "775", "776", "787")):
        raise ValueError("Corporate creators or related editions require review")
    if fields("264") or len(fields("260")) != 1:
        raise ValueError("This route requires one legacy publication statement")
    titles = fields("245")
    if len(titles) != 1 or any(subs(titles[0], code) for code in ("h", "n", "p", "k", "s")):
        raise ValueError("Multipart or non-print title requires review")
    year = date[7:11]
    publication_date = one("260", "c")
    if publication_date not in {year + ".", "c" + year + ".", year, "c" + year}:
        raise ValueError("Transcribed publication year is ambiguous")
    publisher = one("260", "b").rstrip(" ,.;:")
    places = subs(fields("260")[0], "a")
    if not places or any(not v or re.search(r"[\[\]]", v) for v in places):
        raise ValueError("Missing or uncertain place of publication")
    if re.search(r"distribut|\[|\]|;", publisher, re.I):
        raise ValueError("Publisher role is uncertain")
    title = one("245", "a").rstrip(" /:")
    subtitle = subs(fields("245")[0], "b")
    if len(subtitle) > 1:
        raise ValueError("Ambiguous subtitle")
    if subtitle:
        title += ": " + subtitle[0].rstrip(" /")
    if re.search(r"[\[\]]", title):
        raise ValueError("Supplied or uncertain title requires review")
    one("100", "a")  # A single personal main entry is required for this route.
    people = []
    for creator in fields('100') + fields('700'):
        names = subs(creator, 'a')
        # 700 can name editors, owners, or related works. It is not an author
        # list on its own: only simple personal headings confirmed by 245c
        # qualify. Reject analytical entries and all work/role qualifiers.
        allowed = {'a', 'd', 'e', 'q', 'u', '0', '1', '2', '4', '6', '8'}
        if (creator.get('ind1') != '1'
                or (creator.get('tag') == '700' and creator.get('ind2') != ' ')
                or len(names) != 1 or not names[0]
                or any(n.get('code') not in allowed for n in creator)
                or any(v.rstrip(' .').lower() not in {'author', 'joint author'} for v in subs(creator, 'e'))
                or any(v != 'aut' for v in subs(creator, '4'))):
            raise ValueError("Author heading has unsupported identity or role qualifiers")
        author = splitname(names[0].rstrip(" ,."), strict_mode=True)
        people.append({"given": " ".join(author['first']), "family": " ".join(author['von'] + author['last']),
                       "suffix": " ".join(author['jr'])})
    statement = one("245", "c").rstrip(" .")
    statement = re.sub(r"^(?:by|\[by\])\s+", "", statement, flags=re.I)
    names = [statement]
    if len(people) > 1:
        # This deliberately small grammar accepts complete natural-order
        # bylines joined by commas or 'and'. Suffixes/inverted names and
        # qualified responsibilities remain unresolved rather than guessed.
        names = re.split(r",\s*(?:and\s+)?|\s+and\s+", statement)
        if len(names) != len(people) or any(not n.strip() for n in names):
            raise ValueError("Transcribed responsibility is not a complete simple byline")
    # MARC's inverted personal heading explicitly supplies the entire family
    # name. Protect that same verbatim suffix in the natural-order byline so
    # BibTeX's lowercase-particle heuristic cannot split 'De Valois'. This
    # supplies grouping only; every given name and surname still must match.
    for index, (name, person) in enumerate(zip(names, people)):
        family = person['family']
        if ' ' in family and not person['suffix']:
            pattern = r'(?<=\s)' + re.escape(family) + r'$'
            names[index] = re.sub(pattern, lambda _: '{' + family + '}', name.strip(), flags=re.I)
    statement = ' and '.join(names)
    if not author_evidence(statement, people)[0]:
        raise ValueError("Transcribed responsibility differs from the complete named author list")
    if any(re.search(r"reprint|translat|revis|facsimil", " ".join(n.itertext()), re.I) for n in fields("500")):
        raise ValueError("Edition note requires review")
    isbns = []
    for node in fields("020"):
        for value in subs(node, "a"):
            # Older ISBD punctuation separates an ISBN/qualifier from the
            # acquisition terms in 020$c with a terminal spaced colon.
            match = re.fullmatch(r"([\dXx-]+)(?:\s+\([^)]*\))?(?:\s+:)?", value)
            if not match:
                raise ValueError("Unsupported ISBN statement")
            isbns.append(match[1])
    return {"type": "book", "title": [title], "author": people, "published": {"date-parts": [[int(year)]]},
            "publisher": publisher, "ISBN": isbns, "catalogue_id": control("001"),
            "address": [v.rstrip(" ,;:") for v in places], "edition": one("250", "a", False).rstrip(" .")}


def assess_catalogue(fields, response):
    candidates = []
    try:
        if fields.get("ENTRYTYPE") != "book" or fields.get("doi"):
            raise ValueError("Catalogue route requires a book without a supplied DOI")
        url = urlparse(response["url"])
        if (url.scheme != 'https' or url.hostname != 'lx2.loc.gov' or url.path != '/sru/lcdb'
                or url.username or url.password or url.port not in (None, 443)
                or hashlib.sha256(response['raw_xml'].encode()).hexdigest() != response['document_sha256']):
            raise ValueError("Invalid catalogue source provenance")
        # Discovery may omit combining accents that LC's search index fails
        # to match. The original fields and MARC transcription remain intact
        # for every identity/edition comparison below.
        queries = {search_query(fields, fold_diacritics=fold) for fold in (False, True)}
        if re.fullmatch(r'[1-9]\d{3}', str(fields.get('year', ''))):
            queries.update(search_query(fields, include_year=True, fold_diacritics=fold)
                           for fold in (False, True))
        parsed = None
        for query in sorted(queries):
            try:
                parsed = parse_search(response['raw_xml'], query)
                break
            except ValueError as exc:
                if str(exc) != 'Catalogue response does not echo the requested query':
                    raise
        if parsed is None:
            raise ValueError('Catalogue response query does not derive from this citation')
        if parsed['truncated']:
            raise ValueError("Catalogue search is truncated; edition uniqueness is unresolved")
        incomplete = False
        for xml in parsed['records']:
            evidence, record, issues = {}, {}, []
            try:
                record = marc_book(xml)
                ordinary = {k: v for k, v in fields.items() if k not in {'address', 'edition'}}
                evidence, issues = compare_record(ordinary, record)
                for name in ('address', 'edition'):
                    local, source = fields.get(name, ''), record[name]
                    if local or (name == 'edition' and source):
                        values = source if isinstance(source, list) else [source]
                        normalize = normalized_edition if name == 'edition' else lambda v: normalized(v).rstrip('.')
                        match = bool(local and any(normalize(local) == normalize(s) for s in values))
                        code = coded_address_support(local, record, xml) if name == 'address' and not match else None
                        match = match or bool(code)
                        evidence[name] = {'local': local, 'source': values, 'match': match}
                        if code:
                            evidence[name]['source_place_code'] = code
                        if not match:
                            issues.append(f'{name}: missing evidence or mismatch')
            except (ValueError, KeyError, TypeError) as exc:
                issues = ['Catalogue edition unresolved: ' + str(exc)]
                incomplete = True
            candidates.append({'source': 'loc-catalogue', 'record_id': record.get('catalogue_id'),
                               'record': record, 'evidence': evidence, 'issues': issues,
                               'url': response['url'], 'retrieved_at': response['retrieved_at'],
                               'raw_marcxml': xml, 'raw_search_xml': response['raw_xml'],
                               'document_sha256': response['document_sha256']})
        good = [c for c in candidates if not c['issues']]
        if len(good) == 1 and not incomplete:
            return dict(outcome('metadata_verified', [], candidates), accepted_source='loc-catalogue',
                        accepted_record_id=good[0]['record_id'])
        return outcome('needs_review', ['No unique, fully matching catalogue edition'], candidates)
    except (ValueError, KeyError, TypeError, AttributeError, ET.ParseError) as exc:
        return outcome('needs_review', ['Catalogue edition unresolved: ' + str(exc)], candidates)


def reassess_saved_catalogue(fields, previous):
    """Rebuild decisions from the complete search, never saved match booleans."""
    saved = [c for c in previous.get('candidates', []) if c.get('source') == 'loc-catalogue']
    if not saved:
        return None
    responses = {}
    for c in saved:
        response = {'url': c.get('url'), 'raw_xml': c.get('raw_search_xml'),
                    'retrieved_at': c.get('retrieved_at'), 'document_sha256': c.get('document_sha256')}
        responses[tuple(response.values())] = response
    if len(responses) != 1:
        return outcome('needs_review', ['Conflicting saved catalogue searches require review'], saved)
    result = assess_catalogue(fields, next(iter(responses.values())))
    result['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != 'loc-catalogue'] + result['candidates']
    result['attempts'] = previous.get('attempts', [])
    return result


def valid_catalogue_approval(result):
    """Validate the portable source envelope and accepted MARC record identity."""
    if result.get('accepted_source') != 'loc-catalogue' or not result.get('accepted_record_id'):
        return False
    saved = [c for c in result.get('candidates', []) if c.get('source') == 'loc-catalogue'
             and c.get('record_id') == result['accepted_record_id'] and c.get('issues') == [] and c.get('evidence')]
    if len(saved) != 1:
        return False
    try:
        source = saved[0]
        # Reconstruct the originally checked local fields from their evidence.
        fields = {k: e['local'] for k, e in source['evidence'].items()}
        fields['ENTRYTYPE'] = 'book'
        checked = reassess_saved_catalogue(fields, result)
        return bool(checked and checked['status'] == 'metadata_verified'
                    and checked['accepted_record_id'] == result['accepted_record_id']
                    and next(c for c in checked['candidates'] if c.get('source') == 'loc-catalogue'
                             and c.get('record_id') == result['accepted_record_id']) == source)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration):
        return False


def run_catalogue_review(filename, cache, client, report, limit=None, snapshot=None, keys=None):
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    with run_lock(cache):
        entries = load_entries(filename)
        if keys is not None and set(keys) - entries.keys():
            raise ValueError('Catalogue keys must name existing citations')
        count = 0
        try:
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
                previous = cache.get(filename, entry)
                fields = entry['fields']
                if (not previous or previous['status'] != 'needs_review' or previous.get('external_evidence')
                        or fields.get('ENTRYTYPE') != 'book' or fields.get('doi') or not fields.get('author')
                        or previous.get('catalogue_review', {}).get('policy') == CATALOGUE_POLICY):
                    continue
                if limit is not None and count >= limit:
                    break
                response = fetch_search(cache, client, fields)
                result = assess_catalogue(fields, response)
                attempts = [{'source': 'loc-catalogue', 'url': response['url']}]
                queries = [response['query']]
                discovery_options = {}
                if (response.get('total_records') == 0
                        and search_query(fields, fold_diacritics=True) != response['query']):
                    discovery_options = {'fold_diacritics': True}
                    response = fetch_search(cache, client, fields, **discovery_options)
                    result = assess_catalogue(fields, response)
                    attempts.append({'source': 'loc-catalogue', 'url': response['url']})
                    queries.append(response['query'])
                if (result['status'] != 'metadata_verified'
                        and (len(result['candidates']) > 1 or response.get('truncated'))
                        and re.fullmatch(r'[1-9]\d{3}', str(fields.get('year', '')))):
                    refined = fetch_search(cache, client, fields, include_year=True, **discovery_options)
                    narrowed = assess_catalogue(fields, refined)
                    attempts.append({'source': 'loc-catalogue', 'url': refined['url']})
                    queries.append(refined['query'])
                    # An empty refinement is not proof that the broader
                    # edition evidence was wrong. Keep those discovery leads.
                    if narrowed['candidates'] and not refined.get('truncated'):
                        response, result = refined, narrowed
                result['candidates'] = [c for c in previous.get('candidates', []) if c.get('source') != 'loc-catalogue'] + result['candidates']
                result['attempts'] = previous.get('attempts', []) + attempts
                for name in ('auto_review', 'discovery_review', 'research_attempt'):
                    if name in previous:
                        result[name] = deepcopy(previous[name])
                result['catalogue_review'] = {'policy': CATALOGUE_POLICY, 'query': response['query'], 'queries': queries}
                cache.put(filename, entry, result)
                count += 1
        finally:
            write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
        return current_results(filename, cache, entries)
