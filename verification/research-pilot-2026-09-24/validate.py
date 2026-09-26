"""Check every quoted piece of evidence in the research pilot against its source.

For each evidence item {url, quote} in batch-*.json, fetch the URL (or read the
local PDF page for file: URLs), normalise both texts the same way (HTML stripped,
entities decoded, Unicode NFKC, curly quotes and dashes folded, whitespace
collapsed, case folded) and require the quote to occur verbatim. Fetched bodies
are cached under .bibcheck/research-pilot/ so a repeat makes no requests.

A field counts as evidenced only if at least one of its quotes is found; an entry
passes only if its identity quote and every confirmed/corrected field pass. This
checks that the quoted words exist at the cited place and that the proposed
value's surnames, numbers and words all appear inside the found quotes. Whether
the source is the right work and version is what the spot-check is for.
"""
import hashlib
import html
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CACHE = ROOT / ".bibcheck/research-pilot"
import ssl
import certifi
SSL = ssl.create_default_context(cafile=certifi.where())
UNVERIFIED_TLS = set()
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
UA = "CDL-bibliography citation checker (research pilot; contact via repository owner)"
# Apostrophe look-alikes (O´Reilly, Oʼ, O′) fold to "'" before NFKC splits U+00B4 into
# a space and a combining accent; trademark signs are dropped (FitBit® = FitBit).
PRE_FOLD = str.maketrans({"\u00b4": "'", "\u02bc": "'", "\u2032": "'", "\u00ae": "", "\u2122": "", "\u00a9": ""})
FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                      "—": "-", "−": "-", " ": " ", "­": ""})


ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
           ".": "\u0307", "c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b", "k": "\u0328", "r": "\u030a"}


SPECIAL = {"l": "ł", "L": "Ł", "o": "ø", "O": "Ø", "ss": "ß", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
           "aa": "å", "AA": "Å", "i": "ı", "j": "ȷ"}


SYMBOLS = {"times": "\u00d7", "textregistered": "\u00ae", "texttrademark": "\u2122", "textcopyright": "\u00a9"}


def delatex(text):
    """LaTeX accent macros to Unicode: \\'{e}, \\'e, {\\'e}, \\c{c}, \\v{s} ..."""
    def repl(m):
        return unicodedata.normalize("NFC", m[2] + ACCENTS[m[1]])
    # Math sub/superscripts keep their content: {GABA$_A$} -> GABAA, $_{2}$ -> 2.
    text = re.sub(r"\$\s*[_^]\s*\{?([A-Za-z0-9]+)\}?\s*\$", r"\1", text)
    text = re.sub(r"\\(" + "|".join(SYMBOLS) + r")(?![A-Za-z])\s?", lambda m: SYMBOLS[m[1]], text)
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


def strip_html(body):
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", body)
    meta = " ".join(re.findall(r'(?is)<meta[^>]+content="([^"]*)"', body))
    return meta + " " + re.sub(r"(?s)<[^>]+>", " ", body)


RETRY_STATUSES = (429, 503)
MAX_RETRIES = 4
MAX_WAIT = 120.0


def retry_after_seconds(header, attempt, now=None):
    """Seconds to wait before retry number attempt (0-based): the server's Retry-After
    (delta-seconds or an HTTP date) when it gives one, else 5, 10, 20, 40 s; capped at MAX_WAIT."""
    wait = None
    if header:
        header = header.strip()
        if header.isdigit():
            wait = float(header)
        else:
            try:
                from email.utils import parsedate_to_datetime
                when = parsedate_to_datetime(header)
                wait = when.timestamp() - (time.time() if now is None else now)
            except (TypeError, ValueError, IndexError):
                wait = None
    if wait is None or wait < 0:
        wait = 5.0 * 2 ** attempt
    return min(wait, MAX_WAIT)


