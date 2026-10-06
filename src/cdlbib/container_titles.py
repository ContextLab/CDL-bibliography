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
PAGE_KEY = "book-title-page-v1:"      # the response-cache key of a fetched page, before the DOI
READING_TTL = 365 * 86400
MAX_LINES = 150           # lines of a page a model is given
MAX_PAGE_LINES = 5000     # lines kept of a page while it is parsed; the rest is not read
LINE_CHARS = 500          # characters kept of one block of a page; a line this long was cut
PAGE_REDIRECTS = 6        # hops followed from doi.org to the page
PAGE_SECONDS = 120        # the whole fetch of the page, all hops together
RESOLVE_SECONDS = 900     # the whole resolution of one record (the adapter has its own 600 s limit)
PAGE_BYTES = 2_000_000    # the most one hop of a page fetch may send
RECORD_BYTES = 4_000_000  # the most a record source (Crossref, the catalogue) may send in one answer
# The hosts a chapter's page is fetched from: the publisher hosts this package already
# fetches DOI landing pages from (publisher_corrections.ISSUE_HEAD_HOSTS), fixed in the code.
# doi.org only redirects; a redirect to any other host ends the fetch.
from .publisher_corrections import ISSUE_HEAD_HOSTS  # noqa: E402
PAGE_HOSTS = frozenset(ISSUE_HEAD_HOSTS)
# Said with every model-assisted choice, in the proposal's issues and in its stored record,
# whatever the verifier's status is: the verifier accepts either of the record's two titles.
UNCONFIRMED = ("Model-assisted and unconfirmed: check the title against the page before accepting. The citation "
               "check accepts either of the record's two titles, so a status of metadata_verified does not confirm "
               "this choice.")
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
    if len(venues) != 2 or not all(_key(v) for v in venues) or same_title(venues[0], venues[1]):
        return None
    return tuple(venues)


def _key(text):
    """A title as the verifier reads a book title (``verification.normalized``, the transform
    ``compare_record`` gives the ``booktitle`` field); "" for one it does not read."""
    try:
        return normalized(str(text or ""))
    except ValueError:
        return ""


def title_is(cited, source):
    """Whether ``cited`` is the book title ``source``, by the verifier's own rule for a cited
    book title against a record's (``compare_record``: equal as ``verification.normalized``
    reads them, or equal once the record's series number or volume-pack tail is taken off,
    ``verification.book_title_forms``). Every "is this title that title" of this module is
    this function; nothing here compares titles in another way."""
    from .verification import book_title_forms
    target = _key(cited)
    return bool(target) and target in {_key(source), _key(book_title_forms(str(source or "")))}


def same_title(one, two):
    """``title_is`` either way round: for two titles of which neither is the citation's."""
    return title_is(one, two) or title_is(two, one)


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
    hits = [t for t in titles if any(same_title(t, name) for name in book_names)]
    return hits[0] if len(hits) == 1 else None


def crossref_books(client, record):
    """The one lookup of a chapter's book at Crossref: for each of the chapter's ISBNs, the
    records of a book type (never a series: ``BOOK_TYPES``) that carry that ISBN, as
    ``(isbn, item, names, response)``; ``names`` is the record's title, with and without its
    subtitle."""
    from .book_build import same_isbn
    for isbn in _isbns(record):
        response = client.get(WORKS, {"filter": f"isbn:{isbn}," + ",".join("type:" + t for t in BOOK_TYPES), "rows": 5})
        items = (response.get("body") or {}).get("message", {}).get("items", [])
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or item.get("type") not in BOOK_TYPES:
                continue
            own = [re.sub(r"[\s-]", "", str(v)).upper() for v in item.get("ISBN") or [] if isinstance(v, str)]
            if not any(same_isbn(isbn, value) for value in own):
                continue
            names = [t for t in item.get("title") or [] if isinstance(t, str)]
            subtitles = [t for t in item.get("subtitle") or [] if isinstance(t, str)]
            if len(names) == 1 and len(subtitles) == 1:
                names.append(names[0] + ": " + subtitles[0])
            yield isbn, item, names, response


def catalogue_books(client, cache, record):
    """The one lookup of a chapter's book in the Library of Congress catalogue: for each of
    the chapter's ISBNs, the records with that ISBN, as ``(isbn, xml, whole title, found)``."""
    from .book_build import matched_identifier, record_title
    from .catalogue_discovery import fetch_query, identifier_query
    for isbn in _isbns(record):
        found = fetch_query(cache, client, identifier_query("isbn", isbn))
        for xml in found["records"]:
            # An answer that echoes the query proves nothing: the record must state the ISBN itself.
            if matched_identifier(xml, isbn=isbn):
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
                              "matched": {"field": "ISBN", "value": [v for v in item.get("ISBN") or []
                                                                     if isinstance(v, str)], "asked": isbn},
                              "title": names[0], "series": series, "retrieved_at": response.get("retrieved_at")})
    return None


