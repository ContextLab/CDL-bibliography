"""Evidence-based citation checking. No network result ever edits a bibliography.

The cache is an audit log, not an authority: use current_results(), which validates
the source fingerprints, rather than reading old review rows as current approvals.
"""

from __future__ import annotations

import contextlib
from functools import lru_cache
import hashlib
import gzip
import html
import json
import math
import os
from pathlib import Path
import random
import re
import sqlite3
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
import xml.etree.ElementTree as ET

import bibtexparser
from bibtexparser.customization import splitname
from pylatexenc.latex2text import LatexNodes2Text
import requests

POLICY = "2"
ACCEPTED = {"metadata_verified", "human_verified"}
RECORD_FIELDS = {
    "DOI",
    "alias",
    "title",
    "subtitle",
    "author",
    "editor",
    "published",
    "published-print",
    "published-online",
    "issued",
    "container-title",
    "volume",
    "issue",
    "page",
    "article-number",
    "publisher",
    "type",
    "ISBN",
    "ISSN",
    "URL",
    "link",
    "relation",
    "update-to",
    "updated-by",
    "subtype",
}


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def now():
    return datetime.now(timezone.utc).isoformat()


def top_level_parts(text):
    """Split commas outside braces/quotes, preserving LaTeX escaped delimiters."""
    depth, quoted, start, i = 0, False, 0, 0
    parts = []
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == '"' and depth == 0:
            quoted = not quoted
        elif not quoted:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == "," and depth == 0:
                parts.append(text[start:i])
                start = i + 1
        i += 1
    if depth != 0 or quoted:
        raise ValueError("Unbalanced BibTeX field")
    parts.append(text[start:])
    return parts


def load_entries(filename):
    """Strict source scanner plus BibTeX parser; never silently drop entries.

    Fingerprints cover raw entry bytes (including case and whitespace, except the
    citation key token), all
    string/preamble definitions, and recursively inherited crossref/xdata entries.
    A definition change deliberately invalidates all entries, conservatively.
    """
    text = Path(filename).read_bytes().decode("utf-8-sig")
    blocks, definitions, pos = [], [], 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        if text[pos] == "%":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end + 1
            continue
        match = re.match(r"@([A-Za-z]+)\s*([({])", text[pos:])
        if not match:
            raise ValueError(
                f"Unparsed BibTeX at character {pos}: {text[pos : pos + 50]!r}"
            )
        kind, opener = match.groups()
        start = pos
        pos += match.end()
        body_start = pos
        depth, quoted = 0, False
        while pos < len(text):
            c = text[pos]
            if c == "\\":
                pos += 2
                continue
            if c == '"' and depth == 0:
                quoted = not quoted
            if not quoted:
                if (opener == "{" and c == "}" and depth == 0) or (
                    opener == "(" and c == ")" and depth == 0
                ):
                    break
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth < 0:
                        raise ValueError("Unbalanced entry")
            pos += 1
        if pos == len(text):
            raise ValueError(f"Unterminated entry at character {start}")
        raw, body = text[start : pos + 1], text[body_start:pos]
        pos += 1
        if kind.lower() == "comment":
            continue
        if kind.lower() in {"string", "preamble"}:
            definitions.append(raw)
            continue
        parts = top_level_parts(body)
        key_part = parts.pop(0)
        key = key_part.strip()
        key_start = body_start - start + len(key_part) - len(key_part.lstrip())
        keyless = raw[:key_start] + raw[key_start + len(key) :]
        names = []
        for part in parts:
            if not part.strip():
                continue
            field = re.match(r"\s*([\w-]+)\s*=", part)
            if not field:
                raise ValueError(f"Malformed field in {key}: {part!r}")
            names.append(field[1].lower())
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate field in {key}")
        blocks.append((key, raw, names, keyless))
    if not blocks:
        raise ValueError("No bibliography entries found")
    parser = bibtexparser.bparser.BibTexParser(
        ignore_nonstandard_types=False, common_strings=True, homogenize_fields=False
    )
    parsed = parser.parse(text)
    if len(parsed.entries) != len(blocks):
        raise ValueError("BibTeX parser skipped entries; refusing partial verification")
    entries = {}
    definitions_hash = digest("\n".join(definitions))
    for (key, raw, names, keyless), fields in zip(blocks, parsed.entries):
        if fields["ID"] != key or set(fields) - {"ID", "ENTRYTYPE"} != set(names):
            raise ValueError(f"Parser/source disagreement for {key}")
        if key in entries:
            raise ValueError(f"Duplicate citation key: {key}")
        entries[key] = {
            "key": key,
            "raw": raw,
            "fields": fields,
            "base_hash": digest(keyless + "\0" + definitions_hash),
            "legacy_base_hash": digest(raw + "\0" + definitions_hash),
        }

    @lru_cache(maxsize=None)
    def fingerprint(key, ancestors=(), legacy=False):
        if key in ancestors:
            raise ValueError(f"Cyclic bibliography inheritance: {key}")
        entry = entries[key]
        dependencies = []
        for field in ("crossref", "xdata"):
            for parent in entry["fields"].get(field, "").split(","):
                parent = parent.strip()
                if parent:
                    if parent not in entries:
                        raise ValueError(f"Missing inherited entry {parent} for {key}")
                    dependencies.append(fingerprint(parent, ancestors + (key,), legacy))
        return digest(
            entry["legacy_base_hash" if legacy else "base_hash"] + dumps(dependencies)
        )

    for key, entry in entries.items():
        entry["fingerprint"] = "v2:" + fingerprint(key)
        entry["legacy_fingerprint"] = fingerprint(key, legacy=True)
    return entries


