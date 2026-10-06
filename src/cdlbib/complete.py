"""Entry completion: build a complete house-format entry from a source record.

``build`` is pure: it takes what the person typed, a Crossref-shaped record and, when there
is one, the DOI-linked PubMed record (``auto_review.epmc_record`` shape), and returns a
``Proposal``. It reads no file, makes no request, prints nothing and asks nothing.

Every value is produced by the existing house helpers (``correction_proposals``,
``helpers``, ``auto_review``); this module only decides which helper a field goes through
and what becomes of a refusal. A helper that refuses a value does not stop the build: the
field is left as typed (or absent) and listed in ``Proposal.unfilled`` with the helper's
reason and the values the sources gave.

The kinds of ``FieldChange``:
  - ``filled``: nothing was typed; the source's value is in the proposed text;
  - ``kept``: the typed value, which no source contradicts, is kept byte for byte;
  - ``changed``: the typed value is replaced in the proposed text and both are listed. The
    source is a record, or ``house format`` when the typed value is right but written in a
    form the format checker would rewrite. Nothing is written before the person accepts;
  - ``question``: the value is not settled and the proposal needs a decision
    (``needs_decision``), with the reason in ``Proposal.issues``. The proposed text holds
    the typed value when there is one, otherwise the candidate. A surname the source spells
    differently, a lone first page
    and a year the sources leave open are questions;
  - ``dropped``: a field outside the house list, or ``publisher`` on an article.

Three types are built, each from the one Crossref record type the verifier accepts for it
(``verification.compare_record``): ``@article`` from ``journal-article``, ``@inproceedings``
from ``proceedings-article`` and ``@incollection`` from ``book-chapter`` (``KINDS``). Any
other entry type or record type, and a record that is not of the typed entry's type, gives
a proposal with ``unsupported`` set and no proposed text. A record that is itself a
correction or retraction notice is refused (``CompletionRefused``). A work that has been
retracted is built, named as retracted in ``issues``, and always needs a decision.
"""

from dataclasses import dataclass, field
from functools import lru_cache
import html
import re
import unicodedata

from . import correction_proposals as cp
from .auto_review import compatible_authors, expanded_pages, safe_compare
from .errors import CompletionRefused
from .verification import (CORRECTION_FLAG, normalize_doi, normalize_journal, normalized,
                           print_year_selects_cited, split_authors)

# The key written when neither a typed key nor the authors and year are there to make one.
NO_KEY = "KeyNeeded"
# Said of a proposal that has no key yet (the placeholder stands in its text):
NO_KEY_YET = ("No key can be made until the authors are entered: a key is built from the authors and the year. "
              f"({NO_KEY} in the text is a placeholder, not a key; edit the authors in and the key is planned.)")

# The fields built from a source record, in the order they are settled (the layout's order).
BUILT_FIELDS = ("author", "doi", "journal", "number", "pages", "title", "volume", "year")
# The fields an article must have before it can be accepted without a person's decision.
REQUIRED_FIELDS = ("author", "title", "journal", "year")
# The fields an article is expected to have: one that no source states is listed as unfilled.
EXPECTED_FIELDS = ("author", "journal", "pages", "title", "volume", "year")



@dataclass(frozen=True)
class Kind:
    """One entry type the builder makes. ``record``: the Crossref record type the verifier
    accepts for it (``verification.compare_record``). ``built``: the fields filled from the
    record, in the layout's order (the record's ``container-title`` is the ``journal`` of an
    article and the ``booktitle`` of the others). ``required``: what the entry must have to be accepted without a
    decision. ``expected``: fields listed as unfilled when no source states them.
    ``unverified``: house fields the library's entries of the type usually have that the
    verifier has no check for (``compare_record`` answers them "no deterministic verifier
    for this field"): never filled, and listed as unfilled with what the record says."""
    record: str
    built: tuple
    required: tuple
    expected: tuple
    unverified: tuple = ()


KINDS = {
    "article": Kind("journal-article", BUILT_FIELDS, REQUIRED_FIELDS, EXPECTED_FIELDS),
    "inproceedings": Kind("proceedings-article", ("author", "booktitle", "doi", "pages", "title", "volume", "year"),
                          ("author", "title", "booktitle", "year"), ("author", "booktitle", "pages", "title", "year")),
    "incollection": Kind("book-chapter",
                         ("author", "booktitle", "doi", "pages", "publisher", "title", "volume", "year"),
                         ("author", "title", "booktitle", "year"),
                         ("author", "booktitle", "pages", "publisher", "title", "year"), ("address", "editor")),
}
RECORD_KINDS = {kind.record: name for name, kind in KINDS.items()}

# Crossref update types that make a record a notice about another work.
NOTICE_WORDS = ("errat", "corrig", "correct", "retract", "withdraw", "concern", "removal")
RETRACTION_WORDS = ("retract", "withdraw", "removal")

# A page locator the pagination rules accept (correction_proposals.single_source_proposal).
_PAGES = re.compile(r"[a-z]{0,3}\d+(?:-[a-z]{0,3}\d+(?:\.e\d+)?)?")
_DATES = ("published-print", "published-online", "issued", "published")

# Non-ASCII letters are written in LaTeX. The library never mixes brace styles inside one
# name, and the style it uses most is ``{\\"o}`` (counted in the frozen library fixture; the
# counts are in tests/test_complete_build.py). ``_accent`` is the one place the style is set.
def _accent(command, letter):
    """One accented letter: ``{\\"o}``, ``{\\'e}``, ``{\\c{c}}``. To write ``{\\"{o}}`` instead,
    return ``"{\\\\" + command + "{" + letter + "}}"`` for every command."""
    if command.isalpha():  # \\c, \\v, \\u, \\H: the letter is an argument
        return "{\\" + command + "{" + letter + "}}"
    return "{\\" + command + letter + "}"


# combining mark -> accent command. A dot above (\\.) is not here: the author formatter drops
# the period ({\\.Z}urek -> {\\Z}urek), so such a letter is left as the source has it and asked about.
_ACCENTS = {
    "\u0308": '"', "\u0301": "'", "\u0300": "`", "\u0302": "^", "\u0303": "~", "\u0304": "=",
    "\u0327": "c", "\u030c": "v", "\u0306": "u", "\u030b": "H", "\u030a": "r", "\u0328": "k",
    "\u0323": "d", "\u0331": "b",
}
_LETTERS = {  # {\\o} 3, {\\l} 2, {\\ss} 1, {\\L} 1, {\\AA} 1, {\\ae} 1 in the library
    "\u00f8": "{\\o}", "\u00d8": "{\\O}", "\u0142": "{\\l}", "\u0141": "{\\L}", "\u00df": "{\\ss}",
    "\u00e6": "{\\ae}", "\u00c6": "{\\AE}", "\u0153": "{\\oe}", "\u0152": "{\\OE}",
    "\u00e5": "{\\aa}", "\u00c5": "{\\AA}", "\u0131": "{\\i}",
}
_PUNCTUATION = {  # as the library writes them: ' 300+ lines against 6 with a curly one;
    # --- 33 and " -- " 4 against 3 raw en dashes and no em dash; `` 42 against 5 curly quotes
    "\u2019": "'", "\u2018": "`", "\u201c": "``", "\u201d": "''", "\u2013": "--", "\u2014": "---",
    "\u2010": "-", "\u2011": "-", "\u00a0": " ", "\u2009": " ",
}


def latex_text(value):
    """``value`` with every non-ASCII character in the library's LaTeX form
    (``Glöckner`` -> ``Gl{\\"o}ckner``). A character with no form here is left as it is,
    never dropped or replaced by a lookalike; ``not_in_latex`` lists those."""
    out = []
    for char in unicodedata.normalize("NFC", value):
        if ord(char) < 128:
            out.append(char)
            continue
        if char in _LETTERS or char in _PUNCTUATION:
            out.append(_LETTERS.get(char) or _PUNCTUATION[char])
            continue
        parts = unicodedata.normalize("NFD", char)
        base, marks = parts[0], parts[1:]
        if len(marks) == 1 and base.isascii() and base.isalpha() and marks in _ACCENTS:
            out.append(_accent(_ACCENTS[marks], base))
            continue
        out.append(char)
    return "".join(out)


def not_in_latex(value):
    """The characters of ``value`` that ``latex_text`` leaves as they are, in order."""
    return [char for char in dict.fromkeys(latex_text(value)) if ord(char) >= 128]


def _character_question(name, value):
    left = not_in_latex(value)
    if not left:
        return []
    named = ", ".join(f"{c!r} ({unicodedata.name(c, 'unnamed character')})" for c in left)
    return [f"{name}: no LaTeX form is known for {named}; written as the source has it"]


@dataclass
class FieldChange:
    field: str
    typed: str | None
    proposed: str | None
    source: str
    kind: str  # "filled", "kept", "changed", "question" or "dropped"


@dataclass
class Unfilled:
    field: str
    reason: str
    source_values: dict[str, str]


@dataclass
class Proposal:
    key_typed: str | None = None
    typed_raw: str | None = None
    proposed_raw: str | None = None
    entry_type: str | None = None
    changes: list[FieldChange] = field(default_factory=list)
    unfilled: list[Unfilled] = field(default_factory=list)
    record_source: str | None = None
    doi: str | None = None
    status: str | None = None  # the verifier's status for proposed_raw; not set by build
    issues: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    remove_duplicate: bool = False  # explicit removal of a typed live duplicate only
    duplicate_in_library: bool = False
    duplicate_of: str | None = None
    key_proposed: str | None = None
    renames: dict[str, str] = field(default_factory=dict)
    unsupported: str | None = None
    needs_decision: bool = False  # True: never accepted without the person looking at it
    # True when the entry has a key and the required fields of its type (KINDS: author, title,
    # year, and the journal of an article or the book title of a paper or chapter)
    # and none of them is a question. ``build`` sets it; an entry that is not complete
    # always needs a decision.
    complete: bool = False
    notes: list[str] = field(default_factory=list)  # how the record was found; not a problem
    edited_fields: dict | None = None  # strict parsed fields of exact user-edited text
    manual: bool = False
    # Choices made between values a record leaves open, each with what decided it
    # (container_titles.apply: which of a chapter record's two container titles is the book's).
    choices: list[dict] = field(default_factory=list)


@lru_cache(maxsize=1)
def _field_order():
    from .helpers import read
    return tuple(sorted(read("keep_fields.txt")))  # the order check_bib writes (helpers.check_bib)


def render(entry_type, key, fields):
    """One entry in the library's layout: ``@type{Key,`` then one tab-indented
    ``Field = {value}`` per line in the format checker's field order, closed by ``}``.
    ``ENTRYTYPE`` and ``ID`` in ``fields`` are ignored; a field outside the house list
    comes after the others, in alphabetical order."""
    order = [name for name in _field_order() if name not in ("ENTRYTYPE", "ID")]
    names = [n for n in order if fields.get(n) is not None]
    names += sorted(n for n in fields if n not in order and n not in ("ENTRYTYPE", "ID") and fields[n] is not None)
    lines = ["\n\t" + name.capitalize() + " = {" + fields[name] + "}" for name in names]
    return "@" + entry_type + "{" + key + ("," + ",".join(lines) if lines else "") + "}"


class _Hold(Exception):
    """A field that is not filled: the reason, and what each source gave."""

    def __init__(self, reason, values=None, disagreement=False):
        super().__init__(reason)
        self.reason, self.values, self.disagreement = reason, dict(values or {}), disagreement


@dataclass
class _Value:
    value: str
    source: str
    values: dict
    doubts: list = field(default_factory=list)  # why the value is a question rather than settled


def _written(name, value, formatter):
    """``value`` as it is written into the entry, and the questions that raises.

    The text is put in the library's LaTeX form and must come through the house formatter
    unchanged. A character with no LaTeX form stays as the source has it and is asked
    about; so does every non-ASCII character when the formatter would change the LaTeX form
    (it lowers ``{\\"O}`` at the start of a word in a journal name, for one). If the formatter
    changes the source's own text too, nothing is written."""
    written = latex_text(value)
    damaged = re.findall(r"\w*(?:\w\?+\w|\?\?|\ufffd|[\x80-\x9f])\w*", value)
    if damaged:  # a broken encoding at the source: nothing is guessed
        if formatter(value) != value:
            raise _Hold(f"{name}: the source text is damaged (" + ", ".join(repr(d) for d in damaged) + ")", {})
        return value, [f"{name}: the source text looks damaged (" + ", ".join(repr(d) for d in damaged)
                       + "); written as the source has it"]
    if formatter(written) == written:
        return written, _character_question(name, value)
    if formatter(value) == value:
        kept = [c for c in dict.fromkeys(value) if ord(c) >= 128]
        named = ", ".join(f"{c!r} ({unicodedata.name(c, 'unnamed character')})" for c in kept)
        return value, [f"{name}: the {name} formatter does not keep the LaTeX form of {named}; "
                       "written as the source has it"]
    raise _Hold(f"{name}: the {name} formatter changes the built text", {})


def _text(value):
    """A registry string on one line (a deposited line break is white space)."""
    return " ".join(str(value or "").split())


def _is_text(value):
    return value is None or isinstance(value, str)


def _readable(record):
    """The record without the parts that are not in the form Crossref documents, and
    ``{field: reason}`` for each part left out. The helpers are only ever given parts whose
    shape they expect, so an exception from one of them is a defect, not a bad record."""
    clean, problems = {k: v for k, v in record.items() if v is not None}, {}
    record = clean

    def leave_out(part, name):
        clean.pop(part, None)
        problems.setdefault(name, f"{name}: the record's {part} is not in the expected form")

    for part in ("title", "subtitle"):
        value = record.get(part)
        if value is not None and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            leave_out(part, "title")
    people = record.get("author")
    if people is not None and not (isinstance(people, list) and all(
            isinstance(p, dict) and all(_is_text(p.get(k)) for k in ("given", "family", "name", "suffix"))
            for p in people)):
        leave_out("author", "author")
    venues = record.get("container-title")
    if venues is not None and not (isinstance(venues, list) and all(isinstance(v, str) for v in venues)):
        leave_out("container-title", "journal")
    for part, name in (("volume", "volume"), ("issue", "number"), ("page", "pages"), ("article-number", "pages")):
        if not _is_text(record.get(part)):
            leave_out(part, name)
    for part in _DATES:
        value = record.get(part)
        if value is None:
            continue
        parts = value.get("date-parts") if isinstance(value, dict) else None
        if not (isinstance(parts, list) and all(
                isinstance(p, list) and all(isinstance(x, (int, str)) or x is None for x in p) for p in parts)):
            leave_out(part, "year")
    for part in ("update-to", "updated-by"):
        value = record.get(part)
        if value is not None and not (isinstance(value, list) and all(isinstance(v, dict) for v in value)):
            clean.pop(part, None)
    return clean, problems


def _people_text(people):
    return "; ".join(_text(p.get("name")) or _text(f"{p.get('given') or ''} {p.get('family') or ''}")
                     for p in people or [])


def _source_titles(record, evidence):
    """The record's title(s) as the comparator reads them (a split subtitle joined on)."""
    if "title" in evidence:
        return [_text(t) for t in evidence["title"]["source"]]
    return [_text(t) for t in record.get("title") or []]


# The banner some publishers put before the title of a retracted, withdrawn or removed
# article, once or twice over. It is not part of the title (Crossref: the original record's
# title is changed to carry it).
_BANNER_WORDS = (r"RETRACTED ARTICLE|Retracted Article|Retracted article|RETRACTED|Retracted|WITHDRAWN|Withdrawn"
                 r"|REMOVED|Removed")