def from_catalogue(client, cache, record, titles):
    """Step 2: a Library of Congress record with one of the chapter's ISBNs whose transcribed
    title (with or without its subtitle) is one of the two titles."""
    import xml.etree.ElementTree as ET
    from .book_build import matched_identifier, summary
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
                          "isbn": isbn, "matched": matched_identifier(xml, isbn=isbn),
                          "title": whole, "series": series, "url": found["url"],
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
    """A source's list of people as plain dicts, or None when it is not a well-formed list:
    every member a dict that names someone (a family name, or a name). A list with anything
    else in it is no evidence at all: nothing is dropped from it to make it one."""
    if not isinstance(people, list):
        return None
    out = []
    for person in people:
        if not isinstance(person, dict) or any(
                person.get(k) is not None and not isinstance(person.get(k), str) for k in ("given", "family", "name", "suffix")):
            return None
        kept = {k: person[k] for k in ("given", "family", "name", "suffix") if person.get(k)}
        if not (kept.get("family") or kept.get("name")):
            return None
        out.append(kept)
    return out


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


def _crossref_source(item, isbn):
    """What a Crossref record of a book says, read from the record itself: its type (a book
    type, never a series), that it carries ``isbn``, its titles, and its editors (None for
    a malformed list). None when the record is not a book's with that ISBN."""
    from .book_build import same_isbn
    if not isinstance(item, dict) or item.get("type") not in BOOK_TYPES:
        return None
    if not any(same_isbn(isbn, re.sub(r"[\s-]", "", v).upper()) for v in item.get("ISBN") or [] if isinstance(v, str)):
        return None
    names = [t for t in item.get("title") or [] if isinstance(t, str)]
    subtitles = [t for t in item.get("subtitle") or [] if isinstance(t, str)]
    if len(names) == 1 and len(subtitles) == 1:
        names.append(names[0] + ": " + subtitles[0])
    editors = _people(item.get("editor")) if item.get("editor") is not None else []
    return {"names": names, "editor": editors, "type": item.get("type")}


def _catalogue_source(xml, isbn):
    """The same for a Library of Congress record (its MARC XML): it states ``isbn`` itself
    (020), its transcribed title, and the editors the catalogue check's grammar reads."""
    from .book_build import matched_identifier, record_title
    from .catalogue_review import parse_edition
    try:
        if not matched_identifier(xml, isbn=isbn):
            return None
        whole = record_title(xml)
    except (ValueError, TypeError):
        return None
    try:
        editors = _people(parse_edition(xml).get("editor") or [])
    except ValueError:
        editors = []      # a record the catalogue check's grammar does not read names no one here
    return {"names": [whole, whole.split(":")[0]], "editor": editors, "type": "book"}


def _is_title(booktitle, names):
    """Whether ``booktitle`` is one of ``names`` by the comparison used for the two titles."""
    return any(title_is(booktitle, name) for name in names)


