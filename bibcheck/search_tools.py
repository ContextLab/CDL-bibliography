"""Bounded source search for model research; snippets never verify citations."""

from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from research import allowed_url

CACHE_VERSION = "2"


class SourceHTTPError(ValueError):
    def __init__(self, status, retry_after=None):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"Source lookup HTTP {status}")


def get_source(session, url, hosts, https_redirect_hosts=(), max_redirects=3, **kwargs):
    """Fetch public source data without credentials, with checked redirects."""
    if not isinstance(max_redirects, int) or not 0 <= max_redirects <= 8:
        raise ValueError("Source redirect limit must be between zero and eight")
    for _ in range(max_redirects + 1):
        allowed_url(url, hosts)
        time.sleep(1)
        with session.get(
            url,
            timeout=(5, 15),
            stream=True,
            allow_redirects=False,
            headers={"User-Agent": "bibcheck/2.0 citation source research"},
            **kwargs,
        ) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get("Location", ""))
                # Some DOI records still supply legacy HTTP publisher links.
                # Request HTTPS directly on explicitly named publisher hosts;
                # never transmit a request over HTTP or upgrade arbitrary URLs.
                target = urlparse(url)
                if (target.scheme == "http" and target.hostname in https_redirect_hosts
                        and not target.username and not target.password and target.port in (None, 80)):
                    url = target._replace(scheme="https", netloc=target.hostname).geturl()
                kwargs = {}
                continue
            if response.status_code != 200:
                raise SourceHTTPError(
                    response.status_code, response.headers.get("Retry-After")
                )
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise ValueError("Source metadata exceeds 2 MB")
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8"), url
    raise ValueError("Too many source redirects")


class DuckDuckGoResults(HTMLParser):
    """Parse the public HTML interface, not the Instant Answer API."""

    def __init__(self):
        super().__init__()
        self.results = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "result__a" in attrs.get("class", "").split():
            href = urljoin("https://html.duckduckgo.com/", attrs.get("href", ""))
            parsed = urlparse(href)
            if parsed.hostname in {"duckduckgo.com", "html.duckduckgo.com"}:
                href = parse_qs(parsed.query).get("uddg", [""])[0]
            self.current = {"url": href, "title": "", "pdf_url": None}

    def handle_data(self, data):
        if self.current is not None:
            self.current["title"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            if urlparse(self.current["url"]).scheme == "https":
                self.results.append(self.current)
            self.current = None


class WebSearch:
    """Explicit backend, three-second pacing, seven-day persistent query cache."""

    def __init__(
        self, backend="europepmc", cache_path=".bibcheck/search.sqlite3", session=None
    ):
        if backend not in {"duckduckgo", "europepmc"}:
            raise ValueError("Search backend must be duckduckgo or europepmc")
        self.backend = backend
        self.session = session or requests.Session()
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS searches (backend TEXT, query TEXT, at REAL, result TEXT, PRIMARY KEY (backend, query))"
        )

    def close(self):
        self.db.close()

    def search(self, query):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            raise ValueError("Search query must have 1-500 characters")
        query = query.strip()
        cache_backend = self.backend + ":" + CACHE_VERSION
        cached = self.db.execute(
            "SELECT at, result FROM searches WHERE backend=? AND query=?",
            (cache_backend, query),
        ).fetchone()
        if cached and time.time() - cached[0] < 7 * 86400:
            return dict(json.loads(cached[1]), cached=True)
        time.sleep(3)
        if self.backend == "duckduckgo":
            html, _ = get_source(
                self.session,
                "https://html.duckduckgo.com/html/",
                ["html.duckduckgo.com"],
                params={"q": query},
            )
            if any(
                marker in html.lower()
                for marker in ("anomaly.js", "challenge-form", "bots use duckduckgo")
            ):
                raise ValueError(
                    "DuckDuckGo challenge; stopped without bypass or retry"
                )
            parser = DuckDuckGoResults()
            parser.feed(html)
            results = parser.results[:5]
            if not results and "no-results" not in html:
                raise ValueError(
                    "Unrecognized DuckDuckGo response; not treated as no matches"
                )
        else:
            raw, _ = get_source(
                self.session,
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                ["www.ebi.ac.uk"],
                params={
                    "query": query,
                    "format": "json",
                    "resultType": "core",
                    "pageSize": 5,
                },
            )
            body = json.loads(raw)
            if "hitCount" not in body or "resultList" not in body:
                raise ValueError("Malformed Europe PMC search response")
            results = []
            for record in body["resultList"].get("result", []):
                links = record.get("fullTextUrlList", {}).get("fullTextUrl", [])
                pdfs = [
                    v["url"]
                    for v in links
                    if v.get("documentStyle", "").lower() == "pdf" and v.get("url")
                ]
                results.append(
                    {
                        "url": "https://europepmc.org/article/"
                        + record.get("source", "MED")
                        + "/"
                        + record["id"],
                        "title": record.get("title", ""),
                        "doi": record.get("doi"),
                        "authors": record.get("authorString"),
                        "year": record.get("pubYear"),
                        "pdf_url": pdfs[0] if pdfs else None,
                        "pdf_urls": pdfs[:5],
                    }
                )
        result = {
            "backend": self.backend,
            "query": query,
            "retrieved_at": time.time(),
            "results": results,
            "cached": False,
        }
        self.db.execute(
            "INSERT OR REPLACE INTO searches VALUES (?,?,?,?)",
            (cache_backend, query, time.time(), json.dumps(result)),
        )
        self.db.commit()
        return result
