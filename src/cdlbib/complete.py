"""Entry completion: build a complete house-format entry from a source record.

``build`` is pure: it takes what the person typed, a Crossref-shaped record and, when there
is one, the DOI-linked PubMed record (``auto_review.epmc_record`` shape), and returns a
``Proposal``. It reads no file, makes no request, prints nothing and asks nothing.

Every value is produced by the existing house helpers (``correction_proposals``,
``helpers``, ``auto_review``); this module only decides which helper a field goes through
and what becomes of a refusal. A helper that refuses a value does not stop the build: the
field is left as typed (or absent) and listed in ``Proposal.unfilled`` with the helper's
reason and the values the sources gave.

What the person typed:
  - a typed value that no source contradicts is kept byte for byte (``kept``);
  - a typed value that a source contradicts is replaced in the proposed text and listed
    with both values (``changed``); the proposal is only ever written after an accept;
  - a surname the source spells differently is a ``question``: the typed spelling stays in
    the proposed text and the proposal needs a decision;
  - a field outside the house list, and ``publisher`` on an article, is ``dropped``.

Only journal articles are built. Any other type gives a proposal with ``unsupported`` set
and no proposed text. A record that is itself a correction or retraction notice is refused
(``CompletionRefused``).
"""

from dataclasses import dataclass, field
import re

from . import correction_proposals as cp
from .auto_review import compatible_authors, expanded_pages, safe_compare
from .correction_proposals import _fold  # accent- and case-folded text, as the surname rules use
from .errors import CompletionRefused
from .verification import CORRECTION_FLAG, normalize_doi, normalize_journal, print_year_selects_cited, split_authors

# The key written when neither a typed key nor the authors and year are there to make one.
NO_KEY = "KeyNeeded"

# The fields built from a source record, in the order they are settled (the layout's order).
BUILT_FIELDS = ("author", "doi", "journal", "number", "pages", "title", "volume", "year")

# Crossref ``update-to`` types that make a record a notice about another work.
NOTICE_WORDS = ("errat", "corrig", "correct", "retract", "withdraw", "concern", "removal")

# A page locator the pagination rules accept (correction_proposals.single_source_proposal).
_PAGES = re.compile(r"[a-z]{0,3}\d+(?:-[a-z]{0,3}\d+(?:\.e\d+)?)?")


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
    needs_decision: bool = False


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


_HELPER_ERRORS = (ValueError, KeyError, TypeError, AttributeError, IndexError)


def _text(value):
    """A registry string on one line (a deposited line break is white space)."""
    return " ".join(str(value or "").split())


def _people_text(people):
    return "; ".join(_text(p.get("name")) or _text(f"{p.get('given') or ''} {p.get('family') or ''}")
                     for p in people or [])


def _source_titles(record, evidence):
    """The record's title(s) as the comparator reads them (a split subtitle joined on)."""
    if "title" in evidence:
        return [_text(t) for t in evidence["title"]["source"]]
    return [_text(t) for t in record.get("title") or [] if isinstance(t, str)]