def book_editors(record, client, cache=None):
    """What the book's own record says of the editors of the book a chapter is in: a dict
    kept in the chapter's record under ``BOOK_RECORD`` (``verification.compare_record``
    compares an entry's ``editor`` field with it when the chapter's record names no editor).

    Every record of the book that is found is kept, each with the source record itself
    (``record``: the Crossref item, or ``marcxml``), so that ``valid_book_editors`` reads the
    editors from the source again and never from a summary. ``editor`` is set only when the
    evidence is whole: every record found for one title that names editors names the same
    ones, no list is malformed, and Crossref did not hold back records (its answer listed
    every record it counted). Otherwise it is absent, with ``reason``. None when ``record``
    is no chapter's or names editors itself. Nothing is raised."""
    if not isinstance(record, dict) or record.get("type") != "book-chapter" or record.get("editor"):
        return None
    venues = [" ".join(v.split()) for v in record.get("container-title") or [] if isinstance(v, str) and v.strip()]
    cache = cache if cache is not None else client.cache
    if not venues:
        return {"reason": "the chapter's record names no book, so the book's record cannot be looked up"}
    if not _isbns(record):
        return {"reason": "the chapter's record states no ISBN, so the book's record cannot be looked up"}
    sources, failed, undecided = [], [], []

    def title_of(names):
        return decide(tuple(venues), names) if len(venues) > 1 else (venues[0] if decide((venues[0],), names) else None)

    # Each source is asked for every ISBN of the chapter (its print and electronic forms may
    # have records of their own), and every answer is read whole: every record that is the
    # book's, under any of the ISBNs, has to agree before the editors are taken.
    import time
    deadline = time.monotonic() + RESOLVE_SECONDS
    try:
        with within(client, deadline):
            for isbn in _isbns(record):
                response = client.get(WORKS, {"filter": f"isbn:{isbn}," + ",".join("type:" + t for t in BOOK_TYPES), "rows": 5})
                message = (response.get("body") or {}).get("message", {})
                listed = message.get("items") if isinstance(message.get("items"), list) else []
                for item in listed:
                    if isinstance(item, dict) and any(s_.get("doi") == item.get("DOI") for s_ in sources):
                        continue                  # the same record, found again under another ISBN
                    read = _crossref_source(item, isbn)
                    if read is None or not title_of(read["names"]):
                        continue
                    if read["editor"] is None:
                        undecided.append(f"the editor list of the Crossref record {item.get('DOI')} is not well formed")
                    sources.append({"source": "crossref-book-record", "doi": item.get("DOI"), "isbn": isbn, "type": read["type"],
                                    "title": read["names"][0], "names": read["names"], "booktitle": title_of(read["names"]),
                                    "editor": read["editor"] or [], "record": item,
                                    "retrieved_at": response.get("retrieved_at")})
                total = message.get("total-results")
                if isinstance(total, int) and total > len(listed):
                    undecided.append(f"Crossref counts {total} book records with the ISBN {isbn} and returned {len(listed)}")
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        failed.append(f"Crossref did not answer ({exc})")
    try:
        from .book_build import summary
        from .catalogue_discovery import fetch_query, identifier_query
        with within(client, deadline):
            for isbn in _isbns(record):
                found_ = fetch_query(cache, client, identifier_query("isbn", isbn))
                for xml in found_["records"]:
                    read = _catalogue_source(xml, isbn)
                    if read is None or not title_of(read["names"]):
                        continue
                    lead = summary(xml)
                    if any(s_.get("record_id") == lead["record_id"] for s_ in sources):
                        continue                  # the same record, found again under another ISBN
                    sources.append({"source": "loc-catalogue", "lccn": lead["lccn"], "record_id": lead["record_id"],
                                    "isbn": isbn, "type": "book", "title": read["names"][0], "names": read["names"],
                                    "booktitle": title_of(read["names"]), "editor": read["editor"] or [], "marcxml": xml,
                                    "url": found_["url"], "document_sha256": found_["document_sha256"],
                                    "retrieved_at": found_["retrieved_at"]})
                if found_["truncated"]:
                    undecided.append(f"the catalogue lists more records with the ISBN {isbn} than it returned")
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        failed.append(f"the Library of Congress catalogue did not answer ({exc})")
    found = {"sources": sources}
    naming = [s for s in sources if s["editor"]]
    titles = {_key(s["booktitle"]) for s in sources}
    if undecided:
        found["reason"] = "; ".join(undecided) + "; the editors are not taken from an incomplete answer"
        found["disagreement"] = True
    elif len(titles) > 1:
        found["reason"] = "the records found by the chapter's ISBN are of books with different titles, and none is chosen"
        found["disagreement"] = True
    elif any(not same_people(naming[0]["editor"], other["editor"]) for other in naming[1:]):
        found["reason"] = (("the book's Crossref record and its Library of Congress record name different editors, "
                            "and neither is chosen") if len(naming) == 2 and naming[0]["source"] != naming[1]["source"]
                           else f"the {len(naming)} records found for the book name different editors, and none is chosen")
        found["disagreement"] = True
    elif naming:
        found["editor"] = naming[0]["editor"]
        found["by"] = naming[0]["source"]
        found["booktitle"] = naming[0]["booktitle"]
    elif failed:
        found["reason"] = "; ".join(failed) + "; the book's record could not be looked up"
    elif sources:
        found["reason"] = "the book's own record names no editors"
    else:
        found["reason"] = "no record of the book was found by the chapter's ISBN at Crossref or in the Library of Congress catalogue"
    return found


