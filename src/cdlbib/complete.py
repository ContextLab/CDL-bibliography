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
from functools import lru_cache
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
# The fields an article must have before it can be accepted without a person's decision.
REQUIRED_FIELDS = ("author", "title", "journal", "year")
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
    duplicate_of: str | None = None
    key_proposed: str | None = None
    renames: dict[str, str] = field(default_factory=dict)
    unsupported: str | None = None
    needs_decision: bool = False  # True: never accepted without the person looking at it
    # True when the entry has a key and its required fields (author, title, journal, year)
    # and none of them is a question. ``build`` sets it; an entry that is not complete
    # always needs a decision.
    complete: bool = False
    notes: list[str] = field(default_factory=list)  # how the record was found; not a problem


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


# Words that no Title Case convention capitalises (APA, Chicago): they say nothing about
# how a title is cased.
_SMALL_WORDS = frozenset(
    "a an the and but or for nor on at to by of in as via vs per up off from with into onto over between "
    "through across during within without among after before under about against toward towards versus "
    "beyond around upon than".split())
# The banner some publishers put before the title of a retracted, withdrawn or removed
# article, once or twice over. It is not part of the title (Crossref: the original record's
# title is changed to carry it).
_BANNER_WORDS = (r"RETRACTED ARTICLE|Retracted Article|Retracted article|RETRACTED|Retracted|WITHDRAWN|Withdrawn"
                 r"|REMOVED|Removed")
_BANNER = re.compile(r"^(?:(?:\[(?:" + _BANNER_WORDS + r")\]\s*:?|(?:" + _BANNER_WORDS + r")\s*:)\s*)+")
# A title that announces a retraction rather than carrying a banner.
_NOTICE_TITLE = re.compile(r"^(?:Retraction|RETRACTION|Removal|Withdrawal)(?: [Nn]otice| NOTICE)?\s*:")
_DASHES = ("-", "--", "---", "\u2013", "\u2014")
# Abbreviations whose period does not end a sentence; a name may follow (Dr. Smith, St. Louis).
_ABBREVIATIONS = frozenset("st dr mr mrs ms prof vs jr sr etc al cf no vol fig ca approx".split())


def _small_words():
    """Words that are never names: the formatter's own list (uncaps.txt), with the words no
    Title Case convention capitalises (the formatter's list has no "a", "an", "at", "by")."""
    from .helpers import uncaps
    return _SMALL_WORDS | {word.lower() for word in uncaps}


def _core(word):
    """(leading punctuation, the word, trailing punctuation) of one space-separated token."""
    match = re.match(r"^(\W*)(.*?)(\W*)$", word, flags=re.S)
    return match[1], match[2], match[3]


def _position(words, index):
    """Where a word stands: "first"; after a "colon" (or a dash); after a sentence "end"
    (``?``, ``!``, or a period that is not an initial's or a known abbreviation's); or in
    "mid" sentence. After ``N.`` or ``Dr.`` or ``St.`` the sentence goes on (N. Burgess);
    after ``H.M.`` or ``U.S.`` it may or may not, so that is read as an end."""
    if index == 0:
        return "first"
    before = words[index - 1]
    if before.endswith(":") or before in _DASHES or before.endswith(("---", "\u2014", "\u2013")):
        return "colon"
    if before[-1:] in "?!":
        return "end"
    if before[-1:] == ".":
        token = before.strip("()[]{}\"'`")
        if re.fullmatch(r"[A-Za-z]\.", token) or token[:-1].lower() in _ABBREVIATIONS:
            return "mid"
        return "end"
    return "mid"


def _capital_evidence(text):
    """(words that could show the casing, how many of them are capitalised).

    Counted: every part of a word (hyphens split it) that is not the start of a sentence, not
    a small word, not a word the title formatter knows (caps.txt), and has no capital or
    digit after its first letter (an acronym or ``neoHebbian`` is the same in either casing)."""
    from .helpers import force_caps, remove_non_letters
    known = {word.lower() for word in force_caps}
    words = text.split(" ")
    informative = capitalised = 0
    for index, word in enumerate(words):
        start = _position(words, index) != "mid"
        for place, part in enumerate(re.split(r"[-\u2010\u2011/]", word)):
            core = _core(part)[1]
            if not core or not core[0].isalpha() or (start and place == 0):
                continue
            if core.lower() in _SMALL_WORDS or remove_non_letters(core.lower()) in known:
                continue
            if any(c.isupper() or c.isdigit() for c in core[1:]):
                continue
            if len(core) == 1 or (part.endswith(".") and core.lower() in _ABBREVIATIONS):
                continue  # an initial (J.) or an abbreviation (St., Dr.): capital in any casing
            informative += 1
            capitalised += core[0].isupper()
    return informative, capitalised


