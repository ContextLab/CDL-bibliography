"""Reference intake: candidate search, PDF reading, model-assisted reading and manual drafts.

Nothing here prints, prompts, exits, writes the library or records an approval. Every
function returns data a front end shows:

- ``find_candidates``: leads from Crossref, PubMed and arXiv for a title, one or several
  authors, or both. A lead is never an entry: choosing one is ``query_for(candidate)``
  handed to ``api.propose_new`` (find, build, format, check).
- ``read_pdf``: the text of a PDF's first pages, the identifiers printed there, a title
  guess. The file is parsed in a child process with a time limit, a page cap and an output
  cap; an encrypted, scanned or unreadable file is a ``problem`` value, not an exception.
- ``render_first_page``: page 1 as PNG bytes, also in a bounded child process.
- ``propose_from_pdf``: the identifiers in order (DOI, arXiv, PMID), then the title,
  through ``complete.propose``. A record whose title is not on the PDF's first pages is
  never taken silently: the proposal says so and needs a decision.
- ``read_pdf_with_model``: the existing research adapters' ``extract`` phase; only a field
  whose quotation is on the stated page, and whose value is literally in it, is kept.
- ``draft_manual``: typed fields in house format.

A model-read or hand-typed entry has no source record: its proposal has ``manual=True``,
``status="needs_review"`` and always needs a decision. Nothing here can make it verified.
"""
from dataclasses import dataclass, field
import hashlib
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from typing import NamedTuple

from . import complete, deps
from .errors import CdlbibError, SecretNotFound

MAX_PAGES = 5               # pages read from a PDF (research.extract_pages reads as many)
MAX_PAGE_CHARS = 100_000    # text kept per page; reading a page stops there
MAX_TOTAL_CHARS = 300_000   # text kept over all pages; reading the PDF stops there
MAX_STREAM_BYTES = 20_000_000   # the most one PDF stream may decompress to in the reading child
MAX_CHILD_MEMORY = 2_000_000_000    # address-space limit of a child, where the platform accepts one
MAX_PIXELS = 16_000_000     # the most pixels a page preview may have, decided before it is drawn
MAX_QUERY_CHARS = 500       # of a typed title; one name is cut at MAX_NAME_CHARS
MAX_NAME_CHARS = 100
MAX_AUTHORS = 10
MAX_PER_SOURCE = 50         # records asked of one source, whatever the caller passes
MAX_CANDIDATES = 100
MAX_PDF_BYTES = 50_000_000  # a larger file is not opened
MAX_OUTPUT_BYTES = 4_000_000    # what the reading child may send back
MAX_IMAGE_BYTES = 40_000_000    # what the rendering child may send back
READ_TIMEOUT = 60           # seconds the reading child may take
OCR_TIMEOUT = 120           # seconds the OCR child may take (read_pdf's ocr_seconds)
RENDER_TIMEOUT = 30
IDENTIFIER_PAGES = 2        # identifiers are looked for on these first pages
TITLE_PAGES = 4             # a record's title is looked for on these first pages
MODEL_PAGES = 2             # the pages a model is given (the front matter)
CANDIDATE_LIMIT = 20
PER_SOURCE = 10
SOURCES = ("crossref", "pubmed", "arxiv")
ARXIV_API = "https://export.arxiv.org/api/query"
DARTMOUTH_KEY_PAGE = "https://rc.dartmouth.edu/ai/online-resources/connecting-ai-clients/"
ADAPTERS = {"dartmouth": "cdlbib-adapter-dartmouth", "openai": "cdlbib-adapter-openai"}
NO_SOURCE = ("No source record: these fields were not confirmed by Crossref, PubMed or arXiv. The entry "
             "stays unverified until a source confirms it or a logged-in person approves it.")
QUOTE_CHECK = "Passed exact PDF page text checks; identity and interpretation require a human"

_ARXIV_PRINTED = re.compile(
    r"(?i)\barxiv\s*:\s*((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?)"
    r"|arxiv\.org/(?:abs|pdf)/((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?)")
_PMID_PRINTED = re.compile(r"(?i)\bpmid\s*:?\s*(\d{1,9})\b")
_NOT_A_TITLE = re.compile(r"(?i)^(?:untitled|microsoft word\b.*|.*\.(?:pdf|docx?|tex|dvi|indd|qxd|ps))$")


# --- candidates ---------------------------------------------------------------------------------

def to_data(value):
    """``value`` as plain data with nothing left out: ``api.as_data``, the one serializer
    (kept under this name for what intake's own classes call)."""
    from .api import as_data
    return as_data(value)


class Candidates(list):
    """The leads, plus ``errors``: (source, reason) for each source that did not answer.
    ``to_data()`` gives both as plain data (a bare list would lose the errors)."""

    def __init__(self):
        super().__init__()
        self.errors = []

    def to_data(self):
        return to_data(self)


def _plain(text, limit):
    """Typed text on one line, without control characters, at most ``limit`` characters."""
    return " ".join("".join(c if c.isprintable() else " " for c in str(text or "")).split())[:limit].strip()


def _surname(name):
    """The surname of one typed name ("Manning", "Jeremy R. Manning", "Manning, J. R."),
    as accent-free lower-case words of letters and digits only ("van der walt"); "" when
    there is none. Nothing else of the typed text is put into a source's query syntax, so
    a quote, a bracket, a colon or a field tag in a name cannot change the query."""
    from .extra_sources import fold, words
    name = _plain(name, MAX_NAME_CHARS)
    if not name:
        return ""
    return " ".join(words(fold(complete._first_surname(name) or name.split(",")[0].split()[-1])))


def _significant(title, limit=8):
    """Up to ``limit`` title words worth searching for, in title order
    (``extra_sources.pubmed_title_term``'s choice: no stop words, the longest first).
    Words are runs of letters and digits (``extra_sources.words``), nothing else."""
    from .extra_sources import STOPWORDS, words
    found = [w for w in words(title or "") if w not in STOPWORDS and len(w) > 2]
    chosen = sorted(dict.fromkeys(found), key=lambda w: (-len(w), found.index(w)))[:limit]
    return sorted(chosen, key=found.index)


def _bibtex_authors(people):
    """Crossref-shaped people as one BibTeX author string, or None."""
    names = []
    for person in people or []:
        if not isinstance(person, dict):
            continue
        family, given = complete._text(person.get("family")), complete._text(person.get("given"))
        if family:
            names.append(family + (", " + given if given else ""))
        elif complete._text(person.get("name")):
            names.append("{" + complete._text(person["name"]) + "}")
    return " and ".join(names) or None


def _crossref_leads(client, title, authors, year, rows):
    params = {"rows": rows}
    if title:
        params["query.bibliographic"] = " ".join(p for p in (" ".join(title.split()), year) if p)
    if authors:
        params["query.author"] = " ".join(authors)
    response = client.get("https://api.crossref.org/works", params)
    for record in (response.get("body") or {}).get("message", {}).get("items", []):
        if complete._is_notice(record):
            continue
        yield complete._summary(record, "crossref"), _bibtex_authors(record.get("author"))


def _pubmed_leads(client, title, authors, year, rows):
    from .extra_sources import efetch, esearch, medline_is_notice, medline_record
    words = _significant(title)
    if title and len(words) < 2 and not authors:
        return  # one word is not a PubMed title search
    surnames = [s for s in map(_surname, authors) if s]
    terms = [f"{s}[au]" for s in surnames] + [f"{w}[ti]" for w in words]
    if not terms:
        return
    if year:
        terms.append(f"{year}[dp]")
    found = esearch(client, " AND ".join(terms), retmax=rows)
    records = efetch(client, found["pmids"][:rows])[0] if found["pmids"] else {}
    for pmid in found["pmids"][:rows]:  # PubMed's own order
        raw = records.get(pmid)
        if raw is None or medline_is_notice(raw):
            continue
        mapped = medline_record(raw)
        yield complete._summary(mapped, "pubmed"), _bibtex_authors(mapped.get("author"))


def arxiv_search_params(title, authors, rows=PER_SOURCE):
    """The arXiv API request for a title and/or authors: every significant title word in
    ``ti:``, every surname in ``au:``. Each term is letters, digits and (inside the quotes
    of a surname of several words) spaces; the query syntax is written here only."""
    terms = [f"ti:{w}" for w in _significant(title)]
    terms += [f'au:"{s}"' if " " in s else f"au:{s}" for s in map(_surname, authors) if s]
    return {"search_query": " AND ".join(terms), "start": 0, "max_results": rows, "sortBy": "relevance"}


def _arxiv_leads(client, title, authors, year, rows):
    import xml.etree.ElementTree as ET
    from . import arxiv_review as ar
    params = arxiv_search_params(title, authors, rows)
    if not params["search_query"]:
        return
    response = client.get(ARXIV_API, params, xml=True)  # paced, validated and cached by the client
    try:
        root = ET.fromstring(response.get("body") or "")
    except ET.ParseError as exc:
        from .verification import ProviderError
        raise ProviderError("Malformed arXiv XML") from exc
    for item in root.findall("a:entry", ar.NS):
        try:
            base, _ = ar.parse_id((item.findtext("a:id", default="", namespaces=ar.NS)).split("/abs/", 1)[1])
            published = ar.timestamp(item.findtext("a:published", default="", namespaces=ar.NS).strip())
        except (ValueError, IndexError):
            continue  # not a record this project can name
        names = [complete._text(a.findtext("a:name", default="", namespaces=ar.NS))
                 for a in item.findall("a:author", ar.NS)]
        names = [n for n in names if n]
        lead = {"authors": "; ".join(names), "year": str(published.year), "journal": "arXiv",
                "doi": ar.doi_for(base), "title": complete._text(item.findtext("a:title", default="", namespaces=ar.NS)),
                "type": "preprint", "source": "arxiv", "arxiv": base}
        stated = complete._doi_text(item.findtext("x:doi", default="", namespaces=ar.NS) or "")
        if stated:
            lead["published_doi"] = stated  # the published version its arXiv record names
        yield lead, " and ".join(names) or None


_LEADS = {"crossref": _crossref_leads, "pubmed": _pubmed_leads, "arxiv": _arxiv_leads}


def _merge_keys(lead):
    from .verification import normalize_doi
    keys = []
    for name in ("doi", "published_doi"):
        try:
            keys.append(("doi", normalize_doi(lead[name])))
        except (KeyError, ValueError, AttributeError):
            continue
    if lead.get("arxiv"):
        keys.append(("arxiv", lead["arxiv"]))
    if lead.get("pmid"):
        keys.append(("pmid", str(lead["pmid"])))
    return keys


def _library_index(ws):
    """(work identifiers -> key, title and surnames -> key) for the library's entries, by
    the rules ``complete.duplicates`` uses."""
    by_id, by_title = {}, {}
    for key, entry in complete._library_entries(ws).items():
        for work in complete._work_ids(entry["fields"]):
            by_id.setdefault(work, key)
        named = complete._title_byline(entry["fields"])
        if named is not None:
            by_title.setdefault(named, key)
    return by_id, by_title


def _in_library(lead, authors, index):
    by_id, by_title = index
    fields = {"doi": lead.get("doi"), "pmid": lead.get("pmid"), "arxiv": lead.get("arxiv")}
    works = complete._work_ids(fields) | complete._work_ids({"doi": lead.get("published_doi")})
    for work in works:
        if work in by_id:
            return by_id[work]
    named = complete._title_byline({"title": lead.get("title"), "author": authors})
    return by_title.get(named) if named is not None else None


def _relevance(lead, title, surnames, year):
    """None when the lead does not hold what was asked for; else its sort key (lower first)."""
    from .extra_sources import title_similarity, words
    similarity = 1.0
    if title:
        similarity = title_similarity(title, lead.get("title") or "")
        asked = _significant(title, limit=50)
        if similarity < 0.6 and not (asked and set(asked) <= set(words(lead.get("title") or ""))):
            return None
    named = words(lead.get("authors") or "")
    text = " ".join(named)
    if any(not re.search(r"(?<![a-z0-9])" + re.escape(" ".join(words(s))) + r"(?![a-z0-9])", text) for s in surnames):
        return None
    return (0 if not year or year in str(lead.get("year") or "").split("/") else 1, -round(similarity, 3))