def valid_book_editors(record, booktitle=None):
    """The editors of ``record[BOOK_RECORD]``, as ``(editors, source)``, when that is
    evidence about the book this chapter is cited in; else None. Judged again every time the
    record is compared, from the source records kept there and from nothing derived:

    - no disagreement or incomplete answer was recorded;
    - every kept source is read again (``_crossref_source`` / ``_catalogue_source``): a
      record of a book type (never a series), carrying one of the chapter's own ISBNs;
    - the cited book is that record's: ``booktitle`` (the entry's book title; when None, the
      title the lookup settled on) is one of the chapter record's container titles, by the
      verifier's reading of a book title, and that container title is the source record's
      title, by the comparison used for the two titles. Evidence about the series, or about
      another book, is none for this entry;
    - the editors are the ones the source record itself gives, and every source that names
      editors names the same ones."""
    found = record.get(BOOK_RECORD) if isinstance(record, dict) else None
    if not isinstance(found, dict) or found.get("disagreement") or not isinstance(found.get("editor"), list):
        return None
    from .verification import book_title_forms
    venues = [v for v in record.get("container-title") or [] if isinstance(v, str)]
    cited = booktitle if booktitle is not None else found.get("booktitle")
    # The container titles of the chapter that the cited book title is, by the verifier's own
    # reading of a book title (a series number or a volume-pack tail is not part of it).
    books = [v for v in venues if isinstance(cited, str) and title_is(cited, v)]
    if not books:
        return None
    reread = []
    for source in found.get("sources") or []:
        if not isinstance(source, dict) or source.get("isbn") not in _isbns(record):
            return None
        if source.get("source") == "crossref-book-record":
            read = _crossref_source(source.get("record"), source["isbn"])
        elif source.get("source") == "loc-catalogue":
            read = _catalogue_source(source.get("marcxml"), source["isbn"]) if isinstance(source.get("marcxml"), str) else None
        else:
            read = None
        if read is None or read["editor"] is None or read["type"] not in BOOK_TYPES \
                or not any(same_title(v, name) for v in books for name in read["names"]):
            return None
        reread.append((source, read))
    naming = [(source, read) for source, read in reread if read["editor"]]
    chosen = next(((source, read) for source, read in naming if source.get("source") == found.get("by")), None)
    if not chosen or chosen[1]["editor"] != found["editor"] \
            or any(not same_people(chosen[1]["editor"], read["editor"]) for _, read in naming):
        return None
    source, read = chosen       # what is handed on is what the source record says, not the summary kept beside it
    return read["editor"], dict(source, title=read["names"][0], names=read["names"], type=read["type"],
                                editor=read["editor"])


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
            self.lines.append(text[:LINE_CHARS])
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
    """The lines of an HTML page: its citation metadata first, then its text, a line per
    block. A block longer than ``LINE_CHARS`` is cut to that length; a line of that length
    is therefore known to be (or may be) incomplete, and ``choice_from_reading`` does not take
    it as evidence for a title."""
    parser = _PageText()
    parser.feed(markup)
    parser.close()
    parser._end_line()
    return [line[:LINE_CHARS] for line in parser.meta + parser.lines]


def _mentions(line, title):
    """Whether ``line`` holds ``title`` as whole words, both read as the verifier reads a book
    title (``_key``). None when the line (or the title) is one the verifier does not read
    (math, markup): such a line says nothing either way, and is never taken as "does not
    mention"."""
    wanted, text = _key(title), _key(line)
    if not wanted or not text:
        return None
    return bool(re.search(r"(?<!\w)" + re.escape(wanted) + r"(?!\w)", text))


def lines_about(lines, titles, around=2, limit=MAX_LINES):
    """The lines that mention one of the two titles, each with the ``around`` lines before
    and after it, in page order, at most ``limit``: what a model is given to read. Empty
    when the page mentions neither."""
    keep = set()
    for index, line in enumerate(lines):
        if any(_mentions(line, t) is not False for t in titles):      # a line that cannot be read is shown too
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


class OutOfTime(ProviderError):
    """The time allowed for a retrieval is over (or its body is over the size allowed): the
    request was cancelled. A ``ProviderError``, so the paced client does not ask again."""


class _Read:
    """A response whose body was read whole under a deadline and a size limit, standing in
    for the ``requests`` response wherever its body is used (``content``, ``text``,
    ``json()``, ``iter_content``); everything else is the response's own."""

    def __init__(self, response, body):
        self._response, self.content = response, body
        self.status_code, self.headers, self.url = response.status_code, response.headers, response.url

    @property
    def text(self):
        return self.content.decode(self._response.encoding or "utf-8", errors="replace")

    def json(self, **options):
        return json.loads(self.content.decode("utf-8-sig"), **options)

    def iter_content(self, chunk_size=65536, **options):
        for start in range(0, len(self.content), chunk_size or 65536):
            yield self.content[start:start + (chunk_size or 65536)]

    def close(self):
        self._response.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __getattr__(self, name):
        return getattr(self._response, name)


def _inflater(encoding):
    """What turns the bytes of a body sent with ``Content-Encoding: encoding`` into the body:
    None for an unencoded one, a zlib decompressor for gzip and deflate. Any other encoding
    is refused (``OutOfTime``): it is not asked for, and not inflated blind."""
    import zlib
    encoding = str(encoding or "").strip().lower()
    if encoding in ("", "identity"):
        return None
    if encoding in ("gzip", "x-gzip", "deflate"):
        return zlib.decompressobj(47)          # gzip or zlib framing, told apart from the header
    raise OutOfTime("the answer is in an encoding that was not asked for; it was not read")