_BANNER = re.compile(r"^(?:(?:\[(?:" + _BANNER_WORDS + r")\]\s*:?|(?:" + _BANNER_WORDS + r")\s*:)\s*)+")
# A title that announces a retraction rather than carrying a banner.
_NOTICE_TITLE = re.compile(r"^(?:Retraction|RETRACTION|Removal|Withdrawal)(?: [Nn]otice| NOTICE)?\s*:")
def _title(record, mapped, typed, evidence, unsupported):
    from .helpers import format_title
    if "title" not in evidence:
        raise _Hold("title: the source record's title could not be read")
    titles = [_BANNER.sub("", t) for t in _source_titles(record, evidence)]
    titles = [t for t in titles if t]
    if not titles:
        return None
    if len(titles) != 1:
        raise _Hold("title: several source titles", {"crossref": "; ".join(titles)})
    values = {"crossref": titles[0]}
    second = _BANNER.sub("", _text((mapped.get("title") or [""])[0])) if mapped else ""
    if second:
        values["pubmed"] = second
        if cp.normalize_title_safe(second) != cp.normalize_title_safe(titles[0]):
            raise _Hold("title: sources disagree", values, disagreement=True)
    # Formatting belongs to the same autofix helper used by check_bib.
    value = format_title(titles[0])
    value, doubts = _written("title", value, format_title)
    return _Value(value, "crossref+pubmed" if second else "crossref", values, doubts)


# Lower-case particles that begin a family name in the library's own bylines.
_PARTICLES = ("de la", "de los", "de las", "van der", "van den", "van de", "del", "de", "da", "dos", "das", "do",
              "du", "di", "van", "von", "ter", "ten", "la", "le")


def _family_question(people):
    """A question for each name whose family name may have lost its first word to the given
    names: the family begins with a lower-case particle and the given names are two or more
    words ending in a full word (Crossref: given "Jaime Fernández", family "del Río"). A
    given name that ends in an initial (Stéfan J. van der Walt) is not asked about."""
    asked = []
    for person in people:
        given, family = _text(person.get("given")), _text(person.get("family"))
        last = given.split(" ")[-1].strip(".") if given else ""
        if (any(family.startswith(particle + " ") for particle in _PARTICLES) and len(given.split(" ")) > 1
                and len(last) > 2 and last[1:].islower()):
            asked.append(f"author: the source gives the given names {given!r} and the family name {family!r}; "
                         f"the family name may be {last + ' ' + family!r}")
    return asked


def _author(record, mapped, typed):
    from .helpers import reformat_author
    people, source = record.get("author") or [], "crossref"
    if not people and mapped and mapped.get("author"):
        people, source = mapped["author"], "pubmed"
    if not people:
        return None
    values = {source: _people_text(people)}
    try:
        value = cp.source_authors({"author": people}, typed or None)
    except ValueError as exc:
        raise _Hold(str(exc), values)
    if source == "crossref" and mapped and mapped.get("author"):
        values["pubmed"] = _people_text(mapped["author"])
        if not compatible_authors({"author": people}, mapped):
            raise _Hold("author: sources disagree", values, disagreement=True)
        source = "crossref+pubmed"
    try:
        value, doubts = _written("author", value, reformat_author)
    except _Hold as hold:
        raise _Hold(hold.reason, values)
    return _Value(value, source, values, _family_question(people) + doubts)


def _journal(record):
    from .helpers import format_journal_name
    venues = [_text(v) for v in record.get("container-title") or [] if _text(v)]
    if not venues:
        return None
    values = {"crossref": "; ".join(venues)}
    if len(venues) != 1 or re.search(r"[<>{}\\$]", venues[0]):
        raise _Hold("journal: no single registry venue", values)
    value = format_journal_name(cp.journal_text(venues[0]))  # the publisher's name, "The" included
    try:
        if normalize_journal(value) != normalize_journal(venues[0]):
            raise _Hold("journal: formatter changes the venue", values)
    except ValueError as exc:
        raise _Hold("journal: " + str(exc), values)
    try:
        value, doubts = _written("journal", value, format_journal_name)
    except _Hold as hold:
        raise _Hold(hold.reason, values)
    return _Value(value, "crossref", values, doubts)


def _booktitle(record, kind):
    """The proceedings or the book a paper or chapter is in: the record's one container
    title in the form the verifier documents as the house form of a source name
    (``verification.proceedings_name_forms``: no year, no final acronym;
    ``verification.book_title_forms``: no series number, no volume-pack tail), through the
    format checker's formatter for ``booktitle``. A record with several container titles
    (a series and a book, in no stated order) fills nothing."""
    from .helpers import format_journal_name
    from .verification import book_title_forms, ordinal_form, proceedings_name_forms
    venues = [_text(v) for v in record.get("container-title") or [] if _text(v)]
    if not venues:
        return None
    values = {"crossref": "; ".join(venues)}
    if len(venues) != 1 or re.search(r"[<>{}\\$]", venues[0]):
        raise _Hold("booktitle: no single registry title", values)
    source = html.unescape(venues[0])
    form = proceedings_name_forms(source) if kind == "inproceedings" else book_title_forms(source)
    value = format_journal_name(cp.journal_text(form))
    try:
        if ordinal_form(normalized(value)) != ordinal_form(normalized(form)):
            raise _Hold("booktitle: formatter changes the title", values)
    except ValueError as exc:
        raise _Hold("booktitle: " + str(exc), values)
    try:
        value, doubts = _written("booktitle", value, format_journal_name)
    except _Hold as hold:
        raise _Hold(hold.reason, values)
    return _Value(value, "crossref", values, doubts)


def _publisher_format(name):
    from . import helpers
    return helpers.format_journal_name(name, key=helpers.publisher_key, dotted_initials=True)


def _publisher(record):
    """The record's publisher through the format checker's publisher formatter, when that
    leaves the name the verifier compares (``verification.normalize_book_publisher``) as it
    is and changes no letter's case; a name the formatter turns into another (``Springer New
    York`` -> ``Springer``) or respells (``Springer US`` -> ``Springer Us``) is not written."""
    from .helpers import remove_curlies
    from .verification import normalize_book_publisher
    name = _text(record.get("publisher")) if isinstance(record.get("publisher"), str) else ""
    if not name:
        return None
    values = {"crossref": name}
    if re.search(r"[<>{}\\$]", name):
        raise _Hold("publisher: no plain registry name", values)
    value = _publisher_format(html.unescape(name))
    try:
        letters = [re.sub(r"[^A-Za-z]", "", latex_text(text)) for text in (remove_curlies(value), html.unescape(name))]
        if normalize_book_publisher(value) != normalize_book_publisher(name) or letters[0] != letters[1]:
            raise _Hold("publisher: formatter changes the registry name", values)
    except ValueError as exc:
        raise _Hold("publisher: " + str(exc), values)
    try:
        value, doubts = _written("publisher", value, _publisher_format)
    except _Hold as hold:
        raise _Hold(hold.reason, values)
    return _Value(value, "crossref", values, doubts)


def _volume(record, mapped):
    value, source = _text(record.get("volume")), "crossref"
    second = _text(mapped.get("volume")) if mapped else ""
    if not value and second:
        value, source = second, "pubmed"
    if not value:
        return None
    values = {source: value}
    if source == "crossref" and second:
        values["pubmed"] = second
    if not re.fullmatch(r"[1-9]\d*", value):
        raise _Hold("volume: no plain numeric source value", values)
    if source == "crossref" and second:
        if second != value:
            raise _Hold("volume: sources disagree", values, disagreement=True)
        source = "crossref+pubmed"
    return _Value(value, source, values)


def _number(record, mapped):
    """The issue, only when a source states it (correction_proposals.confirm_issue)."""
    values = dict(cp.issue_statements(record, mapped))
    try:
        decision = cp.confirm_issue(record, mapped, None)
    except cp.IssueLookupRequired:
        return None  # no record at hand states an issue: none is written
    except ValueError as exc:
        raise _Hold(str(exc), values, disagreement=len(values) > 1)
    return _Value(decision["issue"], "+".join(decision["sources"]), values)


def _article_number(pages, record, from_article_number):
    """Whether a lone locator is an article number rather than a first page: Crossref's
    ``article-number`` field, a lettered locator (e1234), a number of six or more digits,
    or the number the DOI itself ends in (10.3389/fpsyg.2012.00335 -> 335)."""
    if from_article_number or not pages.isdigit() or len(pages) >= 6:
        return True
    return bool(re.search(r"(?<![1-9])0*" + re.escape(pages.lstrip("0") or "0") + r"$", str(record.get("DOI") or "")))


def _cased(pages, raw):
    """``pages`` (as ``expanded_pages`` gives them, in lower case) with the letters of each
    page label in the case the source prints them: ``S12-9`` -> ``S12-S19``."""
    labels = re.findall(r"[A-Za-z]+(?=\d)", raw)
    def label(match):
        printed = next((x for x in labels if x.lower() == match[0]), None)
        return printed or match[0]
    return re.sub(r"[a-z]+(?=\d)", label, pages)


def _pages(record, mapped):
    first = _text(record.get("page") or record.get("article-number"))
    second = _text(mapped.get("page")) if mapped else ""
    if not first and not second:
        return None
    values = {k: v for k, v in (("crossref", first), ("pubmed", second)) if v}
    try:
        stated = {k: expanded_pages(v) for k, v in values.items()}
    except ValueError as exc:
        raise _Hold("pages: " + str(exc), values)
    if any(not _PAGES.fullmatch(v) for v in stated.values()):
        raise _Hold("pages: unsupported source locator", values)
    one, two = stated.get("crossref"), stated.get("pubmed")
    doubts = []
    if one and two and one != two:
        # A source that gives only the first page does not contradict the other's range
        # (the reading of correction_proposals.shortens_pages): the range is the value.
        if cp.shortens_pages(two, one):
            pages, source, printed = two, "pubmed; crossref gives the first page", second
        elif cp.shortens_pages(one, two):
            pages, source, printed = one, "crossref; pubmed gives the first page", first
        else:
            raise _Hold("pages: sources disagree", values, disagreement=True)
    else:
        pages, printed = one or two, first or second
        source = "crossref+pubmed" if one and two else "crossref" if one else "pubmed"
        number = _text(record.get("article-number"))
        from_number = bool(one and number and (not record.get("page") or _text(record.get("page")) == number))
        if "+" not in source and "-" not in pages and not _article_number(pages, record, from_number):
            doubts.append(f"pages: the source gives only a first page ({pages}); the last page is not confirmed")
    return _Value(_cased(pages, printed).replace("-", "--"), source, values, doubts)


def _proceedings_pages(outcome, doi):
    """The pages of a paper in proceedings, as a question when the paper is in the ACL
    Anthology: the Anthology's own record outranks Crossref's page range (``acl_review``;
    Crossref deposits 3980-3990 for 10.18653/v1/d19-1410, the Anthology and the paper give
    3982--3992), and the builder does not read the Anthology."""
    from .acl_review import parse_id
    try:
        parse_id(doi)
    except ValueError:
        return outcome
    if outcome is not None:
        outcome.doubts.append(f"pages: {doi} is an ACL Anthology paper; the Anthology's record outranks Crossref's "
                              "page range and was not read, so the pages are not confirmed")
    return outcome


def _year(record, mapped, evidence):
    """The year of the printed issue. One year in the record: that year. Print and online
    years that differ: the print year when the DOI-linked PubMed record gives the same year
    (``issue_year_proposal``'s rule), or when the online date is a later digitisation of a
    backfile (``verification.print_year_selects_cited``); otherwise nothing is chosen."""
    years = list(evidence.get("year", {}).get("source") or [])
    values = {}
    for name in _DATES:
        for parts in (record.get(name) or {}).get("date-parts") or []:
            if parts and parts[0] is not None:
                values["crossref " + name] = str(parts[0])
    second = str(mapped["published"]["date-parts"][0][0]) if mapped else ""
    if second:
        values["pubmed"] = second
    if not years:
        return _Value(second, "pubmed", values) if second else None
    if len(years) == 1:
        if second and second != years[0]:
            raise _Hold("year: sources disagree", values, disagreement=True)
        return _Value(years[0], "crossref+pubmed" if second else "crossref", values)
    prints = [str(p[0]) for p in (record.get("published-print") or {}).get("date-parts") or [] if p]
    if len(prints) == 1 and re.fullmatch(r"[1-9]\d{3}", prints[0]):
        if second:
            if second == prints[0]:
                return _Value(prints[0], "crossref+pubmed", values)
            raise _Hold("year: sources disagree", values, disagreement=True)
        probe = {"ENTRYTYPE": "article", "year": prints[0], "volume": str(record.get("volume") or ""),
                 "pages": str(record.get("page") or record.get("article-number") or "")}
        if print_year_selects_cited(probe, record):
            return _Value(prints[0], "crossref", values)
    raise _Hold("year: print and online years differ and no rule selects one", values)


def _update_kind(update):
    return str(update.get("type") or "").lower().replace("_", " ").replace("-", " ")


def _refuse_notice(record):
    """A record that is a correction, erratum or retraction notice is never the record."""
    for update in record.get("update-to") or []:
        kind = _update_kind(update)
        if any(word in kind for word in NOTICE_WORDS):
            article = "an" if kind[:1] in "aeiou" else "a"
            raise CompletionRefused(
                f"The record {record.get('DOI')} is {article} {kind} of {update.get('DOI')}, "
                "not the article itself; cite the article")


def _retractions(record):
    """The DOIs of the retraction notices the record names for itself (``updated-by``)."""
    return [str(u.get("DOI") or "no DOI given") for u in record.get("updated-by") or []
            if any(word in _update_kind(u) for word in RETRACTION_WORDS)]


def _surnames(byline):
    """The typed surnames, as the comparator normalises text (LaTeX accents read as letters)."""
    from .name_parsing import splitname
    out = set()
    for name in split_authors(byline or ""):
        try:
            if name.startswith("{"):
                out.add(normalized(name))
            else:
                parts = splitname(name, strict_mode=True)
                out.add(normalized(" ".join(parts["von"] + parts["last"])))
        except ValueError:  # a name BibTeX cannot split, or markup the comparator refuses
            continue
    return out - {""}


def _different_work(typed, record, evidence):
    """What the typed entry says that this record does not: "title", "authors", or None.

    A typed title is the test when there is one: it must match the record's title, or be
    within the small difference the identity rule allows (two word edits, or the record's
    title without its subtitle; ``correction_proposals.title_small_difference``). With no
    typed title, typed authors must share at least one surname with the record's."""
    title, author = typed.get("title"), typed.get("author")
    if title:
        if evidence.get("title", {}).get("match"):
            return None
        if any(cp.title_small_difference(title, t) for t in _source_titles(record, evidence)):
            return None
        return "title and authors" if author and not evidence.get("author", {}).get("match") else "title"
    if author and not evidence.get("author", {}).get("match"):
        theirs = set()
        for person in record.get("author") or []:
            try:
                theirs.add(normalized(person.get("family") or person.get("name") or ""))
            except ValueError:
                continue
        if theirs - {""} and not (_surnames(author) & theirs):
            return "authors"
    return None


