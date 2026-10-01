"""Paced Library of Congress edition discovery; results are not approvals.

Search results preserve individual MARC records, truncation, and provenance.
No merged work-level metadata is used to decide a book's edition.
"""
import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET

import requests
from .name_parsing import splitname
from .verification import ProviderError, normalized, now, split_authors

ENDPOINT = "https://lx2.loc.gov/sru/lcdb"
S = "{http://www.loc.gov/zing/srw/}"
M = "{http://www.loc.gov/MARC21/slim}"
MAX_BYTES = 2_000_000


def search_query(fields, *, include_year=False, fold_diacritics=False):
    # Search tolerates punctuation differences; assessment must compare the
    # complete transcribed title, including subtitles, independently.
    def search_text(value):
        text = normalized(value)
        if fold_diacritics:
            text = ''.join(c for c in unicodedata.normalize('NFD', text)
                           if not unicodedata.combining(c))
        return " ".join(re.findall(r"\w+", text))
    title = search_text(fields["title"])
    # An edited volume without an author is discovered by its first editor;
    # the assessment still compares the complete ordered editor list.
    names = split_authors(fields.get("author") or fields.get("editor") or "")
    if not title or not names or not names[0]:
        raise ValueError("Catalogue discovery requires a title and named author")
    name = splitname(names[0], strict_mode=True)
    surname = search_text(" ".join(name["von"] + name["last"]))
    if not surname:
        raise ValueError("Catalogue discovery requires a first-author surname")
    query = f'dc.title="{title}" and dc.author="{surname}"'
    if include_year:
        year = str(fields.get('year', ''))
        if not re.fullmatch(r'[1-9]\d{3}', year):
            raise ValueError('Year-filtered discovery requires one explicit four-digit year')
        # LC's date index retains the copyright prefix in legacy records.
        # This only discovers candidates; MARC 008 and the transcribed date
        # still need independent edition-level assessment.
        query += f' and (dc.date="{year}" or dc.date="c{year}")'
    return query


def parse_search(xml, query, limit=10):
    if (not isinstance(xml, str) or len(xml.encode()) > MAX_BYTES
            or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I)):
        raise ValueError("Unsupported catalogue XML")
    root = ET.fromstring(xml)
    if root.tag != S + "searchRetrieveResponse" or root.findtext(S + "version") != "1.1":
        raise ValueError("Not an SRU 1.1 catalogue response")
    if any(n.tag.rsplit("}", 1)[-1] in {"diagnostic", "diagnostics"} for n in root.iter()):
        raise ValueError("Catalogue returned a diagnostic instead of complete records")
    if root.findtext(S + "echoedSearchRetrieveRequest/" + S + "query") != query:
        raise ValueError("Catalogue response does not echo the requested query")
    total = root.findtext(S + "numberOfRecords", "")
    if not re.fullmatch(r"\d+", total):
        raise ValueError("Missing catalogue result count")
    wrappers = root.findall(S + "records/" + S + "record")
    if len(wrappers) != min(int(total), limit):
        raise ValueError("Catalogue returned incomplete records")
    records, ids = [], set()
    for position, wrapper in enumerate(wrappers, 1):
        data = wrapper.find(S + "recordData")
        if (wrapper.findtext(S + "recordSchema") != "marcxml"
                or wrapper.findtext(S + "recordPacking") != "xml"
                or wrapper.findtext(S + "recordPosition") != str(position)
                or data is None or len(data) != 1 or data[0].tag != M + "record"):
            raise ValueError("Unexpected catalogue record envelope")
        record = data[0]
        identity = record.findall(M + "controlfield[@tag='001']")
        if len(identity) != 1 or not (identity[0].text or "").strip() or identity[0].text in ids:
            raise ValueError("Missing or duplicate catalogue record identity")
        ids.add(identity[0].text)
        records.append(ET.tostring(record, encoding="unicode"))
    return {"total_records": int(total), "truncated": int(total) > limit, "records": records}


def fetch_search(cache, client, fields, limit=10, *, include_year=False, fold_diacritics=False):
    if not 1 <= limit <= 50:
        raise ValueError("Catalogue result limit must be between 1 and 50")
    query = search_query(fields, include_year=include_year, fold_diacritics=fold_diacritics)
    identity = f"loc-sru-v1:{limit}:{query}"
    saved = cache.response(identity, 30 * 86400)
    if saved is not None and not client.refresh:
        if hashlib.sha256(saved["raw_xml"].encode()).hexdigest() != saved["document_sha256"]:
            raise ProviderError("Cached catalogue document hash differs")
        parsed = parse_search(saved["raw_xml"], query, limit)
        return dict(saved, **parsed)
    interval = client.interval
    client.interval = max(interval, 3.1)
    try:
        response = client.source_request(ENDPOINT, params={
            "operation": "searchRetrieve", "version": "1.1", "query": query,
            "maximumRecords": limit, "recordSchema": "marcxml", "recordPacking": "xml"
        }, timeout=(10, 45), allow_redirects=False, stream=True)
        try:
            if response.status_code != 200:
                raise ProviderError(f"Catalogue HTTP {response.status_code}; Retry-After: {response.headers.get('Retry-After')}")
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ProviderError("Catalogue response exceeded size limit")
            xml = bytes(body).decode("utf-8-sig")
            parsed = parse_search(xml, query, limit)
            result = dict(parsed, url=response.url, query=query, raw_xml=xml,
                          retrieved_at=now(), document_sha256=hashlib.sha256(xml.encode()).hexdigest())
        finally:
            response.close()
    except (requests.RequestException, ValueError, ET.ParseError) as exc:
        raise ProviderError("Catalogue retrieval failed: " + str(exc)) from exc
    finally:
        client.interval = interval
    cache.save_response(identity, result)
    return result
