"""A chapter record with two container titles: which one is the book's.

Crossref gives some chapters a series title and a book title, in no stated order
(``["Lecture Notes in Statistics", "Nonlinear Estimation and Classification"]``). The book
title of the entry is one of the two, and this module only ever chooses between them: no
other string can come out of it.

The choice is looked for in this order (owner's decision 2026-10-06, docs/decision-log.md):

1. the book's own Crossref record, found by the chapter's ISBNs: a record of a book type
   whose title is one of the two titles;
2. the book's Library of Congress record, found by the same ISBNs (the client and cache of
   the catalogue check): its transcribed title is one of the two titles;
3. a model reading of the chapter's own page at its publisher (the page its DOI resolves
   to, when that is on one of the publisher hosts this package fetches from, ``PAGE_HOSTS``): the ``extract`` phase of the research adapter names the book title with the lines of
   the page it read it from, and the choice is taken only when that title is one of the two
   and a quoted line literally contains it without the other.

Steps 1 and 2 decide by records. Step 3 is a model-assisted choice: it is marked as one, the
proposal then needs the person's decision, and it is never a verification or an approval
(the built entry is checked by the verifier like any other). Step 3 runs only when a model
route is set up, is announced before it runs, and is not run when the person asked to be
asked first (``--ask``) and has not said yes. A saved page and reading are read again
without a request; they are judged again each time, never trusted as a stored answer.
"""
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
import html
import json
import re
from urllib.parse import urlparse

from .verification import ProviderError, normalize_title, normalized, now

BOOK_TYPES = ("book", "edited-book", "monograph", "reference-book")
WORKS = "https://api.crossref.org/works"
PAGE_TTL = 30 * 86400
READING_TTL = 365 * 86400
MAX_LINES = 150           # lines of a page a model is given
MAX_PAGE_LINES = 5000     # lines kept of a page while it is parsed; the rest is not read
PAGE_REDIRECTS = 6        # hops followed from doi.org to the page
PAGE_SECONDS = 120        # the whole fetch of the page, all hops together
RESOLVE_SECONDS = 900     # the whole resolution of one record (the adapter has its own 600 s limit)
# The hosts a chapter's page is fetched from: the publisher hosts this package already
# fetches DOI landing pages from (publisher_corrections.ISSUE_HEAD_HOSTS), fixed in the code.
# doi.org only redirects; a redirect to any other host ends the fetch.
from .publisher_corrections import ISSUE_HEAD_HOSTS  # noqa: E402
PAGE_HOSTS = frozenset(ISSUE_HEAD_HOSTS)
HOW = ("To have a model read the publisher's page for it, set up a model route (`cdlbib setup` "
       "lists them; Dartmouth Chat is the default) and run the lookup again.")


@dataclass
class Resolution:
    """What was found out about a record's two container titles. ``chosen``: the book's
    title (one of ``titles``, byte for byte) or None. ``by``: "crossref-book-record",
    "loc-catalogue" or "model". ``sentence``: what decided it, for a person. ``reason``: why
    nothing was chosen. ``evidence``: the record of the choice (identifiers, the URL and the
    quotation for a model reading). ``question``: set when a model could be asked and the
    person asked to be asked first."""
    titles: tuple
    chosen: str | None = None
    by: str | None = None
    sentence: str | None = None
    reason: str | None = None
    evidence: dict = field(default_factory=dict)
    question: str | None = None

    @property
    def other(self):
        return next((t for t in self.titles if t != self.chosen), None) if self.chosen else None

    @property
    def model_assisted(self):
        return self.by == "model"


def two_titles(record):
    """The two container titles of a chapter record that has exactly two different ones;
    None for any other record."""
    if not isinstance(record, dict) or record.get("type") != "book-chapter":
        return None
    venues = record.get("container-title")
    if not isinstance(venues, list) or not all(isinstance(v, str) for v in venues):
        return None
    venues = [" ".join(v.split()) for v in venues if v.strip()]
    if len(venues) != 2 or _key(venues[0]) == _key(venues[1]) or not all(_key(v) for v in venues):
        return None
    return tuple(venues)


