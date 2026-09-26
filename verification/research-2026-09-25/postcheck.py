"""Deterministic post-check for the agent research route (2026-09-25).

Usage: postcheck.py <wave folder> [--bib PATH|HEAD] [--review PATH] [--offline]
       postcheck.py --write-removals

Reads every batch-*.json in the wave folder (schema:
verification/research-pilot-2026-09-24/PROTOCOL.md), the folder's validation.json
(quote checks, optional) and review.json (independent review, optional), and the
current cdl.bib (default: the committed HEAD version, so half-written edits by
other sessions never leak in). Writes two files into the wave folder:

- postcheck.json: per key the flags, normalisations, final proposed changes,
  key plan (rename / duplicate / collision), DOI status, plus a summary and the
  review measurement (how many reviewer findings the rules alone catch).
- merged.json: final proposals for the user's review page (key, current fields,
  final changes with evidence and provenance, verdict, flags, reviewer agreement).

Nothing is written to cdl.bib. The rules are documented in POSTCHECK.md next to
this file. Network responses (doi.org, Crossref, DataCite) are cached under
.bibcheck/research-postcheck/ and requests are paced, so a repeat run makes no
requests.
"""
import argparse
import difflib
import hashlib
import html
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse

import certifi

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".bibcheck/research-postcheck"
SSL = ssl.create_default_context(cafile=certifi.where())
UA = "CDL-bibliography research post-check (https://github.com/ContextLab/CDL-bibliography)"
PACE = 0.4  # seconds between network requests
RETRIES = 4  # retries of a rate-limited request (HTTP 429/503) before giving up
BACKOFF = 5.0  # seconds before the first retry when the server sends no Retry-After
MAX_WAIT = 120.0  # longest single wait, whatever Retry-After asks for

_cwd = os.getcwd()
sys.path.insert(0, str(ROOT / "bibcheck"))
os.chdir(ROOT)  # helpers reads its word lists relative to the working directory
try:
    import helpers as H  # noqa: E402
finally:
    os.chdir(_cwd)

GIT_ENV = dict(os.environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools")

BIBTEX_TYPES = {"article", "book", "booklet", "inbook", "incollection", "inproceedings",
                "manual", "mastersthesis", "misc", "phdthesis", "proceedings",
                "techreport", "unpublished", "patent"}
NAME_FIELDS = ("author", "editor")
IDENTITY_FIELDS = ("title", "year", "doi", "journal", "booktitle")  # held together on an ambiguous verdict
JUNK_FIELDS = ("force",)  # never a BibTeX field: always removed (AbdeEtal21, LiEtal24b, Amer23b 'Force = {True}')
CONTAINED_TYPES = ("inproceedings", "incollection", "inbook")
ORDINAL_FIELDS = ("title", "booktitle", "journal", "edition", "series", "publisher",
                  "organization", "howpublished", "note", "school", "institution")
SUFFIX_RE = re.compile(r"(?:,?\s+|,\s*)(?:Jr|Sr|II|III|IV)\.?(\}?)$")
PROCEEDINGS_RE = re.compile(r"proceedings|conference|meeting|workshop|symposium|congress|"
                            r"advances in neural information processing systems", re.I)

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    # catalogue (AACR2) abbreviations
    "ala": "AL", "ariz": "AZ", "ark": "AR", "calif": "CA", "cal": "CA", "colo": "CO",
    "conn": "CT", "del": "DE", "d.c": "DC", "fla": "FL", "ga": "GA", "ill": "IL",
    "ind": "IN", "kan": "KS", "kans": "KS", "ky": "KY", "la": "LA", "md": "MD",
    "mass": "MA", "mich": "MI", "minn": "MN", "miss": "MS", "mo": "MO", "mont": "MT",
    "neb": "NE", "nebr": "NE", "nev": "NV", "n.h": "NH", "n.j": "NJ", "n.m": "NM",
    "n.y": "NY", "n.c": "NC", "n.d": "ND", "okla": "OK", "or": "OR", "ore": "OR",
    "pa": "PA", "r.i": "RI", "s.c": "SC", "s.d": "SD", "tenn": "TN", "tex": "TX",
    "vt": "VT", "va": "VA", "wash": "WA", "w.va": "WV", "wis": "WI", "wyo": "WY",
}
US_CODES = set(US_STATES.values())
# Cities whose state is unambiguous, for "City, United States" addresses that
# cdl.bib has no precedent for. cdl.bib's own "City, {ST}" addresses are used first.
US_CITIES = {
    "seattle": "WA", "boston": "MA", "cambridge": "MA", "new york": "NY", "chicago": "IL",
    "los angeles": "CA", "san francisco": "CA", "san diego": "CA", "long beach": "CA",
    "vancouver": "WA", "austin": "TX", "houston": "TX", "dallas": "TX", "denver": "CO",
    "philadelphia": "PA", "pittsburgh": "PA", "baltimore": "MD", "atlanta": "GA",
    "miami": "FL", "orlando": "FL", "new orleans": "LA", "minneapolis": "MN",
    "salt lake city": "UT", "portland": "OR", "honolulu": "HI", "las vegas": "NV",
    "phoenix": "AZ", "washington": "DC", "hillsdale": "NJ", "mahwah": "NJ",
    "princeton": "NJ", "hanover": "NH", "ann arbor": "MI", "madison": "WI",
    "st. louis": "MO", "nashville": "TN", "stanford": "CA", "berkeley": "CA",
    "palo alto": "CA", "cold spring harbor": "NY", "hoboken": "NJ", "waltham": "MA",
}
ORDINAL_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
                 "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303",
           "=": "\u0304", ".": "\u0307", "c": "\u0327", "v": "\u030c", "u": "\u0306",
           "H": "\u030b", "k": "\u0328", "r": "\u030a"}
SPECIAL = {"l": "l", "L": "L", "o": "o", "O": "O", "ss": "ss", "ae": "ae", "AE": "AE",
           "oe": "oe", "OE": "OE", "aa": "a", "AA": "A", "i": "i", "j": "j"}
SYMBOL_MACROS = {"textregistered": "®", "texttrademark": "™", "textcopyright": "©",
                 "pm": " ± "}
# Greek letters compare as their names: Crossref 'PLCβ1' = the entry's '{PLC}$\beta$1' (HernEtal00)
GREEK = {c: f" {n} " for c, n in zip(
    "αβγδεζηθικλμνξπρστυφχψω",
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi pi rho sigma tau upsilon phi chi psi "
    "omega".split())}


# ---------------------------------------------------------------- text folding

def delatex(text):
    """LaTeX accents and special letters to plain Unicode letters."""
    text = re.sub(r"\\(['`^\"~=.])\s*\{?([A-Za-z])\}?",
                  lambda m: unicodedata.normalize("NFC", m[2] + ACCENTS[m[1]]), text)
    text = re.sub(r"\\([cvuHkr])\s*\{([A-Za-z])\}",
                  lambda m: unicodedata.normalize("NFC", m[2] + ACCENTS[m[1]]), text)
    text = re.sub(r"(\d+)\\textsuperscript\{([a-z]+)\}", r"\1\2", text)
    # symbol macros as the registries print them (GusmEtal14 'FitBit{\textregistered}' =
    # Crossref 'FitBit®'; LismIdia95 '$7\pm2$' = '7 ± 2')
    for macro, symbol in SYMBOL_MACROS.items():
        text = re.sub(r"\{?\\" + macro + r"(?![A-Za-z])\}?\s*", symbol, text)
    # font commands keep their text: 'genus \textit{Cataglyphis}' -> 'genus Cataglyphis'
    text = re.sub(r"\\(?:textit|emph|textbf|textsc|textsl|textup|textrm|mathit|mathrm|it|em|bf)\b\s*", "", text)
    for macro, letter in SPECIAL.items():
        text = re.sub(r"\{\\" + macro + r"\}", letter, text)
        text = re.sub(r"\\" + macro + r"(?![A-Za-z])\s?", letter, text)
    text = re.sub(r"\\url\{([^}]*)\}", r"\1", text)
    return text.replace("{", "").replace("}", "")


def fold(text):
    """Case-, accent-, brace- and punctuation-insensitive comparison form."""
    text = delatex(html.unescape(str(text or "")))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = "".join(GREEK.get(c, c) for c in text.casefold())
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def titles_match(a, b):
    """Same title: equal after folding, or one is the other plus a subtitle."""
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return False
    if fa == fb:
        return True
    short, long_ = sorted((fa, fb), key=len)
    if len(short.split()) >= 3 and long_.startswith(short + " "):
        return True
    sa, sb = set(fa.split()), set(fb.split())
    return len(sa & sb) / len(sa | sb) >= 0.85


def _casefolded(text):
    """A title without LaTeX, accents or case, punctuation kept."""
    t = delatex(html.unescape(str(text or "")))
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return t


def footnote_appended(a, b):
    """One title is the other plus a footnote: after stripping trailing markers (*,
    daggers), the shorter title's characters are exactly the start of the longer one,
    which continues with a footnote number glued to the last word or a footnote
    marker, never with more words. The shorter title needs at least three words."""
    strip = lambda t: re.sub(r"[\s*\u2020\u2021\u00a7\u00b6]+$", "", t)
    a, b = strip(_casefolded(a)), strip(_casefolded(b))
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=lambda t: len(re.sub(r"[^0-9a-z]", "", t)))
    if len(fold(short).split()) < 3:
        return False
    target = re.sub(r"[^0-9a-z]", "", short)
    i = 0
    for pos, ch in enumerate(long_):
        if i == len(target):
            rest = long_[pos:]
            break
        if ch.isalnum() and ch.isascii():
            if ch != target[i]:
                return False
            i += 1
    else:
        return i == len(target)
    if long_[pos - 1].isalnum() and rest[:1].isdigit():
        return True  # footnote number glued to the last word
    rest = rest.lstrip()
    return not rest or rest[0] in "*\u2020\u2021\u00a7\u00b6"


NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
BOOK_REVIEW = re.compile(r"^\s*(?:book\s+reviews?|reviews?\s+of)\s*[:.\-\u2013\u2014]?\s+", re.I)


def fold_numbers(text):
    """fold() with number words as digits: Crossref's '2 methods' is 'Two methods'."""
    return " ".join(NUMBER_WORDS.get(w, w) for w in fold(text).split())


def unglue(text):
    """Split a word glued to a following capitalised word, as registries print an
    italic name without its space ('genus<i>Cataglyphis</i>' -> 'genusCataglyphis')."""
    return re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", str(text or ""))


def book_review_of(record_title, entry_title):
    """The record is a review of the entry's title: 'Book Review: <title> <book's
    authors, publisher, price>' (Mitc09). The entry title (three words or more) must
    start the rest, and the next word must not be a part number."""
    m = BOOK_REVIEW.match(record_title or "")
    if not m:
        return False
    rest, entry = fold_numbers(record_title[m.end():]), fold_numbers(entry_title)
    if len(entry.split()) < 3:
        return False
    if rest == entry:
        return True
    return rest.startswith(entry + " ") and not NUMERAL.match(rest[len(entry) + 1:].split()[0])


SECTION_NUMERAL = re.compile(r"^\s*(?:[IVXLC]+|\d+)\.\s*[\u2014\u2013-]*\s*")


def one_edit(a, b):
    """a and b differ by exactly one substituted, inserted or deleted letter."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + (len(a) == len(b)):] == b[i + 1:]


def typo_overlap(rec, entry):
    """Word-set overlap (Jaccard) of two folded titles where a registry word that is
    one letter from an entry word of five or more letters counts as that word
    (ChabEtal98: Crossref 'padiatric' for 'pediatric'). One such typo at most: with
    two or more the plain overlap is returned. Numbers never count."""
    ra, eb = set(rec.split()), set(entry.split())
    fixed, typos = set(), 0
    for w in ra:
        if w in eb or len(w) < 5 or not w.isalpha():
            fixed.add(w)
            continue
        near = [e for e in eb if len(e) >= 5 and e.isalpha() and one_edit(w, e)]
        typos += len(near) == 1
        fixed.add(near[0] if len(near) == 1 else w)
    if typos > 1:
        fixed = ra
    return len(fixed & eb) / len(fixed | eb)


def registry_title_matches(record_title, entry_title):
    """A DOI record title that is the entry's title.

    Accepted: the record is the entry's title with a footnote appended (Crossref
    appends '11The percentage of nights...' to WoodEtal00b's title); the record is a
    book review of the entry's title (Mitc09); or the titles match (titles_match) and
    carry the same part numbers ('... cortex II' is a different work from
    '... cortex'), comparing number words as digits (Waug63b: '2 methods' = 'Two
    methods') and splitting words the registry glued together (WehnSrin81:
    'genusCataglyphis'). A generic record title ('Correspondence') never matches."""
    if footnote_appended(record_title, entry_title) or book_review_of(record_title, entry_title):
        return True
    numerals = lambda t: {w for w in t.split() if NUMERAL.match(w)}
    entry = fold_numbers(entry_title)
    for variant in record_variants(record_title, entry_title):
        rec = fold_numbers(variant)
        if numerals(rec) == numerals(entry) and (titles_match(rec, entry) or typo_overlap(rec, entry) >= 0.85):
            return True
    return False


def record_variants(record_title, entry_title):
    """The registry title as deposited, with glued words split, and without a leading
    section numeral ('I.\u2014COMPUTING MACHINERY AND INTELLIGENCE', Turi50) unless the
    entry's title starts with one too."""
    out = [record_title, unglue(record_title)]
    if SECTION_NUMERAL.match(record_title or "") and not SECTION_NUMERAL.match(entry_title or ""):
        out += [SECTION_NUMERAL.sub("", v, count=1) for v in list(out)]
    # a bare chapter number before a capitalised word (Elsevier: '20 Stage Analysis of
    # Reaction Processes', Sand80), unless the entry's title starts with a number too
    first = (fold(entry_title).split() or [""])[0]
    if CHAPTER_NUMBER.match(record_title or "") and not (first.isdigit() or first in NUMBER_WORDS):
        out += [CHAPTER_NUMBER.sub("", v, count=1) for v in list(out)]
    return list(dict.fromkeys(out))


CHAPTER_NUMBER = re.compile(r"^\s*\d{1,3}\s+(?=[A-Z])")


def main_title(title):
    """The text before the first colon outside braces ('Hippocampus' of
    'Hippocampus: cognitive processes ...'), or None without a colon."""
    depth = 0
    for i, ch in enumerate(title or ""):
        depth += (ch == "{") - (ch == "}")
        if ch == ":" and depth == 0:
            return title[:i]
    return None


def first_page(pages):
    m = re.match(r"\s*([A-Za-z]?\d+)", str(pages or ""))
    return m[1] if m else None


TITLE_SYNONYMS = {"vs": "versus", "v": "versus"}


def squash(text):
    """A title as one run of letters and digits: folded (case, accents, braces,
    punctuation), 'vs' written 'versus', and every space removed, so words a registry
    ran together ('intentionalretrieval', Curr99) compare equal."""
    return "".join(TITLE_SYNONYMS.get(w, w) for w in fold_numbers(text).split())


def osa_distance(a, b, cap=3):
    """Edit distance (insert, delete, substitute, swap two adjacent letters), counted
    up to `cap`."""
    if abs(len(a) - len(b)) >= cap:
        return cap
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) >= cap:
            return cap
        prev2, prev = prev, cur
    return min(prev[-1], cap)


NEAR_TITLE_EDITS = 2      # letters a garbled or mistyped title may differ by
NEAR_TITLE_MIN_LETTERS = 20


def near_title(record_title, entry_title):
    """The registry title is the entry's up to a deposit garble or a typo on either
    side: with spaces removed and 'vs' = 'versus', at most two letters differ (an
    insertion, deletion, substitution or swap: BousRosn70 'unhibited', Mart65's cited
    'paried', Curr99's run-together words and mojibake 'old\u00ee\u00bfnew'), the entry
    title has at least 20 letters, and both carry the same part numbers."""
    def numerals(t):
        # digit runs whether or not glued to a word (Crossref 'IP 3' from 'IP<sub>3</sub>'
        # is the entry's '{IP3}', HernEtal00) plus roman part numbers
        words = fold_numbers(t).split()
        return sorted([d for w in words for d in re.findall(r"\d+", w)] +
                      [w for w in words if w.isalpha() and NUMERAL.match(w)])
    for variant in record_variants(record_title, entry_title):
        r, e = squash(variant), squash(entry_title)
        if len(e) >= NEAR_TITLE_MIN_LETTERS and numerals(unglue(variant)) == numerals(entry_title) \
                and osa_distance(r, e) <= NEAR_TITLE_EDITS:
            return True
    return False


def record_metadata_agrees(rec, first_author=None, year=None, volume=None, pages=None):
    """The DOI record's first-author surname, year (print or issued), volume and first
    page are all present and all equal the entry's. Returns the list of what differs
    or is missing (empty when everything agrees)."""
    fam = fold((rec.get("families") or [""])[0])
    out = []
    if not fam or not first_author or fold(first_author).replace(" ", "") != fam.replace(" ", ""):
        out.append("first author")
    if not year or year not in {rec.get("print_year"), rec.get("issued_year")}:
        out.append("year")
    if not rec.get("volume") or not volume or str(rec["volume"]).strip() != str(volume).strip():
        out.append("volume")
    if not first_page(rec.get("page")) or first_page(rec.get("page")) != first_page(pages):
        out.append("first page")
    return out


