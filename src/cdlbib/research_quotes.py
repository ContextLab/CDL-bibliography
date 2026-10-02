"""Quote matching for research approvals (used by bibcheck/research_route.py).

These are the matching functions of the research pilot's validator
(verification/research-pilot-2026-09-24/validate.py, kept in the archive repository:
https://github.com/ContextLab/CDL-bibliography-stacks/tree/main/verification/research-pilot-2026-09-24), copied unchanged so that
`crossref restore` can re-check a saved research approval without the research
folders. Nothing here makes a network request.
"""
import html
import re
import unicodedata
from urllib.parse import unquote

# Apostrophe look-alikes (O´Reilly, Oʼ, O′) fold to "'" before NFKC splits U+00B4 into
# a space and a combining accent; trademark signs are dropped (FitBit® = FitBit).
PRE_FOLD = str.maketrans({"\u00b4": "'", "\u02bc": "'", "\u2032": "'", "\u00ae": "", "\u2122": "", "\u00a9": ""})

# FOLD also writes the plus-minus sign (U+00B1, LaTeX \pm) the way plain-text sources
# print it: $7\pm2$ = 7 +/- 2 (LismIdia95, PubMed title).
FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                      "—": "-", "−": "-", " ": " ", "­": "", "\u00b1": "+/-"})

ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
           ".": "\u0307", "c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b", "k": "\u0328", "r": "\u030a"}

SPECIAL = {"l": "ł", "L": "Ł", "o": "ø", "O": "Ø", "ss": "ß", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
           "aa": "å", "AA": "Å", "i": "ı", "j": "ȷ"}

SYMBOLS = {"times": "\u00d7", "pm": "\u00b1", "textregistered": "\u00ae", "texttrademark": "\u2122", "textcopyright": "\u00a9"}

def delatex(text):
    """LaTeX accent macros to Unicode: \\'{e}, \\'e, {\\'e}, \\c{c}, \\v{s} ..."""
    def repl(m):
        return unicodedata.normalize("NFC", m[2] + ACCENTS[m[1]])
    # Math sub/superscripts keep their content: {GABA$_A$} -> GABAA, $_{2}$ -> 2.
    text = re.sub(r"\$\s*[_^]\s*\{?([A-Za-z0-9]+)\}?\s*\$", r"\1", text)
    text = re.sub(r"\\(" + "|".join(SYMBOLS) + r")(?![A-Za-z])\s?", lambda m: SYMBOLS[m[1]], text)
    # Escaped specials are the characters themselves: amueller/word\_cloud = word_cloud.
    text = re.sub(r"\\([_&%#$])", r"\1", text)
    # An accent on a dotless i is an accented i: na{\"\i}ve = naïve, Cad{\'\i}k = Cadík.
    text = re.sub(r"\\(['`^\"~=.])\s*\{?\\i(?![A-Za-z])\}?",
                  lambda m: unicodedata.normalize("NFC", "i" + ACCENTS[m[1]]), text)
    # No space between an accent macro and its letter: in a JSON quote '\\" in' is an
    # escaped quote mark followed by a word, not an umlaut on the i.
    text = re.sub(r"\\(['`^\"~=.])\{?([A-Za-z])\}?", repl, text)
    text = re.sub(r"\\([cvuHkr])\s*\{([A-Za-z])\}", repl, text)
    text = re.sub(r"\\([cvuHkr]) ([A-Za-z])", repl, text)
    text = re.sub(r"(\d+)\\textsuperscript\{([a-z]+)\}", r"\1\2", text)  # 30\textsuperscript{th} -> 30th
    # Text-style commands keep their content: \textit{Drosophila} -> Drosophila.
    text = re.sub(r"\\(?:textit|emph|textbf|textsc|textrm|textsf|texttt|mathrm|mathit|mbox)\s*\{([^{}]*)\}", r"\1", text)
    for macro, letter in SPECIAL.items():  # {\l}, \o, \ss ... -> ł, ø, ß
        text = re.sub(r"\{\\" + macro + r"\}", letter, text)
        text = re.sub(r"\\" + macro + r"(?![A-Za-z])\s?", letter, text)
    return text.replace("{", "").replace("}", "")