def read_bounded(response, deadline, limit):
    """The body of a streamed response, read as it was sent (not yet decompressed) in small
    steps, with two limits of ``limit`` bytes: on what is received, and on what it inflates
    to (a small gzip cannot become a large body: the decompressor is given the room that is
    left and stopped there). The clock is looked at between steps; the hard stop at the
    deadline is ``timed``, which runs this."""
    import time
    raw, chunks, received, size = response.raw, [], 0, 0
    inflate = _inflater(response.headers.get("Content-Encoding"))
    try:
        for chunk in raw.stream(8192, decode_content=False):
            if time.monotonic() > deadline:
                raise OutOfTime("the time allowed for this retrieval is over; it was cancelled")
            received += len(chunk)
            if received > limit:
                raise OutOfTime(f"the answer is larger than {limit} bytes; it was cancelled")
            if inflate is not None:
                chunk = inflate.decompress(chunk, limit - size + 1)
                if inflate.unconsumed_tail:
                    raise OutOfTime(f"the answer is larger than {limit} bytes when it is unpacked; it was cancelled")
            size += len(chunk)
            if size > limit:
                raise OutOfTime(f"the answer is larger than {limit} bytes when it is unpacked; it was cancelled")
            chunks.append(chunk)
    except OutOfTime:
        response.close()
        raise
    except Exception as exc:  # noqa: BLE001 - a socket timeout, a broken stream, bad compressed data: no answer
        response.close()
        if time.monotonic() > deadline - 0.5:
            raise OutOfTime("the time allowed for this retrieval is over; it was cancelled") from None
        raise OutOfTime(f"the answer could not be read ({type(exc).__name__})") from None
    return _Read(response, b"".join(chunks))


def _quietly(action):
    try:
        action()
    except Exception:  # noqa: BLE001 - best effort
        pass


def timed(deadline, allowed, work, cancel=None):
    """``work()``'s result, or ``OutOfTime`` at ``deadline`` whatever ``work`` is doing then:
    looking a host up, connecting, waiting for headers, reading a chunk-size line, a trailer
    or a body. ``work`` runs on a thread of its own; this one waits for it no longer than the
    time left, then calls ``cancel`` (which closes what ``work`` holds, so that its blocked
    read ends) and goes on. The caller is released at the deadline; the abandoned thread is a
    daemon and ends when its closed socket or its own timeouts end it. ``allowed``: the whole
    seconds the retrieval was given, for the message."""
    import threading
    import time
    box = {}

    def run():
        try:
            box["value"] = work()
        except BaseException as exc:  # noqa: BLE001 - handed to the caller below
            box["error"] = exc

    left = deadline - time.monotonic()
    if left <= 0:
        raise OutOfTime(f"no answer within {allowed} seconds; nothing was asked")
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(left)
    if worker.is_alive():
        if cancel is not None:
            # Closing is done on a thread of its own and not waited for: closing a response
            # another thread is reading can itself wait for that read. The caller is released now.
            threading.Thread(target=_quietly, args=(cancel,), daemon=True).start()
        raise OutOfTime(f"no answer within {allowed} seconds; the request was cancelled")
    if "error" in box:
        raise box["error"]
    return box["value"]


class _DeadlineSession:
    """A session whose every ``get`` is a hard-bounded retrieval: the request and the reading
    of its body run under ``timed``, so the caller has its answer or ``OutOfTime`` by
    ``deadline``, and no body is larger than ``limit``, as sent or unpacked. Only gzip and
    deflate are asked for. What is asked is the wrapped session's business."""

    def __init__(self, session, deadline, limit):
        import time
        self.session, self.deadline, self.limit = session, deadline, limit
        self.allowed = max(1, round(deadline - time.monotonic()))

    def get(self, url, *args, **options):
        import time
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise OutOfTime(f"no answer within {self.allowed} seconds; nothing was asked")
        connect, read = options.get("timeout") if isinstance(options.get("timeout"), tuple) else (10, 40)
        options.update(stream=True, timeout=(max(0.05, min(connect, left)), max(0.05, min(read, left))),
                       headers=dict(options.get("headers") or {}, **{"Accept-Encoding": "gzip, deflate"}))
        held = {}

        def work():
            import requests
            try:
                held["response"] = self.session.get(url, *args, **options)
                return read_bounded(held["response"], self.deadline, self.limit)
            except (requests.Timeout, OutOfTime) as exc:
                # A timeout of the transport that falls at the deadline is the deadline (the socket
                # timeouts are cut to the time left); one that falls before it is the transport's own.
                if self.deadline - time.monotonic() < 0.5 and "larger than" not in str(exc):
                    raise OutOfTime(f"no answer within {self.allowed} seconds; the request was cancelled") from None
                raise

        def cancel():
            import socket
            response = held.get("response")
            if response is None:
                return
            connection = getattr(response.raw, "connection", None) or getattr(response.raw, "_connection", None)
            sock = getattr(connection, "sock", None)
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)      # ends the read the abandoned thread is blocked in
            response.close()

        return timed(self.deadline, self.allowed, work, cancel)

    def __getattr__(self, name):
        return getattr(self.session, name)