def _title_case(text):
    """Whether a title's capitals cannot be read as names: every word that could show the
    casing is capitalised, or half of them or more are, or the title has four words or fewer
    and one is. (A sentence-case title made only of names looks the same, and is asked about too.)"""
    informative, capitalised = _capital_evidence(text)
    return capitalised > 0 and (2 * capitalised >= informative or len(text.split(" ")) <= 4)


def _without_compound_capitals(text):
    """A Title Case title with its hyphenated ordinary words in lower case
    ("Feature-Based" -> "feature-based"), so the title helper does not read their two
    capitals as an acronym. A compound with an all-capital part (EEG-fMRI) is left alone."""
    return re.sub(r"(?<![\w-])[A-Z][a-z]+(?:-[A-Za-z][a-z]+)+(?![\w-])", lambda m: m[0].lower(), text)


def _protection(word):
    """[(character, inside braces)] of one built word, and the word without its braces."""
    out, depth = [], 0
    for char in word:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        else:
            out.append((char, depth > 0))
    return out


def _as_the_source_has_it(built, source, position, elsewhere=None):
    """One word of a sentence-case title: ``built`` is what the title helper made of it,
    ``source`` what the source printed, ``elsewhere`` the same word in a second sentence-case
    source when there is one. Returns (the word to write, a question or None).

    In mid-sentence a capital is the source's own, a name or an acronym: it is kept, in
    braces, exactly where the source has it, and a word is never given a capital because the
    same word has one elsewhere. The word "A" and a word the source has in lower case that
    the formatter's list spells with capitals (fmri -> {fMRI}) are the helper's.

    After a colon, a dash or a sentence end, a capital may be a name or only the start of
    the phrase. There:
      - a small word (``_small_words``) is the helper's: lower case after a colon or dash
        (the house rule), as printed after ``?``, ``!``, ``.``;
      - a word on the formatter's capitals list, or with a capital or digit inside it, is
        kept protected;
      - any other capitalised word is written in lower case when a second sentence-case
        source prints it in lower case (it is an ordinary word); otherwise it keeps the
        source's capital, in braces, and is a question that shows both forms."""
    marks = _protection(built)
    have = [c for c, _ in marks if c.isalpha()]
    want = [c for c in source if c.isalpha()]
    if [c.lower() for c in have] != [c.lower() for c in want] or not want:
        return built, None  # not the same letters (an escape, a removed period): the helper's word
    core = _core(source)[1]
    ordinary = core[:1].isupper() and not any(c.isupper() or c.isdigit() for c in core[1:])
    listed = "{" in built and have != [c.lower() for c in have]  # the formatter's list knows the word
    asked = None
    if core == "A" and position != "colon":
        return built, None
    if position in ("colon", "end") and ordinary:
        small = core.lower() in _small_words()
        if small and position == "end":
            return built, None
        if listed:
            return built, None
        if small or (elsewhere is not None and _core(elsewhere)[1] == core.lower()):
            text = iter(c.lower() for c in want)
            return "".join(next(text) if c.isalpha() else c for c, _ in marks), None
        asked = (f"title: {core!r} follows a colon, a dash or a sentence end; a name keeps its capital "
                 f"({{{core}}}), an ordinary word is written {core.lower()!r}")
        position = "mid"  # written as the source has it, protected, until the person decides
    if "{" in built and core.isalpha() and core.islower() and len(core) > 1:
        return built, None  # a one-letter word (k, m) is the source's own symbol, not the list's
    open_start = position in ("first", "end")  # a sentence's first letter needs no braces
    letters = [(c, inside) for c, inside in marks if c.isalpha()]
    kept = have == want and all(
        inside or not c.isupper() or (at == 0 and open_start) for at, (c, inside) in enumerate(letters))
    if kept:
        return built, asked
    plain = iter(want)
    text = "".join(next(plain) if c.isalpha() else c for c, _ in marks)
    if open_start and ordinary:
        return text, asked  # the sentence's first word, capitalised as the source has it
    lead, body, trail = _core(text)
    if position == "first" and core.islower() and core.isalpha():
        asked = f"title: the source begins with the lower-case word {core!r}; it is kept as the source has it"
    return lead + "{" + body + "}" + trail, asked