def _as_typed(proposal, typed, kind, questions):
    """The proposal for an entry nothing is filled into: every typed field stays."""
    fields = {k: v for k, v in typed.items() if k not in ("ENTRYTYPE", "ID")}
    for name in sorted(fields):
        if name in questions:
            proposed, source = questions[name]
            proposal.changes.append(FieldChange(name, fields[name], proposed, source, "question"))
        else:
            proposal.changes.append(FieldChange(name, fields[name], fields[name], "typed", "kept"))
    proposal.needs_decision = True
    proposal.proposed_raw = render(kind, proposal.key_typed or NO_KEY, fields)
    return proposal


def _formatters():
    """The format checker's formatter for each field it rewrites (``helpers.check_bib``)."""
    from . import helpers
    return {"title": helpers.format_title, "journal": helpers.format_journal_name,
            "booktitle": helpers.format_journal_name, "publisher": _publisher_format,
            "author": helpers.reformat_author, "editor": helpers.reformat_author,
            "address": lambda value: helpers.format_journal_name(value, key=helpers.address_key,
                                                                 force_caps=helpers.address_codes)}


def _house_form(name, value):
    """A typed value as the format checker would write it (helpers.check_bib rewrites the
    title, the journal, the book title, the publisher, the address, the authors, the editors
    and the pages; it leaves every other field alone), with
    raw non-ASCII letters in the library's LaTeX form. A DOI is never rewritten. When the
    formatter would not leave the LaTeX form alone, the typed value is returned unchanged
    (``_house_question`` then says so)."""
    formatter = _formatters().get(name)
    if name == "doi":
        return value
    if name == "pages":
        from .helpers import valid_pages
        return valid_pages(value)[1][1]
    formed = formatter(value) if formatter else value
    written = latex_text(formed)  # new text is written in the library's LaTeX form
    if formatter and formatter(written) != written:
        return value
    return written


def _house_question(name, value):
    """Why a typed value is kept although it is not in the library's LaTeX form, or None."""
    formatter = _formatters().get(name)
    if not formatter:
        return None
    written = latex_text(formatter(value))
    if formatter(written) == written:
        return None
    kept = [c for c in dict.fromkeys(value) if ord(c) >= 128]
    named = ", ".join(f"{c!r} ({unicodedata.name(c, 'unnamed character')})" for c in kept)
    return (f"{name}: the {name} formatter does not keep the LaTeX form of {named}; "
            "the typed value is kept as typed")


def _usable_corroboration(mapped):
    """Whether a corroborating record has the shape ``auto_review.epmc_record`` returns."""
    def texts(value):
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    try:
        year = mapped["published"]["date-parts"][0][0]
    except (KeyError, IndexError, TypeError):
        return False
    return (isinstance(mapped.get("DOI"), str) and texts(mapped.get("title")) and len(mapped["title"]) == 1
            and isinstance(year, (int, str))
            and isinstance(mapped.get("author"), list) and all(
                isinstance(p, dict) and all(_is_text(p.get(k)) for k in ("given", "family", "suffix"))
                for p in mapped["author"])
            and texts(mapped.get("container-title", []))
            and all(_is_text(mapped.get(k)) for k in ("volume", "issue", "page")))


def build(typed_fields, record, corroborating=None):
    """Propose a complete entry for ``record``: an ``@article``, an ``@inproceedings`` or an
    ``@incollection`` (``KINDS``). With no typed entry type, the type is the one the record's
    type is built as; a typed type is never changed, and a record of another type fills
    nothing.

    ``typed_fields``: the entry as typed, by lower-case field name, with ``ENTRYTYPE`` and
    ``ID`` when there are any (``{"doi": ...}`` alone is enough). ``record``: the Crossref
    record of the work. ``corroborating``: the PubMed record for the same DOI in the shape
    ``auto_review.epmc_record`` returns, or None.

    A paper in proceedings has no publisher, address or editors filled, and a chapter no
    address or editors: the record the client keeps states no place, and the verifier has
    no check for an editor, so an entry with one could not be verified. A chapter's record
    lists them under ``unfilled``.

    Raises ``CompletionRefused`` when the record is a correction or retraction notice.
    """
    from .helpers import authors2key, split_names
    typed = {(k if k in ("ENTRYTYPE", "ID") else k.lower()): v for k, v in typed_fields.items()
             if v is not None and str(v) != ""}
    given_kind = str(typed.get("ENTRYTYPE") or "").lower()
    named = record.get("type") if isinstance(record.get("type"), str) and record.get("type") else None
    kind = given_kind or RECORD_KINDS.get(named, "article")
    record_doi = record.get("DOI").strip() if isinstance(record.get("DOI"), str) else ""
    if typed.get("ID") == NO_KEY:  # the placeholder is not a key
        del typed["ID"]
    proposal = Proposal(key_typed=typed.get("ID") or None, entry_type=kind, record_source="crossref",
                        doi=typed.get("doi") or record_doi or None)
    if kind not in KINDS:
        proposal.unsupported = kind
        proposal.issues.append(f"An entry of type {kind} is not built automatically; the entry is left as typed")
        return proposal
    if named not in RECORD_KINDS:
        proposal.unsupported = named or "unknown"
        proposal.issues.append((f"A record of type {named}" if named else "A record with no type")
                               + " is not built automatically; the entry is left as typed")
        return proposal
    if named != KINDS[kind].record:  # the typed type is the person's: a record of another type fills nothing
        proposal.unsupported = named
        proposal.issues.append(f"A record of type {named} is not built as an entry of type {kind}; "
                               "the entry is left as typed")
        return proposal
    spec = KINDS[kind]
    record, problems = _readable(record)
    _refuse_notice(record)

    def same_doi(one, two):
        try:
            return normalize_doi(one) == normalize_doi(two)
        except ValueError:
            return False

    mapped = corroborating
    if mapped is not None:
        if not isinstance(mapped, dict) or not _usable_corroboration(mapped):
            mapped = None
            proposal.issues.append("The PubMed record is not in the expected form and was not used")
        elif same_doi(mapped["DOI"], record_doi):
            proposal.record_source = "crossref+pubmed"
        else:
            mapped = None
            proposal.issues.append("The PubMed record is for another DOI and was not used")

    # A supplied DOI is never replaced: a record with another DOI fills nothing.
    if typed.get("doi") and not same_doi(str(typed["doi"]), record_doi):
        proposal.issues.append(f"doi: the record's DOI {record_doi} is not the typed DOI {typed['doi']}; "
                               "nothing was filled from it")
        return _as_typed(proposal, typed, kind, {"doi": (typed["doi"], "typed")})

    keep = set(_field_order())
    house = {k: v for k, v in typed.items() if k in keep and (k != "publisher" or kind != "article")}
    evidence, compare_issues = safe_compare(dict(house, ENTRYTYPE=kind), record)
    unsupported = next((i for i in compare_issues if i.startswith("Unsupported source metadata")), None)

    conflict = _different_work(typed, record, evidence)
    if conflict:
        titles = _source_titles(record, evidence)
        names = ", ".join(_text(p.get("family") or p.get("name")) for p in record.get("author") or [])
        subject = (f"the DOI {typed['doi']} resolves to" if typed.get("doi") else f"the record {record_doi} is")
        proposal.issues.append(
            f"doi: {subject} a different work than the typed {conflict} (the record: \""
            + "; ".join(titles) + f"\", by {names or 'no named author'}); nothing was filled from it")
        questions = {}
        if typed.get("doi"):
            questions["doi"] = (typed["doi"], "typed")
        for name, make in (("title", lambda: _title(record, mapped, "", evidence, unsupported)),
                           ("author", lambda: _author(record, mapped, None))):
            if typed.get(name):
                try:
                    outcome = make()
                except _Hold:
                    outcome = None
                questions[name] = (outcome.value if outcome else None, outcome.source if outcome else "crossref")
        return _as_typed(proposal, typed, kind, questions)

    retractions = _retractions(record)
    banner = next((_BANNER.match(t)[0].strip() for t in _source_titles(record, evidence) if _BANNER.match(t)), None)
    if retractions:  # decision log: retractions are flagged for the person; nothing automatic
        proposal.issues.append(("The article" if kind == "article" else "The work")
                               + " was retracted (the retraction notice: " + ", ".join(retractions)
                               + "); it is not added without a decision")
        proposal.needs_decision = True
    elif banner:
        proposal.issues.append(f"The publisher's title begins with \"{banner}\"; it is not added without a decision")
        proposal.needs_decision = True
    elif any(_NOTICE_TITLE.match(t) for t in _source_titles(record, evidence)):
        proposal.issues.append("The record's title reads as a retraction or removal notice; it is not added "
                               "without a decision")
        proposal.needs_decision = True
    if record.get("update-to") or record.get("updated-by"):
        proposal.issues.append(CORRECTION_FLAG)

    makers = {
        "author": lambda: _author(record, mapped, typed.get("author")),
        "booktitle": lambda: _booktitle(record, kind),
        "journal": lambda: _journal(record),
        "number": lambda: _number(record, mapped),
        "pages": lambda: _proceedings_pages(_pages(record, mapped), record_doi) if kind == "inproceedings"
        else _pages(record, mapped),
        "publisher": lambda: _publisher(record),
        "title": lambda: _title(record, mapped, typed.get("title"), evidence, unsupported),
        "volume": lambda: _volume(record, mapped),
        "year": lambda: _year(record, mapped, evidence),
    }
    fields = {}

    def keep_typed(name, had):
        """The typed value stays; in house form when the format checker would rewrite it."""
        formed = _house_form(name, had)
        fields[name] = formed
        asked = _house_question(name, had) if formed == had else None
        if asked:
            proposal.changes.append(FieldChange(name, had, had, "typed", "question"))
            proposal.issues.append(asked)
            proposal.needs_decision = True
        elif formed == had:
            proposal.changes.append(FieldChange(name, had, had, "typed", "kept"))
        else:
            proposal.changes.append(FieldChange(name, had, formed, "house format", "changed"))

    def question(name, had, value, source, reasons):
        fields[name] = had if had else value
        proposal.changes.append(FieldChange(name, had, value, source, "question"))
        proposal.issues.extend([reasons] if isinstance(reasons, str) else reasons)
        proposal.needs_decision = True

    for name in spec.built:
        had = typed.get(name)
        if name == "doi":
            if had:
                keep_typed(name, had)
            elif record_doi:
                try:
                    normalize_doi(record_doi)  # a usable DOI; written as the record gives it
                except ValueError as exc:
                    proposal.unfilled.append(Unfilled(name, str(exc), {"crossref": record_doi}))
                else:
                    fields[name] = record_doi
                    proposal.changes.append(FieldChange(name, None, record_doi, "crossref", "filled"))
            continue
        try:
            outcome = makers[name]()
        except _Hold as hold:
            if hold.disagreement and not (had and name == "year"):
                # Sources that disagree are for a person to settle, whatever the field.
                shown = "; ".join(f"{source}: {value}" for source, value in hold.values.items())
                proposal.issues.append(hold.reason if hold.reason.startswith("number:") or not shown
                                       else f"{hold.reason} ({shown})")
                proposal.needs_decision = True
            if had and name == "year":
                # The sources leave the year open: the typed one stays, unconfirmed.
                proposal.unfilled.append(Unfilled(name, hold.reason, hold.values))
                question(name, had, had, "typed",
                         f"{hold.reason}; the typed year {had} is kept and is not confirmed")
            elif had:
                keep_typed(name, had)
                if hold.disagreement or not evidence.get(name, {}).get("match"):
                    proposal.unfilled.append(Unfilled(name, hold.reason, hold.values))
            else:
                proposal.unfilled.append(Unfilled(name, hold.reason, hold.values))
            continue
        if outcome is None:
            reason = problems.get(name) or f"{name}: no source record states it"
            if had:  # no source states it: left as typed, and said so
                keep_typed(name, had)
                proposal.unfilled.append(Unfilled(name, reason, {}))
            elif name in spec.expected or name in problems:
                proposal.unfilled.append(Unfilled(name, reason, {}))
            continue
        value, source, values = outcome.value, outcome.source, outcome.values
        if not had:
            if outcome.doubts:
                question(name, None, value, source, outcome.doubts)
            else:
                fields[name] = value
                proposal.changes.append(FieldChange(name, None, value, source, "filled"))
            continue
        # The year is the print year by rule, so only the same year counts as agreement.
        if value == had or (name != "year" and evidence.get(name, {}).get("match")):
            keep_typed(name, had)
            continue
        reason = None
        if name == "author":
            hold = cp.surname_change_hold(proposal.key_typed, had, value, source=source)
            if hold:  # a surname respelling is always the person's to decide
                question(name, had, value, source, hold)
                continue
            people = record.get("author") or (mapped or {}).get("author") or []
            if cp.byline_loses_detail(had, people):
                reason = "author: citation byline has detail the source lacks"
        if name == "pages" and cp.shortens_pages(had, value):
            reason = "pages: the source would shorten the cited range"
        if reason is None and cp.loses_characters(had, value, name):
            reason = f"{name}: source value drops accents or has a replacement character"
        if reason:
            keep_typed(name, had)
            proposal.unfilled.append(Unfilled(name, reason, values))
        elif outcome.doubts:
            question(name, had, value, source, outcome.doubts)
        else:
            fields[name] = value
            proposal.changes.append(FieldChange(name, had, value, source, "changed"))

    # Other typed house fields stay as typed; the rest are dropped, as the format checker does.
    dropped = []
    for name in spec.unverified:
        if not typed.get(name):
            # A field the library's entries of this type usually have. The verifier has no
            # check for it, so it is not written; what the record says is listed.
            people = record.get(name) if name == "editor" and isinstance(record.get(name), list) else []
            stated = _people_text([p for p in people if isinstance(p, dict)])
            proposal.unfilled.append(Unfilled(
                name, f"{name}: the verifier has no check for this field; the record's value is not written"
                if stated else f"{name}: no source record states it", {"crossref": stated} if stated else {}))
    for name in sorted(k for k in typed if k not in ("ENTRYTYPE", "ID") and k not in spec.built):
        if name == "publisher" and cp.drop_publisher_proposal(
                {"fields": {"ENTRYTYPE": kind, "publisher": typed[name]}, "key": proposal.key_typed,
                 "fingerprint": None}):
            dropped.append(FieldChange(name, typed[name], None, "house rule: no publisher on an article", "dropped"))
        elif name in keep:
            keep_typed(name, typed[name])
        else:
            dropped.append(FieldChange(name, typed[name], None, "not a house field", "dropped"))
    order = _field_order()
    proposal.changes.sort(key=lambda c: order.index(c.field))
    proposal.changes += dropped

    if fields.get("year") and any(name.strip() for name in split_names(fields.get("author") or "")):
        proposal.key_proposed = authors2key(fields["author"], fields["year"])
    if not proposal.key_typed and not proposal.key_proposed:
        proposal.unfilled.append(Unfilled("ID", "a key needs the authors and the year", {}))
    proposal.doi = fields.get("doi") or proposal.doi
    proposal.proposed_raw = render(kind, proposal.key_typed or proposal.key_proposed or NO_KEY, fields)
    _set_complete(proposal, fields)
    return proposal


def required_fields(entry_type, fields=None):
    """The fields an entry of ``entry_type`` must have to be accepted without a decision:
    ``KINDS`` for the types built from a Crossref record; for a book, its title, its year and
    its authors (the editors, when ``fields`` has editors and no author: an edited volume).
    Any other type is held to the article's."""
    kind = str(entry_type or "").lower()
    if kind == "book":
        edited = fields is not None and not fields.get("author") and fields.get("editor")
        return ("editor" if edited else "author", "title", "year")
    return KINDS.get(kind, KINDS["article"]).required