class Cache:
    """Indexed SQLite with atomic per-entry checkpoints and immutable history."""

    def __init__(self, filename):
        self.path = Path(filename)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError(f"Unsupported cache schema {version}")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY, bibliography TEXT NOT NULL, key TEXT NOT NULL,
                fingerprint TEXT NOT NULL, policy TEXT NOT NULL, result TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS review_lookup ON reviews
                (bibliography, key, fingerprint, policy, id);
            CREATE INDEX IF NOT EXISTS review_content_lookup ON reviews
                (bibliography, fingerprint, policy, id);
            CREATE TABLE IF NOT EXISTS responses (
                request TEXT PRIMARY KEY, fetched REAL NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS source_notices (
                doi TEXT NOT NULL, evidence_hash TEXT NOT NULL, candidate TEXT NOT NULL,
                PRIMARY KEY (doi, evidence_hash));
            CREATE TABLE IF NOT EXISTS notice_checkpoint (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), review_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS source_author_suffixes (
                doi TEXT NOT NULL, evidence_hash TEXT NOT NULL, candidate TEXT NOT NULL,
                PRIMARY KEY (doi, evidence_hash));
            CREATE TABLE IF NOT EXISTS author_suffix_checkpoint (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), review_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS jats_notice_checkpoint (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), review_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS source_article_locators (
                doi TEXT NOT NULL, evidence_hash TEXT NOT NULL, candidate TEXT NOT NULL,
                PRIMARY KEY (doi, evidence_hash));
            CREATE TABLE IF NOT EXISTS article_locator_checkpoint (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), review_id INTEGER NOT NULL);
            PRAGMA user_version=1;
        """)

    def close(self):
        self.db.close()

    def get(self, bibliography, entry, any_policy=False):
        # Separate indexed lookups: an OR across the two fingerprint formats
        # makes SQLite scan a bibliography's entire audit history per entry.
        content_row = self.db.execute(
            """SELECT id,result FROM reviews WHERE bibliography=?
            AND fingerprint=? AND (policy=? OR ?) ORDER BY id DESC LIMIT 1""",
            (
                str(Path(bibliography).resolve()),
                entry["fingerprint"],
                POLICY,
                any_policy,
            ),
        ).fetchone()
        legacy_row = self.db.execute(
            """SELECT id,result FROM reviews WHERE bibliography=?
            AND key=? AND fingerprint=? AND (policy=? OR ?) ORDER BY id DESC LIMIT 1""",
            (
                str(Path(bibliography).resolve()),
                entry["key"],
                entry.get("legacy_fingerprint", entry["fingerprint"]),
                POLICY,
                any_policy,
            ),
        ).fetchone()
        row = max((r for r in (content_row, legacy_row) if r), default=None)
        if not row:
            return None
        result = json.loads(row[1])
        if result["fingerprint"] != entry["fingerprint"]:
            # Upgrade only an exact legacy match. Preserve the evidence, policy,
            # and original check time; this is bookkeeping, not a new check.
            result = dict(
                result,
                fingerprint_migration={
                    "key": result["key"],
                    "fingerprint": result["fingerprint"],
                },
                fingerprint=entry["fingerprint"],
            )
            if not self.store(
                bibliography, entry, result, after_id=row[0], any_policy=any_policy
            ):
                return self.get(bibliography, entry, any_policy=any_policy)
        result = dict(result, key=entry["key"])
        retained = self.retain_notices(entry, result)
        if retained != result:
            return self.put(bibliography, entry, retained)
        return result

    def store(self, bibliography, entry, result, after_id=None, any_policy=False):
        """Append an audit row without changing its policy or verification time."""
        bibliography = str(Path(bibliography).resolve())
        values = (
            bibliography,
            entry["key"],
            entry["fingerprint"],
            result["policy"],
            dumps(result),
        )
        query = """INSERT INTO reviews
                   (bibliography,key,fingerprint,policy,result) SELECT ?,?,?,?,?"""
        if after_id is not None:
            # A status read may migrate concurrently with a new review. Never
            # append stale approval over a decision written since our lookup.
            query += """ WHERE NOT EXISTS (
                SELECT 1 FROM reviews WHERE bibliography=? AND fingerprint=?
                AND (policy=? OR ?) AND id>?) AND NOT EXISTS (
                SELECT 1 FROM reviews WHERE bibliography=? AND key=? AND fingerprint=?
                AND (policy=? OR ?) AND id>?)"""
            values += (
                bibliography,
                entry["fingerprint"],
                POLICY,
                any_policy,
                after_id,
                bibliography,
                entry["key"],
                entry["legacy_fingerprint"],
                POLICY,
                any_policy,
                after_id,
            )
        with self.db:
            return self.db.execute(query, values).rowcount == 1

    def put(self, bibliography, entry, result):
        self.remember_notices(result.get("candidates", []))
        result = self.retain_notices(entry, result)
        result = dict(
            result,
            checked_at=now(),
            key=entry["key"],
            fingerprint=entry["fingerprint"],
            policy=POLICY,
        )
        self.store(bibliography, entry, result)
        return result

    def remember_notices(self, candidates):
        """Keep DOI-linked negative evidence independently of entry revisions."""
        from auto_review import secondary_notice_flags, secondary_suffix_dois
        from source_locators import locator_dois

        for candidate in candidates:
            flagged = secondary_notice_flags([candidate])
            suffixes = secondary_suffix_dois([candidate])
            locators = locator_dois([candidate])
            if not flagged and not suffixes and not locators:
                continue
            # Positive judgments refer to the old entry and must not transfer.
            retained = {k: candidate[k] for k in (
                "source", "doi", "raw_record", "retrieved_at", "request_url", "url",
                "raw_xml", "medline_record", "xml_sha256"
            ) if k in candidate}
            retained.update(evidence={}, issues=["Retained DOI-linked source evidence requires assessment"])
            body = dumps(retained)
            identity = digest(dumps(retained.get("raw_record", retained.get("raw_xml"))))
            with self.db:
                if flagged:
                    self.db.execute("INSERT OR IGNORE INTO source_notices VALUES (?,?,?)",
                                    (next(iter(flagged)), identity, body))
                if suffixes:
                    self.db.execute("INSERT OR IGNORE INTO source_author_suffixes VALUES (?,?,?)",
                                    (next(iter(suffixes)), identity, body))
                if locators:
                    self.db.execute("INSERT OR IGNORE INTO source_article_locators VALUES (?,?,?)",
                                    (next(iter(locators)), identity, body))

    def index_notices(self):
        """Incrementally migrate negative evidence from immutable audit history."""
        row = self.db.execute("SELECT review_id FROM notice_checkpoint WHERE singleton=1").fetchone()
        last = row[0] if row else 0
        end = self.db.execute("SELECT COALESCE(MAX(id),0) FROM reviews").fetchone()[0]
        rows = self.db.execute("""SELECT result FROM reviews WHERE id>? AND id<=?
            AND (result LIKE '%commentCorrectionList%' OR result LIKE '%isRetracted%' OR result LIKE '%biorxiv-preprint%' OR result LIKE '%arxiv-repository%')""", (last, end))
        for (body,) in rows:
            self.remember_notices(json.loads(body).get("candidates", []))
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO notice_checkpoint VALUES (1,?)", (end,))
        row = self.db.execute("SELECT review_id FROM author_suffix_checkpoint WHERE singleton=1").fetchone()
        last = row[0] if row else 0
        for (body,) in self.db.execute("SELECT result FROM reviews WHERE id>? AND id<=? AND result LIKE '%fullName%'", (last, end)):
            self.remember_notices(json.loads(body).get("candidates", []))
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO author_suffix_checkpoint VALUES (1,?)", (end,))
        row = self.db.execute("SELECT review_id FROM jats_notice_checkpoint WHERE singleton=1").fetchone()
        last = row[0] if row else 0
        for (body,) in self.db.execute("SELECT result FROM reviews WHERE id>? AND id<=? AND result LIKE '%pmc-jats%'", (last, end)):
            self.remember_notices(json.loads(body).get("candidates", []))
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO jats_notice_checkpoint VALUES (1,?)", (end,))
        row = self.db.execute("SELECT review_id FROM article_locator_checkpoint WHERE singleton=1").fetchone()
        last = row[0] if row else 0
        for (body,) in self.db.execute("SELECT result FROM reviews WHERE id>? AND id<=? AND result LIKE '%pmc-jats%'", (last, end)):
            self.remember_notices(json.loads(body).get("candidates", []))
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO article_locator_checkpoint VALUES (1,?)", (end,))

    def retain_notices(self, entry, result):
        if result.get("status") == "human_verified":
            return result  # Explicit adjudication still requires its audit record.
        if (result.get('status') == 'metadata_verified' and result.get('accepted_source') == 'loc-catalogue'
                and result.get('accepted_record_id') and entry['fields'].get('ENTRYTYPE') == 'book'
                and not entry['fields'].get('doi')):
            # This edition is identified by a MARC record, not by any rejected
            # Crossref search alternatives retained in its audit history.
            return result
        candidates = list(result.get("candidates", []))
        # Once a DOI is uniquely verified, unrelated search alternatives must
        # not cause evidence attachment or a fresh review timestamp. The
        # accepted DOI and an explicitly supplied local DOI still retain all
        # negative evidence, including notices learned after verification.
        accepted_doi = result.get("accepted_doi")
        if result.get("status") == "metadata_verified" and not accepted_doi:
            # Direct Crossref approvals predate the secondary resolver's
            # accepted_doi field. Recover only their unique clean candidate;
            # ambiguous or malformed historical records retain all warnings.
            direct = {c["doi"] for c in candidates
                      if c.get("source") == "crossref" and c.get("doi")
                      and c.get("issues") == []}
            if len(direct) == 1:
                accepted_doi = next(iter(direct))
        dois = ({accepted_doi}
                if result.get("status") == "metadata_verified" and accepted_doi
                else {c.get("doi") for c in candidates if c.get("doi")})
        if entry["fields"].get("doi"):
            dois.add(entry["fields"]["doi"])
        # Legacy repository citations also put identifiers in volume/pages.
        # Known notices must survive edits before discovery yields candidates.
        from arxiv_review import identifier as arxiv_identifier, doi_for
        from preprint_review import identifier as biorxiv_identifier
        for identify, canonical in ((arxiv_identifier, doi_for), (biorxiv_identifier, lambda x: x)):
            try:
                dois.add(canonical(identify(entry['fields'])[0]))
            except (ValueError, TypeError):
                pass
        existing = {dumps(c.get("raw_record", c.get("raw_xml"))) for c in candidates
                    if c.get("source") in {"europepmc", "pmc-jats", "biorxiv-preprint", "arxiv-repository"}}
        added, known = [], False
        for doi in dois:
            try:
                doi = normalize_doi(doi)
            except (ValueError, TypeError):
                continue
            for (body,) in self.db.execute("SELECT candidate FROM source_notices WHERE doi=? UNION SELECT candidate FROM source_author_suffixes WHERE doi=? UNION SELECT candidate FROM source_article_locators WHERE doi=?", (doi, doi, doi)):
                candidate = json.loads(body)
                from source_locators import locator_dois, locator_conflicts
                if locator_dois([candidate]) and not locator_conflicts(entry['fields'], [candidate]):
                    from auto_review import secondary_notice_flags, secondary_suffix_dois
                    if not secondary_notice_flags([candidate]) and not secondary_suffix_dois([candidate]):
                        continue  # Matching locators are not transferable positive judgments.
                known = True
                raw = dumps(candidate.get("raw_record", candidate.get("raw_xml")))
                if raw not in existing:
                    added.append(candidate)
                    existing.add(raw)
        if not added and not known:
            return result
        result = dict(result, candidates=candidates + added)
        if result.get("status") == "metadata_verified":
            from auto_review import select_result
            checked = select_result(entry["fields"], result["candidates"], result.get("attempts", []))
            if checked["status"] != "metadata_verified":
                result.update(status="needs_review", issues=checked["issues"])
                result.pop("accepted_doi", None)
                result.pop("accepted_source", None)
        return result

    def response(self, request, ttl):
        row = self.db.execute(
            "SELECT fetched,body FROM responses WHERE request=?", (request,)
        ).fetchone()
        if row and time.time() - row[0] < ttl:
            return json.loads(row[1])
        return None

    def save_response(self, request, body):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO responses VALUES (?,?,?)",
                (request, time.time(), dumps(body)),
            )


@contextlib.contextmanager
def run_lock(cache, wait=False):
    """Reject concurrent runners sharing a cache; OS releases lock after crashes."""
    import fcntl

    with open(str(cache.path) + ".lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise ValueError(
                "Another verification process is using this cache"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class ProviderError(RuntimeError):
    pass


def crossref_work_doi(url):
    """Recognize only an HTTPS Crossref work endpoint, never a publisher URL."""
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "api.crossref.org"
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment or set(parse_qs(parsed.query)) - {"mailto"}):
        raise ValueError("Not a Crossref work endpoint")
    match = re.fullmatch(r"/(?:v1/)?works/(.+)", parsed.path)
    if not match:
        raise ValueError("Not a Crossref work endpoint")
    return normalize_doi(unquote(match[1]))


def valid_doi_alias(receipt, requested, prime):
    """Validate saved transport evidence of Crossref's permanent DOI alias."""
    try:
        return bool(receipt and receipt["http_status"] in (301, 308)
                    and normalize_doi(requested) != normalize_doi(prime)
                    and normalize_doi(receipt["requested_doi"]) == normalize_doi(requested)
                    and normalize_doi(receipt["prime_doi"]) == normalize_doi(prime)
                    and crossref_work_doi(receipt["from_url"]) == normalize_doi(requested)
                    and crossref_work_doi(receipt["to_url"]) == normalize_doi(prime))
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