def _title(record, mapped, typed, evidence, unsupported):
    from .helpers import format_title
    if "title" not in evidence:
        raise _Hold(unsupported or "title: the source record has no usable title")
    titles = _source_titles(record, evidence)
    if len(titles) != 1:
        raise _Hold("title: several source titles" if titles else "title: the source states no title",
                    {"crossref": "; ".join(titles)} if titles else {})
    values = {"crossref": titles[0]}
    second = _text((mapped.get("title") or [""])[0]) if mapped else ""
    if second:
        values["pubmed"] = second
        if cp.normalize_title_safe(second) != cp.normalize_title_safe(titles[0]):
            raise _Hold("title: sources disagree", values, disagreement=True)
    try:
        value = cp.source_title(titles[0], typed or "")
    except _HELPER_ERRORS as exc:
        raise _Hold(str(exc), values)
    if second:
        # The two sources state the same title. When they print it in different case, the
        # text with fewer capitals is used: a registry title in Title Case would otherwise
        # have every word with two capitals ("Feature-Based") kept in braces as an acronym.
        try:
            other = cp.source_title(second, typed or "")
        except _HELPER_ERRORS:
            other = None
        if (other and other != value and other.count("{") < value.count("{")
                and re.sub(r"[{}]", "", other).lower() == re.sub(r"[{}]", "", value).lower()):
            value = other
    if format_title(value) != value:
        raise _Hold("title: the title formatter changes the built title", values)
    return value, "crossref+pubmed" if second else "crossref", values


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
    except _HELPER_ERRORS as exc:
        raise _Hold(str(exc), values)
    if source == "crossref" and mapped and mapped.get("author"):
        values["pubmed"] = _people_text(mapped["author"])
        if not compatible_authors({"author": people}, mapped):
            raise _Hold("author: sources disagree", values, disagreement=True)
        source = "crossref+pubmed"
    if reformat_author(value) != value:
        raise _Hold("author: the author formatter changes the built byline", values)
    return value, source, values


def _journal(record):
    from .helpers import format_journal_name
    venues = [_text(v) for v in record.get("container-title") or [] if _text(v)]
    if not venues:
        return None
    values = {"crossref": "; ".join(venues)}
    if len(venues) != 1 or re.search(r"[<>{}\\$]", venues[0]):
        raise _Hold("journal: no single registry venue", values)
    value = format_journal_name(cp.journal_text(venues[0]))
    try:
        same = normalize_journal(value) == normalize_journal(venues[0])
    except _HELPER_ERRORS:
        same = False
    if not same:
        raise _Hold("journal: formatter changes the venue", values)
    return value, "crossref", values


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
    return value, source, values


def _number(record, mapped):
    """The issue, only when a source states it (correction_proposals.confirm_issue)."""
    values = dict(cp.issue_statements(record, mapped))
    try:
        decision = cp.confirm_issue(record, mapped, None)
    except cp.IssueLookupRequired:
        return None  # no record at hand states an issue: none is written
    except ValueError as exc:
        raise _Hold(str(exc), values, disagreement=len(values) > 1)
    return decision["issue"], "+".join(decision["sources"]), values


def _pages(record, mapped):
    raw, source = _text(record.get("page") or record.get("article-number")), "crossref"
    second = _text(mapped.get("page")) if mapped else ""
    if not raw and second:
        raw, source = second, "pubmed"
    if not raw:
        return None
    values = {source: raw}
    if source == "crossref" and second:
        values["pubmed"] = second
    try:
        pages = expanded_pages(raw)
        other = expanded_pages(second) if second else ""
    except _HELPER_ERRORS as exc:
        raise _Hold("pages: " + str(exc), values)
    if not _PAGES.fullmatch(pages):
        raise _Hold("pages: unsupported source locator", values)
    if source == "crossref" and second:
        if other != pages:
            raise _Hold("pages: sources disagree", values, disagreement=True)
        source = "crossref+pubmed"
    return pages.replace("-", "--"), source, values