class _Client:
    """The caller's client, or one of our own over the library's response cache, closed on exit."""

    def __init__(self, ws, client=None, mailto=None, database=None):
        self.ws, self.client, self.mailto, self.database = ws, client, mailto, database
        self.owned = client is None

    def __enter__(self):
        from . import extra_sources
        from .verification import ProviderError
        if self.owned:
            try:
                path = self.database or self.ws.database
                self.client = extra_sources.make_client(path, contact=self.mailto or extra_sources.contact_email(path))
            except (OSError, ValueError, ProviderError, sqlite3.Error) as exc:
                raise CdlbibError(f"The sources cannot be asked: {exc}") from exc
        return self.client

    def __exit__(self, *exc):
        if self.owned and self.client is not None:
            self.client.cache.close()
        return False


def find_candidates(ws, title=None, authors=(), year=None, client=None, limit=CANDIDATE_LIMIT,
                    per_source=PER_SOURCE, sources=SOURCES, mailto=None, database=None, progress=None):
    """Leads for a title, one or several authors, or both, from Crossref, PubMed and arXiv.

    Each lead has the shape of ``complete._summary`` (``authors``, ``year``, ``journal``,
    ``doi``, ``title``, ``type``, ``source``, and ``pmid``/``arxiv`` when known) plus
    ``sources`` (every source that gave it) and ``in_library`` (the key of the library entry
    that is the same work by ``complete.duplicates``' rules, else None). Records with the
    same DOI, arXiv id or PMID are one lead; an arXiv record that names its published DOI
    is merged into that DOI's lead. A lead is kept only when its authors include every
    surname asked for and its title holds the words asked for (or is similar); leads of the
    asked year come first, then the closest titles. At most ``limit`` are returned
    (never more than ``MAX_CANDIDATES``), from at most ``per_source`` records of each source
    (never more than ``MAX_PER_SOURCE``).

    What was typed is data: it goes to Crossref as request parameters, and into the PubMed
    and arXiv query syntax only as words of letters and digits (``_surname``,
    ``_significant``). ``year`` must be four digits.

    A source that does not answer is listed in ``.errors`` and the others are still asked.
    A lead is not an entry: build one with ``query_for(lead)`` through ``api.propose_new``.
    """
    from .verification import ProviderError
    title = _plain(title, MAX_QUERY_CHARS) or None
    authors = [authors] if isinstance(authors, str) else list(authors or ())[:MAX_AUTHORS]
    authors = [a for a in (_plain(a, MAX_NAME_CHARS) for a in authors) if a]
    year = str(year or "").strip() or None
    if year and not re.fullmatch(r"\d{4}", year):
        raise CdlbibError(f"Not a year: {_plain(year, 20)!r} (four digits are expected).")
    try:
        per_source, limit = max(1, min(int(per_source), MAX_PER_SOURCE)), max(0, min(int(limit), MAX_CANDIDATES))
    except (TypeError, ValueError) as exc:
        raise CdlbibError("The number of records to ask for must be a whole number.") from exc
    unknown = [s for s in sources if s not in _LEADS]
    if unknown:
        raise CdlbibError(f"Unknown source {unknown[0]!r}; the sources are {', '.join(_LEADS)}.")
    found = Candidates()
    if not title and not authors:
        raise CdlbibError("Nothing to search for: give a title, one or more authors, or both.")
    surnames = [s for s in map(_surname, authors) if s]
    merged, order = {}, []
    with _Client(ws, client, mailto, database) as client:
        for source in sources:
            try:
                leads = list(_LEADS[source](client, title, authors, year, per_source))
            except (ProviderError, ValueError, KeyError, TypeError, AttributeError) as exc:
                found.errors.append((source, str(exc)))
                if progress:
                    progress(f"{source}: no answer ({exc})")
                continue
            if progress:
                progress(f"{source}: {len(leads)} record{'s' if len(leads) != 1 else ''}")
            for lead, names in leads:
                keys = _merge_keys(lead)
                known = next((merged[k] for k in keys if k in merged), None)
                if known is None:
                    known = dict(lead, sources=[source], _authors=names)
                    order.append(known)
                else:
                    if source not in known["sources"]:
                        known["sources"].append(source)
                    for name in ("pmid", "arxiv"):
                        if lead.get(name) and not known.get(name):
                            known[name] = lead[name]
                for key in keys:
                    merged.setdefault(key, known)
    ranked = []
    for position, lead in enumerate(order):
        score = _relevance(lead, title, surnames, year)
        if score is not None:
            ranked.append((score, position, lead))
    ranked.sort(key=lambda item: item[:2])
    index = None
    for _, _, lead in ranked[:limit]:
        names = lead.pop("_authors")
        try:
            index = index or _library_index(ws)
            lead["in_library"] = _in_library(lead, names, index)
        except (OSError, ValueError) as exc:
            raise CdlbibError(f"The library could not be read to look for duplicates: {exc}") from exc
        found.append(lead)
    return found


def query_for(candidate):
    """The ``complete.Query`` for a chosen lead: what ``api.propose_new`` is given. The rule
    is ``complete.Query.from_candidate`` (the one shared rule): the identifier of the source
    the lead came from (an arXiv lead: its arXiv id), otherwise the DOI, then the PMID, then
    the title. CdlbibError when the lead has none of them."""
    try:
        return complete.Query.from_candidate(candidate)
    except ValueError as exc:
        raise CdlbibError(str(exc)) from exc


# --- PDF reading --------------------------------------------------------------------------------

class Identifier(NamedTuple):
    kind: str          # "doi", "arxiv" or "pmid"
    value: str
    page: int | None   # None: found in the PDF's metadata
    quote: str         # the line it was read from


@dataclass
class PdfIntake:
    """What was read from a PDF. ``problem``: None, or "not_a_file", "not_pdf", "too_large", "encrypted",
    "no_text" (a scan no OCR tool read), "unreadable" or "timeout"; ``detail`` says more.
    ``ocr``: the text is OCR output (``local_ocr``), which misreads characters."""
    path: Path
    sha256: str | None = None
    pages: list = field(default_factory=list)   # [{"page": n, "text": "..."}]
    first_page_text: str = ""
    identifiers: list = field(default_factory=list)
    title_guess: str | None = None
    metadata: dict = field(default_factory=dict)
    problem: str | None = None
    detail: str | None = None
    ocr: bool = False
    title_source: str | None = None   # "largest text on page 1" or "PDF metadata"

    def to_data(self):
        return to_data(self)


def _child(arguments, timeout, limit):
    """Run this module's child entry point and read its output as it comes: (return code,
    stdout bytes, the end of stderr, whether it wrote more than ``limit`` bytes).

    The output is read in blocks and never beyond ``limit`` (plus one block): a child that
    writes more is killed at once. A child still running after ``timeout`` seconds is
    killed and ``subprocess.TimeoutExpired`` is raised. Arguments are passed as an argument
    list (no shell).

    The scratch space is this call's own: one private folder (``tempfile.mkdtemp``, mode
    0700) made here, given to the child as its only temporary location (``TMPDIR``, ``TEMP``
    and ``TMP``, which ``local_ocr``, pdftoppm and tesseract follow, and ``CDLBIB_SCRATCH``),
    holding the child's stderr too. It is removed here, after the child and its process
    group are dead, however the call ends (a result, a timeout, too much output, an
    exception, an interrupt); a killed child cannot clean up after itself, and what it
    leaves is text and images of the person's paper. ``shutil.rmtree`` removes a link found
    inside without following it.
    """
    import selectors
    import tempfile
    import time
    package_parent = str(Path(__file__).resolve().parents[1])
    command = [sys.executable, "-m", "cdlbib.intake", *map(str, arguments)]
    out, over, deadline, process = bytearray(), False, time.monotonic() + timeout, None
    scratch = tempfile.mkdtemp(prefix="cdlbib-pdf-")
    try:
        env = dict(os.environ, TMPDIR=scratch, TEMP=scratch, TMP=scratch, CDLBIB_SCRATCH=scratch,
                   PYTHONPATH=os.pathsep.join(p for p in (package_parent, os.environ.get("PYTHONPATH")) if p))
        with open(os.path.join(scratch, "stderr"), "w+b") as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL,
                                       env=env, cwd=scratch,
                                       start_new_session=True)  # its own group: the tools it starts die with it
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    if not selector.select(left):
                        continue
                    block = os.read(process.stdout.fileno(), 65536)
                    if not block:
                        break
                    out += block
                    if len(out) > limit:
                        over = True
                        break
            if not over:
                process.wait(max(0.1, deadline - time.monotonic()))
            _stop(process)
            errors.seek(0)
            said = errors.read(2000).decode("utf-8", "replace").strip()
        return process.returncode, bytes(out), said, over
    finally:
        if process is not None:
            _stop(process)
        shutil.rmtree(scratch, ignore_errors=True)


def _stop(process):
    """Kill the child and whatever it started (pdftoppm, tesseract), and wait until it is gone."""
    try:
        os.killpg(process.pid, 9)
    except (ProcessLookupError, PermissionError, AttributeError):
        if process.poll() is None:
            process.kill()
    process.wait()
    if process.stdout and not process.stdout.closed:
        process.stdout.close()


def _identifiers(pages, metadata):
    """DOIs, arXiv ids and PMIDs printed on the first pages (above any reference list) and
    named in the metadata, each once, in reading order."""
    from .pdf_evidence import DOI_RX, fold
    from .source_passages import REFERENCE_HEADING
    found, seen = [], set()

    def add(kind, value, page, quote):
        if value and (kind, value.lower()) not in seen:
            seen.add((kind, value.lower()))
            found.append(Identifier(kind, value, page, " ".join(quote.split())[:300]))

    def scan(text, page, label=""):
        for line in text.splitlines():
            line = fold(line)
            quote = label + line
            for match in _ARXIV_PRINTED.finditer(line):
                add("arxiv", complete._arxiv_text(match[1] or match[2]), page, quote)
            for match in DOI_RX.finditer(line):
                arxiv = complete._arxiv_text(match[1])
                if arxiv:
                    add("arxiv", arxiv, page, quote)
                else:
                    add("doi", complete._doi_text(match[1]), page, quote)
            for match in _PMID_PRINTED.finditer(line):
                add("pmid", match[1], page, quote)

    for page in pages[:IDENTIFIER_PAGES]:
        text = page["text"]
        heading = REFERENCE_HEADING.search(text)
        scan(text[:heading.start()] if heading else text, page["page"])
    for name, value in metadata.items():
        scan(str(value), None, f"metadata {name}: ")
    return found


class _NotAFile(Exception):
    """The path does not name a regular file; the message says what it is."""


_READ = {}     # real path -> SHA-256 of the bytes read_pdf read from it (the newest 256 paths of this process)


