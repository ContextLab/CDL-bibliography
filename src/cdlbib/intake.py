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
MAX_PAGE_CHARS = 100_000    # text kept per page
MAX_PDF_BYTES = 50_000_000  # a larger file is not opened
MAX_OUTPUT_BYTES = 4_000_000    # what the reading child may send back
MAX_IMAGE_BYTES = 40_000_000    # what the rendering child may send back
READ_TIMEOUT = 60           # seconds the reading child may take
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

class Candidates(list):
    """The leads, plus ``errors``: (source, reason) for each source that did not answer."""

    def __init__(self):
        super().__init__()
        self.errors = []


def _surname(name):
    """The surname of one typed name ("Manning", "Jeremy R. Manning", "Manning, J. R."),
    accent-free and lower-cased; "" when there is none."""
    from .extra_sources import fold
    name = " ".join(str(name or "").split())
    if not name:
        return ""
    return fold(complete._first_surname(name) or name.split(",")[0].split()[-1])


def _significant(title, limit=8):
    """Up to ``limit`` title words worth searching for, in title order
    (``extra_sources.pubmed_title_term``'s choice: no stop words, the longest first)."""
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
    if year and re.fullmatch(r"\d{4}", year):
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
    ``ti:``, every surname in ``au:``."""
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
    asked year come first, then the closest titles. At most ``limit`` are returned.

    A source that does not answer is listed in ``.errors`` and the others are still asked.
    A lead is not an entry: build one with ``query_for(lead)`` through ``api.propose_new``.
    """
    from .verification import ProviderError
    title = " ".join(str(title or "").split()) or None
    authors = [authors] if isinstance(authors, str) else list(authors or ())
    authors = [" ".join(str(a).split()) for a in authors if str(a or "").strip()]
    year = str(year or "").strip() or None
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
    for _, _, lead in ranked[:max(0, limit)]:
        names = lead.pop("_authors")
        try:
            index = index or _library_index(ws)
            lead["in_library"] = _in_library(lead, names, index)
        except (OSError, ValueError) as exc:
            raise CdlbibError(f"The library could not be read to look for duplicates: {exc}") from exc
        found.append(lead)
    return found


def query_for(candidate):
    """The ``complete.Query`` that names a lead by its identifier (arXiv id, then DOI, then
    PMID): what ``api.propose_new`` is given when the lead is chosen."""
    if candidate.get("arxiv") and candidate.get("source") == "arxiv":
        return complete.Query(arxiv=candidate["arxiv"])
    if candidate.get("doi"):
        return complete.Query(doi=candidate["doi"])
    if candidate.get("pmid"):
        return complete.Query(pmid=str(candidate["pmid"]))
    if candidate.get("arxiv"):
        return complete.Query(arxiv=candidate["arxiv"])
    raise CdlbibError("This record has no DOI, PMID or arXiv id to look it up by.")


# --- PDF reading --------------------------------------------------------------------------------

class Identifier(NamedTuple):
    kind: str          # "doi", "arxiv" or "pmid"
    value: str
    page: int | None   # None: found in the PDF's metadata
    quote: str         # the line it was read from