def urlopen_polite(req, context, timeout=60):
    """urlopen that answers 429 Too Many Requests (and 503) by waiting as asked and
    retrying, up to MAX_RETRIES times; the last HTTPError is raised if it never succeeds."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=context)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUSES or attempt == MAX_RETRIES:
                raise
            time.sleep(retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None, attempt))


WALL = re.compile(r"cookies must be enabled|captcha|just a moment|verify you are (a )?human|access denied|are you a robot", re.I)


def pubmed_text(pmid):
    """The PubMed record as its web page shows it, read through E-utilities (the web
    page answers scripts with a cookie wall): title, 'Forename Lastname' authors,
    journal and citation, followed by the raw MEDLINE and XML records."""
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=" + pmid
    xml = urlopen_polite(urllib.request.Request(base + "&retmode=xml", headers={"User-Agent": UA}), SSL).read().decode()
    time.sleep(0.5)
    medline = urlopen_polite(urllib.request.Request(base + "&rettype=medline&retmode=text", headers={"User-Agent": UA}), SSL).read().decode()
    tag = lambda t: " ".join(re.findall(rf"<{t}[^>]*>(.*?)</{t}>", xml, re.S))
    names = [f"{f} {l}".strip() for l, f in re.findall(r"<LastName>(.*?)</LastName>\s*<ForeName>(.*?)</ForeName>", xml)]
    head = " ".join([tag("ArticleTitle"), ", ".join(names), tag("Title"), tag("ISOAbbreviation"),
                     tag("Year"), tag("Volume"), tag("Issue"), tag("MedlinePgn")])
    return head + "\n" + medline + "\n" + re.sub(r"<[^>]+>", " ", xml)


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".txt")
    if path.exists():
        if path.with_suffix(".unverified-tls").exists():
            UNVERIFIED_TLS.add(url)
        return path.read_text(), False
    m = re.match(r"https?://(?:www\.)?(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d+)", url)
    if m:
        text = pubmed_text(m[1])
        time.sleep(1.0)
        path.write_text(text)
        return text, True
    if url.startswith("file:"):
        parsed = urlparse(url)
        pdf = Path(unquote(parsed.path))
        page = re.search(r"page=(\d+)", parsed.fragment or "")
        args = ["pdftotext", "-layout"]
        if page:
            args += ["-f", page[1], "-l", page[1]]
        text = subprocess.run(args + [str(pdf), "-"], check=True, capture_output=True, text=True).stdout
        network = False
    else:
        def get(agent):
            req = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": "*/*"})
            with urlopen_polite(req, SSL) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        try:
            raw, ctype = get(UA)
        except urllib.error.HTTPError as exc:
            if exc.code != 403:
                raise
            # Some publishers refuse non-browser agents; the content is the same page.
            raw, ctype = get(BROWSER_UA)
        except urllib.error.URLError as exc:
            if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                raise
            # A server with an incomplete certificate chain: fetch unverified and say so.
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "*/*"})
            with urlopen_polite(req, ssl._create_unverified_context()) as resp:
                raw, ctype = resp.read(), resp.headers.get("Content-Type", "")
            UNVERIFIED_TLS.add(url)
            path.with_suffix(".unverified-tls").write_text(url)
        if "pdf" in ctype or raw[:4] == b"%PDF":
            tmp = path.with_suffix(".pdf")
            tmp.write_bytes(raw)
            text = subprocess.run(["pdftotext", "-layout", str(tmp), "-"], check=True, capture_output=True, text=True).stdout
        else:
            text = raw.decode("utf-8", "replace")
            if "html" in ctype or text.lstrip().startswith("<"):
                # Keep the raw markup too: API answers (E-utilities XML) are quoted with their tags.
                text = text + "\n" + strip_html(text)
        network = True
        time.sleep(1.5)
        if len(text) < 3000 and WALL.search(text):
            raise RuntimeError("blocked by a bot/cookie wall; not cached")
    path.write_text(text)
    return text, network


def check(item, requests):
    url, quote = item.get("url"), item.get("quote")
    if not url or not quote:
        return {"ok": False, "why": "missing url or quote"}
    try:
        text, network = fetch(url)
        requests[0] += network
    except Exception as exc:  # unreachable source: the evidence is unverified, not false
        return {"ok": False, "why": f"fetch failed: {type(exc).__name__}: {exc}"[:200]}
    return {"ok": norm(quote) in norm(text), "why": None if norm(quote) in norm(text) else "quote not found at url"}


# Fields a quote cannot settle (entry type, where a URL points): left to the spot-check.
JUDGMENT = {"entrytype", "howpublished", "url"}


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
TRANSLIT_BACK = {}


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
    return re.sub(r"\b(vols?\.?\s*|volume\s+)([ivxlcdm]+)\b", repl, text)


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


def value_supported(field, value, texts, urls=()):
    if field == "doi" and value and any(str(value).lower() in unquote(u).lower() for u in urls):
        return True, []  # the evidence URL is the DOI's own record
    normed = ordinals_to_digits(" ".join(norm(t) for t in texts))
    if field == "volume":
        normed = roman_volumes(normed)
    joined = fold(normed)
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
        if present(t) or present(translit.get(t, t)) or present(t, joined_translit):
            return True
        if field in ("journal", "booktitle"):
            if t in ABBREVIATED and re.search(ABBREVIATED[t], joined):
                return True
            if t == "series" and series_present(fold(value_norm), joined):
                return True
        return False
    missing = [t for t in tokens if not present_any(t)]
    return not missing, missing


def main(folder=None):
    folder = Path(folder) if folder else HERE
    requests = [0]
    report = []
    for batch in sorted(folder.glob("batch-*.json")):
        for row in json.loads(batch.read_text()):
            entry = {"key": row["key"], "verdict": row.get("verdict"), "batch": batch.stem, "fields": {}}
            ident = row.get("identity") or {}
            entry["identity"] = check(ident, requests) if ident.get("url") else {"ok": False, "why": "no identity evidence"}
            for field, f in (row.get("fields") or {}).items():
                if f.get("status") not in ("confirmed", "corrected"):
                    continue
                if field.lower() in JUDGMENT:
                    entry.setdefault("judgment_fields", []).append(field)
                    continue
                items = f.get("evidence") or []
                results = [check(e, requests) for e in items]
                found = [e["quote"] for e, r in zip(items, results) if r["ok"]]
                urls = [e["url"] for e, r in zip(items, results) if r["ok"]]
                supported, missing = value_supported(field, f.get("value"), found, urls)
                entry["fields"][field] = {"status": f["status"], "ok": bool(found) and supported,
                                          "value_missing_from_quotes": missing,
                                          "failures": [r["why"] for r in results if not r["ok"]]}
            evidenced = entry["identity"]["ok"] and all(f["ok"] for f in entry["fields"].values())
            entry["passes"] = bool(evidenced and row.get("verdict") in ("verified", "correction"))
            report.append(entry)
    out = {"network_requests": requests[0], "unverified_tls_urls": sorted(UNVERIFIED_TLS), "entries": len(report),
           "passing": sum(e["passes"] for e in report),
           "by_verdict": {v: sum(e["verdict"] == v for e in report) for v in sorted({e["verdict"] for e in report})},
           "report": report}
    (folder / "validation.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "report"}))
    for e in report:
        bad = [f for f, v in e["fields"].items() if not v["ok"]]
        if e["verdict"] in ("verified", "correction") and not e["passes"]:
            print("FAIL", e["key"], e["verdict"], "identity" if not e["identity"]["ok"] else "", bad)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