def _key(text):
    try:
        return normalize_title(html.unescape(str(text or "")))
    except ValueError:
        return ""


def _isbns(record):
    found = []
    for value in record.get("ISBN") or []:
        digits = re.sub(r"[\s-]", "", str(value)).upper()
        if re.fullmatch(r"\d{9}[\dX]|\d{13}", digits) and digits not in found:
            found.append(digits)
    return found[:4]


def decide(titles, book_names):
    """The one of ``titles`` that is among ``book_names`` (titles a source gives the book),
    when the other is not; else None."""
    names = {_key(n) for n in book_names if _key(n)}
    hits = [t for t in titles if _key(t) in names]
    return hits[0] if len(hits) == 1 else None


def crossref_books(client, record):
    """The one lookup of a chapter's book at Crossref: for each of the chapter's ISBNs, the
    records of a book type (never a series: ``BOOK_TYPES``) that carry that ISBN, as
    ``(isbn, item, names, response)``; ``names`` is the record's title, with and without its
    subtitle."""
    for isbn in _isbns(record):
        response = client.get(WORKS, {"filter": f"isbn:{isbn}," + ",".join("type:" + t for t in BOOK_TYPES), "rows": 5})
        items = (response.get("body") or {}).get("message", {}).get("items", [])
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or item.get("type") not in BOOK_TYPES:
                continue
            own = [re.sub(r"[\s-]", "", str(v)).upper() for v in item.get("ISBN") or []]
            if isbn not in own:
                continue
            names = [t for t in item.get("title") or [] if isinstance(t, str)]
            subtitles = [t for t in item.get("subtitle") or [] if isinstance(t, str)]
            if len(names) == 1 and len(subtitles) == 1:
                names.append(names[0] + ": " + subtitles[0])
            yield isbn, item, names, response


def catalogue_books(client, cache, record):
    """The one lookup of a chapter's book in the Library of Congress catalogue: for each of
    the chapter's ISBNs, the records with that ISBN, as ``(isbn, xml, whole title, found)``."""
    from .book_build import record_title
    from .catalogue_discovery import fetch_query, identifier_query
    for isbn in _isbns(record):
        found = fetch_query(cache, client, identifier_query("isbn", isbn))
        for xml in found["records"]:
            yield isbn, xml, record_title(xml), found


def from_crossref(client, record, titles):
    """Step 1: a Crossref record of a book type that carries one of the chapter's ISBNs and
    whose title (with or without its subtitle) is one of the two titles."""
    if True:
        for isbn, item, names, response in crossref_books(client, record):
            chosen = decide(titles, names)
            if chosen:
                other = next(t for t in titles if t != chosen)
                series = [v for v in item.get("container-title") or [] if isinstance(v, str)]
                agrees = bool(decide((other,), series))
                return Resolution(titles, chosen, "crossref-book-record", sentence=(
                    f"The book's own Crossref record ({item.get('DOI')}, ISBN {isbn}) has the title "
                    f"\"{names[0]}\"" + (f" and names \"{other}\" as its series" if agrees else "") + "."),
                    evidence={"source": "crossref", "doi": item.get("DOI"), "isbn": isbn, "type": item.get("type"),
                              "title": names[0], "series": series, "retrieved_at": response.get("retrieved_at")})
    return None


def from_catalogue(client, cache, record, titles):
    """Step 2: a Library of Congress record with one of the chapter's ISBNs whose transcribed
    title (with or without its subtitle) is one of the two titles."""
    import xml.etree.ElementTree as ET
    from .book_build import summary
    from .catalogue_discovery import M
    if True:
        for isbn, xml, whole, found in catalogue_books(client, cache, record):
            chosen = decide(titles, [whole, whole.split(":")[0]])
            if not chosen:
                continue
            other = next(t for t in titles if t != chosen)
            root = ET.fromstring(xml)
            series = [(n.text or "").strip().rstrip(" ;,.") for tag in ("490", "830")
                      for f in root.findall(M + f"datafield[@tag='{tag}']")
                      for n in f.findall(M + "subfield[@code='a']")]
            agrees = bool(decide((other,), series))
            lead = summary(xml)
            return Resolution(titles, chosen, "loc-catalogue", sentence=(
                f"The book's Library of Congress record (LCCN {lead['lccn']}, ISBN {isbn}) has the title "
                f"\"{whole}\"" + (f" and names \"{other}\" as its series" if agrees else "") + "."),
                evidence={"source": "loc-catalogue", "lccn": lead["lccn"], "record_id": lead["record_id"],
                          "isbn": isbn, "title": whole, "series": series, "url": found["url"],
                          "document_sha256": found["document_sha256"], "retrieved_at": found["retrieved_at"]})
    return None