def doi_title_verdict(rec, cands, volume=None, pages=None, first_author=None, year=None, issue=None, journal=None):
    """How a DOI record's title relates to the entry: ('match', why), ('part_number', why)
    when the titles agree except for part numbers (a different part of a series or a
    registry that left the number out: held for the user, JacoEtal98), ('short', why)
    when the registry holds only the entry's pre-colon main title but neither volume
    nor first page corroborates it, or (None, '') when the record is another work.

    A registry title that is exactly the entry's pre-colon main title (Elsevier/Cell
    deposit 'Hippocampus', 'Gain Modulation': Eich04, SaliThie00, ShadMovs99,
    WagnEtal01) matches when the record's volume or first page equals the entry's.

    A registry title that is the entry's up to a garble or typo (near_title) is
    ('near', why) when the record's first-author surname, year, volume and first page
    all equal the entry's (Curr99, BousRosn70, Mart65); without that agreement it is
    another work."""
    rec_title = re.sub(r"(?i)^chapter\s+(?:\d+|[ivxlc]+)\.?[:.]?\s+", "", rec["title"])
    record_title = rec_title + (": " + rec["subtitle"] if rec.get("subtitle") else "")
    for c in cands:
        for t in dict.fromkeys((record_title, rec_title)):
            if registry_title_matches(t, c):
                return "match", "title"
    short = None
    for c in cands:
        main = main_title(c)
        if main and any(fold_numbers(v) == fold_numbers(main) for v in record_variants(rec_title, main)):
            vol_ok = bool(rec.get("volume") and volume and str(rec["volume"]).strip() == str(volume).strip())
            page_ok = bool(first_page(rec.get("page")) and first_page(rec.get("page")) == first_page(pages))
            if vol_ok or page_ok:
                return "match", "pre-colon main title, " + ("volume" if vol_ok else "first page") + " agrees"
            short = ("short", f"registry title is the pre-colon main title {main!r} of the entry, but neither "
                              "volume nor first page corroborates it")
    if short:
        return short
    for c in cands:
        for t in dict.fromkeys((record_title, rec_title)):
            if near_title(t, c):
                differs = record_metadata_agrees(rec, first_author, year, volume, pages)
                if not differs:
                    return "near", (f"registry title {t!r} is the entry's {c!r} up to two letters or run-together "
                                    "words; first author, year, volume and first page all agree")
    page_ok = bool(first_page(rec.get("page")) and first_page(rec.get("page")) == first_page(pages))
    for c in cands:
        for t in dict.fromkeys((record_title, rec_title)):
            if any(titles_match(fold_numbers(v), fold_numbers(c)) for v in record_variants(t, c)):
                if page_ok:  # both parts of a series share the registry title (DamiEtal99a/b)
                    return "part_number_page", (f"titles agree except for part numbers ({t!r} vs {c!r}); "
                                                "the record's first page is the entry's")
                return "part_number", f"titles agree except for part numbers ({t!r} vs {c!r})"
    if generic_item_agrees(rec, volume, issue, pages, year, journal):
        return "generic", (f"registry title {record_title!r} is not the entry's, but volume {rec['volume']}, issue "
                           f"{rec['issue']}, first page {first_page(rec['page'])} and year {year} all equal the "
                           "entry's" + (f" in {rec['container']!r}" if rec.get("container") else ""))
    return None, ""


def generic_item_agrees(rec, volume, issue, pages, year, journal):
    """A registry record whose title is a generic column or section heading (Rebe10:
    Scientific American Mind's 'Ask the Brains') is the entry's item only when its
    volume, issue, first page and year (print or issued) all equal the entry's, and its
    container, when both have one, is the entry's journal. BoddEtal97's 'Correspondence'
    (Crossref 1996, the entry 1997) is not."""
    same = lambda a, b: bool(a) and bool(b) and str(a).strip().lower() == str(b).strip().lower()
    if not (same(rec.get("volume"), volume) and same(rec.get("issue"), issue)
            and first_page(rec.get("page")) and first_page(rec.get("page")) == first_page(pages)
            and year and year in {rec.get("print_year"), rec.get("issued_year")}):
        return False
    return not (rec.get("container") and journal) or fold(rec["container"]) == fold(journal) \
        or titles_match(rec["container"], journal)


def braced(text):
    return re.findall(r"\{([^{}]*)\}", text or "")


def guarded(original, formatted):
    """A house formatter's output, unless it altered brace-protected text or lowercased a
    capital inside a word (O'Reilly -> O'reilly, McGraw -> Mcgraw)."""
    if sorted(braced(original)) != sorted(braced(formatted)):
        return None
    ow, nw = original.split(), formatted.split()
    if len(ow) == len(nw):
        for o, n in zip(ow, nw):
            if o.lower() == n.lower() and any(a.isupper() and b.islower() for a, b in zip(o[1:], n[1:])):
                return None
    return formatted


# ---------------------------------------------------------------- network

_last = [0.0]


def retry_wait(retry_after, attempt):
    """Seconds to wait before retry number `attempt` (0-based) of a rate-limited
    request: the server's Retry-After (seconds or an HTTP date) when given, else
    exponential backoff; never more than MAX_WAIT."""
    wait = None
    if retry_after:
        try:
            wait = float(retry_after)
        except ValueError:
            try:
                from email.utils import parsedate_to_datetime
                wait = parsedate_to_datetime(retry_after).timestamp() - time.time()
            except (TypeError, ValueError):
                wait = None
    if wait is None:
        wait = BACKOFF * 2 ** attempt
    return min(max(wait, 0.0), MAX_WAIT)


def http_get(url, offline=False, retries=None):
    """(status, body) for a GET, cached on disk; status 0 = network failure. A
    rate-limited answer (429, 503) is retried up to `retries` times (default RETRIES),
    honouring Retry-After, before it is returned (and never cached)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if path.exists():
        cached = json.loads(path.read_text())
        return cached["status"], cached["body"]
    if offline:
        return None, "offline: not cached"
    retries = RETRIES if retries is None else retries
    for attempt in range(retries + 1):
        wait = PACE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        retry_after = None
        try:
            with urllib.request.urlopen(req, timeout=60, context=SSL) as resp:
                status, body = resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            status, body = err.code, err.read().decode("utf-8", "replace")
            retry_after = err.headers.get("Retry-After") if err.headers else None
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            _last[0] = time.time()
            return 0, f"network error: {err}"
        _last[0] = time.time()
        if status not in (429, 503) or attempt == retries:
            break
        time.sleep(retry_wait(retry_after, attempt))
    if status in (200, 404) or (status == 400 and "handles" in url):
        path.write_text(json.dumps({"url": url, "status": status, "body": body}))
    return status, body


def clean_doi(doi):
    doi = (doi or "").strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.lower()


def strip_tags(text):
    """A registry title without its HTML/JATS tags. A tag is a word break: Crossref
    glues 'D<sub>2</sub>Dopamine' and 'Ca<sup>2+</sup>Currents' (HernEtal00), which
    read 'D2Dopamine' when the tags were removed without a space."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def date_year(msg, key):
    parts = (msg.get(key) or {}).get("date-parts") or [[None]]
    return str(parts[0][0]) if parts and parts[0] and parts[0][0] else None


def doi_record(doi, offline=False):
    """Registration status and the registry record of a DOI.

    {"doi", "registered": True/False/None, "ra", "title", "print_year",
     "online_year", "issued_year", "page", "volume", "issue", "type", "error"}
    registered is None when the check could not be completed (never treated as
    registered)."""
    doi = clean_doi(doi)
    out = {"doi": doi, "registered": None}
    enc = quote(doi, safe="/()")
    status, body = http_get(f"https://doi.org/api/handles/{enc}", offline)
    if status == 200:
        try:
            code = json.loads(body).get("responseCode")
        except ValueError:
            code = None
        out["registered"] = code == 1
        if code != 1:
            out["error"] = f"handle responseCode {code}"
    elif status == 404:
        out["registered"] = False
        out["error"] = "doi.org/api/handles returned 404 (handle not found)"
    else:
        out["error"] = f"handle check failed: HTTP {status} {str(body)[:120]}"
        return out
    if not out["registered"]:
        return out
    status, body = http_get(f"https://doi.org/ra/{enc}", offline)
    try:
        out["ra"] = json.loads(body)[0].get("RA") if status == 200 else None
    except (ValueError, IndexError, AttributeError):
        out["ra"] = None
    if out["ra"] == "Crossref":
        status, body = http_get(f"https://api.crossref.org/works/{enc}", offline)
        if status == 200:
            msg = json.loads(body)["message"]
            title = " ".join(msg.get("title") or [])
            sub = " ".join(msg.get("subtitle") or [])
            out.update({
                "title": strip_tags(title),
                "subtitle": strip_tags(sub) or None,
                "container": " ".join(msg.get("container-title") or []) or None,
                "print_year": date_year(msg, "published-print"),
                "online_year": date_year(msg, "published-online"),
                "issued_year": date_year(msg, "issued"),
                "page": msg.get("page"), "volume": msg.get("volume"),
                "issue": msg.get("issue"), "type": msg.get("type"),
                "authors": [" ".join(x for x in (a.get("given"), a.get("family") or a.get("name")) if x)
                            for a in msg.get("author") or []],
                "families": [a.get("family") or a.get("name") or "" for a in msg.get("author") or []],
            })
        else:
            out["error"] = f"Crossref record unavailable: HTTP {status}"
    elif out["ra"] == "DataCite":
        status, body = http_get(f"https://api.datacite.org/dois/{enc}", offline)
        if status == 200:
            attrs = json.loads(body)["data"]["attributes"]
            titles = attrs.get("titles") or [{}]
            out.update({"title": titles[0].get("title"),
                        "authors": [c.get("name") or " ".join(x for x in (c.get("givenName"), c.get("familyName")) if x)
                                    for c in attrs.get("creators") or []],
                        "families": [c.get("familyName") or (c.get("name") or "").split(",")[0]
                                     for c in attrs.get("creators") or []],
                        "issued_year": str(attrs.get("publicationYear") or "") or None,
                        "type": (attrs.get("types") or {}).get("resourceTypeGeneral")})
        else:
            out["error"] = f"DataCite record unavailable: HTTP {status}"
    else:
        out["error"] = f"registration agency {out['ra']!r}: no title check available"
    return out


# ---------------------------------------------------------------- bibliography

def load_bib(bib="HEAD"):
    """{key: entry} of cdl.bib; 'HEAD' reads the committed version."""
    if bib == "HEAD":
        text = subprocess.run(["git", "show", "HEAD:cdl.bib"], cwd=ROOT, env=GIT_ENV,
                              check=True, capture_output=True, text=True).stdout
        with tempfile.NamedTemporaryFile("w", suffix=".bib", delete=False) as tmp:
            tmp.write(text)
        try:
            return H.load_bibliography(tmp.name, verbose=False)
        finally:
            os.unlink(tmp.name)
    return H.load_bibliography(str(bib), verbose=False)


def renamed_away():
    path = ROOT / "verification/key-renames.json"
    if not path.exists():
        return {}
    return {r["old_key"]: r["new_key"] for r in json.loads(path.read_text())}


def city_states(bib):
    """{folded city: state code} from cdl.bib's own 'City, {ST}' addresses (unique only)."""
    seen = {}
    for e in bib.values():
        m = re.fullmatch(r"\s*([^,{}]+),\s*\{([A-Z]{2})\}\s*", e.get("address", ""))
        if m and m[2] in US_CODES:
            seen.setdefault(fold(m[1]), set()).add(m[2])
    return {c: s.pop() for c, s in seen.items() if len(s) == 1}


# ---------------------------------------------------------------- names

