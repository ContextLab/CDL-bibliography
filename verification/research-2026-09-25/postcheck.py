"""Deterministic post-check for the agent research route (2026-09-25).

Usage: postcheck.py <wave folder> [--bib PATH|HEAD] [--review PATH] [--offline]

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


# ---------------------------------------------------------------- text folding

def delatex(text):
    """LaTeX accents and special letters to plain Unicode letters."""
    text = re.sub(r"\\(['`^\"~=.])\s*\{?([A-Za-z])\}?",
                  lambda m: unicodedata.normalize("NFC", m[2] + ACCENTS[m[1]]), text)
    text = re.sub(r"\\([cvuHkr])\s*\{([A-Za-z])\}",
                  lambda m: unicodedata.normalize("NFC", m[2] + ACCENTS[m[1]]), text)
    text = re.sub(r"(\d+)\\textsuperscript\{([a-z]+)\}", r"\1\2", text)
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
    text = re.sub(r"[^0-9a-z]+", " ", text.casefold())
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


def registry_title_matches(record_title, entry_title):
    """A DOI record title that is the entry's title.

    Accepted: the record is the entry's title with a footnote appended (Crossref
    appends '11The percentage of nights...' to WoodEtal00b's title), or the titles
    match (titles_match) and carry the same part numbers ('... cortex II' is a
    different work from '... cortex'). A generic record title ('Correspondence')
    never matches."""
    if footnote_appended(record_title, entry_title):
        return True
    numerals = lambda t: {w for w in fold(t).split() if NUMERAL.match(w)}
    return numerals(record_title) == numerals(entry_title) and titles_match(record_title, entry_title)


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


def http_get(url, offline=False):
    """(status, body) for a GET, cached on disk; status 0 = network failure."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if path.exists():
        cached = json.loads(path.read_text())
        return cached["status"], cached["body"]
    if offline:
        return None, "offline: not cached"
    wait = PACE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL) as resp:
            status, body = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        status, body = err.code, err.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        _last[0] = time.time()
        return 0, f"network error: {err}"
    _last[0] = time.time()
    if status in (200, 404) or (status == 400 and "handles" in url):
        path.write_text(json.dumps({"url": url, "status": status, "body": body}))
    return status, body