def _set_complete(proposal, fields):
    """Set ``Proposal.complete``: the entry has a key and every required field of its type
    (``required_fields``), and none of
    them is a question. An entry that is not complete needs a decision. The one rule, for
    every builder (``build``, ``build_arxiv`` and ``propose`` when it rewrites the text)."""
    asked = {c.field for c in proposal.changes if c.kind == "question"}
    required = required_fields(proposal.entry_type, fields)
    proposal.complete = bool((proposal.key_typed or proposal.key_proposed)
                             and all(fields.get(name) and name not in asked for name in required))
    if not proposal.complete:
        proposal.needs_decision = True


# --- finding the work ---------------------------------------------------------------------------
#
# ``Query`` is what the person gave; ``identify`` asks the sources which work it is;
# ``propose`` builds the entry and has it checked. None of them prints, prompts or builds a
# network object: the client and the cache are the caller's.

from .verification import ProviderError  # noqa: E402 - raised by identify when a source does not answer

ARXIV_JOURNAL = "{arXiv}"  # written ``Journal = {{arXiv}}``, as every arXiv entry of the library has it
LOOKUP_FAILED = "provider_error"  # the verifier's own status for a source that did not answer
SHORT_LIST = 5  # how many candidates a person is shown

_PMID_TEXT = re.compile(r"(?:pmid\s*:?\s*|https?://pubmed\.ncbi\.nlm\.nih\.gov/)(\d{1,9})/?", re.I)
_DOI_PREFIX = re.compile(r"^(?:(?:https?://)?(?:dx\.|www\.)?doi\.org/|doi\s*:\s*|doi\s+)", re.I)
_ARXIV_LINK = re.compile(r"^(?:https?://)?(?:www\.)?(arxiv\.org/(?:abs|pdf)/[^?#\s]+?)(?:\.pdf)?(?:[?#]\S*)?$", re.I)
# The check the first layers of the verifier make is not the whole gate: said on every
# proposal whose status is not an accepted one.
FIRST_CHECK = "This status comes from the first check only; `cdlbib verify` runs the full check."
# DataCite relations by which an arXiv record names its published version.
_PUBLISHED_RELATIONS = {"IsPreprintOf", "IsVersionOf", "IsIdenticalTo"}


def _doi_text(text):
    """``text`` as a DOI without its resolver prefix, in the case it was given; None when
    it is not a DOI (``verification.normalize_doi`` is the test)."""
    return _doi_read(text)[0]


def _doi_read(text):
    """``_doi_text`` and what was cut from the end, if anything: punctuation that cannot
    end a DOI (``.``, ``,``, ``;``, ``:``, and a closing bracket with no opening one inside
    the DOI, so ``10.1016/S0140-6736(97)11096-0`` keeps its bracket)."""
    from urllib.parse import unquote
    value = unquote(_DOI_PREFIX.sub("", text.strip()).replace("\\_", "_"))
    try:
        normalize_doi(value)
    except ValueError:
        return None, ""
    kept = value
    while len(kept) > 1 and (kept[-1] in ".,;:" or (kept[-1] == ")" and kept.count(")") > kept.count("("))
                             or (kept[-1] == "]" and kept.count("]") > kept.count("["))):
        kept = kept[:-1]
    try:
        normalize_doi(kept)
    except ValueError:
        return value, ""
    return kept, value[len(kept):]


def _arxiv_text(text):
    """``text`` as an arXiv identifier (``2208.02957``, with ``v2`` when a version was
    given); None when it is not one (``arxiv_review.parse_id`` is the test)."""
    from .arxiv_review import parse_id
    value = text.strip()
    link = _ARXIV_LINK.match(value)
    if link:  # with or without the scheme, a final .pdf, a query (?context=...) or a fragment
        value = "https://" + link[1]
    try:
        base, version = parse_id(value)
    except ValueError:
        return None
    return base + (f"v{version}" if version else "")


@dataclass
class Query:
    """What the person gave: one identifier, or a title with an author and a year."""
    doi: str | None = None
    pmid: str | None = None
    arxiv: str | None = None
    title: str | None = None
    author: str | None = None
    year: str | None = None
    raw: str | None = None   # the typed entry's text, when the query is a typed entry
    key: str | None = None   # its key
    fields: dict | None = None  # its fields (with ENTRYTYPE and ID), as load_entries gives them
    notes: list[str] = field(default_factory=list)  # what was done to the text to read it
    isbn: str | None = None  # a book, looked up in the Library of Congress catalogue (book_build)
    lccn: str | None = None  # the same, by the Library's control number
    book: bool = False       # the title and author are a book's: the catalogue is searched

    @classmethod
    def parse(cls, text, author=None, year=None, book=False):
        """A DOI or DOI link, ``PMID:123`` or a PubMed link, an arXiv id, link or DOI, an
        ISBN (``ISBN 978...``, or a bare ISBN-13), ``LCCN 2012007685``; anything else is the
        words of a title (a book's, with ``book``)."""
        from .book_build import isbn_text, lccn_text
        text = " ".join(str(text or "").split())
        author, year = (author or "").strip() or None, str(year or "").strip() or None
        if isbn_text(text):
            return cls(isbn=isbn_text(text), book=True)
        if lccn_text(text):
            return cls(lccn=lccn_text(text), book=True)
        if book:
            return cls(title=text or None, author=author, year=year, book=True)
        pmid = _PMID_TEXT.fullmatch(text)
        if pmid:
            return cls(pmid=pmid[1], author=author, year=year)
        arxiv = _arxiv_text(text) if text else None
        if arxiv:
            return cls(arxiv=arxiv, author=author, year=year)
        doi, cut = _doi_read(text) if text else (None, "")
        if doi:
            said = [f"The DOI was read as {doi}: the final {cut!r} was taken as punctuation after it."] if cut else []
            return cls(doi=doi, author=author, year=year, notes=said)
        return cls(title=text or None, author=author, year=year)

    @classmethod
    def from_candidate(cls, candidate):
        """The query for a candidate a person picked (a dict with any of ``source``, ``doi``,
        ``pmid``, ``arxiv``, ``title``): the one rule every front end uses. The identifier of
        the source the candidate came from: an arXiv lead by its arXiv id; anything else by
        its DOI, else its PMID, else an arXiv id, else its title. ValueError when it has
        none of them. A catalogue record (``source`` "loc-catalogue") by its LCCN."""
        if candidate.get("source") == "loc-catalogue" and candidate.get("lccn"):
            return cls(lccn=str(candidate["lccn"]), book=True)
        arxiv = str(candidate.get("arxiv") or "").strip()
        if arxiv and candidate.get("source") == "arxiv":
            return cls(arxiv=_arxiv_text(arxiv) or arxiv)
        doi = _doi_read(str(candidate.get("doi") or "").strip())[0]
        if doi:
            return cls(doi=doi)
        if candidate.get("pmid"):
            return cls(pmid=str(candidate["pmid"]).strip())
        if arxiv:
            return cls(arxiv=_arxiv_text(arxiv) or arxiv)
        if str(candidate.get("title") or "").strip():
            return cls.parse(candidate["title"], year=str(candidate.get("year") or "").split("/")[0] or None)
        raise ValueError("This record has no DOI, PMID, arXiv id or title to look it up by.")

    @classmethod
    def from_entry(cls, entry):
        """The query a typed entry makes (``verification.load_entries`` shape). An entry
        that names arXiv as its journal is an arXiv query; otherwise its DOI comes first,
        then a PMID, then its title, authors and year."""
        from .arxiv_review import identifier
        from .verification import arxiv_id
        fields = dict(entry["fields"])
        doi = (fields.get("doi") or "").strip() or None
        if doi and _doi_read(doi)[1]:
            doi = _doi_read(doi)[0]  # looked up without the punctuation; the typed text stays (propose)
        arxiv = None
        try:
            base, version, _ = identifier(dict(fields, ENTRYTYPE=str(fields.get("ENTRYTYPE", "")).lower()))
            arxiv = base + (f"v{version}" if version else "")
        except ValueError:
            if doi and _arxiv_text(doi):
                arxiv = _arxiv_text(doi)
            elif not doi and not fields.get("journal"):
                arxiv = _arxiv_text(arxiv_id(fields) or "")
        if arxiv:
            doi = None
        pmid = re.fullmatch(r"\s*(?:pmid\s*:?\s*)?(\d{1,9})\s*", fields.get("pmid") or "", re.I)
        return cls(doi=doi, pmid=pmid[1] if pmid else None, arxiv=arxiv,
                   title=fields.get("title") or None, author=fields.get("author") or None,
                   year=fields.get("year") or None, raw=entry.get("raw"), key=entry.get("key"), fields=fields)


@dataclass
class Identified:
    """What the sources say the work is.

    ``record``: the Crossref record (``source`` "crossref"), or the saved arXiv documents
    ``arxiv_review.collect`` returns (``source`` "arxiv"); None when no single record was
    found. ``corroborating``: the PubMed record for the same DOI in the shape ``build``
    takes. ``candidates``: the records a person chooses from, each with ``authors``,
    ``year``, ``journal``, ``doi``, ``title``, ``type`` and ``source``. ``published_for``:
    the preprint (a DOI or ``arXiv:<id>``) whose published version ``record`` is.
    ``decision`` and ``questions`` are part of the answer: a caller that builds from
    ``record`` without ``propose`` must put ``decision`` in the proposal's issues, turn
    each field of ``questions`` into a question with its reason, and set ``needs_decision``
    (``propose`` does; ``needs_a_decision`` says whether any of this applies).
    ``source`` "pubmed": ``record`` is the PubMed record of a paper PubMed gives no DOI
    for, in the Crossref shape ``extra_sources.medline_record`` makes.
    """
    record: dict | None = None
    corroborating: dict | None = None
    candidates: list[dict] = field(default_factory=list)
    source: str | None = None
    note: str | None = None
    published_for: str | None = None
    decision: str | None = None  # why the proposal built from ``record`` needs a decision
    questions: dict = field(default_factory=dict)  # {field: reason}: built values that are not settled

    @property
    def needs_a_decision(self):
        """Whether an entry built from ``record`` may not be accepted without the person."""
        return bool(self.decision or self.questions or self.candidates or self.published_for
                    or self.record is None)


def _summary(record, source="crossref"):
    """One line of a short list: who, when, where, which DOI."""
    people = record.get("author") if isinstance(record.get("author"), list) else []
    venues = record.get("container-title") if isinstance(record.get("container-title"), list) else []
    titles = [t for t in record.get("title") or [] if isinstance(t, str)] if isinstance(record.get("title"), list) else []
    subtitles = record.get("subtitle") if isinstance(record.get("subtitle"), list) else []
    subtitles = [_text(t) for t in subtitles if isinstance(t, str) and t.strip()]
    title = _text(titles[0]) if titles else ""
    if title and len(subtitles) == 1 and not title.lower().endswith(subtitles[0].lower()):
        title += ": " + subtitles[0]  # Crossref sometimes deposits the subtitle apart
    try:
        years = sorted(cp._record_years(record))
    except (AttributeError, TypeError):
        years = []
    out = {"authors": _people_text([p for p in people if isinstance(p, dict)]), "year": "/".join(years),
           "journal": _text(venues[0]) if venues else "", "doi": record.get("DOI") or None,
           "title": title, "type": record.get("type") or None, "source": source}
    if record.get("PMID"):
        out["pmid"] = str(record["PMID"])
    return out


def _abstract_sign(record, mapped=None):
    """The sign that a record deposited as a journal article may be a conference abstract,
    as (kind, detail), or None (house rule: a conference abstract is never the record).
    The project has no detector for this on a Crossref record (``sfn_abstracts`` works from
    a typed citation), so the signs are the three the owner named: ``venue``, the venue
    names abstracts or a meeting; ``supplement``, the issue or volume is a supplement;
    ``no pages`` / ``one page``, there is neither a page range nor an article number (the
    builder's ``_article_number`` says what an article number is). ``mapped``: the PubMed
    record for the same DOI, whose pages count when Crossref deposits none or only the first.

    A paper in proceedings (``proceedings-article``) is read the same way, except that its
    venue is a meeting by nature: only a venue that names abstracts is the ``venue`` sign.
    A chapter (``book-chapter``) shows the ``venue`` sign alone, when its book names
    abstracts; a chapter's pages are not read as a sign.

    Known gap: an abstract of the Vision Sciences Society meeting printed in Journal of
    Vision (10.1167/15.12.782) has a volume, an issue and a page that is also the end of
    its DOI, exactly as an article of that journal has (10.1167/15.11.1 is one: the two
    Crossref records carry the same fields, down to a reference count of 0). Its Crossref
    record shows no sign, and it is built as an article."""
    venues = record.get("container-title") if isinstance(record.get("container-title"), list) else []
    words = r"\b(?:abstracts?|meetings?)\b" if record.get("type") == "journal-article" else r"\babstracts?\b"
    named = next((_text(v) for v in venues if isinstance(v, str) and re.search(words, v, re.I)), None)
    if named:
        return "venue", named
    if record.get("type") == "book-chapter":
        return None
    for part in ("issue", "volume"):
        value = record.get(part)
        if isinstance(value, str) and re.search(r"suppl", value, re.I):
            return "supplement", f"{part} {_text(value)}"
    page = record.get("page") if isinstance(record.get("page"), str) else ""
    number = record.get("article-number") if isinstance(record.get("article-number"), str) else ""
    second = mapped.get("page") if mapped and isinstance(mapped.get("page"), str) else ""
    verdict = ("no pages", "")
    for pages, from_number in ((_text(page or number), bool(number and not page)), (_text(second), False)):
        if not pages:
            continue
        try:
            stated = expanded_pages(pages)
        except ValueError:
            return None
        first, _, last = stated.partition("-")
        if (last and first != last) or (not last and _article_number(stated, record, from_number)):
            return None
        verdict = ("one page", pages)
    return verdict


def _abstract_signs(record, mapped=None):
    """``_abstract_sign`` in words, or None."""
    sign = _abstract_sign(record, mapped)
    if not sign:
        return None
    kind, detail = sign
    part, _, value = detail.partition(" ")
    return {"venue": f"its venue is \"{detail}\"", "supplement": f"its {part} is a supplement ({value})",
            "no pages": "it has no pages and no article number",
            "one page": f"it has one page ({detail}) and no article number"}[kind]


def _abstract_note(record, mapped=None):
    """For a record that is taken or refused on its own (a DOI that was given, the one
    match of a title search), with PubMed's pages read when there are any."""
    sign = _abstract_signs(record, mapped) if record.get("type") in RECORD_KINDS else None
    return (f"The record {record.get('DOI')} may be a conference abstract: {sign}. A conference abstract is not "
            "cited (house rule), so it is not taken without a decision.") if sign else None


def _crossref_states(record):
    """For a record in a list of several matches, where only its Crossref record has been
    read: what that record states, and no more. Only a venue that names abstracts or a
    meeting is called a possible conference abstract."""
    sign = _abstract_sign(record) if record.get("type") in RECORD_KINDS else None
    if not sign:
        return None
    kind, detail = sign
    if kind == "venue":
        return _abstract_note(record)
    doi = record.get("DOI")
    part, _, value = detail.partition(" ")
    return {"supplement": f"Crossref places the record {doi} in a supplement ({part} {value}).",
            "no pages": f"Crossref gives the record {doi} no pages and no article number.",
            "one page": f"Crossref gives the record {doi} a single page ({detail}) and no page range."}[kind]