# --- the editors of a chapter's book ----------------------------------------------------------------
#
# Owner's decision 2026-10-06: a chapter's editors come from the BOOK's record. A chapter's own
# Crossref record hardly ever names them. The book's record is the one the two steps above
# find: a Crossref record of a book type, then a Library of Congress record, with one of the
# chapter's ISBNs, whose title is one of the chapter record's container titles. A series has
# no record of a book type and no ISBN of the chapter's, so a series' editors are never taken.

BOOK_RECORD = "book-record"    # the key under which what was found is kept in the chapter's record


def _people(people):
    return [{k: str(p.get(k) or "") for k in ("given", "family", "name", "suffix") if p.get(k)}
            for p in people or [] if isinstance(p, dict)]


def same_people(one, two):
    """Whether two sources' lists name the same people in the same order, by the rule a
    citation's byline is compared with a source's (``verification.author_evidence``): the
    shorter given names of each pair are taken as the citation's."""
    from .correction_proposals import house_byline
    from .verification import author_evidence
    if len(one) != len(two):
        return False
    try:
        return author_evidence(house_byline(one), two)[0] or author_evidence(house_byline(two), one)[0]
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def book_editors(record, client, cache=None):
    """What the book's own record says of the editors of the book a chapter is in: a dict
    kept in the chapter's record under ``BOOK_RECORD`` (``verification.compare_record``
    compares an entry's ``editor`` field with it when the chapter's record names no editor).

    ``editor``: the editors, complete and in order, when a record of the book names them and
    the records found do not disagree; else absent, with ``reason``. ``sources``: each record
    found (``source``, its identifier, ``isbn``, ``title``, ``editor``, ``retrieved_at``).
    None when ``record`` is no chapter's or names editors itself. Nothing is raised: a source
    that did not answer is a ``reason``."""
    if not isinstance(record, dict) or record.get("type") != "book-chapter" or record.get("editor"):
        return None
    venues = [" ".join(v.split()) for v in record.get("container-title") or [] if isinstance(v, str) and v.strip()]
    cache = cache if cache is not None else client.cache
    if not venues:
        return {"reason": "the chapter's record names no book, so the book's record cannot be looked up"}
    if not _isbns(record):
        return {"reason": "the chapter's record states no ISBN, so the book's record cannot be looked up"}
    sources, failed = [], []
    try:
        for isbn, item, names, response in crossref_books(client, record):
            title = decide(tuple(venues), names) if len(venues) > 1 else (venues[0] if decide((venues[0],), names) else None)
            if title:
                sources.append({"source": "crossref-book-record", "doi": item.get("DOI"), "isbn": isbn, "type": item.get("type"),
                                "title": names[0], "names": names, "editor": _people(item.get("editor")),
                                "retrieved_at": response.get("retrieved_at")})
                break
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        failed.append(f"Crossref did not answer ({exc})")
    try:
        from .book_build import summary
        from .catalogue_review import parse_edition
        for isbn, xml, whole, found in catalogue_books(client, cache, record):
            names = [whole, whole.split(":")[0]]
            title = decide(tuple(venues), names) if len(venues) > 1 else (venues[0] if decide((venues[0],), names) else None)
            if not title:
                continue
            try:
                people = _people(parse_edition(xml).get("editor"))
            except ValueError:
                people = []   # a record the catalogue check's grammar does not read names no one here
            lead = summary(xml)
            sources.append({"source": "loc-catalogue", "lccn": lead["lccn"], "isbn": isbn, "title": whole, "names": names,
                            "editor": people, "url": found["url"], "document_sha256": found["document_sha256"],
                            "retrieved_at": found["retrieved_at"]})
            break
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        failed.append(f"the Library of Congress catalogue did not answer ({exc})")
    found = {"sources": sources}
    naming = [s for s in sources if s["editor"]]
    if len(naming) == 2 and not same_people(naming[0]["editor"], naming[1]["editor"]):
        found["reason"] = ("the book's Crossref record and its Library of Congress record name different editors, "
                           "and neither is chosen")
        found["disagreement"] = True
    elif naming:
        found["editor"] = naming[0]["editor"]
        found["by"] = naming[0]["source"]
    elif failed:
        found["reason"] = "; ".join(failed) + "; the book's record could not be looked up"
    elif sources:
        found["reason"] = "the book's own record names no editors"
    else:
        found["reason"] = "no record of the book was found by the chapter's ISBN at Crossref or in the Library of Congress catalogue"
    return found