def _sentence_title(text, typed, other=None):
    """A sentence-case source title in house form, with the source's own capitals kept.
    ``other`` is a second sentence-case source's text of the same title, when there is one.
    Returns (title, questions); ``ValueError`` is the title helper's refusal."""
    built = cp.source_title(text, typed or "").split(" ")
    source = text.split(" ")
    if len(built) != len(source):
        raise ValueError("title: the built title does not line up with the source's words")
    second = other.split(" ") if other and len(other.split(" ")) == len(source) else None
    words, doubts = [], []
    for index, (made, printed) in enumerate(zip(built, source)):
        word, asked = _as_the_source_has_it(made, printed, _position(source, index),
                                            second[index] if second else None)
        words.append(word)
        doubts += [asked] if asked else []
    return " ".join(words), doubts


def _capitals_set_aside(title_case, sentence):
    """The words a source set aside as Title Case capitalises and the sentence-case source
    used instead does not, when the first is not capitalised throughout: its capitals may be
    names (``Recall in Boston schoolchildren`` beside ``Recall in boston schoolchildren``)."""
    informative, capitalised = _capital_evidence(title_case)
    one, two = title_case.split(" "), sentence.split(" ")
    if len(one) != len(two) or capitalised == informative and len(one) > 4:
        return []
    small = _small_words()
    return [_core(a)[1] for index, (a, b) in enumerate(zip(one, two))
            if index and a != b and a.lower() == b.lower() and _core(a)[1][:1].isupper()
            and _core(b)[1][:1].islower() and _core(a)[1].lower() not in small]