def clean_doi(doi):
    doi = (doi or "").strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.lower()


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
                "title": html.unescape(re.sub(r"<[^>]+>", "", title)),
                "subtitle": html.unescape(re.sub(r"<[^>]+>", "", sub)) or None,
                "container": " ".join(msg.get("container-title") or []) or None,
                "print_year": date_year(msg, "published-print"),
                "online_year": date_year(msg, "published-online"),
                "issued_year": date_year(msg, "issued"),
                "page": msg.get("page"), "volume": msg.get("volume"),
                "issue": msg.get("issue"), "type": msg.get("type"),
            })
        else:
            out["error"] = f"Crossref record unavailable: HTTP {status}"
    elif out["ra"] == "DataCite":
        status, body = http_get(f"https://api.datacite.org/dois/{enc}", offline)
        if status == 200:
            attrs = json.loads(body)["data"]["attributes"]
            titles = attrs.get("titles") or [{}]
            out.update({"title": titles[0].get("title"),
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
    """'Jean-Pierre' -> 'J-P', 'S.W.' -> 'S W', 'T. V. P.' -> 'T V P', 'JP' -> 'J P'."""
    token = token.strip()
    if not token:
        return ""
    words = token.replace(".", ". ").split()
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
            m = H.LETTER_UNIT.match(p)
            letters.append(m.group(0) if m else p[0])
        out.append("-".join(letters))
    return " ".join(out)


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
    given, family = tokens[:start], tokens[start:]
    new_given = []
    for t in given:
        if is_initial(t):
            new_given.append(t)
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


def given_part(name):
    tokens = split_top(name)
    fam = surname(name)
    return " ".join(tokens[: len(tokens) - len(split_top(fam))])


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
        elif same and same[0] < key:
            plan.update(action="duplicate", merge_into=same[0],
                        detail=f"same work (title, first author, year) already in cdl.bib as {same[0]}: "
                               f"merge {key} into it")
        elif same:
            plan["detail"] = (f"same work (title, first author, year) as {', '.join(same)} in cdl.bib: "
                              f"{same[0]} should merge into {key}")
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


def print_years_in_notes(notes):
    years = set()
    for clause in re.split(r";\s|\.\s|\n", notes or ""):
        c = clause.lower()
        if "reprint" in c:
            continue
        if re.search(r"\bprint(ed)?\b|published-print|print year|print edition|print issue", c):
            years |= set(re.findall(r"\b(?:19|20)\d{2}\b", clause))
    return years


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


def check_entry(row, current, bib, ctx, review=None, validation=None):
    """Post-check one researcher row. Returns the per-key record."""
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

    # --- DOI registration and record match
    doi_status = None
    if "doi" in applied:
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
            rec_title = re.sub(r"(?i)^chapter\s+(?:\d+|[ivxlc]+)\.?[:.]?\s+", "", rec["title"])
            record_title = rec_title + (": " + rec["subtitle"] if rec.get("subtitle") else "")
            cands = [c for c in ((applied.get("title") or {}).get("value"), current.get("title"),
                                 (applied.get("chapter") or {}).get("value"), current.get("chapter"),
                                 (applied.get("booktitle") or {}).get("value"), current.get("booktitle"))
                     if c]
            if not any(titles_match(record_title, c) or registry_title_matches(rec_title, c) for c in cands):
                del applied["doi"]
                flag(flags, "doi_title_mismatch", "doi",
                     f"{doi} is registered to {record_title!r} ({rec.get('ra')}), not this entry's title; "
                     "DOI change dropped", "dropped")
            else:
                rec_pages = re.sub(r"(?<!-)[-–](?!-)", "--", rec["page"]) if rec.get("page") else None
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
                elif rec.get("print_year") and year and rec["print_year"] != year:
                    flag(flags, "print_year_conflict", "year",
                         f"{rec.get('ra')} published-print {rec['print_year']} vs year {year}: print year wins")
                    suggestions.setdefault("year", rec["print_year"])
                elif not rec.get("print_year") and rec.get("issued_year") and year \
                        and rec["issued_year"] != year:
                    flag(flags, "doi_record_conflict", "year",
                         f"{rec.get('ra')} record of {doi} is dated {rec['issued_year']}, proposal {year}")

    # --- print year from notes / year evidence
    year_now = (applied.get("year") or {}).get("value") or current.get("year")
    note_prints = print_years_in_notes(row.get("notes"))
    corroborated = len(quoted_print_years(fields.get("year")).get(year_now) or ()) >= 2
    if note_prints and year_now and year_now not in note_prints and not corroborated:
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

    # ENTRYTYPE
    if "ENTRYTYPE" in applied:
        et, notes, bad = normalise_entrytype(applied["ENTRYTYPE"]["value"])
        if bad:
            del applied["ENTRYTYPE"]
            final["ENTRYTYPE"] = current.get("ENTRYTYPE")
            flag(flags, "invalid_entrytype", "ENTRYTYPE", bad + "; not applied", "dropped")
        else:
            set_norm("ENTRYTYPE", et, notes)
    elif final.get("ENTRYTYPE") == "conference" and applied:
        set_norm("ENTRYTYPE", "inproceedings", ["@conference -> @inproceedings"])

    # titled chapter: @inbook{title=book, chapter=chapter} -> @incollection
    chap = final.get("chapter", "")
    if final.get("ENTRYTYPE") in ("inbook", "incollection") and chap and not re.fullmatch(r"[\dIVXivx]+", chap):
        book = final.get("booktitle") or (final.get("title") if not titles_match(final.get("title", ""), chap)
                                          else current.get("title"))
        if book and not titles_match(book, chap):
            bt = guarded(book, H.format_journal_name(book))
            if bt is None:
                bt = book
                flag(flags, "booktitle_case", "booktitle",
                     f"house title-case formatter would alter protected text in {book!r}; "
                     "booktitle kept as given, check its title case")
            set_norm("ENTRYTYPE", "incollection", ["titled chapter: @inbook -> @incollection"]
                     if final.get("ENTRYTYPE") == "inbook" else ["chapter field folded into title"])
            set_norm("booktitle", bt, [f"book title moved to booktitle: {bt!r}"])
            set_norm("title", chap, [f"chapter title moved to title: {chap!r}"])
            final.pop("chapter", None)
            applied.pop("chapter", None)
            if "chapter" in current:
                removals["chapter"] = "moved into title (@incollection house form)"

    # titled chapter already split into title + booktitle: @inbook -> @incollection
    if final.get("ENTRYTYPE") == "inbook" and not final.get("chapter") and final.get("booktitle") \
            and final.get("title") and verdict != "no_source":
        set_norm("ENTRYTYPE", "incollection", ["titled chapter with booktitle: @inbook -> @incollection"])

    # a chapter or proceedings paper has no journal: drop it, or move it to the
    # booktitle (none yet) or series (a book series given as the journal)
    if final.get("ENTRYTYPE") in CONTAINED_TYPES and final.get("journal"):
        journal = final["journal"]
        bt, series = final.get("booktitle", ""), final.get("series", "")
        fj, fbt = fold(journal), fold(bt)
        if not bt:
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

    # single-source surname change: a new surname that respells a cited one is held,
    # i.e. that author keeps the cited name, unless the reviewer confirms the author
    if "author" in applied and applied["author"]["source"] == "researcher" and current.get("author"):
        strip = lambda n: fold(SUFFIX_RE.sub(r"\1", surname(n)))
        old = {strip(n): n for n in split_names(current["author"]) if n != "others"}
        ev = (fields.get("author") or {}).get("evidence") or []
        rv_author = ((review or {}).get("field_verdicts") or {}).get("author")
        release = bool(review) and reviewer_confirms(rv_author)
        out, kept, released = [], [], []
        for n in split_names(final["author"]):
            new = strip(n)
            if not new or new in old or n == "others":
                out.append(n)
                continue
            near = sorted(((difflib.SequenceMatcher(None, o, new).ratio(), o) for o in old if o), reverse=True)
            near = [o for r, o in near if r >= 0.75]
            if not near or any(o.replace(" ", "") == new.replace(" ", "") for o in near):
                out.append(n)  # an added or reordered author, or a brace/spacing fix, not a respelling
                continue
            last = new.split()[-1]
            hosts = {urlparse(e.get("url", "")).netloc for e in ev if last in fold(e.get("quote", "")).split()}
            if len(hosts) >= 2:
                out.append(n)
                continue
            detail = (f"surname {near[0]!r} -> {new!r} rests on {len(hosts)} source host(s) {sorted(hosts)}; "
                      "single-source surname changes need corroboration or the user's sign-off")
            if release:
                flag(flags, "surname_single_source", "author",
                     detail + f"; applied: the reviewer confirms the author ({rv_author})", "applied")
                out.append(n)
                released.append(n)
            else:
                cited = normalise_name(old[near[0]])[0]  # the whole cited name, house format
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
            new, notes, problems = normalise_address(v, ctx["cities"])
            for p in problems:
                flag(flags, "us_address_state_unknown", "address", p)
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
        if (applied.get(name) or {}).get("source") == "reviewer" or name in removals:
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

    # --- changes vs current
    changes = []
    for name, a in sorted(applied.items()):
        if final.get(name) == current.get(name):
            continue
        change = {"field": name, "current": current.get(name), "proposed": final.get(name),
                  "source": a["source"], "evidence": a.get("evidence") or []}
        if a.get("normalised_from"):
            change["normalised_from"] = a["normalised_from"]
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
    if verdict in ("ambiguous", "no_source"):
        flag(flags, "needs_user", "verdict", f"verdict {verdict}: user decision")

    return {"key": key, "verdict": verdict, "flags": flags, "normalisations": norms,
            "changes": changes, "removals": removals, "held": held,
            "suggestions": suggestions, "key_plan": plan, "doi_status": doi_status,
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


def run(folder, bib="HEAD", review_path=None, offline=False, write=True):
    folder = Path(folder)
    bibd = load_bib(bib)
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
               "index": index}
        out = {}
        for stem, row in rows:
            rec = check_entry(row, bibd.get(row["key"]), bibd, ctx,
                              review=reviews.get(row["key"]) if with_review else None,
                              validation=validation.get(row["key"]))
            rec["batch"] = stem
            out[row["key"]] = rec
        wave_duplicates(out)
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
            "reviewer": ({"agree": rv.get("agree"), "sampled_as": rv.get("sampled_as"),
                          "field_verdicts": rv.get("field_verdicts"), "problems": rv.get("problems"),
                          "suggested_value": rv.get("suggested_value")} if rv else None),
            "needs_user": bool(r["verdict"] in ("ambiguous", "no_source") or
                               any(f["action"] in ("held", "flag") for f in r["flags"]) or r["key_plan"]["action"] != "keep"),
        })
    if write:
        (folder / "postcheck.json").write_text(json.dumps(post, indent=1, ensure_ascii=False) + "\n")
        (folder / "merged.json").write_text(json.dumps(page, indent=1, ensure_ascii=False) + "\n")
    return post, page, rules_only, merged


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--bib", default="HEAD", help="cdl.bib path, or HEAD (default) for the committed file")
    ap.add_argument("--review", default=None)
    ap.add_argument("--offline", action="store_true", help="use cached network responses only")
    args = ap.parse_args(argv)
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