def valid_book_editors(record):
    """The editors of ``record[BOOK_RECORD]`` when that is evidence about this chapter's
    book: found by one of the chapter's own ISBNs, under a title that is one of the chapter
    record's container titles, with no disagreement recorded. Else None. Judged again every
    time the record is compared; nothing stored is trusted beyond this."""
    found = record.get(BOOK_RECORD) if isinstance(record, dict) else None
    if not isinstance(found, dict) or found.get("disagreement") or not isinstance(found.get("editor"), list):
        return None
    venues = tuple(v for v in record.get("container-title") or [] if isinstance(v, str))
    source = next((s for s in found.get("sources") or [] if isinstance(s, dict) and s.get("source") == found.get("by")), None)
    if (not source or source.get("editor") != found["editor"] or source.get("isbn") not in _isbns(record)
            or not any(decide((v,), [str(n) for n in source.get("names") or []]) for v in venues)):
        return None
    return found["editor"], source


# --- the publisher's page ---------------------------------------------------------------------------

class _PageText(HTMLParser):
    """The text of a page, a line per block, and its citation metadata (``<meta
    name="citation_...">``, as publishers print it for indexers) as lines of their own."""
    BLOCKS = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "td", "th", "section",
              "article", "header", "footer", "nav", "title", "dd", "dt", "dl", "main", "aside", "table", "span", "a"}
    SKIPPED = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.current, self.skipping, self.meta = [], [], 0, []

    def _end_line(self):
        text = " ".join("".join(self.current).split())
        if text and len(self.lines) < MAX_PAGE_LINES:
            self.lines.append(text[:500])
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIPPED:
            self.skipping += 1
        elif tag == "meta":
            named = dict(attrs)
            name, content = str(named.get("name") or named.get("property") or ""), str(named.get("content") or "")
            if (re.fullmatch(r"(?i)(?:citation_|dc\.|prism\.)[\w.]*title[\w.]*", name) and content.strip()
                    and len(self.meta) < 50):
                self.meta.append(f"meta {name}: " + " ".join(content.split()))
        elif tag in self.BLOCKS and tag not in ("span", "a"):
            self._end_line()

    def handle_endtag(self, tag):
        if tag in self.SKIPPED:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCKS and tag not in ("span", "a"):
            self._end_line()

    def handle_data(self, data):
        if not self.skipping and len(self.lines) < MAX_PAGE_LINES and sum(map(len, self.current)) < 4000:
            self.current.append(data[:4000])


def page_lines(markup):
    """The lines of an HTML page: its citation metadata first, then its text."""
    parser = _PageText()
    parser.feed(markup)
    parser.close()
    parser._end_line()
    return [line[:500] for line in parser.meta + parser.lines]


def _mentions(line, title):
    try:
        return bool(re.search(r"(?<!\w)" + re.escape(normalized(html.unescape(title))) + r"(?!\w)", normalized(line)))
    except ValueError:
        return False