class within:
    """``with within(client, deadline): ...``: every request the paced client makes inside
    (Crossref's book lookup, the catalogue's search) is read by ``read_bounded`` under the
    one ``deadline`` and ``RECORD_BYTES``. The client's own session is put back on leaving."""

    def __init__(self, client, deadline, limit=None):
        self.client, self.deadline, self.limit = client, deadline, RECORD_BYTES if limit is None else limit

    def __enter__(self):
        self.session = self.client.session
        self.client.session = _DeadlineSession(self.session, self.deadline, self.limit)
        return self

    def __exit__(self, *exc):
        self.client.session = self.session
        return False


def page_session():
    """The session a publisher's page is fetched with, made for that one fetch and for
    nothing else, so that no credential can ride on it:

    - ``trust_env`` is off: no ``.netrc`` login, no ``REQUESTS_CA_BUNDLE``, and no proxy from
      the environment. The proxy policy is therefore "none": the page is asked for directly,
      and on a machine that reaches the web only through a proxy the fetch fails and the
      book title stays unfilled (said in the reason);
    - no ``auth``, no client certificate, no default parameters, and an empty cookie jar. The
      jar lives for this one fetch: a publisher's own redirect chain sets a cookie on one hop
      and reads it on the next (Springer's does), and nothing is kept afterwards;
    - certificates are verified against the bundled authorities, always.

    On the two DNS lookups: ``checked_url`` resolves the host to refuse private addresses, and
    the connection resolves it again. They can differ (DNS rebinding), and the connection is
    not pinned to the first answer. What bounds the harm is that every host is one of the
    fixed public hosts of ``PAGE_HOSTS`` and the connection is HTTPS with the certificate
    verified for that host name: an address that is not the publisher's cannot complete the
    TLS handshake, so no request line, header or cookie is sent to it and no body is read
    from it. What such an address does receive is a TCP connection and a TLS ClientHello
    naming a public host."""
    import requests
    session = requests.Session()
    session.trust_env = False
    session.auth, session.cert, session.params, session.proxies = None, None, {}, {}
    session.verify = True
    session.cookies.clear()
    session.headers.pop("Authorization", None)
    return session


class _CheckedSession:
    """A session that asks for nothing ``checked_url`` refuses and reads every answer by
    ``read_bounded``. The fetcher (``search_tools.get_source``) calls ``get`` once per hop
    with redirects off, so every hop, the first and each redirect target, is checked here in
    the form it is asked for. A request may carry a User-Agent header and nothing else of
    its own: no credentials, cookies, parameters or proxies are accepted from the caller."""

    def __init__(self, session, deadline):
        self.session, self.deadline, self.asked = session, deadline, []

    def get(self, url, **options):
        if options.get("allow_redirects") is not False or options.get("params"):
            raise UnsafeURL("a request that would not be checked hop by hop")
        if any(options.get(name) for name in ("auth", "cookies", "cert", "proxies", "data", "json")) \
                or set(options.get("headers") or {}) - {"User-Agent"}:
            raise UnsafeURL("a request that would carry credentials or other data")
        bounded = _DeadlineSession(self.session, self.deadline, PAGE_BYTES)
        try:
            url = timed(self.deadline, bounded.allowed, lambda: checked_url(url))     # the DNS lookup is timed too
            self.asked.append(url)
            return bounded.get(url, **options)
        except OutOfTime as exc:
            raise UnsafeURL(str(exc)) from None