def _year(record, mapped, evidence):
    """The year of the printed issue. One year in the record: that year. Print and online
    years that differ: the print year when the DOI-linked PubMed record gives the same year
    (``issue_year_proposal``'s rule), or when the online date is a later digitisation of a
    backfile (``verification.print_year_selects_cited``); otherwise nothing is chosen."""
    years = list(evidence.get("year", {}).get("source") or [])
    values = {}
    for name in ("published-print", "published-online", "issued", "published"):
        for parts in (record.get(name) or {}).get("date-parts") or []:
            if parts and parts[0] is not None:
                values["crossref " + name] = str(parts[0])
    second = ""
    if mapped:
        try:
            second = str(mapped["published"]["date-parts"][0][0])
        except _HELPER_ERRORS:
            second = ""
        if second:
            values["pubmed"] = second
    if not years:
        return (second, "pubmed", values) if second else None
    if len(years) == 1:
        if second and second != years[0]:
            raise _Hold("year: sources disagree", values, disagreement=True)
        return years[0], "crossref+pubmed" if second else "crossref", values
    prints = [str(p[0]) for p in (record.get("published-print") or {}).get("date-parts") or [] if p]
    if len(prints) == 1 and re.fullmatch(r"[1-9]\d{3}", prints[0]):
        if second:
            if second == prints[0]:
                return prints[0], "crossref+pubmed", values
            raise _Hold("year: sources disagree", values, disagreement=True)
        probe = {"ENTRYTYPE": "article", "year": prints[0], "volume": str(record.get("volume") or ""),
                 "pages": str(record.get("page") or record.get("article-number") or "")}
        if print_year_selects_cited(probe, record):
            return prints[0], "crossref", values
    raise _Hold("year: print and online years differ and no rule selects one", values)


def _refuse_notice(record):
    """A record that is a correction, erratum or retraction notice is never the record."""
    for update in record.get("update-to") or []:
        kind = str((update or {}).get("type") or "")
        if any(word in kind.lower().replace("_", " ") for word in NOTICE_WORDS):
            raise CompletionRefused(
                f"The record {record.get('DOI')} is a {kind.replace('_', ' ')} of {update.get('DOI')}, "
                "not the article itself; cite the article")


def _surnames(byline):
    from .name_parsing import splitname
    out = set()
    for name in split_authors(byline or ""):
        try:
            if name.startswith("{"):
                out.add(_fold(name))
            else:
                parts = splitname(name, strict_mode=True)
                out.add(_fold(" ".join(parts["von"] + parts["last"])))
        except _HELPER_ERRORS:
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
        people = record.get("author") or []
        try:
            theirs = {_fold(p.get("family") or p.get("name") or "") for p in people} - {""}
        except _HELPER_ERRORS:
            theirs = set()
        if people and not (_surnames(author) & theirs):
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