def lines_about(lines, titles, around=2, limit=MAX_LINES):
    """The lines that mention one of the two titles, each with the ``around`` lines before
    and after it, in page order, at most ``limit``: what a model is given to read. Empty
    when the page mentions neither."""
    keep = set()
    for index, line in enumerate(lines):
        if any(_mentions(line, t) for t in titles):
            keep.update(range(max(0, index - around), min(len(lines), index + around + 1)))
    return [lines[i] for i in sorted(keep)][:limit]


class UnsafeURL(ValueError):
    """A URL that is not fetched: the message says why and repeats nothing of the URL."""


def checked_url(url, resolve=True):
    """``url`` in the one form that is fetched, or ``UnsafeURL``. HTTPS only; no user name or
    password; port 443 or none; no backslash, white space or control character anywhere; the
    host in lower case without a final dot, in IDNA form, never an IP address, and one of
    ``PAGE_HOSTS`` exactly (a fixed list in the code: nothing a record or a model says adds to
    it). The two URL parsers in use (``urllib.parse``, which validates elsewhere in this
    package, and urllib3's, which ``requests`` connects by) must name the same host. With
    ``resolve``, every address the host resolves to must be a public one. Returned is the URL
    rebuilt from the checked parts, so what was checked is what is asked for."""
    import ipaddress
    import socket
    from urllib3.util import parse_url
    from urllib3.exceptions import LocationParseError
    if not isinstance(url, str) or not url or len(url) > 2000:
        raise UnsafeURL("not a URL of usable length")
    if any(ord(c) < 0x21 or ord(c) == 0x7f or c == "\\" for c in url):
        raise UnsafeURL("a backslash, white space or control character in the URL")
    try:
        one, two = urlparse(url), parse_url(url)
        port = one.port
    except (ValueError, LocationParseError):
        raise UnsafeURL("the URL cannot be parsed") from None
    if one.scheme != "https" or two.scheme != "https":
        raise UnsafeURL("not an HTTPS URL")
    if one.username is not None or one.password is not None or two.auth is not None or "@" in one.netloc:
        raise UnsafeURL("a user name or password in the URL")
    if port not in (None, 443) or two.port not in (None, 443):
        raise UnsafeURL("a port other than 443")
    host = (one.hostname or "").lower().rstrip(".")
    if not host or host != (two.host or "").lower().strip("[]").rstrip("."):
        raise UnsafeURL("the URL's host is read in two ways")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeURL("an IP address in place of a host name")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise UnsafeURL("a host name that is not a valid one") from None
    if host not in PAGE_HOSTS:
        raise UnsafeURL("a host that is not one of the publisher hosts this package fetches from")
    if resolve:
        try:
            found = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            raise UnsafeURL("the host name does not resolve") from None
        if not found or any(not public_address(item[4][0]) for item in found):
            raise UnsafeURL("the host resolves to an address that is not a public one")
    rest = (one.path or "/") + ("?" + one.query if one.query else "")
    return "https://" + host + rest


def public_address(text):
    """Whether an IP address is one on the public internet (not private, loopback, link-local,
    multicast, reserved or unspecified, in either family, IPv4-mapped forms included)."""
    import ipaddress
    try:
        address = ipaddress.ip_address(str(text).split("%")[0])
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    address = mapped or address
    return address.is_global and not (address.is_private or address.is_loopback or address.is_link_local
                                      or address.is_multicast or address.is_reserved or address.is_unspecified)


class _CheckedSession:
    """A ``requests`` session that asks for nothing ``checked_url`` refuses. The fetcher
    (``search_tools.get_source``) calls ``get`` once per hop with redirects off, so every hop,
    the first and each redirect target, is checked here in the form it is asked for."""

    def __init__(self, session, deadline):
        self.session, self.deadline, self.asked = session, deadline, []

    def get(self, url, **options):
        import time
        if time.monotonic() > self.deadline:
            raise UnsafeURL("the time allowed for reading the page is over")
        if options.get("allow_redirects") is not False or options.get("params"):
            raise UnsafeURL("a request that would not be checked hop by hop")
        url = checked_url(url)
        self.asked.append(url)
        return self.session.get(url, **options)


