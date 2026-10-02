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