def _crossref_record(client, doi):
    """The Crossref record of ``doi`` and the response, or (None, response) when Crossref
    has none. The request is the verifier's (``PoliteClient.crossref_doi`` of the
    normalised DOI), so the built entry is later checked against the same saved response."""
    response = client.crossref_doi(normalize_doi(doi))
    if response["http_status"] != 200 or not response.get("body"):
        return None, response
    return response["body"]["message"], response


def _corroboration(client, record):
    """The PubMed record Europe PMC holds for the record's DOI, mapped for ``build``
    (``auto_review.epmc_record``), the raw record, and why it was not used, if it was not."""
    from .auto_review import epmc_record
    from .extra_sources import route_epmc_doi
    if record.get("type") != "journal-article" or not isinstance(record.get("DOI"), str):
        return None, None, None
    try:
        raws, _ = route_epmc_doi(client, record["DOI"])
    except ValueError:  # a DOI Europe PMC cannot be asked for (quotes or spaces in it)
        return None, None, None
    if not raws:
        return None, None, None
    if len(raws) > 1:
        ids = ", ".join(str(r.get("id")) for r in raws)
        return None, None, f"PubMed has several records for {record['DOI']} ({ids}); none was used"
    try:
        return epmc_record(raws[0], record), raws[0], None
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, raws[0], f"The PubMed record {raws[0].get('id')} was not used: {exc}"


def _published_dois(record):
    """The DOIs a Crossref preprint record names as its published version."""
    relation = record.get("relation") if isinstance(record.get("relation"), dict) else {}
    links = relation.get("is-preprint-of") if isinstance(relation.get("is-preprint-of"), list) else []
    found = []
    for link in links:
        if isinstance(link, dict) and link.get("id-type") == "doi" and _doi_text(str(link.get("id") or "")):
            found.append(_doi_text(str(link["id"])))
    return list(dict.fromkeys(found))


def _notes(*parts):
    return " ".join(p for p in parts if p) or None


def _wanted(query):
    """The typed entry's type when the builder makes it (None for a bare query or any other
    type), and the Crossref record types that can be the record: the one the verifier
    accepts for that type, or every built type when no type was typed."""
    kind = str((query.fields or {}).get("ENTRYTYPE") or "").lower()
    return (kind, {KINDS[kind].record}) if kind in KINDS else (None, set(RECORD_KINDS))


def _not_built(named, kind):
    """Why a record of type ``named`` is not the record of an entry of type ``kind``."""
    return f"is not built as an entry of type {kind}" if kind and named in RECORD_KINDS else "is not built automatically"


def _from_doi(client, doi, follow=True, wanted=frozenset({"journal-article"})):
    """The record of a DOI. It is that DOI's Crossref record and nothing else: nothing is
    searched for, and a DOI Crossref does not have gives no record. A preprint record that
    names one published work of a type in ``wanted`` is answered with that work, offered
    first."""
    try:
        record, response = _crossref_record(client, doi)
    except ValueError as exc:
        return Identified(note=f"doi: {exc}; the entry is left as typed")
    if record is None:
        return Identified(note=f"The DOI {doi} was not found in Crossref (HTTP {response['http_status']}); "
                               "nothing was searched for in its place and the entry is left as typed")
    alias = None
    if response.get("doi_alias"):
        alias = f"Crossref answers the DOI {doi} with the record of {record.get('DOI')}."
    if follow and record.get("type") == "posted-content":
        linked = _published_dois(record)
        if len(linked) == 1:
            published = _from_doi(client, linked[0], follow=False)
            if published.record is not None and published.record.get("type") in wanted:
                published.candidates = [_summary(published.record), _summary(record)]
                published.published_for = doi
                published.note = _notes(
                    alias, f"The DOI {doi} is a preprint; its record names {published.record.get('DOI')} as the "
                    "published version, which is proposed here (house rule: cite the published version).",
                    published.note)
                return published
    # A correction or retraction notice is refused by the builder: PubMed is not asked about it.
    mapped, _, unused = (None, None, None) if _is_notice(record) else _corroboration(client, record)
    # The DOI was given, so its record is the record; what looks like an abstract is said.
    return Identified(record=record, corroborating=mapped, source="crossref+pubmed" if mapped else "crossref",
                      note=_notes(alias, unused), decision=_abstract_note(record, mapped))


class _PubmedClient:
    """The caller's client as ``extra_sources`` wants it: that module reads the contact
    address from ``client.contact`` (its own ``make_client`` sets it), and a plain
    ``PoliteClient`` has it as ``mailto``. Everything else is the caller's client, which
    is not changed."""

    def __init__(self, client):
        self._client = client
        self.contact = client.mailto

    def __getattr__(self, name):
        return getattr(self._client, name)


def _pubmed_client(client):
    return client if getattr(client, "contact", None) else _PubmedClient(client)


_KNOWN_JOURNALS = {}


def _known_journal(name, bib=None):
    """Whether ``name`` is, under ``verification.normalize_journal``, a journal name the
    house journal list has (``helpers.journal_key``, the list ``format_journal_name``
    works from) or an entry of the library already uses (``correction_proposals.
    library_bib()``; read once per file and modification time)."""
    from . import helpers
    from .errors import CdlbibError

    def norm(value):
        try:
            return normalize_journal(value)
        except ValueError:
            return None

    names = set()
    for short, full in helpers.journal_key.items():
        names.update(v for v in (short, full) if isinstance(v, str))
    try:
        path = bib if bib is not None else cp.library_bib()
        stamp = (str(path), path.stat().st_mtime_ns)
        if stamp not in _KNOWN_JOURNALS:
            from .verification import load_entries
            _KNOWN_JOURNALS.clear()
            _KNOWN_JOURNALS[stamp] = {norm(entry['fields'].get('journal', ''))
                                      for entry in load_entries(path).values()}
        used = _KNOWN_JOURNALS[stamp]
    except (CdlbibError, OSError, UnicodeError, ValueError):  # no library at hand: the house list alone
        used = set()
    wanted = norm(name)
    return bool(wanted) and (wanted in used or wanted in {norm(v) for v in names})


def _same_work(pubmed, record):
    """What differs between a PubMed record (``medline_record`` shape) and the Crossref
    record its DOI leads to, or None: the title must be the same by the verifier's
    comparison or within the identity rule's small difference
    (``correction_proposals.title_small_difference``), and the first author's surname the
    same after ``verification.normalized`` (the test ``_different_work`` makes of a typed
    entry)."""
    from .auto_review import safe_compare
    title = (pubmed.get("title") or [""])[0]
    evidence, _ = safe_compare({"ENTRYTYPE": "article", "title": title}, record)
    titles = evidence.get("title", {}).get("source") or []
    same_title = bool(evidence.get("title", {}).get("match")) or any(
        cp.title_small_difference(title, t) for t in titles)
    one, two = _record_first_surname(pubmed), _record_first_surname(record)
    differs = ([] if same_title else ["title"]) + ([] if one and one == two else ["first author"])
    return " and ".join(differs) or None


def _by_pmid(client, pmid, bib=None):
    from .extra_sources import efetch, medline_is_notice, medline_record
    records, _ = efetch(_pubmed_client(client), [pmid])
    raw = records.get(str(pmid))
    if raw is None:
        return Identified(note=f"PubMed has no journal article under PMID {pmid}; the entry is left as typed")
    listed = dict(_summary(medline_record(raw), "pubmed"), pmid=str(pmid))
    if medline_is_notice(raw):
        kinds = ", ".join(raw.get("publication_types") or [])
        return Identified(candidates=[listed], note=f"PMID {pmid} is not an article ({kinds}); nothing was built from it")
    if len(raw["dois"]) > 1:
        return Identified(candidates=[listed], note=f"The PubMed record {pmid} has several DOIs ("
                          + ", ".join(raw["dois"]) + "); nothing was built from it")
    if not raw["dois"]:
        # PubMed gives no DOI: the entry is built from the PubMed record alone, in the
        # Crossref shape the verifier already reads it in, under PubMed's own journal title.
        record = medline_record(raw)
        catalogue = _text(raw.get("journal_title") or "")
        name = re.sub(r"\s*\([^()]*\)\s*$", "", catalogue)  # NLM's place and date qualifier
        record["container-title"] = [name] if name else []
        questions = {}
        if name and not _known_journal(name, bib):
            questions["journal"] = (f"journal: the name is the title in PubMed's catalogue (\"{catalogue}\"), which "
                                    "is not a journal name the library or the house journal list has; it may not "
                                    "be the name the journal prints")
        return Identified(record=record, source="pubmed", questions=questions,
                          note=f"Built from the PubMed record {pmid} alone: PubMed gives no DOI for it, and no "
                               "second source was compared.")
    found = _from_doi(client, raw["dois"][0])
    if found.record is None:
        found.candidates = [listed]
    elif not found.published_for:
        differs = _same_work(medline_record(raw), found.record)
        if differs:  # PubMed's DOI leads to another work: neither is taken
            return Identified(candidates=[listed, _summary(found.record)],
                              note=f"PubMed gives PMID {pmid} the DOI {raw['dois'][0]}, but the Crossref record of "
                                   f"that DOI differs from the PubMed record in its {differs}; nothing was built")
    found.note = _notes(f"PMID {pmid} has the DOI {raw['dois'][0]}.", found.note)
    return found


def _first_surname(author):
    """The first author's surname as the comparator reads it, or None."""
    from .name_parsing import splitname
    try:
        name = split_authors(author or "")[0]
        if not name.strip():
            return None
        if name.startswith("{"):
            return normalized(name) or None
        parts = splitname(name, strict_mode=True)
        return normalized(" ".join(parts["von"] + parts["last"])) or None
    except (ValueError, IndexError):
        return None


def _record_first_surname(record):
    people = record.get("author") if isinstance(record.get("author"), list) else []
    if not people or not isinstance(people[0], dict):
        return None
    try:
        return normalized(str(people[0].get("family") or people[0].get("name") or "")) or None
    except ValueError:
        return None


def _is_notice(record):
    try:
        _refuse_notice(record)
    except (CompletionRefused, AttributeError, TypeError):
        return True
    return False


def _judged(fields, record, source, want_surname, want_year, kind=None, wanted=frozenset({"journal-article"})):
    """How a found record stands against the typed title, first author and year.

    ``strict``: the record is of a type in ``wanted`` (a journal article, unless the typed
    entry or the bare query says otherwise) and shows no sign of being a conference
    abstract (``_abstract_signs``), the title is the same after ``verification.normalize_title`` (the
    verifier's comparison: case, accents, LaTeX, punctuation and spacing do not count), the
    first author's surname is the same after ``verification.normalized``, and, when a year
    was given, it is one of the record's publication years. ``plausible``: the same
    surname (when an author was given) and a title that is the same or within the identity
    rule's small difference (``correction_proposals.title_small_difference``: two word
    edits, or the record's title without its subtitle); the year is not asked for. With
    no author given nothing is strict, and only the same title is plausible.
    """
    from .auto_review import safe_compare
    evidence, _ = safe_compare(fields, record)
    titles = evidence.get("title", {}).get("source") or []
    same_title = bool(evidence.get("title", {}).get("match"))
    near_title = same_title or any(cp.title_small_difference(fields.get("title", ""), t) for t in titles)
    surname = _record_first_surname(record)
    same_surname = bool(want_surname and surname and surname == want_surname)
    try:
        years = cp._record_years(record)  # print, online and issued years, as the verifier reads them
    except (AttributeError, TypeError):
        years = set()
    same_year = not want_year or str(want_year).strip() in years
    usable = not _is_notice(record)
    matches = usable and same_title and same_surname and same_year
    # Only a record of a wanted type that does not look like a conference abstract is taken; any
    # other match is a candidate, with the reason.
    demoted = None
    if matches and record.get("type") not in wanted:
        demoted = (f"The record {record.get('DOI') or record.get('PMID')} is of type {record.get('type')}, "
                   + ("not a journal article." if wanted == {"journal-article"}
                      else f"which {_not_built(record.get('type'), kind)}."))
    elif matches:
        demoted = _abstract_note(record)
    return {"record": record, "source": source, "doi": record.get("DOI"), "demoted": demoted,
            "states": _crossref_states(record) if matches and record.get("type") in wanted else demoted,
            "match": matches, "strict": matches and not demoted,
            "plausible": usable and ((same_surname and near_title) if want_surname else same_title)}


def _distinct_works(picked):
    """The matches that are different works. A preprint whose record names one of the
    other matches as its published version is that work's preprint, not a second work
    (house rule: cite the published one); two APA DOI forms of one article are one choice
    (``verification.collapse_apa_twins``)."""
    from .verification import collapse_apa_twins
    dois = set()
    for item in picked:
        try:
            dois.add(normalize_doi(item["doi"]))
        except (ValueError, AttributeError):
            continue
    picked = [item for item in picked
              if not (item["record"].get("type") == "posted-content"
                      and any(normalize_doi(d) in dois for d in _published_dois(item["record"])))]
    if len(picked) == 2 and all(item["doi"] for item in picked):
        kept = collapse_apa_twins({item["doi"]: {"doi": item["doi"], "record": item["record"], "issues": [],
                                                 "item": item} for item in picked})
        picked = [candidate["item"] for candidate in kept.values()]
    return picked


def _mentioned(title, records):
    """Does the title of any of ``records`` contain ``title`` (compared as the verifier
    compares titles) without being it?"""
    from .verification import normalize_title
    try:
        wanted = normalize_title(title)
    except ValueError:
        return False
    for record in records:
        for text in record.get("title") or []:
            try:
                found = normalize_title(text)
            except (ValueError, TypeError):
                continue
            if wanted and wanted in found and wanted != found:
                return True
    return False