def fetch_page(doi, session=None, deadline=None):
    """The page the chapter's DOI resolves to, as ``{"url", "lines", "document_sha256",
    "retrieved_at"}``; ``ValueError`` when it cannot be read.

    The fetcher is the package's own (``search_tools.get_source``, as
    ``publisher_corrections`` uses it): redirects are followed by hand, at most
    ``PAGE_REDIRECTS``, the body is read as a stream and given up at two megabytes, each
    request has its own timeouts, and no credentials are sent. Every hop is asked for only
    after ``checked_url`` accepts it (``_CheckedSession``); the hosts are ``PAGE_HOSTS``, a
    fixed list. Nothing of the record but its DOI goes into the first URL."""
    import time
    from urllib.parse import quote
    import requests
    from .search_tools import SourceHTTPError, get_source
    deadline = deadline if deadline is not None else time.monotonic() + PAGE_SECONDS
    guarded = _CheckedSession(session or requests.Session(), deadline)
    try:
        markup, url = get_source(guarded, "https://doi.org/" + quote(doi, safe="/"), sorted(PAGE_HOSTS),
                                 max_redirects=PAGE_REDIRECTS,
                                 https_redirect_hosts=sorted(PAGE_HOSTS - {"doi.org", "dx.doi.org"}))
    except UnsafeURL as exc:
        raise ValueError(f"the page is not fetched: {exc}") from None
    except requests.RequestException as exc:
        raise ValueError(f"the page could not be fetched ({type(exc).__name__})") from None
    except SourceHTTPError as exc:
        raise ValueError(f"the page answered HTTP {int(exc.status)}") from None
    except ValueError as exc:       # too many redirects, a body over the limit, or a hop to a host outside the list
        outside = "explicitly allowed host" in str(exc)        # research.allowed_url's refusal (it repeats the URL)
        raise ValueError("the DOI leads to a host that is not one of the publisher hosts this package fetches from"
                         if outside else "the page redirects too often or is larger than 2 MB") from None
    return {"url": checked_url(url, resolve=False), "lines": page_lines(markup),
            "document_sha256": hashlib.sha256(markup.encode("utf-8")).hexdigest(), "retrieved_at": now()}


def pages_for(page, titles):
    """What the adapter is given: one page holding the lines about the two titles."""
    lines = lines_about(page["lines"], titles)
    return [{"page": 1, "text": "\n".join(lines) + "\n"}] if lines else []


def choice_from_reading(titles, pages, extracted):
    """The book title a model reading supports, as ``(title, quotation)``; ``ValueError``
    with the reason when it supports none. The reading (``research`` adapter, ``extract``
    phase) is of exactly ``pages``; its ``booktitle`` must be one of the two titles and
    nothing else, its passages must be the lines of ``pages`` they say they are, at least one
    of those lines must literally contain the chosen title and not the other, and none may
    contain the other title without the chosen one (a line that cites the book with its
    series holds both and decides nothing). The quotation returned is the lines that hold
    the chosen title alone; the title returned is the registry's string, never the model's."""
    if not isinstance(extracted, dict) or not isinstance(extracted.get("fields"), dict):
        raise ValueError("the reading is not in the expected form")
    expected = hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if extracted.get("source_text_sha256") != expected:
        raise ValueError("the reading is of another text than the page's lines")
    found = extracted["fields"].get("booktitle")
    if not isinstance(found, dict) or not isinstance(found.get("value"), str):
        raise ValueError("the model named no book title on the page")
    chosen = decide(titles, [found["value"]])
    if not chosen:
        raise ValueError("the book title the model named is not one of the record's two titles")
    other = next(t for t in titles if t != chosen)
    text = {p["page"]: p["text"] for p in pages}
    quotes = []
    for passage in found.get("passages") or []:
        try:
            quote = text[passage["page"]][passage["start"]:passage["end"]]
        except (KeyError, TypeError):
            raise ValueError("the reading's passages are not lines of the page") from None
        if not quote.strip() or quote != passage.get("quote"):
            raise ValueError("the reading's passages are not lines of the page")
        quotes.append(quote.strip())
    if not quotes or found.get("grounding") != "literal_text_present":
        raise ValueError("the model's book title is not literally on the lines it selected")
    if found.get("role_risk"):
        raise ValueError("the lines the model selected may not state the work's own book title ("
                         + ", ".join(str(r) for r in found["role_risk"]) + ")")
    alone = [q for q in quotes if _mentions(q, chosen) and not _mentions(q, other)]
    if not alone:
        raise ValueError("no quoted line contains the chosen title without the other, so the lines do not say "
                         "which is the book's")
    if any(_mentions(q, other) and not _mentions(q, chosen) for q in quotes):
        raise ValueError("a quoted line gives the other title as the book's")
    return chosen, " / ".join(dict.fromkeys(alone))


