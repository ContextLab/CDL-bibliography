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
    differently, a title whose capitals come from a Title Case source, a lone first page
    and a year the sources leave open are questions;
  - ``dropped``: a field outside the house list, or ``publisher`` on an article.

Only journal articles are built. Any other type gives a proposal with ``unsupported`` set
and no proposed text. A record that is itself a correction or retraction notice is refused
(``CompletionRefused``). An article that has been retracted is built, named as retracted
in ``issues``, and always needs a decision.
"""

from dataclasses import dataclass, field
import re
import unicodedata

from . import correction_proposals as cp
from .auto_review import compatible_authors, expanded_pages, safe_compare
from .errors import CompletionRefused
from .verification import (CORRECTION_FLAG, normalize_doi, normalize_journal, normalized,
                           print_year_selects_cited, split_authors)

# The key written when neither a typed key nor the authors and year are there to make one.
NO_KEY = "KeyNeeded"

# The fields built from a source record, in the order they are settled (the layout's order).
BUILT_FIELDS = ("author", "doi", "journal", "number", "pages", "title", "volume", "year")
# The fields an article is expected to have: one that no source states is listed as unfilled.
EXPECTED_FIELDS = ("author", "journal", "pages", "title", "volume", "year")

# Crossref update types that make a record a notice about another work.
NOTICE_WORDS = ("errat", "corrig", "correct", "retract", "withdraw", "concern", "removal")
RETRACTION_WORDS = ("retract", "withdraw", "removal")

# A page locator the pagination rules accept (correction_proposals.single_source_proposal).
_PAGES = re.compile(r"[a-z]{0,3}\d+(?:-[a-z]{0,3}\d+(?:\.e\d+)?)?")
_DATES = ("published-print", "published-online", "issued", "published")

CAPITALS_QUESTION = ("title: capitalisation taken from a title-case source; proper nouns and acronyms "
                     "cannot be told apart from ordinary words")


# Non-ASCII letters are written in LaTeX, in the form the library itself uses most for each
# kind of accent (counted in tests/fixtures/cdl-prewave1-2026-09-26.bib, 2026-10-02; the
# counts are in tests/test_complete_build.py). "{}" stands for the letter.
_SYMBOL_ACCENTS = {  # combining mark -> (accent command, form)
    "\u0308": ('"', "braced"),   # {\"o} 85, \"{o} 45, {\"{o}} 39, \"o 12
    "\u0301": ("'", "argument"),  # \'{e} 82, {\'e} 66, {\'{e}} 24, \'e 23
    "\u0300": ("`", "braced"),   # {\`a} 3
    "\u0302": ("^", "braced"),   # {\^o} 1, {\^{o}} 1, \^o 1
    "\u0303": ("~", "braced"),   # {\~n} 7, \~{n} 4
    "\u0304": ("=", "braced"),   # none in the library: the commonest form overall
    "\u0307": (".", "braced"),   # none in the library
}
_LETTER_ACCENTS = {  # combining mark -> (accent command, form)
    "\u0327": ("c", "braced"),    # {\c{s}} 3, {\c s} 3
    "\u030c": ("v", "argument"),  # \v{c} 4, {\v{r}} 2, {\v C} 2
    "\u0306": ("u", "braced"),    # {\u{g}} 3
    "\u030b": ("H", "braced"),    # {\H{o}} 2, {\H o} 2
    "\u030a": ("r", "braced"),    # none in the library
    "\u0328": ("k", "braced"),    # none in the library
    "\u0323": ("d", "braced"),    # none in the library
    "\u0331": ("b", "braced"),    # none in the library
}
_LETTERS = {  # {\o} 3, {\l} 2, {\ss} 1, {\L} 1, {\AA} 1, {\ae} 1 in the library
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
        if len(marks) == 1 and base.isascii() and base.isalpha() and (marks in _SYMBOL_ACCENTS or marks in _LETTER_ACCENTS):
            symbol = marks in _SYMBOL_ACCENTS
            command, form = (_SYMBOL_ACCENTS if symbol else _LETTER_ACCENTS)[marks]
            if form == "argument":
                out.append("\\" + command + "{" + base + "}")
            else:
                out.append("{\\" + command + (base if symbol else "{" + base + "}") + "}")
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
    duplicate_of: str | None = None
    key_proposed: str | None = None
    renames: dict[str, str] = field(default_factory=dict)
    unsupported: str | None = None
    needs_decision: bool = False  # True: never accepted without the person looking at it
    notes: list[str] = field(default_factory=list)  # how the record was found; not a problem


def _field_order():
    from .helpers import read
    return sorted(read("keep_fields.txt"))  # the order check_bib writes (helpers.check_bib)


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


def _text(value):
    """A registry string on one line (a deposited line break is white space)."""
    return " ".join(str(value or "").split())


def _is_text(value):
    return value is None or isinstance(value, str)


def _readable(record):
    """The record without the parts that are not in the form Crossref documents, and
    ``{field: reason}`` for each part left out. The helpers are only ever given parts whose
    shape they expect, so an exception from one of them is a defect, not a bad record."""
    clean, problems = dict(record), {}

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


def _title_case(text):
    """Whether a title is printed with its ordinary words capitalised (Title Case): more
    than half of the longer words after the first begin with a capital."""
    words = re.findall(r"[^\W\d_][\w'’]*", text)[1:]
    judged = [w for w in words if len(w) >= 5] or words
    return bool(judged) and sum(w[0].isupper() for w in judged) > len(judged) / 2


def _own_capitals(text):
    """The words a sentence-case title capitalises in mid-sentence: names and acronyms the
    source itself marks. Given to ``source_title`` as protected words, which keeps them."""
    words = []
    for match in re.finditer(r"[^\W\d_][\w'’-]*", text):
        before = text[:match.start()].rstrip()
        if match[0][0].isupper() and before and before[-1] not in ":.?!":
            words.append(match[0])
    return words


def _without_compound_capitals(text):
    """A Title Case title with its hyphenated ordinary words in lower case
    ("Feature-Based" -> "feature-based"), so the title helper does not read their two
    capitals as an acronym. A compound with an all-capital part (EEG-fMRI) is left alone."""
    return re.sub(r"(?<![\w-])[A-Z][a-z]+(?:-[A-Za-z][a-z]+)+(?![\w-])", lambda m: m[0].lower(), text)


def _title(record, mapped, typed, evidence, unsupported):
    from .helpers import format_title
    if "title" not in evidence:
        raise _Hold(unsupported or "title: the source record has no usable title")
    titles = _source_titles(record, evidence)
    if not titles:
        return None
    if len(titles) != 1:
        raise _Hold("title: several source titles", {"crossref": "; ".join(titles)})
    values = {"crossref": titles[0]}
    second = _text((mapped.get("title") or [""])[0]) if mapped else ""
    if second:
        values["pubmed"] = second
        if cp.normalize_title_safe(second) != cp.normalize_title_safe(titles[0]):
            raise _Hold("title: sources disagree", values, disagreement=True)
    # Capitals are only settled by a source that prints the title in sentence case: there
    # a capital in mid-sentence is a name or an acronym. A Title Case title capitalises
    # every word, so its capitals say nothing; the sentence-case candidate is a question.
    doubt = None
    if not _title_case(titles[0]):
        text = titles[0]
    elif second and not _title_case(second):
        text = second
    else:
        text, doubt = _without_compound_capitals(titles[0]), CAPITALS_QUESTION
    protected = "" if doubt else " ".join("{" + word + "}" for word in _own_capitals(text))
    try:
        value = cp.source_title(text, ((typed or "") + " " + protected).strip())
    except ValueError as exc:
        raise _Hold(str(exc), values)
    doubts = ([doubt] if doubt else []) + _character_question("title", value)
    value = latex_text(value)
    if format_title(value) != value:
        raise _Hold("title: the title formatter changes the built title", values)
    return _Value(value, "crossref+pubmed" if second else "crossref", values, doubts)


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
    doubts = _character_question("author", value)
    value = latex_text(value)
    if reformat_author(value) != value:
        raise _Hold("author: the author formatter changes the built byline", values)
    return _Value(value, source, values, doubts)


def _journal(record):
    from .helpers import format_journal_name
    venues = [_text(v) for v in record.get("container-title") or [] if _text(v)]
    if not venues:
        return None
    values = {"crossref": "; ".join(venues)}
    if len(venues) != 1 or re.search(r"[<>{}\\$]", venues[0]):
        raise _Hold("journal: no single registry venue", values)
    value = format_journal_name(cp.journal_text(venues[0]))  # the publisher's name, "The" included
    doubts = _character_question("journal", value)
    value = latex_text(value)
    try:
        same = normalize_journal(value) == normalize_journal(venues[0]) and format_journal_name(value) == value
    except ValueError:
        same = False
    if not same:
        raise _Hold("journal: formatter changes the venue", values)
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
            pages, source = two, "pubmed; crossref gives the first page"
        elif cp.shortens_pages(one, two):
            pages, source = one, "crossref; pubmed gives the first page"
        else:
            raise _Hold("pages: sources disagree", values, disagreement=True)
    else:
        pages = one or two
        source = "crossref+pubmed" if one and two else "crossref" if one else "pubmed"
        from_number = bool(one and not record.get("page") and record.get("article-number"))
        if "+" not in source and "-" not in pages and not _article_number(pages, record, from_number):
            doubts.append(f"pages: the source gives only a first page ({pages}); the last page is not confirmed")
    return _Value(pages.replace("-", "--"), source, values, doubts)


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


def _house_form(name, value):
    """A typed value as the format checker would write it (helpers.check_bib rewrites the
    title, the journal, the authors and the pages; it leaves every other field alone), with
    raw non-ASCII letters in the library's LaTeX form. A DOI is never rewritten."""
    from . import helpers
    if name == "doi":
        return value
    if name == "pages":
        return helpers.valid_pages(value)[1][1]
    if name == "title":
        value = helpers.format_title(value)
    elif name == "journal":
        value = helpers.format_journal_name(value)
    elif name == "author":
        value = helpers.reformat_author(value)
    return latex_text(value)  # new text is written in the library's LaTeX form