def split_top(text, sep=" "):
    """Split on sep outside braces."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "{"
        depth -= ch == "}"
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [t for t in (x.strip() for x in out) if t]


def split_names(value):
    """Split an and-separated name list, never inside braces ({Food and Drug Administration})."""
    words, names, cur, depth = re.split(r"(\s+)", value or ""), [], "", 0
    for w in words:
        if depth == 0 and w == "and":
            names.append(cur)
            cur = ""
            continue
        depth += w.count("{") - w.count("}")
        cur += w
    names.append(cur)
    return [n.strip() for n in names if n.strip()]


def given_initials(token):
    """'Jean-Pierre' -> 'J-P', 'S.W.' -> 'S W', 'T. V. P.' -> 'T V P', 'JP' -> 'J P'.
    A hyphen joins dotted initials too ('J.-A.' -> 'J-A', Crossref's form), and a
    brace-protected capital is that letter ('Jean-{A}rcady' -> 'J-A', TrulEtal97; it
    was read as the initial '{')."""
    token = token.strip()
    if not token:
        return ""
    words = re.sub(r"\.(?!-)", ". ", token).split()
    out = []
    for w in words:
        parts = [p for p in w.replace(".", "").split("-") if p]
        if not parts:
            continue
        if len(parts) == 1 and parts[0].isupper() and parts[0].isalpha() and len(parts[0]) > 1:
            out.extend(parts[0])  # clumped initials
            continue
        letters = []
        for p in parts:
            plain = re.match(r"\{([A-Za-z])\}", p)  # '{A}rcady': a protected capital, no macro
            m = H.LETTER_UNIT.match(p)
            letters.append(plain[1] if plain else m.group(0) if m else p[0])
        out.append("-".join(letters))
    return " ".join(out)


def looks_initial(tok):
    """An initial, dotted or not ('A', 'A.', 'J.-P.', 'J-P')."""
    return is_initial(tok) or re.fullmatch(r"(?:[A-Z]\.)+(?:-(?:[A-Z]\.?))*|[A-Z]\.?(?:-[A-Z]\.?)+", tok) is not None


def mid_word_surname(name):
    """(initials, words) of a house-form name whose given part is initials followed by
    full words ('A Quattrini Li' -> ('A', 'Quattrini Li')), or None."""
    tokens = split_top(name)
    if len(tokens) < 3 or any("{" in t or "\\" in t for t in tokens[1:]):
        return None
    i = 0
    while i < len(tokens) - 1 and looks_initial(tokens[i]):
        i += 1
    if i == 0 or i >= len(tokens) - 1 or not re.fullmatch(r"[A-Z][a-z]+(?:-[A-Z][a-z]+)*", tokens[i]):
        return None
    return " ".join(tokens[:i]), " ".join(tokens[i:])


FAMILY_RES = (re.compile(r'"family"\s*:\s*"([^"]+)"'), re.compile(r'"(?:name|familyName)"\s*:\s*"([^",]+)[,"]'),
              re.compile(r"<LastName>([^<]+)</LastName>"), re.compile(r"\bFAU\s+-\s+([^,\n]+),"))


def source_families(evidence, record=None):
    """Folded family names as the sources print them: Crossref/DataCite JSON quotes,
    PubMed LastName, MEDLINE FAU, and the fetched DOI record's families."""
    out = {fold(f) for f in (record or {}).get("families") or [] if f}
    for e in evidence or []:
        for rx in FAMILY_RES:
            out |= {fold(m) for m in rx.findall(e.get("quote", ""))}
    return out


def is_initial(tok):
    if re.fullmatch(r"(?:[A-Z]|\{\\[^}]+\}|\\[^A-Za-z\s]\{?[A-Za-z]\}?)(?:-(?:[A-Z]|\{\\[^}]+\}))*", tok):
        return True
    return False


def uncapitalise(tokens):
    """Name words printed in capitals (World Scientific's 'EUGENIO', 'LACHAUX') in
    ordinary case, so no formatter reads them as clumped initials ('E U G E N I O').
    A plain capitalised token of four or more letters is a word; in a name printed
    entirely in capitals, a two- or three-letter token with a vowel ('ANN', 'WU') is a
    word too. 'JP' in 'JP Smith' stays clumped initials. Braced and LaTeX tokens are
    left alone."""
    plain = [t for t in tokens if "{" not in t and "\\" not in t and re.search(r"[A-Za-z]", t)]
    all_caps = bool(plain) and all(t == t.upper() for t in plain)
    out = []
    for t in tokens:
        letters_ = re.sub(r"[^A-Za-z]", "", t)
        if t in plain and t == t.upper() and (
                len(letters_) >= 4 or (all_caps and len(letters_) >= 2 and re.search(r"[AEIOUY]", letters_))):
            t = re.sub(r"[A-Za-z]+", lambda m: m[0].capitalize(), t)
        out.append(t)
    return out


def normalise_name(name):
    """One name in house form; returns (new, [notes])."""
    notes = []
    if name == "others" or (name.startswith("{") and name.endswith("}")
                             and split_top(name) == [name] and "\\" not in name[1:3]):
        return name, notes
    original = name
    parts = [p.strip() for p in split_top(name, ",")]
    kept = []
    for p in parts:
        if re.fullmatch(r"(?:Jr|Sr|II|III|IV)\.?", p):
            notes.append(f"suffix '{p}' removed")
            continue
        q = SUFFIX_RE.sub(r"\1", p)
        if q != p:
            notes.append(f"suffix removed from '{p}'")
        kept.append(q)
    if len(kept) == 2:
        family, given = kept
        if " " in family and not (family.startswith("{") and family.endswith("}")):
            family = "{" + family + "}"
        name = f"{given} {family}"
    elif len(kept) == 1:
        name = SUFFIX_RE.sub(r"\1", kept[0])
        if name != kept[0]:
            notes.append("suffix removed")
    else:
        return original, [f"cannot parse name {original!r}"]
    tokens = uncapitalise(split_top(name))
    if tokens != split_top(name):
        notes.append(f"capitalised name {name!r} -> {' '.join(tokens)!r}")
    # unbrace a single-word surname group without macros: {Engel} -> Engel
    last = tokens[-1]
    if last.startswith("{") and last.endswith("}") and " " not in last and "\\" not in last \
            and last.count("{") == 1:
        tokens[-1] = last[1:-1]
    # surname starts at the first lowercase particle or at the last token
    start = len(tokens) - 1
    for i, t in enumerate(tokens[:-1]):
        if t.lower() in H.prefixes and t == t.lower():
            start = i
            break
    else:
        # a capitalised particle after the initials starts a compound surname, braced
        # as cdl.bib writes it: 'B A L Di Leone' -> 'B A L {Di Leone}' (VogtEtal14),
        # never the initial 'D'
        for i, t in enumerate(tokens[:-1]):
            if i and t.lower() in CAP_PARTICLES and t[:1].isupper() and all(is_initial(g) for g in tokens[:i]):
                start = i
                if "\\" not in " ".join(tokens[i:]):
                    family = "{" + " ".join(tokens[i:]).replace("{", "").replace("}", "") + "}"
                    notes.append(f"particle surname braced: {' '.join(tokens[i:])!r} -> {family!r}")
                    tokens = tokens[:i] + [family]
                break
    given, family = tokens[:start], tokens[start:]
    new_given = []
    for i, t in enumerate(given):
        if is_initial(t):
            new_given.append(t)
        elif i and len(kept) == 1 and all(looks_initial(g) for g in given[:i]):
            # a full word after the initials is part of the surname in house form
            # ('A Quattrini Li', 'K Vasuden Alwala'): never turned into an initial
            # (CarvEtal22b 'A Q Li' added an initial); braced only on a source's word.
            # A 'Family, Given' form names its given part, which is abbreviated as usual
            new_given.extend(given[i:])
            break
        else:
            ini = given_initials(t)
            if ini != t:
                notes.append(f"'{t}' -> '{ini}'")
            new_given.append(ini)
    name = " ".join(new_given + family)
    try:
        name = H.reformat_author(name)
    except ValueError as err:
        return original, [f"house formatter could not parse {original!r}: {err}"]
    return name, notes if name != original else []


CAP_PARTICLES = {"de", "da", "di", "du", "des", "del", "della", "der", "den", "van", "von", "la", "le", "dos",
                 "das", "dei", "ten", "ter"}


def normalise_names(value):
    names, notes = [], []
    for n in split_names(value):
        new, why = normalise_name(n)
        names.append(new)
        notes += why
    return " and ".join(names), notes


def surname(name):
    tokens = split_top(name)
    if not tokens:
        return ""
    start = len(tokens) - 1
    for i, t in enumerate(tokens[:-1]):
        if t.lower() in H.prefixes and t == t.lower():
            start = i
            break
    return " ".join(tokens[start:])


def surname_key(name):
    """Folded surname for the respelling test, without format damage that is not a
    spelling: a suffix, also mangled ('{Robinson I I }', KrauEtal13), and a leading
    'and' left by a broken name split ('A A {and Artigas}', ChamEtal03)."""
    f = fold(SUFFIX_RE.sub(r"\1", surname(name)))
    f = re.sub(r"^and\s+", "", f)
    return re.sub(r"(?:\s+(?:jr|sr|i|ii|iii|iv|2nd|3rd))+$", "", f)


def surname_without_accented(name):
    """Folded surname with every accented letter left out, so a restored accented
    letter ('Par-Blagoev' -> 'Par{\\'e}-Blagoev', WagnEtal01) compares equal."""
    t = unicodedata.normalize("NFC", delatex(html.unescape(surname(name))))
    return fold("".join(c for c in t if c.isascii()))


_HOUSE_SURNAMES = {}


def house_surname_forms(bib):
    """{(first initial, surname letters): {surname form: count}} over the author and
    editor fields of cdl.bib, for names written with a space or particle."""
    cached = _HOUSE_SURNAMES.get(id(bib))
    if cached and cached[0] is bib:
        return cached[1]
    forms = {}
    for e in bib.values():
        for field in NAME_FIELDS:
            for n in split_names(e.get(field, "")):
                fam, giv = surname(n), given_part(n)
                if not giv or " " not in fold(fam):
                    continue
                k = (fold(giv)[:1], fold(fam).replace(" ", ""))
                forms.setdefault(k, {}).setdefault(fam, 0)
                forms[k][fam] += 1
    _HOUSE_SURNAMES[id(bib)] = (bib, forms)
    return forms


def house_surname(name, bib, exclude=None):
    """A run-together surname ('M {denNijs}', MillEtal07d) in the form cdl.bib already
    writes for the same author ('M {den Nijs}', five entries): same first initial, the
    same letters, and a spaced form used at least twice (entries other than `exclude`).
    Returns (name, note) or (name, None)."""
    fam, giv = surname(name), given_part(name)
    if not giv or " " in fold(fam) or not fold(fam):
        return name, None
    forms = house_surname_forms(bib).get((fold(giv)[:1], fold(fam).replace(" ", "")), {})
    if exclude is not None:
        forms = dict(forms)
        for n in split_names((exclude or {}).get("author", "")) + split_names((exclude or {}).get("editor", "")):
            if surname(n) in forms:
                forms[surname(n)] -= 1
    best = sorted(((c, f) for f, c in forms.items() if c >= 2), reverse=True)
    if not best or (len(best) > 1 and best[0][0] == best[1][0]):
        return name, None
    new = f"{giv} {best[0][1]}"
    return new, f"surname {fam!r} -> {best[0][1]!r} as cdl.bib writes it ({best[0][0]} entries)"


_NAME_INDEX = {}


def name_initials(name):
    """The initials of a name's given part as folded letters: 'J-P' -> ('j', 'p')."""
    return tuple(w[0] for w in fold(given_part(name)).split())


def compatible_initials(a, b):
    """Same first initial, and one list of initials starts the other ('D' ~ 'D M')."""
    if not a or not b or a[0] != b[0]:
        return False
    short, long_ = sorted((a, b), key=len)
    return long_[:len(short)] == short


def house_name_uses(bib, name, exclude_key=None):
    """Keys of cdl.bib entries (other than exclude_key) whose author or editor field has
    a person with the same folded surname as `name` and compatible initials."""
    cached = _NAME_INDEX.get(id(bib))
    if not (cached and cached[0] is bib):
        index = {}
        for k, e in bib.items():
            for field in NAME_FIELDS:
                for n in split_names(e.get(field, "")):
                    if n != "others":
                        index.setdefault(surname_key(n), []).append((name_initials(n), k))
        cached = _NAME_INDEX[id(bib)] = (bib, index)
    mine = name_initials(name)
    return sorted({k for ini, k in cached[1].get(surname_key(name), []) if k != exclude_key
                   and compatible_initials(ini, mine)})


def given_part(name):
    tokens = split_top(name)
    fam = surname(name)
    return " ".join(tokens[: len(tokens) - len(split_top(fam))])


ARXIV_ID = re.compile(r"arxiv\D{0,20}?(\d{4}\.\d{4,5}|[a-z][a-z\-]*(?:\.[A-Z]{2})?/\d{7})", re.I)
ZENODO_DOI = re.compile(r"10\.5281/zenodo\.(\d+)", re.I)


def deposited_witnesses(row, final, ctx, last):
    """[(host, description)] of author-deposited records that print the folded surname
    `last`: the arXiv record of an arXiv id named in the row (its title must be the
    entry's), and the Zenodo record of a 10.5281/zenodo DOI the entry carries. The
    authors deposit these names themselves, and the post-check fetches them from
    export.arxiv.org / zenodo.org, not the researcher's quoted host."""
    fetch = ctx.get("fetch") or http_get
    text = " ".join([row.get("notes", ""), (row.get("identity") or {}).get("url", "")] +
                    [e.get("url", "") for f in (row.get("fields") or {}).values() for e in (f or {}).get("evidence") or []] +
                    [str(final.get("doi", "")), str(final.get("volume", "")), str(final.get("journal", ""))])
    out = []
    for aid in dict.fromkeys(m for m in ARXIV_ID.findall(text)):
        status, body = fetch(f"https://export.arxiv.org/api/query?id_list={aid}")
        if status != 200:
            continue
        entry = (re.search(r"<entry>(.*?)</entry>", body, re.S) or [None, ""])[1]
        title = re.sub(r"\s+", " ", html.unescape((re.search(r"<title>(.*?)</title>", entry, re.S) or [None, ""])[1]))
        names = [html.unescape(n) for n in re.findall(r"<name>(.*?)</name>", entry)]
        if title and titles_match(title, final.get("title", "")) and any(last in fold(n).split() for n in names):
            out.append(("export.arxiv.org", f"arXiv {aid} ({', '.join(names[:3])})"))
    for zid in dict.fromkeys(ZENODO_DOI.findall(str(final.get("doi", "")))):
        status, body = fetch(f"https://zenodo.org/api/records/{zid}")
        if status != 200:
            continue
        try:
            creators = json.loads(body)["metadata"]["creators"]
        except (ValueError, KeyError, TypeError):
            continue
        fams = [c.get("name", "").split(",")[0] for c in creators]
        if any(last in fold(f).split() for f in fams):
            out.append(("zenodo.org", f"Zenodo record {zid} of the entry's DOI"))
    return out


# ---------------------------------------------------------------- user decisions (cross-wave page, 2026-09-26)

HERE = Path(__file__).resolve().parent
DECISIONS = HERE / "crosswave/applied-decisions.json"
DECISIONS_DIR = HERE / "crosswave/decisions"
REMOVALS = HERE / "crosswave/removals.json"

# Software / Zenodo releases: cite the FIRST version, its year, no version number
# (user, q-brainiak: "always cite the *first* version (and use to get the year)-- and
# don't specify a version number in the citation info")
_VTOKEN = (r"\{?(?:(?:[Vv]ersion|[Rr]elease)\s*|[Vv]\.?\s?)?\d+(?:\.\d+)+[A-Za-z0-9.\-]*\}?"   # 1.5.0, v0.2, Version 1.0
           r"|\{?(?:(?:[Vv]ersion|[Rr]elease)\s*|[Vv]\.?)\d+[A-Za-z0-9.\-]*\}?")                  # v1, Version 3
_VERSION_TAIL = re.compile(r"\s*[:,–—-]?\s*\(?(?:" + _VTOKEN + r")\)?(?:\s*\([^()]*\d{4}\))?\s*$")
_VERSION_BEFORE_COLON = re.compile(r"\s+(?:" + _VTOKEN + r")(?=\s*:)")


def strip_version(text):
    """A software title (or note) without its version number: a trailing version
    ('{ContextLab}/chatify: {v0.2.1}', 'Kit v0.2', ': {Version 1.0}', Zenodo's
    'v0.2.1 (August, 2023)') or one just before a colon ('{WordCloud} 1.5.0: a little
    ...'). A number without a v/version prefix and without a dot is not a version
    ('Llama 3'), nor is one inside the title ('{V1} alpha')."""
    t = str(text or "")
    prev = None
    while prev != t:
        prev = t
        t = _VERSION_TAIL.sub("", t)
    t = _VERSION_BEFORE_COLON.sub("", t)
    return re.sub(r"\s*[:,]\s*$", "", t).strip()


def zenodo_first_version(doi, fetch):
    """The first version of the Zenodo release series a 10.5281/zenodo DOI belongs to
    (a concept DOI redirects to its latest version). Reads zenodo.org/api/records/<id>
    (conceptrecid, relations.version index) and, unless that record is index 0, pages
    through /versions (25 per page, the anonymous limit) for the index-0 record.
    Returns {"doi", "year", "date", "version", "title", "type", "creators", "count",
    "concept", "url"} or {"error"}."""
    m = ZENODO_DOI.search(str(doi or ""))
    if not m:
        return {"error": f"{doi} is not a Zenodo DOI"}
    status, body = fetch(f"https://zenodo.org/api/records/{m[1]}")
    if status != 200:
        return {"error": f"zenodo.org/api/records/{m[1]}: HTTP {status}"}
    try:
        rec = json.loads(body)
    except ValueError:
        return {"error": f"zenodo.org/api/records/{m[1]}: not JSON"}

    def summary(r, url, count):
        md = r.get("metadata") or {}
        date = str(md.get("publication_date") or "")
        return {"doi": clean_doi(r.get("doi")), "date": date, "year": date[:4] if re.match(r"\d{4}", date) else None,
                "version": md.get("version"), "title": md.get("title"),
                "type": (md.get("resource_type") or {}).get("type"),
                "creators": [c.get("name", "") for c in md.get("creators") or []],
                "concept": r.get("conceptrecid"), "count": count, "url": url}

    def relation(r):
        return (((r.get("metadata") or {}).get("relations") or {}).get("version") or [{}])[0]

    def index(r):
        return relation(r).get("index")

    url = f"https://zenodo.org/api/records/{m[1]}"
    if index(rec) == 0:
        return summary(rec, url, 1 if relation(rec).get("is_last") else None)
    total, page = None, 1
    while page <= 40:
        vurl = f"https://zenodo.org/api/records/{rec['id']}/versions?size=25&page={page}&allversions=true"
        status, body = fetch(vurl)
        if status != 200:
            return {"error": f"{vurl}: HTTP {status}"}
        try:
            hits = json.loads(body)["hits"]
        except (ValueError, KeyError):
            return {"error": f"{vurl}: no hits"}
        total = hits.get("total")
        for h in hits.get("hits") or []:
            if index(h) == 0:
                return summary(h, vurl, total)
        if not hits.get("hits") or page * 25 >= (total or 0):
            break
        page += 1
    return {"error": f"no index-0 version among {total} versions of Zenodo record {m[1]}"}


def software_entry(entry):
    """A software citation: a Zenodo DOI, @software, or a @misc that points at GitHub."""
    et = str(entry.get("ENTRYTYPE") or "").lower()
    return bool(ZENODO_DOI.search(str(entry.get("doi") or ""))) or et == "software" or \
        (et == "misc" and "github.com" in str(entry.get("howpublished") or entry.get("url") or ""))


# Countries in addresses: drop a country that no quote prints (user, q-country 'drop':
# Herb34 'Langensalza, Germany', BuzsEtal94 '..., Germany'); an address that is only a
# country is left out. Keys: how the country is written in an address; values: the
# words a source may print for it (folded). Two-letter codes that are US states
# ({DE}, {IN}, {IL}, {LA}, {CA}, ...) are never read as countries; city-states
# (Singapore, Hong Kong alone) are cities, not countries.
_UK = ("uk", "u k", "united kingdom", "great britain", "britain", "england", "scotland", "wales")
COUNTRIES = {
    "germany": ("germany", "deutschland"), "uk": _UK, "united kingdom": _UK, "england": _UK, "scotland": _UK,
    "great britain": _UK, "gb": _UK,
    "netherlands": ("netherlands", "holland", "nederland"), "the netherlands": ("netherlands", "holland", "nederland"),
    "nl": ("netherlands", "holland", "nederland"),
    "france": ("france",), "fr": ("france",), "canada": ("canada",), "sweden": ("sweden", "sverige"),
    "se": ("sweden", "sverige"), "austria": ("austria", "osterreich"), "at": ("austria", "osterreich"),
    "switzerland": ("switzerland", "schweiz", "suisse"), "ch": ("switzerland", "schweiz", "suisse"),
    "italy": ("italy", "italia"), "it": ("italy", "italia"), "spain": ("spain", "espana"), "es": ("spain", "espana"),
    "japan": ("japan",), "jp": ("japan",), "china": ("china",), "cn": ("china",),
    "australia": ("australia",), "au": ("australia",), "russia": ("russia",), "ru": ("russia",),
    "denmark": ("denmark",), "dk": ("denmark",), "norway": ("norway",), "no": ("norway",),
    "finland": ("finland",), "fi": ("finland",), "belgium": ("belgium", "belgique"), "be": ("belgium", "belgique"),
    "israel": ("israel",), "india": ("india",), "poland": ("poland", "polska"), "pl": ("poland", "polska"),
    "czech republic": ("czech",), "cz": ("czech",), "hungary": ("hungary",), "hu": ("hungary",),
    "portugal": ("portugal",), "pt": ("portugal",), "ireland": ("ireland",), "ie": ("ireland",),
    "new zealand": ("new zealand",), "nz": ("new zealand",), "brazil": ("brazil", "brasil"), "br": ("brazil", "brasil"),
    "mexico": ("mexico",), "greece": ("greece",), "korea": ("korea",), "south korea": ("korea",), "kr": ("korea",),
    "taiwan": ("taiwan",), "tw": ("taiwan",), "bulgaria": ("bulgaria",), "iceland": ("iceland",),
}


def address_country(address):
    """(rest, country as written, printed forms) when the address's last comma part is
    a country, else None. 'Langensalza, Germany' -> ('Langensalza', 'Germany', ...);
    'Germany' -> ('', 'Germany', ...); 'Bloomington, {IN}' -> None (a US state)."""
    parts = [p.strip() for p in split_top(str(address or ""), ",")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    last = parts[-1]
    plain = last.replace("{", "").replace("}", "").strip().rstrip(".")
    key = plain.lower()
    if plain.upper() in US_CODES and len(plain) == 2:
        return None
    if key not in COUNTRIES or (len(key) == 2 and plain != plain.upper()):
        return None
    return ", ".join(parts[:-1]), last, COUNTRIES[key]


def country_printed(forms, quotes):
    folded = [fold(q) for q in quotes]
    return any(re.search(r"(?<![a-z0-9])" + re.escape(f) + r"(?![a-z0-9])", q) for f in forms for q in folded)


def address_quotes(fields):
    """The quotes that can print an address: the address and publisher evidence (an
    imprint line prints both)."""
    return [e.get("quote", "") for n in ("address", "publisher")
            for e in ((fields.get(n) or {}).get("evidence") or [])]


def quote_found(quote, body):
    """A quote is found in a fetched body verbatim, in its compact JSON form (so that
    '"date":"1885"' matches an escaped JSON body), or after folding."""
    cands = [str(body or "")]
    try:
        cands.append(json.dumps(json.loads(body), ensure_ascii=False, separators=(",", ":")))
    except (ValueError, TypeError):
        pass
    fq = fold(quote)
    return any(quote in c or (fq and fq in fold(c)) for c in cands)


def load_decisions(path=None):
    """{key: decision} from crosswave/applied-decisions.json ({} when absent)."""
    path = Path(path) if path else DECISIONS
    if not path.exists():
        return {}
    return json.loads(path.read_text())["entries"]


def build_removals(decisions_dir=None, bib=None):
    """The entries the user approved for removal (cross-wave page, 2026-09-26): every
    a-<key> decision with verdict 'correct' (conference abstracts; the six marked
    'wrong' are real articles and stay), plus any j-<key> whose note says to remove it
    as a conference abstract (JohnRedi07b, which is also an a- item)."""
    d = Path(decisions_dir) if decisions_dir else DECISIONS_DIR
    out = {}
    for p in sorted(d.glob("a-*.json")):
        r = json.loads(p.read_text())
        if r.get("verdict") == "correct":
            out[r["entry"]] = {"key": r["entry"], "reason": "conference abstract",
                               "decisions": [f"{r['key']}: {r['verdict']}"]}
    for p in sorted(d.glob("j-*.json")):
        r = json.loads(p.read_text())
        note = str(r.get("note") or "")
        if re.search(r"\bremove\b", note, re.I) and re.search(r"conference abstract", note, re.I):
            e = out.setdefault(r["entry"], {"key": r["entry"], "reason": "conference abstract", "decisions": []})
            e["decisions"].append(f"{r['key']}: {r['verdict']} ({note})")
    waves = {}
    for p in sorted(HERE.glob("wave*/batch-*.json")):
        for row in json.loads(p.read_text()):
            waves.setdefault(row["key"], set()).add(p.parent.name)
    for k, e in out.items():
        e["waves"] = sorted(waves.get(k, ()))
        if bib is not None:
            e["in_head_bib"] = k in bib
    return [out[k] for k in sorted(out, key=str.lower)]


# ---------------------------------------------------------------- field rules

def roman(n):
    """'15' -> 'xv' (lowercase, for comparison with folded text); '' if not a number."""
    if not re.fullmatch(r"\d+", str(n)) or not 0 < int(n) < 4000:
        return ""
    n, out = int(n), ""
    for v, r in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"),
                 (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + r, n - v
    return out


VENUE_STOP = {"the", "of", "on", "in", "and", "for", "a", "an", "proceedings", "proc", "conference", "annual",
              "international", "workshop", "symposium", "meeting"}


PUBLISHER_STOP = {"the", "and", "of", "press", "publishing", "publishers", "publisher", "verlag", "inc", "ltd", "co",
                  "company", "sons", "son", "sohne", "university", "books", "group", "pub", "associates", "gmbh"}


def different_publisher(new, old):
    """Two publisher names with no content word in common (ignoring 'Press', 'Sons',
    'Verlag', ...): another publisher, not a rewording ('Erlbaum' ~ 'Lawrence Erlbaum
    Associates'). An empty old publisher is not 'different'."""
    words = lambda t: {w for w in fold(t).split() if w not in PUBLISHER_STOP}
    a, b = words(new), words(old)
    return bool(a) and bool(b) and not (a & b)


def same_venue(journal, booktitle):
    """A journal value that names the same venue as the booktitle (a rewording of the
    conference or book name: DesaEtal12's 'Engineering in Medicine and Biology Society
    Annual International Conference of the {IEEE}'), not a book series. Content words
    (minus function words and generic venue words) of the journal: at least two, and
    at least 80% of them in the booktitle. 'Advances in Psychology' against a book
    title shares none."""
    words = lambda t: {w for w in fold(t).split() if w not in VENUE_STOP and not re.fullmatch(r"(?:19|20)\d{2}", w)}
    j, b = words(journal), words(booktitle)
    return len(j) >= 2 and len(j & b) / len(j) >= 0.8


def ordinal_suffix(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def normalise_ordinals(value):
    def fix(m):
        return f"{m[1]}\\textsuperscript{{{ordinal_suffix(m[1])}}}"
    parts = re.split(r"(\\url\{[^}]*\})", value)
    out = []
    for p in parts:
        if p.startswith("\\url{"):
            out.append(p)
            continue
        p = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", fix, p)
        p = re.sub(r"\b(\d+)\\textsuperscript\{(?:st|nd|rd|th)\}", fix, p)
        out.append(p)
    new = "".join(out)
    return new, ([f"ordinals: {value!r} -> {new!r}"] if new != value else [])


def normalise_edition(value):
    v = value.strip()
    m = re.fullmatch(r"(?i)(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
                     r"(?:\s+(?:ed\.?|edn\.?|edition))?", v)
    if m:
        n = ORDINAL_WORDS[m[1].lower()]
        new = f"{n}\\textsuperscript{{{ordinal_suffix(n)}}}"
    else:
        new = re.sub(r"(?i)^(\d+)(?:st|nd|rd|th)?(?:\\textsuperscript\{[a-z]+\})?"
                     r"(?:\s+(?:ed\.?|edn\.?|edition))?$",
                     lambda m: f"{m[1]}\\textsuperscript{{{ordinal_suffix(m[1])}}}", v)
    return new, ([f"edition: {value!r} -> {new!r}"] if new != value else [])


def normalise_number(value):
    new = re.sub(r"^\s*(\d+)\s*(?:-|–|—|--|---)\s*(\d+)\s*$", r"\1--\2", value)
    return new, ([f"issue range: {value!r} -> {new!r}"] if new != value else [])


def normalise_pages(value):
    new = re.sub(r"^\s*([A-Za-z]?\d+)\s*(?:-|–|—|---)\s*([A-Za-z]?\d+)\s*$", r"\1--\2", value)
    m = re.fullmatch(r"(\d+)--(\d+)", new)
    if m and len(m[2]) < len(m[1]) and int(m[2]) < int(m[1]):
        new = f"{m[1]}--{m[1][: len(m[1]) - len(m[2])]}{m[2]}"
    return new, ([f"pages: {value!r} -> {new!r}"] if new != value else [])


def normalise_booktitle(value):
    notes = []
    new = value
    if PROCEEDINGS_RE.search(value):
        new = re.sub(r"\s*\((?:19|20)\d{2}\)", "", new)
        new = re.sub(r"\s*'\d{2}\b", "", new)
        new = re.sub(r"(?<![\d/])\b(?:19|20)\d{2}\b(?![\d/])\s*", "", new)
        new = re.sub(r"\s+([,:;)])", r"\1", re.sub(r"\s{2,}", " ", new)).strip(" ,")
        if new != value:
            notes.append(f"proceedings year removed: {value!r} -> {new!r}")
    new2, n2 = normalise_ordinals(new)
    return new2, notes + n2


def normalise_address(value, cities):
    v = value.strip()
    m = re.fullmatch(r"(.+?),\s*(?:United States(?: of America)?|U\.?S\.?A?\.?)", v)
    if m:
        city = m[1].strip()
        m2 = re.fullmatch(r"(.+?),\s*\{?([A-Z]{2})\}?", city)
        if m2 and m2[2] in US_CODES:
            new = f"{m2[1].strip()}, {{{m2[2]}}}"
        else:
            st = cities.get(fold(city)) or US_CITIES.get(fold(city))
            if not st:
                return value, [], [f"US address {value!r}: state unknown, needs 'City, {{ST}}'"]
            new = f"{city}, {{{st}}}"
        return new, [f"US address: {value!r} -> {new!r}"], []
    m = re.fullmatch(r"(.+?),\s*\{?([A-Za-z. ]+?)\}?\.?", v)
    if m:
        state = m[2].strip()
        key = state.lower().rstrip(".")
        code = state if state in US_CODES else US_STATES.get(key) or US_STATES.get(state.lower())
        if code and not (state in US_CODES and v.endswith("{" + state + "}")):
            if state in US_CODES or len(state) > 2 or "." in state or state.lower() in US_STATES:
                new = f"{m[1].strip()}, {{{code}}}"
                if new != value:
                    return new, [f"US address: {value!r} -> {new!r}"], []
    formatted = guarded(v, H.format_journal_name(v, key=H.address_key, force_caps=H.address_codes))
    if formatted and formatted != value:
        return formatted, [f"address house form: {value!r} -> {formatted!r}"], []
    return value, [], []


def normalise_entrytype(value):
    v = (value or "").strip().lower().lstrip("@")
    if v == "conference":
        return "inproceedings", ["@conference -> @inproceedings"], None
    if v not in BIBTEX_TYPES:
        return None, [], f"ENTRYTYPE {value!r} is not a BibTeX entry type"
    return v, ([] if v == value else [f"ENTRYTYPE {value!r} -> {v!r}"]), None


# ---------------------------------------------------------------- key rule

def key_target(entry):
    names = entry.get("author", "").strip() or entry.get("editor", "").strip()
    year = entry.get("year", "").strip()
    if not names or not year:
        return None
    try:
        return H.authors2key(names, year)
    except Exception:  # authors2key raises bare Exception on malformed names
        return None


def key_fits(key, target):
    return key == target or (key.startswith(target) and re.fullmatch(r"[a-z]+", key[len(target):]) is not None)


def first_surname(e):
    names = split_names(e.get("author") or e.get("editor") or "")
    return fold(surname(names[0])) if names else ""


NUMERAL = re.compile(r"^(?:\d+|[ivxlc]+)$")


def same_work(a, b):
    """Title + first author surname + year; part numbers in the titles must agree
    (Part I and Part II of a series are different works)."""
    ta, tb = fold(a.get("title", "")), fold(b.get("title", ""))
    if {w for w in ta.split() if NUMERAL.match(w)} != {w for w in tb.split() if NUMERAL.match(w)}:
        return False
    return (titles_match(ta, tb)
            and first_surname(a) and first_surname(a) == first_surname(b)
            and a.get("year", "").strip() == b.get("year", "").strip())


def work_index(bib):
    """{(first surname, year): [keys]} for duplicate search."""
    idx = {}
    for k, e in bib.items():
        idx.setdefault((first_surname(e), e.get("year", "").strip()), []).append(k)
    return idx


def same_work_in_bib(key, final, bib, index):
    """Other cdl.bib entries that are the same work as `final` (title, first author, year),
    whether or not they have a DOI."""
    cands = index.get((first_surname(final), final.get("year", "").strip()), []) if index is not None else bib
    return sorted(k for k in cands if k != key and same_work(bib[k], final))


def keeper(keys, target):
    """Which of several keys for one work stays: the one that fits the ID rule for the
    work's corrected metadata (RuggAlla00, not Rugg00, once K Allan is added), else the
    earliest key. Deterministic, so two entries are never told to merge into each other."""
    fitting = sorted(k for k in keys if target and key_fits(k, target))
    return fitting[0] if fitting else sorted(keys)[0]


def next_suffix(used):
    for s in H.get_key_suffixes(len(used) + 2):
        if s not in used:
            return s


def key_plan(key, current, final, bib, taken, reserved, index=None):
    """rename / duplicate / collision plan for the final entry."""
    target = key_target(final)
    plan = {"current_key": key, "target_base": target, "action": "keep"}
    if target is None:
        plan["action"] = "no_key_rule"
        return plan
    same_doi = [k for k, e in bib.items() if k != key and final.get("doi")
                and clean_doi(e.get("doi")) == clean_doi(final.get("doi"))]
    if same_doi:
        plan["same_doi_as"] = same_doi
    same = same_work_in_bib(key, final, bib, index)
    if same:
        plan["same_work_as"] = same
    if key_fits(key, target) or H.key_overrides.get(key) == target:
        if same_doi:
            plan["action"] = "duplicate"
            plan["merge_into"] = same_doi[0]
        elif same and keeper([key] + same, target) != key:
            into = keeper([key] + same, target)
            plan.update(action="duplicate", merge_into=into,
                        detail=f"same work (title, first author, year) already in cdl.bib as {into}: "
                               f"merge {key} into it")
        elif same:
            plan["detail"] = (f"same work (title, first author, year) as {', '.join(same)} in cdl.bib: "
                              f"{', '.join(same)} should merge into {key}")
        return plan
    if key_target(current) == target and not same_doi and not same \
            and not any(k in bib and same_work(bib[k], final) for k in bib if k != key and key_fits(k, target)):
        # no key-determining field (first-author surname, author count, year) changed:
        # a key that never followed the rule is kept (ChatGPT, not Open23)
        plan["detail"] = (f"{key} does not follow the ID rule ({target}), but no key-determining field changed: "
                          "kept")
        return plan
    plan["rename_reason"] = ("key does not follow the corrected metadata"
                             if key_fits(key, key_target(current) or "\0")
                             else "key already differed from the rule before this correction")
    group = [k for k in list(bib) + sorted(taken) if k != key and key_fits(k, target)]
    group = sorted(set(group))
    dup = [k for k in group if k in bib and same_work(bib[k], final)] or \
          [k for k in same_doi if key_fits(k, target)] or same
    if dup:
        plan.update(action="duplicate", merge_into=dup[0],
                    detail=f"same work already in cdl.bib as {dup[0]}: merge {key} into it")
        return plan
    if group:
        used = {k[len(target):] for k in group}
        new_suffix = next_suffix(used - {""} | ({"a"} if "" in used else set()))
        plan.update(action="collision", new_key=target + new_suffix, existing=group,
                    detail=f"{target} is taken by a different work ({', '.join(group)})")
        if "" in used:
            plan["also_rename"] = {target: target + "a"}
            plan["detail"] += f"; house suffix rule: {target} -> {target}a, new entry {target + new_suffix}"
        return plan
    new = target
    if new in reserved:
        plan["reserved_warning"] = f"{new} was renamed away to {reserved[new]}; citing papers may still use it"
    plan.update(action="rename", new_key=new)
    return plan


# ---------------------------------------------------------------- entry check

def flag(flags, code, field, detail, action="flag"):
    flags.append({"code": code, "field": field, "detail": detail, "action": action})


def year_evidence_quotes(f):
    return [e.get("quote", "") for e in (f or {}).get("evidence") or []]


NOT_PRINT_DATE = re.compile(r"online|digiti[sz]|electronic|epub|archive|scann|web|posted|deposit", re.I)


# The batch schema (PROTOCOL.md) has no structured field for a replacement candidate:
# the researchers write it in `notes`. These phrases name another version; a match
# preceded in its clause by 'no'/'not'/'never'/'without' ('No published version
# found', 'not the published version', 'Crossref has no is-preprint-of relation') does
# not count. 'journal version' is left out: it is mostly 'the journal version is cited'.
OTHER_VERSION = re.compile(r"replacement candidate|published version|is-preprint-of", re.I)
NEGATION = re.compile(r"\b(?:no|not|never|without)\b", re.I)


def other_version_named(notes):
    """The first phrase of `notes` that names another (published) version, or None."""
    for m in OTHER_VERSION.finditer(notes or ""):
        clause = re.split(r"[.;:()]\s", (notes or "")[:m.start()])[-1]
        if not NEGATION.search(clause[-30:]):
            return m[0]
    return None


def print_years_in_notes(notes):
    """Years the notes give as print dates: those in a clause that says print/printed
    (not reprint), except a year whose own part of the clause (split at parentheses,
    commas, 'but', 'while', 'whereas') calls it an online, digitisation, archive or
    deposit date and never print (AdelEtal95: 'Crossref record lacks volume/print year
    (its 2008 date is the online digitisation)' gives no print year)."""
    years = set()
    for clause in re.split(r";\s|\.\s|\n", notes or ""):
        c = clause.lower()
        if "reprint" in c:
            continue
        if re.search(r"\bprint(ed)?\b|published-print|print year|print edition|print issue", c):
            for part in re.split(r"[()\[\],]|\b(?:but|while|whereas)\b", clause):
                # 'pre-2000 SfN abstracts' names no date (ReccOKee89): a year glued to a
                # word by a hyphen is not read
                found = set(re.findall(r"(?<![A-Za-z]-)\b(?:19|20)\d{2}\b", part))
                if found and NOT_PRINT_DATE.search(part) and not re.search(r"\bprint", part, re.I):
                    continue
                years |= found
    return years


JANUARY_COVER_RES = (re.compile(r"\bDP\s+-\s+((?:19|20)\d{2})\s+Jan\b"),
                     re.compile(r"<PubDate>\s*<Year>((?:19|20)\d{2})</Year>\s*<Month>(?:Jan|January|0?1)</Month>"),
                     re.compile(r'printPublicationDate"?\s*:\s*"?((?:19|20)\d{2})-01\b'))


def january_cover_hosts(yfield, year):
    """Source hosts whose quoted print (cover) date is January of `year`: MEDLINE 'DP -
    1999 Jan', PubMed <PubDate><Year>1999</Year><Month>Jan</Month>, Europe PMC
    printPublicationDate 1999-01."""
    hosts = set()
    for e in (yfield or {}).get("evidence") or []:
        q = e.get("quote", "")
        if any(year in rx.findall(q) for rx in JANUARY_COVER_RES):
            hosts.add(urlparse(e.get("url", "")).netloc)
    return hosts


PRINT_DATE_RES = (re.compile(r'printPublicationDate"?\s*:\s*"?((?:19|20)\d{2})'),
                  re.compile(r"<PubDate>\s*<Year>((?:19|20)\d{2})"),
                  re.compile(r"\bDP\s+-\s+((?:19|20)\d{2})"),
                  re.compile(r"published-print\D{0,40}((?:19|20)\d{2})"))


def quoted_print_years(yfield):
    """{year: {source hosts}} of print dates quoted in the year evidence: Europe PMC
    printPublicationDate, PubMed <PubDate><Year> (the issue date), MEDLINE DP, Crossref
    published-print."""
    out = {}
    for e in (yfield or {}).get("evidence") or []:
        q, host = e.get("quote", ""), urlparse(e.get("url", "")).netloc
        for rx in PRINT_DATE_RES:
            for y in rx.findall(q):
                out.setdefault(y, set()).add(host)
    return out


def patent_like(row, current):
    urls = " ".join([row.get("identity", {}).get("url", "")] +
                    [e.get("url", "") for f in (row.get("fields") or {}).values()
                     for e in (f.get("evidence") or [])])
    return (current.get("ENTRYTYPE") == "patent" or "patent" in urls.lower()
            or re.search(r"\bpatent\b", row.get("notes", ""), re.I) is not None)


def field_name(name):
    """Canonical field name: 'ENTRYTYPE' for any case of entrytype, else lowercase."""
    return "ENTRYTYPE" if str(name).lower() == "entrytype" else str(name).lower()


def canonical_fields(d):
    """A field-keyed dict with canonical names; on a case clash the non-empty value wins."""
    out = {}
    for k, v in (d or {}).items():
        n = field_name(k)
        if n not in out or out[n] in (None, "", {}):
            out[n] = v
    return out


def canonical_review(review):
    if not review:
        return review
    review = dict(review)
    for part in ("suggested_value", "field_verdicts"):
        if review.get(part):
            review[part] = canonical_fields(review[part])
    return review


def is_removal(value):
    """A reviewer's suggested value that asks for the field to go ('remove', 'delete')."""
    return str(value or "").strip().lower().strip("()[] .") in ("remove", "delete", "drop", "remove field")


def reviewer_confirms(verdict_text):
    """A reviewer field verdict that confirms the researcher's value: 'agree ...' or
    'disagree (held but correct)'."""
    v = str(verdict_text or "").lower()
    return v.startswith("agree") or "held but correct" in v


def fetch_blocked(vfield, validation):
    """The validator could not read the source (not a wrong value): every failure is a
    fetch failure, or the whole page failed (identity quote and every field's quotes
    'not found', i.e. a block page was served)."""
    fails = (vfield or {}).get("failures") or []
    if not fails:
        return False
    if all(str(f).startswith("fetch failed") for f in fails):
        return True
    vf = (validation or {}).get("fields") or {}
    identity_failed = not ((validation or {}).get("identity") or {}).get("ok", True)
    return identity_failed and all(not v.get("ok", True) for v in vf.values()) and \
        all(f in ("quote not found at url",) or str(f).startswith("fetch failed") for f in fails)


def check_entry(row, current, bib, ctx, review=None, validation=None, decision=None):
    """Post-check one researcher row. Returns the per-key record. `decision` is the
    user's per-entry decision from crosswave/applied-decisions.json (field values it
    sets or withdraws; source 'user')."""
    key = row["key"]
    verdict = row.get("verdict")
    fields = canonical_fields(row.get("fields"))
    review = canonical_review(review)
    flags, norms = [], []
    applied = {}   # field -> {"value", "source", "evidence", ...}
    held = {}      # field -> reason
    removals = {}  # field -> reason
    suggestions = {}
    current = dict(current or {})

    if not current:
        flag(flags, "not_in_bib", None, f"{key} is not in cdl.bib", "held")

    # --- verdict consistency
    statuses = {f: (v or {}).get("status") for f, v in fields.items()}
    if verdict == "verified" and any(s == "corrected" for s in statuses.values()):
        flag(flags, "verdict_inconsistent", "verdict",
             "verdict 'verified' but fields are corrected: should be 'correction'")
    if verdict == "correction" and not any(s == "corrected" for s in statuses.values()):
        flag(flags, "verdict_inconsistent", "verdict", "verdict 'correction' with no corrected field")
    if verdict in ("ambiguous", "no_source") and len(statuses) >= 2 and \
            all(s in ("confirmed", "corrected") for s in statuses.values()) and \
            (row.get("identity") or {}).get("quote"):
        flag(flags, "verdict_understated", "verdict",
             f"verdict '{verdict}' but identity is quoted and every field is confirmed/corrected")

    vfields = canonical_fields((validation or {}).get("fields"))
    if validation and verdict != "no_source" and not (validation.get("identity") or {}).get("ok", True):
        flag(flags, "identity_quote_failed", "identity",
             f"identity quote not found at source: {validation['identity'].get('why')}")

    # --- researcher fields
    for name, f in fields.items():
        f = f or {}
        status, value = f.get("status"), f.get("value")
        if verdict == "no_source" or status not in ("confirmed", "corrected"):
            if value not in (None, "") and str(value) != current.get(name, "" if name != "ENTRYTYPE" else current.get("ENTRYTYPE")):
                suggestions[name] = value
            continue
        if value is None or str(value).strip() == "":
            if current.get(name):
                flag(flags, "empty_value", name,
                     f"researcher proposed an empty {name} (current {current.get(name)!r}); never applied, "
                     "a removal needs the user's decision", "held")
            else:
                flag(flags, "empty_value", name, f"researcher proposed an empty {name}; never applied", "held")
            continue
        v = vfields.get(name)
        if v is not None and not v.get("ok", True):
            missing = v.get("value_missing_from_quotes") or []
            ac = address_country(value) if name == "address" else None
            if ac and missing and not v.get("failures") \
                    and set(fold(" ".join(missing)).split()) <= set(fold(ac[1]).split()) \
                    and not country_printed(ac[2], address_quotes(fields)):
                # the quotes cover the address except the country no source prints:
                # the country goes (user rule) and the hold with it (BuzsEtal94 'Germany')
                if ac[0]:
                    applied[name] = {"value": ac[0], "source": "researcher", "status": status,
                                     "evidence": f.get("evidence") or [], "normalised_from": str(value)}
                flag(flags, "country_dropped", name,
                     f"{value!r}: the quotes cover it except the country {ac[1]!r}, which no quote prints; "
                     + (f"country dropped: {ac[0]!r}" if ac[0] else "the address is only a country: not applied")
                     + " (user rule, cross-wave q-country)", "applied")
                continue
            flag(flags, "quote_check_failed", name,
                 f"validator: {name} not covered by its quotes (missing {missing}; failures {v.get('failures')})",
                 "held")
            held[name] = "quote check failed"
            continue
        applied[name] = {"value": str(value), "source": "researcher", "status": status,
                         "evidence": f.get("evidence") or []}

    open_fields = sorted(n for n, f in fields.items() if (f or {}).get("status") == "not_found")
    if verdict in ("verified", "correction"):
        for n in open_fields:
            flag(flags, "field_not_found", n,
                 f"verdict '{verdict}' but {n} is not_found: the entry is not fully verified")

    # --- patents: grant year, never filing/priority
    if patent_like(row, current):
        yf = fields.get("year") or {}
        quotes = " ".join(year_evidence_quotes(yf)).lower()
        grant = re.findall(r"(?:grant(?:ed)?|issued|issue date|publication of grant)\D{0,20}((?:19|20)\d{2})",
                           row.get("notes", ""), re.I)
        if re.search(r"fil(?:ed|ing)|priority|application|submitted|applied", quotes):
            if "year" in applied:
                del applied["year"]
            held["year"] = "patent year taken from a filing/priority date"
            flag(flags, "patent_filing_year", "year",
                 "patent year evidence is a filing/priority/application date; a patent is dated by its "
                 f"grant (issue) year{'; notes give grant year ' + grant[0] if grant else ''}", "held")
            if grant and grant[0] != current.get("year"):
                suggestions["year"] = grant[0]
        elif "year" in applied and not re.search(r"grant|issue|publication", quotes):
            flag(flags, "patent_year_unproven", "year",
                 "patent year evidence does not state a grant/issue date")
        if not re.search(r"patent", " ".join(str(current.get(k, "")) + " " +
                                              str((applied.get(k) or {}).get("value", ""))
                                              for k in ("howpublished", "note", "number", "publisher")), re.I):
            flag(flags, "patent_number_missing", "howpublished",
                 "patent entry does not record the patent number (e.g. Howpublished = {{U.S.} Patent N})")

    # --- reviewer merge
    reviewer_key = None
    reviewer_removes = set()

    def resolve_hold(name, why):
        for f in flags:
            if f["field"] == name and f["code"] == "quote_check_failed" and f["action"] == "held":
                f["action"] = "applied"
                f["detail"] += f"; {why} (source reviewer)"

    if review:
        sv = review.get("suggested_value") or {}
        verdicts = review.get("field_verdicts") or {}
        for name, value in sv.items():
            if name == "key":
                m = re.match(r"\s*([A-Za-z][A-Za-z\-]*\d{2}[a-z]*)", str(value or ""))
                if not m:  # a key outside the ID rule, named as it is ('ChatGPT')
                    m = re.match(r"\s*([A-Za-z][\w\-]*)\b", str(value or ""))
                    m = m if m and (m[1] == key or m[1] in bib) else None
                reviewer_key = {"text": value, "key": m[1] if m else None}
                continue
            if name == "action":
                flag(flags, "reviewer_action", None, str(value))
                continue
            if value is None or str(value).strip() == "":
                if name in applied:
                    del applied[name]
                    flag(flags, "reviewer_dropped", name,
                         f"reviewer withdrew the proposed {name}; not applied", "dropped")
                continue
            if is_removal(value):  # 'remove' is an instruction, never a value (AbdeEtal21 force)
                applied.pop(name, None)
                reviewer_removes.add(name)
                continue
            applied[name] = {"value": str(value), "source": "reviewer",
                             "evidence": [{"reviewer_problems": review.get("problems") or []}]}
            if name in held:
                held.pop(name)
                resolve_hold(name, "reviewer supplied the value")
        for name, verdict_f in verdicts.items():
            if str(verdict_f).lower().startswith("disagree") and not reviewer_confirms(verdict_f) \
                    and name in applied and applied[name]["source"] == "researcher" and name not in sv:
                del applied[name]
                flag(flags, "reviewer_disagrees", name,
                     f"reviewer disagrees ({verdict_f}) and gave no replacement value; not applied", "held")
            elif name in held and name not in sv and reviewer_confirms(verdict_f) \
                    and fetch_blocked(vfields.get(name), validation):
                f = fields.get(name) or {}
                value = f.get("value")
                if value not in (None, "") and str(value).strip():
                    applied[name] = {"value": str(value), "source": "reviewer", "status": f.get("status"),
                                     "evidence": (f.get("evidence") or []) +
                                     [{"reviewer_confirmed": verdict_f,
                                       "reviewer_problems": review.get("problems") or []}]}
                    held.pop(name)
                    resolve_hold(name, "validator could not fetch the source; reviewer confirmed "
                                       f"the value ({verdict_f})")

    # --- ambiguous verdict: the identity-defining changes (title, year, DOI, venue) are
    # one decision for the user, never applied piecemeal (Ebbi85 got the 1913
    # translation's title and DOI with the original's year 1885)
    if verdict == "ambiguous":
        ident = {n: applied[n]["value"] for n in IDENTITY_FIELDS
                 if n in applied and str(applied[n]["value"]) != str(current.get(n, ""))}
        for n, v in ident.items():
            applied.pop(n)
            held[n] = "verdict ambiguous: identity-defining change held for the user"
            suggestions[n] = v
        if ident:
            flag(flags, "ambiguous_identity_held", ", ".join(ident),
                 "verdict ambiguous: the identity-defining changes are one decision for the user, held together: " +
                 "; ".join(f"{n}={v!r}" for n, v in ident.items()), "held")

    # --- the user's decision for this entry (cross-wave page): withdrawn proposals and
    # values the user chose (source 'user'); holds on those fields are superseded
    user_fields = {}
    if decision:
        withdraw = [field_name(n) for n in decision.get("withdraw") or []]
        chosen = {field_name(n): s for n, s in (decision.get("set") or {}).items()}
        fetch = ctx.get("fetch") or http_get
        for n in withdraw:
            applied.pop(n, None)
            held.pop(n, None)
            suggestions.pop(n, None)
        for n, spec in chosen.items():
            own = spec.get("evidence") or []
            ev = own or (fields.get(n) or {}).get("evidence") or []
            applied[n] = {"value": str(spec["value"]), "source": "user", "evidence": ev,
                          "decision": decision.get("decision")}
            held.pop(n, None)
            suggestions.pop(n, None)
            user_fields[n] = spec["value"]
            for e in own:  # the user's value has its own source: its quotes are checked
                status_, body = fetch(e["url"])
                if status_ != 200 or not quote_found(e["quote"], body):
                    flag(flags, "user_evidence_unverified", n,
                         f"quote {e['quote']!r} not found at {e['url']} (HTTP {status_})")
        decided = set(withdraw) | set(chosen)
        for f in flags:
            fs = {field_name(x.strip()) for x in str(f["field"] or "").split(",") if x.strip()}
            if f["action"] == "held" and fs and fs <= decided:
                f["action"] = "dropped"
                f["detail"] += f"; superseded by the user's decision ({decision.get('decision')})"
        if decided:
            flag(flags, "user_decision", ", ".join(sorted(decided)),
                 f"{decision.get('decision')}: " + "; ".join(
                     [f"{n} = {v['value']!r}" for n, v in chosen.items()] +
                     ([f"research proposals withdrawn for {', '.join(n for n in withdraw if n not in chosen)}"]
                      if any(n not in chosen for n in withdraw) else [])), "applied")

    # --- DOI registration and record match
    doi_status = None
    if "doi" in applied and clean_doi(applied["doi"]["value"]) == clean_doi(current.get("doi")) \
            and applied["doi"]["source"] == "researcher":
        # the entry's own DOI, confirmed: no change, so nothing to check or drop (Thor13's
        # spurious 'DOI change dropped' on its existing DOI)
        applied["doi"]["value"] = current["doi"]
    elif "doi" in applied:
        doi = clean_doi(applied["doi"]["value"])
        applied["doi"]["value"] = doi
        rec = ctx["doi"](doi)
        doi_status = rec
        if rec.get("registered") is False:
            del applied["doi"]
            flag(flags, "doi_unregistered", "doi",
                 f"{doi} is not a registered DOI ({rec.get('error')}); DOI change dropped", "dropped")
        elif rec.get("registered") is None:
            del applied["doi"]
            flag(flags, "doi_check_failed", "doi", f"{doi}: {rec.get('error')}; held", "held")
        elif not (rec.get("title") or "").strip():
            del applied["doi"]
            flag(flags, "doi_title_unavailable", "doi",
                 f"{doi}: {rec.get('error') or 'the registry record has no title'}; held", "held")
        else:
            record_title = rec["title"] + (": " + rec["subtitle"] if rec.get("subtitle") else "")
            cands = [c for c in ((applied.get("title") or {}).get("value"), current.get("title"),
                                 (applied.get("chapter") or {}).get("value"), current.get("chapter"),
                                 (applied.get("booktitle") or {}).get("value"), current.get("booktitle"))
                     if c]
            authors_now = split_names((applied.get("author") or {}).get("value") or current.get("author", ""))
            if ZENODO_DOI.search(doi):
                # a release title carries its version ('Brain Imaging Analysis Kit v0.2');
                # software is cited without one (user rule), so versions are not part numbers
                rec = dict(rec, title=strip_version(rec["title"]),
                           subtitle=strip_version(rec["subtitle"]) if rec.get("subtitle") else None)
                cands = [strip_version(c) for c in cands]
                record_title = rec["title"]
            title_verdict, why = doi_title_verdict(
                rec, cands, (applied.get("volume") or {}).get("value") or current.get("volume"),
                (applied.get("pages") or {}).get("value") or current.get("pages"),
                first_author=surname(normalise_name(authors_now[0])[0]) if authors_now else None,
                year=(applied.get("year") or {}).get("value") or current.get("year"),
                issue=(applied.get("number") or {}).get("value") or current.get("number"),
                journal=(applied.get("journal") or {}).get("value") or current.get("journal"))
            rv_doi = str(((review or {}).get("field_verdicts") or {}).get("doi") or "")
            confirmed = applied["doi"]["source"] == "reviewer" or reviewer_confirms(rv_doi) \
                or "but correct" in rv_doi.lower()
            if title_verdict in ("part_number", "short") and not confirmed:
                del applied["doi"]
                held["doi"] = why
                flag(flags, "doi_title_part_number" if title_verdict == "part_number" else "doi_title_short", "doi",
                     f"{doi} is registered to {record_title!r} ({rec.get('ra')}): {why}; held", "held")
            elif title_verdict is None:
                del applied["doi"]
                flag(flags, "doi_title_mismatch", "doi",
                     f"{doi} is registered to {record_title!r} ({rec.get('ra')}), not this entry's title; "
                     "DOI change dropped", "dropped")
            else:
                if title_verdict == "near":
                    flag(flags, "doi_title_near", "doi", f"{doi} is registered to {record_title!r}: {why}; applied",
                         "applied")
                elif title_verdict == "generic":
                    flag(flags, "doi_generic_title", "doi", f"{doi} is registered to {record_title!r}: {why}; "
                                                            "applied", "applied")
                elif title_verdict == "part_number_page":
                    flag(flags, "doi_title_part_number", "doi",
                         f"{doi} is registered to {record_title!r}: {why}; applied", "applied")
                elif title_verdict != "match":
                    flag(flags, "doi_title_part_number" if title_verdict == "part_number" else "doi_title_short",
                         "doi", f"{doi} is registered to {record_title!r}: {why}; applied: the reviewer "
                                f"confirms the DOI ({rv_doi or 'reviewer value'})", "applied")
                rec_pages = re.sub(r"(?<!-)[-–](?!-)", "--", rec["page"]) if rec.get("page") else None
                if rec_pages and re.fullmatch(r"(\w+)--\1", rec_pages):
                    rec_pages = rec_pages.split("--")[0]  # a one-page item deposited as '1005-1005' (Mitc09)
                pages = (applied.get("pages") or {}).get("value") or current.get("pages")
                if rec_pages and pages and rec_pages != pages:
                    flag(flags, "doi_record_conflict", "pages",
                         f"{rec.get('ra')} record of {doi} gives pages {rec['page']!r}, proposal {pages!r}")
                year = (applied.get("year") or {}).get("value") or current.get("year")
                print_hosts = quoted_print_years(fields.get("year")).get(year) or set()
                if rec.get("print_year") and year and rec["print_year"] != year and len(print_hosts) >= 2:
                    flag(flags, "doi_record_conflict", "year",
                         f"{rec.get('ra')} published-print {rec['print_year']} vs the print date {year} quoted "
                         f"from {len(print_hosts)} sources {sorted(print_hosts)}: the corroborated print date "
                         f"stands; the {rec.get('ra')} deposit year is not suggested")
                elif rec.get("print_year") and year and rec["print_year"] == str(int(year) - 1) \
                        and january_cover_hosts(fields.get("year"), year) \
                        and rec.get("volume") and str(rec["volume"]).strip() == str(
                            (applied.get("volume") or {}).get("value") or current.get("volume") or "").strip():
                    # a January issue printed (or deposited) late the year before: the
                    # cover date of that volume is the citation year (WiggEtal99)
                    flag(flags, "doi_record_conflict", "year",
                         f"{rec.get('ra')} published-print {rec['print_year']} vs the January {year} cover date of "
                         f"volume {rec['volume']} quoted from {sorted(january_cover_hosts(fields.get('year'), year))}: "
                         f"the cover year stands; the {rec.get('ra')} year is not suggested")
                elif rec.get("print_year") and year and rec["print_year"] != year:
                    flag(flags, "print_year_conflict", "year",
                         f"{rec.get('ra')} published-print {rec['print_year']} vs year {year}: print year wins")
                    suggestions.setdefault("year", rec["print_year"])
                elif not rec.get("print_year") and rec.get("issued_year") and year \
                        and rec["issued_year"] != year:
                    flag(flags, "doi_record_conflict", "year",
                         f"{rec.get('ra')} record of {doi} is dated {rec['issued_year']}, proposal {year}")

    # --- software / Zenodo releases: the FIRST version's DOI and year (user rule,
    # cross-wave q-brainiak); the version number itself is removed with the house rules
    software = None
    zdoi = clean_doi((applied.get("doi") or {}).get("value") if "doi" in applied else current.get("doi"))
    if verdict != "no_source" and ZENODO_DOI.search(zdoi or "") and "doi" not in held:
        first = zenodo_first_version(zdoi, ctx.get("fetch") or http_get)
        software = {"doi": zdoi, "first": first}
        if first.get("error"):
            flag(flags, "software_first_version_unresolved", "doi",
                 f"{zdoi}: first version not resolved ({first['error']}); DOI and year left as they are", "held")
        else:
            ev = [{"url": first["url"], "record": {k: first[k] for k in ("doi", "date", "version", "title", "concept")}}]
            if first["doi"] != zdoi:
                reg = ctx["doi"](first["doi"])
                if reg.get("registered") is True:
                    applied["doi"] = {"value": first["doi"], "source": "postcheck", "evidence": ev,
                                      "normalised_from": zdoi}
                    doi_status = reg
                    flag(flags, "software_first_version", "doi",
                         f"{zdoi} is " + ("the concept DOI (it resolves to the latest version)"
                                          if zdoi.endswith("." + str(first["concept"])) else "not the first version")
                         + f" of Zenodo release series {first['concept']}: cite the "
                         f"first version {first['doi']} ({first['date']}, version {first['version']!r}; user rule)",
                         "applied")
                else:
                    flag(flags, "software_first_version_unresolved", "doi",
                         f"first version {first['doi']} of {zdoi} is not a registered DOI ({reg.get('error')}); held",
                         "held")
            year = (applied.get("year") or {}).get("value") or current.get("year")
            if first["year"] and first["year"] != year and "software_first_version_unresolved" not in \
                    {f["code"] for f in flags}:
                applied["year"] = {"value": first["year"], "source": "postcheck", "evidence": ev,
                                   **({"normalised_from": applied["year"]["value"]} if "year" in applied else {})}
                held.pop("year", None)
                suggestions.pop("year", None)
                flag(flags, "software_first_version", "year",
                     f"year {year} -> {first['year']}: the first version {first['doi']} is dated {first['date']} "
                     "(user rule: the year comes from the first version)", "applied")
            fams = {fold(c.split(",")[0] if "," in c else (c.split() or [""])[-1]) for c in first["creators"]}
            cited = {fold(surname(n)) for n in split_names((applied.get("author") or {}).get("value")
                                                           or current.get("author", "")) if n != "others"}
            if fams and cited and fams != cited:
                flag(flags, "software_first_version_authors", "author",
                     f"the first version {first['doi']} lists {len(first['creators'])} creator(s) "
                     f"({', '.join(first['creators'][:6])}{', ...' if len(first['creators']) > 6 else ''}); the entry's "
                     f"author list differs (only in the first version: {sorted(fams - cited)[:6]}; only in the "
                     f"entry: {sorted(cited - fams)[:6]}); authors left as they are for the user")

    # --- print year from notes / year evidence
    year_now =(applied.get("year") or {}).get("value") or current.get("year")
    note_prints = print_years_in_notes(row.get("notes"))
    corroborated = len(quoted_print_years(fields.get("year")).get(year_now) or ()) >= 2
    # a conference paper is cited by its conference year: a later print of the
    # proceedings (Curran's NeurIPS reprints, VaswEtal17 2017 printed 2018) is not the
    # paper's print year when the year's own evidence quotes the conference year
    venue = str((applied.get("booktitle") or {}).get("value") or current.get("booktitle") or "")
    etype_now = str((applied.get("ENTRYTYPE") or {}).get("value") or current.get("ENTRYTYPE") or "").lower()
    conference_year = bool(year_now) and (etype_now in ("inproceedings", "conference") or PROCEEDINGS_RE.search(venue)) \
        and any(re.search(r"(?<!\d)" + re.escape(year_now) + r"(?!\d)", q)
                for q in year_evidence_quotes(fields.get("year")))
    if note_prints and year_now and year_now not in note_prints and not corroborated and conference_year:
        flag(flags, "proceedings_print_year", "year",
             f"notes give a print date {sorted(note_prints)} of the proceedings; the conference year {year_now} is "
             "quoted and stands (no year suggested)", "applied")
    elif note_prints and year_now and year_now not in note_prints and not corroborated:
        flag(flags, "print_year_conflict", "year",
             f"notes give a print date {sorted(note_prints)} but the year is {year_now}: print year wins")
        if len(note_prints) == 1:
            suggestions.setdefault("year", next(iter(note_prints)))
    yq = " ".join(year_evidence_quotes(fields.get("year"))).lower()
    if "year" in applied and applied["year"]["source"] == "researcher" and \
            re.search(r"published-online|first published online|epub|online", yq) and \
            not re.search(r"published-print|print", yq):
        flag(flags, "year_from_online_date", "year",
             "year evidence is an online-publication date; the print year wins")

    # --- a different publisher next to a held or unsupported address: one decision
    # (Herb34: the 1891 Langensalza publisher applied, the 1834 'K\\"onigsberg' kept)
    if "publisher" in applied and current.get("address") and "address" not in applied \
            and different_publisher(applied["publisher"]["value"], current.get("publisher", "")):
        new_pub = applied.pop("publisher")["value"]
        held["publisher"] = "a different publisher needs its address, which is held or unsupported"
        suggestions["publisher"] = new_pub
        addr = (fields.get("address") or {}).get("value")
        flag(flags, "publisher_address_held", "publisher, address",
             f"publisher {current.get('publisher')!r} -> {new_pub!r} but the address {current['address']!r} is "
             + (f"held ({held['address']}; proposed {addr!r})" if "address" in held else
                f"not supported for the new publisher (proposed {addr!r})" if addr else "not supported by any source")
             + "; publisher and address are one decision for the user, both kept as they are", "held")

    # --- final entry before house rules
    final = dict(current)
    for name, a in applied.items():
        final[name] = a["value"]

    def set_norm(name, new, notes):
        if not notes or new == final.get(name):
            return
        final[name] = new
        norms.extend({"field": name, "note": n} for n in notes)
        if name in applied:
            applied[name].setdefault("normalised_from", applied[name]["value"])
            applied[name]["value"] = new
        else:
            applied[name] = {"value": new, "source": "postcheck", "evidence": []}

    # ENTRYTYPE; @conference -> @inproceedings only with a proceedings booktitle,
    # otherwise @misc for the user to check (Laks01: a speech, no proceedings)
    def conference_to(why_from):
        venue = final.get("booktitle") or final.get("journal") or ""
        if venue and PROCEEDINGS_RE.search(venue):
            return "inproceedings", [f"{why_from} -> @inproceedings"]
        flag(flags, "conference_without_proceedings", "ENTRYTYPE",
             f"{why_from} without a proceedings booktitle ({venue!r}): @misc, not @inproceedings "
             "(house rule @conference -> @inproceedings needs a proceedings volume)")
        return "misc", [f"{why_from} -> @misc (no proceedings booktitle)"]

    if "ENTRYTYPE" in applied:
        raw_type = str(applied["ENTRYTYPE"]["value"] or "").strip().lower().lstrip("@")
        et, notes, bad = normalise_entrytype(applied["ENTRYTYPE"]["value"])
        if bad:
            del applied["ENTRYTYPE"]
            final["ENTRYTYPE"] = current.get("ENTRYTYPE")
            flag(flags, "invalid_entrytype", "ENTRYTYPE", bad + "; not applied", "dropped")
        else:
            if raw_type == "conference":
                et, notes = conference_to("@conference")
            set_norm("ENTRYTYPE", et, notes)
    elif final.get("ENTRYTYPE") == "conference" and applied:
        set_norm("ENTRYTYPE", *conference_to("@conference"))

    # titled chapter: @inbook{title=book, chapter=chapter} -> @incollection
    chap = final.get("chapter", "")
    if final.get("ENTRYTYPE") in ("inbook", "incollection") and chap and not re.fullmatch(r"[\dIVXivx]+", chap) \
            and verdict in ("no_source", "ambiguous"):
        flag(flags, "chapter_move_held", "chapter",
             f"verdict {verdict}: the titled-chapter move (@incollection, title = chapter, booktitle = book) "
             "is left for the user", "held")
    elif final.get("ENTRYTYPE") in ("inbook", "incollection") and chap and not re.fullmatch(r"[\dIVXivx]+", chap):
        bt_now = final.get("booktitle")
        rt = (applied.get("title") or {}).get("value") \
            if (applied.get("title") or {}).get("source") in ("researcher", "reviewer") else None
        if rt and bt_now and titles_match(rt, bt_now):
            rt = None  # the researcher's title is the book's
        researcher_book = (fields.get("booktitle") or {}).get("value")
        if researcher_book and titles_match(researcher_book, chap) and not titles_match(final.get("title", ""), chap):
            # the chapter field holds the BOOK title (Stey01, BairNoma78): the title is
            # already the chapter's; the chapter field becomes the booktitle, never the title
            chapter_title, book, how = final.get("title", ""), bt_now or chap, "chapter field holds the book title"
        elif rt and not titles_match(rt, current.get("title", "")):
            # the researcher corrected the chapter title in title: it wins over the cited
            # chapter field (GoldEtal08 'Neural integrator models', Howa08, BoraEtal05)
            chapter_title, book, how = rt, bt_now or current.get("title"), "researcher's corrected title"
        else:
            chapter_title = chap
            book = bt_now or (final.get("title") if not titles_match(final.get("title", ""), chap)
                              else current.get("title"))
            how = "cited chapter field"
        if book and not titles_match(book, chapter_title):
            bt = guarded(book, H.format_journal_name(book))
            if bt is None:
                bt = book
                flag(flags, "booktitle_case", "booktitle",
                     f"house title-case formatter would alter protected text in {book!r}; "
                     "booktitle kept as given, check its title case")
            set_norm("ENTRYTYPE", "incollection", ["titled chapter: @inbook -> @incollection"]
                     if final.get("ENTRYTYPE") == "inbook" else ["chapter field folded into title"])
            set_norm("booktitle", bt, [f"book title moved to booktitle: {bt!r}"])
            if chapter_title != final.get("title"):
                set_norm("title", chapter_title, [f"chapter title moved to title ({how}): {chapter_title!r}"])
                if how == "cited chapter field" and "title" in applied:
                    applied["title"]["source"] = "postcheck"  # not the researcher's value
            final.pop("chapter", None)
            applied.pop("chapter", None)
            if "chapter" in current:
                removals["chapter"] = ("moved into booktitle (it held the book title)" if how.startswith("chapter field")
                                       else "moved into title (@incollection house form)")

    # titled chapter already split into title + booktitle: @inbook -> @incollection
    if final.get("ENTRYTYPE") == "inbook" and not final.get("chapter") and final.get("booktitle") \
            and final.get("title") and verdict != "no_source":
        set_norm("ENTRYTYPE", "incollection", ["titled chapter with booktitle: @inbook -> @incollection"])

    # a contained type never loses its last venue: when the proposed booktitle is held
    # or dropped, the type change and the journal removal are not applied either
    # (GatyEtal16, IsolEtal17, LiEtal24a ended as @inproceedings with no venue)
    researcher_removes = {field_name(n) for n in row.get("remove") or []}
    booktitle_lost = "booktitle" in held or any(f["field"] == "booktitle" and f["action"] in ("held", "dropped")
                                                for f in flags)
    if final.get("ENTRYTYPE") in CONTAINED_TYPES and final.get("ENTRYTYPE") != current.get("ENTRYTYPE") \
            and not final.get("booktitle") and booktitle_lost and current.get("ENTRYTYPE"):
        proposed = final["ENTRYTYPE"]
        applied.pop("ENTRYTYPE", None)
        final["ENTRYTYPE"] = current["ENTRYTYPE"]
        held["ENTRYTYPE"] = f"@{proposed} needs the held booktitle"
        researcher_removes.discard("journal")
        suggestions.setdefault("ENTRYTYPE", proposed)
        flag(flags, "venue_held", "ENTRYTYPE",
             f"@{current['ENTRYTYPE']} -> @{proposed} with the journal removed would leave no venue: the booktitle "
             f"is held ({held.get('booktitle', 'not applied')}); type, journal and booktitle are one decision for the "
             "user, the entry is kept as it is", "held")

    # a chapter or proceedings paper has no journal: drop it, or move it to the
    # booktitle (none yet) or series (a book series given as the journal)
    if final.get("ENTRYTYPE") in CONTAINED_TYPES and final.get("journal"):
        journal = final["journal"]
        bt, series = final.get("booktitle", ""), final.get("series", "")
        fj, fbt = fold(journal), fold(bt)
        removed = "journal" in researcher_removes  # the researcher's remove list wins over a move (NeweRose81)
        if not bt and removed:
            why = "the researcher asked to remove it; not moved to booktitle"
        elif not bt:
            set_norm("booktitle", journal, [f"@{final['ENTRYTYPE']}: journal {journal!r} moved to booktitle"])
            why = "moved to booktitle"
        elif fbt == fj or fbt.startswith(fj + " ") or (series and fold(series) == fj):
            why = "already given by the " + ("series" if series and fold(series) == fj else "booktitle")
            vol = final.get("volume", "").strip()
            rest = fbt[len(fj):].split() if fbt.startswith(fj + " ") else []
            if vol and not series and rest and (rest[0] == vol or rest[0] == roman(vol)):
                applied.pop("volume", None)
                final.pop("volume", None)
                norms.append({"field": "volume", "note": f"series number {vol} is in the booktitle {bt!r}"})
                if current.get("volume"):
                    removals["volume"] = f"series number already in the booktitle {bt!r}"
        elif same_venue(journal, bt):
            why = f"names the same venue as the booktitle {bt!r}"
        elif not series and removed:
            why = "the researcher asked to remove it; not moved to series"
        elif not series:
            set_norm("series", journal, [f"@{final['ENTRYTYPE']}: journal {journal!r} is a book series; moved to series"])
            why = "moved to series"
        else:
            why = f"not a field of @{final['ENTRYTYPE']} (booktitle {bt!r}, series {series!r} kept)"
        applied.pop("journal", None)
        final.pop("journal", None)
        norms.append({"field": "journal", "note": f"@{final['ENTRYTYPE']} has no journal: {why}"})
        if current.get("journal"):
            removals["journal"] = f"@{final['ENTRYTYPE']} has no journal ({why})"

    # names
    for name in NAME_FIELDS:
        if name in applied:
            new, notes = normalise_names(applied[name]["value"])
            bad = [n for n in notes if "could not parse" in n or "cannot parse" in n]
            for b in bad:
                flag(flags, "name_unparsed", name, b)
            set_norm(name, new, [n for n in notes if n not in bad])
            names_, house_notes = [], []
            for n in split_names(applied[name]["value"]):
                hn, note = house_surname(n, bib, exclude=current)
                names_.append(hn)
                if note:
                    house_notes.append(note)
            set_norm(name, " and ".join(names_), house_notes)
            # a full word after the initials is braced into the surname only when a
            # source prints that compound as the family name (never on a guess)
            fams = source_families((fields.get(name) or {}).get("evidence"),
                                   doi_status if name == "author" and (doi_status or {}).get("registered") else None)
            names_, brace_notes = [], []
            for n in split_names(applied[name]["value"]):
                mw = mid_word_surname(n)
                if mw and fold(mw[1]) in fams:
                    n = f"{mw[0]} {{{mw[1]}}}"
                    brace_notes.append(f"compound surname braced as the source prints it: {n!r}")
                names_.append(n)
            set_norm(name, " and ".join(names_), brace_notes)

    # single-source surname change: a new surname that respells a cited one is held,
    # i.e. that author keeps the cited name, unless the reviewer confirms the author
    if "author" in applied and applied["author"]["source"] == "researcher" and current.get("author"):
        strip = surname_key
        old = {}
        for n in split_names(current["author"]):
            if n != "others":
                old.setdefault(strip(n), n)
                old.setdefault(strip(normalise_name(n)[0]), n)  # 'B A L Di Leone' = 'B A L {Di Leone}'
        old_noacc = {fold(o).replace(" ", "") for o in old}
        ev = (fields.get("author") or {}).get("evidence") or []
        # the DOI record the post-check fetched (and kept) is a source host too
        reg = doi_status if doi_status and "doi" in applied else None
        reg_names = fold(" ".join(reg.get("authors") or [])).split() if reg else []
        reg_host = {"Crossref": "api.crossref.org", "DataCite": "api.datacite.org"}.get((reg or {}).get("ra"), "doi record")
        rv_author = ((review or {}).get("field_verdicts") or {}).get("author")
        release = bool(review) and reviewer_confirms(rv_author)
        out, kept, released = [], [], []
        cited_list = [n for n in split_names(current["author"])]
        for pos, n in enumerate(split_names(final["author"])):
            new = strip(n)
            if cited_list and cited_list[-1] == "others" and pos >= len(cited_list) - 1:
                out.append(n)  # expands the cited 'and others': an added author (YangEtal24)
                continue
            if not new or new in old or n == "others":
                out.append(n)
                continue
            near = sorted(((difflib.SequenceMatcher(None, o, new).ratio(), o) for o in old if o), reverse=True)
            near = [o for r, o in near if r >= 0.75]
            if not near or any(o.replace(" ", "") == new.replace(" ", "") for o in near) \
                    or surname_without_accented(n).replace(" ", "") in old_noacc:
                out.append(n)  # an added or reordered author, a brace/spacing fix, or a restored accent
                continue
            last = new.split()[-1]
            quoted = {urlparse(e.get("url", "")).netloc for e in ev if last in fold(e.get("quote", "")).split()}
            hosts = set(quoted)
            deposited = []
            if last in reg_names:
                hosts.add(reg_host)
            if len(hosts) < 2:
                # an author-deposited record (arXiv, Zenodo) fetched from a host the
                # researcher did not quote is a second host (CaliVita05: arXiv
                # cs/0412098 'Rudi Cilibrasi'; ChanEtal20: Zenodo 'Geerligs, Linda')
                for host, why in deposited_witnesses(row, final, ctx, last):
                    if host not in hosts:
                        hosts.add(host)
                        deposited.append(why)
            if len(hosts) >= 2:
                out.append(n)
                if deposited:
                    flag(flags, "surname_corroborated", "author",
                         f"surname {near[0]!r} -> {new!r}: released by the deposited-record rule, "
                         f"{'; '.join(deposited)} is the second host {sorted(hosts)}", "applied")
                elif len(quoted) < 2:
                    flag(flags, "surname_corroborated", "author",
                         f"surname {near[0]!r} -> {new!r}: released by the DOI record rule, the {reg_host} "
                         f"record of the kept DOI is the second host {sorted(hosts)}", "applied")
                continue
            # the corrected spelling is already cdl.bib's for this person (same surname,
            # compatible initials, in another entry) and the cited spelling is not:
            # a second, independent witness (TulvThom73: editor 'D M Thomson')
            cited_name = next((c for c in cited_list if near[0] in (strip(c), strip(normalise_name(c)[0]))),
                              old[near[0]])
            new_uses = house_name_uses(bib, n, exclude_key=key)
            old_uses = house_name_uses(bib, cited_name, exclude_key=key)
            if hosts and new_uses and not old_uses:
                out.append(n)
                flag(flags, "surname_corroborated", "author",
                     f"surname {near[0]!r} -> {new!r}: released by the cdl.bib rule, {sorted(hosts)} plus "
                     f"cdl.bib's own spelling for this person in {', '.join(new_uses[:5])} (the cited "
                     "spelling is in no other entry)", "applied")
                continue
            detail = (f"surname {near[0]!r} -> {new!r} rests on {len(hosts)} source host(s) {sorted(hosts)}; "
                      "single-source surname changes need corroboration or the user's sign-off")
            if release:
                flag(flags, "surname_single_source", "author",
                     detail + f"; applied: the reviewer confirms the author ({rv_author})", "applied")
                out.append(n)
                released.append(n)
            else:
                # the whole cited name, house format; of several cited authors with that
                # surname (YangEtal24's Yangs), the one at the same position
                same = [c for c in cited_list if near[0] in (strip(c), strip(normalise_name(c)[0]))]
                pick = cited_list[pos] if pos < len(cited_list) and cited_list[pos] in same else old[near[0]]
                cited = normalise_name(pick)[0]
                flag(flags, "surname_single_source", "author",
                     detail + f"; held: the cited name {cited!r} is kept", "held")
                out.append(cited)
                kept.append(cited)
        if released:
            applied["author"]["source"] = "reviewer"
            applied["author"]["evidence"] = list(applied["author"]["evidence"]) + [
                {"reviewer_confirmed": rv_author, "reviewer_problems": review.get("problems") or []}]
        if kept:
            value = " and ".join(out)
            final["author"] = value
            applied["author"]["value"] = value
            held["author"] = "single-source surname respelling not applied; kept as cited: " + ", ".join(kept)

    for name in list(applied):
        a = applied[name]
        v = a["value"]
        if name == "number":
            set_norm(name, *normalise_number(v))
        elif name == "pages":
            set_norm(name, *normalise_pages(v))
        elif name == "booktitle":
            set_norm(name, *normalise_booktitle(v))
        elif name == "edition":
            set_norm(name, *normalise_edition(v))
        elif name == "address":
            ac = address_country(v)
            own = [str(e.get("quote", "")) for e in a.get("evidence") or [] if isinstance(e, dict)]
            if ac and not country_printed(ac[2], own + address_quotes(fields)):
                if not any(f["code"] == "country_dropped" and f["detail"].startswith(repr(v)) for f in flags):
                    flag(flags, "country_dropped", "address",
                         f"{v!r}: no quote prints the country {ac[1]!r}; "
                         + (f"country dropped: {ac[0]!r}" if ac[0] else "the address is only a country: left out")
                         + " (user rule, cross-wave q-country)", "applied")
                if not ac[0]:
                    applied.pop(name)
                    if current.get(name):
                        final[name] = current[name]
                        if fold(current[name]) == fold(v):
                            final.pop(name)
                            removals[name] = f"only a country ({current[name]!r}) that no quote prints"
                    else:
                        final.pop(name, None)
                    continue
                set_norm(name, ac[0], [f"country {ac[1]!r} not printed by any quote: {v!r} -> {ac[0]!r}"])
                v = ac[0]
            new, notes, problems = normalise_address(v, ctx["cities"])
            for p in problems:
                flag(flags, "us_address_state_unknown", "address", p)
            added = address_country(new) if new != v else None
            if added and added[0] and not country_printed(added[2], own + address_quotes(fields)):
                # the house address key adds a country ('Leipzig' -> 'Leipzig, Germany'):
                # the user rule wins, a country no quote prints is not added
                notes = [n for n in notes if "house form" not in n] + \
                    [f"house address form {new!r} adds the country {added[1]!r}, which no quote prints: kept {added[0]!r}"]
                new = added[0]
            set_norm(name, new, notes)
        elif name == "doi":
            set_norm(name, clean_doi(v), ["doi lowercased"] if clean_doi(v) != v else [])
        elif name == "title" and a["source"] != "postcheck":
            try:
                ft = guarded(v, H.format_title(v))
            except Exception as err:  # format_title raises bare Exception on unbalanced braces
                flag(flags, "title_unformattable", "title", str(err))
                ft = None
            if ft and ft != v:
                set_norm(name, ft, [f"title house form: {v!r} -> {ft!r}"])
        elif name == "journal":
            fj = guarded(v, H.format_journal_name(v))
            if fj and fj != v:
                set_norm(name, fj, [f"journal house form: {v!r} -> {fj!r}"])
        elif name == "publisher":
            fp = guarded(v, H.format_journal_name(v, key=H.publisher_key, dotted_initials=True))
            if fp and fp != v:
                set_norm(name, fp, [f"publisher house form: {v!r} -> {fp!r}"])
        if name in ORDINAL_FIELDS and name not in ("booktitle", "edition") and name in applied:
            set_norm(name, *normalise_ordinals(applied[name]["value"]))

    # software is cited without a version number: not in the title or note, and no
    # version field (user rule, cross-wave q-brainiak)
    if software_entry(final) and verdict != "no_source":
        for name in ("title", "note"):
            v = final.get(name)
            if v and strip_version(v) != v:
                new = strip_version(v)
                if new:
                    set_norm(name, new, [f"software {name} without its version: {v!r} -> {new!r}"])
                    flag(flags, "software_version_removed", name, f"{v!r} -> {new!r} (user rule: no version number)",
                         "applied")
                elif name == "note":
                    applied.pop(name, None)
                    final.pop(name)
                    norms.append({"field": name, "note": f"note {v!r} held only a version number"})
                    if current.get(name):
                        removals[name] = f"only a version number ({current[name]!r}; user rule)"
        if final.get("version"):
            v = final.pop("version")
            applied.pop("version", None)
            flag(flags, "software_version_removed", "version", f"version {v!r} removed (user rule)", "applied")
            if current.get("version"):
                removals["version"] = f"software is cited without a version number ({current['version']!r}; user rule)"

    etype = final.get("ENTRYTYPE")
    if etype == "book" and final.get("pages"):
        applied.pop("pages", None)
        final.pop("pages", None)
        norms.append({"field": "pages", "note": "@book has no pages"})
        if current.get("pages"):
            removals["pages"] = "@book has no pages (house rule)"
    if etype == "article" and final.get("publisher"):
        applied.pop("publisher", None)
        final.pop("publisher", None)
        norms.append({"field": "publisher", "note": "@article has no publisher"})
        if current.get("publisher"):
            removals["publisher"] = "no publisher on @article (house rule)"

    # an article number moved into pages: a Number holding the same value goes
    if "pages" in applied and applied["pages"]["value"] != current.get("pages") and final.get("number") \
            and re.fullmatch(r"[A-Za-z]?\d+", final.get("pages", "").strip()) \
            and final["number"].strip() == final["pages"].strip():
        applied.pop("number", None)
        final.pop("number", None)
        norms.append({"field": "number", "note": f"article number {final['pages']} is now in pages"})
        if current.get("number"):
            removals["number"] = f"article number {current['number']} moved into pages"
    # @misc: no journal, and a volume that is a URL goes
    if etype == "misc":
        for name in ("journal", "volume"):
            v = str(final.get(name) or "")
            if not v or (name == "volume" and not re.search(r"https?:|www\.|\\url|\.(?:com|org|edu)\b", v)):
                continue
            applied.pop(name, None)
            final.pop(name, None)
            why = "@misc has no journal" if name == "journal" else f"@misc: volume {v!r} is a URL, not a volume"
            norms.append({"field": name, "note": why})
            if current.get(name):
                removals[name] = why
    # the researcher's own removals (top-level "remove" list); a reviewer value wins
    for name in [field_name(n) for n in row.get("remove") or []]:
        if (applied.get(name) or {}).get("source") == "reviewer" or name in removals \
                or name not in researcher_removes:
            continue
        if current.get(name) or final.get(name):
            applied.pop(name, None)
            final.pop(name, None)
            if current.get(name):
                removals[name] = f"researcher asked to remove it (current {current[name]!r})"

    # whitespace-only changes of text fields (a house-form question, not a source correction)
    for name in ("title", "booktitle", "journal"):
        a = applied.get(name)
        if a and a["source"] == "researcher" and current.get(name) and a["value"] != current[name] \
                and re.sub(r"\s+", "", a["value"]) == re.sub(r"\s+", "", current[name]):
            flag(flags, "style_only_change", name,
                 f"{current[name]!r} -> {a['value']!r} changes only spacing; a house-style decision "
                 "(check how cdl.bib writes it), not a source correction")

    # --- a no_source row never changes: the post-check's own house rules are not applied
    # either (BairNoma78's chapter move); only the reviewer's values remain
    if verdict == "no_source":
        for name in [n for n, a in applied.items() if a["source"] != "reviewer"]:
            applied.pop(name)
        final = dict(current)
        for name, a in applied.items():
            final[name] = a["value"]
        removals = {}
        norms = [n for n in norms if n["field"] in applied]

    # --- fields the reviewer asked to remove
    for name in sorted(reviewer_removes):
        applied.pop(name, None)
        final.pop(name, None)
        if name in current:
            removals[name] = f"reviewer asked to remove it (current {current[name]!r})"

    # --- junk fields are always removed ('Force = {True}')
    for name in JUNK_FIELDS:
        if name in current or name in final:
            applied.pop(name, None)
            final.pop(name, None)
            if name in current:
                removals[name] = f"not a BibTeX field (junk {name} = {current[name]!r})"

    # --- the notes name another version (a published version, a replacement candidate):
    # the preprint -> published choice is the user's (TsitEtal19, LiEtal24b, JainHuth18)
    other = other_version_named(row.get("notes"))
    if other:
        flag(flags, "other_version_named", None,
             f"the researcher's notes name another version ({other!r}): replacement is the user's decision")

    # --- changes vs current
    changes = []
    for name, a in sorted(applied.items()):
        if final.get(name) == current.get(name):
            continue
        change = {"field": name, "current": current.get(name), "proposed": final.get(name),
                  "source": a["source"], "evidence": a.get("evidence") or []}
        if a.get("normalised_from"):
            change["normalised_from"] = a["normalised_from"]
            change["normalised_by"] = "postcheck"  # the value differs from the proposal by the post-check's rules
        if a.get("decision"):
            change["decision"] = a["decision"]  # the user's cross-wave decision (source 'user')
        if review and name in (review.get("field_verdicts") or {}):
            change["reviewer"] = review["field_verdicts"][name]
        changes.append(change)

    # --- key plan
    plan = key_plan(key, current, final, bib, ctx["taken"], ctx["reserved"], ctx.get("index"))
    if plan["action"] in ("rename", "collision"):
        ctx["taken"].add(plan["new_key"])
    if plan["action"] == "duplicate":
        flag(flags, "duplicate", "key", plan.get("detail") or
             f"same DOI as {plan['merge_into']}: merge {key} into {plan['merge_into']}")
    elif plan.get("same_work_as"):
        flag(flags, "duplicate", "key", plan["detail"])
    if plan["action"] == "collision":
        flag(flags, "key_collision", "key", plan["detail"] + f"; proposed key {plan['new_key']}")
    elif plan["action"] == "rename":
        flag(flags, "key_rename", "key", f"{key} -> {plan['new_key']} ({plan['rename_reason']})")
    if reviewer_key:
        plan["reviewer_key"] = reviewer_key
        want = plan.get("merge_into") or plan.get("new_key") or key
        plan["reviewer_agrees"] = reviewer_key["key"] == want

    if suggestions:
        flag(flags, "unverified_suggestions", None,
             "values left not_found or suggested by the rules (never applied): " +
             ", ".join(f"{k}={v!r}" for k, v in suggestions.items()))
    user_resolved = bool((decision or {}).get("resolves_verdict"))
    if verdict in ("ambiguous", "no_source") and not user_resolved:
        flag(flags, "needs_user", "verdict", f"verdict {verdict}: user decision")
    elif verdict in ("ambiguous", "no_source"):
        flag(flags, "user_decision", "verdict",
             f"verdict {verdict} resolved by the user's decision ({decision.get('decision')})", "applied")

    return {"key": key, "verdict": verdict, "flags": flags, "normalisations": norms,
            "changes": changes, "removals": removals, "held": held,
            "suggestions": suggestions, "key_plan": plan, "doi_status": doi_status,
            "user_resolved": user_resolved, "software": software,
            "final_entry": final}


# ---------------------------------------------------------------- wave

def wave_duplicates(records):
    """Entries of one wave that resolve to the same work: the same final DOI, or the
    same title + first author + year. The later key merges into the earliest."""
    groups = {}
    keys = sorted(records)
    by_doi = {}
    for k in keys:
        d = clean_doi(records[k]["final_entry"].get("doi"))
        if d:
            by_doi.setdefault(d, []).append(k)
    for d, ks in by_doi.items():
        if len(ks) > 1:
            groups.setdefault(ks[0], set()).update(ks[1:])
    buckets = {}
    for k in keys:
        e = records[k]["final_entry"]
        buckets.setdefault((first_surname(e), e.get("year", "").strip()), []).append(k)
    for ks in buckets.values():
        for i, a in enumerate(ks):
            for b in ks[i + 1:]:
                if same_work(records[a]["final_entry"], records[b]["final_entry"]):
                    groups.setdefault(a, set()).add(b)
    # the entry that stays is the keeper (the key that fits the ID rule for the work's
    # corrected metadata, else the earliest), not simply the earliest key: Rugg00 and
    # RuggAlla00 were each told to merge into the other
    merged_groups = {}
    for first, rest in groups.items():
        members = {first} | set(rest)
        target = key_target(records[first]["final_entry"])
        keep = keeper(sorted(members), target)
        merged_groups.setdefault(keep, set()).update(members - {keep})
    groups = merged_groups
    for first, rest in groups.items():
        for k in sorted(rest):
            rec, plan = records[k], records[k]["key_plan"]
            why = (f"same work as {first} in this wave (same DOI or title, first author and year)")
            if plan.get("merge_into") == first:
                continue
            plan.setdefault("same_work_in_wave", []).append(first)
            if plan["action"] != "duplicate":
                plan.update(action="duplicate", merge_into=first, detail=f"{why}: merge {k} into {first}")
            flag(rec["flags"], "duplicate", "key", f"{why}: merge {k} into {first}")
        plan = records[first]["key_plan"]
        new = sorted(set(rest) - set(plan.get("same_work_as") or []))
        if new:
            plan.setdefault("same_work_in_wave", []).extend(new)
            flag(records[first]["flags"], "duplicate", "key",
                 f"{', '.join(new)} in this wave is the same work: merge into {first}")
    break_merge_cycles(records)


def break_merge_cycles(records):
    """Never A -> B and B -> A: of two entries told to merge into each other, the keeper
    (keeper()) stays, with a flag; the other merges into it."""
    for k in sorted(records):
        plan = records[k]["key_plan"]
        m = plan.get("merge_into") if plan.get("action") == "duplicate" else None
        if not m or m not in records:
            continue
        other = records[m]["key_plan"]
        if other.get("action") == "duplicate" and other.get("merge_into") == k:
            keep = keeper([k, m], key_target(records[k]["final_entry"]))
            drop = m if keep == k else k
            kp = records[keep]["key_plan"]
            kp.pop("merge_into", None)
            kp.update(action="keep",
                      detail=f"{drop} is the same work and merges into {keep} (circular merge resolved: {keep} fits "
                             "the ID rule for the corrected metadata or is the earlier key)")
            records[drop]["key_plan"].update(action="duplicate", merge_into=keep)
            flag(records[keep]["flags"], "duplicate", "key", kp["detail"])

def apply_entry_decisions(records, decisions, bib, taken):
    """The user's per-entry decisions that are about the whole entry, after the key
    plans and wave duplicates: a key the user chose (Shim94 -> Shim95b, Shim95 ->
    Shim95a, OGra11 -> OGra08), an approved duplicate merge, the keeper of a merge and
    whether it drops its suffix (KahaEtal08a, only when no other key with its base is
    in cdl.bib), removal of the entry (conference abstracts), 'a real article, not an
    abstract', and printed names kept (Hwang). Each is a 'user_decision' flag."""
    for k in sorted(records):
        d = decisions.get(k)
        if not d:
            continue
        rec = records[k]
        plan, flags, why = rec["key_plan"], rec["flags"], d.get("decision")
        if d.get("key"):
            want = d["key"]
            have = plan.get("new_key") if plan["action"] in ("rename", "collision") else \
                (k if plan["action"] == "keep" else None)
            if have == want:
                plan["user_decision"] = why
                flag(flags, "user_decision", "key", f"{why}: key {k} -> {want}, as planned (approved)", "applied")
            else:
                before = f"{plan['action']} {plan.get('new_key') or plan.get('merge_into') or ''}".strip()
                for x in ("merge_into", "existing", "also_rename"):
                    plan.pop(x, None)
                plan.update(action="rename", new_key=want, rename_reason=f"user decision ({why})", user_decision=why)
                taken.add(want)
                flag(flags, "user_decision", "key",
                     f"{why}: key {k} -> {want} (the post-check planned {before}; the user's decision wins)", "applied")
        if d.get("merge_into"):
            want = d["merge_into"]
            if plan["action"] == "duplicate" and plan.get("merge_into") == want:
                plan["user_decision"] = why
                flag(flags, "user_decision", "key", f"{why}: merge {k} into {want} (approved duplicate)", "applied")
            else:
                before = f"{plan['action']} {plan.get('new_key') or plan.get('merge_into') or ''}".strip()
                plan.update(action="duplicate", merge_into=want, user_decision=why,
                            detail=f"user decision ({why}): merge {k} into {want}")
                flag(flags, "user_decision", "key",
                     f"{why}: merge {k} into {want} (the post-check planned {before}; the user's decision wins)",
                     "applied")
        if d.get("keeper_of"):
            gone = sorted(d["keeper_of"])
            flag(flags, "user_decision", "key", f"{why}: {', '.join(gone)} merge(s) into {k} (approved duplicate)",
                 "applied")
            if d.get("drop_suffix_if_only"):
                base = re.sub(r"[a-z]+$", "", k)
                others = sorted(x for x in bib if x != k and x not in gone
                                and re.fullmatch(re.escape(base) + r"[a-z]*", x))
                if not others and plan["action"] == "keep":
                    plan.update(action="rename", new_key=base, user_decision=why,
                                rename_reason=f"user decision ({why}): the only {base} once {', '.join(gone)} is merged")
                    taken.add(base)
                    flag(flags, "user_decision", "key", f"{why}: {k} -> {base} (no other {base} key in cdl.bib)",
                         "applied")
                else:
                    plan["suffix_kept"] = others
                    flag(flags, "user_decision", "key",
                         f"{why}: {k} keeps its suffix: {', '.join(others) or 'a key plan'} "
                         f"{'is' if len(others) == 1 else 'are'} also in cdl.bib", "applied")
        if d.get("remove_entry"):
            rec["remove_entry"] = d["remove_entry"]
            # worded without the user's note: the cross-wave page's abstract finder reads
            # these flags, and must not find the entry because of its own decision
            items = ", ".join(re.findall(r"cross-wave ((?:a|j|q|dup)-[\w-]+)", why or "")) or "cross-wave page"
            flag(flags, "user_decision", None,
                 f"user decision ({items}): remove {k} from cdl.bib (approved removal as an abstract; "
                 "listed in crosswave/removals.json)", "flag")
        if d.get("not_abstract"):
            flag(flags, "user_decision", None,
                 f"{why}: a real article, not a conference abstract: keep it and verify it normally", "applied")
        if d.get("names_as_printed"):
            flag(flags, "user_decision", "author",
                 f"{why}: each paper keeps the author's printed name (no unification across papers)", "applied")


def measure(review_rows, rules_only):
    """For each reviewer finding (agree != yes): is a disputed field touched by the rules?"""
    rows = [r for r in review_rows if r.get("key") != "_summary" and r.get("agree") != "yes"]
    summary = next((r for r in review_rows if r.get("key") == "_summary"), {})
    sample = set(summary.get("random_sample_with_disagreement") or [])
    out = []
    for r in rows:
        disputed = {f for f, v in (r.get("field_verdicts") or {}).items() if v in ("disagree", "unsure")}
        disputed |= {f for f in (r.get("suggested_value") or {}) if f != "action"}
        rec = rules_only.get(r["key"]) or {}
        touched = {}
        for f in rec.get("flags", []):
            if f["code"] in ("needs_user", "unverified_suggestions", "reviewer_action"):
                continue
            touched.setdefault(f["field"], []).append(f["code"])
        for n in rec.get("normalisations", []):
            touched.setdefault(n["field"], []).append("normalised")
        hits = {k: v for k, v in touched.items() if k in disputed}
        out.append({"key": r["key"], "random_sample": r["key"] in sample, "disputed": sorted(disputed),
                    "caught": bool(hits), "by": hits,
                    "rules_touched": {k: v for k, v in touched.items() if k is not None}})
    caught = [o for o in out if o["caught"]]
    rs = [o for o in out if o["random_sample"]]
    return {"findings": len(out), "caught": len(caught),
            "random_sample_findings": len(rs), "random_sample_caught": sum(o["caught"] for o in rs),
            "rows": out}


def resolution(review_rows, merged, bib):
    """For each reviewer finding (agree != yes): does the final output (rules + reviewer
    merge) do what the reviewer asked? Checks, per field: a suggested value is the final
    value; a field the reviewer says must be removed / should go is absent; a key the
    reviewer calls a duplicate has a duplicate plan or flag; any other disagreement
    without a value leaves the field as it is in cdl.bib. A row with none of these is
    'not checkable' (resolved None: e.g. a missed source)."""
    out = []
    for r in review_rows:
        if r.get("key") == "_summary" or r.get("agree") == "yes":
            continue
        rec = merged.get(r["key"])
        if rec is None:
            out.append({"key": r["key"], "resolved": False, "checks": [["row", False, "not in the wave"]]})
            continue
        fin, cur = rec["final_entry"], bib.get(r["key"]) or {}
        sv = canonical_fields(r.get("suggested_value"))
        fv = canonical_fields(r.get("field_verdicts"))
        checks = []
        about = " ".join([str(fv.get("key", "")), str(sv.get("key", "")), str(sv.get("action", ""))] +
                         [str(p) for p in r.get("problems") or []]).lower()
        if sv.get("key") or str(fv.get("key", "")).lower().startswith("disagree"):
            plan = rec["key_plan"]
            if "duplicate" in about or "merge" in about:
                checks.append(["key", plan["action"] == "duplicate" or any(x["code"] == "duplicate" for x in rec["flags"])
                               and (not sv.get("key") or plan.get("reviewer_agrees", True)),
                               f"reviewer: duplicate ({sv.get('key') or fv.get('key')}); plan {plan['action']} "
                               f"{plan.get('merge_into') or ''}".strip()])
            elif sv.get("key"):
                checks.append(["key", bool(plan.get("reviewer_agrees")),
                               f"reviewer key {sv['key']!r}; plan {plan['action']} "
                               f"{plan.get('new_key') or plan.get('merge_into') or ''}".strip()])
            else:
                checks.append(["key", plan["action"] != "keep", f"reviewer: {fv.get('key')}; plan {plan['action']}"])
        for f, v in sv.items():
            if f in ("action", "key"):
                continue
            if v is None or str(v).strip() == "":
                ok = fin.get(f) == cur.get(f)
                checks.append([f, ok, "reviewer withdrew the change"])
            elif is_removal(v):
                checks.append([f, f not in fin, f"reviewer: {v}"])
            else:
                ok = fold(fin.get(f, "")) == fold(v) if f != "ENTRYTYPE" else \
                    str(fin.get(f, "")).lower() == str(v).lower().lstrip("@")
                checks.append([f, ok, f"final {fin.get(f)!r} vs reviewer {v!r}"])
        for f, v in fv.items():
            text = str(v).lower()
            if f in sv or not text.startswith("disagree") or reviewer_confirms(v):
                continue
            if f == "key":
                continue
            elif f == "entrytype" or f == "ENTRYTYPE":
                checks.append([f, "entrytype" not in fin, v])
            elif re.search(r"remov|should go|must go|drop", text):
                checks.append([f, f not in fin, v])
            else:
                checks.append([f, fin.get(f) == cur.get(f), v])
        out.append({"key": r["key"], "random_sample": r.get("sampled_as") == "b",
                    "resolved": all(c[1] for c in checks) if checks else None, "checks": checks})
    return {"findings": len(out), "resolved": sum(o["resolved"] is True for o in out),
            "unresolved": [o["key"] for o in out if o["resolved"] is False],
            "not_checkable": [o["key"] for o in out if o["resolved"] is None], "rows": out}


def run(folder, bib="HEAD", review_path=None, offline=False, write=True, decisions_path=None):
    folder = Path(folder)
    bibd = load_bib(bib)
    decisions = load_decisions(decisions_path)
    review_path = Path(review_path) if review_path else folder / "review.json"
    review_rows = json.loads(review_path.read_text()) if review_path.exists() else []
    reviews = {r["key"]: r for r in review_rows if r.get("key") != "_summary"}
    vpath = folder / "validation.json"
    validation = {e["key"]: e for e in json.loads(vpath.read_text())["report"]} if vpath.exists() else {}
    doi_cache = {}

    def doi(d):
        if d not in doi_cache:
            doi_cache[d] = doi_record(d, offline)
        return doi_cache[d]

    rows = []
    for batch in sorted(folder.glob("batch-*.json")):
        for row in json.loads(batch.read_text()):
            rows.append((batch.stem, row))

    index = work_index(bibd)

    def pass_(with_review):
        ctx = {"doi": doi, "cities": city_states(bibd), "taken": set(), "reserved": renamed_away(),
               "index": index, "fetch": lambda url: http_get(url, offline)}
        out = {}
        for stem, row in rows:
            # the user's decisions are not rules: the rules-alone pass never sees them
            rec = check_entry(row, bibd.get(row["key"]), bibd, ctx,
                              review=reviews.get(row["key"]) if with_review else None,
                              validation=validation.get(row["key"]),
                              decision=decisions.get(row["key"]) if with_review else None)
            rec["batch"] = stem
            out[row["key"]] = rec
        wave_duplicates(out)
        if with_review:
            apply_entry_decisions(out, decisions, bibd, ctx["taken"])
        return out

    rules_only = pass_(False)
    merged = pass_(True)
    meas = measure(review_rows, rules_only) if review_rows else None
    codes = {}
    for rec in merged.values():
        for f in rec["flags"]:
            codes[f["code"]] = codes.get(f["code"], 0) + 1
    plans = [r["key_plan"] for r in merged.values()]
    summary = {
        "entries": len(merged), "bib": bib,
        "flag_counts": dict(sorted(codes.items())),
        "dois_dropped": sorted(f"{k}: {f['detail']}" for k, r in merged.items() for f in r["flags"]
                               if f["code"] in ("doi_unregistered", "doi_title_mismatch")),
        "dois_dropped_by_rules_alone": sorted(k for k, r in rules_only.items() for f in r["flags"]
                                             if f["code"] in ("doi_unregistered", "doi_title_mismatch")),
        "renames": {p["current_key"]: p["new_key"] for p in plans if p["action"] == "rename"},
        "duplicates": {p["current_key"]: p["merge_into"] for p in plans if p["action"] == "duplicate"},
        "collisions": {p["current_key"]: p["new_key"] for p in plans if p["action"] == "collision"},
        "doi_requests_uncached": None,
        "user_decisions": {k: [f["detail"] for f in r["flags"] if f["code"] == "user_decision"]
                           for k, r in sorted(merged.items()) if any(f["code"] == "user_decision" for f in r["flags"])},
        "remove_entries": sorted(k for k, r in merged.items() if r.get("remove_entry")),
        "software_first_version": {k: {"cited": r["software"]["doi"],
                                       "first": r["software"]["first"].get("doi"),
                                       "first_year": r["software"]["first"].get("year"),
                                       "error": r["software"]["first"].get("error"),
                                       "year": r["final_entry"].get("year"), "key_plan": r["key_plan"]["action"],
                                       "new_key": r["key_plan"].get("new_key")}
                                   for k, r in sorted(merged.items()) if r.get("software")},
        "country_dropped": sorted(f"{k}: {f['detail']}" for k, r in merged.items() for f in r["flags"]
                                  if f["code"] == "country_dropped"),
    }
    post = {"summary": summary, "measurement": meas,
            "review_resolution": resolution(review_rows, merged, bibd) if review_rows else None,
            "review_resolution_rules_alone": resolution(review_rows, rules_only, bibd) if review_rows else None,
            "entries": {k: {kk: vv for kk, vv in r.items() if kk != "final_entry"} for k, r in merged.items()},
            "rules_only_flags": {k: [f["code"] + (":" + f["field"] if f["field"] else "") for f in r["flags"]]
                                 for k, r in rules_only.items()}}
    page = []
    for k, r in merged.items():
        rv = reviews.get(k)
        page.append({
            "key": k, "batch": r["batch"], "verdict": r["verdict"],
            "current": {f: v for f, v in (bibd.get(k) or {}).items()},
            "final_changes": r["changes"], "removals": r["removals"],
            "key_plan": r["key_plan"],
            "flags": r["flags"],
            "doi_status": r["doi_status"],
            "remove_entry": r.get("remove_entry"),
            "user_decisions": [f["detail"] for f in r["flags"] if f["code"] == "user_decision"],
            "reviewer": ({"agree": rv.get("agree"), "sampled_as": rv.get("sampled_as"),
                          "field_verdicts": rv.get("field_verdicts"), "problems": rv.get("problems"),
                          "suggested_value": rv.get("suggested_value")} if rv else None),
            "needs_user": bool((r["verdict"] in ("ambiguous", "no_source") and not r.get("user_resolved")) or
                               any(f["action"] in ("held", "flag") for f in r["flags"]) or r["key_plan"]["action"] != "keep"),
        })
    if write:
        (folder / "postcheck.json").write_text(json.dumps(post, indent=1, ensure_ascii=False) + "\n")
        (folder / "merged.json").write_text(json.dumps(page, indent=1, ensure_ascii=False) + "\n")
    return post, page, rules_only, merged


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--bib", default="HEAD", help="cdl.bib path, or HEAD (default) for the committed file")
    ap.add_argument("--review", default=None)
    ap.add_argument("--offline", action="store_true", help="use cached network responses only")
    ap.add_argument("--write-removals", action="store_true",
                    help="write crosswave/removals.json (entries the user approved for removal) and exit")
    args = ap.parse_args(argv)
    if args.write_removals:
        rows = build_removals(bib=load_bib(args.bib))
        REMOVALS.write_text(json.dumps({
            "about": "Entries the user approved for removal from cdl.bib on the cross-wave decisions page "
                     "(2026-09-26; raw answers in crosswave/decisions/). Built by postcheck.py --write-removals "
                     "for the later apply step; cdl.bib is not edited here.",
            "count": len(rows), "entries": rows}, indent=1, ensure_ascii=False) + "\n")
        print(REMOVALS, len(rows))
        return 0
    if not args.folder:
        ap.error("folder is required unless --write-removals is given")
    post, _, _, _ = run(args.folder, args.bib, args.review, args.offline)
    s = post["summary"]
    print(json.dumps({k: v for k, v in s.items() if k != "doi_requests_uncached"}, indent=1))
    if post["measurement"]:
        m = post["measurement"]
        print(f"review findings caught by rules alone: {m['caught']}/{m['findings']}; "
              f"random sample {m['random_sample_caught']}/{m['random_sample_findings']}")
        for r in m["rows"]:
            print(("CAUGHT " if r["caught"] else "MISSED ") + r["key"], r["disputed"], r["by"] or r["rules_touched"])
    if post.get("review_resolution"):
        rr = post["review_resolution"]
        print(f"review findings resolved by rules + reviewer merge: {rr['resolved']}/{rr['findings']}; "
              f"unresolved {rr['unresolved']}; not checkable {rr['not_checkable']}")
        ra = post["review_resolution_rules_alone"]
        print(f"  of which resolved by the rules alone (no reviewer values): {ra['resolved']}/{ra['findings']}; "
              f"unresolved {ra['unresolved']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
