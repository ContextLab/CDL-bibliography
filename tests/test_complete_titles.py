"""Entry completion, title capitalisation, judged on every article title of the library.

Each ``@article`` title of the frozen library (tests/fixtures/cdl-prewave1-2026-09-26.bib)
is turned back into what a publisher would send and given to ``cdlbib.complete.build`` as
the only source, three ways: in sentence case, and in Title Case by two conventions. The
built title must be the library's title, or the proposal must be a question for the person
(``needs_decision``). A built title that differs from the library's and is not a question is
an unflagged error; there must be none.

"The library's title" means the same characters with the same capitals and the same capitals
protected by braces. These do not count as differences (``same`` below):
  - brace style: ``{Bayesian}`` or ``{B}ayesian``, and how an accent is written;
  - whether the capital that begins a sentence (the title's first letter, or the letter after
    ``?``, ``!`` or ``.``) is in braces;
  - the word ``A``, which the title formatter leaves as it finds it;
and one is counted on its own (``colon rule``): the house rule writes the word after a colon
or a dash in lower case (correction_proposals.source_title, helpers.format_title), while the
frozen library keeps a capital there in some titles (``…: {E}vidence from``, ``…: {A} review``).
The builder follows the house rule; a title that differs from the library's only in that
letter is counted under ``colon rule`` and listed in the task report, not as an error.
Another is counted on its own (``library unprotected``): a capital in mid-sentence that the
library's title leaves outside braces (``{EEG}-Informed``, ``Go/{No-Go}``), which BibTeX
styles would lower-case; the builder protects it.

No network; no test reads the live cdl.bib.
"""
from pathlib import Path
import re
import unicodedata

import pytest

from cdlbib import complete

ROOT = Path(__file__).resolve().parents[1]
FROZEN = (ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib").read_text(encoding="utf-8")

_COMBINING = {'"': "̈", "'": "́", "`": "̀", "^": "̂", "~": "̃", "=": "̄",
              ".": "̇", "c": "̧", "v": "̌", "u": "̆", "H": "̋", "r": "̊",
              "k": "̨", "d": "̣", "b": "̱"}
_LETTERS = {"o": "ø", "O": "Ø", "l": "ł", "L": "Ł", "ss": "ß", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
            "aa": "å", "AA": "Å", "i": "ı"}
_ACCENT = re.compile(
    r"\{\\([\"'`^~=.])\{\\?([A-Za-z])\}\}|\{\\([\"'`^~=.])\\?([A-Za-z])\}"
    r"|\\([\"'`^~=.])\{\\?([A-Za-z])\}|\\([\"'`^~=.])([A-Za-z])"
    r"|\{\\([cvuHrkdb])\{([A-Za-z])\}\}|\{\\([cvuHrkdb]) ([A-Za-z])\}|\\([cvuHrkdb])\{([A-Za-z])\}")
_LETTER = re.compile(r"\{\\(o|O|l|L|ss|ae|AE|oe|OE|aa|AA|i)\}|\\(o|O|l|L|ss|ae|AE|oe|OE|aa|AA|i)\{\}")


def unicode_text(title):
    """A library title with its LaTeX accents and letters as Unicode characters and
    ``\\&``-style escapes as the plain character; braces that protect case are kept."""
    def accent(match):
        command, letter = [g for g in match.groups() if g is not None]
        return unicodedata.normalize("NFC", letter + _COMBINING[command])
    text = _ACCENT.sub(accent, title)
    text = _LETTER.sub(lambda m: _LETTERS[m[1] or m[2]], text)
    return re.sub(r"\\([&%#_])", r"\1", text)


# How the library writes punctuation that a publisher sends as one character.
_PUNCTUATION = {"\u2019": "'", "\u2018": "`", "\u201c": "``", "\u201d": "''", "\u2013": "--", "\u2014": "---",
                "\u2010": "-", "\u2011": "-", "\u00a0": " ", "\u2009": " "}


def marked(title):
    """[(character, protected by braces)] of a title, braces removed."""
    out, depth = [], 0
    for char in "".join(_PUNCTUATION.get(c, c) for c in unicode_text(title)):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        else:
            out.append((char, depth > 0))
    return out


def _word_bounds(chars, index):
    start = index
    while start > 0 and chars[start - 1] != " ":
        start -= 1
    end = index
    while end < len(chars) and chars[end] != " ":
        end += 1
    return start, end


def same(built, library):
    """"same", "colon rule", "library unprotected" or "differs" (see the module's text)."""
    one, two = marked(built), marked(library)
    if len(one) != len(two):
        return "differs"
    text = "".join(c for c, _ in two)
    colon = unprotected = False
    for index, ((a, pa), (b, pb)) in enumerate(zip(one, two)):
        if a == b and (pa == pb or not a.isupper()):
            continue
        start, end = _word_bounds(text, index)
        word = text[start:end]
        before = text[:start].rstrip()
        first_letter = index == next((i for i in range(start, end) if text[i].isalpha()), -1)
        if a == b and (word.strip("\"'`(),.;:?!") == "A" or (first_letter and (not before or before[-1] in "?!."))):
            continue  # the word "A"; a sentence's first capital, in braces or not
        if (first_letter and a.lower() == b.lower() and before and (before[-1] == ":" or before.endswith("-"))
                and not any(c.isupper() for c in text[index + 1:end])):
            colon = True  # the house rule: lower case after a colon or a dash
            continue
        if a == b and pa and not pb:
            unprotected = True  # a mid-sentence capital the library leaves outside braces
            continue
        return "differs"
    return "colon rule" if colon else "library unprotected" if unprotected else "same"


ARTICLE_TITLES = [(key, re.search(r"(?m)^\tTitle = \{(.*)\}[,}]?$", body))
                  for key, body in re.findall(r"(?ms)^@article\{([^,]+),\n(.*?)\}\}$", FROZEN)]
ARTICLE_TITLES = [(key, match[1]) for key, match in ARTICLE_TITLES if match]
# A title with other LaTeX (math, \texttt, \textsuperscript) has no plain publisher's form.
FED = [(key, title) for key, title in ARTICLE_TITLES if not re.search(r"[\\$]", unicode_text(title))]

_APA_SMALL = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "by", "of", "in", "as", "via",
              "vs", "per", "up", "off"}