class PoliteClient:
    """Serial requests, persistent connections, adaptive pacing and bounded retries.

    Cached responses contain retrieval time and URL; failed requests are never
    negative-cached. A provider outage stops a run instead of hammering each entry.
    """

    def __init__(
        self,
        cache,
        mailto,
        interval=1.0,
        session=None,
        sleep=time.sleep,
        clock=time.monotonic,
        refresh=False,
    ):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", mailto or ""):
            raise ValueError(
                "Supply a real contact email with --mailto or CROSSREF_MAILTO"
            )
        if not math.isfinite(interval) or interval < 0.5:
            raise ValueError("Request interval must be at least 0.5 seconds")
        self.cache, self.mailto, self.interval = cache, mailto, interval
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"bibcheck/2.0 (https://github.com/ContextLab/CDL-bibliography; mailto:{mailto})"
            }
        )
        self.sleep, self.clock, self.refresh = sleep, clock, refresh
        self.next_request = 0
        self.host_intervals = {}
        self.requests = 0

    def source_request(self, *args, **kwargs):
        """Count and pace one bounded publisher request (including redirects)."""
        self.sleep(max(0, self.next_request - self.clock()))
        self.requests += 1
        try:
            return self.session.get(*args, **kwargs)
        finally:
            self.next_request = self.clock() + self.interval

    def get(self, url, params=None, xml=False, _alias_depth=0):
        host = urlparse(url).hostname
        params = dict(params or {})
        if host == "api.crossref.org":
            params["mailto"] = self.mailto
        identity = dumps([url, {k: v for k, v in params.items() if k != "mailto"}, xml])
        cached = self.cache.response(identity, 30 * 86400)
        if cached is not None and not self.refresh:
            return cached
        for attempt in range(4):
            self.sleep(max(0, self.next_request - self.clock()))
            minimum = 3.1 if host == "export.arxiv.org" else self.interval
            delay = max(minimum, self.host_intervals.get(host, 0))
            try:
                self.requests += 1
                response = self.session.get(
                    url, params=params, timeout=(10, 40), allow_redirects=False
                )
            except requests.RequestException as exc:
                self.next_request = self.clock() + max(delay, 2 ** (attempt + 1))
                if attempt == 3:
                    raise ProviderError(f"{host}: {type(exc).__name__}: {exc}") from exc
                continue
            self.next_request = self.clock() + delay
            try:
                limit = float(response.headers["x-rate-limit-limit"])
                seconds = float(response.headers["x-rate-limit-interval"].rstrip("s"))
                if (
                    math.isfinite(limit)
                    and math.isfinite(seconds)
                    and limit > 0
                    and seconds > 0
                ):
                    delay = max(delay, 1.1 * seconds / limit)
                    self.host_intervals[host] = delay
                    self.next_request = self.clock() + delay
            except (KeyError, ValueError):
                pass
            if response.status_code == 429 or response.status_code >= 500:
                retry = response.headers.get("Retry-After", "")
                try:
                    wait = float(retry)
                except ValueError:
                    try:
                        wait = parsedate_to_datetime(retry).timestamp() - time.time()
                    except (ValueError, TypeError, OverflowError):
                        wait = 0
                self.host_intervals[host] = min(60, delay * 2)
                wait = max(
                    wait if math.isfinite(wait) else 0,
                    2 ** (attempt + 2) + random.random(),
                )
                if wait > 120 or attempt == 3:
                    raise ProviderError(
                        f"{host}: HTTP {response.status_code}; retry after {wait:.0f}s"
                    )
                self.next_request = self.clock() + wait
                continue
            if response.status_code in (301, 308) and host == "api.crossref.org" and not xml:
                try:
                    requested = crossref_work_doi(url)
                    target = urljoin(url, response.headers["Location"])
                    prime = crossref_work_doi(target)
                    if _alias_depth or requested == prime or urlparse(target).query:
                        raise ValueError("Alias loop, multiple hops, or unexpected query")
                    destination = self.get(target, _alias_depth=1)
                    record = destination.get("body", {}).get("message", {})
                    if destination["http_status"] != 200 or normalize_doi(record.get("DOI", "")) != prime:
                        raise ValueError("Alias destination did not return the named DOI")
                    receipt = {"requested_doi": requested, "prime_doi": prime,
                               "from_url": url, "to_url": target, "http_status": response.status_code,
                               "retrieved_at": now()}
                    if not valid_doi_alias(receipt, requested, prime):
                        raise ValueError("Invalid DOI alias evidence")
                    result = dict(destination, doi_alias=receipt)
                    self.cache.save_response(identity, result)
                    return result
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    raise ProviderError(f"Crossref alias requires review: {exc}") from exc
            if response.status_code not in (200, 404):
                raise ProviderError(
                    f"{host}: HTTP {response.status_code} (including redirects requires review)"
                )
            try:
                body = (
                    None
                    if response.status_code == 404
                    else (response.text if xml else response.json())
                )
            except (ValueError, requests.RequestException) as exc:
                raise ProviderError(f"{host}: invalid response") from exc
            result = {
                "url": response.url,
                "retrieved_at": now(),
                "http_status": response.status_code,
                "body": body,
            }
            # Retain metadata only: abstracts and references are unnecessary.
            if host == "api.crossref.org" and body is not None:
                if not isinstance(body, dict) or body.get("status") != "ok":
                    raise ProviderError("Malformed Crossref response")
                message = body.get("message")
                if not isinstance(message, dict):
                    raise ProviderError("Missing Crossref message")
                if "items" in message:
                    if not isinstance(message["items"], list):
                        raise ProviderError("Malformed Crossref items")
                    message = dict(
                        message, items=[self.trim(x) for x in message["items"]]
                    )
                else:
                    message = self.trim(message)
                result["body"] = dict(body, message=message)
            if host == "api.datacite.org" and body is not None:
                if (
                    not isinstance(body, dict)
                    or not isinstance(body.get("data"), dict)
                    or not isinstance(body["data"].get("attributes"), dict)
                    or not body["data"]["attributes"].get("doi")
                ):
                    raise ProviderError("Malformed DataCite response")
            if host == "www.ebi.ac.uk" and body is not None and xml:
                if len(body) > 20_000_000:
                    raise ProviderError("Europe PMC XML exceeds 20 MB")
                try:
                    if ET.fromstring(body).tag != "article":
                        raise ProviderError("Europe PMC XML is not an article")
                except ET.ParseError as exc:
                    raise ProviderError("Malformed Europe PMC XML") from exc
            if host == "www.ebi.ac.uk" and response.status_code == 200 and not xml:
                result_list = body.get("resultList") if isinstance(body, dict) else None
                records = result_list.get("result") if isinstance(result_list, dict) else None
                count = body.get("hitCount") if isinstance(body, dict) else None
                if (
                    not isinstance(records, list)
                    or type(count) is not int
                    or count != len(records)
                ):
                    # Search responses have occasionally been incomplete despite
                    # HTTP 200. Retry the identical query with bounded pacing;
                    # never cache it or interpret missing results as absence.
                    self.next_request = self.clock() + max(delay, 2 ** (attempt + 1))
                    size = len(records) if isinstance(records, list) else "missing"
                    reported = count if type(count) is int else "invalid"
                    if attempt < 3:
                        print(f"Europe PMC incomplete response (hitCount={reported}, "
                              f"records={size}); retry {attempt + 2}/4", flush=True)
                        continue
                    raise ProviderError(
                        "Malformed or truncated Europe PMC response after 4 attempts "
                        f"(hitCount={reported}, records={size})"
                    )
                if any(not isinstance(r, dict) for r in records):
                    raise ProviderError("Malformed Europe PMC record")
                from auto_review import EPMC_FIELDS

                result["body"] = dict(
                    body,
                    resultList={
                        "result": [
                            {k: v for k, v in r.items() if k in EPMC_FIELDS}
                            for r in records
                        ]
                    },
                )
            if host == "export.arxiv.org" and body is not None:
                try:
                    root = ET.fromstring(body)
                except ET.ParseError as exc:
                    raise ProviderError("Malformed arXiv XML") from exc
                atom = "{http://www.w3.org/2005/Atom}"
                if root.tag != atom + "feed" or any(
                    "/api/errors" in item.findtext(atom + "id", default="")
                    for item in root.findall(atom + "entry")
                ):
                    raise ProviderError("arXiv returned an API error feed")
            self.cache.save_response(identity, result)
            return result
        raise ProviderError(f"{host}: retries exhausted")

    @staticmethod
    def trim(record):
        if not isinstance(record, dict) or not record.get("DOI"):
            raise ProviderError("Crossref record has no DOI")
        return {k: v for k, v in record.items() if k in RECORD_FIELDS}

    def crossref_doi(self, doi):
        return self.get("https://api.crossref.org/works/" + quote(doi, safe=""))

    def crossref_search(self, fields):
        title = fields.get("title", "")
        try:
            title = normalized(title)
        except ValueError:
            pass  # search is discovery only; unsupported markup still cannot pass
        author = split_authors(fields.get("author", ""))[0]
        query = " ".join(
            [
                title,
                author,
                fields.get("year", ""),
                fields.get("journal", fields.get("booktitle", "")),
            ]
        )
        if len(query) > 1500:
            # Bound query cost without truncating the metadata used to verify it.
            query = query[:1500]
        return self.get(
            "https://api.crossref.org/works", {"query.bibliographic": query, "rows": 5}
        )

    def crossref_batch(self, dois):
        """Small DOI-only OR filter; never batch unrelated search strings.

        Commas cannot be represented safely in filter values; resolve those via
        singleton requests. Callers must check omitted DOIs individually.
        """
        dois = list(dict.fromkeys(dois))
        if not dois or len(dois) > 20 or any("," in doi for doi in dois):
            raise ValueError("DOI batch requires 1–20 DOIs without commas")
        return self.get(
            "https://api.crossref.org/works",
            {"filter": ",".join("doi:" + doi for doi in dois), "rows": len(dois)},
        )