def build(typed_fields, record, corroborating=None):
    """Propose a complete ``@article`` entry for ``record``.

    ``typed_fields``: the entry as typed, by lower-case field name, with ``ENTRYTYPE`` and
    ``ID`` when there are any (``{"doi": ...}`` alone is enough). ``record``: the Crossref
    record of the work. ``corroborating``: the PubMed record for the same DOI in the shape
    ``auto_review.epmc_record`` returns, or None.

    Raises ``CompletionRefused`` when the record is a correction or retraction notice.
    """
    from .helpers import authors2key, split_names
    typed = {(k if k in ("ENTRYTYPE", "ID") else k.lower()): v for k, v in typed_fields.items()
             if v is not None and str(v) != ""}
    kind = str(typed.get("ENTRYTYPE") or "article").lower()
    record_doi = record.get("DOI").strip() if isinstance(record.get("DOI"), str) else ""
    proposal = Proposal(key_typed=typed.get("ID") or None, entry_type=kind, record_source="crossref",
                        doi=typed.get("doi") or record_doi or None)
    if kind != "article":
        proposal.unsupported = kind
        proposal.issues.append(f"An entry of type {kind} is not built automatically; the entry is left as typed")
        return proposal
    if record.get("type") != "journal-article":
        named = record.get("type") if isinstance(record.get("type"), str) and record.get("type") else None
        proposal.unsupported = named or "unknown"
        proposal.issues.append((f"A record of type {named}" if named else "A record with no type")
                               + " is not built automatically; the entry is left as typed")
        return proposal
    record, problems = _readable(record)
    _refuse_notice(record)

    def same_doi(one, two):
        try:
            return normalize_doi(one) == normalize_doi(two)
        except ValueError:
            return False

    mapped = corroborating
    if mapped is not None:
        if isinstance(mapped.get("DOI"), str) and same_doi(mapped["DOI"], record_doi):
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
    house = {k: v for k, v in typed.items() if k in keep and k != "publisher"}
    evidence, compare_issues = safe_compare(dict(house, ENTRYTYPE="article"), record)
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
    if retractions:  # decision log: retractions are flagged for the person; nothing automatic
        proposal.issues.append("The article was retracted (the retraction notice: " + ", ".join(retractions)
                               + "); it is not added without a decision")
        proposal.needs_decision = True
    if record.get("update-to") or record.get("updated-by"):
        proposal.issues.append(CORRECTION_FLAG)

    makers = {
        "author": lambda: _author(record, mapped, typed.get("author")),
        "journal": lambda: _journal(record),
        "number": lambda: _number(record, mapped),
        "pages": lambda: _pages(record, mapped),
        "title": lambda: _title(record, mapped, typed.get("title"), evidence, unsupported),
        "volume": lambda: _volume(record, mapped),
        "year": lambda: _year(record, mapped, evidence),
    }
    fields = {}

    def keep_typed(name, had):
        """The typed value stays; in house form when the format checker would rewrite it."""
        formed = _house_form(name, had)
        fields[name] = formed
        if formed == had:
            proposal.changes.append(FieldChange(name, had, had, "typed", "kept"))
        else:
            proposal.changes.append(FieldChange(name, had, formed, "house format", "changed"))

    def question(name, had, value, source, reasons):
        fields[name] = had if had else value
        proposal.changes.append(FieldChange(name, had, value, source, "question"))
        proposal.issues.extend([reasons] if isinstance(reasons, str) else reasons)
        proposal.needs_decision = True

    for name in BUILT_FIELDS:
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
            elif name in EXPECTED_FIELDS or name in problems:
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
    for name in sorted(k for k in typed if k not in ("ENTRYTYPE", "ID") and k not in BUILT_FIELDS):
        if name == "publisher" and cp.drop_publisher_proposal(
                {"fields": {"ENTRYTYPE": "article", "publisher": typed[name]}, "key": proposal.key_typed,
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
    return proposal


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
_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.I)
# DataCite relations by which an arXiv record names its published version.
_PUBLISHED_RELATIONS = {"IsPreprintOf", "IsVersionOf", "IsIdenticalTo"}


def _doi_text(text):
    """``text`` as a DOI without its resolver prefix, in the case it was given; None when
    it is not a DOI (``verification.normalize_doi`` is the test)."""
    from urllib.parse import unquote
    value = unquote(_DOI_PREFIX.sub("", text.strip()).replace("\\_", "_"))
    try:
        normalize_doi(value)
    except ValueError:
        return None
    return value


def _arxiv_text(text):
    """``text`` as an arXiv identifier (``2208.02957``, with ``v2`` when a version was
    given); None when it is not one (``arxiv_review.parse_id`` is the test)."""
    from .arxiv_review import parse_id
    value = re.sub(r"\.pdf$", "", text.strip(), flags=re.I)
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

    @classmethod
    def parse(cls, text, author=None, year=None):
        """A DOI or DOI link, ``PMID:123`` or a PubMed link, an arXiv id, link or DOI;
        anything else is the words of a title."""
        text = " ".join(str(text or "").split())
        author, year = (author or "").strip() or None, str(year or "").strip() or None
        pmid = _PMID_TEXT.fullmatch(text)
        if pmid:
            return cls(pmid=pmid[1], author=author, year=year)
        arxiv = _arxiv_text(text) if text else None
        if arxiv:
            return cls(arxiv=arxiv, author=author, year=year)
        doi = _doi_text(text) if text else None
        if doi:
            return cls(doi=doi, author=author, year=year)
        return cls(title=text or None, author=author, year=year)

    @classmethod
    def from_entry(cls, entry):
        """The query a typed entry makes (``verification.load_entries`` shape). An entry
        that names arXiv as its journal is an arXiv query; otherwise its DOI comes first,
        then a PMID, then its title, authors and year."""
        from .arxiv_review import identifier
        from .verification import arxiv_id
        fields = dict(entry["fields"])
        doi = (fields.get("doi") or "").strip() or None
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
    """
    record: dict | None = None
    corroborating: dict | None = None
    candidates: list[dict] = field(default_factory=list)
    source: str | None = None
    note: str | None = None
    published_for: str | None = None


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


def _from_doi(client, doi, follow=True):
    """The record of a DOI. It is that DOI's Crossref record and nothing else: nothing is
    searched for, and a DOI Crossref does not have gives no record. A preprint record that
    names one published journal article is answered with the article, offered first."""
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
            if published.record is not None and published.record.get("type") == "journal-article":
                published.candidates = [_summary(published.record), _summary(record)]
                published.published_for = doi
                published.note = _notes(
                    alias, f"The DOI {doi} is a preprint; its record names {published.record.get('DOI')} as the "
                    "published version, which is proposed here (house rule: cite the published version).",
                    published.note)
                return published
    # A correction or retraction notice is refused by the builder: PubMed is not asked about it.
    mapped, _, unused = (None, None, None) if _is_notice(record) else _corroboration(client, record)
    return Identified(record=record, corroborating=mapped, source="crossref+pubmed" if mapped else "crossref",
                      note=_notes(alias, unused))


def _pubmed_client(client):
    """``extra_sources`` reads the contact address from ``client.contact`` (set by its own
    ``make_client``); a plain ``PoliteClient`` has it as ``mailto``."""
    if getattr(client, "contact", None) is None:
        client.contact = client.mailto
    return client


def _by_pmid(client, pmid):
    from .extra_sources import efetch, medline_is_notice, medline_record
    records, _ = efetch(_pubmed_client(client), [pmid])
    raw = records.get(str(pmid))
    if raw is None:
        return Identified(note=f"PubMed has no journal article under PMID {pmid}; the entry is left as typed")
    listed = dict(_summary(medline_record(raw), "pubmed"), pmid=str(pmid))
    if medline_is_notice(raw):
        kinds = ", ".join(raw.get("publication_types") or [])
        return Identified(candidates=[listed], note=f"PMID {pmid} is not an article ({kinds}); nothing was built from it")
    if len(raw["dois"]) != 1:
        said = "no DOI" if not raw["dois"] else "several DOIs (" + ", ".join(raw["dois"]) + ")"
        return Identified(candidates=[listed], note=f"The PubMed record {pmid} has {said}; an entry is built from "
                                                    "a Crossref record, so nothing was built")
    found = _from_doi(client, raw["dois"][0])
    if found.record is None:
        found.candidates = [listed]
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


def _judged(fields, record, source, want_surname, want_year):
    """How a found record stands against the typed title, first author and year.

    ``strict``: the title is the same after ``verification.normalize_title`` (the
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
    return {"record": record, "source": source, "doi": record.get("DOI"),
            "strict": usable and same_title and same_surname and same_year,
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


def _by_title(client, query):
    """Crossref's bibliographic search (``PoliteClient.crossref_search``) and PubMed
    (``extra_sources.route_pubmed``), judged by ``_judged``."""
    from .extra_sources import crossref_candidate, medline_is_notice, medline_record, route_pubmed
    fields = {k: v for k, v in (query.fields or {}).items() if isinstance(v, str)}
    fields.update({k: v for k, v in (("title", query.title), ("author", query.author), ("year", query.year)) if v})
    fields = dict(fields, ENTRYTYPE="article")
    fields.pop("doi", None)
    want_surname, want_year = _first_surname(fields.get("author")), fields.get("year")
    response = client.crossref_search(fields)
    items = (response.get("body") or {}).get("message", {}).get("items", [])
    pool = [_judged(fields, record, "crossref", want_surname, want_year) for record in items]
    known = set()
    for item in pool:
        try:
            known.add(normalize_doi(item["doi"]))
        except (ValueError, AttributeError):
            continue
    pubmed = route_pubmed(_pubmed_client(client), fields)
    for pmid, raw in pubmed["records"].items():
        if medline_is_notice(raw):
            continue
        mapped = medline_record(raw, fields.get("journal"))
        judged = _judged(fields, mapped, "pubmed", want_surname, want_year)
        if not judged["plausible"] and not judged["strict"]:
            continue
        if mapped.get("DOI"):
            if normalize_doi(mapped["DOI"]) in known:
                continue  # the same work Crossref's search already gave
            candidate = crossref_candidate(client, mapped["DOI"])
            if candidate:  # found through PubMed; the record is still Crossref's
                known.add(normalize_doi(mapped["DOI"]))
                pool.append(_judged(fields, candidate["record"], "crossref", want_surname, want_year))
                continue
        pool.append(judged)

    asked = ["the title"] + (["the first author"] if want_surname else []) + (["the year"] if want_year else [])
    asked = asked[0] if len(asked) == 1 else ", ".join(asked[:-1]) + " and " + asked[-1]
    strict = _distinct_works([item for item in pool if item["strict"]])
    if len(strict) == 1 and strict[0]["source"] == "crossref":
        found = _from_doi(client, strict[0]["doi"])
        found.note = _notes(f"One record matches {asked}: {strict[0]['doi']}.", found.note)
        return found
    if strict:
        listed = [_summary(item["record"], item["source"]) for item in strict[:SHORT_LIST]]
        if len(strict) == 1:
            return Identified(candidates=listed, note=f"The one record that matches {asked} is in PubMed only, "
                                                      "without a DOI; an entry is built from a Crossref record")
        return Identified(candidates=listed, note=f"{len(strict)} records match {asked}; one has to be chosen")
    plausible = _distinct_works([item for item in pool if item["plausible"]])
    if plausible:
        listed = [_summary(item["record"], item["source"]) for item in plausible[:SHORT_LIST]]
        return Identified(candidates=listed,
                          note=f"No record matches {asked} exactly; {len(plausible)} similar "
                               f"record{'s' if len(plausible) != 1 else ''} found, and none is taken without a choice")
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


def _by_arxiv(client, cache, requested):
    from . import arxiv_review as ar
    base, _ = ar.parse_id(requested)
    own = ar.doi_for(base)

    def published(doi, said_by):
        """The published version a source names: the identification when Crossref has it as
        a journal article; otherwise why not, and the record Crossref does have, if any."""
        doi = _doi_text(doi or "")
        if not doi or normalize_doi(doi) == own:
            return None, None, []
        found = _from_doi(client, doi, follow=False)
        if found.record is None:
            return None, (f"{said_by} names {doi} as the published version of arXiv:{requested}, but Crossref "
                          "has no record of that DOI; the preprint is proposed."), []
        if found.record.get("type") != "journal-article":
            return None, (f"{said_by} names {doi} as the published version of arXiv:{requested}; Crossref has "
                          f"it as a record of type {found.record.get('type')}, which is not built automatically. "
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


def identify(query, client, cache=None):
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
    if query.doi:
        return _from_doi(client, query.doi)
    if query.pmid:
        return _by_pmid(client, query.pmid)
    if query.arxiv:
        return _by_arxiv(client, cache if cache is not None else client.cache, query.arxiv)
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
        if formed == had:
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
            for key in sorted(errors):
                for name in sorted(errors[key]):
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
    except ProviderError as exc:
        proposal.status = LOOKUP_FAILED
        add(f"The proposed entry could not be verified: a source did not answer ({exc})")
        proposal.needs_decision = True
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
    return proposal


def propose(query, client, cache):
    """Find the work, build the entry, and have it checked. Returns a ``Proposal`` always:

    - no record (an unresolved DOI, nothing found, several candidates): the entry is left
      as typed (``proposed_raw`` is None), ``issues`` says why, ``candidates`` lists the
      choices;
    - a source did not answer: ``status`` is ``provider_error`` and ``issues`` gives the
      reason, so one failed lookup does not lose the other queries of a batch;
    - otherwise the built entry, with the verifier's ``status`` and ``issues`` for it.
    Nothing here records an approval: ``status`` is only ever what the verifier returned.
    """
    from .verification import ProviderError
    typed = dict(query.fields) if query.fields else ({"doi": query.doi} if query.doi else {})
    kind = str(typed.get("ENTRYTYPE") or "article").lower()
    if kind != "article":
        proposal = build(typed, {})
        proposal.typed_raw = query.raw
        return proposal

    def as_typed(reasons, candidates=(), status=None):
        return Proposal(key_typed=query.key, typed_raw=query.raw, entry_type=kind, doi=typed.get("doi"),
                        status=status, issues=[r for r in reasons if r], candidates=list(candidates),
                        needs_decision=True)

    try:
        found = identify(query, client, cache)
    except ProviderError as exc:
        return as_typed([f"The lookup failed: a source did not answer ({exc}); the entry is left as typed"],
                        status=LOOKUP_FAILED)
    if found.record is None:
        return as_typed([found.note], found.candidates)
    replaced = None
    if found.published_for and typed.get("doi"):
        # The typed DOI is the preprint's. The published record is offered, never applied:
        # the DOI is shown as a question and the typed entry stays until the person decides.
        replaced = typed.pop("doi")
    try:
        if found.source == "arxiv":
            proposal = build_arxiv(typed, found.record)
        else:
            proposal = build(typed, found.record, found.corroborating)
    except CompletionRefused as exc:
        return as_typed([found.note, str(exc)], found.candidates)
    proposal.typed_raw = query.raw
    proposal.candidates = list(found.candidates)
    if found.note:  # a choice to make is an issue; how the record was found is a note
        (proposal.issues if found.candidates or found.published_for else proposal.notes).insert(0, found.note)
    if replaced:
        for index, change in enumerate(proposal.changes):
            if change.field == "doi":
                proposal.changes[index] = FieldChange("doi", replaced, change.proposed, change.source, "question")
    if found.candidates or found.published_for:
        proposal.needs_decision = True
    if proposal.proposed_raw is None:
        return proposal
    return checked(proposal, client, found.record if found.source == "arxiv" else None)
