"""Position- and role-aware evidence from a local PDF for one bibliography entry.

The verifier decides, field by field, whether the printed PDF of the cited
version *supports* a BibTeX entry.  Every decision is made by deterministic
code over text extracted by code (``pdftotext -bbox-layout``).  No model is
consulted; an optional model may at most suggest candidate lines elsewhere,
and nothing it says is read here.

Only bibliographic regions of the cited article count as evidence:

* the title run and the byline directly beneath it (identity);
* header/footer bands of the article's first page (journal citation line,
  masthead, DOI line) and running heads that repeat across the article's pages;
* the printed page-number sequence of the article's own pages;
* an explicit self-citation line on the first page ("Citation:", "Cite as:").

Repository/publisher cover pages (JSTOR, ResearchGate, HighWire, Science) are
recognised and skipped: they are never the identity page and never supply values.
Copyright years are never a year source (vanVEtal13: (c) 2012 on a 2013 issue).

Body text, statistics, figure/table labels, reference lists, received/accepted
dates, copyright years, affiliations and postcodes, DOI/ISSN/price-code digits,
and lines belonging to other articles never supply a value.  A field is

* ``supported``    -- a bibliographic region prints exactly the cited value and
                      no bibliographic region prints a different one;
* ``contradicted`` -- a bibliographic region prints a different value;
* ``absent``       -- the PDF does not settle the field (abstain).

An entry passes only when every checked field is supported, the PDF is the
published version, and no other bibliographic field is left unchecked.
"""

import argparse
import functools
import hashlib
import html
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import unicodedata

from .verification import normalized, split_authors  # noqa: E402  (stable helpers)

LAYOUT_POLICY = 1
VERIFIER_POLICY = 1
MAX_PAGES = 120
CHECKED_FIELDS = ("title", "author", "journal", "year", "volume", "number", "pages", "doi")
# Fields that carry no bibliographic claim, or that the user's policy removes
# from @article entries (publisher, 2026-09-22 decision); never evidence.
IGNORED_FIELDS = {"ID", "ENTRYTYPE", "url", "urldate", "abstract", "keywords", "file"}
POLICY_DROPPED = {"article": {"publisher"}}

# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


_WORD = re.compile(
    r'<word xMin="([-\d.]+)" yMin="([-\d.]+)" xMax="([-\d.]+)" yMax="([-\d.]+)">(.*?)</word>')


def parse_bbox_layout(xhtml):
    """Parse ``pdftotext -bbox-layout`` output into pages of lines of words."""
    pages = []
    for page_match in re.finditer(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', xhtml, re.S):
        width, height, body = float(page_match[1]), float(page_match[2]), page_match[3]
        lines = []
        for block_no, block in enumerate(re.finditer(r"<block [^>]*>(.*?)</block>", body, re.S)):
            for line in re.finditer(r"<line [^>]*>(.*?)</line>", block[1], re.S):
                words = [
                    {"x0": float(w[1]), "y0": float(w[2]), "x1": float(w[3]), "y1": float(w[4]),
                     "text": html.unescape(w[5])}
                    for w in _WORD.finditer(line[1])
                ]
                if words:
                    lines.append({"block": block_no, "words": words})
        pages.append({"page": len(pages) + 1, "width": width, "height": height, "lines": lines})
    return pages


def extract_layout(path, max_pages=MAX_PAGES):
    result = subprocess.run(
        ["pdftotext", "-bbox-layout", "-f", "1", "-l", str(max_pages), "-enc", "UTF-8", str(path), "-"],
        capture_output=True, timeout=120, check=True,
    )
    return parse_bbox_layout(result.stdout.decode("utf-8", "replace"))


def cached_layout(path, cache_dir):
    """Layout for ``path`` cached by PDF content hash; never writes near the source."""
    sha = file_sha256(path)
    cache_dir = Path(cache_dir)
    target = cache_dir / f"{sha}-layout-v{LAYOUT_POLICY}.json"
    if target.exists():
        record = json.loads(target.read_text())
        if record["pdf_sha256"] == sha and record["policy"] == LAYOUT_POLICY:
            return record
    record = {"pdf_sha256": sha, "policy": LAYOUT_POLICY,
              "extractor": "pdftotext -bbox-layout", "pages": extract_layout(path)}
    if file_sha256(path) != sha:
        raise ValueError("PDF changed during extraction")
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False))
    tmp.replace(target)
    return record


# --------------------------------------------------------------------------
# Text normalization
# --------------------------------------------------------------------------

SPACING_DIACRITICS = {
    "´": "́", "ˊ": "́", "`": "̀", "ˋ": "̀",
    "¨": "̈", "ˆ": "̂", "^": "̂", "˜": "̃", "~": "̃",
    "ˇ": "̌", "¸": "̧", "˚": "̊", "°": "̊",
    "˘": "̆", "˝": "̋", "¯": "̄", "˙": "̇",
}
QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "´": "'",
                        "“": '"', "”": '"'})
DASH_CHARS = "‐‑‒–—―−­"


def nfc(text):
    return unicodedata.normalize("NFC", text)


def fold(text):
    """Compatibility-fold PDF text (ligatures, full-width) keeping accents."""
    text = re.sub(r"(?<=\d)[\u2009\u202f\u2006\u2005](?=\d{3}(?!\d))", "", text)   # 2\u2009597 -> 2597
    text = "".join(" " if ch in "     " else ch for ch in text)
    text = unicodedata.normalize("NFKC", text)
    return nfc(text)


def alnum_key(text):
    """Letters (accents kept) and digits only, lowercased: layout-insensitive."""
    return "".join(ch for ch in nfc(fold(text)).lower() if ch.isalnum())


def strip_accents(text):
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if not unicodedata.combining(ch))


def word_variants(word):
    """Readings of a PDF word whose accents were extracted as spacing marks.

    ``Buzs´aki`` may mean the mark belongs to the next or previous letter.
    A word without spacing marks has exactly one reading.
    """
    word = fold(word) if not any(c in SPACING_DIACRITICS for c in word) else word
    if not any(c in SPACING_DIACRITICS for c in word):
        return {nfc(word)}
    out = set()
    for direction in (1, -1):
        chars, result, i = list(word), [], 0
        pending = None
        seq = chars if direction == 1 else chars
        if direction == 1:
            while i < len(seq):
                c = seq[i]
                if c in SPACING_DIACRITICS:
                    pending = SPACING_DIACRITICS[c]
                elif pending and c.isalpha():
                    result.append(c + pending)
                    pending = None
                else:
                    result.append(c)
                i += 1
        else:
            for c in seq:
                if c in SPACING_DIACRITICS and result and result[-1][-1:].isalpha():
                    result[-1] = result[-1] + SPACING_DIACRITICS[c]
                elif c not in SPACING_DIACRITICS:
                    result.append(c)
        out.add(nfc("".join(result)))
    return out


def clean_number_text(text):
    """Remove strings whose digits never denote volume/issue/page/year."""
    t = fold(text)
    t = re.sub(r"(?i)\bdoi\s*[:.]?\s*10\.\d{3,9}/\S+", " ", t)
    t = re.sub(r"(?i)\b10\.\d{4,9}/\S+", " ", t)
    t = re.sub(r"(?i)\b(?:https?://|www\.)\S+", " ", t)
    t = re.sub(r"\S+@\S+", " ", t)
    t = re.sub(r"(?i)\bPII\b.*", " ", t)
    t = re.sub(r"(?i)\b(?:downloaded|accessed|retrieved|printed on|this article was downloaded)\b[^|\u2022]*", " ", t)
    t = re.sub(r"(?i)\bISSN\b[:\s]*", " ", t)
    t = re.sub(r"\b\d{4}\s*-\s*\d{3}[\dXx]\b", " ", t)          # ISSN
    t = re.sub(r"\S*[/$]\S*", " ", t)                              # price codes, 00/$ etc.
    t = re.sub(r"(?i)\b(?:received|revised|accepted|submitted|available online|published online|"
               r"first published|online publication|epub|advance access|advance online|"
               r"published\s+\d|resubmitted|editor)\b[^|•]*", " ", t)
    t = re.sub(r"(?i)(?:©|ª|\bcopyright\b|\(c\))\s*(?:by\s+)?(?:the\s+authors?\(?s?\)?\s*)?\(?\s*\d{4}\)?", " ", t)
    return t


def unify_dashes(text):
    for ch in DASH_CHARS:
        text = text.replace(ch, "-")
    text = re.sub(r"(?<=\d)\s*±\s*(?=\d)", "-", text)     # font-mapped en dash
    text = re.sub(r"(?<=\d)\s*-+\s*(?=[a-zA-Z]?\d)", "-", text)
    return text


# --------------------------------------------------------------------------
# Page model
# --------------------------------------------------------------------------


def _median(values, default=0.0):
    values = [v for v in values if v > 0]
    return statistics.median(values) if values else default