def _same_letters(one, two):
    """Whether two built titles have the same characters with the same capitals protected."""
    first, second = _protection(one), _protection(two)
    return ([c for c, _ in first] == [c for c, _ in second]
            and [inside for c, inside in first if c.isupper()] == [inside for c, inside in second if c.isupper()])


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
    # Capitals are only settled by a source that prints the title in sentence case: there
    # a capital in mid-sentence is a name or an acronym. A Title Case title capitalises
    # every word, so its capitals say nothing; the sentence-case candidate is a question.
    sentence = [text for text in (titles[0], second) if text and not _title_case(text)]
    try:
        if sentence:
            value, doubts = _sentence_title(sentence[0], typed, sentence[1] if len(sentence) == 2 else None)
            if len(sentence) == 2:
                other = _sentence_title(sentence[1], typed, sentence[0])[0]
                if not _same_letters(value, other):  # no rule says whose capitals are right
                    doubts = doubts + [f"title: the sources differ in capitals: crossref \"{titles[0]}\", "
                                       f"pubmed \"{second}\""]
            elif second:
                # The other source was set aside as Title Case. A capital only it has may
                # still be a name: asked about, never dropped without a word.
                aside = second if sentence[0] == titles[0] else titles[0]
                only = _capitals_set_aside(aside, sentence[0])
                if only:
                    doubts = doubts + ["title: one source capitalises " + ", ".join(repr(w) for w in only)
                                       + f" and the other does not: crossref \"{titles[0]}\", pubmed \"{second}\""]
        else:
            value = cp.source_title(_without_compound_capitals(titles[0]), typed or "")
            doubts = [CAPITALS_QUESTION]
    except ValueError as exc:
        raise _Hold(str(exc), values)
    value, more = _written("title", value, format_title)
    return _Value(value, "crossref+pubmed" if second else "crossref", values, doubts + more)


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
    raw non-ASCII letters in the library's LaTeX form. A DOI is never rewritten. When the
    formatter would not leave the LaTeX form alone, the typed value is returned unchanged
    (``_house_question`` then says so)."""
    from . import helpers
    formatter = {"title": helpers.format_title, "journal": helpers.format_journal_name,
                 "author": helpers.reformat_author}.get(name)
    if name == "doi":
        return value
    if name == "pages":
        return helpers.valid_pages(value)[1][1]
    formed = formatter(value) if formatter else value
    written = latex_text(formed)  # new text is written in the library's LaTeX form
    if formatter and formatter(written) != written:
        return value
    return written


def _house_question(name, value):
    """Why a typed value is kept although it is not in the library's LaTeX form, or None."""
    from . import helpers
    formatter = {"title": helpers.format_title, "journal": helpers.format_journal_name,
                 "author": helpers.reformat_author}.get(name)
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
    if typed.get("ID") == NO_KEY:  # the placeholder is not a key
        del typed["ID"]
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
    banner = next((_BANNER.match(t)[0].strip() for t in _source_titles(record, evidence) if _BANNER.match(t)), None)
    if retractions:  # decision log: retractions are flagged for the person; nothing automatic
        proposal.issues.append("The article was retracted (the retraction notice: " + ", ".join(retractions)
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
    asked = {c.field for c in proposal.changes if c.kind == "question"}
    proposal.complete = bool((proposal.key_typed or proposal.key_proposed)
                             and all(fields.get(name) and name not in asked for name in REQUIRED_FIELDS))
    if not proposal.complete:
        proposal.needs_decision = True
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
_DOI_PREFIX = re.compile(r"^(?:(?:https?://)?(?:dx\.|www\.)?doi\.org/|doi\s*:\s*|doi\s+)", re.I)
_ARXIV_LINK = re.compile(r"^(?:https?://)?(?:www\.)?(arxiv\.org/(?:abs|pdf)/[^?#\s]+?)(?:\.pdf)?(?:[?#]\S*)?$", re.I)
# The check the first layers of the verifier make is not the whole gate: said on every
# proposal whose status is not an accepted one.
FIRST_CHECK = ("This status comes from the first check only; `cdlbib verify` runs the full check and may "
               "still accept the entry.")
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
        doi, cut = _doi_read(text) if text else (None, "")
        if doi:
            said = [f"The DOI was read as {doi}: the final {cut!r} was taken as punctuation after it."] if cut else []
            return cls(doi=doi, author=author, year=year, notes=said)
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


def _abstract_signs(record, mapped=None):
    """Why a record deposited as a journal article may be a conference abstract, or None
    (house rule: a conference abstract is never the record). The project has no detector
    for this on a Crossref record (``sfn_abstracts`` works from a typed citation), so the
    signs are the three the owner named: the venue names abstracts or a meeting; the issue
    or volume is a supplement; or there is neither a page range nor an article number
    (the builder's ``_article_number`` says what an article number is). ``mapped``: the
    PubMed record for the same DOI, whose pages count when Crossref deposits none or only
    the first."""
    venues = record.get("container-title") if isinstance(record.get("container-title"), list) else []
    named = next((_text(v) for v in venues if isinstance(v, str)
                  and re.search(r"\b(?:abstracts?|meetings?)\b", v, re.I)), None)
    if named:
        return f"its venue is \"{named}\""
    for part in ("issue", "volume"):
        value = record.get(part)
        if isinstance(value, str) and re.search(r"suppl", value, re.I):
            return f"its {part} is a supplement ({_text(value)})"
    page = record.get("page") if isinstance(record.get("page"), str) else ""
    number = record.get("article-number") if isinstance(record.get("article-number"), str) else ""
    second = mapped.get("page") if mapped and isinstance(mapped.get("page"), str) else ""
    verdict = "it has no pages and no article number"
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
        verdict = f"it has one page ({pages}) and no article number"
    return verdict


def _abstract_note(record, mapped=None):
    sign = _abstract_signs(record, mapped) if record.get("type") == "journal-article" else None
    return (f"The record {record.get('DOI')} may be a conference abstract: {sign}. A conference abstract is not "
            "cited (house rule), so it is not taken without a decision.") if sign else None


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
    if len(raw["dois"]) > 1:
        return Identified(candidates=[listed], note=f"The PubMed record {pmid} has several DOIs ("
                          + ", ".join(raw["dois"]) + "); nothing was built from it")
    if not raw["dois"]:
        # PubMed gives no DOI: the entry is built from the PubMed record alone, in the
        # Crossref shape the verifier already reads it in, under PubMed's own journal title.
        record = medline_record(raw)
        record["container-title"] = record["container-title"][:1]
        return Identified(record=record, source="pubmed",
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


def _judged(fields, record, source, want_surname, want_year):
    """How a found record stands against the typed title, first author and year.

    ``strict``: the record is a journal article that shows no sign of being a conference
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
    # Only a journal article that does not look like a conference abstract is taken; any
    # other match is a candidate, with the reason.
    demoted = None
    if matches and record.get("type") != "journal-article":
        demoted = f"The record {record.get('DOI') or record.get('PMID')} is of type {record.get('type')}, not a journal article."
    elif matches:
        demoted = _abstract_note(record)
    return {"record": record, "source": source, "doi": record.get("DOI"), "demoted": demoted,
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
    # Every match counts when asking whether there is exactly one, also a match that is not
    # taken (another type, or the signs of a conference abstract).
    matched = _distinct_works([item for item in pool if item["match"]])
    if len(matched) == 1:
        item, listed = matched[0], [_summary(matched[0]["record"], matched[0]["source"])]
        if item["source"] != "crossref":
            return Identified(candidates=listed, note=f"The one record that matches {asked} is in PubMed only, "
                                                      "without a DOI; an entry is built from a Crossref record")
        if item["demoted"] and item["record"].get("type") != "journal-article":
            return Identified(candidates=listed, note=_notes(f"One record matches {asked}.", item["demoted"]))
        found = _from_doi(client, item["doi"])
        if found.record is None or found.decision:
            # Still with the signs of an abstract once PubMed's pages are known: a candidate.
            return Identified(candidates=listed, note=_notes(f"One record matches {asked}.", found.decision or found.note))
        found.note = _notes(f"One record matches {asked}: {item['doi']}.", found.note)
        return found
    if matched:
        listed = [_summary(item["record"], item["source"]) for item in matched[:SHORT_LIST]]
        demoted = [item["demoted"] for item in matched[:SHORT_LIST] if item["demoted"]]
        return Identified(candidates=listed,
                          note=_notes(f"{len(matched)} records match {asked}; one has to be chosen" + ("." if demoted else ""),
                                      *demoted))
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


def _set_complete(proposal, fields):
    """``Proposal.complete`` by ``build``'s rule (a key, and every required field there and
    not a question); an entry that is not complete needs a decision. ``build`` computes it
    inline, so the rule is repeated here, on the same ``REQUIRED_FIELDS``."""
    asked = {c.field for c in proposal.changes if c.kind == "question"}
    proposal.complete = bool((proposal.key_typed or proposal.key_proposed)
                             and all(fields.get(name) and name not in asked for name in REQUIRED_FIELDS))
    if not proposal.complete:
        proposal.needs_decision = True


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


def propose(query, client, cache):
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
        return as_typed([found.note] + query.notes, found.candidates)
    # A preprint DOI in a typed entry: the published record is offered, never applied. The
    # entry is built without the DOI (the builder fills nothing under a DOI that is not the
    # record's) and the typed DOI is then put back into the text, exactly as typed, with the
    # offered DOI shown as a question. A DOI given as a bare query is not an entry's text:
    # the offered DOI is then the candidate of a question with nothing typed.
    given = typed.get("doi") if found.published_for else None
    if given:
        typed.pop("doi")
    try:
        if found.source == "arxiv":
            proposal = build_arxiv(typed, found.record)
        else:
            proposal = build(typed, found.record, found.corroborating)
            if found.source == "pubmed":
                _renamed_pubmed(proposal)
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
    if given:
        offered = found.record.get("DOI")
        fields = _written_fields(proposal)
        if fields is None:  # the text cannot be rebuilt with the typed DOI in it: nothing is proposed
            return as_typed([found.note, "The proposed entry could not be written with the typed DOI kept"],
                            found.candidates)
        in_entry = bool(query.fields)
        fields["doi"] = given if in_entry else offered
        order = _field_order()
        proposal.changes = sorted(
            [c for c in proposal.changes if c.field != "doi" and c.kind != "dropped"]
            + [FieldChange("doi", given if in_entry else None, offered, "crossref", "question")],
            key=lambda c: order.index(c.field)) + [c for c in proposal.changes if c.kind == "dropped"]
        proposal.doi = fields["doi"]
        proposal.proposed_raw = render(proposal.entry_type, proposal.key_typed or proposal.key_proposed or NO_KEY,
                                       fields)
        _set_complete(proposal, fields)
    return checked(proposal, client, found.record if found.source == "arxiv" else None)