def _by_title(client, query):
    """Crossref's bibliographic search (``PoliteClient.crossref_search``) and PubMed
    (``extra_sources.route_pubmed``), judged by ``_judged``."""
    from .extra_sources import crossref_candidate, medline_is_notice, medline_record, route_pubmed
    fields = {k: v for k, v in (query.fields or {}).items() if isinstance(v, str)}
    fields.update({k: v for k, v in (("title", query.title), ("author", query.author), ("year", query.year)) if v})
    kind, wanted = _wanted(query)
    fields = dict(fields, ENTRYTYPE=kind or "article")
    fields.pop("doi", None)
    want_surname, want_year = _first_surname(fields.get("author")), fields.get("year")
    response = client.crossref_search(fields)
    items = (response.get("body") or {}).get("message", {}).get("items", [])
    pool = [_judged(fields, record, "crossref", want_surname, want_year, kind, wanted) for record in items]
    known = set()
    for item in pool:
        try:
            known.add(normalize_doi(item["doi"]))
        except (ValueError, AttributeError):
            continue
    # PubMed holds journal articles: it is not asked about a typed paper in proceedings or chapter.
    pubmed = route_pubmed(_pubmed_client(client), fields) if "journal-article" in wanted else {"records": {}}
    for pmid, raw in pubmed["records"].items():
        if medline_is_notice(raw):
            continue
        mapped = medline_record(raw, fields.get("journal"))
        judged = _judged(fields, mapped, "pubmed", want_surname, want_year, kind, wanted)
        if not judged["plausible"] and not judged["strict"]:
            continue
        if mapped.get("DOI"):
            if normalize_doi(mapped["DOI"]) in known:
                continue  # the same work Crossref's search already gave
            candidate = crossref_candidate(client, mapped["DOI"])
            if candidate:  # found through PubMed; the record is still Crossref's
                known.add(normalize_doi(mapped["DOI"]))
                pool.append(_judged(fields, candidate["record"], "crossref", want_surname, want_year, kind, wanted))
                continue
        pool.append(judged)

    asked = ["the title"] + (["the first author"] if want_surname else []) + (["the year"] if want_year else [])
    asked = asked[0] if len(asked) == 1 else ", ".join(asked[:-1]) + " and " + asked[-1]
    # Every match counts when asking whether there is exactly one, also a match that is not
    # taken (another type, or the signs of a conference abstract).
    matched = _distinct_works([item for item in pool if item["match"]])
    if len(matched) == 1:
        item, listed = matched[0], [_summary(matched[0]["record"], matched[0]["source"])]
        if item["source"] != "crossref":
            return Identified(candidates=listed, note=f"The one record that matches {asked} is in PubMed only, "
                                                      "without a DOI; an entry is built from a Crossref record")
        if item["demoted"] and item["record"].get("type") not in wanted:
            return Identified(candidates=listed, note=_notes(f"One record matches {asked}.", item["demoted"]))
        found = _from_doi(client, item["doi"], wanted=wanted)
        if found.record is None or found.decision:
            # Still with the signs of an abstract once PubMed's pages are known: a candidate.
            return Identified(candidates=listed, note=_notes(f"One record matches {asked}.", found.decision or found.note))
        found.note = _notes(f"One record matches {asked}: {item['doi']}.", found.note)
        return found
    if matched:
        listed = [_summary(item["record"], item["source"]) for item in matched[:SHORT_LIST]]
        # Several matches: no further lookup is made per candidate, so the note says what
        # each Crossref record states, not what the work may be.
        demoted = [item["states"] for item in matched[:SHORT_LIST] if item["states"]]
        return Identified(candidates=listed,
                          note=_notes(f"{len(matched)} records match {asked}; one has to be chosen" + ("." if demoted else ""),
                                      *demoted))
    plausible = _distinct_works([item for item in pool if item["plausible"]])
    if plausible:
        listed = [_summary(item["record"], item["source"]) for item in plausible[:SHORT_LIST]]
        return Identified(candidates=listed,
                          note=f"No record matches {asked} exactly; {len(plausible)} similar "
                               f"record{'s' if len(plausible) != 1 else ''} found, and none is taken without a choice")
    if not want_surname and fields.get("title") and _mentioned(fields["title"], items):
        # A title alone is never taken as the work (nothing is strict without the first author),
        # and the search above ranked records ABOUT a paper of this title (recommendations,
        # commentaries: their titles contain it) before the paper itself. So the title is asked
        # for as a title, among the records of the wanted type, and what carries exactly this
        # title is offered for a choice.
        kinds = sorted(wanted) if wanted else ["journal-article"]
        again = client.get("https://api.crossref.org/works",
                           {"query.title": fields["title"][:1500], "filter": ",".join("type:" + k for k in kinds), "rows": 5})
        titled = _distinct_works([item for item in (
            _judged(fields, record, "crossref", want_surname, want_year, kind, wanted)
            for record in (again.get("body") or {}).get("message", {}).get("items", [])) if item["plausible"]])
        if titled:
            listed = [_summary(item["record"], item["source"]) for item in titled[:SHORT_LIST]]
            return Identified(candidates=listed, note=(
                f"{len(titled)} record{'s have' if len(titled) != 1 else ' has'} this title. A title alone is not "
                "taken as the work: choose the record, or give the first author as well"))
        return Identified(note=f"No record in Crossref or PubMed has exactly {asked}. A title alone often does not "
                               "find the work: give the first author as well, or its DOI; the entry is left as typed")
    return Identified(note=f"No record in Crossref or PubMed matches {asked}; the entry is left as typed")


def _arxiv_documents(cache, client, requested, only_api=False):
    """The saved arXiv documents for an identifier, fetched as the arXiv check fetches
    them (``arxiv_review.collect``; the same cache entries)."""
    from . import arxiv_review as ar
    from .preprint_review import fetch_document
    base, _ = ar.parse_id(requested)
    if only_api:
        url = ar.api_url(base)
        return fetch_document(cache, client, url, "arxiv-source-v1:" + url, validate=lambda s: ar.atom(s, base))
    return ar.collect(cache, client, {"ENTRYTYPE": "article", "journal": ARXIV_JOURNAL, "volume": requested})


def _by_arxiv(client, cache, requested, kind=None, wanted=frozenset({"journal-article"})):
    from . import arxiv_review as ar
    base, _ = ar.parse_id(requested)
    own = ar.doi_for(base)

    def published(doi, said_by):
        """The published version a source names: the identification when Crossref has it as
        a record of a type in ``wanted``; otherwise why not, and the record Crossref does
        have, if any."""
        doi = _doi_text(doi or "")
        if not doi or normalize_doi(doi) == own:
            return None, None, []
        found = _from_doi(client, doi, follow=False)
        if found.record is None:
            return None, (f"{said_by} names {doi} as the published version of arXiv:{requested}, but Crossref "
                          "has no record of that DOI; the preprint is proposed."), []
        if found.record.get("type") not in wanted:
            return None, (f"{said_by} names {doi} as the published version of arXiv:{requested}; Crossref has "
                          f"it as a record of type {found.record.get('type')}, which "
                          f"{_not_built(found.record.get('type'), kind)}. "
                          "The preprint is proposed (house rule: cite the published version)."), [
                              _summary(found.record)]
        return found, None, []

    def offered(found, said_by, latest):
        preprint = {"authors": "; ".join(latest["authors"]), "year": str(latest["published"].year),
                    "journal": "arXiv", "doi": own, "title": _text(latest["title"]), "type": "preprint",
                    "source": "arxiv"}
        found.candidates = [_summary(found.record), preprint]
        found.published_for = "arXiv:" + requested
        found.note = _notes(f"arXiv:{requested} is a preprint; {said_by} names {found.record.get('DOI')} as the "
                            "published version, which is proposed here (house rule: cite the published version).",
                            found.note)
        return found

    try:
        latest = ar.atom(_arxiv_documents(cache, client, requested, only_api=True), base)
        found, missing, others = published(latest["doi"], "Its arXiv record")
        if found:
            return offered(found, "its arXiv record", latest)
        raw = _arxiv_documents(cache, client, requested)
        attrs = ar.registry(raw["datacite"], base)
        related = [r.get("relatedIdentifier") for r in attrs.get("relatedIdentifiers") or []
                   if isinstance(r, dict) and r.get("relatedIdentifierType") == "DOI"
                   and r.get("relationType") in _PUBLISHED_RELATIONS]
        for doi in dict.fromkeys(d for d in related if isinstance(d, str)):
            found, other, listed = published(doi, "Its DataCite record")
            if found:
                return offered(found, "its DataCite record", latest)
            missing, others = missing or other, others or listed
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return Identified(note=f"arXiv:{requested} could not be read from arXiv and DataCite ({exc}); "
                               "the entry is left as typed")
    return Identified(record=raw, source="arxiv", note=missing, candidates=others)


def identify(query, client, cache=None, ws=None):
    """Find the work ``query`` names. Lookups go through ``client``; the arXiv documents
    are kept in ``cache`` (``client.cache`` when none is given), as the arXiv check keeps
    them. A source that does not answer raises ``verification.ProviderError``.

    - A DOI: that DOI's Crossref record, never a search result. Not in Crossref: no record.
    - A PMID: the PubMed record's DOI, then as a DOI.
    - An arXiv id: the arXiv and DataCite records of the preprint.
    - A title: exactly one record matching the title, the first author's surname and the
      year (when given) is the record; several are returned as ``candidates``; ``_judged``
      says what matching means.
    A preprint that names its published version is answered with the published record
    (``published_for`` names the preprint, ``candidates`` lists both, published first).
    """
    kind, wanted = _wanted(query)
    if query.doi:
        return _from_doi(client, query.doi, wanted=wanted)
    if query.pmid:
        return _by_pmid(client, query.pmid, ws.bib if ws is not None else None)
    if query.arxiv:
        return _by_arxiv(client, cache if cache is not None else client.cache, query.arxiv, kind, wanted)
    if query.title:
        return _by_title(client, query)
    return Identified(note="Nothing to look up: give a DOI, a PMID, an arXiv id, or a title")


# --- the arXiv house form -----------------------------------------------------------------------

_ARXIV_BUILT = ("author", "doi", "journal", "title", "volume", "year")


def _renamed(text):
    """The builder's source names for an arXiv record (arXiv first, DataCite second)."""
    return text.replace("crossref", "arxiv").replace("pubmed", "datacite")


def _same_arxiv(value, base, version):
    from .arxiv_review import parse_id
    try:
        other, other_version = parse_id(value)
    except ValueError:
        return False
    return other == base and other_version in (None, version) if version else other == base and other_version is None


def build_arxiv(typed_fields, raw):
    """Propose an arXiv preprint in the house form, from the documents
    ``arxiv_review.collect`` saves (the arXiv record, its page and its DataCite record)::

        @article{PianHill22,
        	Author = {S T Piantadosi and F Hill},
        	Doi = {10.48550/arxiv.2208.02957},
        	Journal = {{arXiv}},
        	Title = {Meaning without reference in large language models},
        	Volume = {2208.02957},
        	Year = {2022}}

    The identifier is in ``Volume`` and the DOI is the one DataCite registers, the form
    most arXiv entries of the library have. The year is DataCite's publication year (the
    first submission), or the year of the version when the identifier names one: the
    years the arXiv check (``arxiv_review.assess_arxiv``) accepts. Each value is decided
    as ``build`` decides it; the sources are named ``arxiv`` and ``datacite``.
    """
    from . import arxiv_review as ar
    from .auto_review import safe_compare
    from .helpers import authors2key, split_names
    from .preprint_review import people as byline_people
    typed = {(k if k in ("ENTRYTYPE", "ID") else k.lower()): v for k, v in typed_fields.items()
             if v is not None and str(v) != ""}
    kind = str(typed.get("ENTRYTYPE") or "article").lower()
    base = raw["base"]
    proposal = Proposal(key_typed=typed.get("ID") or None, entry_type=kind, record_source="arxiv+datacite")
    if kind != "article":
        proposal.unsupported = kind
        proposal.issues.append(f"An entry of type {kind} is not built automatically; the entry is left as typed")
        return proposal
    try:
        latest = ar.atom(raw["latest_api"], base)
        attrs = ar.registry(raw["datacite"], base)
        version, selected = None, latest
        if "selected_api" in raw:
            version = ar.parse_id(raw["selected_api"]["url"].split("id_list=", 1)[1])[1]
            selected = ar.atom(raw["selected_api"], f"{base}v{version}")
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        raise CompletionRefused(f"The arXiv and DataCite documents of arXiv:{base} cannot be read ({exc})") from exc
    identifier = base + (f"v{version}" if version else "")
    own = attrs["doi"]
    proposal.doi = typed.get("doi") or own

    if typed.get("doi") and not _same_arxiv(str(typed["doi"]), base, None):
        proposal.issues.append(f"doi: the arXiv record's DOI {own} is not the typed DOI {typed['doi']}; "
                               "nothing was filled from it")
        return _as_typed(proposal, typed, kind, {"doi": (typed["doi"], "typed")})
    if ar.notice_dois({"source": ar.SOURCE, "doi": ar.doi_for(base), "raw_record": raw}):
        proposal.issues.append(f"arXiv:{base} carries a withdrawal, retraction or correction notice; it is not "
                               "added without a decision")
        proposal.needs_decision = True

    def people_of(names):
        try:
            return byline_people(names)
        except ValueError as exc:
            raise _Hold("author: " + str(exc), {"arxiv": "; ".join(names)})

    registered = [{"given": c.get("givenName"), "family": c.get("familyName")} for c in attrs.get("creators") or []
                  if isinstance(c, dict)]
    registered = registered if registered and all(_is_text(p["given"]) and p["given"] and _is_text(p["family"])
                                                  and p["family"] for p in registered) else []
    titles = [t.get("title") for t in attrs.get("titles") or [] if isinstance(t, dict) and isinstance(t.get("title"), str)]
    year = str(selected["updated"].year) if version else str(attrs.get("publicationYear") or "")
    # DataCite describes the current version: it corroborates only when that is the one cited.
    second = {"author": registered, "title": titles[:1] if len(titles) == 1 else []} if not version else {}
    record = {"type": "posted-content", "DOI": own, "title": [_text(selected["title"])],
              "container-title": ["arXiv"], "volume": identifier,
              "published": {"date-parts": [[int(year)]]} if year.isdigit() else {}}

    def author():
        record["author"] = people_of(selected["authors"])
        return _author(record, second or None, typed.get("author"))

    keep = set(_field_order())
    house = {k: v for k, v in typed.items() if k in keep and k != "publisher"}
    try:
        record["author"] = byline_people(selected["authors"])
    except ValueError:
        record["author"] = []
    evidence, compare_issues = safe_compare(dict(house, ENTRYTYPE="article"), record)
    unsupported = next((i for i in compare_issues if i.startswith("Unsupported source metadata")), None)

    def year_value():
        values = {"arxiv": str(selected["updated" if version else "published"].year)}
        if version:
            return _Value(year, "arxiv", values)
        values["datacite"] = year
        if not re.fullmatch(r"[1-9]\d{3}", year) or values["arxiv"] != year:
            raise _Hold("year: sources disagree", values, disagreement=True)
        return _Value(year, "arxiv+datacite", values)

    makers = {
        "author": author,
        "doi": lambda: _Value(own, "datacite", {"datacite": own}),
        "journal": lambda: _Value(ARXIV_JOURNAL, "house rule", {}),
        "title": lambda: _title(record, second or None, typed.get("title"), evidence, unsupported),
        "volume": lambda: _Value(identifier, "arxiv", {"arxiv": identifier}),
        "year": year_value,
    }
    fields = {}

    def keep_typed(name, had):
        formed = _house_form(name, had)
        fields[name] = formed
        asked = _house_question(name, had) if formed == had else None
        if asked:
            proposal.changes.append(FieldChange(name, had, had, "typed", "question"))
            proposal.issues.append(asked)
            proposal.needs_decision = True
        elif formed == had:
            proposal.changes.append(FieldChange(name, had, had, "typed", "kept"))
        else:
            proposal.changes.append(FieldChange(name, had, formed, "house format", "changed"))

    def question(name, had, value, source, reasons):
        fields[name] = had if had else value
        proposal.changes.append(FieldChange(name, had, value, source, "question"))
        proposal.issues.extend([reasons] if isinstance(reasons, str) else reasons)
        proposal.needs_decision = True

    for name in _ARXIV_BUILT:
        had = typed.get(name)
        try:
            outcome = makers[name]()
        except _Hold as hold:
            held = Unfilled(name, hold.reason, {_renamed(k): v for k, v in hold.values.items()})
            if had:
                keep_typed(name, had)
                if hold.disagreement or not evidence.get(name, {}).get("match"):
                    proposal.unfilled.append(held)
            else:
                proposal.unfilled.append(held)
            continue
        if outcome is None:
            if had:
                keep_typed(name, had)
            proposal.unfilled.append(Unfilled(name, f"{name}: no source record states it", {}))
            continue
        value, source = outcome.value, _renamed(outcome.source)
        values = {_renamed(k): v for k, v in outcome.values.items()}
        if not had:
            if outcome.doubts:
                question(name, None, value, source, outcome.doubts)
            else:
                fields[name] = value
                proposal.changes.append(FieldChange(name, None, value, source, "filled"))
            continue
        same = value == had or (name != "year" and evidence.get(name, {}).get("match"))
        if name in ("volume", "doi"):
            same = same or _same_arxiv(had, base, version)  # the same identifier, written another way
        if same:
            keep_typed(name, had)
            continue
        reason = None
        if name == "author":
            hold = cp.surname_change_hold(proposal.key_typed, had, value, source=source)
            if hold:
                question(name, had, value, source, hold)
                continue
            if cp.byline_loses_detail(had, record.get("author") or []):
                reason = "author: citation byline has detail the source lacks"
        if reason is None and cp.loses_characters(had, value, name):
            reason = f"{name}: source value drops accents or has a replacement character"
        if reason:
            keep_typed(name, had)
            proposal.unfilled.append(Unfilled(name, reason, values))
        elif outcome.doubts:
            question(name, had, value, source, outcome.doubts)
        else:
            fields[name] = value
            proposal.changes.append(FieldChange(name, had, value, source, "changed"))

    dropped = []
    for name in sorted(k for k in typed if k not in ("ENTRYTYPE", "ID") and k not in _ARXIV_BUILT):
        if name == "publisher":
            dropped.append(FieldChange(name, typed[name], None, "house rule: no publisher on an article", "dropped"))
        elif name in keep:
            keep_typed(name, typed[name])
        else:
            dropped.append(FieldChange(name, typed[name], None, "not a house field", "dropped"))
    order = _field_order()
    proposal.changes.sort(key=lambda c: order.index(c.field))
    proposal.changes += dropped

    if fields.get("year") and any(name.strip() for name in split_names(fields.get("author") or "")):
        proposal.key_proposed = authors2key(fields["author"], fields["year"])
    if not proposal.key_typed and not proposal.key_proposed:
        proposal.unfilled.append(Unfilled("ID", "a key needs the authors and the year", {}))
    proposal.doi = fields.get("doi") or proposal.doi
    proposal.proposed_raw = render(kind, proposal.key_typed or proposal.key_proposed or NO_KEY, fields)
    _set_complete(proposal, fields)
    return proposal


