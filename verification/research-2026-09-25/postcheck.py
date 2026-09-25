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
ORDINAL_FIELDS = ("title", "booktitle", "journal", "edition", "series", "publisher",
                  "organization", "howpublished", "note", "school", "institution")
SUFFIX_RE = re.compile(r"(?:,?\s+|,\s*)(?:Jr|Sr|II|III|IV)\.?(\}?)$")
HONORIFICS = {"professor", "prof", "dr", "sir", "mr", "mrs", "ms", "phd", "md", "by",
              "the", "and", "editor", "editors", "ed", "eds", "author", "authors",
              "lecture", "copyright", "of", "with"}
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
    tokens = split_top(name)
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


GIVEN_TOKEN = re.compile(r"[^\W\d_][\w'’\-]*\.?", re.U)


def evidence_given_names(sur, quotes):
    """Given-name strings the evidence prints next to surname `sur`."""
    target = fold(sur).split()[-1:] if fold(sur) else []
    if not target:
        return []
    target = target[0]
    found = []
    for q in quotes:
        q = html.unescape(q).replace("\\/", "/")
        for g, f in re.findall(r'"given"\s*:\s*"([^"]*)"\s*,\s*"family"\s*:\s*"([^"]*)"', q):
            if fold(f).split()[-1:] == [target]:
                found.append(g)
        for f, g in re.findall(r'"family"\s*:\s*"([^"]*)"\s*,\s*"given"\s*:\s*"([^"]*)"', q):
            if fold(f).split()[-1:] == [target]:
                found.append(g)
        for f, g in re.findall(r"<LastName>(.*?)</LastName>\s*<ForeName>(.*?)</ForeName>", q):
            if fold(f).split()[-1:] == [target]:
                found.append(g)
        for f, g in re.findall(r"FAU\s*-\s*([^,\n]+),\s*([^\n]+)", q):
            if fold(f).split()[-1:] == [target]:
                found.append(g.strip())
        # a name printed in capitals (GEOFF WARD) is a name, not clumped initials
        q = re.sub(r"\b[A-Z]{4,}\b", lambda m: m.group(0).capitalize(), q)
        if re.search(r'"given"|<LastName>|FAU\s*-', q):
            continue
        toks = list(GIVEN_TOKEN.finditer(q))
        for i, t in enumerate(toks):
            if fold(t.group(0)) != target:
                continue
            given = []
            j = i
            while j > 0 and len(given) < 4:
                prev = toks[j - 1]
                gap = q[prev.end():toks[j].start()]
                word = prev.group(0)
                if gap.strip() or not word[:1].isupper() or fold(word) in HONORIFICS:
                    break
                given.insert(0, word)
                j -= 1
            if given:
                found.append(" ".join(given))
    return found


def letters(initials):
    return initials.replace("-", " ").split()


def initials_from_evidence(value, quotes):
    """Extend or hyphenate initials the evidence prints more fully.

    Returns (new value, notes). Never removes an initial; applies only when every
    evidence form for that surname agrees (each is a prefix of the longest)."""
    names, notes = [], []
    for n in split_names(value):
        if n == "others" or n.startswith("{"):
            names.append(n)
            continue
        sur, giv = surname(n), given_part(n)
        forms = [given_initials(g) for g in evidence_given_names(sur, quotes)]
        forms = [f for f in forms if f]
        if not forms:
            names.append(n)
            continue
        best = max(forms, key=lambda f: (len(letters(f)), "-" in f))
        if not all(letters(best)[: len(letters(f))] == letters(f) for f in forms):
            names.append(n)
            continue
        have = letters(giv)
        if have == letters(best) and "-" in best and "-" not in giv:
            notes.append(f"{sur}: '{giv}' -> '{best}' (hyphenated given name in source)")
            names.append(f"{best} {sur}")
        elif len(have) < len(letters(best)) and letters(best)[: len(have)] == have:
            notes.append(f"{sur}: '{giv}' -> '{best}' (source gives all initials)")
            names.append(f"{best} {sur}")
        else:
            names.append(n)
    return " and ".join(names), notes


# ---------------------------------------------------------------- field rules

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


def same_work(a, b):
    """Title + first author surname + year."""
    fa = lambda e: fold(surname(split_names(e.get("author") or e.get("editor") or "")[0])) \
        if (e.get("author") or e.get("editor")) else ""
    return (titles_match(a.get("title", ""), b.get("title", ""))
            and fa(a) and fa(a) == fa(b)
            and a.get("year", "").strip() == b.get("year", "").strip())


def next_suffix(used):
    for s in H.get_key_suffixes(len(used) + 2):
        if s not in used:
            return s