def fetch_page(doi, deadline=None):
    """The page the chapter's DOI resolves to, as ``{"url", "lines", "document_sha256",
    "retrieved_at"}``; ``ValueError`` when it cannot be read.

    The fetcher is the package's own (``search_tools.get_source``, as
    ``publisher_corrections`` uses it): redirects are followed by hand, at most
    ``PAGE_REDIRECTS``. Every hop is asked for only after ``checked_url`` accepts it, on a
    session made for this fetch that carries no credentials (``page_session``), and its
    answer is read by ``read_bounded``: the whole fetch, all hops and every byte of every
    body, ends at ``deadline`` (``PAGE_SECONDS`` from now when none is given), and no body is
    larger than ``PAGE_BYTES``. The hosts are ``PAGE_HOSTS``, a fixed list. Nothing of the
    record but its DOI goes into the first URL."""
    import time
    from urllib.parse import quote
    import requests
    from .search_tools import SourceHTTPError, get_source
    limit = time.monotonic() + PAGE_SECONDS
    session = page_session()
    guarded = _CheckedSession(session, min(limit, deadline) if deadline is not None else limit)
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
    finally:
        session.close()
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
            whole, start, end = text[passage["page"]], passage["start"], passage["end"]
            quote = whole[start:end]
        except (KeyError, TypeError):
            raise ValueError("the reading's passages are not lines of the page") from None
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(whole) \
                or not quote.strip() or quote != passage.get("quote"):
            raise ValueError("the reading's passages are not lines of the page")
        # What is judged is every whole line the passage touches, never the slice the model
        # chose out of it: "Book: A; series: B" cannot be cut down to "B".
        first = whole.rfind("\n", 0, start) + 1
        last = whole.find("\n", end - 1 if whole[end - 1] == "\n" else end)
        quotes += [line.strip() for line in whole[first:len(whole) if last < 0 else last].split("\n") if line.strip()]
    if not quotes or found.get("grounding") != "literal_text_present":
        raise ValueError("the model's book title is not literally on the lines it selected")
    if found.get("role_risk"):
        raise ValueError("the lines the model selected may not state the work's own book title ("
                         + ", ".join(str(r) for r in found["role_risk"]) + ")")
    # A line of LINE_CHARS or more was cut when the page was read (page_lines): what followed is
    # not known, the other title among it perhaps, so it cannot say which title is the book's.
    if any(_mentions(q, chosen) is None or _mentions(q, other) is None for q in quotes):
        raise ValueError("a quoted line holds markup the citation check does not read, so what it says of the "
                         "titles is not known")
    alone = [q for q in quotes if len(q) < LINE_CHARS and _mentions(q, chosen) and not _mentions(q, other)]
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
    page = cache.response(PAGE_KEY + doi, PAGE_TTL)
    if page is None:
        return None, None, None
    pages = pages_for(page, titles)
    digest = hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return page, pages, cache.response("book-title-reading-v1:" + digest, READING_TTL)


def from_model(client, cache, record, titles, announce=None, allow_model=None, environ=None, deadline=None):
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
                page = fetch_page(doi, deadline=deadline)
            except ValueError as exc:
                return Resolution(titles, reason=f"the publisher's page could not be read ({exc}), so no model was asked")
            cache.save_response(PAGE_KEY + doi, page)
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
    deadline, failed = time.monotonic() + RESOLVE_SECONDS, []
    for name, step in (("Crossref", lambda: from_crossref(client, record, titles)),
                       ("the Library of Congress catalogue", lambda: from_catalogue(client, cache, record, titles))):
        try:
            with within(client, deadline):       # one deadline for every byte of every record lookup
                found = step()
        except (ProviderError, ValueError, KeyError, TypeError) as exc:
            failed.append(f"{name} did not answer ({exc})")
            continue
        if found:
            return found
    if time.monotonic() > deadline:
        failed.append("the record lookups took longer than the time allowed")
    if failed:
        return Resolution(titles, reason="; ".join(failed) + "; the book's own record could not be looked up, "
                                         "and no model is asked in its place")
    found = from_model(client, cache, record, titles, announce=announce, allow_model=allow_model, environ=environ,
                       deadline=deadline)
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
    written = next((c.proposed for c in proposal.changes if c.field == "booktitle"), None)
    proposal.choices.append(dict(resolution.evidence, field="booktitle", by=resolution.by,
                                 chosen=resolution.chosen, other=resolution.other, written=written,
                                 model_assisted=resolution.model_assisted,
                                 confirmed=not resolution.model_assisted,
                                 **({"statement": UNCONFIRMED} if resolution.model_assisted else {})))
    if resolution.model_assisted:
        proposal.issues.append(said + " " + UNCONFIRMED)
        proposal.needs_decision = True
    else:
        proposal.notes.append(said)
    return proposal


# --- after the entry is written -------------------------------------------------------------------

MODEL_CHOICE = "model-assisted-choice"     # ``kind`` of the external evidence stored with such an entry


def model_choice(proposal, booktitle=None):
    """The model-assisted choice a proposal carries (its record in ``choices``), or None. The
    choice is bound to the exact book title it wrote (``written``): with ``booktitle`` (the
    book title of the entry as it will be written) it is returned only when that is still the
    value, so a person who typed another title has dropped the choice, and nothing else has."""
    choice = next((c for c in getattr(proposal, "choices", None) or []
                   if c.get("field") == "booktitle" and c.get("model_assisted") and c.get("chosen")), None)
    if choice is None or (booktitle is not None and booktitle != choice.get("written")):
        return None
    return choice