def json_unescape(text):
    """JSON \\uXXXX escapes (Crossref API bodies are quoted raw) to the characters they
    stand for, surrogate pairs included. \\u followed by four hex digits is never a
    LaTeX breve, which takes a braced or spaced letter."""
    text = re.sub(r"\\u(d[89ab][0-9a-f]{2})\\u(d[c-f][0-9a-f]{2})",
                  lambda m: chr(0x10000 + ((int(m[1], 16) - 0xD800) << 10) + int(m[2], 16) - 0xDC00), text, flags=re.I)
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), text)


def norm(text):
    text = delatex(json_unescape(html.unescape(text))).replace("&", " and ")
    text = unicodedata.normalize("NFKC", text.translate(PRE_FOLD)).translate(FOLD)
    text = re.sub(r"-\s*\n\s*", "-", text)  # keep hyphenated line breaks as hyphens
    return re.sub(r"\s+", " ", text).strip().casefold()


def transient_error(text):
    """Why a fetched body is a server error reply rather than the record, or None.
    The Library of Congress SRU server (lx2.loc.gov:210) intermittently answers a valid
    LCCN query with numberOfRecords 1 but no record, only the diagnostic 'First record
    position out of range' (LaddWood11, KuceFran67); the same URL returns the MARC record
    on a retry. Such a reply is not the source, so it is neither cached nor searched."""
    if "<zs:searchRetrieveResponse" in text and "<zs:records>" not in text and "diagnostic" in text:
        m = re.search(r"<diag:message>(.*?)</diag:message>", text)
        return "SRU diagnostic without a record: " + (m[1] if m else "unknown")
    return None


def hyphen_joined(normed):
    """A line-end hyphen with the break written as a space ('Dis- tribution', Niph78) and
    the same hyphen at a line break in the source (norm keeps it as 'Dis-tribution') are one
    text: whitespace after a hyphen is dropped on both sides before the substring test."""
    return re.sub(r"-\s+", "-", normed)


def value_tokens(field, value):
    """The parts of a proposed value that the quotes must contain: surnames for
    names, every number for coordinates, every word of 3+ letters otherwise."""
    value = delatex(str(value or ""))
    if field in ("author", "editor"):
        names = [n.strip() for n in re.split(r"\s+and\s+", value) if n.strip()]
        return [norm(n.split(",")[0] if "," in n else n.split()[-1]) for n in names if n.lower() != "others"]
    if field in ("pages", "volume", "number", "year"):
        return re.findall(r"\d+", value)
    return [w for w in re.findall(r"\w{3,}", norm(value))]


STOP = {"the", "and", "for", "with", "from", "of", "in", "on", "an", "a", "to", "at", "by"}

ORDINAL_WORDS = {w: n for n, w in enumerate("zeroth first second third fourth fifth sixth seventh eighth "
                 "ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth "
                 "eighteenth nineteenth twentieth".split())}

TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

def suffix(n):
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def ordinals_to_digits(text):
    """'twenty-fourth' -> '24th', 'fourth' -> '4th' (text already normalised)."""
    def compound(m):
        n = TENS[m[1]] + ORDINAL_WORDS[m[2]]
        return f"{n}{suffix(n)}"
    text = re.sub(r"\b(" + "|".join(TENS) + r")[- ](" + "|".join(list(ORDINAL_WORDS)[1:10]) + r")\b", compound, text)
    return re.sub(r"\b(" + "|".join(ORDINAL_WORDS) + r")\b", lambda m: f"{ORDINAL_WORDS[m[1]]}{suffix(ORDINAL_WORDS[m[1]])}", text)


NONDECOMPOSING = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ı": "i",
                                "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE"})

UMLAUT_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})

def expand_ranges(text):
    """Abbreviated page ranges as PubMed writes them: 'b153-64' -> 'b153-164', '1188-97' -> '1188-1197'."""
    def full(m):
        a, b = m[2], m[3]
        return f"{m[1]}{a}-{m[1]}{a[:len(a) - len(b)] + b}" if len(b) < len(a) else m[0]
    return re.sub(r"(?<![\w-])([a-z]?)(\d+)-(\d+)(?![\w-])", full, text)


def fold(text):
    text = text.translate(NONDECOMPOSING)
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

def roman_to_int(numeral):
    """'xxxiv' -> 34; None unless the numeral is written canonically (so 'mix' or 'civil' is not a number)."""
    values = [ROMAN[c] for c in numeral.lower()]
    total = sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))
    return total if total and int_to_roman(total) == numeral.lower() else None


