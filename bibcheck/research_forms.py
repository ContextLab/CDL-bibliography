"""House normalisers for research approvals (used by bibcheck/research_route.py).

These are the normalisers of the research post-check
(verification/research-2026-09-25/postcheck.py, kept on the archive branch:
https://github.com/ContextLab/CDL-bibliography/tree/verification-records-2026-09/verification/research-2026-09-25), copied unchanged so that
`crossref restore` can re-check a saved research approval without the research
folders. Nothing here makes a network request.
"""
import html
import os
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
_cwd = os.getcwd()
sys.path.insert(0, str(ROOT / "bibcheck"))
os.chdir(ROOT)  # helpers reads its word lists relative to the working directory

try:
    import helpers as H  # noqa: E402
finally:
    os.chdir(_cwd)

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


def city_states(bib):
    """{folded city: state code} from cdl.bib's own 'City, {ST}' addresses (unique only)."""
    seen = {}
    for e in bib.values():
        m = re.fullmatch(r"\s*([^,{}]+),\s*\{([A-Z]{2})\}\s*", e.get("address", ""))
        if m and m[2] in US_CODES:
            seen.setdefault(fold(m[1]), set()).add(m[2])
    return {c: s.pop() for c, s in seen.items() if len(s) == 1}


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


def evidence_items(spec):
    """The evidence items of a resolution `set`, first to last: its own url/quote, then
    every {url, quote} in `evidence` and `extra_evidence` (a list, or one item). A value
    whose words an official record prints far apart on one page (KahaEtal08a's first and
    last folios, Rans02's contents start and running-head end) is covered by the union
    of several quotes (user rule 2026-09-26)."""
    items = []
    if spec.get("url") or spec.get("quote"):
        items.append({"url": spec.get("url"), "quote": spec.get("quote")})
    for name in ("evidence", "extra_evidence"):
        extra = spec.get(name) or []
        for x in [extra] if isinstance(extra, dict) else extra:
            items.append({"url": (x or {}).get("url"), "quote": (x or {}).get("quote")} if isinstance(x, dict)
                         else {"url": None, "quote": None})
    return items


PAGE_RANGE = re.compile(r"^\s*(\d+)\s*(?:-{1,3}|–)\s*(\d+)\s*$")

def inferred_end_page(V, value, quotes, urls, next_quote):
    """(ok, why) for pages S--E whose end page no source prints (user rule, round 2: 'infer
    it from the next item's printed start page - 1'): S must be in the quotes, and the
    next item's printed start page -- the LAST number of the next_start quote, the page
    column of a contents line ('Diagnostic Audiometry Robert W. Keith, Ph.D. 33') -- must
    be E + 1."""
    m = PAGE_RANGE.match(str(value or ""))
    if not m:
        return False, f"next_start: {value!r} is not one page range S--E"
    start, end = int(m[1]), int(m[2])
    if end < start:
        return False, f"next_start: end page {end} is before start page {start}"
    ok, _ = V.value_supported("pages", str(start), quotes, urls)
    if not ok:
        return False, f"next_start: start page {start} is not in the quote"
    nums = re.findall(r"(?<!\d)\d+(?!\d)", V.norm(next_quote))
    if not nums or int(nums[-1]) != end + 1:
        return False, (f"next_start: the next item's printed start page is {nums[-1] if nums else 'missing'}, "
                       f"not {end + 1} (end page {end} + 1)")
    return True, None


def catalogue_extent(V, value, quotes):
    """(ok, why) for pages 1--N of a numbered monograph issued whole (Gomu53, Gate17): the
    library catalogue's physical extent 'N p.' (README default: monograph pages are the
    catalogue extent). Only a range starting at page 1, only the 'N p.' form."""
    m = PAGE_RANGE.match(str(value or ""))
    if not m or m[1] != "1":
        return False, None
    hit = any(re.search(r"(?<![\d\[\]-])" + m[2] + r"\s*p\.", V.norm(q)) for q in quotes)
    return hit, None if hit else f"no catalogue extent '{m[2]} p.' in the quote"


def roman_page_prefix(V, value, quotes):
    """(ok, why) for a volume printed as the roman-numeral prefix of its page numbers
    (ICASSP 'I-185-I-188', SAGE 'I-212-I-224'; README default: the prefix is the Volume,
    in arabic). The numeral must be upper case and joined to a page number by a hyphen."""
    v = str(value or "").strip()
    if not v.isdigit() or int(v) < 1:
        return False, None
    numeral = V.int_to_roman(int(v)).upper()
    hit = any(re.search(r"(?<![A-Za-z])" + numeral + r"-\d+", q) for q in quotes)
    return hit, None if hit else f"no page prefix '{numeral}-<page>' in the quote"


def normalise_emdash(value):
    """Em dashes in titles are written a---b, no spaces (user rule, 2026-09-26)."""
    v = str(value or "")
    new = v.replace("—", "---").replace("\\textemdash{}", "---").replace("\\textemdash ", "---")
    new = re.sub(r"\s*---\s*", "---", new)
    return new, ([f"em dash house form: {v!r} -> {new!r}"] if new != v else [])


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