def build(typed_fields, record, corroborating=None):
    """Propose a complete ``@article`` entry for ``record``.

    ``typed_fields``: the entry as typed, by lower-case field name, with ``ENTRYTYPE`` and
    ``ID`` when there are any (``{"doi": ...}`` alone is enough). ``record``: the Crossref
    record of the work. ``corroborating``: the PubMed record for the same DOI in the shape
    ``auto_review.epmc_record`` returns, or None.

    Raises ``CompletionRefused`` when the record is a correction or retraction notice.
    """
    from .helpers import authors2key
    typed = {(k if k in ("ENTRYTYPE", "ID") else k.lower()): v for k, v in typed_fields.items()
             if v is not None and str(v) != ""}
    kind = str(typed.get("ENTRYTYPE") or "article").lower()
    proposal = Proposal(key_typed=typed.get("ID") or None, entry_type=kind, record_source="crossref",
                        doi=typed.get("doi") or record.get("DOI"))
    if kind != "article":
        proposal.unsupported = kind
        proposal.issues.append(f"An entry of type {kind} is not built automatically; the entry is left as typed")
        return proposal
    if record.get("type") != "journal-article":
        proposal.unsupported = str(record.get("type"))
        proposal.issues.append(
            f"A record of type {record.get('type')} is not built automatically; the entry is left as typed")
        return proposal
    _refuse_notice(record)

    mapped = corroborating
    if mapped is not None:
        try:
            same = normalize_doi(mapped.get("DOI") or "") == normalize_doi(record.get("DOI") or "")
        except _HELPER_ERRORS:
            same = False
        if same:
            proposal.record_source = "crossref+pubmed"
        else:
            mapped = None
            proposal.issues.append("The PubMed record is for another DOI and was not used")

    # A supplied DOI is never replaced: a record with another DOI fills nothing.
    record_doi = str(record.get("DOI") or "")
    if typed.get("doi"):
        try:
            same = normalize_doi(typed["doi"]) == normalize_doi(record_doi)
        except _HELPER_ERRORS:
            same = False
        if not same:
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
                questions[name] = (outcome[0] if outcome else None, outcome[1] if outcome else "crossref")
        return _as_typed(proposal, typed, kind, questions)

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
    for name in BUILT_FIELDS:
        had = typed.get(name)
        if name == "doi":
            if had:
                fields[name] = had
                proposal.changes.append(FieldChange(name, had, had, "typed", "kept"))
            elif record_doi:
                try:
                    fields[name] = normalize_doi(record_doi)
                    proposal.changes.append(FieldChange(name, None, fields[name], "crossref", "filled"))
                except _HELPER_ERRORS as exc:
                    proposal.unfilled.append(Unfilled(name, str(exc), {"crossref": record_doi}))
            continue
        try:
            outcome = makers[name]()
        except _Hold as hold:
            if had:
                fields[name] = had
                proposal.changes.append(FieldChange(name, had, had, "typed", "kept"))
                if hold.disagreement or not evidence.get(name, {}).get("match"):
                    proposal.unfilled.append(Unfilled(name, hold.reason, hold.values))
            else:
                proposal.unfilled.append(Unfilled(name, hold.reason, hold.values))
            continue
        if outcome is None:
            if had:  # no source states it: left as typed, and said so
                fields[name] = had
                proposal.changes.append(FieldChange(name, had, had, "typed", "kept"))
                proposal.unfilled.append(Unfilled(name, f"{name}: no source record states it", {}))
            continue
        value, source, values = outcome
        if not had:
            fields[name] = value
            proposal.changes.append(FieldChange(name, None, value, source, "filled"))
            continue
        # The year is the print year by rule, so only the same year counts as agreement.
        agrees = value == had or (name != "year" and evidence.get(name, {}).get("match"))
        if agrees:
            fields[name] = had
            proposal.changes.append(FieldChange(name, had, had, "typed", "kept"))
            continue
        reason = None
        if name == "author":
            hold = cp.surname_change_hold(proposal.key_typed, had, value, source=source)
            if hold:  # a surname respelling is always the person's to decide
                fields[name] = had
                proposal.changes.append(FieldChange(name, had, value, source, "question"))
                proposal.issues.append(hold)
                proposal.needs_decision = True
                continue
            people = record.get("author") or (mapped or {}).get("author") or []
            if cp.byline_loses_detail(had, people):
                reason = "author: citation byline has detail the source lacks"
        if name == "pages" and cp.shortens_pages(had, value):
            reason = "pages: the source would shorten the cited range"
        if reason is None and cp.loses_characters(had, value, name):
            reason = f"{name}: source value drops accents or has a replacement character"
        if reason:
            fields[name] = had
            proposal.changes.append(FieldChange(name, had, had, "typed", "kept"))
            proposal.unfilled.append(Unfilled(name, reason, values))
            continue
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
            fields[name] = typed[name]
            proposal.changes.append(FieldChange(name, typed[name], typed[name], "typed", "kept"))
        else:
            dropped.append(FieldChange(name, typed[name], None, "not a house field", "dropped"))
    order = _field_order()
    proposal.changes.sort(key=lambda c: order.index(c.field))
    proposal.changes += dropped

    if fields.get("author") and fields.get("year"):
        try:
            proposal.key_proposed = authors2key(fields["author"], fields["year"])
        except Exception:  # authors2key raises bare Exception on a byline it cannot key
            proposal.key_proposed = None
    if not proposal.key_typed and not proposal.key_proposed:
        proposal.unfilled.append(Unfilled("ID", "a key needs the authors and the year", {}))
    proposal.doi = fields.get("doi") or proposal.doi
    proposal.proposed_raw = render(kind, proposal.key_typed or proposal.key_proposed or NO_KEY, fields)
    return proposal