_CHICAGO_SMALL = _APA_SMALL | {
    "from", "with", "into", "onto", "over", "between", "through", "across", "during", "within", "without",
    "among", "after", "before", "under", "about", "against", "toward", "towards", "versus", "beyond", "around",
    "upon", "than"}


def sentence_case(title):
    return re.sub(r"[{}]", "", unicode_text(title))


def title_case(title, small):
    """The title as a publisher prints it in Title Case: every word capitalised but the
    small ones, a word after a hyphen too; words that already have a capital are left."""
    out, first = [], True
    for word in sentence_case(title).split(" "):
        if (first or word.lower().strip("(:,") not in small) and word.islower():
            at = next((i for i, c in enumerate(word) if c.isalpha()), None)
            if at is not None:
                word = word[:at] + word[at].upper() + word[at + 1:]
            word = re.sub(r"-([a-z])", lambda m: "-" + m[1].upper(), word)
        out.append(word)
        first = word.endswith((":", "?"))
    return " ".join(out)


FEEDS = {
    "sentence case": sentence_case,
    "Title Case, APA": lambda title: title_case(title, _APA_SMALL),
    "Title Case, Chicago": lambda title: title_case(title, _CHICAGO_SMALL),
}


def run(feed):
    """{"same": n, "colon rule": [...], "question": n, "unfilled": n, "errors": [...]} for one feed."""
    result = {"same": 0, "colon rule": [], "library unprotected": [], "question": 0, "unfilled": 0, "errors": []}
    for key, title in FED:
        record = {"type": "journal-article", "DOI": "10.1000/corpus", "title": [FEEDS[feed](title)]}
        proposal = complete.build({"doi": "10.1000/corpus"}, record)
        change = [c for c in proposal.changes if c.field == "title"]
        if not change:
            result["unfilled"] += 1  # the title helper refused the source; nothing is written
            continue
        verdict = same(change[0].proposed, title)
        if change[0].kind == "question":
            assert proposal.needs_decision
            result["question"] += 1
        elif verdict == "same":
            result["same"] += 1
        elif verdict in ("colon rule", "library unprotected"):
            result[verdict].append(key)
        else:
            result["errors"].append((key, title, change[0].proposed))
    return result


def test_the_corpus_is_every_article_title_of_the_frozen_library():
    assert len(ARTICLE_TITLES) == 5868
    assert len(FED) == 5838  # 30 titles hold other LaTeX (math, \texttt, a superscript)


def test_the_comparison_tells_brace_style_from_a_real_difference():
    assert same("A hierarchical {Bayesian} model", "A hierarchical {B}ayesian model") == "same"
    assert same('Gl{\\"o}ckner and Gl\\"{o}ckner', 'Gl{\\"{o}}ckner and Gl{\\"o}ckner') == "same"
    assert same("Is it so? Maybe", "Is it so? {M}aybe") == "same"
    assert same("Memory: evidence from sleep", "Memory: {E}vidence from sleep") == "colon rule"
    assert same("Memory: a review", "Memory: {A} review") == "colon rule"
    assert same("A hierarchical bayesian model", "A hierarchical {B}ayesian model") == "differs"
    assert same("A hierarchical {Bayesian} {M}odel", "A hierarchical {B}ayesian model") == "differs"
    assert same("Cognitive {Maps} beyond", "Cognitive maps beyond") == "differs"
    assert same("{EEG-Informed} {fMRI} reveals", "{EEG}-Informed {fMRI} reveals") == "library unprotected"
    assert same("{EEG}-Informed {fMRI} reveals", "{EEG-Informed} {fMRI} reveals") == "differs"
    assert same("Seaborn: statistics", "{s}eaborn: statistics") == "differs"


# Measured on 2026-10-02 (the task report has the table). "question" is the noise: titles a
# person is asked about. The limits keep it from growing unnoticed.
@pytest.mark.parametrize("feed, most_questions", [
    ("sentence case", 40),
    ("Title Case, APA", len(FED)),
    ("Title Case, Chicago", len(FED)),
])
def test_every_library_title_comes_back_exact_or_as_a_question(feed, most_questions):
    result = run(feed)
    shown = "\n".join(f"{key}: library {title!r}, built {built!r}" for key, title, built in result["errors"][:40])
    assert not result["errors"], f"{len(result['errors'])} unflagged title errors on the {feed} feed:\n{shown}"
    assert result["question"] <= most_questions, (feed, result["question"])
