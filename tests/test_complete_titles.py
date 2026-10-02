"""Entry completion, title capitalisation, judged on every article title of the library.

Each ``@article`` title of the frozen library (tests/fixtures/cdl-prewave1-2026-09-26.bib)
is turned back into what a publisher would send and given to ``cdlbib.complete.build`` as
the only source, three ways: in sentence case, and in Title Case by two conventions. The
built title must be the library's title, or the proposal must be a question for the person
(``needs_decision``). A built title that differs from the library's and is not a question is
an unflagged error; there must be none.

"The library's title" means the same characters, the same capitals, and the same capitals
protected by braces. Only brace style is ignored: which characters share a pair of braces
(``{Bayesian}`` or ``{B}ayesian``), how an accent is written, and how the library writes a
punctuation mark (``'`` for a curly apostrophe, ``--`` for an en dash).

Three kinds of difference are counted on their own and listed by key, not passed as equal:
  - ``first letter``: the library puts the title's very first capital in braces
    (``{N}eural correlates of…``); the builder does not, and no style changes that letter;
  - ``small word``: after a colon, a dash or a sentence end the library keeps a braced
    capital on a small word (``…: {A} review``, ``…? {T}he case``); the builder writes it as
    the title formatter does (lower case after a colon or dash, the house rule);
  - ``library unprotected``: a capital that the library's title leaves outside braces
    (``{EEG}-Informed``, ``Go/{No-Go}``), which BibTeX styles would lower-case; the builder
    protects it.

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


def _small():
    from cdlbib import helpers
    return complete._SMALL_WORDS | {word.lower() for word in helpers.uncaps}


def same(built, library):
    """"same", "first letter", "small word", "library unprotected" or "differs" (see the
    module's text). A title with several kinds is counted under the last that applies."""
    one, two = marked(built), marked(library)
    if len(one) != len(two):
        return "differs"
    text = "".join(c for c, _ in two)
    words = text.split(" ")
    small_word = unprotected = first = False
    for index, ((a, pa), (b, pb)) in enumerate(zip(one, two)):
        if a == b and (pa == pb or not a.isupper()):
            continue
        start, end = _word_bounds(text, index)
        word = text[start:end]
        place = complete._position(words, text[:start].count(" "))
        first_letter = index == next((i for i in range(start, end) if text[i].isalpha()), -1)
        if a == b and first_letter and start == 0 and pb and not pa:
            first = True
            continue
        if (first_letter and a.lower() == b.lower() and place in ("colon", "end")
                and word.strip("\"'`(),.;:?!").lower() in _small()):
            small_word = True
            continue
        if a == b and pa and not pb:
            unprotected = True
            continue
        return "differs"
    return ("library unprotected" if unprotected else "small word" if small_word
            else "first letter" if first else "same")


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
    """{"same": n, "small word": [...], "library unprotected": [...], "question": n, "unfilled": n,
    "first letter": [...], "errors": [...]} for one feed."""
    result = {"same": 0, "first letter": [], "small word": [], "library unprotected": [], "question": 0,
              "unfilled": 0, "errors": []}
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
        elif verdict in ("first letter", "small word", "library unprotected"):
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
    assert same("Neural correlates of memory", "{N}eural correlates of memory") == "first letter"
    assert same("Memory: a review", "Memory: {A} review") == "small word"
    assert same("Is it so? The case", "Is it so? {T}he case") == "small word"
    assert same("{EEG-Informed} {fMRI} reveals", "{EEG}-Informed {fMRI} reveals") == "library unprotected"
    # Whether a capital is protected is never brace style.
    assert same("Is it so? Maybe", "Is it so? {M}aybe") == "differs"
    assert same("Memory: evidence from sleep", "Memory: {E}vidence from sleep") == "differs"
    assert same("Comment on {N}. Burgess", "Comment on {N. Burgess}") == "differs"
    assert same("{EEG}-Informed {fMRI} reveals", "{EEG-Informed} {fMRI} reveals") == "differs"
    assert same("A hierarchical bayesian model", "A hierarchical {B}ayesian model") == "differs"
    assert same("A hierarchical {Bayesian} {M}odel", "A hierarchical {B}ayesian model") == "differs"
    assert same("Cognitive {Maps} beyond", "Cognitive maps beyond") == "differs"
    assert same("Seaborn: statistics", "{s}eaborn: statistics") == "differs"


def test_library_titles_with_a_name_after_an_initial_or_a_question_mark():
    """KahaEtal99b (``{J. O'Keefe} and {N. Burgess}``) and Boro01 (``? {M}andarin``): a period
    after an initial does not end the sentence, and a capital after ``?`` is asked about."""
    titles = dict(FED)
    for key in ("KahaEtal99b", "Boro01"):
        record = {"type": "journal-article", "DOI": "10.1000/corpus", "title": [sentence_case(titles[key])]}
        proposal = complete.build({"doi": "10.1000/corpus"}, record)
        change = next(c for c in proposal.changes if c.field == "title")
        assert same(change.proposed, titles[key]) == "same", (key, change.proposed)
    assert "{N. Burgess}" in titles["KahaEtal99b"] and "? {M}andarin" in titles["Boro01"]


# Measured on 2026-10-02 (the task report has the table). "question" is the noise: titles a
# person is asked about. The limits keep it from growing unnoticed.
@pytest.mark.parametrize("feed, most_questions", [
    ("sentence case", 292),  # under 5% of the titles
    ("Title Case, APA", len(FED)),
    ("Title Case, Chicago", len(FED)),
])
def test_every_library_title_comes_back_exact_or_as_a_question(feed, most_questions):
    result = run(feed)
    shown = "\n".join(f"{key}: library {title!r}, built {built!r}" for key, title, built in result["errors"][:40])
    assert not result["errors"], f"{len(result['errors'])} unflagged title errors on the {feed} feed:\n{shown}"
    assert result["question"] <= most_questions, (feed, result["question"])