def normalize_doi(value):
    value = value.strip().replace("\\_", "_")
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    value = unquote(value)
    if not re.fullmatch(r"10\.\d{4,9}/\S+", value):
        raise ValueError(f"Invalid DOI: {value!r}")
    return value.lower()


def normalized(value):
    """Conservative typography normalization; retain accents, subtitles and math.

    Unknown commands/math/semantic HTML are unresolved, never silently erased.
    """
    value = html.unescape(str(value))
    value = re.sub(r"</?(?:i|b|em|strong|jats:italic|jats:bold)\b[^>]*>", "", value)
    if re.search(r"[$<>]|\\[\[\]()]", value):
        raise ValueError("Math or semantic markup needs source review")
    allowed = {
        "textit",
        "textbf",
        "emph",
        "textrm",
        "texttt",
        "textsc",
        "textnormal",
        "LaTeX",
        "TeX",
        "ae",
        "AE",
        "oe",
        "OE",
        "o",
        "O",
        "l",
        "L",
        "ss",
        "i",
        "j",
        "c",
        "v",
        "u",
        "H",
        "r",
        "k",
        "b",
        "d",
        "t",
    }
    if any(command not in allowed for command in re.findall(r"\\([A-Za-z]+)", value)):
        raise ValueError("Unknown LaTeX command needs source review")
    if any(
        command not in "\\'`^\"~=. &%_{}#"
        for command in re.findall(r"\\([^A-Za-z])", value)
    ):
        raise ValueError("Unknown LaTeX control symbol needs source review")
    # API metadata is plain text, not a TeX alignment/comment. Preserve literal
    # punctuation rather than letting latex2text erase '&', '%' or '#'.
    value = re.sub(r"(?<!\\)([&%#])", r"\\\1", value)
    # pylatexenc's default texttt handler drops its argument. Font choice is
    # presentational; its content must survive just as it does for textrm.
    value = re.sub(r"\\texttt\b", r"\\textrm", value)
    value = LatexNodes2Text().latex_to_text(value)
    # casefold() would conflate distinct words such as German Maße and Masse.
    value = unicodedata.normalize("NFC", value).lower()
    value = value.translate(
        str.maketrans(
            {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "‐": "-", "‑": "-", "\u00a0": " "}
        )
    )
    return " ".join(value.split()).strip()