def int_to_roman(n):
    out = ""
    for v, r in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"),
                 (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + r, n - v
    return out


def roman_volumes(text):
    """'vol. xxxiv' / 'volume xxxiv' -> 'vol. 34': a Roman numeral counts as a volume number only
    right after the word volume, never on its own (a stray 'i' or 'v' is not a volume)."""
    def repl(m):
        n = roman_to_int(m[2])
        return f"{m[1]}{n}" if n else m[0]
    text = re.sub(r"\b(vols?\.?\s*|volume\s+)([ivxlcdm]+)\b", repl, text)
    # German title pages spell the volume as an ordinal before 'Band': 'Sechster Band' is
    # vol. 6 (MullSchu94). Only directly before 'band', never an ordinal on its own.
    return re.sub(r"\b(" + "|".join(sorted(GERMAN_ORDINALS, key=len, reverse=True)) + r")(?:er|e|es|en)\s+band\b",
                  lambda m: f"vol. {GERMAN_ORDINALS[m[1]]}", text)


GERMAN_ORDINALS = {w: n for n, w in enumerate(
    "erst zweit dritt viert fünft sechst siebent acht neunt zehnt elft zwölft dreizehnt vierzehnt "
    "fünfzehnt sechzehnt siebzehnt achtzehnt neunzehnt zwanzigst".split(), 1)}

# Journal words a quote may print in a standard abbreviated form. Each pattern must
# spell out the same thing, not merely something related: 'usa' is the United States
# of America or U.S.A., never plain 'U.S.' or 'United States'.
ABBREVIATED = {"usa": r"(?<!\w)(?:united states of america|u\.?\s?s\.?\s?a)(?!\w)"}

def series_present(value_norm, joined):
    """'... of London Series B: ...' against a quote printing 'of London. B, ...' or
    'of London, Ser. B': the series letter must follow the same preceding word, with
    only punctuation and an optional 'ser.'/'series' between."""
    m = re.search(r"(\w+)\W+series\s+([a-z])\b", value_norm)
    if not m:
        return False
    return re.search(r"(?<!\w)" + re.escape(fold(m[1])) + r"[\s.,;:]+(?:ser(?:ies|\.)?\s*)?"
                     + re.escape(m[2]) + r"(?!\w)", joined)


def journal_abbreviations(value):
    """Abbreviations bibcheck's journal alias table (journal_key.xls, via
    helpers.journal_key) maps onto this journal, e.g.
    'eur j neurosci' for European Journal of Neuroscience. Only aliases whose target is the
    value's own journal and whose words abbreviate that name's words in order are used, so
    a misspelled or different-journal alias in the table never counts."""
    target = journal_name_key(value)
    return [alias for alias, full in load_journal_key().items()
            if isinstance(alias, str) and isinstance(full, str) and journal_name_key(full) == target
            and abbreviates(journal_name_key(alias).split(), target.split())]


def journal_name_key(name):
    words = re.findall(r"\w+", fold(norm(delatex(name))))
    return " ".join(w for w in words if w != "the")


JOURNAL_STOP = {"of", "and", "the", "in", "for", "on", "de", "la", "et", "und", "fur"}

def abbreviates(short, full):
    """Every word of short abbreviates the next unmatched word of full (same first letter,
    remaining letters in order: 'eur' european, 'natl' national); the words of full that are
    skipped must be stopwords, so 'j neurosci' does not abbreviate 'european journal of neuroscience'."""
    i = 0
    for w in short:
        while i < len(full) and not (full[i][0] == w[0] and re.fullmatch(".*?".join(map(re.escape, w)) + ".*", full[i])):
            if full[i] not in JOURNAL_STOP:
                return False
            i += 1
        if i == len(full):
            return False
        i += 1
    return all(w in JOURNAL_STOP for w in full[i:]) and short != full


def journal_abbreviation_present(value, joined):
    """A table abbreviation of the value's journal printed in the quotes, and not as part of
    a longer name of a different journal in the table: 'j neurosci' (The Journal of
    Neuroscience) inside 'Eur J Neurosci' is the European journal, not a match."""
    spaced = " " + " ".join(re.findall(r"\w+", joined)) + " "
    target = journal_name_key(value)
    others = [journal_name_key(n) for a, f in load_journal_key().items() if isinstance(a, str)
              for n in (a, f) if isinstance(n, str)
              and journal_name_key(f if isinstance(f, str) else a) != target]
    for alias in journal_abbreviations(value):
        words = " " + journal_name_key(alias) + " "
        if words in spaced and not any(words in " " + o + " " and " " + o + " " in spaced for o in others):
            return True
    return False


_JOURNAL_KEY = None

def load_journal_key():
    global _JOURNAL_KEY
    if _JOURNAL_KEY is None:
        from . import helpers
        _JOURNAL_KEY = dict(helpers.journal_key)
    return _JOURNAL_KEY


# Same-firm publisher variants a catalogue record prints for the house full form, per the
# rule that a catalogue's short form of the same firm is a match. Each list names one
# firm only: 'Scribner' (LoC imprints of the 1960s-70s) is Charles Scribner's Sons, and
# 'G. Allen & Unwin' is George Allen & Unwin; a successor or different firm (Holt,
# Rinehart and Winston; Unwin Hyman) is never listed. Keys and variants are compared
# after publisher_key(): punctuation dropped, '&' read as 'and'.
PUBLISHER_FIRMS = {
    "charles scribner's sons": ["charles scribner's sons", "c scribner's sons", "scribner's sons", "scribner"],
    "george allen and unwin": ["george allen and unwin", "g allen and unwin", "allen and unwin"],
    "henry holt and company": ["henry holt and company", "henry holt and co", "h holt and company", "h holt and co"],
    "institute of physics publishing": ["institute of physics publishing", "institute of physics pub",
                                        "institute of physics publ", "iop publishing"],
    # LoC 260$b prints the firm as 'Sage,' (SnijBosk12, ISBN 9781849202008).
    "sage publications": ["sage publications", "sage publications inc", "sage publications ltd", "sage"],
}

def publisher_key(name):
    return " ".join(re.findall(r"[\w']+", fold(norm(delatex(name)))))


def publisher_variant_present(value, joined_texts):
    variants = PUBLISHER_FIRMS.get(publisher_key(value))
    if not variants:
        return False
    text = publisher_key(joined_texts)
    return any(re.search(r"(?<![\w'])" + re.escape(v) + r"(?![\w'])", text) for v in variants)


def joined_word_variants(text):
    """Two print artefacts that split or run words together: a camel-case run-in where a
    record dropped a space ('inMind', 'thetaResponse', 'denNijs' in PubMed records) is
    also read with the space, and a line-end hyphen before a lowercase continuation
    ('Be-\ndingungen', 'Dis- tribution') is also read joined. Only two or more lowercase
    letters before the capital split, so 'McDonald' and 'DiCarlo' stay whole. A one-letter
    capital word run in ('bindingA review', Crossref joining title and subtitle, BrowMcCo06)
    splits the same way. Dotted initialisms are also read without the dots ('M.I.T.' = MIT,
    Whor56); spaced initials ('J. R. R.') are left alone."""
    text = re.sub(r"(?<=[a-z]{2})(?=[A-Z](?:[a-z]|\s))", " ", text)
    text = re.sub(r"(?<![\w.])((?:[A-Za-z]\.){2,})", lambda m: m[1].replace(".", ""), text)
    return re.sub(r"(\w)-\s+([a-z])", r"\1\2", text)


def affiliation_marks_dropped(text):
    """Author bylines print affiliation numbers glued to the surname ('Po-Hsuan Chen1 ,'
    in a NeurIPS PDF, ChenEtal15a; 'Long1, Michael J Kahana1' in the CNS 2012 program,
    LongKaha12a). For author/editor fields a run of digits directly after a letter and
    before a non-word character is dropped; digits inside a word are kept."""
    return re.sub(r"(?<=[^\W\d_])\d+(?!\w)", "", text)


# Words the house form adds to a booktitle that sources do not print. Each is accepted
# as missing only when it is the ONLY missing word (never standing in for content words):
# * 'proceedings' when the booktitle opens 'Proceedings of (the) ...' and every other word
#   is quoted (MallEtal97, ParkEtal24: citation_conference_title omits it);
# * 'abstracts' only in the SfN house form 'Society for Neuroscience Abstracts'
#   (bibcheck/sfn_abstracts.py BOOKTITLE, SFN-SOURCE.md), and only when the quotes print
#   the organisation 'Society for Neuroscience' as a phrase (the planner citation footer).
SFN_BOOKTITLE = "society for neuroscience abstracts"

def house_booktitle_word(value_norm, missing, joined):
    if missing == ["proceedings"]:
        return bool(re.match(r"proceedings of (the )?\w", value_norm))
    if missing == ["abstracts"]:
        return value_norm == SFN_BOOKTITLE and re.search(r"(?<!\w)society for neuroscience(?!\w)", joined) is not None
    return False


def value_supported(field, value, texts, urls=()):
    if field == "doi" and value and any(str(value).lower() in unquote(u).lower() for u in urls):
        return True, []  # the evidence URL is the DOI's own record
    normed = ordinals_to_digits(" ".join(norm(t) for t in texts))
    variant = (lambda t: affiliation_marks_dropped(joined_word_variants(t))) if field in ("author", "editor") \
        else joined_word_variants
    alt = ordinals_to_digits(" ".join(norm(variant(t)) for t in texts))
    if field == "volume":
        normed, alt = roman_volumes(normed), roman_volumes(alt)
    joined = fold(normed)
    joined_alt = fold(alt)
    if field == "publisher" and publisher_variant_present(str(value or ""), " ".join(texts)):
        return True, []
    # German umlauts are also written ae/oe/ue: the quote may use either form, and so may the value.
    joined_translit = fold(normed.translate(UMLAUT_TRANSLIT))
    if field == "pages":
        joined = expand_ranges(joined)  # only page values: a DOI suffix like 2001-354 is not a range
    def present(t, text=None):
        text = joined if text is None else text
        if t.isdigit():  # compare numbers numerically: an issue printed "03" is 3
            return re.search(r"(?<!\d)0*" + re.escape(t.lstrip("0") or "0") + r"(?!\d)", text)
        return re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text)
    # Normalise the value exactly like the quotes: ordinal words become digits on both sides.
    value_norm = ordinals_to_digits(norm(delatex(str(value or ""))))
    raw_tokens = value_tokens(field, value_norm)
    if field not in ("author", "editor"):
        raw_tokens = [t for t in raw_tokens if fold(t) not in STOP]
    translit = {fold(t): fold(t.translate(UMLAUT_TRANSLIT)) for t in raw_tokens}
    tokens = [fold(t) for t in raw_tokens]
    def present_any(t):
        if present(t) or present(translit.get(t, t)) or present(t, joined_translit) or present(t, joined_alt):
            return True
        if field in ("journal", "booktitle"):
            if t in ABBREVIATED and re.search(ABBREVIATED[t], joined):
                return True
            if t == "series" and series_present(fold(value_norm), joined):
                return True
        if field in ("title", "booktitle") and t == "volume":
            # 'volume 2' printed 'v. 2' or 'vol. 2' (LoC contents note, McClEtal86): the same
            # number must follow the abbreviation.
            nums = re.findall(r"(?<!\w)volume\s+(\d+)", fold(value_norm))
            return bool(nums) and all(re.search(r"(?<!\w)v(?:ol)?\.?\s*" + n + r"(?!\d)", joined) for n in nums)
        return False
    missing = [t for t in tokens if not present_any(t)]
    if missing and field not in ("author", "editor"):
        # Two value words the source runs together ('La Jolla' printed 'LaJolla', BartEtal04c):
        # the missing word joined to the value word before it must be one whole quote word,
        # with a capital where the second word starts (an all-lowercase join is not read apart).
        words = re.findall(r"\w+", fold(value_norm))
        raw = fold(" ".join(texts))
        def run_together(t):
            return any(w == t and i and re.search(
                r"(?<!\w)(?i:" + re.escape(words[i - 1]) + ")" + re.escape(t[0].upper()) + "(?i:" + re.escape(t[1:]) + r")(?!\w)", raw)
                for i, w in enumerate(words))
        missing = [t for t in missing if not run_together(t)]
    if missing and field == "booktitle" and house_booktitle_word(fold(value_norm), missing, joined):
        return True, []
    if missing and field == "journal" and journal_abbreviation_present(str(value or ""), joined):
        return True, []
    return not missing, missing