def key_plan(key, current, final, bib, taken, reserved):
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
    if key_fits(key, target) or H.key_overrides.get(key) == target:
        if same_doi:
            plan["action"] = "duplicate"
            plan["merge_into"] = same_doi[0]
        return plan
    plan["rename_reason"] = ("key does not follow the corrected metadata"
                             if key_fits(key, key_target(current) or "\0")
                             else "key already differed from the rule before this correction")
    group = [k for k in list(bib) + sorted(taken) if k != key and key_fits(k, target)]
    group = sorted(set(group))
    dup = [k for k in group if k in bib and same_work(bib[k], final)] or \
          [k for k in same_doi if key_fits(k, target)]
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


def patent_like(row, current):
    urls = " ".join([row.get("identity", {}).get("url", "")] +
                    [e.get("url", "") for f in (row.get("fields") or {}).values()
                     for e in (f.get("evidence") or [])])
    return (current.get("ENTRYTYPE") == "patent" or "patent" in urls.lower()
            or re.search(r"\bpatent\b", row.get("notes", ""), re.I) is not None)


def check_entry(row, current, bib, ctx, review=None, validation=None):
    """Post-check one researcher row. Returns the per-key record."""
    key = row["key"]
    verdict = row.get("verdict")
    fields = row.get("fields") or {}
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

    vfields = (validation or {}).get("fields") or {}
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
            held.pop(name, None)
        for name, verdict_f in verdicts.items():
            if verdict_f == "disagree" and name in applied and applied[name]["source"] == "researcher" \
                    and name not in sv:
                del applied[name]
                flag(flags, "reviewer_disagrees", name,
                     "reviewer disagrees and gave no replacement value; not applied", "held")

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
            if not any(titles_match(record_title, c) or titles_match(rec_title, c) for c in cands):
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
                if rec.get("print_year") and year and rec["print_year"] != year:
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
    if note_prints and year_now and year_now not in note_prints:
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

    # names
    for name in NAME_FIELDS:
        if name in applied:
            new, notes = normalise_names(applied[name]["value"])
            bad = [n for n in notes if "could not parse" in n or "cannot parse" in n]
            for b in bad:
                flag(flags, "name_unparsed", name, b)
            set_norm(name, new, [n for n in notes if n not in bad])
            quotes = [e.get("quote", "") for e in (fields.get(name) or {}).get("evidence") or []]
            quotes.append((row.get("identity") or {}).get("quote", ""))
            if applied.get(name, {}).get("source") == "researcher":
                new2, notes2 = initials_from_evidence(final[name], quotes)
                if notes2:
                    flag(flags, "initials_from_source", name, "; ".join(notes2), "applied")
                set_norm(name, new2, notes2)

    # single-source surname change: a new surname that respells a cited one
    if "author" in applied and applied["author"]["source"] == "researcher" and current.get("author"):
        strip = lambda n: fold(SUFFIX_RE.sub(r"\1", surname(n)))
        old = {strip(n) for n in split_names(current["author"]) if n != "others"}
        ev = (fields.get("author") or {}).get("evidence") or []
        for n in split_names(final["author"]):
            new = strip(n)
            if not new or new in old or n == "others":
                continue
            near = [o for o in old if o and difflib.SequenceMatcher(None, o, new).ratio() >= 0.75]
            if not near:
                continue  # an added or reordered author, not a respelling
            last = new.split()[-1]
            hosts = {urlparse(e.get("url", "")).netloc for e in ev if last in fold(e.get("quote", "")).split()}
            if len(hosts) < 2:
                flag(flags, "surname_single_source", "author",
                     f"surname {near[0]!r} -> {new!r} rests on {len(hosts)} source host(s) {sorted(hosts)}; "
                     "single-source surname changes need corroboration or the user's sign-off", "held")

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
    plan = key_plan(key, current, final, bib, ctx["taken"], ctx["reserved"])
    if plan["action"] in ("rename", "collision"):
        ctx["taken"].add(plan["new_key"])
    if plan["action"] == "duplicate":
        flag(flags, "duplicate", "key", plan.get("detail") or
             f"same DOI as {plan['merge_into']}: merge {key} into {plan['merge_into']}")
    elif plan["action"] == "collision":
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

    def pass_(with_review):
        ctx = {"doi": doi, "cities": city_states(bibd), "taken": set(), "reserved": renamed_away()}
        out = {}
        for stem, row in rows:
            rec = check_entry(row, bibd.get(row["key"]), bibd, ctx,
                              review=reviews.get(row["key"]) if with_review else None,
                              validation=validation.get(row["key"]))
            rec["batch"] = stem
            out[row["key"]] = rec
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
                               any(f["action"] in ("held", "flag") and f["code"] != "initials_from_source"
                                   for f in r["flags"]) or r["key_plan"]["action"] != "keep"),
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