def normalize_pages(value):
    value = re.sub(r"\s*-+\s*", "-", normalized(value))
    # A one-page range and its sole page denote the same locator. Preserve
    # leading zeroes and never collapse distinct endpoints or mixed prefixes.
    match = re.fullmatch(r"(\d+)-\1", value)
    return match[1] if match else value


def normalize_title(value):
    """Ignore one terminal sentence period; preserve all other title content."""
    value = normalized(value)
    if value.endswith(".") and not value.endswith(".."):
        return value[:-1]
    return value


def normalize_journal(value):
    # This equivalence is confined to venue names, never paper titles/names.
    name = re.sub(r"(?<!\w)&(?!\w)", "and", normalized(value))
    # Exact, enumerated title variants checked in the representative source
    # audit (verification/pilot50/manual-ledger.txt). No substring/fuzzy matching:
    # e.g. the distinct Indian academy journal must never collapse into PNAS.
    aliases = {
        "proceedings of the national academy of sciences, usa": "proceedings of the national academy of sciences of the united states of america",
        "proceedings of the national academy of sciences": "proceedings of the national academy of sciences of the united states of america",
        "journal of neuroscience": "the journal of neuroscience",
        "the journal of neuroscience : the official journal of the society for neuroscience": "the journal of neuroscience",
        # Exact title variants checked against NLM/owner records; no generic
        # removal of articles, journal sections, cities, or historical titles.
        "journal of physiology": "the journal of physiology",
        "lancet neurology": "the lancet neurology",
        "the lancet. neurology": "the lancet neurology",
        "new england journal of medicine": "the new england journal of medicine",
        "annals of mathematical statistics": "the annals of mathematical statistics",
        "computer journal": "the computer journal",
        "journal of the acoustical society of america": "the journal of the acoustical society of america",
        "journal of general psychology": "the journal of general psychology",
        "journal of psychology": "the journal of psychology",
        "american journal of human genetics": "the american journal of human genetics",
        "journal of comparative neurology": "the journal of comparative neurology",
        "international journal of robotics research": "the international journal of robotics research",
        "european physical journal b": "the european physical journal b",
        "journal of experimental biology": "the journal of experimental biology",
        "british journal for the philosophy of science": "the british journal for the philosophy of science",
        "journal of abnormal and social psychology": "the journal of abnormal and social psychology",
        # NLM 9214304 lists Cognitive Brain Research as the other title of
        # Brain research. Cognitive brain research. (ISSN 0926-6410).
        # Keep the section name: Brain Research itself is a different journal.
        "brain research. cognitive brain research": "cognitive brain research",
        "brain research: cognitive brain research": "cognitive brain research",
        "brain research : cognitive brain research": "cognitive brain research",
        # Publisher-branded journal and NLM/formatter variants independently
        # checked against published front matter (documented-journals-audit.json).
        # These are exact names, not general trademark/subtitle removal.
        "foundations and trends® in machine learning": "foundations and trends in machine learning",
        "philosophical transactions of the royal society of london series b: biological sciences": "philosophical transactions of the royal society b: biological sciences",
        "philosophical transactions of the royal society of london. series b, biological sciences": "philosophical transactions of the royal society b: biological sciences",
    }
    return aliases.get(name, name)


BENIGN_RELATIONS = {"has-review", "references", "is-referenced-by"}


def record_advisories(fields, record):
    notes = []
    if not fields.get("number") and record.get("issue"):
        notes.append(f"Optional issue number available from source: {record['issue']}")
    if isinstance(record.get("relation"), dict):
        benign = sorted(set(record["relation"]) & BENIGN_RELATIONS)
        if benign:
            notes.append(
                "Non-version source relationships retained: " + ", ".join(benign)
            )
    return notes


def split_authors(value):
    # BibTeX 'and' inside a braced organization is not an author delimiter.
    names, depth, start, i = [], 0, 0, 0
    while i < len(value):
        if value[i] == "\\":
            i += 2
            continue
        if value[i] == "{":
            depth += 1
        elif value[i] == "}":
            depth -= 1
        elif depth == 0 and value[i : i + 5] == " and ":
            names.append(value[start:i].strip())
            start, i = i + 5, i + 4
        i += 1
    names.append(value[start:].strip())
    return names


def given_name_tokens(value):
    """Separate explicitly dotted initials without inferring undotted acronyms.

    Registry deposits often omit spaces in ``A.A.`` or ``M.E. J.``. Dots
    delimit those single-letter initials; a word such as ``Ann`` or an
    undotted ``AA`` must remain one token. Hyphenated names retain their
    existing comparison semantics.
    """
    value = normalized(value)
    value = re.sub(
        r"(?<!\S)(?:[^\W\d_]\.)+[^\W\d_]\.?(?=\s|$)",
        lambda match: match.group().replace(".", " "),
        value,
    )
    return value.replace(".", "").split()


def given_token_matches(local, source):
    """Match explicit initials, including each half of a hyphenated name."""
    if local == source or (len(local) == 1 and source.startswith(local)):
        return True
    left, right = local.split("-"), source.split("-")
    return (len(left) > 1 and len(left) == len(right)
            and all(a and b and (a == b or (len(a) == 1 and b.startswith(a)))
                    for a, b in zip(left, right)))


def normalize_author_suffix(value):
    """Ignore a single abbreviation period on explicitly recognized suffixes."""
    value = normalized(value)
    if re.fullmatch(r"(?:jr|sr|ii|iii|iv|v|vi|vii|viii|ix|x)\.", value):
        return value[:-1]
    return value


def author_evidence(value, people):
    names = split_authors(value)
    if not value or not people or len(names) != len(people):
        return False, "Missing authors or different author counts"
    for name, person in zip(names, people):
        if name.startswith("{") and name.endswith("}"):
            if not normalized(name) or normalized(name) != normalized(
                person.get("name", "")
            ):
                return (
                    False,
                    "Corporate author differs or is not represented as an organization",
                )
            continue
        parts = splitname(name, strict_mode=True)
        family = " ".join(parts["von"] + parts["last"])
        if normalized(family) != normalized(person.get("family", "")):
            return False, "Author surnames/order differ"
        if normalize_author_suffix(" ".join(parts["jr"])) != normalize_author_suffix(person.get("suffix", "")):
            return False, "Author suffix differs"
        given = given_name_tokens(" ".join(parts["first"]))
        actual = given_name_tokens(person.get("given", ""))
        if not given or len(given) != len(actual):
            return False, "Missing or incomplete given names"
        for a, b in zip(given, actual):
            # Initials are allowed only when explicitly supplied by the citation;
            # do not collapse two conflicting full names or omit middle initials.
            if not given_token_matches(a, b):
                return False, "Author given names differ"
    return (
        True,
        "Complete author list in order; citation initials agree with source names",
    )