def restate(proposal, fields):
    """After a proposal was edited and rechecked: when its book title is still the one a
    model chose, the proposal says so again and needs the person's decision again (a recheck
    starts from no issues); when the person changed the book title, the choice is theirs and
    the model's is taken off the proposal."""
    carried = model_choice(proposal)
    if carried is None:
        return proposal
    if model_choice(proposal, (fields or {}).get("booktitle")) is None:
        proposal.choices = [c for c in proposal.choices if c is not carried]
        return proposal
    said = (f"booktitle: \"{carried['chosen']}\" was chosen between the record's two titles with a model "
            f"({carried.get('route')}), from the line \"{carried.get('quote')}\" of {carried.get('url')}. " + UNCONFIRMED)
    if not any(UNCONFIRMED in issue for issue in proposal.issues):
        proposal.issues.append(said)
    proposal.needs_decision = True
    return proposal


def _choice_evidence(choice):
    return {"kind": MODEL_CHOICE, "summary": "booktitle chosen with a model, unconfirmed",
            "statement": UNCONFIRMED, "model_assisted": True, "confirmed": False,
            "reviewer": f"model:{choice.get('route')}", "booktitle": choice.get("written"),
            "fields": {"booktitle": {"value": choice.get("chosen"), "quote": choice.get("quote"),
                                     "page": choice.get("url")}},
            **{k: choice.get(k) for k in ("route", "model", "url", "quote", "document_sha256", "chosen", "other",
                                          "page_retrieved_at", "read_at")}}


def _put_choice(cache, bibliography, entry, choice):
    """Store the mark for ``entry`` (key, text, fields, fingerprint). The mark names the book
    title it is about; an entry with another book title is refused. A person's approval of
    this exact entry is left as it is."""
    from .errors import CdlbibError
    from .verification import outcome
    if entry["fields"].get("booktitle") != choice.get("written") or not choice.get("written"):
        raise CdlbibError(f"{entry['key']}: the book title is not the one the model-assisted choice wrote; "
                          "the mark is for that title only.")
    previous = cache.get(bibliography, entry)
    if previous and previous.get("status") == "human_verified":
        return previous
    return cache.put(bibliography, entry, dict(
        previous or outcome("needs_review", []), status="needs_review", external_evidence=_choice_evidence(choice),
        issues=["booktitle chosen with a model, unconfirmed: human confirmation required"]))


def store_model_choices(ws, accepted, planned, entries, database=None):
    """Called by the writer (``complete.apply``) when everything is planned and nothing is
    written yet: for each proposal about to be written whose book title a model chose (and
    still is that title), the mark is stored for the entry as it WILL be (its fingerprint is
    read from the exact text about to be written). The mark therefore exists before the
    entry does, whichever interface accepted it; if it cannot be stored, ``CdlbibError`` is
    raised and nothing is written. Returns the keys marked."""
    import sqlite3
    from .errors import CdlbibError
    from .verification import Cache, run_lock
    wanted = []
    for outcome in planned.outcomes:
        if outcome.status != "written":
            continue
        entry = entries[outcome.key]
        choice = model_choice(accepted[outcome.index], entry["fields"].get("booktitle"))
        if choice is not None:
            wanted.append((entry, choice))
    if not wanted:
        return []
    cache = None
    try:
        cache = Cache(database or ws.database, ledger=ws.revocations)
        with run_lock(cache):
            for entry, choice in wanted:
                _put_choice(cache, ws.bib, entry, choice)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        raise CdlbibError("The entry's book title was chosen with a model, and the record of that could not be "
                          f"stored ({exc}); nothing was written.") from exc
    finally:
        if cache is not None:
            cache.close()
    return [entry["key"] for entry, _ in wanted]


def keep_model_choice(ws, key, fingerprint, choice, database=None):
    """Store the mark for the library entry ``key`` as it is now (the writer stores it itself,
    before it writes: ``store_model_choices``; this is for an entry already in the library).
    Its result becomes ``needs_review`` with the choice as its ``external_evidence`` (kind
    ``MODEL_CHOICE``: route, model, URL, quoted line, page hash, and the book title it is
    about), bound to the entry's fingerprint: the record ``crossref attach-evidence`` and a
    model reading of a PDF use, with their meaning. Every automatic check leaves such an
    entry ``needs_review`` (the verifier accepts either of the record's two titles, so its
    acceptance would say nothing of the choice) until a person approves the entry; an edit of
    the entry gives it a new fingerprint, and with it a new judgement. Never an approval."""
    import sqlite3
    from .errors import CdlbibError
    from .library import transaction
    from .verification import Cache, load_entries, run_lock
    cache = None
    try:
        with transaction(ws):
            cache = Cache(database or ws.database, ledger=ws.revocations)
            with run_lock(cache):
                entry = load_entries(ws.bib).get(key)
                if entry is None or entry["fingerprint"] != fingerprint:
                    raise CdlbibError(f"{key} is not the entry that was written; the model-assisted mark was not stored.")
                return _put_choice(cache, ws.bib, entry, choice)
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise CdlbibError(f"The model-assisted mark could not be stored: {exc}") from exc
    finally:
        if cache is not None:
            cache.close()