def _route(environ=None):
    """The first model route that is set up ("dartmouth", then "openai") and its label, or
    (None, None). The stored key of each is looked up, as the adapter will (``environ``: an
    explicit configuration to read in place of the process environment and the keychain)."""
    from . import intake
    for route in intake.model_routes(probe=("dartmouth", "openai"), environ=environ):
        if route.available:
            return route.name, route.label
    return None, None


def _saved(cache, doi, titles):
    """(page, pages, reading) from the response cache, as far as they are saved."""
    page = cache.response("book-title-page-v1:" + doi, PAGE_TTL)
    if page is None:
        return None, None, None
    pages = pages_for(page, titles)
    digest = hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return page, pages, cache.response("book-title-reading-v1:" + digest, READING_TTL)


def from_model(client, cache, record, titles, announce=None, allow_model=None, environ=None):
    """Step 3. Returns a ``Resolution``: chosen with ``by`` "model", or not chosen with the
    ``reason`` (and ``question`` when the person is to be asked first)."""
    from . import deps
    from .research import INSTRUCTIONS, invoke_adapter
    from .verification import normalize_doi
    try:
        doi = normalize_doi(record.get("DOI"))
    except (ValueError, TypeError, AttributeError):
        return Resolution(titles, reason="the record has no usable DOI to find the publisher's page by")
    page, pages, reading = _saved(cache, doi, titles)
    route = (reading or {}).get("route")
    if reading is None:
        if allow_model is False:
            return Resolution(titles, reason="a model was not asked: it was declined")
        route, label = _route(environ)
        if not route:
            return Resolution(titles, reason="no model route is set up, so no model was asked. " + HOW)
        question = (f"The record of {record.get('DOI')} names two titles (\"{titles[0]}\" and \"{titles[1]}\") and "
                    f"no record says which is the book's. Ask {label} to read the publisher's page for it "
                    "(one request; it can take a few minutes)?")
        if deps.ask() and allow_model is not True:
            return Resolution(titles, question=question,
                              reason="a model can be asked, and was not: you asked to be asked first (--ask)")
        if announce:
            announce(f"{record.get('DOI')}: two container titles and no record that says which is the book's; "
                     f"asking {label} to read the publisher's page (one request; it can take a few minutes)")
        if page is None:
            try:
                page = fetch_page(doi)
            except ValueError as exc:
                return Resolution(titles, reason=f"the publisher's page could not be read ({exc}), so no model was asked")
            cache.save_response("book-title-page-v1:" + doi, page)
            pages = pages_for(page, titles)
        if not pages:
            return Resolution(titles, reason=f"the publisher's page ({page['url']}) gives no text that names "
                                             "either title (some publishers' pages cannot be read by a program), "
                                             "so no model was asked")
        from .intake import _adapter
        try:
            extracted = invoke_adapter(_adapter(route), {"phase": "extract", "instructions": INSTRUCTIONS,
                                                         "entry": {}, "pages": pages})
        except ValueError as exc:
            return Resolution(titles, reason=f"{label} did not return a reading ({exc})")
        reading = {"route": route, "extracted": extracted, "retrieved_at": now()}
        cache.save_response("book-title-reading-v1:" + extracted.get("source_text_sha256", ""), reading)
    if not pages:
        return Resolution(titles, reason=f"the publisher's page ({page['url']}) names neither title")
    try:
        chosen, quote = choice_from_reading(titles, pages, reading.get("extracted"))
    except ValueError as exc:
        return Resolution(titles, reason=f"a model read the publisher's page ({page['url']}) and its reading "
                                         f"does not decide it: {exc}")
    trace = (reading.get("extracted") or {}).get("provider_trace") or {}
    return Resolution(titles, chosen, "model", sentence=(
        f"Model-assisted choice ({route}{', ' + str(trace.get('model')) if trace.get('model') else ''}): on the "
        f"publisher's page {page['url']} the book title was read from the line \"{quote}\". "
        "This is not a verification."),
        evidence={"source": "model", "route": route, "model": trace.get("model"), "url": page["url"],
                  "quote": quote, "document_sha256": page["document_sha256"],
                  "page_retrieved_at": page["retrieved_at"], "read_at": reading.get("retrieved_at")})