def normalize_publisher(value):
    """Exact corporate-name variants, never acquisitions or historical imprints.

    Sources and exclusions: verification/resolution-2026-09-15/README.md.
    Only applied to journal publishers; book editions retain literal checks.
    """
    value = normalized(value)
    return {
        "elsevier bv": "elsevier",
        "elsevier b.v.": "elsevier",
        "mit press - journals": "mit press",
        "journal of neurosurgery publishing group (jnspg)": "journal of neurosurgery publishing group",
        "american psychological association (apa)": "american psychological association",
        "american association for the advancement of science (aaas)": "american association for the advancement of science",
        "oxford university press (oup)": "oxford university press",
        "public library of science (plos)": "public library of science",
        "association for computing machinery (acm)": "association for computing machinery",
        "institute of electrical and electronics engineers (ieee)": "institute of electrical and electronics engineers",
        "ieee": "institute of electrical and electronics engineers",
        "cambridge university press (cup)": "cambridge university press",
        "american physical society (aps)": "american physical society",
        # Same publisher's brand and legal entity; no parent/imprint mapping.
        # https://www.frontiersin.org/about/contact
        # https://karger.com/pages/catalogue-and-pricing
        "frontiers media sa": "frontiers",
        "s. karger ag": "karger",
    }.get(value, value)


def explicit_final_article(fields, record, evidence):
    """A final DOI and complete journal coordinates select the article itself.

    A has-preprint link is retained as provenance, never followed to replace the
    cited work. Missing/malformed links, other version relations, and any field
    conflict continue to block. See Crossref's posted-content markup guide.
    """
    relations = record.get("relation")
    if (
        fields.get("ENTRYTYPE", "").lower() != "article"
        or record.get("type") != "journal-article"
        or not isinstance(relations, dict)
        or set(relations) - (BENIGN_RELATIONS | {"has-preprint"})
        or not isinstance(relations.get("has-preprint"), list)
        or not relations["has-preprint"]
        or record.get("update-to")
        or record.get("updated-by")
        or not all(
            evidence.get(f, {}).get("match")
            for f in ("doi", "title", "author", "year", "journal", "volume", "pages")
        )
    ):
        return False
    try:
        own_doi = normalize_doi(record["DOI"])
        return all(
            isinstance(link, dict)
            and link.get("id-type") == "doi"
            and normalize_doi(link.get("id", "")) != own_doi
            for link in relations["has-preprint"]
        )
    except (ValueError, TypeError, AttributeError):
        return False


def compare_record(fields, record, doi_alias=None):
    """Return field evidence and blockers. Similarity scores cannot authorize."""
    evidence, issues = {}, []

    def check(field, source, required=False, transform=normalized):
        local = fields.get(field, "")
        values = source if isinstance(source, list) else [source]
        values = [str(v) for v in values if v is not None and str(v)]
        if not local and not required:
            return
        try:
            canonical = transform(local) if local else ""
            match = bool(
                canonical and values and any(canonical == transform(v) for v in values)
            )
        except ValueError:
            match = False
        evidence[field] = {"local": local, "source": values, "match": match}
        if not match:
            issues.append(f"{field}: missing evidence or mismatch")

    titles = record.get("title", [])
    subtitles = record.get("subtitle", [])
    if (
        not isinstance(titles, list)
        or not isinstance(subtitles, list)
        or any(not isinstance(t, str) for t in titles + subtitles)
    ):
        raise ValueError("Source title/subtitle must be arrays of strings")
    subtitles = [s for s in subtitles if s.strip()]
    if subtitles:
        if len(titles) != 1 or len(subtitles) != 1:
            raise ValueError(
                "Ambiguous correspondence between source titles and subtitles"
            )
        # Crossref sometimes splits a subtitle and sometimes includes it already.
        titles = [
            t if normalized(t).endswith(": " + normalized(s)) else t + ": " + s
            for t in titles
            for s in subtitles
        ]
    check("title", titles, True, transform=normalize_title)
    try:
        authors_ok, detail = author_evidence(
            fields.get("author", ""), record.get("author", [])
        )
    except (ValueError, KeyError) as exc:
        authors_ok, detail = False, str(exc)
    evidence["author"] = {
        "local": fields.get("author", ""),
        "source": record.get("author", []),
        "match": authors_ok,
        "detail": detail,
    }
    if not authors_ok:
        issues.append("author: " + detail)
    years = set()
    for date in ("published", "published-print", "published-online", "issued"):
        for parts in record.get(date, {}).get("date-parts", []):
            if parts and re.fullmatch(r"[1-9]\d{3}", str(parts[0])):
                years.add(str(parts[0]))
    check("year", sorted(years), True)
    if len(years) != 1:
        issues.append(
            "year: conflicting or missing publication dates; select the cited edition explicitly"
        )
    kind = fields["ENTRYTYPE"].lower()
    expected = {
        "article": "journal-article",
        "inproceedings": "proceedings-article",
        "book": "book",
        "incollection": "book-chapter",
    }
    if kind not in expected or record.get("type") != expected[kind]:
        issues.append("publication type/version is unsupported or differs")
    venue_field = "journal" if kind == "article" else "booktitle"
    check(
        venue_field,
        record.get("container-title", []),
        kind in {"article", "incollection", "inproceedings"},
        transform=normalize_journal if venue_field == "journal" else normalized,
    )
    for field, source in (
        ("volume", "volume"),
        ("number", "issue"),
        ("publisher", "publisher"),
    ):
        check(
            field,
            record.get(source),
            kind == "book" and field == "publisher",
            transform=normalize_publisher
            if field == "publisher" and kind == "article"
            else normalized,
        )
    check(
        "pages",
        record.get("page") or record.get("article-number"),
        transform=normalize_pages,
    )
    identity_fields = fields
    if valid_doi_alias(doi_alias, fields.get("doi"), record.get("DOI")):
        check("doi", [record.get("DOI"), fields["doi"]], transform=normalize_doi)
        evidence["doi"]["alias_authority"] = doi_alias
        identity_fields = dict(fields, doi=record["DOI"])
    else:
        check("doi", record.get("DOI"), transform=normalize_doi)
    check(
        "isbn",
        record.get("ISBN", []),
        transform=lambda s: normalized(s).replace("-", ""),
    )
    check(
        "issn",
        record.get("ISSN", []),
        transform=lambda s: normalized(s).replace("-", ""),
    )
    # Missing local volume/page information also requires attention when the
    # source has it, rather than accepting an incomplete final citation.
    for local, remote in (("volume", "volume"), ("pages", "page")):
        if record.get(remote) and not fields.get(local):
            issues.append(f"{local}: source supplies a field absent from the citation")
    # An omitted optional issue is advisory when volume and full pagination
    # already agree. A supplied but wrong issue ALWAYS remains a blocker.
    if (
        record.get("issue")
        and not fields.get("number")
        and not all(evidence.get(f, {}).get("match") for f in ("volume", "pages"))
    ):
        issues.append("number: source supplies a field absent from the citation")
    if record.get("article-number") and not fields.get("pages"):
        issues.append(
            "pages: source supplies an article number absent from the citation"
        )
    covered = {
        "ID",
        "ENTRYTYPE",
        "title",
        "author",
        "year",
        "journal",
        "booktitle",
        "volume",
        "number",
        "pages",
        "publisher",
        "doi",
        "isbn",
        "issn",
        "force",
    }
    for field in sorted(set(fields) - covered):
        issues.append(f"{field}: no deterministic verifier for this field")
    if record.get("update-to") or record.get("updated-by"):
        issues.append("Source flags an update/correction/retraction relationship")
    relation = record.get("relation") or {}
    if (not isinstance(relation, dict) or set(relation) - BENIGN_RELATIONS) and not (
        not issues and explicit_final_article(identity_fields, record, evidence)
    ):
        issues.append("Source has related versions/works; review publication identity")
    return evidence, issues