@contextlib.contextmanager
def _captured(path):
    """The file ``path`` names, captured once: its bytes are copied from one checked
    descriptor (opened without blocking and without following a link; nothing but a regular file)
    into a private folder of this call and hashed as they are copied. Yields (the copy, its
    size, its first 1024 bytes, its SHA-256); the copy is None, and nothing is copied, for a
    file larger than ``MAX_PDF_BYTES``. Everything that reads the PDF afterwards (the parser,
    OCR, the page preview) reads the copy, so what is read is what was hashed, whatever
    happens to the path meanwhile. The folder is removed when the block ends."""
    import stat
    import tempfile
    real = Path(os.path.realpath(path))
    descriptor = os.open(real, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_CLOEXEC", 0))
    scratch = None
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            kind = ("a folder" if stat.S_ISDIR(status.st_mode) else "a pipe" if stat.S_ISFIFO(status.st_mode)
                    else "a device" if stat.S_ISCHR(status.st_mode) or stat.S_ISBLK(status.st_mode)
                    else "a socket" if stat.S_ISSOCK(status.st_mode) else "not a regular file")
            raise _NotAFile(f"The path names {kind}, not a file; nothing was read.")
        head = os.read(descriptor, 1024)
        if status.st_size > MAX_PDF_BYTES:
            yield None, status.st_size, head, None
            return
        scratch = tempfile.mkdtemp(prefix="cdlbib-pdf-copy-")
        copy = Path(scratch) / "paper.pdf"
        digest, read = hashlib.sha256(head), len(head)
        with open(copy, "xb") as held:
            held.write(head)
            while read <= MAX_PDF_BYTES:      # never more than the cap, whatever the file has become
                block = os.read(descriptor, min(1 << 20, MAX_PDF_BYTES + 1 - read))
                if not block:
                    break
                digest.update(block)
                held.write(block)
                read += len(block)
        if read > MAX_PDF_BYTES:              # it grew past the cap while it was read
            yield None, read, head, None
            return
        yield copy, read, head, digest.hexdigest()
    finally:
        os.close(descriptor)
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


def _ocr_tools():
    return all(shutil.which(tool) for tool in ("pdftoppm", "tesseract"))


def read_pdf(path, ocr=True, progress=None, ocr_seconds=None):
    """Read a PDF's first ``MAX_PAGES`` pages in a child process.

    Returns a ``PdfIntake`` always, for a path that can be opened: something that is not a
    regular file (a folder, a pipe, a device: ``problem`` "not_a_file", decided from the
    opened descriptor before anything is read, and never waited for), a file that is not a
    PDF, is larger than ``MAX_PDF_BYTES``, is encrypted, cannot be parsed, takes too long
    or has no text is reported in ``problem``. The limits are applied before or while the
    work they bound is done: in the child, a cap on
    what one PDF stream may decompress to (``MAX_STREAM_BYTES``), text extraction that stops
    at ``MAX_PAGE_CHARS`` per page and ``MAX_TOTAL_CHARS`` in all (``detail`` then says the
    text was cut), a CPU limit and, where the platform accepts one, an address-space limit;
    here, the child's output is read in blocks up to ``MAX_OUTPUT_BYTES`` and the child is
    killed when it writes more or runs out of time.

    A PDF with no text is read by ``local_ocr`` when ``pdftoppm`` and ``tesseract`` are
    installed (``ocr=True``), also in a child, which is killed with the tools it started
    after ``ocr_seconds`` (default ``OCR_TIMEOUT``); the result then has ``ocr=True`` and no
    ``problem``, or ``problem`` "no_text" with the reason. One deadline covers the whole
    call: ``READ_TIMEOUT`` for reading plus ``ocr_seconds`` when OCR may run. ``progress``
    receives a line when reading starts, when no text is found, and when OCR starts.
    A path that cannot be opened raises ``CdlbibError``; a missing pypdf ``MissingDependency``.
    """
    import time
    path = Path(path)
    ocr_seconds = OCR_TIMEOUT if ocr_seconds is None else max(0.0, float(ocr_seconds))
    deadline = time.monotonic() + READ_TIMEOUT + (ocr_seconds if ocr else 0)
    said = progress or (lambda line: None)
    try:
        capture = _captured(path)
        real, size, head, digest = capture.__enter__()
    except _NotAFile as exc:
        return PdfIntake(path=path, problem="not_a_file", detail=str(exc))
    except OSError as exc:
        raise CdlbibError(f"The PDF could not be opened: {exc}") from exc
    try:      # ``real`` is this call's own copy of the bytes that were hashed; only it is read from here on
        if digest is not None:
            _READ.pop(os.path.realpath(path), None)
            _READ[os.path.realpath(path)] = digest
            while len(_READ) > 256:
                _READ.pop(next(iter(_READ)))
        return _read_captured(path, real, size, head, digest, ocr, ocr_seconds, deadline, said)
    finally:
        capture.__exit__(None, None, None)


def _read_captured(path, real, size, head, digest, ocr, ocr_seconds, deadline, said):
    import time
    intake = PdfIntake(path=path)
    if b"%PDF-" not in head:
        intake.problem, intake.detail = "not_pdf", "The file does not start as a PDF (no %PDF- header)."
        return intake
    if size > MAX_PDF_BYTES:
        intake.problem = "too_large"
        intake.detail = f"The file is {size // 1_000_000} MB; at most {MAX_PDF_BYTES // 1_000_000} MB is read."
        return intake
    intake.sha256 = digest
    deps.need("pypdf", "research", "Reading PDF files")
    said(f"Reading the first pages of {path.name}")
    try:
        code, out, err, over = _child(["read", real, MAX_PAGES, MAX_PAGE_CHARS, MAX_TOTAL_CHARS,
                                       MAX_STREAM_BYTES], READ_TIMEOUT, MAX_OUTPUT_BYTES)
    except subprocess.TimeoutExpired:
        intake.problem, intake.detail = "timeout", f"Reading the PDF took more than {READ_TIMEOUT} seconds."
        return intake
    if over or code != 0:
        intake.problem = "unreadable"
        intake.detail = (f"The PDF reader wrote more than {MAX_OUTPUT_BYTES} bytes and was stopped." if over
                         else f"The PDF reader stopped ({err.splitlines()[-1][:300] if err else code}).")
        return intake
    try:
        read = json.loads(out.decode("utf-8"))
        intake.pages = [{"page": int(p["page"]), "text": str(p["text"])[:MAX_PAGE_CHARS]}
                        for p in read["pages"][:MAX_PAGES]]
        intake.metadata = {str(k)[:100]: str(v)[:1000] for k, v in list(read["metadata"].items())[:50]}
        intake.problem, intake.detail = read["problem"], read["detail"]
        intake.title_guess, intake.title_source = read["title_guess"], read["title_source"]
    except (ValueError, KeyError, TypeError, AttributeError):
        intake.pages, intake.problem, intake.detail = [], "unreadable", "The PDF reader's answer could not be read."
        return intake
    if intake.problem == "no_text":
        said("No text was found in the PDF (a scan)")
    if intake.problem == "no_text" and ocr and _ocr_tools():
        allowed = min(ocr_seconds, deadline - time.monotonic())
        said(f"Running OCR on the first pages (pdftoppm, tesseract; at most {allowed:.0f} seconds)")
        try:
            if allowed <= 0:
                raise subprocess.TimeoutExpired("ocr", ocr_seconds)
            code, out, err, over = _child(["ocr", real, MAX_PAGES, MAX_PAGE_CHARS], allowed, MAX_OUTPUT_BYTES)
            pages = json.loads(out.decode("utf-8")) if code == 0 and not over else None
            if not isinstance(pages, list):
                raise ValueError(err.splitlines()[-1][:200] if err else "the OCR reader stopped")
            intake.pages = [{"page": int(p["page"]), "text": str(p["text"])[:MAX_PAGE_CHARS]} for p in pages][:MAX_PAGES]
            intake.ocr, intake.problem = True, None
            intake.detail = "The PDF has no text of its own; this text was read from the page images (OCR) and may be misread."
        except subprocess.TimeoutExpired:
            intake.detail = (f"The PDF has no text, and OCR did not finish within {ocr_seconds:.0f} seconds; "
                             "it was stopped.")
        except (ValueError, KeyError, TypeError) as exc:
            intake.detail = f"The PDF has no text, and OCR did not read it ({str(exc)[:200]})."
    elif intake.problem == "no_text" and ocr:
        intake.detail = "The PDF has no text (a scan), and pdftoppm and tesseract are not both installed to read it."
    intake.first_page_text = intake.pages[0]["text"] if intake.pages else ""
    intake.identifiers = _identifiers(intake.pages, intake.metadata)
    if not intake.title_guess:
        title = " ".join(intake.metadata.get("title", "").split())
        if len(title) >= 10 and not _NOT_A_TITLE.match(title):
            intake.title_guess, intake.title_source = title, "PDF metadata"
    return intake


def render_first_page(path, width=800):
    """Page 1 of a PDF as PNG bytes, ``width`` pixels wide (16 to 4000), rendered by
    pypdfium2 in a child process (``RENDER_TIMEOUT`` seconds). The image's size is worked
    out from the page's size before anything is drawn, and a page that would need more
    than ``MAX_PIXELS`` pixels is refused; the child's output is read in blocks up to
    ``MAX_IMAGE_BYTES``. Raises ``MissingDependency`` without pypdfium2 and ``CdlbibError``
    when the page cannot be drawn."""
    path, width = Path(path), int(width)
    if not 16 <= width <= 4000:
        raise CdlbibError("The preview width must be between 16 and 4000 pixels.")
    try:
        capture = _captured(path)
        real, size, head, digest = capture.__enter__()
    except _NotAFile as exc:
        raise CdlbibError(str(exc)) from exc
    except OSError as exc:
        raise CdlbibError(f"The PDF could not be opened: {exc}") from exc
    try:
        if b"%PDF-" not in head:
            raise CdlbibError("The file does not start as a PDF (no %PDF- header).")
        if size > MAX_PDF_BYTES:
            raise CdlbibError(f"The file is larger than {MAX_PDF_BYTES // 1_000_000} MB; no preview is drawn.")
        read_as = _READ.get(os.path.realpath(path))
        if read_as is not None and read_as != digest:
            # The preview stands beside what was read (and beside evidence bound to that
            # reading's SHA-256): a file that is no longer those bytes is not shown as if it were.
            raise CdlbibError("The file has changed since it was read (it is no longer the same bytes), so no "
                              "preview of it is drawn; read the PDF again.")
        deps.need("pypdfium2", "pdf", "the PDF page preview")
        try:
            code, out, err, over = _child(["render", real, width, MAX_PIXELS], RENDER_TIMEOUT, MAX_IMAGE_BYTES)
        except subprocess.TimeoutExpired:
            raise CdlbibError(f"Drawing the page took more than {RENDER_TIMEOUT} seconds.") from None
    finally:
        capture.__exit__(None, None, None)
    if over:
        raise CdlbibError(f"The page image is larger than {MAX_IMAGE_BYTES} bytes; drawing was stopped.")
    if code != 0 or not out.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CdlbibError("The first page could not be drawn" + (f" ({err.splitlines()[-1][:300]})." if err else "."))
    return out


def title_on_pages(pages, title):
    """Whether ``title`` is printed on the first ``TITLE_PAGES`` pages: as whole lines
    (``pdf_evidence.find_title_runs``), or inside the page text by the same comparison
    (``pdf_evidence.title_key``: letters, digits and hyphens; case, spacing and other
    punctuation do not count). LaTeX in the title is read as text first."""
    from .pdf_evidence import find_title_runs, title_key
    from .verification import normalized
    try:
        title = normalized(title)
    except ValueError:
        title = re.sub(r"[{}]", "", title)
    lined = [{"page": p["page"], "lines": [{"text": line, "text_nosup": line, "h": 0}
                                           for line in p["text"].splitlines() if line.strip()]}
             for p in pages[:TITLE_PAGES]]
    if find_title_runs(lined, title, max_pages=TITLE_PAGES):
        return True
    target = title_key(title)
    if len(target.replace("-", "")) < 8:
        return False
    for page in pages[:TITLE_PAGES]:
        key = title_key(re.sub(r"-\s*\n\s*", "-", page["text"]))
        if target in key or target.replace("-", "") in title_key(re.sub(r"-\s*\n\s*", "", page["text"])).replace("-", ""):
            return True
    return False


@dataclass
class PdfResult:
    """What ``propose_from_pdf`` found. ``proposal``: the entry built from a source record,
    or None when no record was found. ``found_by``: the ``Identifier`` (kind "title" for a
    title lookup) that gave it. ``candidates``: leads from the title lookup that were not
    taken. ``tried``: one line per lookup, in order. ``message``: the outcome in a sentence.
    ``prefill``: what was read, for the model or manual step."""
    intake: PdfIntake
    proposal: object = None
    found_by: Identifier | None = None
    candidates: list = field(default_factory=list)
    tried: list = field(default_factory=list)
    message: str = ""
    prefill: dict = field(default_factory=dict)

    @property
    def matched(self):
        return self.proposal is not None

    DATA_PROPERTIES = ("matched",)

    def to_data(self):
        return to_data(self)


def prefill_from(intake, proposal=None):
    """Fields for a manual form from what was read: the title guess, the first DOI printed
    in the PDF and, from a model reading, the fields it kept and the values it left unfilled."""
    fields = {}
    if intake is not None:
        if intake.title_guess:
            fields["title"] = intake.title_guess
        doi = next((i.value for i in intake.identifiers if i.kind == "doi"), None)
        if doi:
            fields["doi"] = doi
    if proposal is not None:
        for missing in proposal.unfilled:
            for value in missing.source_values.values():
                if value and missing.field != "ENTRYTYPE":
                    fields[missing.field] = value
        read = (getattr(proposal, "evidence", None) or {}).get("fields") or {}
        fields.update({name: found["value"] for name, found in read.items()})
    return {k: v for k, v in fields.items() if k not in ("ENTRYTYPE", "ID") and isinstance(v, str) and v.strip()}


def propose_from_pdf(ws, intake, client=None, mailto=None, database=None, progress=None):
    """Find the source record of a PDF that ``read_pdf`` read and build its entry.

    The identifiers are tried in the order DOI, arXiv, PMID (each kind in reading order),
    then the title guess, each through ``complete.propose``; the first that gives a built
    entry is the answer. The built entry's title is then looked for on the PDF's first
    pages (``title_on_pages``): when it is not there, or the PDF gave no text to compare,
    the proposal says so in ``issues`` and needs a decision, so a different work is never
    taken silently. A title lookup takes a record only as ``complete.identify`` does;
    other records it finds are returned as ``candidates``. When nothing matches,
    ``proposal`` is None and ``message`` says so.
    """
    from .verification import ProviderError
    result = PdfResult(intake=intake, prefill=prefill_from(intake))
    order = {"doi": 0, "arxiv": 1, "pmid": 2}
    lookups = [(i, complete.Query(**{i.kind: i.value}))
               for i in sorted(intake.identifiers, key=lambda i: order[i.kind])]
    if intake.title_guess:
        author = " ".join(intake.metadata.get("author", "").split())
        first = re.split(r"\s*(?:;|,|&|\band\b)\s*", author)[0] if author else ""
        named = Identifier("title", intake.title_guess, 1 if intake.title_source != "PDF metadata" else None,
                           intake.title_guess)
        if len(first.split()) >= 2:
            lookups.append((named, complete.Query(title=intake.title_guess, author=first)))
        lookups.append((named, complete.Query(title=intake.title_guess)))
    if not lookups:
        result.message = "No DOI, arXiv id, PMID or title could be read from the PDF, so no record was looked up."
        return result
    with _Client(ws, client, mailto, database) as client:
        for found_by, query in lookups:
            label = f"{found_by.kind} {found_by.value}" + (f" (first author {query.author})" if query.author else "")
            try:
                proposal = complete.propose(query, client, client.cache, ws=ws)
            except (CdlbibError, OSError, ValueError, TypeError, ProviderError, sqlite3.Error) as exc:
                result.tried.append(f"{label}: {exc}")
                continue
            finally:
                if progress:
                    progress(f"Looked up {label}")
            if not proposal.proposed_raw:
                result.tried.append(f"{label}: " + ("; ".join(proposal.issues) or "no record"))
                if found_by.kind == "title":
                    result.candidates = result.candidates or list(proposal.candidates)
                continue
            where = "its metadata" if found_by.page is None else f"page {found_by.page}"
            proposal.notes.insert(0, f"Found by the {found_by.kind} read from the PDF ({where}): {found_by.value}")
            title = complete._completion_fields(proposal).get("title") or ""
            if not any(p["text"].strip() for p in intake.pages):
                proposal.issues.append("The PDF gave no text, so the record's title could not be compared with it; "
                                       "check that this record is the PDF's work")
                proposal.needs_decision = True
            elif not title_on_pages(intake.pages, title):
                proposal.issues.append(
                    f"The title of the record found by this {found_by.kind} ({title}) is not on the first "
                    f"{min(TITLE_PAGES, len(intake.pages))} page(s) of the PDF: the record may be a different work "
                    "(an identifier printed in the PDF can belong to another paper). Nothing is taken without a decision")
                proposal.needs_decision = True
            result.tried.append(f"{label}: record found")
            result.proposal, result.found_by = proposal, found_by
            result.message = f"A source record was found by the {found_by.kind} read from the PDF."
            return result
    result.message = ("No source record was found for this PDF"
                      + (f"; {len(result.candidates)} similar record(s) are listed to choose from" if result.candidates else "")
                      + ". It can be read with a language model, or typed in by hand.")
    return result


# --- model reading ------------------------------------------------------------------------------

@dataclass
class ModelRoute:
    name: str          # "dartmouth" or "openai"
    label: str
    available: bool | None   # None: not checked (the stored key was not looked up)
    how: str           # how to set it up; shown whether or not it is available
    default: bool = False
    detail: str = ""   # when it is not available (or not checked): exactly what is missing or wrong


_ROUTE_KEYS = {"dartmouth": "dartmouth-chat", "openai": "openai"}


OPENAI_MODEL_HOW = ("Set the environment variable BIBCHECK_RESEARCH_MODEL to the OpenAI model to use "
                    "(e.g. `export BIBCHECK_RESEARCH_MODEL=<model name>`).")


def route_state(route, environ=None, stored=False):
    """(whether ``route`` can be used: True, False, or None for "not checked"; what exactly is
    missing or wrong, "" when nothing is). The one rule, for ``model_routes`` and for
    ``api.features``. Without ``stored`` only the environment is looked at (no keychain, so
    no consent dialog and no wait): True when the key's variable holds one token (and, for
    OpenAI, a model is named), False when what is set cannot work, None when the variable
    is not set. With ``stored`` the key is looked up as the adapter will (``secrets.get``:
    the variable, then the keychain), for this route only."""
    from . import secrets
    source = os.environ if environ is None else environ
    variable = secrets.KEYS[_ROUTE_KEYS[route]].env
    value = source.get(variable) or ""
    model = route != "openai" or bool(source.get("BIBCHECK_RESEARCH_MODEL"))
    no_model = "the model to use is not named: the environment variable BIBCHECK_RESEARCH_MODEL is not set"
    if value:
        if any(char.isspace() for char in value):
            return False, f"the environment variable {variable} holds whitespace; a key is a single token"
        return (True, "") if model else (False, no_model)
    if not stored:
        return None, f"not checked: {variable} is not set, and the system keychain was not read"
    try:
        secrets.get(_ROUTE_KEYS[route], environ)
    except SecretNotFound:
        return False, "no API key was found" + ("" if model else "; and " + no_model)
    return (True, "") if model else (False, no_model)


def model_routes(probe=(), environ=None):
    """The model routes, Dartmouth Chat (the default) first, each with ``how`` to set it up
    whether or not it is. ``available`` is passive unless the route is named in ``probe``:
    True when the key's environment variable is set, otherwise None ("not checked"; the
    keychain is not opened). For a route in ``probe`` (e.g. ``probe=("dartmouth",)``) the
    stored key is looked up too and ``available`` is True or False. No key is returned."""
    from . import secrets
    unknown = [name for name in probe if name not in _ROUTE_KEYS]
    if unknown:
        raise CdlbibError(f"Unknown model route {unknown[0]!r}; the routes are {', '.join(_ROUTE_KEYS)}.")
    dartmouth, openai = (route_state(name, environ, name in probe) for name in ("dartmouth", "openai"))
    return [
        ModelRoute("dartmouth", "Dartmouth Chat", dartmouth[0],
                   f"Create an API key in Dartmouth Chat (steps: {DARTMOUTH_KEY_PAGE}). "
                   + secrets.places("dartmouth-chat") + " Only models the Dartmouth catalogue lists as free are used.",
                   default=True, detail=dartmouth[1]),
        ModelRoute("openai", "OpenAI", openai[0],
                   "Create an OpenAI API key. " + secrets.places("openai")
                   + " Also set the environment variable BIBCHECK_RESEARCH_MODEL to the model to use.",
                   detail=openai[1]),
    ]


@dataclass
class ModelProposal(complete.Proposal):
    """A proposal read from a PDF by a model. ``evidence``: what ``evidence_for`` stores."""
    evidence: dict | None = None

    def to_data(self):
        return to_data(self)


def _adapter(route):
    name = ADAPTERS[route]
    beside = Path(sys.executable).parent / name
    located = str(beside) if beside.exists() else shutil.which(name)
    if not located:
        raise CdlbibError(f"The command {name} was not found; it is installed with cdlbib.")
    return located


def _house(entry_type, fields):
    """``fields`` as the format checker writes them: (fields, what it changed {name: new},
    names it removed, why it could not run or None). One entry in a temporary file through
    ``helpers.check_bib`` with autofix, as ``complete.checked`` reads one entry."""
    import contextlib
    import io
    import tempfile
    from .helpers import check_bib
    from .verification import load_entries
    with tempfile.TemporaryDirectory(prefix="cdlbib-draft-") as folder:
        path = Path(folder) / "draft.bib"
        path.write_text(complete.render(entry_type, "Draft", fields) + "\n", encoding="utf-8")
        try:
            load_entries(path)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                _, polished = check_bib(str(path), autofix=True, verbose=False)
            written = dict(list(polished)[0])  # the corrected entry; its key is planned separately
        except Exception as exc:  # noqa: BLE001 - check_bib raises plain exceptions on entries it cannot judge
            return dict(fields), {}, [], f"{type(exc).__name__}: {exc}"
    written = {k: v for k, v in written.items() if k not in ("ENTRYTYPE", "ID")}
    changed = {name: value for name, value in written.items() if fields.get(name) != value}
    return written, changed, sorted(set(fields) - set(written)), None


_ENTRY_SYNTAX = re.compile(r"@\s*[A-Za-z]+\s*[{(]")
# Words that address a program reading the page. Used for ONE thing: a note a person sees
# (``addressed_to_a_model``). It is a list of phrases and is trivially avoided, so nothing
# is kept, dropped or cleaned because of it; what a reading may contain is decided by
# ``derivation`` and the fixed lists below, whatever the PDF says.
_ADDRESSED = re.compile(r"(?i)\b(?:ignore|disregard|override)\b.{0,60}\binstructions?\b|\bsystem prompt\b"
                        r"|\b(?:language model|ai assistant|chatbot)\b")
MODEL_FIELDS = ("title", "author", "year", "journal", "booktitle", "volume", "number", "pages", "publisher",
                "doi", "isbn", "issn", "edition")   # the only field names a reading can fill
DRAFT_TYPES = ("article", "book", "incollection", "inproceedings", "inbook", "phdthesis", "mastersthesis",
               "techreport", "misc", "unpublished", "proceedings", "manual", "booklet")
# A flagged passage whose value is still written, as a question, rather than left unfilled.
QUESTION_RISKS = {"author": ("reference_list", "affiliation_line", "possible_omitted_author"),
                  "year": ("receipt_or_revision_date", "copyright_line", "preprint_version_stamp")}
KNOWN_RISKS = ("reference_list", "receipt_or_revision_date", "copyright_line", "preprint_version_stamp",
               "affiliation_line", "institution_named_as_venue", "possible_omitted_author")


def addressed_to_a_model(pages):
    """Whether the pages hold words that address a language model. For a note only."""
    return any(_ADDRESSED.search(" ".join(page["text"].split())) for page in pages)


def _tokens(text):
    """Lower-case runs of letters and digits after the PDF text fold (ligatures, full-width
    forms); accents are kept, and a look-alike letter of another script is another letter."""
    from .pdf_evidence import fold
    return re.findall(r"[^\W_]+", fold(str(text)).lower())


def _within(part, whole):
    """Whether the token list ``part`` occurs in ``whole`` as one unbroken run."""
    size = len(part)
    return bool(size) and any(whole[i:i + size] == part for i in range(len(whole) - size + 1))


def derivation(name, value, quote):
    """The fixed rule by which ``value`` follows from ``quote`` (text of the PDF's page, as
    this program extracted it), or None when it does not. One rule per field, none of them
    set by the reply or by the PDF:

    - ``year``: four digits that stand in the quote as a number of their own;
    - ``volume``, ``number``, ``edition``: one token that is a token of the quote;
    - ``pages``: one or two page numbers (``45`` or ``45-67``), each a token of the quote;
    - ``doi``: a DOI (``complete._doi_text``) that ``pdf_evidence.DOI_RX`` finds in the quote;
    - ``year``: also between 1500 and next year;
    - ``isbn``, ``issn``: the quote prints one, as one number with a right check digit, and
      it is the value's (digits of separate numbers are never joined);
    - ``author``: every name, split at `` and ``, has two or more tokens, its family name
      (the last, or the first before a comma) of two or more letters, and is an unbroken run of the quote's tokens; the names stand
      in the quote in the value's order without overlapping;
    - ``title``, ``journal``, ``booktitle``, ``publisher``: the value's tokens (two or more,
      or one of four or more letters) are one unbroken run of the quote's tokens.
    """
    from .pdf_evidence import DOI_RX, fold
    from .verification import normalize_doi
    value, words = " ".join(str(value).split()), _tokens(quote)
    if not value or name not in MODEL_FIELDS:
        return None
    if name == "year":
        from datetime import date
        alone = (re.fullmatch(r"\d{4}", value) and 1500 <= int(value) <= date.today().year + 1
                 and re.search(  # not a part of a DOI, an ISSN, a date or a decimal
                     r"(?<![\w./-])" + value + r"(?![\w/-]|\.\d)", fold(quote)))
        return "a four-digit year in the quotation" if alone else None
    if name in ("volume", "number", "edition"):
        own = _tokens(value)
        return "a token of the quotation" if len(own) == 1 and own[0] in words else None
    if name == "pages":
        parts = re.fullmatch(r"([A-Za-z]{0,3}\d+)(?:\s*(?:-{1,2}|\u2013|\u2014)\s*([A-Za-z]{0,3}\d+))?", value)
        if not parts or any(part and part.lower() not in words for part in parts.groups()):
            return None
        return "page numbers in the quotation"
    if name == "doi":
        own = complete._doi_text(value)
        try:
            found = {normalize_doi(complete._doi_text(m[1]) or "") for m in DOI_RX.finditer(fold(quote))
                     if complete._doi_text(m[1])}
            return "a DOI in the quotation" if own and normalize_doi(own) in found else None
        except ValueError:
            return None
    if name in ("isbn", "issn"):
        own = _standard_number(name, value)
        printed = {_standard_number(name, m[0]) for m in _PRINTED_NUMBER[name].finditer(fold(quote))}
        return f"a valid {name.upper()} printed in the quotation" if own and own in printed else None
    if name == "author":
        # Each name as printed: at least two tokens, one of them a family name of two or more
        # letters; the names in the quotation in the value's order, none overlapping another.
        # A footnote digit set against a surname ("Example1") is not part of the name.
        names = [(_tokens(n), "," in n) for n in re.split(r"\s+and\s+", value)]
        printed, position = [re.sub(r"(?<=[^\W\d_])\d+$", "", word) for word in words], 0
        for tokens, family_first in names:
            family = tokens[0 if family_first else -1] if tokens else ""  # "Example, Ada" or "Ada Example"
            if len(tokens) < 2 or not (len(family) >= 2 and family.isalpha()):
                return None
            start = next((i for i in range(position, len(printed) - len(tokens) + 1)
                          if printed[i:i + len(tokens)] == tokens), None)
            if start is None:
                return None
            position = start + len(tokens)
        return "each name, in order, in the quotation" if names else None
    own = _tokens(value)
    if not (len(own) >= 2 or (len(own) == 1 and sum(c.isalpha() for c in own[0]) >= 4)):
        return None  # one short token grounds nothing
    return "its words, in order, in the quotation" if _within(own, words) else None


_PRINTED_NUMBER = {
    "issn": re.compile(r"(?<![0-9A-Za-z])\d{4}[-\u2010-\u2015]?\d{3}[\dXx](?![0-9A-Za-z])"),
    "isbn": re.compile(r"(?<![0-9A-Za-z])(?:(?:\d[- ]?){12}\d|(?:\d[- ]?){9}[\dXx])(?![0-9A-Za-z])"),
}


def _standard_number(kind, text):
    """An ISSN or ISBN as its digits (and X), when ``text`` is one as printed and its check
    digit is right; else None."""
    if not _PRINTED_NUMBER[kind].fullmatch(text.strip()):
        return None
    digits = re.sub(r"[^0-9Xx]", "", text).upper()
    if "X" in digits[:-1]:
        return None
    values = [10 if c == "X" else int(c) for c in digits]
    if len(digits) == 8 and kind == "issn":
        valid = sum(v * w for v, w in zip(values, range(8, 0, -1))) % 11 == 0
    elif len(digits) == 10 and kind == "isbn":
        valid = sum(v * w for v, w in zip(values, range(10, 0, -1))) % 11 == 0
    elif len(digits) == 13 and kind == "isbn":
        valid = sum(v * (1, 3)[i % 2] for i, v in enumerate(values)) % 10 == 0
    else:
        valid = False
    return digits if valid else None


# The control sequences a typed value may hold without a question: the accent and letter
# commands and the text commands ``verification.normalized`` reads, and the text and maths
# commands the library's entries use (counted in tests/fixtures/cdl-prewave1-2026-09-26.bib).
ALLOWED_COMMANDS = frozenset(
    "c v u H r k b d t ae AE aa AA oe OE o O l L ss i j "
    "textit textbf emph textrm texttt textsc textnormal textsuperscript textsubscript LaTeX TeX "
    "textasciitilde textasciicircum textregistered texttrademark url "
    "alpha beta gamma delta epsilon theta lambda mu pi sigma tau phi chi psi omega times pm".split())
ALLOWED_SYMBOLS = frozenset("'`^\"~=. &%_{}#$,-")
# Never written, typed or not: they read or write files, run commands or redefine TeX.
FORBIDDEN_COMMANDS = frozenset(
    "input include write openout immediate csname endcsname catcode def let read special directlua "
    "edef gdef xdef futurelet expandafter newcommand renewcommand providecommand usepackage "
    "openin closeout closein newwrite newread latelua luaexec scantokens verbatiminput lstinputlisting "
    "includegraphics InputIfFileExists IfFileExists ShellEscape".split())
VERBATIM_FIELDS = ("doi",)   # written as given: a DOI's underscore is not escaped in the library
_TEX_SPECIAL = {"&": "\\&", "%": "\\%", "#": "\\#", "$": "\\$", "_": "\\_",
                "~": "\\textasciitilde{}", "^": "\\textasciicircum{}"}


def plain_text_problem(name, value):
    """Why ``value``, read from a PDF or by a model, cannot be taken as plain text, or None.
    Such a value is text, never markup: it may hold no backslash, no brace, no ``^^`` and no
    control character (a DOI, which is written as it is, no TeX special either)."""
    if "\\" in value or "{" in value or "}" in value:
        return "a backslash or a brace (LaTeX markup, which text read from a PDF may not bring)"
    if "^^" in value:
        return "the TeX character notation ^^"
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return "a control character"
    if name in VERBATIM_FIELDS and re.search(r"[%#&$~^\s]", value):
        return "a character a DOI field cannot hold"
    return None


def escape_plain(name, value):
    """Plain text as TeX text: ``% # & $ _ ~ ^`` are escaped (the house formatter has no
    escaper of its own; this is the only one, used for text read from a PDF or by a
    model). A ``VERBATIM_FIELDS`` value is returned as it is."""
    return value if name in VERBATIM_FIELDS else re.sub(r"[&%#$_~^]", lambda m: _TEX_SPECIAL[m[0]], value)


def latex_problems(name, value):
    """(why a typed value is refused or None, questions about it). Refused: a command of
    ``FORBIDDEN_COMMANDS``, ``^^``, and a ``%`` that is not written ``\\%`` (it would comment
    out the rest of the line). Asked about: every other control sequence outside
    ``ALLOWED_COMMANDS`` / ``ALLOWED_SYMBOLS``, and a ``#`` or ``&`` not written with a backslash."""
    if "^^" in value:
        return "the TeX character notation ^^", []
    commands = re.findall(r"\\([A-Za-z@]+)", value)
    banned = [c for c in commands if c in FORBIDDEN_COMMANDS or "@" in c]
    if banned:
        return f"the command \\{banned[0]}, which is never written into the library", []
    bare = re.sub(r"\\.", "", value)  # what is left when every control sequence's first character is gone
    if "%" in bare and name not in VERBATIM_FIELDS:
        return "a % that is not written \\% (TeX would ignore the rest of the line)", []
    asked = [f"{name}: the command \\{c} is not one the library's entries use; check that it is meant"
             for c in dict.fromkeys(commands) if c not in ALLOWED_COMMANDS]
    asked += [f"{name}: the control symbol \\{c} is not one the library's entries use; check that it is meant"
              for c in dict.fromkeys(re.findall(r"\\([^A-Za-z@])", value)) if c not in ALLOWED_SYMBOLS]
    asked += [f"{name}: {c} is not written \\{c}; TeX reads a bare {c} as markup"
              for c in "#&" if c in bare and name not in VERBATIM_FIELDS]
    return None, asked


def scan_entry(raw):
    """(entry type, key, {field: value}) of ``raw`` read by a strict scanner that accepts
    only what ``complete.render`` writes: ``@type{Key`` then, for each field, ``,``, white
    space, ``name = {value}`` with the value's braces paired, and one closing ``}`` with
    nothing after it. No ``"`` delimiters, no ``#`` concatenation, no ``%``, no second
    entry, no repeated field. Raises ``ValueError`` saying what was found instead."""
    head = re.match(r"@([A-Za-z]+)\{([^\s,{}%#\"'@=\\()]+)", raw)
    if not head:
        raise ValueError("no @type{key header")
    position, fields = head.end(), {}
    while True:
        if raw[position:] == "}":
            return head[1].lower(), head[2], fields
        field = re.compile(r",\s*([A-Za-z][A-Za-z0-9_-]*) = \{").match(raw, position)
        if not field:
            raise ValueError(f"unexpected text at character {position}: {raw[position:position + 20]!r}")
        name, depth, end = field[1].lower(), 1, field.end()
        while depth and end < len(raw):
            depth += (raw[end] == "{") - (raw[end] == "}")
            end += 1
        if depth:
            raise ValueError(f"the value of {name} is never closed")
        if name in fields:
            raise ValueError(f"the field {name} is written twice")
        fields[name], position = raw[field.end():end - 1], end


def structure_problem(value):
    """Why ``value`` cannot be written as one field value, or None. A value may not change
    the structure of the entry it is written into: its braces must pair up (never closing
    one it did not open), it may not end in a backslash (which would take the closing
    brace), hold a control character, or hold the start of an entry (``@type{``)."""
    depth = 0
    for char in value:
        depth += (char == "{") - (char == "}")
        if depth < 0:
            return "a closing brace with no opening brace before it"
    if depth:
        return "an opening brace that is never closed"
    if (len(value) - len(value.rstrip("\\"))) % 2:
        return "a backslash at the end"
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return "a control character"
    if _ENTRY_SYNTAX.search(value):
        return "the start of a BibTeX entry (@type{)"
    if "^^" in value:
        return "the TeX character notation ^^"
    return None


def _proved(raw, entry_type, fields):
    """Refuse (``CdlbibError``) unless ``raw`` reads back, by the library's own reader
    (``verification.load_entries``), as exactly one entry of ``entry_type`` whose field
    names and values are exactly ``fields``, AND ``scan_entry`` (a strict scanner of the
    rendered text itself, which shares nothing with that reader) finds the same type, one
    key and the same fields: the text holds nothing that was not checked."""
    import tempfile
    from .verification import load_entries
    try:
        kind, _, scanned = scan_entry(raw)
    except ValueError as exc:
        raise CdlbibError(f"The drafted text is not one plainly written entry ({exc}); nothing is proposed.") from exc
    if kind != entry_type or scanned != fields:
        differing = sorted(n for n in set(scanned) | set(fields) if scanned.get(n) != fields.get(n))
        raise CdlbibError("The drafted text does not hold exactly the fields that were checked "
                          f"({', '.join(differing) or 'entry type'}); nothing is proposed.")
    with tempfile.TemporaryDirectory(prefix="cdlbib-draft-") as folder:
        path = Path(folder) / "rendered.bib"
        path.write_text(raw + "\n", encoding="utf-8")
        try:
            entries = load_entries(path)
        except ValueError as exc:
            raise CdlbibError(f"The drafted entry does not read back as BibTeX ({exc}); nothing is proposed.") from exc
    read = [dict(entry["fields"]) for entry in entries.values()]
    if len(read) != 1:
        raise CdlbibError(f"The drafted text reads back as {len(read)} entries, not one; nothing is proposed.")
    kind = str(read[0].pop("ENTRYTYPE", "")).lower()
    read[0].pop("ID", None)
    if kind != entry_type or read[0] != fields:
        differing = sorted(n for n in set(read[0]) | set(fields) if read[0].get(n) != fields.get(n))
        raise CdlbibError("The drafted entry does not read back as the fields that were checked "
                          f"({', '.join(differing) or 'entry type'}); nothing is proposed.")


def _draft(ws, entry_type, values, sources, unfilled, notes, kind, plain=(), questions=None):
    """The manual proposal for ``values`` ({field: text}); ``sources`` {field: where from}.

    The one place a model-read or typed entry is rendered. Every value is refused before
    rendering when it could change the entry's structure (``structure_problem``), again
    after the formatter, and the rendered text must read back as exactly the checked
    fields (``_proved``). Nothing is repaired silently: a refusal is a ``CdlbibError``.

    ``plain``: the fields whose value was read from a PDF or by a model. Such a value is
    plain text: one with LaTeX markup in it (``plain_text_problem``) is left ``Unfilled``
    with the reason, and the others have their TeX specials escaped (``escape_plain``), so
    the only backslashes in them are that escaper's and the house accent conversion's. Any
    other value was typed by a person and may hold LaTeX: ``latex_problems`` refuses what is
    never written and turns an unfamiliar command into an issue. ``questions``
    {field: reason}: kept fields that are a ``question``, with the reason in ``issues``."""
    questions, unfilled, asked = dict(questions or {}), list(unfilled), []
    entry_type = str(entry_type or "article").strip().lower()
    if not re.fullmatch(r"[a-z]+", entry_type):
        raise CdlbibError(f"Not an entry type: {entry_type!r}")
    typed = {}
    for name, value in values.items():
        name, value = str(name).strip().lower(), " ".join(str(value or "").split())
        if name in ("entrytype", "id") or not value:
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise CdlbibError(f"Not a field name: {name!r}")
        if name == "force":  # the format checker skips an entry that has it; a draft follows the house rules
            raise CdlbibError("A draft cannot have a 'force' field.")
        if name in plain:
            problem = plain_text_problem(name, value)
            if problem:
                unfilled.append(complete.Unfilled(
                    name, f"{name}: the value has {problem}; it is not written", {sources.get(name, "read"): value}))
                continue
        else:
            problem = structure_problem(value) or latex_problems(name, value)[0]
            if problem:
                raise CdlbibError(f"{name}: the value has {problem}, so it cannot be written as one field; correct it.")
            asked += latex_problems(name, value)[1]
        typed[name] = value
    if not typed:
        raise CdlbibError("There is nothing to draft: no field has a value that can be written"
                          + ("".join(f"; {u.reason}" for u in unfilled) if unfilled else "") + ".")
    given = {name: complete.latex_text(escape_plain(name, value) if name in plain else value)
             for name, value in typed.items()}
    fields, changed, removed, failure = _house(entry_type, given)
    for name, value in fields.items():
        problem = structure_problem(value) if isinstance(value, str) else "a value that is not text"
        if problem or not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise CdlbibError(f"{name}: after formatting the value has {problem or 'no valid field name'}; "
                              "nothing is proposed.")
    proposal = ModelProposal(entry_type=entry_type, status="needs_review", manual=True, needs_decision=True,
                             notes=[NO_SOURCE, *notes], unfilled=unfilled, doi=fields.get("doi"), issues=asked)
    if failure:
        proposal.issues.append(f"The format check could not run on this entry ({failure}); it is written as given")
    for name in sorted(typed):
        source = sources.get(name, "typed")
        shown = typed[name] if kind == "typed" else None
        if name in removed:
            proposal.changes.append(complete.FieldChange(name, typed[name], None, "house format", "dropped"))
        elif name in questions:
            proposal.changes.append(complete.FieldChange(name, shown, fields[name], source, "question"))
            proposal.issues.append(questions[name])
        elif kind == "typed" and fields[name] != typed[name]:
            proposal.changes.append(complete.FieldChange(
                name, shown, fields[name], f"{sources[name]}; house format" if name in sources else "house format",
                "changed"))
        else:
            proposal.changes.append(complete.FieldChange(name, shown, fields[name], source,
                                                         "kept" if kind == "typed" else "filled"))
        if name in changed and name not in removed:
            proposal.notes.append(f"{name}: written in house format ({typed[name]} -> {fields[name]})")
        for char_issue in complete._character_question(name, typed[name]):
            proposal.issues.append(char_issue)
    if entry_type == "article":
        named = {u.field for u in proposal.unfilled}
        proposal.unfilled += [complete.Unfilled(name, f"{name}: not given", {}) for name in complete.EXPECTED_FIELDS
                              if name not in fields and name not in named]
    proposal.proposed_raw = complete.render(entry_type, complete.NO_KEY, fields)
    if not (fields.get("author") and fields.get("year")):
        proposal.issues.append("No citation key can be made without an author and a year")
    try:
        complete._plan_proposal(ws, proposal, complete.Query(), ())
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        proposal.issues.append(f"The key and the duplicate check could not be made ({exc})")
    complete._set_complete(proposal, fields)
    proposal.needs_decision = True
    _proved(proposal.proposed_raw, entry_type, fields)
    return proposal


def proposal_from_findings(ws, intake, extracted, route="dartmouth", entry_type="article"):
    """The proposal for an adapter's ``extract`` answer, checked against the PDF's pages.

    The answer is untrusted data, and so is the PDF it was made from: no wording in either
    can add to what is kept. A field is kept only when all of this holds, each decided here:

    - its name is one of ``MODEL_FIELDS`` (anything else in the answer, such as a status,
      an approval or a key, is dropped; ``ENTRYTYPE`` is never taken from the answer);
    - ``research.validate_findings`` finds its quotation, white space apart, in the text of
      the stated page as this program extracted it (``intake.pages``), and every passage
      is that page's text at the stated offsets;
    - ``derivation`` gives the rule by which the value follows from that quotation;
    - the adapter did not withdraw it (``grounding``): it can only take a field away;
    - the quoted passage's role is not in doubt (``source_passages.role_risks`` judged here
      from the page, and the adapter's flags). An author or a year in a passage flagged as
      ``QUESTION_RISKS`` lists is written as a ``question`` with the reason in ``issues``;
    - the value is plain text (``plain_text_problem``: no backslash, brace or ``^^``); its
      TeX specials are escaped when it is written (``escape_plain``).

    Every other field is ``Unfilled`` with the reason and the model's value. A kept field
    is a ``FieldChange`` whose source names the page and the quotation. The entry type is
    the caller's, from ``DRAFT_TYPES``. The entry is written in house format, keyed by
    ``plan_key`` and checked for duplicates. Whatever the answer holds, the proposal has no
    source record (``manual=True``, ``status="needs_review"``), always needs a decision, and
    only a logged-in person's approval can change that (``api.approve``). A value the PDF
    itself prints is grounded even when the PDF is wrong or was written to mislead: the
    quotation beside each field is there for the person to compare with the page.
    """
    from .research import validate_findings
    from .source_passages import REFERENCE_HEADING, role_risks
    from .verification import now
    read = extracted.get("fields") if isinstance(extracted, dict) else None
    if not isinstance(read, dict) or not read:
        raise CdlbibError("The model returned no fields for this PDF.")
    entry_type = str(entry_type or "").strip().lower()
    if entry_type not in DRAFT_TYPES:
        raise CdlbibError(f"Not an entry type a draft can have: {_plain(entry_type, 30)!r}.")
    pages = intake.pages
    flagged = extracted.get("role_risk_fields") if isinstance(extracted.get("role_risk_fields"), dict) else {}
    kept, unfilled, dropped, doubts = {}, [], 0, {}
    for name, evidence in list(read.items())[:50]:
        if name == "ENTRYTYPE":
            unfilled.append(complete.Unfilled("ENTRYTYPE", "ENTRYTYPE: the entry type is chosen by the person, "
                                                           "not read by the model", {}))
            continue
        if name not in MODEL_FIELDS:  # status, approved, key, anything else: not a field a reading has
            dropped += 1
            continue
        value = evidence.get("value") if isinstance(evidence, dict) else None
        value = " ".join(value.split())[:2000] if isinstance(value, str) else None
        said = {f"model reading ({route})": value} if value else {}
        try:  # the quotation, and every passage, must be text of the stated page as read here
            validate_findings({"fields": {name: evidence}}, pages)
        except ValueError as exc:
            unfilled.append(complete.Unfilled(name, f"not kept: {exc}", said))
            continue
        if not said:
            unfilled.append(complete.Unfilled(name, f"{name}: the model gave no value", {}))
            continue
        spans = [{k: span[k] for k in ("id", "page", "start", "end", "quote") if k in span}
                 for span in evidence.get("passages") or []]
        quote = "".join(span["quote"] for span in spans) or evidence["quote"]
        rule = derivation(name, value, quote)
        # What the adapter says against a field is heeded (it can only withdraw one); what it
        # says for a field is not: the rule above decides.
        withdrawn = evidence.get("grounding", "literal_text_present") != "literal_text_present"
        # The role of the quoted passage, judged here from the page (source_passages.role_risks),
        # together with what the adapter flagged; a flag can hold a field back, never grant it.
        text = next(p["text"] for p in pages if p["page"] == evidence["page"])
        heading, first = REFERENCE_HEADING.search(text), (quote.strip().splitlines() or [""])[0]
        at = spans[0]["start"] if spans and isinstance(spans[0].get("start"), int) else text.find(first)
        own = role_risks(name, value, [quote], bool(heading) and at >= heading.end())
        risks = [r for r in [*own, *(evidence.get("role_risk") or []), *(flagged.get(name) or [])] if r in KNOWN_RISKS]
        risks = list(dict.fromkeys(risks))
        broken = plain_text_problem(name, value)
        if broken:
            unfilled.append(complete.Unfilled(
                name, f"{name}: the value has {broken}; it is not written", said))
        elif not rule or withdrawn:
            unfilled.append(complete.Unfilled(
                name, f"{name}: the value is not literally in the quoted text (page {evidence['page']}); "
                      "it is the model's interpretation", said))
        elif risks and not set(risks) <= set(QUESTION_RISKS.get(name, ())):
            unfilled.append(complete.Unfilled(
                name, f"{name}: the quoted text (page {evidence['page']}) may play another role "
                      f"({', '.join(risks)}), so it is not taken as the work's own {name}", said))
        else:
            if risks:  # written, as a question the person settles
                doubts[name] = (f"{name}: the quoted text (page {evidence['page']}) may play another role "
                                f"({', '.join(risks)}); check that {value} is the work's own {name}")
            kept[name] = {"value": value, "page": evidence["page"], "quote": evidence["quote"],
                          **({"passages": spans} if spans else {}), "derivation": rule}
    if not kept:
        raise CdlbibError("The model reading gave no field that its quotation supports: "
                          + "; ".join(u.reason for u in unfilled))
    def quoted(evidence):  # every selected passage, in page order, on one line
        return " ".join("".join(span["quote"] for span in evidence.get("passages") or []).split()
                        or evidence["quote"].split())

    sources = {name: f'model reading, p.{e["page"]}: "{quoted(e)}"' for name, e in kept.items()}
    left = tuple(f"{u.field}: " for u in unfilled) or ("\0",)  # said once, as the reason the field is unfilled
    said_too = extracted.get("uncertainties") if isinstance(extracted.get("uncertainties"), list) else []
    uncertainties = [_plain(u, 300) for u in said_too[:20] if isinstance(u, str)]
    notes = ([f"Read by a language model ({route}) from {intake.path.name}; every kept field quotes the page it was read from."]
             + (["The PDF's text is OCR output, which misreads characters."] if intake.ocr else [])
             + ([f"{dropped} item(s) of the model's answer were not bibliographic fields and were dropped."]
                if dropped else [])
             + (["This PDF contains text addressed to a language model; compare each quoted field with the page."]
                if addressed_to_a_model(pages) else []))
    proposal = _draft(ws, entry_type, {name: e["value"] for name, e in kept.items()}, sources, unfilled, notes,
                      "model", plain=set(kept), questions=doubts)
    proposal.issues += [f"model: {u}" for u in uncertainties if not u.startswith(left)]
    proposal.evidence = {
        "source": "local PDF read by a language model",
        "pdf_sha256": intake.sha256,
        "pdf_name": intake.path.name,
        "ocr": intake.ocr,
        "retrieved_at": now(),
        "reviewer": "model-reading:" + route,
        "fields": kept,
        "unsupported_fields": [{"field": u.field, "reason": u.reason, "values": u.source_values} for u in unfilled],
        "uncertainties": uncertainties,
        "extraction_policy": _plain(extracted.get("extraction_policy"), 60) or None,
        "provider_trace": {"extract": extracted.get("provider_trace")
                           if len(json.dumps(extracted.get("provider_trace"), default=str)) <= 20_000 else None},
        "quote_check": QUOTE_CHECK,
    }
    return proposal


def read_pdf_with_model(ws, intake, route="dartmouth", progress=None, entry_type="article"):
    """Have a model read the PDF's front matter (``MODEL_PAGES`` pages) and propose an entry.

    The route's installed adapter is run through ``research.invoke_adapter`` with the
    ``extract`` phase of the research protocol, so the Dartmouth adapter makes its
    free-model check before any inference; the answer goes through
    ``proposal_from_findings``. Only the chosen route's key is looked up. Raises
    ``SecretNotFound`` (a ``CdlbibError``) with the setup instructions when it is missing, and
    ``CdlbibError`` when the route is unknown, when the PDF gave no text, or when the adapter fails. Nothing is written; the
    proposal is never a verification.
    """
    from .research import INSTRUCTIONS, invoke_adapter
    if route not in _ROUTE_KEYS:
        raise CdlbibError(f"Unknown model route {route!r}; the routes are {', '.join(_ROUTE_KEYS)}.")
    chosen = next(r for r in model_routes(probe=(route,)) if r.name == route)  # this route's key only
    if not chosen.available:
        raise SecretNotFound(f"{chosen.label} is not set up. {chosen.how}")
    pages = [p for p in intake.pages[:MODEL_PAGES]]
    if not any(p["text"].strip() for p in pages):
        raise CdlbibError("The PDF gave no text for a model to read" + (f" ({intake.detail})" if intake.detail else "."))
    if progress:
        progress(f"Asking {chosen.label} to read {len(pages)} page{'s' if len(pages) != 1 else ''} of {intake.path.name}")
    try:
        extracted = invoke_adapter(_adapter(route), {
            "phase": "extract", "instructions": INSTRUCTIONS, "entry": {}, "pages": pages,
            "output_schema": {"fields": {"title": {"value": "...", "page": 1, "quote": "..."}},
                              "uncertainties": ["Missing fields, discrepancies, edition concerns"]}})
    except ValueError as exc:
        raise CdlbibError(f"{chosen.label} did not return a reading ({exc}). "
                          f"The route can be checked with: {ADAPTERS[route]}"
                          + (" --check-model" if route == "dartmouth" else "")) from exc
    if progress:
        progress("Checking each quotation against the PDF's pages")
    return proposal_from_findings(ws, intake, extracted, route, entry_type)


# --- manual drafts ------------------------------------------------------------------------------

def draft_manual(ws, fields, entry_type="article", prefill=None):
    """A hand-typed entry in house format. ``fields`` is what the person typed; ``prefill``
    ({field: value}, e.g. ``prefill_from``) supplies fields they left empty, and those are
    marked as read from the PDF and taken as plain text (one with LaTeX markup in it is left
    unfilled; TeX specials are escaped). A typed value may hold LaTeX: a command that is
    never written (``FORBIDDEN_COMMANDS``), ``^^`` or a bare ``%`` is refused, and a command
    outside ``ALLOWED_COMMANDS`` is an issue naming it. Values are put in the library's LaTeX form
    (``complete.latex_text``) and through the format checker (``helpers.check_bib`` on the
    one entry); the key comes from ``complete.plan_key`` and a duplicate is flagged. The
    proposal has no source record (``manual=True``, ``status="needs_review"``)."""
    typed = {str(k).strip().lower(): v for k, v in (fields or {}).items() if str(v or "").strip()}
    read = {str(k).strip().lower(): v for k, v in (prefill or {}).items()
            if str(v or "").strip() and str(k).strip().lower() not in typed}
    sources = {name: "read from the PDF (not typed)" for name in read}
    return _draft(ws, entry_type, {**read, **typed}, sources, [], [], "typed", plain=set(read))


# --- model evidence -----------------------------------------------------------------------------

def evidence_for(proposal, intake):
    """The external-evidence record of a model-read proposal: the PDF's SHA-256, each kept
    field with its page and quotation, the provider trace, the uncertainties and the fields
    that were not kept. Raises ``CdlbibError`` for a proposal no model read, or one read
    from a different PDF."""
    evidence = getattr(proposal, "evidence", None)
    if not evidence:
        raise CdlbibError("This proposal was not read from a PDF by a model, so it has no model evidence.")
    if intake is not None and intake.sha256 != evidence.get("pdf_sha256"):
        raise CdlbibError("This proposal was read from a different PDF.")
    return json.loads(json.dumps(evidence))


def attach_model_evidence(ws, key, evidence, fingerprint, database=None):
    """Store ``evidence`` (``evidence_for``) with the library entry ``key`` as its
    ``external_evidence``, the record ``crossref attach-evidence`` writes, bound to the
    entry's fingerprint: ``fingerprint`` is required and must be the entry's current one
    (``Accepted.fingerprint``, ``EntryDetail.fingerprint``). The library's write lock is
    held while the entry is read and the record stored (``library.transaction``).

    This is not an approval. The entry's result is ``needs_review`` with the evidence
    attached, as ``attach-evidence`` leaves it; an entry that is already accepted is left
    alone (``CdlbibError``), so no accepted status is changed. Returns the stored result.
    """
    from .library import transaction
    from .verification import ACCEPTED, Cache, outcome, run_lock
    if not isinstance(evidence, dict) or not all(evidence.get(k) for k in ("pdf_sha256", "fields", "reviewer")):
        raise CdlbibError("Model evidence needs pdf_sha256, fields and reviewer.")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise CdlbibError("Model evidence is stored for one exact entry text: its fingerprint is required.")
    cache = None
    try:
        with transaction(ws):
            cache = Cache(database or ws.database, ledger=ws.revocations)
            with run_lock(cache):
                entries = complete._library_entries(ws)
                if key not in entries:
                    raise CdlbibError(f"There is no entry {key} in the library.")
                entry = entries[key]
                if entry["fingerprint"] != fingerprint:
                    raise CdlbibError("The entry changed since the model read it; the evidence was not attached.")
                previous = cache.get(ws.bib, entry)
                if previous and previous["status"] in ACCEPTED:
                    raise CdlbibError(f"{key} is already {previous['status']}; the model evidence was not attached.")
                return cache.put(ws.bib, entry, dict(
                    previous or outcome("needs_review", []), status="needs_review", external_evidence=evidence,
                    issues=["External PDF/LLM findings attached; human confirmation required"]))
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise CdlbibError(f"The model evidence could not be stored: {exc}") from exc
    finally:
        if cache is not None:
            cache.close()


@dataclass
class Accepted:
    """What ``accept_draft`` did. ``applied``: the writer's ``complete.Applied`` (``written``
    is empty when the writer refused, with the reason in ``refused``). ``key`` and
    ``fingerprint``: the entry as it is now in the file. ``evidence``: the model evidence of
    the proposal, or None for a draft that has none. ``evidence_stored``: True, None (there
    was none to store) or False, with ``evidence_error`` saying why; the entry is written
    all the same, and ``attach_model_evidence(ws, key, evidence, fingerprint)`` with this
    result's values stores it later."""
    applied: object
    key: str | None = None
    fingerprint: str | None = None
    evidence: dict | None = None
    evidence_stored: bool | None = None
    evidence_error: str | None = None

    @property
    def written(self):
        return self.key is not None

    DATA_PROPERTIES = ("written",)

    def to_data(self):
        return to_data(self)


def accept_draft(ws, proposal, pdf=None, database=None):
    """Write an accepted model-read or hand-typed proposal and keep its evidence, as one
    action under the library's write lock (``library.transaction``, which the writer
    re-enters): the entry is written by the existing writer (``complete.apply``: backup or
    saved copy, key plan, rename ledger), read back from the file, and the proposal's model
    evidence (``evidence_for(proposal, pdf)``; none for a typed draft) is stored bound to
    exactly the fingerprint read back. Returns ``Accepted``.

    No approval is recorded and the entry's status is not an accepted one. When the writer
    refuses, nothing is written or stored (``Accepted.applied.refused``). When the entry is
    written and the evidence cannot be stored, the result says so (``evidence_stored``
    False, ``evidence_error``) and carries what a retry needs. A proposal that was not made
    here (``manual`` False) is refused: those are written by ``api.apply_proposals``.
    """
    from .library import transaction
    if not isinstance(proposal, complete.Proposal) or not proposal.manual:
        raise CdlbibError("Only a model-read or hand-typed draft is accepted here; a proposal built from a "
                          "source record is written by apply_proposals.")
    evidence = evidence_for(proposal, pdf) if getattr(proposal, "evidence", None) else None
    kept = []

    def journal(entries, planned):
        # The evidence is put on disk BEFORE the entry is written, bound to the fingerprint the
        # entry will have (read from the exact text about to be written), so that whatever
        # happens after this point, a retry has what it needs. If it cannot be kept, the entry
        # is not written either.
        key = planned.written[0]
        try:
            _keep_pending(ws, key, entries[key]["fingerprint"], evidence)
        except (CdlbibError, OSError) as exc:
            from .errors import CompletionRefused
            raise CompletionRefused(f"The model evidence of {key} could not be kept on disk ({exc}), so the entry "
                                    "was not written either; nothing was changed.") from exc
        kept.append(key)

    try:
        with transaction(ws):
            try:
                applied = complete.apply(ws, [proposal], before_commit=journal if evidence is not None else None)
            except BaseException:
                for key in kept:       # the write did not happen: the evidence has no entry to wait for
                    _drop_pending(ws, key)
                raise
            if not applied.written:
                return Accepted(applied=applied, evidence=evidence)
            key = applied.written[0]
            result = Accepted(applied=applied, key=key, evidence=evidence,
                              fingerprint=complete._library_entries(ws)[key]["fingerprint"])
            if evidence is not None:
                try:
                    attach_model_evidence(ws, key, evidence, result.fingerprint, database=database)
                    result.evidence_stored = True
                    _drop_pending(ws, key)
                except CdlbibError as exc:
                    result.evidence_stored, result.evidence_error = False, str(exc)
            return result
    except (OSError, ValueError, KeyError) as exc:
        raise CdlbibError(f"The draft could not be accepted: {exc}") from exc


PENDING_EVIDENCE = "pending-evidence"    # <library>/.bibcheck/pending-evidence/<key>.json


def _pending_name(key):
    from urllib.parse import quote
    return quote(str(key), safe="").replace(".", "%2E") + ".json"


def _keep_pending(ws, key, fingerprint, evidence):
    from . import writer
    data = json.dumps({"key": key, "fingerprint": fingerprint, "evidence": evidence}, ensure_ascii=False, indent=1)
    writer.keep_record(ws, PENDING_EVIDENCE, _pending_name(key), data.encode("utf-8"))


def _drop_pending(ws, key):
    from . import writer
    with contextlib.suppress(CdlbibError, OSError):
        writer.drop_record(ws, PENDING_EVIDENCE, _pending_name(key))


def _pending(ws):
    """{key: (fingerprint, evidence)} of the records that are what ``_keep_pending`` writes
    (the right name for their key, the three fields, of the right kinds); others are ignored."""
    from . import writer
    found = {}
    for name, data in writer.records(ws, PENDING_EVIDENCE).items():
        try:
            record = json.loads(data.decode("utf-8"))
            key, fingerprint, evidence = record["key"], record["fingerprint"], record["evidence"]
        except (ValueError, KeyError, TypeError):
            continue
        if (set(record) == {"key", "fingerprint", "evidence"} and isinstance(key, str) and isinstance(fingerprint, str)
                and isinstance(evidence, dict) and name == _pending_name(key)):
            found[key] = (fingerprint, evidence)
    return found


def pending_evidence(ws):
    """The model evidence waiting to be stored, as ``api.PendingEvidence(key, fingerprint,
    stale)``: ``stale`` when the entry is gone or no longer has that fingerprint."""
    from .api import PendingEvidence
    waiting = _pending(ws)
    if not waiting:
        return []
    try:
        entries = complete._library_entries(ws)
    except (OSError, ValueError) as exc:
        raise CdlbibError(f"{ws.bib} could not be read: {exc}") from exc
    return [PendingEvidence(key, fingerprint, key not in entries or entries[key]["fingerprint"] != fingerprint)
            for key, (fingerprint, _) in sorted(waiting.items())]


def retry_evidence(ws, key, database=None):
    """Store the evidence kept for ``key`` (``_keep_pending``), under the library's write
    lock, bound to the fingerprint it was kept with; see ``api.retry_evidence``."""
    from .library import transaction
    try:
        with transaction(ws):
            waiting = _pending(ws)
            if key not in waiting:
                raise CdlbibError(f"No model evidence is waiting to be stored for {key}.")
            fingerprint, evidence = waiting[key]
            result = Accepted(applied=None, key=key, fingerprint=fingerprint, evidence=evidence, evidence_stored=False)
            entry = complete._library_entries(ws).get(key)
            if entry is None:
                # The record is written before the entry: a write that never happened (a crash in
                # between) leaves evidence for no entry. It is dropped.
                _drop_pending(ws, key)
                result.evidence_error = f"{key} is not in the library: the entry was not written, and its evidence was dropped"
                return result
            if entry["fingerprint"] != fingerprint:
                result.evidence_error = f"{key} has changed since the evidence was read; it no longer applies"
                return result
            try:
                attach_model_evidence(ws, key, evidence, fingerprint, database=database)
            except CdlbibError as exc:
                result.evidence_error = str(exc)
                return result
            result.evidence_stored = True
            _drop_pending(ws, key)
            return result
    except (OSError, ValueError, KeyError) as exc:
        raise CdlbibError(f"The evidence for {key} could not be stored: {exc}") from exc


# --- the child process --------------------------------------------------------------------------

def _limit(seconds, memory):
    """Limit this (child) process: CPU seconds, and address space and data size where the
    platform accepts the limit. Returns the names of the limits that were set. On macOS the
    memory limits are refused (measured 2026-10-05, macOS 26 arm64: ``setrlimit`` raises
    ValueError for RLIMIT_AS, RLIMIT_DATA and RLIMIT_RSS), so there the bounds are the ones
    applied while reading: the stream cap, the text caps, the pixel cap, and the parent's
    output limit and time limit."""
    done = []
    try:
        import resource
    except ImportError:
        return done
    for name, value in (("RLIMIT_CPU", int(seconds)), ("RLIMIT_AS", int(memory)), ("RLIMIT_DATA", int(memory))):
        try:
            kind = getattr(resource, name)
            hard = resource.getrlimit(kind)[1]
            value = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(kind, (value, hard))
            done.append(name)
        except (AttributeError, ValueError, OSError):
            continue
    return done


class _Enough(Exception):
    """Raised inside text extraction to stop it at a cap."""


def _title_from_runs(runs):
    """The text set largest on the page: consecutive fragments of one size are a run; the
    largest run that is not an arXiv stamp, among the three largest sizes.

    A title is set larger than the page's running text, so a run qualifies only when its
    size is more than a tenth above the size most of the page's characters are set in.
    (Without that, a page whose larger runs all fail falls through to a paragraph of body
    text.) The largest size on the page is the one exception, for a page that carries
    little but its title: there a run qualifies unless it reads as sentences. A run needs
    three words, or two when it is the largest text on the page ("Mistral 7B")."""
    joined, sized = [], []
    for text, size in runs:
        if text.strip():
            sized.append((size, len(text.strip())))
        if joined and abs(joined[-1][1] - size) <= 0.02 * size:
            joined[-1][0] += text
        elif text.strip():
            joined.append([text, size])
    if not joined:
        return None
    half, body = sum(count for _, count in sized) / 2, 0.0
    for size, count in sorted(sized):  # the size at the middle character of the page
        half, body = half - count, size
        if half <= 0:
            break
    sizes = sorted({size for _, size in joined}, reverse=True)[:3]
    for size in sizes:
        largest, above = size == sizes[0], size > 1.1 * body
        if not (largest or above):
            break
        for text, own in joined:
            text = " ".join(text.split())
            if own != size or not 10 <= len(text) <= 400 or re.match(r"(?i)arxiv\s*:", text):
                continue
            if len(text.split()) < (2 if largest else 3):
                continue
            if not above and re.search(r"[.!?]\s+[A-Z]", text):
                continue
            return text
    return None


def _cap_streams(pypdf, stream_bytes):
    """Lower pypdf's own caps on what one stream may decompress to (and declare, and
    allocate for an image) to ``stream_bytes``; pypdf refuses a stream that would exceed
    them while inflating it. Through ``pypdf.overwrite_configuration`` where pypdf has it,
    else through the module constants older pypdf 6 releases read."""
    if hasattr(pypdf, "overwrite_configuration"):
        current = pypdf.get_configuration()
        names = [n for n in ("maximum_declared_stream_length", "array_based_stream_maximum_output_length",
                             "jbig2_maximum_output_length", "lzw_maximum_output_length",
                             "run_length_maximum_output_length", "zlib_maximum_output_length",
                             "image_maximum_buffer_size", "xmp_maximum_input_length") if hasattr(current, n)]
        pypdf.overwrite_configuration(**{n: min(getattr(current, n), stream_bytes) for n in names})
        return
    import pypdf.filters
    for name in ("ZLIB_MAX_OUTPUT_LENGTH", "LZW_MAX_OUTPUT_LENGTH", "RUN_LENGTH_MAX_OUTPUT_LENGTH",
                 "JBIG2_MAX_OUTPUT_LENGTH", "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH", "MAX_DECLARED_STREAM_LENGTH",
                 "FLATE_MAX_BUFFER_SIZE"):
        if isinstance(getattr(pypdf.filters, name, None), int):
            setattr(pypdf.filters, name, min(getattr(pypdf.filters, name), stream_bytes))


def _read_job(path, max_pages=MAX_PAGES, page_chars=MAX_PAGE_CHARS, total_chars=MAX_TOTAL_CHARS,
              stream_bytes=MAX_STREAM_BYTES):
    import pypdf
    _cap_streams(pypdf, stream_bytes)
    out = {"pages": [], "metadata": {}, "title_guess": None, "title_source": None, "problem": None, "detail": None}
    try:
        reader = pypdf.PdfReader(path)
        if reader.is_encrypted:
            try:
                opened = reader.decrypt("")
            except Exception:  # noqa: BLE001 - any failure to open it is "encrypted"
                opened = 0
            if not opened:
                out.update(problem="encrypted", detail="The PDF is encrypted and needs a password.")
                return out
        for name, value in list((reader.metadata or {}).items())[:50]:
            if isinstance(value, str) and value.strip():
                out["metadata"][str(name).lstrip("/").lower()[:100]] = " ".join(value[:5000].split())[:1000]
        runs, total, cut = [], 0, False
        for number in range(1, max_pages + 1):
            if number > len(reader.pages) or cut:
                break
            pieces, seen = [], 0

            def visit(text, cm, tm, font, size, first=(number == 1)):
                nonlocal seen
                if not text:
                    return
                seen += len(text)
                pieces.append(text)
                if seen > page_chars or total + seen > total_chars:
                    raise _Enough()  # stop here: nothing beyond the cap is extracted
                if first and size:
                    a = tm[0] * cm[0] + tm[1] * cm[2]
                    b = tm[0] * cm[1] + tm[1] * cm[3]
                    scale = (a * a + b * b) ** 0.5
                    if abs(b) <= abs(a) and scale:  # upright text only
                        runs.append((text, round(abs(size) * scale, 1)))

            try:
                text = reader.pages[number - 1].extract_text(visitor_text=visit) or ""
            except _Enough:
                text, cut = "".join(pieces), True
            text = text[:max(0, min(page_chars, total_chars - total))]
            total += len(text)
            out["pages"].append({"page": number, "text": text})
        if not any(p["text"].strip() for p in out["pages"]):
            out.update(problem="no_text", detail="The PDF has no text (a scan).")
            return out
        if cut:
            out["detail"] = (f"The PDF's text was cut: at most {page_chars} characters of a page and "
                             f"{total_chars} in all are read.")
        title = _title_from_runs(runs)
        if title:
            out.update(title_guess=title, title_source="largest text on page 1")
    except Exception as exc:  # noqa: BLE001 - a damaged or hostile file may raise anything
        out.update(pages=[], problem="unreadable", detail=f"The PDF could not be parsed ({type(exc).__name__}).")
    return out


def _png(pixels):
    """A numpy (height, width, channels) uint8 array as PNG bytes (1, 3 or 4 channels)."""
    import struct
    import zlib
    height, width, channels = pixels.shape
    kind = {1: 0, 3: 2, 4: 6}[channels]
    rows = b"".join(b"\x00" + pixels[y].tobytes() for y in range(height))

    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, kind, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def _render_job(path, width, max_pixels=MAX_PIXELS):
    import math
    import pypdfium2
    document = pypdfium2.PdfDocument(path)
    try:
        page = document[0]
        page_width, page_height = page.get_width(), page.get_height()
        if not (page_width > 0 and page_height > 0):
            raise ValueError("the page has no size")
        height = math.ceil(page_height * width / page_width)
        if width * height > max_pixels:  # decided from the page's size, before anything is drawn
            raise ValueError(f"the page is {page_width:.0f} x {page_height:.0f} points: {width} pixels wide it would "
                             f"be {height} pixels high, more than the {max_pixels} pixels a preview may have")
        pixels = page.render(scale=width / page_width, rev_byteorder=True).to_numpy()
        if pixels.ndim == 2:
            pixels = pixels[:, :, None]
        return _png(pixels)
    finally:
        document.close()


def _main(arguments):
    """The child: ``read PATH PAGES PAGE_CHARS TOTAL_CHARS STREAM_BYTES`` writes one JSON
    object, ``render PATH WIDTH MAX_PIXELS`` writes a PNG. The limits are set first."""
    job = arguments[0] if arguments else ""
    try:
        if job == "read" and len(arguments) == 6:
            _limit(READ_TIMEOUT, MAX_CHILD_MEMORY)
            sys.stdout.write(json.dumps(_read_job(arguments[1], *map(int, arguments[2:])), ensure_ascii=False))
            return 0
        if job == "render" and len(arguments) == 4:
            _limit(RENDER_TIMEOUT, MAX_CHILD_MEMORY)
            sys.stdout.buffer.write(_render_job(arguments[1], int(arguments[2]), int(arguments[3])))
            return 0
        if job == "ocr" and len(arguments) == 4:  # the existing OCR (local_ocr), bounded like the reading
            from . import local_ocr
            _limit(OCR_TIMEOUT * 4, MAX_CHILD_MEMORY)
            pages, kept = local_ocr.ocr_front(arguments[1], local_ocr.extraction_profile()), int(arguments[3])
            sys.stdout.write(json.dumps([{"page": p["page"], "text": p["text"][:kept]}
                                         for p in pages[:int(arguments[2])]], ensure_ascii=False))
            return 0
        if job == "limits" and len(arguments) == 1:  # which limits this platform accepts
            sys.stdout.write(json.dumps(_limit(READ_TIMEOUT, MAX_CHILD_MEMORY)))
            return 0
    except Exception as exc:  # noqa: BLE001 - the parent reports the last line
        sys.stderr.write(f"{type(exc).__name__}: {str(exc)[:300]}\n")
        return 3
    sys.stderr.write("usage: python -m cdlbib.intake read PATH PAGES PAGE_CHARS TOTAL_CHARS STREAM_BYTES"
                     " | render PATH WIDTH MAX_PIXELS | ocr PATH PAGES PAGE_CHARS | limits\n")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
