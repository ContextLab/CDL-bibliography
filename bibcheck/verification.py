"""Evidence-based citation checking. No network result ever edits a bibliography.

The cache is an audit log, not an authority: use current_results(), which validates
the source fingerprints, rather than reading old review rows as current approvals.
"""

from __future__ import annotations

import contextlib
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
from urllib.parse import quote, unquote, urlparse
import xml.etree.ElementTree as ET

import bibtexparser
from bibtexparser.customization import splitname
from pylatexenc.latex2text import LatexNodes2Text
import requests

POLICY = "2"
ACCEPTED = {"metadata_verified", "human_verified"}
RECORD_FIELDS = {
    "DOI",
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

    Fingerprints cover raw entry bytes (including case, whitespace and key), all
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
        key = parts.pop(0).strip()
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
        blocks.append((key, raw, names))
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
    for (key, raw, names), fields in zip(blocks, parsed.entries):
        if fields["ID"] != key or set(fields) - {"ID", "ENTRYTYPE"} != set(names):
            raise ValueError(f"Parser/source disagreement for {key}")
        if key in entries:
            raise ValueError(f"Duplicate citation key: {key}")
        entries[key] = {
            "key": key,
            "raw": raw,
            "fields": fields,
            "base_hash": digest(raw + "\0" + definitions_hash),
        }

    def fingerprint(key, ancestors=()):
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
                    dependencies.append(fingerprint(parent, ancestors + (key,)))
        return digest(entry["base_hash"] + dumps(dependencies))

    for key, entry in entries.items():
        entry["fingerprint"] = fingerprint(key)
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
            CREATE TABLE IF NOT EXISTS responses (
                request TEXT PRIMARY KEY, fetched REAL NOT NULL, body TEXT NOT NULL);
            PRAGMA user_version=1;
        """)

    def close(self):
        self.db.close()

    def get(self, bibliography, entry, any_policy=False):
        row = self.db.execute(
            """SELECT result FROM reviews WHERE bibliography=?
            AND key=? AND fingerprint=? AND (policy=? OR ?) ORDER BY id DESC LIMIT 1""",
            (
                str(Path(bibliography).resolve()),
                entry["key"],
                entry["fingerprint"],
                POLICY,
                any_policy,
            ),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, bibliography, entry, result):
        result = dict(
            result,
            checked_at=now(),
            key=entry["key"],
            fingerprint=entry["fingerprint"],
            policy=POLICY,
        )
        with self.db:
            self.db.execute(
                """INSERT INTO reviews
                (bibliography,key,fingerprint,policy,result) VALUES (?,?,?,?,?)""",
                (
                    str(Path(bibliography).resolve()),
                    entry["key"],
                    entry["fingerprint"],
                    POLICY,
                    dumps(result),
                ),
            )
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

    def get(self, url, params=None, xml=False):
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
            if host == "www.ebi.ac.uk" and body is not None and not xml:
                records = (
                    body.get("resultList", {}).get("result")
                    if isinstance(body, dict)
                    else None
                )
                count = body.get("hitCount") if isinstance(body, dict) else None
                if (
                    not isinstance(records, list)
                    or type(count) is not int
                    or count != len(records)
                ):
                    raise ProviderError("Malformed or truncated Europe PMC response")
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
    value = LatexNodes2Text().latex_to_text(value)
    # casefold() would conflate distinct words such as German Maße and Masse.
    value = unicodedata.normalize("NFC", value).lower()
    value = value.translate(
        str.maketrans(
            {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "\u00a0": " "}
        )
    )
    return " ".join(value.split()).strip()


def normalize_pages(value):
    return re.sub(r"\s*-+\s*", "-", normalized(value))


def normalize_journal(value):
    # This equivalence is confined to venue names, never paper titles/names.
    return re.sub(r"(?<!\w)&(?!\w)", "and", normalized(value))


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
        if normalized(" ".join(parts["jr"])) != normalized(person.get("suffix", "")):
            return False, "Author suffix differs"
        given = normalized(" ".join(parts["first"])).replace(".", "").split()
        actual = normalized(person.get("given", "")).replace(".", "").split()
        if not given or len(given) != len(actual):
            return False, "Missing or incomplete given names"
        for a, b in zip(given, actual):
            # Initials are allowed only when explicitly supplied by the citation;
            # do not collapse two conflicting full names or omit middle initials.
            if a != b and not (len(a) == 1 and b.startswith(a)):
                return False, "Author given names differ"
    return (
        True,
        "Complete author list in order; citation initials agree with source names",
    )


def compare_record(fields, record):
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
    check("title", titles, True)
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
        check(field, record.get(source), kind == "book" and field == "publisher")
    check(
        "pages",
        record.get("page") or record.get("article-number"),
        transform=normalize_pages,
    )
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
    if not isinstance(relation, dict) or set(relation) - BENIGN_RELATIONS:
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
            evidence, issues = compare_record(fields, record)
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
                    "schema": 1,
                    "policy": POLICY,
                    "created_at": now(),
                    "entries": len(results),
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
            or header.get("schema") != 1
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
        if result["status"] == "metadata_verified" and not any(
            c.get("source") == "crossref"
            and c.get("evidence")
            and c.get("issues") == []
            for c in result.get("candidates", [])
        ):
            raise ValueError("Machine approval is missing its source evidence")
        seen.add(result["key"])
    count = 0
    with cache.db:
        for result in records:
            entry = entries.get(result["key"])
            if (
                entry
                and entry["fingerprint"] == result["fingerprint"]
                and result["status"] != "pending"
                and not cache.get(filename, entry)
            ):
                cache.db.execute(
                    """INSERT INTO reviews
                    (bibliography,key,fingerprint,policy,result) VALUES (?,?,?,?,?)""",
                    (
                        str(Path(filename).resolve()),
                        entry["key"],
                        entry["fingerprint"],
                        POLICY,
                        dumps(result),
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
):
    validate_output_path(filename, report, cache)
    if snapshot:
        validate_output_path(filename, snapshot, cache)
    completed = 0
    with run_lock(cache, wait=wait):
        entries = load_entries(filename)  # may have changed while waiting for a runner
        try:
            for key, entry in entries.items():
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