def outcome(status, issues, candidates=None, attempts=None):
    return {
        "status": status,
        "issues": issues,
        "candidates": candidates or [],
        "attempts": attempts or [],
    }


def assess_candidates(fields, response):
    if response["body"] is None:
        return []
    message = response["body"]["message"]
    records = message.get("items", [message])
    candidates = []
    for record in records:
        try:
            evidence, issues = compare_record(fields, record, response.get("doi_alias"))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            evidence, issues = {}, [f"Unsupported source metadata: {exc}"]
        candidates.append(
            {
                "source": "crossref",
                "doi": record.get("DOI"),
                "url": "https://doi.org/" + quote(record.get("DOI", ""), safe="/"),
                "record": record,
                "evidence": evidence,
                "issues": issues,
                "advisories": record_advisories(fields, record),
                "retrieved_at": response["retrieved_at"],
                **({"doi_alias": response["doi_alias"]} if response.get("doi_alias") else {}),
            }
        )
    return candidates


def arxiv_id(fields):
    haystack = " ".join(fields.get(k, "") for k in ("eprint", "url", "journal", "doi"))
    match = re.search(
        r"(?:arxiv[}:.\s/]*|arxiv\.org/(?:abs|pdf)/)([a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?|\d{4}\.\d{4,5}(?:v\d+)?)",
        haystack,
        re.I,
    )
    if match:
        return match[1]
    value = fields.get("eprint", "")
    if fields.get("archiveprefix", "").lower() == "arxiv" and re.fullmatch(
        r"\d{4}\.\d{4,5}(?:v\d+)?", value
    ):
        return value
    return None


def fallback_evidence(fields, client, doi=None):
    """Identifier-specific authorities before PDF/LLM and human review.

    These sources provide review evidence, not a Crossref-equivalent approval:
    DataCite publicationYear and arXiv submitted dates have different semantics.
    """
    attempts, candidates = [], []
    if doi:
        response = client.get("https://api.datacite.org/dois/" + quote(doi, safe=""))
        attempts.append(
            {
                "source": "datacite",
                "url": response["url"],
                "http_status": response["http_status"],
            }
        )
        if response["body"]:
            attrs = response["body"].get("data", {}).get("attributes", {})
            if not attrs.get("doi"):
                raise ProviderError("Malformed DataCite response")
            candidates.append(
                {
                    "source": "datacite",
                    "url": response["url"],
                    "retrieved_at": response["retrieved_at"],
                    "record": {
                        k: attrs.get(k)
                        for k in (
                            "doi",
                            "titles",
                            "creators",
                            "publicationYear",
                            "publisher",
                            "types",
                            "relatedIdentifiers",
                            "url",
                            "version",
                        )
                    },
                }
            )
    identifier = arxiv_id(fields)
    if identifier:
        response = client.get(
            "https://export.arxiv.org/api/query", {"id_list": identifier}, xml=True
        )
        attempts.append(
            {
                "source": "arxiv",
                "url": response["url"],
                "http_status": response["http_status"],
            }
        )
        if response["body"]:
            try:
                root = ET.fromstring(response["body"])
            except ET.ParseError as exc:
                raise ProviderError("Malformed arXiv XML") from exc
            ns = {
                "a": "http://www.w3.org/2005/Atom",
                "x": "http://arxiv.org/schemas/atom",
            }
            for item in root.findall("a:entry", ns):
                record = {
                    k: item.findtext("a:" + k, default="", namespaces=ns)
                    for k in ("id", "title", "published", "updated")
                }
                record["authors"] = [
                    a.findtext("a:name", namespaces=ns)
                    for a in item.findall("a:author", ns)
                ]
                record["doi"] = item.findtext("x:doi", namespaces=ns)
                record["journal_ref"] = item.findtext("x:journal_ref", namespaces=ns)
                candidates.append(
                    {
                        "source": "arxiv",
                        "url": record["id"],
                        "record": record,
                        "retrieved_at": response["retrieved_at"],
                    }
                )
    return attempts, candidates


def verify_entry(entry, client):
    fields = entry["fields"]
    attempts, candidates = [], []
    doi = None
    if fields.get("doi"):
        try:
            doi = normalize_doi(fields["doi"])
        except ValueError as exc:
            return outcome("needs_review", [str(exc)])
        response = client.crossref_doi(doi)
        attempts.append(
            {
                "source": "crossref-doi",
                "url": response["url"],
                "http_status": response["http_status"],
            }
        )
        candidates = assess_candidates(fields, response)
        if candidates:
            good = [x for x in candidates if not x["issues"]]
            return outcome(
                "metadata_verified" if len(good) == 1 else "needs_review",
                [] if len(good) == 1 else candidates[0]["issues"],
                candidates,
                attempts,
            )
        extra_attempts, extras = fallback_evidence(fields, client, doi)
        attempts += extra_attempts
        candidates += extras
    if fields.get("title"):
        response = client.crossref_search(fields)
        attempts.append(
            {
                "source": "crossref-search",
                "url": response["url"],
                "http_status": response["http_status"],
            }
        )
        found = assess_candidates(fields, response)
        candidates += found
        good = {c["doi"]: c for c in found if not c["issues"]}
        if len(good) == 1 and not doi:
            # A truncated result list cannot prove uniqueness. A strict match is
            # evidence of consistency; also retain competing exact title matches.
            selected = next(iter(good.values()))
            rivals = [
                c
                for c in found
                if c["doi"] != selected["doi"]
                and c["evidence"].get("title", {}).get("match")
                and c["evidence"].get("author", {}).get("match")
            ]
            if not rivals:
                return outcome("metadata_verified", [], candidates, attempts)
        if len(good) > 1:
            return outcome(
                "needs_review",
                ["Multiple fully matching DOIs; ambiguous publication identity"],
                candidates,
                attempts,
            )
    if not doi:
        extra_attempts, extras = fallback_evidence(fields, client)
        attempts += extra_attempts
        candidates += extras
    issues = [
        "No unambiguous, fully supported metadata match; source/PDF review required"
    ]
    if doi:
        issues.append(
            "Supplied DOI was not found in Crossref; do not replace it with a search result automatically"
        )
    return outcome("needs_review", issues, candidates, attempts)


def current_results(filename, cache, entries=None):
    entries = entries if entries is not None else load_entries(filename)
    return {
        key: cache.get(filename, entry)
        or dict(
            outcome("pending", ["New, edited, or policy-invalidated entry"]),
            key=key,
            fingerprint=entry["fingerprint"],
            policy=POLICY,
        )
        for key, entry in entries.items()
    }


def validate_output_path(filename, output, cache):
    """Reports/snapshots must never overwrite the bibliography or working DB."""
    output = Path(output)
    for protected in (Path(filename), cache.path):
        if output.resolve() == protected.resolve() or (
            output.exists() and protected.exists() and output.samefile(protected)
        ):
            raise ValueError(
                "Output path would overwrite the bibliography or verification database"
            )