def prepare_pages(raw_pages):
    pages = []
    for raw in raw_pages:
        H = raw["height"] or 1.0
        lines = []
        for idx, line in enumerate(raw["lines"]):
            words = line["words"]
            heights = [w["y1"] - w["y0"] for w in words]
            # reference size from alphanumeric words only (tall bars/brackets never set it)
            alnum = sorted(h for w, h in zip(words, heights) if any(c.isalnum() for c in w["text"]))
            line_h = alnum[int(0.9 * (len(alnum) - 1))] if alnum else (max(heights) if heights else 0)
            big = [(w, h) for w, h in zip(words, heights) if h >= 0.8 * line_h and any(c.isalnum() for c in w["text"])]
            base = _median([h for _, h in big], line_h)
            baseline = _median([w["y1"] for w, _ in big], max(w["y1"] for w in words))
            y1 = max(w["y1"] for w in words)
            for w, h in zip(words, heights):
                w["sup"] = bool(h < 0.78 * base and w["y1"] < baseline - 0.12 * base and len(words) > 1)
            text = " ".join(fold(w["text"]) for w in words)
            lines.append({
                "idx": idx, "block": line["block"], "words": words, "text": text,
                "text_nosup": " ".join(fold(w["text"]) for w in words if not w["sup"]),
                "x0": min(w["x0"] for w in words), "x1": max(w["x1"] for w in words),
                "y0": min(w["y0"] for w in words), "y1": y1, "h": base,
                "ry0": min(w["y0"] for w in words) / H, "ry1": y1 / H,
                # vertical text (margin stamps, axis labels): tall, narrow word boxes
                "rotated": sum((w["x1"] - w["x0"]) < 0.8 * (w["y1"] - w["y0"]) and len(w["text"]) > 2
                               for w in words) > len(words) / 2,
            })
        weighted = []
        for ln in [l for l in lines if not l["rotated"]]:
            weighted.extend([ln["h"]] * max(1, len(ln["text"]) // 10))
        body_h = _median(weighted, 10.0)
        pages.append({"page": raw["page"], "width": raw["width"], "height": H,
                      "lines": lines, "body_h": body_h})
    return pages


def rows_of(lines, tolerance=0.45, max_gap=None):
    """Merge lines sharing a baseline band into rows ordered left to right.

    With ``max_gap`` (in multiples of line height) only horizontally adjacent
    lines merge, so a byline never absorbs the neighbouring column.
    """
    rows = []
    for ln in sorted(lines, key=lambda l: (l["x0"], l["y1"])) if max_gap else sorted(lines, key=lambda l: (l["y1"], l["x0"])):
        for row in rows:
            ref = row[0]
            mid = (ln["y0"] + ln["y1"]) / 2
            same = ref["y0"] - 1 <= mid <= ref["y1"] + 1 or abs(ln["y1"] - ref["y1"]) <= tolerance * max(ln["h"], ref["h"], 1)
            if same and max_gap is not None:
                h = max(ln["h"], ref["h"], 1)
                right = max(l["x1"] for l in row)
                left = min(l["x0"] for l in row)
                same = (ln["x0"] - right) <= max_gap * h and (left - ln["x1"]) <= max_gap * h
            if same:
                row.append(ln)
                break
        else:
            rows.append([ln])
    rows = [sorted(r, key=lambda l: l["x0"]) for r in rows]
    return sorted(rows, key=lambda r: (min(l["y1"] for l in r), r[0]["x0"]))


TOP_BAND, BOTTOM_BAND = 0.115, 0.895

REFERENCE_LIKE = re.compile(
    r"^\s*(?:\[\d+\]|\d{1,3}\.\s+[A-Z]|\d{1,3}\s+[A-Z][a-z]+,?\s+[A-Z]\.)|\bet al\b|\(\d{4}[a-z]?\)\.\s+[A-Z]")
AFFILIATION_WORDS = re.compile(
    r"(?i)\b(?:universit\w*|department|dept|institute|institut|laborator\w*|school|college|faculty|"
    r"hospital|centre|center|division|program|avenue|street|road|boulevard|campus|box|usa|u\.s\.a|"
    r"canada|germany|france|japan|china|italy|spain|netherlands|england|uk|e-?mail|correspond\w*|"
    r"present address|tel|fax|inc|corp|corporation|research|labs?|llc|gmbh|ltd|foundation|society|"
    r"academy|clinic|unit|google|microsoft|facebook|ibm|openai|deepmind)\b")


def band_rows(page, *, top=TOP_BAND, bottom=BOTTOM_BAND):
    lines = [l for l in page["lines"] if l["ry1"] <= top or l["ry0"] >= bottom]
    return rows_of(lines)


def row_text(row):
    return " ".join(l["text"] for l in row)


def band_words(row):
    """Words of a header/footer row, re-joining letter-spaced runs ("4 5 3" -> "453").

    Only rows where most words are single characters are treated as letter-spaced,
    and only same-class neighbours (digits with digits, letters with letters) that
    sit closer than half a character height are joined.
    """
    words = [dict(w) for l in row for w in l["words"] if not w.get("sup")]
    if not words or sum(len(w["text"]) == 1 for w in words) < 0.5 * len(words):
        return words
    out = []
    for w in words:
        prev = out[-1] if out else None
        h = max(w["y1"] - w["y0"], 1)
        if prev is not None and len(w["text"]) <= 3 and len(prev["text"]) <= 12 and \
                w["x0"] - prev["x1"] <= 0.5 * h and \
                ((prev["text"].isdigit() and w["text"].isdigit()) or (prev["text"].isalpha() and w["text"].isalpha())):
            prev["text"] += w["text"]
            prev["x1"] = w["x1"]
        else:
            out.append(w)
    return out


def band_text(row):
    return " ".join(fold(w["text"]) for w in band_words(row))


# --------------------------------------------------------------------------
# Entry parsing
# --------------------------------------------------------------------------

PARTICLES = {"van", "von", "der", "den", "de", "del", "della", "da", "di", "du", "la", "le", "ter",
             "ten", "dos", "das", "st", "bin", "al", "el"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def _brace_tokens(text):
    tokens, depth, cur = [], 0, ""
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch.isspace() and depth == 0:
            if cur:
                tokens.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        tokens.append(cur)
    return tokens


def _latex(text):
    return nfc(normalized(text))


def parse_bib_name(raw):
    """Return (given tokens, surname tokens, suffix) in lowercase NFC text."""
    raw = raw.strip()
    parts = [p.strip() for p in re.split(r",(?![^{]*})", raw)]
    suffix = None
    if len(parts) == 1:
        toks = _brace_tokens(parts[0])
        if len(toks) == 1:
            given, last = [], toks
        else:
            # surname = last token plus preceding lowercase particles
            i = len(toks) - 1
            while i - 1 >= 1 and _latex(toks[i - 1]).lower() in PARTICLES and toks[i - 1][:1].islower():
                i -= 1
            given, last = toks[:i], toks[i:]
            if len(given) >= 1 and _latex(last[-1]).lower().rstrip(".") in SUFFIXES and len(last) == 1 and len(given) >= 2:
                suffix = last[-1]
                last = [given[-1]]
                given = given[:-1]
    else:
        last = _brace_tokens(parts[0])
        if len(parts) == 3:
            suffix, given = parts[1], _brace_tokens(parts[2])
        else:
            given = _brace_tokens(parts[1])
    given_out = []
    for tok in given:
        text = re.sub(r"[\u2010\u2011]", "-", _latex(tok).lower())
        text = re.sub(r"\.(?=\S)", ". ", text) if re.fullmatch(r"(?:\w\.){2,}", text) else text
        for piece in text.replace(".", " ").split():
            piece = piece.strip("-")
            if piece:
                given_out.append(piece)
    last_out = []
    for tok in last:
        text = _latex(tok).lower().translate(QUOTES)
        last_out.extend(text.split())
    return given_out, last_out, (_latex(suffix).lower().rstrip(".") if suffix else None)


def entry_authors(fields):
    names = split_authors(fields.get("author", ""))
    return [parse_bib_name(n) for n in names if n.strip()]


def normalize_issue(value):
    v = fold(str(value)).lower().strip()
    v = unify_dashes(v)
    v = re.sub(r"\s*[-/–]\s*", "-", v)
    v = re.sub(r"^(?:suppl(?:ement)?|supp)\.?\s*", "suppl ", v)
    v = re.sub(r"^s(\d+)$", r"suppl \1", v)
    v = re.sub(r"\s+", " ", v).strip()
    m = re.fullmatch(r"0*(\d+)", v)
    return m[1] if m else v


def normalize_number(value):
    m = re.fullmatch(r"0*(\d+)", str(value).strip())
    return m[1] if m else str(value).strip().lower()


def parse_entry_pages(value):
    v = unify_dashes(fold(_latex(value))).strip().lower()
    v = re.sub(r"\s*-+\s*", "-", v)
    m = re.fullmatch(r"([a-z]?\d+)(?:-([a-z]?\d+))?", v)
    if not m:
        return {"raw": v, "first": None, "last": None}
    first, last = m[1], m[2] or m[1]
    return {"raw": v, "first": first, "last": last}


# --------------------------------------------------------------------------
# Journal matching
# --------------------------------------------------------------------------

STOP = {"of", "the", "and", "in", "for", "on", "&", "a", "an", "to", "de", "la", "le", "und", "fur", "für"}


@functools.lru_cache(maxsize=None)
def journal_words(name):
    t = fold(name).lower().replace("&", " and ")
    t = re.sub(r"[^\w\s]", " ", t)
    return t.split()


@functools.lru_cache(maxsize=None)
def journal_key(name):
    try:
        name = _latex(name)
    except ValueError:
        pass
    words = journal_words(name)
    if words and words[0] == "the":
        words = words[1:]
    return " ".join(words)


SECTION_WORDS = {"review", "reviews", "article", "articles", "letter", "letters", "report", "reports",
                 "research", "opinion", "perspective", "perspectives", "feature", "commentary", "brief",
                 "communication", "communications", "news", "views", "original", "special", "issue", "the",
                 "cover", "focus", "insight", "insights", "essay", "primer"}
# Exact acronyms printed instead of the full title; each checked against the
# journal's own front matter.  No other acronym is expanded.
JOURNAL_ACRONYMS = {
    "pnas": {"proceedings of the national academy of sciences",
             "proceedings of the national academy of sciences usa",
             "proceedings of the national academy of sciences of the united states of america"},
}


# Capitalised words that may directly precede a journal name on an imprint line
# ("... Institute of Technology Journal of Cognitive Neuroscience 30:9").  Any
# other capitalised word before a match could be part of a longer journal name.
IMPRINT_WORDS = {"technology", "press", "inc", "ltd", "limited", "society", "association", "elsevier",
                 "publishers", "publishing", "reserved", "llc", "group", "sciences", "org", "com", "www",
                 "doi", "online", "open", "access", "downloaded"}
NAME_HEADS = {"nature", "journal", "annals", "review", "reviews", "trends", "current", "frontiers", "proceedings",
              "european", "american", "international", "british", "canadian", "cell", "brain", "cognitive",
              "experimental", "clinical", "applied", "human", "behavioral", "behavioural", "developmental",
              "social", "biological", "physical", "computational", "neural", "molecular", "comparative"}


@functools.lru_cache(maxsize=8)
def _known_words(known_journals):
    return [journal_key(k).split() for k in known_journals]


def _extends_known(before, needle_words, known_words):
    """True when ``before + needle`` is inside the name of another known journal."""
    seq = [before] + list(needle_words)
    n = len(seq)
    return any(words[i:i + n] == seq for words in known_words for i in range(len(words) - n + 1))


def _bounded_find(hay, needle_words, known_words=()):
    """Index of ``needle_words`` in ``hay`` [(lower, original)] as a whole journal name.

    The words just before may be a lowercase token (site name), a section label or a
    separator, never a capitalised name word or connector (so ``Cognitive Neuroscience``
    is not found inside ``Journal of Cognitive Neuroscience``); the word just after must
    not continue the name (``Cognition`` is not ``Cognition and Emotion``).
    """
    words = [h[0] for h in hay]
    n = len(needle_words)
    for i in range(len(words) - n + 1):
        if words[i:i + n] != needle_words:
            continue
        if i:
            before, orig = hay[i - 1][0], hay[i - 1][1]
            if before.isalpha() and before not in SECTION_WORDS and before not in IMPRINT_WORDS and (
                    before in STOP or orig[:1].isupper() or _extends_known(before, needle_words, known_words)):
                continue
        if len(hay[i + n - 1]) > 2 and hay[i + n - 1][2]:
            continue      # "Journal of Experimental Psychology:" -- a section title follows
        if i + n < len(words):
            after = words[i + n]
            if after.isalpha() and after not in {"vol", "volume", "no", "issue", "pp", "doi", "www", "article",
                                                 "articles", "report", "reports", "review", "research",
                                                 "published", "copyright", "letters", "letter"} \
                    and not re.fullmatch(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*", after):
                continue
        return i
    return None


def _segment_words(text):
    """(lower, original, followed_by_colon) for each word of ``text``."""
    t = fold(text).replace("&", " and ")
    t = re.sub(r"[|\u2022\u00b7\u25cf\u25a0]", " | ", t)
    t = re.sub(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", " ", t)
    out = []
    for m in re.finditer(r"[\w|]+", t):
        colon = bool(re.match(r"\s*:", t[m.end():]))
        out.append((m[0].lower(), m[0], colon))
    return out


def is_abbreviation_of(abbrev_words, full_words):
    content = [w for w in full_words if w not in STOP]
    ab = [w for w in abbrev_words if w not in STOP]
    if len(ab) != len(content) or len(ab) < 2:
        return False
    return all(f.startswith(a) and len(a) >= 1 for a, f in zip(ab, content))


def journal_in_text(journal, text, known_journals=()):
    """Return ('full'|'abbreviation', matched text) when ``text`` names the journal."""
    target = journal_key(journal).split()
    if not target:
        return None
    words = _segment_words(text)
    known_words = _known_words(tuple(known_journals))
    idx = _bounded_find(words, target, known_words)
    if idx is not None:
        return ("full", " ".join(w[1] for w in words[idx: idx + len(target)]))
    for acronym, names in JOURNAL_ACRONYMS.items():
        if " ".join(target) in names and _bounded_find(words, acronym.split()) is not None:
            return ("acronym", acronym.upper())
    # Letter-spaced mastheads ("PS YC HOLOGICA L SC IENCE"): whole segment only.
    for segment in re.split(r"[|\u2022\u00b7]", fold(text)):
        toks = segment.split()
        if not toks or sum(len(t) <= 2 for t in toks) < 0.4 * len(toks):
            continue                       # only genuinely letter-spaced text is squashed
        squashed = re.sub(r"[^\w]", "", segment.lower().replace("&", "and"))
        if squashed and squashed in {"".join(target), "the" + "".join(target)} and len(squashed) >= 6:
            return ("full", segment.strip())
    # Abbreviations: candidate runs of words (periods allowed) bounded by non-words.
    raw = re.sub(r"[|•·]", " | ", fold(text))
    tokens = re.findall(r"[A-Za-z][A-Za-z'À-ɏ]*\.?|\d+|\S", raw)
    content = [w for w in journal_words(journal) if w not in STOP]
    n = len(content)
    if n < 2:
        return None
    for i in range(len(tokens)):
        run, j = [], i
        while j < len(tokens) and len(run) < n + 4 and re.fullmatch(r"[A-Za-z][A-Za-z'À-ɏ]*\.?", tokens[j]):
            run.append(tokens[j].rstrip(".").lower())
            j += 1
        if i > 0 and re.fullmatch(r"[A-Za-z][A-Za-z'À-ɏ]*\.?", tokens[i - 1]):
            continue
        for end in range(len(run), 1, -1):
            cand = run[:end]
            if end < len(run):
                continue  # the whole word run must be the abbreviation (bounded)
            if [w for w in cand if w not in STOP] == content:
                continue  # unabbreviated words: only the bounded full-name rule applies
            if j + 1 < len(tokens) and tokens[j] in {":", "-", "\u2013", "\u2014", "/"} and tokens[j + 1][:1].isupper():
                continue  # "J Exp Psychol: Gen" -- a section title continues the name
            if is_abbreviation_of(cand, journal_words(journal)):
                if any(len(a) >= 3 for a in cand):
                    rivals = [k for k in known_journals
                              if journal_key(k) != journal_key(journal) and is_abbreviation_of(cand, journal_words(k))]
                    if not rivals:
                        return ("abbreviation", " ".join(tokens[i:j]))
    return None


# --------------------------------------------------------------------------
# Citation-line templates (applied only to bibliographic rows)
# --------------------------------------------------------------------------

YEAR = r"(1[6-9]\d\d|20[0-4]\d)"
MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
          r"sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|spring|summer|autumn|fall|winter)\.?")
PAGE = r"([a-zA-Z]?\d{1,6})"
ISSUE = r"((?:suppl(?:ement)?\.?\s*|s)?\d{1,4}(?:\s*[-/]\s*\d{1,4})?|suppl(?:ement)?\.?)"

TEMPLATES = [
    # APA: "2013, Vol. 142, No. 2, 412-425" ; "Vol. 25, No. 2. pp. 229-236, 1995"
    ("labeled", re.compile(
        r"(?i)(?:\b" + YEAR + r"\s*,\s*)?\bvol(?:ume)?\.?\s*(\d{1,5})(?![A-Za-z0-9])\s*[,.;|]?\s*"
        r"(?:\(\s*" + ISSUE + r"\s*\)|(?:no|nos|number|issue|nr)\.?\s*" + ISSUE + r"(?![A-Za-z0-9]))?\s*[,.;:|]?\s*"
        r"(?:(?:pp?|pages)\.?\s*)?(?:" + PAGE + r"\s*-\s*" + PAGE + r")?"
        r"(?:\s*[,;.]\s*\(?" + YEAR + r"\)?(?!\d)|\s*\(" + YEAR + r"\)|(?:(?<=[,;.])|(?<=[,;.]\s))\s*" + YEAR + r"(?!\d))?")),
    # PNAS: "PNAS 2024 Vol. 121 No. 35" (journal-anchored, see parse_citation_text)
    # MIT Press: "30:9, pp. 1345-1365"
    ("mit", re.compile(r"(?i)\b(\d{1,4}):(\d{1,3}),\s*pp\.\s*" + PAGE + r"\s*-\s*" + PAGE)),
    # Elsevier: "Neuropsychologia 38 (2000) 410-425"
    ("elsevier", re.compile(r"(?i)\b(\d{1,5})\s*\(\s*" + YEAR + r"\s*\)\s*" + PAGE + r"(?:\s*-\s*" + PAGE + r")?\b")),
    # OUP/Brain: "BRAIN 2017: 140; 1337-1350", "Cerebral Cortex May 2008;18:1150-1160"
    ("oup", re.compile(r"(?i)\b" + YEAR + r"\s*[;:]\s*(\d{1,5})(?:\s*\(\s*" + ISSUE + r"\s*\))?\s*[;:]\s*"
                       + PAGE + r"(?:\s*-\s*" + PAGE + r")?\b")),
    # "30(4):1250-1257", "6(6): e1000806", "18(2):123"
    ("vol_issue_pages", re.compile(r"(?i)(?<![\d.])(\d{1,5})\s*\(\s*" + ISSUE + r"\s*\)\s*[:,]\s*"
                                   + PAGE + r"(?:\s*-\s*" + PAGE + r")?\b")),
    # Nature Communications / Scientific Reports: "(2018) 9:2715" (article number)
    ("paren_year_vol_artno", re.compile(r"(?i)\(\s*" + YEAR + r"\s*\)\s*(\d{1,4})\s*:\s*(\d{1,8})\b(?!\s*-)")),
    # "Current Opinion in Behavioral Sciences 2015, 5:85-90"
    ("year_vol_colon", re.compile(r"(?i)\b" + YEAR + r"\s*,\s*(\d{1,4})\s*:\s*" + PAGE + r"\s*-\s*" + PAGE + r"\b")),
    # Springer/Wiley: "(2011) 18:1-10", "HIPPOCAMPUS 18:1175-1186 (2008)"
    ("vol_colon_pages", re.compile(r"(?i)(?<![\d.(])(\d{1,5})\s*:\s*" + PAGE + r"\s*-\s*" + PAGE + r"\b")),
    # Cell/Nature style after the journal name: "Neuron 50, 507-517, May 4, 2006"
    ("journal_comma", re.compile(r"(?i)^\s*(\d{1,5})\s*,\s*" + PAGE + r"(?:\s*-\s*" + PAGE + r")?\s*(?:[,(]|$)")),
    # "Psychological Reports, 1974, 34, 275-288" / "Memory & Cognition 2009, 37 (4), 464-476"
    ("journal_year", re.compile(r"(?i)^\s*[,.]?\s*" + YEAR + r"\s*[,.]\s*(\d{1,4})\s*(?:\(\s*" + ISSUE + r"\s*\))?"
                                r"\s*[,.]\s*" + PAGE + r"\s*-\s*" + PAGE + r"\b")),
    # Physical Review: "PHYSICAL REVIEW E 89, 052102 (2014)"
    ("artno_year", re.compile(r"(?i)^\s*(\d{1,5})\s*,\s*(\d{5,8})\s*\(\s*" + YEAR + r"\s*\)")),
]

ARTNO_PATTERNS = [
    re.compile(r"(?i)(?<![-\w])(e\d{4,8})\b(?!\s*-)"),
    re.compile(r"(?i)\barticle(?:\s+(?:no\.?|number|id))?\s*[:#]?\s*(\d{1,8})\b"),
    re.compile(r"(?i)\bart\.?\s*no\.?\s*(\d{1,8})\b"),
]

DATE_YEAR = re.compile(r"(?i)\b" + MONTHS + r",?\s*(?:\d{1,2},?\s*)?" + YEAR + r"\b")
PAREN_YEAR = re.compile(r"\(\s*" + YEAR + r"\s*\)")


def _is_year(value):
    return bool(re.fullmatch(YEAR, value or ""))


def citation_text(text):
    """The one normalisation shared by template parsing and journal offsets."""
    t = unify_dashes(clean_number_text(text)).replace("&", " and ")
    # Elsevier font maps "(2000)" to "Ž 2000 ." in some 2000-era PDFs
    t = re.sub(r"(?<=\d)\s*\u017d\s*((?:19|20)\d\d)\s*\.\s*", r" (\1) ", t)
    # Springer prints 2597 as "2 597" (thin space); re-join only after ':' or a dash
    t = re.sub(r"(?<=[:\-])\s*(\d{1,3}) (\d{3})(?!\d)", r"\1\2", t)
    return re.sub(r"[|\u2022\u00b7\u25cf\u25a0\u5169]", " | ", t)


def parse_citation_text(text, journal_hit):
    """Structured values from one bibliographic row; each value keeps its template."""
    t = citation_text(text)
    values = []

    def add(field, value, template):
        if value:
            values.append({"field": field, "value": value, "template": template})

    for name, rx in TEMPLATES:
        if name in {"journal_comma", "artno_year", "journal_year"}:
            continue
        for m in rx.finditer(t):
            g = m.groups()
            if name == "labeled":
                y1, vol, iss1, iss2, first, last, y2, y3, y4 = g
                y2 = y2 or y3 or y4
                add("volume", vol, name)
                add("number", iss1 or iss2, name)
                if first:
                    add("first", first, name)
                    add("last", last, name)
                add("year", y1 or y2, name)
            elif name == "mit":
                add("volume", g[0], name); add("number", g[1], name)
                add("first", g[2], name); add("last", g[3], name)
            elif name == "elsevier":
                add("volume", g[0], name); add("year", g[1], name)
                add("first", g[2], name); add("last", g[3] or g[2] if g[3] else None, name)
                if not g[3]:
                    add("first_only", g[2], name)
            elif name == "oup":
                add("year", g[0], name); add("volume", g[1], name); add("number", g[2], name)
                add("first", g[3], name)
                if g[4]:
                    add("last", g[4], name)
            elif name == "vol_issue_pages":
                if _is_year(g[1]) and not g[2].lower().startswith("e"):
                    continue
                add("volume", g[0], name); add("number", g[1], name)
                if g[2].lower().startswith("e"):
                    add("artno", g[2], name)
                else:
                    add("first", g[2], name)
                    if g[3]:
                        add("last", g[3], name)
            elif name == "paren_year_vol_artno":
                add("year", g[0], name); add("volume", g[1], name); add("artno", g[2], name)
            elif name == "year_vol_colon":
                add("year", g[0], name)
            elif name == "vol_colon_pages":
                add("volume", g[0], name); add("first", g[1], name); add("last", g[2], name)
    if journal_hit is not None:
        after = t[journal_hit:]
        m = re.match(r"(?i)^\s*" + YEAR + r"\s+vol", after)
        if m:
            add("year", m[1], "journal_year_vol")
        for name in ("journal_year", "artno_year", "journal_comma"):
            rx = dict(TEMPLATES)[name]
            m = rx.match(after)
            if m:
                g = m.groups()
                if name == "artno_year":
                    add("volume", g[0], name); add("artno", g[1], name); add("year", g[2], name)
                elif name == "journal_year":
                    add("year", g[0], name); add("volume", g[1], name); add("number", g[2], name)
                    add("first", g[3], name); add("last", g[4], name)
                elif _is_year(g[0]):
                    continue                     # "Journal 2009, 37 ..." is a year, not a volume
                else:
                    add("volume", g[0], name); add("first", g[1], name)
                    if g[2]:
                        add("last", g[2], name)
                    else:
                        add("first_only", g[1], name)
                break
    if journal_hit is not None:
        m = re.match(r"^\s*" + PAGE + r"\s*-\s*" + PAGE + r"\s*\|", t)
        if m:
            add("first", m[1], "range_then_journal"); add("last", m[2], "range_then_journal")
    for rx in ARTNO_PATTERNS:
        for m in rx.finditer(t):
            add("artno", m[1], "article_number")
    for m in DATE_YEAR.finditer(t):
        add("year", m[1], "issue_date")
    for m in PAREN_YEAR.finditer(t):
        add("year", m[1], "paren_year")
    # "Science 333, 773 (2011)" style handled by journal_comma + paren_year
    return values


def journal_offset(journal, text, known_journals):
    """Character offset just after the journal name inside cleaned ``text``."""
    t = citation_text(text)
    words = journal_key(journal).split()
    if not words:
        return None
    pattern = r"(?i)\b(?:the\s+)?" + r"[\W_]+".join(re.escape(w) for w in words) + r"\b\.?"
    m = re.search(pattern, t)
    if m:
        return m.end()
    hit = journal_in_text(journal, text, known_journals)
    if hit and hit[0] in {"abbreviation", "acronym"}:
        idx = t.find(hit[1])
        if idx >= 0:
            return idx + len(hit[1])
    return None


# --------------------------------------------------------------------------
# Identity: title run + byline
# --------------------------------------------------------------------------


def title_key(text):
    """Letters, digits and hyphens (all dash forms), lowercased; spaces and other
    punctuation dropped.  Hyphens inside a word are kept: 'Inter-response' is not
    'Interresponse'."""
    text = nfc(fold(text)).lower()
    for ch in DASH_CHARS:
        text = text.replace(ch, "-")
    return "".join(ch for ch in text if ch.isalnum() or ch == "-")


def _line_key(line):
    return title_key(line["text_nosup"])


def find_title_runs(pages, title, max_pages=4, byline_surname=None):
    """Consecutive lines whose text equals the cited title exactly (title_key).

    A hyphen at the end of a line may be a real hyphen or a line-break hyphen,
    so both readings are tried; every other character must match.
    """
    target = title_key(title)
    runs = []
    if len(target.replace("-", "")) < 8:
        return runs
    for page in pages[:max_pages]:
        lines = page["lines"]
        keys = [_line_key(l) for l in lines]
        for i in range(len(lines)):
            accs = {""}
            for j in range(i, min(i + 10, len(lines))):
                nxt = set()
                for acc in accs:
                    for reading in {acc, acc[:-1] if acc.endswith("-") else acc}:
                        cand = reading + keys[j]
                        if target.startswith(cand):
                            nxt.add(cand)
                accs = nxt
                if not accs:
                    break
                if target in accs or any(a.endswith("-") and a[:-1] == target for a in accs):
                    run = lines[i:j + 1]
                    runs.append({"page": page["page"], "lines": run, "complete": _run_complete(lines, i, j, byline_surname)})
                    break
    return runs


def _run_complete(lines, i, j, byline_surname=None):
    """False when a same-size line directly above or below extends the heading.

    Checked geometrically (any block): a title line set in its own block, like a
    final word on the next line, still continues the heading.
    """
    run = lines[i:j + 1]
    h = _median([l["h"] for l in run], 0)
    if not h:
        return True
    x0, x1 = min(l["x0"] for l in run), max(l["x1"] for l in run)
    top, bottom = run[0]["y0"], run[-1]["y1"]
    for other in lines:
        if other in run or not other["text_nosup"].strip() or other["rotated"]:
            continue
        if byline_surname and byline_surname in {_norm_name(w) for w in re.findall(r"[^\W\d_][\w'\u2019-]*", other["text_nosup"])}:
            continue          # the byline itself, set at title size
        if abs(other["h"] - h) > 0.06 * h or other["x1"] < x0 - h or other["x0"] > x1 + h:
            continue
        above = 0 <= top - other["y1"] < 0.8 * h
        below = 0 <= other["y0"] - bottom < 0.8 * h
        overlap = other["y0"] < bottom and other["y1"] > top and not (other["x0"] >= x1 or other["x1"] <= x0)
        if above or below or overlap:
            return False
    return True


NAME_CHARS = "A-Za-zÀ-ɏḀ-ỿ'’´`¨ˆ˜ˇ¸˚˘˝.\\-"
NAME_WORD = r"[" + NAME_CHARS + r"]+"
DEGREES = {"phd", "md", "bs", "ms", "ma", "ba", "bsc", "msc", "dphil", "mphil", "frs", "mbbs", "psyd",
           "mph", "rn", "dr", "prof", "professor", "facp", "frcp", "jd", "edd", "scd", "dsc"}
TITLE_WORDS = {"member", "fellow", "senior", "student", "life", "ieee", "acm", "associate"}
AND_WORDS = {"and", "&", "und", "et", "y", "e"}


def _join_small_caps(words):
    """Rejoin small-caps names that extraction splits as 'J ONATHAN' (tall + short caps)."""
    out = []
    for w in words:
        if out and not w["sup"] and not out[-1]["sup"] and re.fullmatch(r"[A-Z]", out[-1]["text"]) \
                and re.fullmatch(r"[A-ZÀ-Þ'’.,-]{2,}", w["text"]) \
                and (w["y1"] - w["y0"]) < 0.92 * (out[-1]["y1"] - out[-1]["y0"]) \
                and w["x0"] - out[-1]["x1"] < 0.35 * (out[-1]["y1"] - out[-1]["y0"]):
            merged = dict(out[-1])
            merged["text"] = out[-1]["text"] + w["text"]
            merged["x1"] = w["x1"]
            out[-1] = merged
        else:
            out.append(w)
    return out


def byline_tokens(bands):
    """Token stream from byline bands.

    ``bands`` is a list of (kind, rows) where kind is 'name' or 'skip'.  Tokens are
    ('name', word), ('sep', kind), ('soft', newline) or ('row_end', '').  Superscripts,
    unraised affiliation letters, digits, e-mails, wide gaps and conjunctions become
    separators; a newline between consecutive name bands is *soft*.
    """
    tokens = []
    prev_kind = None
    for kind, rows in bands:
        if kind != "name":
            if tokens:
                tokens.append(("sep", "skipped"))
            prev_kind = kind
            continue
        if tokens and prev_kind == "name":
            tokens.append(("soft", "\n"))
        prev_kind = kind
        for ri, row in enumerate(rows):
            if ri:
                tokens.append(("sep", "gap"))
            words = _join_small_caps([w for line in row for w in line["words"]])
            h = _median([line["h"] for line in row], 1.0)
            prev = None
            for wi, w in enumerate(words):
                if prev is not None and w["x0"] - prev["x1"] > 1.2 * max(h, 1):
                    tokens.append(("sep", "gap"))
                prev = w
                if w["sup"]:
                    tokens.append(("sep", "marker"))
                    continue
                raw = w["text"]
                if "@" in raw or raw.lower().startswith(("http", "www.")):
                    tokens.append(("sep", "email"))
                    continue
                text = raw if any(c in SPACING_DIACRITICS for c in raw) else fold(raw)
                pieces = re.findall(NAME_WORD + r"|[^\s]", text)
                for pi, piece in enumerate(pieces):
                    low = piece.lower()
                    bare = low.replace(".", "")
                    if bare in DEGREES and ("." in piece or bare in {"phd", "md"}):
                        tokens.append(("sep", "degree"))
                    elif low in AND_WORDS:
                        tokens.append(("sep", "and"))
                    elif not re.search(r"[A-Za-zÀ-ɏḀ-ỿ]", piece):
                        tokens.append(("sep", "," if piece in ",;" else "marker"))
                    elif re.fullmatch(r"[a-z]", piece):
                        tokens.append(("sep", "marker"))
                    elif re.fullmatch(r"(?:[A-Za-z]\.){2,}", piece):
                        tokens.extend(("name", x + ".") for x in piece.split(".") if x)
                    else:
                        last_of_row = wi == len(words) - 1 and pi == len(pieces) - 1
                        if piece.endswith("-") and last_of_row and len(piece) > 1:
                            tokens.append(("name", piece))
                        else:
                            tokens.append(("name", piece.strip("-") or piece))
            tokens.append(("row_end", ""))
    joined, i = [], 0
    while i < len(tokens):
        kind, text = tokens[i]
        if kind == "name" and text.endswith("-") and i + 3 < len(tokens) and tokens[i + 1][0] == "row_end" \
                and tokens[i + 2][0] == "soft" and tokens[i + 3][0] == "name":
            joined.append(("name", text + tokens[i + 3][1]))
            i += 4
            continue
        joined.append((kind, text.strip("-") if kind == "name" and len(text) > 1 else text))
        i += 1
    return joined


def name_groups(tokens, newline_breaks):
    """Split the token stream into one word list per printed person.

    A group that contains affiliation words ends that row's names; the rest of
    the row is skipped.  With ``newline_breaks`` a row end also ends a person.
    """
    groups, cur, skip_row = [], [], False

    def flush():
        nonlocal cur, skip_row
        if cur:
            if AFFILIATION_WORDS.search(" ".join(cur)):
                skip_row = True
            else:
                groups.append(cur)
        cur = []

    for kind, text in tokens:
        if kind == "row_end":
            if skip_row:
                skip_row, cur = False, []
            elif newline_breaks:
                flush()
            continue
        if skip_row:
            continue
        if kind == "name":
            cur.append(text)
        elif kind == "soft":
            if newline_breaks:
                flush()
        else:
            flush()
    if not skip_row:
        flush()
    out = []
    for g in groups:
        if not out and len(g) > 1 and g[0].lower() == "by":
            g = g[1:]
        low = [x.lower().rstrip(".") for x in g]
        if all(x in TITLE_WORDS for x in low):
            continue
        if len(g) == 1 and low[0] in SUFFIXES and out:
            out[-1] = out[-1] + [g[0]]
            continue
        out.append(g)
    return out


def _norm_name(text):
    return nfc(text).lower().translate(QUOTES).rstrip(".")


def _given_token_ok(e, p):
    """Entry given token ``e`` (no dots) against PDF given word ``p``."""
    status = "mismatch"
    for v in word_variants(p):
        v = _norm_name(v).replace(".", "")
        if not v:
            continue
        if e == v:
            return "ok"
        if len(e) == 1 and v.startswith(e):
            return "ok"
        el, vl = e.split("-"), v.split("-")
        if len(el) > 1 and len(el) == len(vl) and all(
                a and b and (a == b or (len(a) == 1 and b.startswith(a))) for a, b in zip(el, vl)):
            return "ok"
        if len(v) == 1 and e.startswith(v):
            status = "initial_only"                          # entry is fuller than the print
        elif len(vl) > 1 and len(el) == len(vl) and all(len(b) == 1 and a.startswith(b) for a, b in zip(el, vl)):
            status = "initial_only"
    return status


def match_byline(authors, groups):
    """Match entry authors in order to PDF name groups; every PDF name must be used.

    Returns (status, detail): 'ok', 'contradicted' or 'absent'.
    """
    if not groups:
        return "absent", "no byline names"
    if any([x.lower().rstrip(".") for x in g] in (["al"], ["et", "al"]) for g in groups):
        return "absent", "byline abbreviated with et al."
    matched = []
    for n, (given, surname, suffix) in enumerate(authors):
        if n >= len(groups):
            return "contradicted", f"byline has {len(groups)} names; entry lists {len(authors)}"
        words = list(groups[n])
        pdf_suffix = None
        if len(words) > 1 and _norm_name(words[-1]) in SUFFIXES:
            pdf_suffix = _norm_name(words[-1])
            words = words[:-1]
        k = len(surname)
        if len(words) < k:
            return "contradicted", f"author {n + 1}: byline name {' '.join(groups[n])!r} too short"
        pdf_surname = words[-k:]
        if not all(any(_norm_name(v) == s for v in word_variants(p)) for p, s in zip(pdf_surname, surname)):
            return "contradicted", f"author {n + 1}: surname {' '.join(surname)!r} vs printed {' '.join(pdf_surname)!r}"
        pdf_given = words[:-k]
        if len(pdf_given) != len(given):
            return "contradicted", f"author {n + 1}: given names {given} vs printed {pdf_given}"
        for e, p in zip(given, pdf_given):
            status = _given_token_ok(e, p)
            if status == "initial_only":
                return "absent", f"author {n + 1}: PDF prints only initial(s) for {given}"
            if status != "ok":
                return "contradicted", f"author {n + 1}: given names {given} vs printed {pdf_given}"
        if (suffix or None) != (pdf_suffix or None):
            return "contradicted", f"author {n + 1}: suffix {suffix} vs printed {pdf_suffix}"
        matched.append(" ".join(groups[n]))
    if len(groups) > len(authors):
        extra = groups[len(authors):]
        if len(extra) == 1 and len(extra[0]) == 1:
            return "absent", f"unexplained word after the last author: {extra[0][0]!r}"
        return "contradicted", f"byline has further names: {[' '.join(g) for g in extra]}"
    return "ok", matched


STOP_LINE = re.compile(
    r"(?i)^\s*(?:abstract|summary|a b s t r a c t|keywords?|key words|introduction|received|accepted|published|"
    r"revised|article info|article history|a r t i c l e|citation|editor|edited by|copyright|©|open access|"
    r"background|objectives?|highlights|check for updates|research article|original article|doi|the journal|"
    r"affiliations?|corresponding)\b")


def _name_words(text):
    t = re.sub(r"[\d*†‡§¶⁎∗,;&()\[\]]|\band\b", " ", fold(text))
    return [w for w in t.split() if not re.fullmatch(r"[a-z]|[^\w]+", w)]


STOP_SQUASHED = ("abstract", "summary", "keywords", "introduction", "received", "accepted", "articleinfo",
                 "articlehistory", "highlights", "citation", "editedby", "openaccess", "checkforupdates")


def is_stop_row(text):
    squashed = re.sub(r"[^a-z]", "", fold(text).lower())
    return bool(STOP_LINE.match(text)) or squashed.startswith(STOP_SQUASHED)


def looks_like_name_row(text):
    if is_stop_row(text) or AFFILIATION_WORDS.search(text) or "@" in text or ":" in text:
        return False
    if re.search(r"\b(?:1[89]|20)\d\d\b", text):
        return False
    words = _name_words(text)
    if not words or len(words) > 30:
        return False
    caps = sum(1 for w in words if w[:1].isupper())
    lower = [w for w in words if w[:1].islower() and w.lower().rstrip(".") not in PARTICLES]
    return caps >= max(2, int(0.8 * len(words))) and not lower


def is_affiliation_row(text):
    """Affiliation/address/e-mail rows between byline rows (never paragraph prose)."""
    words = fold(text).split()
    if len(words) > 30 or is_stop_row(text):
        return False
    return bool(AFFILIATION_WORDS.search(text)) or "@" in text


def _starts_as_affiliation(text):
    t = fold(text).strip()
    return bool(re.match(r"^(?:[\d*†‡§¶⁎∗]|[a-z]\s|\(|the\s)", t, re.I) and
                AFFILIATION_WORDS.search(t)) or bool(AFFILIATION_WORDS.match(t)) or "@" in t


def _bands(rows):
    """Group rows that share a baseline (side-by-side names) into bands."""
    bands = []
    for row in rows:
        y = max(l["y1"] for l in row)
        h = _median([l["h"] for l in row], 1.0)
        if bands and abs(y - bands[-1][0]) <= 0.35 * h:
            bands[-1][1].append(row)
        else:
            bands.append([y, [row]])
    return [sorted(b[1], key=lambda r: r[0]["x0"]) for b in bands]


def find_byline(page, run, authors):
    """Bands under the title run that form the byline, and the match result.

    Name bands are kept; affiliation bands (smaller type, or starting with an
    affiliation word/marker) are skipped; anything else ends the byline.  The
    byline must end inside the searched window, or the result is 'absent'.
    """
    H, W = page["height"], page["width"]
    last = run["lines"][-1]
    x0 = min(l["x0"] for l in run["lines"])
    x1 = max(l["x1"] for l in run["lines"])
    title_h = _median([l["h"] for l in run["lines"]], 0)
    lo_x, hi_x = x0 - 0.12 * W, x1 + 0.12 * W
    below = []
    for l in page["lines"]:
        if l in run["lines"] or not (last["y1"] - 0.5 * title_h <= l["y0"] <= last["y1"] + 0.35 * H):
            continue
        width = max(l["x1"] - l["x0"], 1)
        inside = max(0.0, min(l["x1"], hi_x) - max(l["x0"], lo_x)) / width
        rotated = (l["y1"] - l["y0"]) > 2.5 * max(l["h"], 1) and width < 3 * max(l["h"], 1)
        margin = l["x1"] < 0.08 * W or l["x0"] > 0.92 * W
        if inside >= 0.7 and not rotated and not margin:
            below.append(l)
    bands = _bands(rows_of(below, max_gap=3.0))
    if not bands or not authors:
        return {"status": "absent", "detail": "no text under title", "rows": []}
    first_surname = authors[0][1][-1]
    start = None
    for i, band in enumerate(bands[:6]):
        text = " ".join(row_text(r) for r in band)
        key = {_norm_name(v) for w in re.findall(NAME_WORD, text) for v in word_variants(w.strip("-"))}
        key |= {_norm_name(w["text"]) for r in band for w in _join_small_caps([w for l in r for w in l["words"]])}
        if first_surname in key:
            start = i
            break
        if any(looks_like_name_row(row_text(r)) for r in band):
            return {"status": "absent", "detail": f"name-like row before the first author: {text!r}", "rows": []}
        band_h = _median([l["h"] for r in band for l in r], 0)
        if title_h and abs(band_h - title_h) <= 0.1 * title_h:
            return {"status": "absent", "detail": f"title-size row between title and byline: {text!r}", "rows": []}
    if start is None:
        return {"status": "absent", "detail": "first author not printed under the title", "rows": []}
    first = [r for r in bands[start] if not is_stop_row(row_text(r))] or bands[start]
    base_h = _median([l["h"] for r in first for l in r], 1.0)
    chosen = [("name", first)]
    ended = False
    stop_at = None
    for bi, band in enumerate(bands[start + 1:start + 16], start + 1):
        stop_at = bi
        texts = [row_text(r) for r in band]
        h = _median([l["h"] for r in band for l in r], 0)
        gap = min(l["y0"] for r in band for l in r) - max(l["y1"] for r in chosen[-1][1] for l in r)
        if gap > 3.5 * base_h:
            ended = True
            break
        same = abs(h - base_h) <= 0.12 * base_h
        if len(band) > 1 and any(is_stop_row(t) for t in texts) and not all(is_stop_row(t) for t in texts):
            band = [r for r, t in zip(band, texts) if not is_stop_row(t)]
            texts = [row_text(r) for r in band]
        if same and all(looks_like_name_row(t) or (not _starts_as_affiliation(t) and
                                                   looks_like_name_row(re.split(r",|\s{2,}", t)[0]))
                        for t in texts):
            chosen.append(("name", band))
        elif all(is_affiliation_row(t) for t in texts):
            chosen.append(("skip", band))
        else:
            ended = True
            break
    if not ended:
        return {"status": "absent", "detail": "byline does not end inside the searched window",
                "rows": [" | ".join(row_text(r) for r in b) for _, b in chosen]}
    # A name row further down (before the abstract or body text) means the byline
    # continues past an unrecognised row -- e.g. an affiliation without a keyword.
    for band in bands[stop_at:]:
        texts = [row_text(r) for r in band]
        if any(is_stop_row(t) for t in texts) or any(len(t.split()) > 14 for t in texts):
            break
        h = _median([l["h"] for r in band for l in r], 0)
        if abs(h - base_h) <= 0.12 * base_h and any(looks_like_name_row(t) for t in texts):
            return {"status": "absent", "detail": f"possible further byline row: {' | '.join(texts)!r}",
                    "rows": [" | ".join(row_text(r) for r in b) for k, b in chosen if k == "name"]}
    tokens = byline_tokens(chosen)
    results = [match_byline(authors, name_groups(tokens, nb)) for nb in (False, True)]
    status, detail = next((r for r in results if r[0] == "ok"), results[0])
    if status == "ok" and title_h and base_h > title_h * 1.3:
        status, detail = "absent", "byline set larger than the title; roles unclear"
    return {"status": status, "detail": detail, "page": page["page"],
            "rows": [" | ".join(row_text(r) for r in b) for k, b in chosen if k == "name"]}


COVER_MARKERS = re.compile(
    r"(?i)see discussions, stats,? and author profiles|stable url\s*:|jstor is a not-for-profit|"
    r"your use of the jstor archive|this article appeared in a journal published by elsevier|"
    r"this copy is for your personal,? non-?commercial use only|all content following this page was uploaded|"
    r"the following resources related to this article are available online|^\s*citations\s+reads\s*$")


def is_cover_page(page):
    return any(COVER_MARKERS.search(l["text"]) for l in page["lines"])


# --------------------------------------------------------------------------
# Version / identity flags
# --------------------------------------------------------------------------

NONFINAL = [
    (re.compile(r"(?i)\bbiorxiv\b|\bmedrxiv\b|\bpsyarxiv\b|\bresearch square\b"), "preprint server"),
    (re.compile(r"(?i)\barxiv\s*:\s*\d{4}\.\d{4,5}|\barxiv\s*:\s*[a-z-]+/\d{7}"), "arXiv stamp"),
    (re.compile(r"(?i)\bpreprint\b|not (?:yet )?(?:been )?(?:certified by )?peer[- ]review(?:ed)?|under review"), "preprint wording"),
    (re.compile(r"(?i)author\s*manuscript|accepted\s*manuscript|hhs public access|nih public access|"
                r"nih-pa|europe pmc funders|published in final edited form"), "author manuscript"),
    (re.compile(r"(?i)uncorrected proof|corrected proof|article in press|in press as\b|manuscript in press"), "proof / in press"),
    (re.compile(r"(?i)online first publication|advance online publication|epub ahead of print|"
                r"published online ahead of print|ahead of print"), "online-first version"),
    (re.compile(r"(?i)\bvol(?:ume)?\.?\s*0{2,}\b|\b00 month\b|\bno\.\s*\d+,\s*000\b"), "placeholder pagination (proof)"),
    (re.compile(r"(?i)\breprinted (?:from|in|with)\b|\breprint(?:ed)? by permission\b|collected (?:works|papers)"), "reprint"),
]


def version_regions(page, title_top=None):
    """Lines where publishers and servers stamp the version of a PDF."""
    W = page["width"]
    for l in page["lines"]:
        margin = l["x1"] < 0.09 * W or l["x0"] > 0.91 * W
        band = l["ry1"] <= 0.12 or l["ry0"] >= 0.88
        above_title = title_top is not None and l["y1"] <= title_top + 1
        if margin or band or above_title:
            yield l


def version_flags(pages, k0, title_top=None):
    """Preprint / manuscript / proof / reprint stamps on the article's first pages."""
    flags = []
    for idx in range(0, min(len(pages), k0 + 2)):
        page = pages[idx]
        for l in version_regions(page, title_top if idx == k0 else None):
            if REFERENCE_LIKE.search(l["text"]):
                continue
            for rx, label in NONFINAL:
                for m in rx.finditer(l["text"]):
                    flags.append({"page": page["page"], "flag": label, "text": l["text"][:160]})
    return flags


# --------------------------------------------------------------------------
# Printed page numbers
# --------------------------------------------------------------------------


def page_number_candidates(page, top=0.10, bottom=0.90):
    out = set()
    for row in band_rows(page, top=top, bottom=bottom):
        words = band_words(row)
        if not words:
            continue
        texts = [fold(w["text"]).strip("|•") for w in words]
        texts = [t for t in texts if t]
        if not texts:
            continue
        for t in (texts[0], texts[-1]):
            if re.fullmatch(r"[1-9]\d{0,5}", t):
                out.add(int(t))
    return out


def page_sequence(pages, start_index):
    """Best arithmetic sequence of printed page numbers from ``start_index``."""
    span = pages[start_index:]
    cands = [page_number_candidates(p) for p in span]
    scores = {}
    for k, cs in enumerate(cands):
        for c in cs:
            s = c - k
            if s >= 1:
                scores[s] = scores.get(s, 0) + 1
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    s, hits = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    numbered = sum(1 for cs in cands if cs)
    matched = [k for k, cs in enumerate(cands) if s + k in cs]
    if hits < 2 or hits <= second or hits < 0.5 * max(numbered, 1):
        return {"start": None, "hits": hits, "numbered": numbered, "reason": "no unique consistent sequence"}
    return {"start": s, "hits": hits, "numbered": numbered, "matched": matched,
            "last_printed": (s + len(span) - 1) if (len(span) - 1) in matched else None,
            "pages": len(span)}


def new_article_signals(page):
    """Vertical positions of signs that another article starts on ``page``
    (title-size horizontal text, or an Abstract/Summary/Keywords heading)."""
    body = page["body_h"] or 10
    out = []
    for l in page["lines"]:
        if l["rotated"]:
            continue
        t = l["text"].strip()
        if re.match(r"(?i)^(abstract|a b s t r a c t|summary|keywords?)\b", t) and l["h"] >= 0.9 * body:
            out.append(l["ry0"])
        elif l["h"] >= 1.6 * body and len(t) > 12 and not re.match(r"(?i)^(fig|table|appendix|references)", t):
            out.append(l["ry0"])
    return out


def looks_like_new_article(page):
    return bool(new_article_signals(page))


def article_may_continue_past(pages, k0):
    """True when a following article could occupy the PDF's final pages.

    Any sign on a page before the last, or high on the last page, means the
    final printed number may belong to another article.  A sign low on the last
    page is a run-on start (Science, Nature, Trends): that page is still ours.
    """
    after = pages[k0 + 1:]
    for i, p in enumerate(after):
        sig = new_article_signals(p)
        if not sig:
            continue
        if i < len(after) - 1 or min(sig) < 0.25:
            return True
    return False


# --------------------------------------------------------------------------
# Bibliographic rows
# --------------------------------------------------------------------------


def _mask(text):
    return re.sub(r"\d+", "#", alnum_key(text) if False else fold(text).lower()).strip()


def bibliographic_rows(pages, k0, cover_pages):
    """Rows allowed to supply coordinates, each with its role."""
    out = []
    # identity page bands (excluding paragraph text and reference-like lines)
    page = pages[k0]
    body = page["body_h"] or 10
    for row in band_rows(page):
        text = band_text(row)
        if REFERENCE_LIKE.search(text):
            continue
        para = any(len(l["text"]) > 70 and abs(l["h"] - body) <= 0.08 * body for l in row)
        if para:
            continue
        role = "first_page_header" if row[0]["ry1"] <= TOP_BAND else "first_page_footer"
        out.append({"page": page["page"], "role": role, "text": text})
    # multi-line masthead blocks in the bands ("Journal of Experimental Psychology:" /
    # "Learning, Memory, and Cognition" / "2010, Vol. 36, No. 2, 324-347")
    blocks = {}
    for l in page["lines"]:
        if l["ry1"] <= TOP_BAND or l["ry0"] >= BOTTOM_BAND:
            blocks.setdefault(l["block"], []).append(l)
    for group in blocks.values():
        if 1 < len(group) <= 4 and not any(len(l["text"]) > 70 and abs(l["h"] - body) <= 0.08 * body for l in group):
            text = " ".join(l["text"] for l in sorted(group, key=lambda l: l["y0"]))
            if not REFERENCE_LIKE.search(text):
                role = "first_page_header" if group[0]["ry1"] <= TOP_BAND else "first_page_footer"
                out.append({"page": page["page"], "role": role, "text": text})
    # identity-page self citation lines ("Citation: ...", "Cite as ...", "Cite this article")
    lines = page["lines"]
    for i, l in enumerate(lines):
        if re.match(r"(?i)^\s*(citation|cite (?:as|this article)|to cite this article|please cite)\s*[:.]?", l["text"]):
            text = " ".join(x["text"] for x in lines[i:i + 4] if x["block"] == l["block"])
            out.append({"page": page["page"], "role": "self_citation", "text": text})
    # running heads repeated on two or more of the article's pages
    seen = {}
    for p in pages[k0:]:
        for row in band_rows(p, top=0.10, bottom=0.92):
            text = band_text(row)
            if REFERENCE_LIKE.search(text):
                continue
            key = re.sub(r"\d+", "#", fold(text).lower())
            key = re.sub(r"^#\s*|\s*#$", "", key)
            seen.setdefault(key, []).append((p["page"], text))
    for key, occ in seen.items():
        pages_hit = {pg for pg, _ in occ}
        if len(pages_hit) >= 2 and re.search(r"[a-z]", key):
            for pg, text in occ:
                out.append({"page": pg, "role": "running_head", "text": text})
    # repository / publisher cover pages that carry this article's title
    for ci in cover_pages:
        for l in pages[ci]["lines"]:
            if re.search(r"\d", l["text"]) and not REFERENCE_LIKE.search(l["text"]):
                out.append({"page": pages[ci]["page"], "role": "cover_page", "text": l["text"]})
    return out


# --------------------------------------------------------------------------
# Decision
# --------------------------------------------------------------------------


def _field(status, **kw):
    kw["status"] = status
    return kw


def verify_entry_pdf(entry_fields, layout_pages, known_journals=()):
    """Return per-field evidence and an overall pass flag for one PDF."""
    fields = {k.lower() if k not in {"ID", "ENTRYTYPE"} else k: v for k, v in entry_fields.items()}
    etype = fields.get("ENTRYTYPE", "").lower()
    pages = layout_pages if layout_pages and "body_h" in layout_pages[0] else prepare_pages(layout_pages)
    result = {"verifier_policy": VERIFIER_POLICY, "key": fields.get("ID"), "fields": {},
              "identity": None, "version_flags": [], "pass": False}
    if not pages or not any(p["lines"] for p in pages):
        result["identity"] = {"status": "absent", "detail": "no text layer"}
        for f in CHECKED_FIELDS:
            if fields.get(f):
                result["fields"][f] = _field("absent", detail="no text layer")
        return result

    # ---------- identity
    try:
        title = _latex(fields.get("title", ""))
    except ValueError as exc:
        title = None
        result["fields"]["title"] = _field("absent", detail=f"title needs source review: {exc}")
    try:
        authors = entry_authors(fields)
    except ValueError as exc:
        authors = []
        result["fields"]["author"] = _field("absent", detail=f"author needs source review: {exc}")
    runs = find_title_runs(pages, title, byline_surname=authors[0][1][-1] if authors else None) if title else []
    chosen, byline = None, None
    for run in runs:
        if not run["complete"]:
            continue
        page = pages[run["page"] - 1]
        if is_cover_page(page):
            continue
        by = find_byline(page, run, authors)
        if chosen is None or (by["status"] == "ok" and byline["status"] != "ok"):
            chosen, byline = run, by
        if by["status"] == "ok":
            break
    if title is not None:
        if chosen is not None and byline is not None and byline["status"] == "ok":
            result["fields"]["title"] = _field(
                "supported", region="title_block", page=chosen["page"],
                span=" / ".join(l["text"] for l in chosen["lines"]))
        elif chosen is not None:
            result["fields"]["title"] = _field(
                "absent", region="title_block", page=chosen["page"],
                detail="cited title printed, but not as the heading directly above this byline",
                span=" / ".join(l["text"] for l in chosen["lines"]))
        elif runs:
            result["fields"]["title"] = _field(
                "contradicted", region="title_block", page=runs[0]["page"],
                detail="printed heading continues beyond the cited title",
                span=" / ".join(l["text"] for l in runs[0]["lines"]))
        else:
            result["fields"]["title"] = _field("absent", detail="cited title not printed as a heading run")
    if "author" not in result["fields"]:
        if byline is None:
            result["fields"]["author"] = _field("absent", detail="no title run to anchor the byline")
        else:
            status = {"ok": "supported"}.get(byline["status"], byline["status"])
            result["fields"]["author"] = _field(status, region="byline", page=byline.get("page"),
                                                span=" / ".join(byline["rows"]), detail=byline["detail"])
    identity_ok = chosen is not None and byline is not None and byline["status"] == "ok"
    k0 = (chosen["page"] - 1) if chosen else 0
    result["identity"] = {"status": "supported" if identity_ok else "absent", "page": k0 + 1}

    # ---------- version
    flags = version_flags(pages, k0, chosen["lines"][0]["y0"] if chosen else None)
    result["version_flags"] = flags
    if flags:
        result["identity"]["version"] = "not the published version: " + ", ".join(sorted({f["flag"] for f in flags}))
    else:
        result["identity"]["version"] = "no preprint/manuscript/reprint markers"

    # ---------- bibliographic rows and parsed coordinates
    cover_pages = []   # repository covers carry scraped metadata, never evidence
    rows = bibliographic_rows(pages, k0, cover_pages)
    journal = fields.get("journal")
    observations = []
    journal_hits = []
    for row in rows:
        hit = journal_in_text(journal, row["text"], known_journals) if journal else None
        if hit:
            journal_hits.append(dict(row, match=hit[0], matched=hit[1]))
        offset = journal_offset(journal, row["text"], known_journals) if (journal and hit) else None
        labeled = bool(re.search(r"(?i)\bvol(?:ume)?\.?\s*\d", row["text"]))
        if not (hit or labeled or row["role"] in {"self_citation"}):
            continue
        for v in parse_citation_text(row["text"], offset):
            observations.append(dict(v, page=row["page"], role=row["role"], span=row["text"],
                                     journal_named=bool(hit)))
    # masthead: lines above the title on the identity page
    if chosen is not None and journal:
        top_y = chosen["lines"][0]["y0"]
        for l in pages[k0]["lines"]:
            if l["y1"] <= top_y + 1 and l not in chosen["lines"]:
                hit = journal_in_text(journal, l["text"], known_journals)
                if hit:
                    journal_hits.append({"page": k0 + 1, "role": "masthead", "text": l["text"],
                                         "match": hit[0], "matched": hit[1]})
    result["observations"] = observations

    # ---------- journal
    if journal:
        full = [h for h in journal_hits if h["match"] == "full"]
        abbr = [h for h in journal_hits if h["match"] in {"abbreviation", "acronym"}]
        if full:
            h = full[0]
            result["fields"]["journal"] = _field("supported", region=h["role"], page=h["page"], span=h["text"])
        elif abbr:
            h = abbr[0]
            result["fields"]["journal"] = _field("supported", region=f"{h['role']} ({h['match']})",
                                                 page=h["page"], span=h["text"])
        else:
            result["fields"]["journal"] = _field("absent", detail="journal name not printed in a bibliographic region")

    def decide(name, entry_value, obs_field, norm):
        vals = [o for o in observations if o["field"] == obs_field]
        if not vals:
            return _field("absent", detail=f"no bibliographic {name} printed")
        distinct = {norm(o["value"]) for o in vals}
        want = norm(entry_value)
        if distinct == {want}:
            o = vals[0]
            return _field("supported", region=o["role"], page=o["page"], span=o["span"], template=o["template"])
        other = [o for o in vals if norm(o["value"]) != want]
        o = other[0]
        return _field("contradicted", region=o["role"], page=o["page"], span=o["span"],
                      printed=o["value"], template=o["template"])

    if fields.get("volume"):
        result["fields"]["volume"] = decide("volume", fields["volume"], "volume", normalize_number)
    if fields.get("number"):
        result["fields"]["number"] = decide("issue", fields["number"], "number", normalize_issue)
    if fields.get("year"):
        result["fields"]["year"] = decide("year", fields["year"], "year", lambda v: str(v).strip())

    # ---------- pages
    if fields.get("pages"):
        result["fields"]["pages"] = decide_pages(fields["pages"], observations, pages, k0, chosen is not None)

    # ---------- doi
    if fields.get("doi"):
        result["fields"]["doi"] = decide_doi(fields["doi"], pages, k0, cover_pages)

    # ---------- anything else the entry cites
    unchecked = [f for f in fields if f not in CHECKED_FIELDS and f not in IGNORED_FIELDS
                 and f not in POLICY_DROPPED.get(etype, set())]
    result["unchecked_fields"] = unchecked
    result["policy_dropped_fields"] = [f for f in fields if f in POLICY_DROPPED.get(etype, set())]
    result["pass"] = bool(
        etype == "article" and identity_ok and not flags and not unchecked
        and all(result["fields"].get(f, {}).get("status") == "supported" for f in CHECKED_FIELDS if fields.get(f))
    )
    return result


def decide_pages(value, observations, pages, k0, anchored):
    """Pages from the citation line and/or the article's own printed page numbers.

    The first page must be printed *for this article*: in a citation line, or
    as the page number printed on the identity page itself (never inferred
    from later pages, which would be off by one behind an unrecognised cover).
    The last page must be printed in a citation line, or on the final PDF page
    of an unbroken sequence with no sign of a following article.
    """
    cited = parse_entry_pages(value)
    if cited["first"] is None:
        return _field("absent", detail=f"unparsed page value {value!r}")
    want_first, want_last = normalize_number(cited["first"]), normalize_number(cited["last"])
    seq = page_sequence(pages, k0) if anchored else None
    seq_start = seq.get("start") if seq else None
    firsts = [o for o in observations if o["field"] == "first"]
    lasts = [o for o in observations if o["field"] == "last"]
    first_only = [o for o in observations if o["field"] == "first_only"]
    artnos = [o for o in observations if o["field"] == "artno"]
    # Elsevier-style "NeuroImage 215 (2020) 116461" with pages printed 1..n is an article number
    if seq_start == 1:
        for o in first_only:
            if len(o["value"]) >= 5:
                artnos.append(dict(o, field="artno"))
        first_only = [o for o in first_only if len(o["value"]) < 5]
    if artnos:
        values = {normalize_number(o["value"]) for o in artnos}
        if len(values) == 1 and want_first == want_last and want_first in values:
            o = artnos[0]
            return _field("supported", region=o["role"], page=o["page"], span=o["span"], template="article_number")
        return _field("contradicted", detail=f"PDF prints article number(s) {sorted(values)}; cited {value!r}",
                      region=artnos[0]["role"], span=artnos[0]["span"])
    first_vals = {normalize_number(o["value"]) for o in firsts + first_only}
    last_vals = {normalize_number(o["value"]) for o in lasts}
    if len(first_vals) > 1 or len(last_vals) > 1:
        bad = want_first not in first_vals or (last_vals and want_last not in last_vals)
        return _field("contradicted" if bad else "absent",
                      detail=f"conflicting printed ranges: first {sorted(first_vals)} last {sorted(last_vals)}")
    printed_first = next(iter(first_vals), None)
    printed_last = next(iter(last_vals), None)
    # the identity page must print its own number for the sequence to anchor the first page
    seq_first = str(seq_start) if seq_start and 0 in seq.get("matched", []) else None
    seq_last = None
    if seq_start and seq.get("last_printed") and not article_may_continue_past(pages, k0):
        seq_last = str(seq["last_printed"])
    if printed_first and seq_first and printed_first != seq_first:
        return _field("absent", detail=f"citation line first page {printed_first} vs printed page number {seq_first}")
    first_known = printed_first or seq_first
    if first_known is None:
        return _field("absent", detail="no first page printed for this article",
                      sequence={k: v for k, v in (seq or {}).items() if k != "matched"})
    span_first = (firsts or first_only)[0]["span"] if printed_first else f"page number printed on PDF page {k0 + 1}"
    region_first = (firsts or first_only)[0]["role"] if printed_first else "page_number"
    if want_first != first_known:
        return _field("contradicted", detail=f"printed first page {first_known}", printed=first_known,
                      region=region_first, span=span_first)
    if printed_last and seq_last and printed_last != seq_last:
        seq_last = None          # PDF lacks or appends pages; the printed range decides
    last_known = printed_last or seq_last
    if last_known is None:
        return _field("absent", detail="no last page printed for this article",
                      sequence={k: v for k, v in (seq or {}).items() if k != "matched"})
    if want_last != last_known:
        return _field("contradicted", detail=f"printed last page {last_known}", printed=last_known,
                      region="citation_line" if printed_last else "page_number")
    if printed_first and printed_last:
        o = firsts[0]
        return _field("supported", region=o["role"], page=o["page"], span=o["span"], template=o["template"])
    return _field("supported", region=f"{region_first} + page_numbers",
                  span=f"{span_first}; last page {last_known} printed on PDF page {len(pages)}")


DOI_RX = re.compile(r"(?i)\b(10\.\d{4,9}/[^\s\"<>]+)")


def decide_doi(value, pages, k0, cover_pages):
    want = re.sub(r"(?i)^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip()).lower().rstrip(".")
    found = []
    for idx in [k0] + list(cover_pages):
        page = pages[idx]
        for l in page["lines"]:
            # the article's own DOI line: header/footer band or the front matter above
            # the abstract, never a reference or body sentence that cites another DOI
            if REFERENCE_LIKE.search(l["text"]) or not (l["ry1"] <= 0.35 or l["ry0"] >= 0.88):
                continue
            if not re.search(r"(?i)\bdoi\b|doi\.org", l["text"]):
                continue
            for m in DOI_RX.finditer(fold(l["text"]).replace(" ", "")):
                found.append((page["page"], m[1].lower().rstrip(".,;"), l["text"]))
    if not found:
        return _field("absent", detail="no DOI printed on the first page")
    for pg, doi, text in found:
        if doi == want:
            return _field("supported", region="doi_line", page=pg, span=text)
    return _field("contradicted", detail=f"printed DOI(s) {[d for _, d, _ in found]}")


def verify_pdf_path(entry_fields, pdf_path, cache_dir, known_journals=()):
    layout = cached_layout(pdf_path, cache_dir)
    out = verify_entry_pdf(entry_fields, layout["pages"], known_journals)
    out["pdf_sha256"] = layout["pdf_sha256"]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("key")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--bibliography", type=Path, default=Path("cdl.bib"))
    parser.add_argument("--cache", type=Path, default=Path(".bibcheck/pdf-benchmark/layout"))
    args = parser.parse_args()
    from .verification import load_entries
    entries = load_entries(args.bibliography)
    known = {e["fields"].get("journal") for e in entries.values() if e["fields"].get("journal")}
    out = verify_pdf_path(entries[args.key]["fields"], args.pdf, args.cache, known)
    out.pop("observations", None)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