def _written_fields(proposal):
    """The fields of ``proposal.proposed_raw``, read back from its changes by ``build``'s
    rule (a question keeps the typed value when there is one); None when rendering them
    does not give the text again."""
    fields = {}
    for change in proposal.changes:
        if change.kind != "dropped":
            fields[change.field] = change.typed if change.kind == "question" and change.typed else change.proposed
    fields = {name: value for name, value in fields.items() if value is not None}
    key = proposal.key_typed or proposal.key_proposed or NO_KEY
    return fields if render(proposal.entry_type, key, fields) == proposal.proposed_raw else None


def _renamed_pubmed(proposal):
    """``build`` names its first record ``crossref``; here that record is PubMed's."""
    def named(text):
        return text.replace("crossref", "pubmed").replace("Crossref", "PubMed")
    proposal.record_source = "pubmed"
    proposal.changes = [FieldChange(c.field, c.typed, c.proposed, named(c.source), c.kind) for c in proposal.changes]
    proposal.unfilled = [Unfilled(u.field, named(u.reason), {named(k): v for k, v in u.source_values.items()})
                         for u in proposal.unfilled]
    proposal.issues = [named(i) for i in proposal.issues]
    return proposal


# --- building and checking ----------------------------------------------------------------------

def checked(proposal, client, arxiv_raw=None):
    """Run ``proposal.proposed_raw`` through the format check and the verifier, and record
    what they say on the proposal: ``status`` is the verifier's and nothing else's;
    ``issues`` gains its findings, those of the closest source record, and the format
    checker's. ``arxiv_raw``: the arXiv documents, for an arXiv preprint (the arXiv check
    judges it, as in the gate).

    The verifier takes an entry as ``verification.load_entries`` gives it (``key``,
    ``raw``, ``fields``, ``fingerprint``) and the project has no parser for one entry's
    text, so the text is written to a file of its own in a temporary folder and read back
    with ``load_entries``; the format check reads the same file.

    A check that cannot run is said so in ``issues`` and the proposal then needs a
    decision: the format checker raising (``helpers.check_bib`` raises on entries it
    cannot judge, an entry without a title among them), the text not reading back, or a
    source not answering the verifier (``status`` is then ``provider_error``). An entry
    the verifier does not accept needs a decision too.
    """
    import contextlib
    import io
    from pathlib import Path
    import tempfile
    from .auto_review import fetch_epmc, reassess, target_dois
    from .helpers import check_bib
    from .verification import ACCEPTED, ProviderError, load_entries, verify_entry
    from .verification_cli import closest_candidate

    def add(issue):
        if issue not in proposal.issues:
            proposal.issues.append(issue)

    with tempfile.TemporaryDirectory(prefix="cdlbib-proposal-") as folder:
        path = Path(folder) / "proposed.bib"
        path.write_text(proposal.proposed_raw + "\n", encoding="utf-8")
        try:
            entries = load_entries(path)
            entry = next(iter(entries.values()))
        except ValueError as exc:
            add(f"The proposed entry could not be read back ({exc}); neither check was run")
            proposal.needs_decision = True
            return proposal
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                errors, _ = check_bib(str(path), verbose=False)
        except Exception as exc:  # noqa: BLE001 - check_bib raises plain exceptions on entries it cannot judge
            add(f"The format check could not run on the proposed entry ({type(exc).__name__}: {exc})")
            proposal.needs_decision = True
        else:
            keyless = entry["key"] == NO_KEY and not proposal.key_typed and not proposal.key_proposed
            if keyless:
                # The text carries the placeholder because an entry cannot be written without a
                # key token. The checker's advice for it (a key made of the year alone, since
                # there are no names) is not a finding about this entry: there is no key yet.
                add(NO_KEY_YET)
                proposal.needs_decision = True
            for key in sorted(errors):
                for name in sorted(errors[key]):
                    if keyless and name == "ID":
                        continue
                    add(f"format: the format checker would write {'the key' if name == 'ID' else name} "
                        f"as {errors[key][name]}")
                    proposal.needs_decision = True
    try:
        if arxiv_raw is not None:
            from .arxiv_review import assess_arxiv
            result = assess_arxiv(entry["fields"], arxiv_raw)
        else:
            result = verify_entry(entry, client)
            if result["status"] not in ACCEPTED:
                # As the gate does (auto_review.run_auto_review): the PubMed record of each DOI
                # the entry may be is looked up and noted in ``attempts`` (the print-year rule
                # asks that it was looked for), then the saved evidence is judged again.
                candidates, attempts = list(result["candidates"]), list(result["attempts"])
                for doi in target_dois(result):
                    try:
                        indexed, response = fetch_epmc(client, [doi])
                    except ValueError:  # a DOI Europe PMC cannot be asked for
                        continue
                    attempts.append({"source": "europepmc", "doi": doi, "url": response["url"],
                                     "matches": len(indexed[doi]), "retrieved_at": response["retrieved_at"]})
                    primary = next((c for c in result["candidates"] if c.get("source") == "crossref"
                                    and _doi_text(str(c.get("doi") or "")) and normalize_doi(c["doi"]) == doi), None)
                    if primary:
                        candidates += [{"source": "europepmc", "doi": primary["doi"], "raw_record": raw,
                                        "retrieved_at": response["retrieved_at"], "request_url": response["url"]}
                                       for raw in indexed[doi]]
                result = reassess(entry, dict(result, candidates=candidates, attempts=attempts))
                # As the gate does next for a book (catalogue_review.run_catalogue_review).
                from .book_build import catalogue_check
                result = catalogue_check(entry, result, client)
    except ProviderError as exc:
        proposal.status = LOOKUP_FAILED
        add(f"The proposed entry could not be verified: a source did not answer ({exc})")
        proposal.needs_decision = True
        proposal.notes.append(FIRST_CHECK)
        return proposal
    proposal.status = result["status"]
    for issue in result.get("issues") or []:
        add(issue)
    if proposal.status not in ACCEPTED:
        if not result.get("issues"):
            add("The verifier did not accept the proposed entry; it needs a human check")
        closest = closest_candidate(entry["fields"], result)  # what the gate prints under UNRESOLVED
        for issue in (closest or {}).get("issues") or []:
            if issue not in proposal.issues:
                add(f"{closest.get('source')} {closest.get('doi') or ''}: {issue}".replace("  ", " "))
        proposal.needs_decision = True
        proposal.notes.append(FIRST_CHECK)
    return proposal


def _propose(query, client, cache, ws=None, announce=None, allow_model=None):
    """Find the work, build the entry, and have it checked. Returns a ``Proposal`` always:

    - no record (an unresolved DOI, nothing found, several candidates): the entry is left
      as typed (``proposed_raw`` is None), ``issues`` says why, ``candidates`` lists the
      choices;
    - a source did not answer: ``status`` is ``provider_error`` and ``issues`` gives the
      reason, so one failed lookup does not lose the other queries of a batch;
    - otherwise the built entry, with the verifier's ``status`` and ``issues`` for it.
    Nothing here records an approval: ``status`` is only ever what the verifier returned.

    A DOI that was given is never dropped or replaced: when the published version of a
    typed preprint is offered, the proposed text keeps the typed DOI and the offered one
    is a ``question``. A PMID whose PubMed record has no DOI is built from that record
    alone (``record_source`` "pubmed"). A status that is not an accepted one comes with
    the ``FIRST_CHECK`` note.

    A book (a query with an ISBN, an LCCN, or ``book``) is built from its Library of Congress
    record (``book_build``). A chapter whose record names two container titles has the book's
    title looked for (``container_titles.resolve``): ``announce`` is told before a model is
    asked, and ``allow_model`` is the person's answer when they asked to be asked first.
    """
    from .verification import ProviderError
    typed = dict(query.fields) if query.fields else ({"doi": query.doi} if query.doi else {})
    kind = str(typed.get("ENTRYTYPE") or "article").lower()
    if (query.isbn or query.lccn or query.book) and not query.fields:
        # A book: built from its Library of Congress record and checked like any entry.
        from .book_build import propose_book
        proposal = propose_book(query, client, cache if cache is not None else client.cache)
        return checked(proposal, client) if proposal.proposed_raw else proposal
    if kind not in KINDS:
        proposal = build(typed, {})
        proposal.typed_raw = query.raw
        return proposal

    def as_typed(reasons, candidates=(), status=None):
        return Proposal(key_typed=query.key, typed_raw=query.raw, entry_type=kind, doi=typed.get("doi"),
                        status=status, issues=[r for r in reasons if r], candidates=list(candidates),
                        needs_decision=True)

    try:
        found = identify(query, client, cache, ws=ws)
    except ProviderError as exc:
        return as_typed([f"The lookup failed: a source did not answer ({exc}); the entry is left as typed"],
                        status=LOOKUP_FAILED)
    if found.record is None:
        return as_typed([found.note] + query.notes, found.candidates)
    # A DOI that was given and is not the record's own is never dropped or replaced: the
    # entry is built without it (the builder fills nothing under a DOI that is not the
    # record's) and it is then shown as a question, given -> offered. Two cases: the DOI of
    # a preprint whose published version is offered, and a typed DOI with punctuation after
    # it. A typed entry's text keeps the typed DOI; a bare query has no text, so the text
    # holds the offered DOI.
    given, cut = None, ""
    if found.published_for and typed.get("doi"):
        given = typed.pop("doi")
    elif query.fields and typed.get("doi") and found.source != "arxiv":
        stripped, cut = _doi_read(str(typed["doi"]))
        if cut and found.record.get("DOI") and stripped and normalize_doi(stripped) == normalize_doi(
                found.record["DOI"]):
            given = typed.pop("doi")
        else:
            cut = ""
    resolution = None
    try:
        if found.source == "arxiv":
            proposal = build_arxiv(typed, found.record)
        else:
            record = found.record
            if found.source != "pubmed" and not typed.get("booktitle"):
                # A series title and a book title, in no stated order: which is the book's is
                # looked for, and the entry is then built from the record with that one title.
                from . import container_titles
                resolution = container_titles.resolve(record, client, cache, announce=announce,
                                                      allow_model=allow_model)
                if resolution is not None and resolution.chosen:
                    record = dict(record, **{"container-title": [resolution.chosen]})
            proposal = build(typed, record, found.corroborating)
            if found.source == "pubmed":
                _renamed_pubmed(proposal)
            if resolution is not None and proposal.proposed_raw is not None:
                container_titles.apply(proposal, resolution)
    except CompletionRefused as exc:
        return as_typed([found.note, str(exc)], found.candidates)
    proposal.typed_raw = query.raw
    proposal.candidates = list(found.candidates)
    proposal.notes += [n for n in query.notes if n not in proposal.notes]
    if found.note:  # a choice to make is an issue; how the record was found is a note
        (proposal.issues if found.candidates or found.published_for else proposal.notes).insert(0, found.note)
    if found.decision:
        proposal.issues.append(found.decision)
        proposal.needs_decision = True
    if found.candidates or found.published_for:
        proposal.needs_decision = True
    if proposal.proposed_raw is None:
        return proposal
    for name, reason in found.questions.items():
        # A built value the lookup says is not settled (PubMed's catalogue title).
        for index, change in enumerate(proposal.changes):
            if change.field == name and change.kind == "filled":
                proposal.changes[index] = FieldChange(name, None, change.proposed, change.source, "question")
                proposal.issues.append(reason)
                proposal.needs_decision, proposal.complete = True, False
    if given:
        offered = found.record.get("DOI")
        if cut:
            offered = _doi_read(given)[0]
            proposal.issues.append(f"doi: the typed DOI ends in {cut!r}, which was taken as punctuation after it; "
                                   f"{offered} was looked up, and the typed value is kept until this is decided")
            proposal.needs_decision = True
        fields = _written_fields(proposal)
        if fields is None:  # the text cannot be rebuilt with the typed DOI in it: nothing is proposed
            return as_typed([found.note, "The proposed entry could not be written with the typed DOI kept"],
                            found.candidates)
        in_entry = bool(query.fields)
        fields["doi"] = given if in_entry else offered
        order = _field_order()
        proposal.changes = sorted(
            [c for c in proposal.changes if c.field != "doi" and c.kind != "dropped"]
            + [FieldChange("doi", given, offered, "typed" if cut else "crossref", "question")],
            key=lambda c: order.index(c.field)) + [c for c in proposal.changes if c.kind == "dropped"]
        proposal.doi = fields["doi"]
        proposal.proposed_raw = render(proposal.entry_type, proposal.key_typed or proposal.key_proposed or NO_KEY,
                                       fields)
        _set_complete(proposal, fields)
    return checked(proposal, client, found.record if found.source == "arxiv" else None)


@dataclass
class KeyPlan:
    key: str
    renames: dict[str, str] = field(default_factory=dict)


def _completion_fields(item):
    if isinstance(item, Proposal):
        return dict(item.edited_fields) if item.edited_fields is not None else (_written_fields(item) or {})
    if isinstance(item, Query):
        return dict(item.fields or {}, **{name: getattr(item, name) for name in
                    ('doi', 'pmid', 'arxiv', 'title', 'author', 'year')
                    if getattr(item, name) is not None})
    raise TypeError('batch reservations must be Proposal objects')