def export_snapshot(filename, cache, output):
    """Portable, compressed JSON Lines; do not commit a changing binary SQLite DB."""
    validate_output_path(filename, output, cache)
    cache.index_notices()
    results = current_results(filename, cache)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
    ) as handle:
        temporary = handle.name
    with gzip.open(temporary, "wt", encoding="utf-8") as stream:
        stream.write(
            dumps(
                {
                    "schema": 2,
                    "policy": POLICY,
                    "created_at": now(),
                    "entries": len(results),
                    "source_notices": [json.loads(r[0]) for r in cache.db.execute(
                        "SELECT candidate FROM source_notices ORDER BY doi,evidence_hash")],
                    "source_author_suffixes": [json.loads(r[0]) for r in cache.db.execute(
                        "SELECT candidate FROM source_author_suffixes ORDER BY doi,evidence_hash")],
                    "source_article_locators": [json.loads(r[0]) for r in cache.db.execute(
                        "SELECT candidate FROM source_article_locators ORDER BY doi,evidence_hash")],
                }
            )
            + "\n"
        )
        for result in results.values():
            stream.write(dumps(result) + "\n")
    os.replace(temporary, path)
    return results


def import_snapshot(filename, cache, snapshot):
    """Restore only matching fingerprints/policy from a trusted local snapshot.

    The entire file is validated before any rows are written. A snapshot is an
    audit artifact with the same trust as its source repository, not a signed
    certificate. Restoring it never blesses changed entries.
    """
    entries = load_entries(filename)
    with gzip.open(snapshot, "rt", encoding="utf-8") as stream:
        header = json.loads(next(stream))
        if (
            not isinstance(header, dict)
            or header.get("schema") not in (1, 2)
            or header.get("policy") != POLICY
        ):
            raise ValueError(
                "Snapshot schema/policy differs; reverify with the current policy"
            )
        records = [json.loads(line) for line in stream]
    if len(records) != header.get("entries"):
        raise ValueError("Incomplete verification snapshot")
    seen = set()
    statuses = ACCEPTED | {"pending", "needs_review", "provider_error"}
    for result in records:
        if (
            not isinstance(result, dict)
            or not {"key", "fingerprint", "policy", "status"} <= result.keys()
            or result["status"] not in statuses
            or result["policy"] != POLICY
            or result["key"] in seen
        ):
            raise ValueError("Invalid snapshot review record")
        if result["status"] == "human_verified" and not result.get("human_review"):
            raise ValueError("Human approval is missing its audit record")
        from catalogue_review import valid_catalogue_approval
        from preprint_review import valid_preprint_approval
        from arxiv_review import valid_arxiv_approval
        if result["status"] == "metadata_verified" and not valid_catalogue_approval(result) and not valid_preprint_approval(result) and not valid_arxiv_approval(result) and not any(
            c.get("source") in {"crossref", "europepmc", "pmc-jats", "publisher-head", "catalogue-imprint"}
            and c.get("evidence")
            and c.get("issues") == []
            and (
                c.get("source") == "crossref"
                or (
                    result.get("accepted_source") == c.get("source")
                    and result.get("accepted_doi") == c.get("doi")
                    and (
                        c.get("raw_record")
                        if c.get("source") == "europepmc"
                        else (
                            c.get("raw_metadata") and c.get("document_sha256")
                            if c.get("source") == "publisher-head"
                            else (c.get("raw_marcxml") and c.get("document_sha256") and c.get("edition_binding")
                                  if c.get("source") == "catalogue-imprint"
                                  else c.get("raw_xml") and c.get("medline_record"))
                        )
                    )
                )
            )
            for c in result.get("candidates", [])
        ):
            raise ValueError("Machine approval is missing its source evidence")
        seen.add(result["key"])
    notices = header.get("source_notices", [])
    from auto_review import secondary_notice_flags, secondary_suffix_dois
    if not isinstance(notices, list) or any(not isinstance(c, dict) or not secondary_notice_flags([c]) for c in notices):
        raise ValueError("Invalid snapshot source notice")
    suffixes = header.get("source_author_suffixes", [])
    if not isinstance(suffixes, list) or any(not isinstance(c, dict) or not secondary_suffix_dois([c]) for c in suffixes):
        raise ValueError("Invalid snapshot author suffix evidence")
    from source_locators import locator_dois
    locators = header.get("source_article_locators", [])
    if not isinstance(locators, list) or any(not isinstance(c, dict) or not locator_dois([c]) for c in locators):
        raise ValueError("Invalid snapshot article locator evidence")
    # Even an edited entry must retain known warnings from the trusted baseline.
    cache.remember_notices(notices + suffixes + locators)
    for result in records:
        cache.remember_notices(result.get("candidates", []))
    # Schema 1 includes the key in its hash and can migrate only an exact match.
    # Schema 2 is portable across key renames as well as clone paths.
    by_fingerprint = {}
    for entry in entries.values():
        by_fingerprint.setdefault(entry["fingerprint"], []).append(entry)
    count = 0
    with cache.db:
        for result in records:
            if header["schema"] == 1:
                entry = entries.get(result["key"])
                matches = (
                    [entry]
                    if entry and entry["legacy_fingerprint"] == result["fingerprint"]
                    else []
                )
            else:
                matches = by_fingerprint.get(result["fingerprint"], [])
            for entry in matches:
                if result["status"] == "pending" or cache.get(filename, entry):
                    continue
                restored = dict(
                    result, key=entry["key"], fingerprint=entry["fingerprint"]
                )
                if header["schema"] == 1:
                    restored["fingerprint_migration"] = {
                        "key": result["key"],
                        "fingerprint": result["fingerprint"],
                    }
                cache.db.execute(
                    """INSERT INTO reviews
                    (bibliography,key,fingerprint,policy,result) VALUES (?,?,?,?,?)""",
                    (
                        str(Path(filename).resolve()),
                        entry["key"],
                        entry["fingerprint"],
                        POLICY,
                        dumps(restored),
                    ),
                )
                count += 1
    return count


def write_report(filename, cache, report):
    validate_output_path(filename, report, cache)
    entries = load_entries(filename)  # re-read: edits during a run cannot pass
    results = current_results(filename, cache, entries)
    path = Path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as output:
        temporary = output.name
        for key, result in results.items():
            output.write(dumps(dict(result, entry=entries[key]["fields"])) + "\n")
    os.replace(temporary, path)
    return results


def run_verification(
    filename,
    cache,
    client,
    report,
    retry=False,
    refresh=False,
    limit=None,
    wait=False,
    snapshot=None,
    recheck_cached=False,
    keys=None,
):
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    completed = 0
    with run_lock(cache, wait=wait):
        cache.index_notices()
        entries = load_entries(filename)  # may have changed while waiting for a runner
        if keys is not None and set(keys) - entries.keys():
            raise ValueError(
                "Unknown citation keys: "
                + ", ".join(sorted(set(keys) - entries.keys()))
            )
        try:
            for key, entry in entries.items():
                if keys is not None and key not in keys:
                    continue
                previous = cache.get(filename, entry)
                if (
                    previous
                    and previous["status"] == "metadata_verified"
                    and recheck_cached
                ):
                    from auto_review import reassess

                    previous = cache.put(filename, entry, reassess(entry, previous))
                if (
                    previous
                    and previous["status"] != "provider_error"
                    and not refresh
                    and not (retry and previous["status"] not in ACCEPTED)
                ):
                    continue
                if limit is not None and completed >= limit:
                    break
                try:
                    result = verify_entry(entry, client)
                except ProviderError as exc:
                    cache.put(filename, entry, outcome("provider_error", [str(exc)]))
                    raise
                cache.put(filename, entry, result)
                completed += 1
                if completed % 25 == 0:
                    print(
                        f"Checked {completed}; latest {key}: {result['status']}; network requests {client.requests}",
                        flush=True,
                    )
        finally:
            results = write_report(filename, cache, report)
            if snapshot:
                export_snapshot(filename, cache, snapshot)
    return results