def resolve(record, client, cache=None, announce=None, allow_model=None, environ=None):
    """What can be found out about ``record``'s two container titles (None when it does not
    have exactly two). The record steps come first; the model step only when both answered
    and neither decides: a record source that did not answer is said in ``reason`` and no
    model is asked in its place. Nothing is raised."""
    titles = two_titles(record)
    if titles is None:
        return None
    import time
    cache = cache if cache is not None else client.cache
    started, failed = time.monotonic(), []
    for name, step in (("Crossref", lambda: from_crossref(client, record, titles)),
                       ("the Library of Congress catalogue", lambda: from_catalogue(client, cache, record, titles))):
        try:
            found = step()
        except (ProviderError, ValueError, KeyError, TypeError) as exc:
            failed.append(f"{name} did not answer ({exc})")
            continue
        if found:
            return found
    if time.monotonic() - started > RESOLVE_SECONDS:
        failed.append("the record lookups took longer than the time allowed")
    if failed:
        return Resolution(titles, reason="; ".join(failed) + "; the book's own record could not be looked up, "
                                         "and no model is asked in its place")
    found = from_model(client, cache, record, titles, announce=announce, allow_model=allow_model, environ=environ)
    if not found.chosen:
        found.reason = "no record of the book says which is its title; " + (found.reason or "")
    return found


def apply(proposal, resolution):
    """Record ``resolution`` on the proposal built from the record with the chosen title as
    its one container title: the source of the book title says how it was chosen, the
    sentence is a note, the evidence is kept in ``proposal.choices``, and a model-assisted
    choice makes the proposal need the person's decision. A resolution that chose nothing
    extends the reason of the unfilled book title."""
    from .complete import FieldChange, Unfilled
    if resolution is None:
        return proposal
    if not resolution.chosen:
        proposal.unfilled = [Unfilled(u.field, u.reason + ": " + resolution.reason.rstrip(".")
                                      + ". The book title is left unfilled: type it in", u.source_values)
                             if u.field == "booktitle" and resolution.reason else u for u in proposal.unfilled]
        if resolution.question:
            proposal.choices.append({"field": "booktitle", "by": None, "titles": list(resolution.titles),
                                     "question": resolution.question})
        return proposal
    label = {"crossref-book-record": "crossref (the book's own Crossref record)",
             "loc-catalogue": "crossref (the book's Library of Congress record)",
             "model": "crossref (model-assisted choice)"}[resolution.by]
    proposal.changes = [FieldChange(c.field, c.typed, c.proposed, label if c.source == "crossref" else c.source, c.kind)
                        if c.field == "booktitle" else c for c in proposal.changes]
    said = (f"booktitle: the record names two titles, \"{resolution.titles[0]}\" and \"{resolution.titles[1]}\"; "
            f"\"{resolution.chosen}\" is taken as the book's. " + resolution.sentence)
    proposal.choices.append(dict(resolution.evidence, field="booktitle", by=resolution.by,
                                 chosen=resolution.chosen, other=resolution.other,
                                 model_assisted=resolution.model_assisted))
    if resolution.model_assisted:
        proposal.issues.append(said + " Check the title against the page before accepting.")
        proposal.needs_decision = True
    else:
        proposal.notes.append(said)
    return proposal