@dataclass
class PdfIntake:
    """What was read from a PDF. ``problem``: None, or "not_pdf", "too_large", "encrypted",
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


def _child(arguments, timeout):
    """Run this module's child entry point; (return code, stdout bytes, stderr text)."""
    package_parent = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (package_parent, os.environ.get("PYTHONPATH")) if p))
    done = subprocess.run([sys.executable, "-m", "cdlbib.intake", *arguments], capture_output=True,
                          timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace").strip()


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


def _hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _ocr_tools():
    return all(shutil.which(tool) for tool in ("pdftoppm", "tesseract"))


def read_pdf(path, ocr=True):
    """Read a PDF's first ``MAX_PAGES`` pages in a child process (``READ_TIMEOUT`` seconds).

    Returns a ``PdfIntake`` always, for an existing file: a file that is not a PDF, is
    larger than ``MAX_PDF_BYTES``, is encrypted, cannot be parsed, takes too long or has no
    text is reported in ``problem``. A PDF with no text is read by ``local_ocr`` when
    ``pdftoppm`` and ``tesseract`` are installed (``ocr=True``); the result then has
    ``ocr=True`` and no ``problem``. A missing file raises ``CdlbibError``; a missing pypdf
    raises ``MissingDependency``.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            head = handle.read(1024)
    except OSError as exc:
        raise CdlbibError(f"The PDF could not be opened: {exc}") from exc
    intake = PdfIntake(path=path)
    if b"%PDF-" not in head:
        intake.problem, intake.detail = "not_pdf", "The file does not start as a PDF (no %PDF- header)."
        return intake
    if size > MAX_PDF_BYTES:
        intake.problem = "too_large"
        intake.detail = f"The file is {size // 1_000_000} MB; at most {MAX_PDF_BYTES // 1_000_000} MB is read."
        return intake
    intake.sha256 = _hash(path)
    deps.need("pypdf", "research", "Reading PDF files")
    try:
        code, out, err = _child(["read", str(path)], READ_TIMEOUT)
    except subprocess.TimeoutExpired:
        intake.problem, intake.detail = "timeout", f"Reading the PDF took more than {READ_TIMEOUT} seconds."
        return intake
    if code != 0 or len(out) > MAX_OUTPUT_BYTES:
        intake.problem = "unreadable"
        intake.detail = ("The PDF reader returned too much text." if code == 0
                         else f"The PDF reader stopped ({err.splitlines()[-1][:300] if err else code}).")
        return intake
    try:
        read = json.loads(out.decode("utf-8"))
        intake.pages = [{"page": int(p["page"]), "text": str(p["text"])} for p in read["pages"]][:MAX_PAGES]
        intake.metadata = {str(k): str(v) for k, v in read["metadata"].items()}
        intake.problem, intake.detail = read["problem"], read["detail"]
        intake.title_guess, intake.title_source = read["title_guess"], read["title_source"]
    except (ValueError, KeyError, TypeError, AttributeError):
        intake.pages, intake.problem, intake.detail = [], "unreadable", "The PDF reader's answer could not be read."
        return intake
    if intake.problem == "no_text" and ocr and _ocr_tools():
        from . import local_ocr
        try:
            pages = local_ocr.ocr_front(path, local_ocr.extraction_profile())
            intake.pages = [{"page": p["page"], "text": p["text"][:MAX_PAGE_CHARS]} for p in pages][:MAX_PAGES]
            intake.ocr, intake.problem = True, None
            intake.detail = "The PDF has no text of its own; this text was read from the page images (OCR) and may be misread."
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            intake.detail = f"The PDF has no text, and OCR did not read it ({type(exc).__name__}: {str(exc)[:200]})."
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
    pypdfium2 in a child process (``RENDER_TIMEOUT`` seconds). Raises ``MissingDependency``
    without pypdfium2 and ``CdlbibError`` when the page cannot be drawn."""
    path, width = Path(path), int(width)
    if not 16 <= width <= 4000:
        raise CdlbibError("The preview width must be between 16 and 4000 pixels.")
    try:
        with open(path, "rb") as handle:
            head = handle.read(1024)
        size = path.stat().st_size
    except OSError as exc:
        raise CdlbibError(f"The PDF could not be opened: {exc}") from exc
    if b"%PDF-" not in head:
        raise CdlbibError("The file does not start as a PDF (no %PDF- header).")
    if size > MAX_PDF_BYTES:
        raise CdlbibError(f"The file is larger than {MAX_PDF_BYTES // 1_000_000} MB; no preview is drawn.")
    deps.need("pypdfium2", "pdf", "the PDF page preview")
    try:
        code, out, err = _child(["render", str(path), str(width)], RENDER_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise CdlbibError(f"Drawing the page took more than {RENDER_TIMEOUT} seconds.") from None
    if code != 0 or not out.startswith(b"\x89PNG\r\n\x1a\n") or len(out) > MAX_IMAGE_BYTES:
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
        fields.update(complete._completion_fields(proposal))
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
    available: bool
    how: str           # how to set it up; shown whether or not it is available
    default: bool = False


def _has_key(name, environ=None):
    from . import secrets
    try:
        secrets.get(name, environ)
    except SecretNotFound:
        return False
    return True


def model_routes(environ=None):
    """The model routes, Dartmouth Chat (the default) first. ``available`` is whether the
    route's API key is found by ``secrets.get`` (the environment variable, then the system
    keychain) and, for OpenAI, whether ``BIBCHECK_RESEARCH_MODEL`` names a model. A route
    that is not available is still listed, with ``how``. No key is returned or shown."""
    from . import secrets
    source = os.environ if environ is None else environ
    return [
        ModelRoute("dartmouth", "Dartmouth Chat", _has_key("dartmouth-chat", environ),
                   f"Create an API key in Dartmouth Chat (steps: {DARTMOUTH_KEY_PAGE}). "
                   + secrets.places("dartmouth-chat") + " Only models the Dartmouth catalogue lists as free are used.",
                   default=True),
        ModelRoute("openai", "OpenAI", _has_key("openai", environ) and bool(source.get("BIBCHECK_RESEARCH_MODEL")),
                   "Create an OpenAI API key. " + secrets.places("openai")
                   + " Also set the environment variable BIBCHECK_RESEARCH_MODEL to the model to use."),
    ]


@dataclass
class ModelProposal(complete.Proposal):
    """A proposal read from a PDF by a model. ``evidence``: what ``evidence_for`` stores."""
    evidence: dict | None = None


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


def _draft(ws, entry_type, values, sources, unfilled, notes, kind):
    """The manual proposal for ``values`` ({field: text}); ``sources`` {field: where from}."""
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
        typed[name] = value
    if not typed:
        raise CdlbibError("There is nothing to draft: no field has a value.")
    given = {name: complete.latex_text(value) for name, value in typed.items()}
    fields, changed, removed, failure = _house(entry_type, given)
    proposal = ModelProposal(entry_type=entry_type, status="needs_review", manual=True, needs_decision=True,
                             notes=[NO_SOURCE, *notes], unfilled=list(unfilled), doi=fields.get("doi"))
    if failure:
        proposal.issues.append(f"The format check could not run on this entry ({failure}); it is written as given")
    for name in sorted(typed):
        source = sources.get(name, "typed")
        shown = typed[name] if kind == "typed" else None
        if name in removed:
            proposal.changes.append(complete.FieldChange(name, typed[name], None, "house format", "dropped"))
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
    return proposal


def proposal_from_findings(ws, intake, extracted, route="dartmouth", entry_type="article"):
    """The proposal for an adapter's ``extract`` answer, checked against the PDF's pages.

    A field is kept only when ``research.validate_findings`` finds its quotation on the
    stated page and the value is literally in the quoted text (the adapter's ``grounding``,
    else ``source_passages.literal_grounding``), with no role risk flagged for the quoted
    passage (a receipt date, a copyright line, an affiliation, a reference list). Every
    other field is ``Unfilled`` with the reason and the model's value. A kept field is a
    ``FieldChange`` whose source names the page and the quotation. The entry is written in
    house format, keyed by ``plan_key`` and checked for duplicates; it has no source record
    (``manual=True``, ``status="needs_review"``) and always needs a decision.
    """
    from .research import validate_findings
    from .source_passages import literal_grounding
    from .verification import now
    read = extracted.get("fields") if isinstance(extracted, dict) else None
    if not isinstance(read, dict) or not read:
        raise CdlbibError("The model returned no fields for this PDF.")
    pages = intake.pages
    flagged = extracted.get("role_risk_fields") if isinstance(extracted.get("role_risk_fields"), dict) else {}
    kept, unfilled = {}, []
    for name, evidence in read.items():
        value = evidence.get("value") if isinstance(evidence, dict) else None
        said = {f"model reading ({route})": value} if isinstance(value, str) and value.strip() else {}
        try:
            validate_findings({"fields": {name: evidence}}, pages)
        except ValueError as exc:
            unfilled.append(complete.Unfilled(name, f"not kept: {exc}", said))
            continue
        if not said:
            unfilled.append(complete.Unfilled(name, f"{name}: the model gave no value", {}))
            continue
        quotes = [span["quote"] for span in evidence.get("passages") or []] or [evidence["quote"]]
        grounded = (evidence["grounding"] == "literal_text_present" if "grounding" in evidence
                    else literal_grounding(name, value, ["".join(quotes), *quotes]))
        risks = list(evidence.get("role_risk") or flagged.get(name) or [])
        if name == "ENTRYTYPE" or not grounded:
            unfilled.append(complete.Unfilled(
                name, f"{name}: the value is not literally in the quoted text (page {evidence['page']}); "
                      "it is the model's interpretation", said))
        elif risks:
            unfilled.append(complete.Unfilled(
                name, f"{name}: the quoted text (page {evidence['page']}) may play another role "
                      f"({', '.join(risks)}), so it is not taken as the work's own {name}", said))
        else:
            kept[name] = evidence
    if not kept:
        raise CdlbibError("The model reading gave no field that its quotation supports: "
                          + "; ".join(u.reason for u in unfilled))
    def quoted(evidence):  # every selected passage, in page order, on one line
        return " ".join("".join(span["quote"] for span in evidence.get("passages") or []).split()
                        or evidence["quote"].split())

    sources = {name: f'model reading, p.{e["page"]}: "{quoted(e)}"' for name, e in kept.items()}
    left = tuple(f"{u.field}: " for u in unfilled) or ("\0",)  # said once, as the reason the field is unfilled
    uncertainties = [u for u in extracted.get("uncertainties") or [] if isinstance(u, str)]
    notes = ([f"Read by a language model ({route}) from {intake.path.name}; every kept field quotes the page it was read from."]
             + (["The PDF's text is OCR output, which misreads characters."] if intake.ocr else []))
    proposal = _draft(ws, entry_type, {name: e["value"] for name, e in kept.items()}, sources, unfilled, notes, "model")
    proposal.issues += [f"model: {u}" for u in uncertainties if not u.startswith(left)]
    proposal.evidence = {
        "source": "local PDF read by a language model",
        "pdf_sha256": intake.sha256,
        "pdf_name": intake.path.name,
        "ocr": intake.ocr,
        "retrieved_at": now(),
        "reviewer": "model-reading:" + route,
        "fields": {name: {k: v for k, v in e.items() if k in ("value", "page", "quote", "passages", "grounding")}
                   for name, e in kept.items()},
        "unsupported_fields": [{"field": u.field, "reason": u.reason, "values": u.source_values} for u in unfilled],
        "uncertainties": uncertainties,
        "extraction_policy": extracted.get("extraction_policy"),
        "provider_trace": {"extract": extracted.get("provider_trace")},
        "quote_check": QUOTE_CHECK,
    }
    return proposal


def read_pdf_with_model(ws, intake, route="dartmouth", progress=None, entry_type="article"):
    """Have a model read the PDF's front matter (``MODEL_PAGES`` pages) and propose an entry.

    The route's installed adapter is run through ``research.invoke_adapter`` with the
    ``extract`` phase of the research protocol, so the Dartmouth adapter makes its
    free-model check before any inference; the answer goes through
    ``proposal_from_findings``. Raises ``CdlbibError`` when the route is unknown or not set
    up, when the PDF gave no text, or when the adapter fails. Nothing is written; the
    proposal is never a verification.
    """
    from .research import INSTRUCTIONS, invoke_adapter
    routes = {r.name: r for r in model_routes()}
    if route not in routes:
        raise CdlbibError(f"Unknown model route {route!r}; the routes are {', '.join(routes)}.")
    chosen = routes[route]
    if not chosen.available:
        raise CdlbibError(f"{chosen.label} is not set up. {chosen.how}")
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
    marked as read from the PDF. Values are put in the library's LaTeX form
    (``complete.latex_text``) and through the format checker (``helpers.check_bib`` on the
    one entry); the key comes from ``complete.plan_key`` and a duplicate is flagged. The
    proposal has no source record (``manual=True``, ``status="needs_review"``)."""
    typed = {str(k).strip().lower(): v for k, v in (fields or {}).items() if str(v or "").strip()}
    read = {str(k).strip().lower(): v for k, v in (prefill or {}).items()
            if str(v or "").strip() and str(k).strip().lower() not in typed}
    sources = {name: "read from the PDF (not typed)" for name in read}
    return _draft(ws, entry_type, {**read, **typed}, sources, [], [], "typed")


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


def attach_model_evidence(ws, key, evidence, fingerprint=None, database=None):
    """Store ``evidence`` (``evidence_for``) with the library entry ``key`` as its
    ``external_evidence``, the record ``crossref attach-evidence`` writes, bound to the
    entry's current fingerprint (``fingerprint``, when given, must be the current one).

    This is not an approval. The entry's result is ``needs_review`` with the evidence
    attached, as ``attach-evidence`` leaves it; an entry that is already accepted is left
    alone (``CdlbibError``), so no accepted status is changed. Returns the stored result.
    """
    from .verification import ACCEPTED, Cache, load_entries, outcome, run_lock
    if not isinstance(evidence, dict) or not all(evidence.get(k) for k in ("pdf_sha256", "fields", "reviewer")):
        raise CdlbibError("Model evidence needs pdf_sha256, fields and reviewer.")
    cache = None
    try:
        cache = Cache(database or ws.database, ledger=ws.revocations)
        with run_lock(cache):
            entries = complete._library_entries(ws)
            if key not in entries:
                raise CdlbibError(f"There is no entry {key} in the library.")
            entry = entries[key]
            if fingerprint is not None and entry["fingerprint"] != fingerprint:
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


# --- the child process --------------------------------------------------------------------------

def _limit_cpu(seconds):
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    except (ImportError, ValueError, OSError):
        pass  # no CPU limit on this platform; the parent's time limit still applies


def _title_from_runs(runs):
    """The text set largest on the page: consecutive fragments of one size are a run; the
    largest run of at least three words that is not an arXiv stamp, among the three largest sizes."""
    joined = []
    for text, size in runs:
        if joined and abs(joined[-1][1] - size) <= 0.02 * size:
            joined[-1][0] += text
        elif text.strip():
            joined.append([text, size])
    for size in sorted({size for _, size in joined}, reverse=True)[:3]:
        for text, own in joined:
            text = " ".join(text.split())
            if own == size and len(text.split()) >= 3 and 10 <= len(text) <= 400 and not re.match(r"(?i)arxiv\s*:", text):
                return text
    return None


def _read_job(path):
    import pypdf
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
        for name, value in (reader.metadata or {}).items():
            if isinstance(value, str) and value.strip():
                out["metadata"][str(name).lstrip("/").lower()] = " ".join(value.split())[:1000]
        runs = []

        def visit(text, cm, tm, font, size):
            a = tm[0] * cm[0] + tm[1] * cm[2]
            b = tm[0] * cm[1] + tm[1] * cm[3]
            scale = (a * a + b * b) ** 0.5
            if text and abs(b) <= abs(a) and size and scale:  # upright text only
                runs.append((text, round(abs(size) * scale, 1)))

        for number, page in enumerate(reader.pages[:MAX_PAGES], 1):
            contents = page.get_contents()
            if contents and len(contents.get_data()) > 5_000_000:
                out.update(pages=[], problem="unreadable", detail="A page's content is too large to read.")
                return out
            text = page.extract_text(visitor_text=visit if number == 1 else None) or ""
            out["pages"].append({"page": number, "text": text[:MAX_PAGE_CHARS]})
        if not any(p["text"].strip() for p in out["pages"]):
            out.update(problem="no_text", detail="The PDF has no text (a scan).")
            return out
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


def _render_job(path, width):
    import pypdfium2
    document = pypdfium2.PdfDocument(path)
    try:
        page = document[0]
        bitmap = page.render(scale=width / page.get_width(), rev_byteorder=True)
        pixels = bitmap.to_numpy()
        if pixels.ndim == 2:
            pixels = pixels[:, :, None]
        return _png(pixels)
    finally:
        document.close()


def _main(arguments):
    """The child: ``read PATH`` writes one JSON object, ``render PATH WIDTH`` writes a PNG."""
    job = arguments[0] if arguments else ""
    try:
        if job == "read" and len(arguments) == 2:
            _limit_cpu(READ_TIMEOUT)
            sys.stdout.write(json.dumps(_read_job(arguments[1]), ensure_ascii=False))
            return 0
        if job == "render" and len(arguments) == 3:
            _limit_cpu(RENDER_TIMEOUT)
            sys.stdout.buffer.write(_render_job(arguments[1], int(arguments[2])))
            return 0
    except Exception as exc:  # noqa: BLE001 - the parent reports the last line
        sys.stderr.write(f"{type(exc).__name__}: {str(exc)[:300]}\n")
        return 3
    sys.stderr.write("usage: python -m cdlbib.intake read PATH | render PATH WIDTH\n")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