def _reservations(ws, batch):
    """Explicit preview reservations only; callers must pass accepted entries at writing.

    Never mutate a proposal. Apply earlier preview rename maps to the virtual library
    so a third proposal sees the first two as a/b. This is not permission to write any
    rename: the final accepted batch must be planned again against the live library.
    """
    library = _library_entries(ws)
    entries = {key: dict(entry['fields']) for key, entry in library.items()}
    for item in batch:
        if not isinstance(item, Proposal):
            raise TypeError('batch reservations must be Proposal objects')
        if item.duplicate_of or not item.proposed_raw:
            continue
        for old, new in item.renames.items():
            if old in entries:
                if new in entries:
                    raise ValueError(f'Key reservation collision: {new}')
                entries[new] = entries.pop(old)
                entries[new]['ID'] = new
        key = item.key_typed or item.key_proposed
        if not key or key == NO_KEY:
            continue
        if key in entries and not (item.key_typed == key and key in library
                                   and item.typed_raw == library[key]['raw']):
            raise ValueError(f'Key reservation collision: {key}')
        entries[key] = dict(_completion_fields(item), ID=key)
    return entries


def _work_ids(fields):
    ids = set()
    doi = fields.get('doi')
    if doi:
        try:
            ids.add(('doi', normalize_doi(doi)))
        except ValueError:
            pass
    pmid = str(fields.get('pmid') or '').strip()
    match = _PMID_TEXT.fullmatch(pmid)
    if match:
        ids.add(('pmid', str(int(match[1]))))
    elif pmid.isdigit():
        ids.add(('pmid', str(int(pmid))))
    try:
        arxiv_journal = normalized(fields.get('journal') or '') == 'arxiv'
    except ValueError:
        arxiv_journal = False
    for value in (fields.get('arxiv'), fields.get('eprint'), doi,
                  fields.get('volume') if arxiv_journal else None):
        identifier = _arxiv_text(str(value)) if value else None
        if identifier:
            ids.add(('arxiv', re.sub(r'v\d+$', '', identifier)))
    return ids


def _title_byline(fields):
    from .name_parsing import splitname
    title, author = fields.get('title'), fields.get('author')
    if not title or not author:
        return None
    try:
        surnames = []
        for name in split_authors(author):
            if name.startswith('{') and name.endswith('}'):
                surname = normalized(name)
            else:
                parts = splitname(name, strict_mode=True)
                surname = normalized(' '.join(parts['von'] + parts['last']))
            if not surname:
                return None
            surnames.append(surname)
        return normalized(title), tuple(surnames)
    except ValueError:
        return None


def duplicates(ws, proposal_or_query, batch=()):
    """Same identifiers or normalized title and ordered surnames, excluding typed self.

    ``batch`` explicitly selects earlier Proposal preview reservations; omitted proposals
    have no effect. A typed entry is its own library entry only when its raw bytes match.
    An edited or newly typed key does not hide the entry it happens to collide with.
    """
    fields = _completion_fields(proposal_or_query)
    ids, title = _work_ids(fields), _title_byline(fields)
    raw = proposal_or_query.typed_raw if isinstance(proposal_or_query, Proposal) else proposal_or_query.raw
    key = proposal_or_query.key_typed if isinstance(proposal_or_query, Proposal) else proposal_or_query.key
    library = _library_entries(ws)
    batch = tuple(batch)
    entries = _reservations(ws, batch)
    self_key = key if raw and key in library and raw == library[key]['raw'] else None
    for item in batch:
        if not item.duplicate_of and item.proposed_raw:
            self_key = item.renames.get(self_key, self_key)
    for existing, data in entries.items():
        if self_key == existing:
            continue
        if ids & _work_ids(data) or (title is not None and title == _title_byline(data)):
            return existing
    return None


def plan_key(ws, fields, batch=()):
    """House helper key/suffix preview. All changes are returned, never written.

    Explicit batch proposals reserve keys for previews only; final writing must recompute
    with accepted proposals only and ask again if the displayed rename plan changes.
    """
    return _key_plan(fields, _reservations(ws, batch))


def _key_plan(fields, entries):
    from .helpers import authors2key, check_key_suffixes, key_names
    # The names a key is built from: the authors, or the editors of an edited volume
    # (helpers.key_names).
    base = authors2key(fields.get('author') or fields['editor'], fields['year'])
    related = {}
    for (key, data), names in zip(entries.items(), key_names(entries)):
        if names.strip() and data.get('year') and authors2key(names, data['year']) == base:
            related[key] = dict(data, ID=key)
    marker = '__completion_new__'
    while marker in related:
        marker += '_'
    related[marker] = dict(fields, ID=marker)
    targets = check_key_suffixes(related)
    renames = {old: new for old, new in zip(related, targets) if old != marker and old != new}
    occupied = set(entries) - set(renames)
    for target in [targets[-1], *renames.values()]:
        if target in occupied and target not in related:
            raise ValueError(f'Key already belongs to another work: {target}')
    return KeyPlan(targets[-1], renames)


def _plan_proposal(ws, proposal, query, batch):
    """Attach local review findings, independently of source verification status."""
    entries = _library_entries(ws)
    if query.key in entries and (not query.raw or query.raw != entries[query.key]['raw']):
        proposal.issues.append(f'The typed key {query.key} already exists in the library; decide which entry it belongs to')
        proposal.needs_decision = True
    proposal.duplicate_of = duplicates(ws, proposal if proposal.proposed_raw else query, batch)
    if proposal.duplicate_of:
        proposal.duplicate_in_library = bool(query.key in entries and query.raw == entries[query.key]['raw'])
        proposal.issues.append(f'This work is already in the library or batch as {proposal.duplicate_of}')
        proposal.needs_decision = True
        return proposal
    fields = _completion_fields(proposal)
    if (fields.get('author') or (fields.get('editor') and proposal.record_source == 'loc-catalogue')) and fields.get('year'):
        # Updating an exact typed library entry must not reserve that entry twice.
        reserved = _reservations(ws, batch)
        if query.key in entries and query.raw == entries[query.key]['raw']:
            self_key = query.key
            for item in batch:
                if not item.duplicate_of and item.proposed_raw:
                    self_key = item.renames.get(self_key, self_key)
            reserved.pop(self_key, None)
        try:
            plan = _key_plan(fields, reserved)
        except ValueError as exc:
            proposal.issues.append(str(exc))
            proposal.needs_decision = True
            return proposal
        proposal.key_proposed, proposal.renames = plan.key, plan.renames
        if plan.renames or (proposal.key_typed and proposal.key_typed != plan.key):
            proposal.needs_decision = True
        if not proposal.key_typed:
            proposal.proposed_raw = render(proposal.entry_type, plan.key, fields)
    return proposal


def _library_entries(ws):
    from .verification import load_entries
    # The strict scanner deliberately refuses a bibliography with no entries. An empty
    # file is a valid starting library here; every nonempty file still uses that scanner.
    return load_entries(ws.bib) if ws.bib.read_text(encoding="utf-8-sig").strip() else {}


def propose(query, client, cache, ws=None, batch=(), announce=None, allow_model=None):
    """Find, build and check (see ``_propose``); optionally attach local key previews.

    ``ws`` is explicit, never discovered/downloaded. ``batch`` explicitly reserves earlier
    proposals for this preview, not for writing; the writer must replan accepted entries.
    """
    batch = tuple(batch)
    proposal = _propose(query, client, cache, ws=ws, announce=announce, allow_model=allow_model)
    return _plan_proposal(ws, proposal, query, batch) if ws is not None else proposal


@dataclass
class Outcome:
    """What the writer did with one accepted proposal."""
    index: int           # its place in the ``accepted`` list
    key: str             # written: the key it has in the file now; removed: the key removed;
                         # refused: the key the refusal is listed under in ``Applied.refused``
    status: str          # "written" | "removed" | "refused"
    reason: str = ""     # why, when refused


def has_force(fields):
    """Does an entry (its fields, any case) carry the ``force`` field, the per-entry override
    of the format checker? Such an entry is never written and never passes the gate
    (prompts.FORCE_REFUSED): every entry follows the same house rules."""
    return any(str(name).lower() == "force" for name in fields or ())


@dataclass
class Applied:
    written: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    renamed: dict[str, str] = field(default_factory=dict)
    refused: list[tuple[str, str]] = field(default_factory=list)
    # One Outcome per accepted proposal, in the order they were given (outcomes[i] is about accepted[i]).
    outcomes: list = field(default_factory=list)
    backup: object = None       # the managed library's checkpoint taken before the write
    saved_copy: object = None   # any other library: the copy of cdl.bib as it was (.bibcheck/edits/)
    notes: list = field(default_factory=list)   # non-fatal lines (an interrupted earlier write that was settled)


def _key_token(raw, key):
    match = re.match(r'(@[A-Za-z]+\s*[({]\s*)([^,\s})]+)', raw)
    if not match:
        raise ValueError('The proposed entry has no citation key token')
    return raw[:match.start(2)] + key + raw[match.end(2):]


from .library import serialized


@serialized
def apply(ws, accepted, *, batch=None, before_commit=None):
    """Write explicitly accepted proposals in place, refusing stale spans and previews.

    ``before_commit(entries, result)``: called once everything is planned and nothing is
    written yet, with the library as it will be (``verification.load_entries`` of the exact
    text about to be written: keys, texts, fingerprints) and the Applied so far; what it
    raises stops the write, with nothing written.

    UTF-8 (including BOM), line endings and final-newline presence are retained. No
    approval is recorded. New entries append in accepted order with one blank line:
    the house formatter does not require sorting entries. The files are written by
    writer.commit (checkpoint or pre-write copy, changed-since-read refusal, recovery).
    """
    import tempfile
    from . import writer
    from .prompts import FORCE_REFUSED
    from .errors import CdlbibError
    from .verification import load_entries
    from .workspace import Workspace

    result = Applied()
    try:
        writer.require_protectable(ws)
        from . import library
        result.notes = library.settled(ws) + writer.recover(ws)
        original = ws.bib.read_bytes()
        bom = original.startswith(b'\xef\xbb\xbf')
        text = original.decode('utf-8-sig')
        newline = '\r\n' if '\r\n' in text else '\n'
        final = text.endswith('\n')
        # A snapshot lets the strict scanner validate the one original read and each
        # virtual accepted state, without rereading the user's file during planning.
        with tempfile.TemporaryDirectory(prefix='cdlbib-apply-') as folder:
            snapshot = Workspace(folder)
            def scan(value):
                snapshot.bib.write_bytes(value.encode('utf-8'))
                return load_entries(snapshot.bib) if value.strip() else {}
            entries = scan(text)
            used_spans = set()
            for index, proposal in enumerate(accepted):
                if not isinstance(proposal, Proposal):
                    raise CdlbibError('Accepted entries must be Proposal objects')
                name = proposal.key_typed or proposal.key_proposed or NO_KEY
                try:
                    if not proposal.remove_duplicate and (not proposal.proposed_raw or proposal.unsupported):
                        raise ValueError('No writable entry was proposed')
                    if proposal.typed_raw is not None:
                        count = text.count(proposal.typed_raw)
                        if count != 1:
                            raise ValueError(f'appears {count} times' if count else 'changed on disk')
                        live = entries.get(proposal.key_typed)
                        if live is None or live['raw'] != proposal.typed_raw:
                            raise ValueError('changed on disk: the typed text is not a live entry under its original key')
                        if proposal.typed_raw in used_spans:
                            raise ValueError('The typed entry was already accepted in this batch')
                    if proposal.remove_duplicate:
                        if not proposal.typed_raw or not proposal.duplicate_of:
                            raise ValueError('Only a typed live duplicate can be removed')
                        duplicate_entry = entries.get(proposal.duplicate_of)
                        duplicate = duplicate_entry['fields'] if duplicate_entry else None
                        own = entries[proposal.key_typed]['fields']
                        if duplicate is None or proposal.duplicate_of == proposal.key_typed or not (
                            _work_ids(own) & _work_ids(duplicate) or
                            (_title_byline(own) is not None and _title_byline(own) == _title_byline(duplicate))
                        ):
                            raise ValueError('The duplicate identity changed; review a new proposal')
                        text = text.replace(proposal.typed_raw, '', 1)
                        entries = scan(text)
                        used_spans.add(proposal.typed_raw)
                        result.removed.append(proposal.key_typed)
                        result.outcomes.append(Outcome(index, proposal.key_typed, 'removed'))
                        continue
                    fields = _completion_fields(proposal)
                    if has_force(fields):
                        raise ValueError(FORCE_REFUSED)
                    old = proposal.key_typed
                    reserved = {key: dict(entry['fields']) for key, entry in entries.items()}
                    if old in entries and proposal.typed_raw == entries[old]['raw']:
                        reserved.pop(old)
                    elif old in entries:
                        raise ValueError(f'The typed key {old} already exists in the library')
                    ids, identity = _work_ids(fields), _title_byline(fields)
                    for key, data in reserved.items():
                        if ids & _work_ids(data) or (identity is not None and identity == _title_byline(data)):
                            raise ValueError(f'This work is already in the library or accepted batch as {key}')
                    plan = _key_plan(fields, reserved)
                    if plan.key != proposal.key_proposed or plan.renames != proposal.renames:
                        raise ValueError('The key or rename plan changed; review a new proposal')
                    candidate = text
                    raw = _key_token(proposal.proposed_raw, plan.key)
                    raw = raw.replace('\r\n', '\n').replace('\n', newline)
                    if proposal.typed_raw is not None:
                        candidate = candidate.replace(proposal.typed_raw, raw, 1)
                    else:
                        candidate = candidate + (newline * (2 if not candidate.endswith(newline) else
                                    1 if not candidate.endswith(newline * 2) else 0) if candidate else '') + raw
                        if final:
                            candidate += newline
                    renames = dict(plan.renames)
                    if old and old != plan.key:
                        renames[old] = plan.key
                    for source, target in plan.renames.items():
                        source_raw = entries[source]['raw']
                        if candidate.count(source_raw) != 1:
                            raise ValueError(f'The entry to rename {source} is not uniquely located')
                        candidate = candidate.replace(source_raw, _key_token(source_raw, target), 1)
                    next_entries = scan(candidate)
                    if has_force(next_entries[plan.key]['fields']):       # whatever the proposal said its fields were
                        raise ValueError(FORCE_REFUSED)
                    text, entries = candidate, next_entries
                    if proposal.typed_raw is not None:
                        used_spans.add(proposal.typed_raw)
                    result.written = [plan.renames.get(key, key) for key in result.written] + [plan.key]
                    for earlier in result.outcomes:       # an entry written earlier in this batch may be renamed by this one
                        if earlier.status == 'written':
                            earlier.key = plan.renames.get(earlier.key, earlier.key)
                    result.outcomes.append(Outcome(index, plan.key, 'written'))
                    result.renamed.update(renames)
                except (ValueError, KeyError, TypeError) as exc:
                    result.refused.append((name, str(exc)))
                    result.outcomes.append(Outcome(index, name, 'refused', str(exc)))
            if not result.written and not result.removed:
                return result
        changed = (b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8')
        writes = [(ws.bib, changed)]
        expected = {ws.bib: original}
        if result.renamed:
            ledger, expected[ws.key_renames], data = writer.renames_recorded(
                ws, result.renamed, 'Accepted entry completion key plan')
            writes.append((ledger, data))
        if before_commit is not None:
            before_commit(entries, result)
        done = writer.commit(ws, writes, expected, batch=batch)
        result.backup, result.saved_copy = done.backup, done.saved_copy
        return result
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise CdlbibError(f'Entry completion could not be written: {exc}') from exc
