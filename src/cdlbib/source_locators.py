"""Retain final-article coordinates that two identified sources corroborate.

A sparse registry deposit cannot hide a publisher/PubMed locator. This module
only supplies negative evidence; it cannot approve an entry or repair a field.
"""
from functools import lru_cache
import json
import xml.etree.ElementTree as ET

from .verification import normalize_doi, normalized


@lru_cache(maxsize=1024)
def _coordinates(doi, xml, medline_json):
    try:
        from .auto_review import expanded_pages
        from .fulltext_review import front_record
        med = json.loads(medline_json)
        if med.get('source') != 'MED' or not med.get('id'):
            return None
        info = med['journalInfo']
        journal = info['journal']
        primary = {'DOI':doi, 'type':'journal-article',
                   'ISSN':[v for k in ('issn','essn') if (v:=journal.get(k))],
                   'container-title':[journal['title']]}
        # Reuse all existing final-version, exact DOI, date, structured-name,
        # and top-level front-matter guards. Never read a reference-list page.
        record = front_record(xml, primary, med)
        volume = normalized(record.get('volume') or '')
        page = expanded_pages(record.get('page') or record.get('article-number') or '')
        if (not volume or not page or volume != normalized(str(info.get('volume') or ''))
                or page != expanded_pages(med.get('pageInfo') or '')
                or not set(record['ISSN']) & set(primary['ISSN'])):
            return None
        return doi, volume, page
    except (ValueError, TypeError, KeyError, AttributeError, ET.ParseError):
        return None


def source_coordinates(candidate):
    if candidate.get('source') != 'pmc-jats' or not candidate.get('raw_xml'):
        return None
    try:
        return _coordinates(normalize_doi(candidate['doi']), candidate['raw_xml'],
                            json.dumps(candidate['medline_record'], sort_keys=True))
    except (ValueError, TypeError, KeyError):
        return None


def locator_dois(candidates):
    return {coords[0] for c in candidates if (coords := source_coordinates(c))}


def locator_conflicts(fields, candidates):
    if fields.get('ENTRYTYPE') != 'article':
        return set()
    from .auto_review import expanded_pages
    result = set()
    for candidate in candidates:
        coords = source_coordinates(candidate)
        if coords:
            doi, volume, page = coords
            try:
                match = (normalized(fields.get('volume', '')) == volume
                         and expanded_pages(fields.get('pages', '')) == page)
            except (ValueError, TypeError):
                match = False
            if not match:
                result.add(doi)
    return result
