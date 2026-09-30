"""Surname scan (user rule 2026-09-30, CONFIRM.md answer 5): compare every author surname
of each verified or held entry with the surnames of the source records saved for it in a
baseline snapshot. No network request; cdl.bib is only read.

    python verification/apply-2026-09-30-surnames/scan.py SNAPSHOT [OUT.json]

Records compared per entry (every status; the row records the entry's status):

* registry records saved for the entry's accepted DOI (its ``doi`` field when nothing was
  accepted): Crossref, PubMed via Europe PMC, PMC JATS front matter, the publisher's page
  head, a catalogue imprint (``record.author``);
* the accepted route candidate (``accepted_source``, matched by DOI or record id): the
  structured byline in its evidence (``evidence.author.source``), or its record;
* research evidence (``research-evidence`` candidates): every quote cited for the author
  field. A cited surname counts as stated when all its words occur in the quotes; one
  that does not is listed (class ``not-in-quote``) with the quotes.

Normalization before comparing (the checker's typography rules): LaTeX accents and braces
resolved (``verification.normalized``), accents folded, case folded. Then each difference
is classed:

* ``order``: the cited surname is printed at another position of the source's byline and
  not at this one (an order difference, not a spelling; listed, not asked about);
* ``punctuation``: equal once punctuation and spaces are dropped too ("St. Jacques");
* ``transliteration``: equal once umlauts etc. are written out ("Klosterkoetter");
* ``garbled-source``: the source surname has an unreadable character (U+FFFD, "?", an HTML
  entity, a spacing accent);
* ``name-split``: one surname's words contain the other's (particles, a second surname, a
  given name or suffix inside the family field: "Feldman Barrett", "Kai Li", "Roediger, III"),
  or the source's family field holds the cited given name (given/family swapped);
* ``spelling``: anything else.
"""
from collections import Counter
import gzip
import html
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))
from bibtexparser.customization import splitname  # noqa: E402
from verification import ACCEPTED, load_entries, normalized, split_authors  # noqa: E402

REGISTRY = {"crossref", "europepmc", "pmc-jats", "publisher-head", "catalogue-imprint"}
LABEL = {"crossref": "Crossref", "europepmc": "PubMed via Europe PMC", "pmc-jats": "PMC full-text front matter",
         "publisher-head": "publisher page", "catalogue-imprint": "catalogue imprint",
         "loc-catalogue": "Library of Congress catalogue", "arxiv-repository": "arXiv",
         "osf-repository": "PsyArXiv (OSF)", "datacite-registry": "DataCite", "acl-anthology": "ACL Anthology",
         "biorxiv-preprint": "bioRxiv"}
# Hosts whose quotes are registry or catalogue metadata, not the printed work.
METADATA_HOSTS = {"api.crossref.org", "eutils.ncbi.nlm.nih.gov", "www.ebi.ac.uk", "pubmed.ncbi.nlm.nih.gov",
                  "api.datacite.org", "lx2.loc.gov", "lccn.loc.gov", "export.arxiv.org", "api.openalex.org",
                  "api.semanticscholar.org", "doi.org", "dx.doi.org", "europepmc.org", "zenodo.org",
                  "www.worldcat.org", "search.worldcat.org", "catalog.hathitrust.org", "openlibrary.org"}
# Citation exports and metadata endpoints on publisher hosts (RIS, REST records).
EXPORT = re.compile(r"/rest/|/citation/|format=refman|citation-needed\.|[?&]format=(?:json|xml)", re.I)
GARBLED = re.compile(r"[�?&´˜¨`]")


def latex_letters(value):
    """Two LaTeX forms the checker's own parsers mishandle, as Unicode: a tilde accent
    outside braces (``Pi\\~{n}a``; BibTeX name splitting reads ``~`` as a space) and
    ``\\aa`` (``verification.normalized`` rejects it as an unknown command)."""
    value = re.sub(r"\\~\{?([A-Za-z])\}?", lambda m: unicodedata.normalize("NFC", m[1] + "\u0303"), value)
    return re.sub(r"\{?\\(aa|AA)\}?", lambda m: "å" if m[1] == "aa" else "Å", value)


def fold(value):
    text = html.unescape(latex_letters(str(value or "")))
    try:
        text = normalized(text)
    except ValueError:
        pass
    text = unicodedata.normalize("NFKD", text.replace("{", "").replace("}", ""))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold().strip()


def words(value):
    return re.findall(r"[a-z]+", fold(value))


def decode_quote(quote):
    """A quote as text: JSON \\u escapes and HTML entities resolved."""
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), quote)
    return html.unescape(text.replace('\\"', '"'))


def cited_names(value):
    """[(position, full name, given, surname)]; corporate names and 'others' skipped."""
    out = []
    for i, name in enumerate(split_authors(value or ""), 1):
        if not name or fold(name) == "others":
            continue
        try:
            parts = splitname(latex_letters(name), strict_mode=True)
        except (ValueError, TypeError):
            continue
        surname = " ".join(parts["von"] + parts["last"])
        if not surname or (name.startswith("{") and name.endswith("}") and not parts["first"]):
            continue  # a corporate author
        out.append((i, name, " ".join(parts["first"]), surname))
    return out


TRANSLITERATION = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "å": "aa", "ø": "oe", "æ": "ae"}


def transliterated(value):
    text = html.unescape(latex_letters(str(value or "")))
    try:
        text = normalized(text)
    except ValueError:
        pass
    text = unicodedata.normalize("NFC", text.replace("{", "").replace("}", "")).casefold()
    return "".join(TRANSLITERATION.get(c, c) for c in text)


def classify(cited, cited_given, source, source_given, source_families):
    cw, sw = set(words(cited)), set(words(source))
    if cw and not (sw and (cw <= sw or sw <= cw)) and any(cw <= set(words(f)) for f in source_families):
        return "order"
    if GARBLED.search(source):
        return "garbled-source"
    if "".join(words(cited)) == "".join(words(source)):
        return "punctuation"
    if re.sub(r"[^a-z]", "", transliterated(cited)) == re.sub(r"[^a-z]", "", transliterated(source)):
        return "transliteration"
    if cw and sw and (cw <= sw or sw <= cw):
        return "name-split"
    if (sw and sw <= set(words(cited_given))) or (cw and cw <= set(words(source_given))):
        return "name-split"  # given and family swapped
    return "spelling"


def people_of(value):
    if not isinstance(value, list):
        return None
    out = []
    for p in value:
        if isinstance(p, dict) and (p.get("family") is not None or p.get("familyName") is not None):
            out.append({"family": p.get("family") if p.get("family") is not None else p.get("familyName") or "",
                        "given": p.get("given") if p.get("given") is not None else p.get("givenName") or ""})
        else:
            out.append(None)  # an organization
    return out


def source_quote(label, person):
    if label == "Crossref":
        return f'"given":"{person["given"]}","family":"{person["family"]}"'
    return f'{person["given"]} {person["family"]}'.strip()


def research_quotes(cand, field="author"):
    spec = (cand.get("fields") or {}).get(field) or {}
    return [{"url": e.get("url") or "", "quote": decode_quote(e["quote"])}
            for e in spec.get("evidence") or [] if e.get("quote")]


def printed(quotes, *surnames):
    """Quotes from the printed work (not registry/catalogue metadata) that print any of
    the given surnames' words."""
    out = []
    for q in quotes:
        host = urlparse(q["url"]).netloc.lower()
        if not host or host in METADATA_HOSTS or host.startswith("api.") or EXPORT.search(q["url"]):
            continue  # registry, catalogue or index metadata, or a citation export, not the printed work
        qw = set(words(q["quote"]))
        if any(words(s) and set(words(s)) <= qw for s in surnames if s):
            out.append(q)
    return out


def scan(snapshot):
    with gzip.open(snapshot, "rt") as f:
        records = {r["key"]: r for r in map(json.loads, f) if "key" in r}
    entries = load_entries(ROOT / "cdl.bib")
    rows, compared = [], Counter()
    for key, entry in entries.items():
        r = records.get(key)
        if not r or r.get("fingerprint") != entry["fingerprint"]:
            continue
        fields = entry["fields"]
        value = fields.get("author")
        if not value:
            continue
        names = cited_names(value)
        byline = [n for n in split_authors(value) if fold(n) != "others"]
        doi = (r.get("accepted_doi") or fields.get("doi") or "").lower()
        compared[r["status"]] += 1
        quotes = [q for c in r.get("candidates") or [] if c.get("source") == "research-evidence"
                  for q in research_quotes(c)]
        for cand in r.get("candidates") or []:
            src = cand.get("source")
            cdoi = (cand.get("doi") or "").lower()
            record = cand.get("record") or {}
            accepted_route = r["status"] in ACCEPTED and src == r.get("accepted_source") and (
                (cdoi and cdoi == doi) or (cand.get("record_id") and cand.get("record_id") == r.get("accepted_record_id"))
                or (not cdoi and not cand.get("record_id")))
            if src == "research-evidence":
                if not quotes:
                    continue
                joined = " ".join(q["quote"] for q in research_quotes(cand))
                text, run = set(words(joined)), "".join(words(joined))
                for pos, name, given, cited in names:
                    if words(cited) and not (set(words(cited)) <= text or "".join(words(cited)) in run):
                        rows.append({"key": key, "status": r["status"], "accepted_source": r.get("accepted_source"),
                                     "position": pos, "cited_name": name, "entry_spelling": cited,
                                     "source_spelling": None, "source": "research-evidence",
                                     "url": (research_quotes(cand) or [{}])[0].get("url"),
                                     "source_quote": "", "class": "not-in-quote",
                                     "quotes": research_quotes(cand)})
                continue
            if src in REGISTRY and doi and cdoi == doi:
                people = people_of(record.get("author"))
            elif accepted_route:
                ev = ((cand.get("evidence") or {}).get("author") or {}).get("source")
                people = people_of(ev) if isinstance(ev, list) and ev and isinstance(ev[0], dict) else \
                    people_of(record.get("author"))
            else:
                continue
            if people is None or len(people) != len(byline):
                continue
            label = LABEL.get(src, src)
            url = f"https://api.crossref.org/works/{cdoi}" if src == "crossref" and cdoi else \
                (cand.get("url") or cand.get("record_id") or "")
            for pos, name, given, cited in names:
                person = people[pos - 1]
                if person is None or fold(cited) == fold(person["family"]):
                    continue
                rows.append({"key": key, "status": r["status"], "accepted_source": r.get("accepted_source"),
                             "position": pos, "cited_name": name, "entry_spelling": cited,
                             "source_spelling": person["family"], "source": label, "url": url,
                             "source_quote": source_quote(label, person),
                             "class": classify(cited, given, person["family"], person["given"],
                                               [p["family"] for i, p in enumerate(people, 1) if p and i != pos]),
                             "quotes": printed(quotes, cited, person["family"])})
    # One row per (key, position, source spelling); every source that prints it is kept.
    merged = {}
    for row in rows:
        k = (row["key"], row["position"], fold(row["source_spelling"] or ""), row["class"] == "not-in-quote")
        if k in merged:
            m = merged[k]
            if row["source"] not in m["sources"]:
                m["sources"].append(row["source"])
                m["urls"].append(row["url"])
                m["source_quotes"].append(row["source_quote"])
        else:
            merged[k] = dict(row, sources=[row["source"]], urls=[row["url"]], source_quotes=[row["source_quote"]])
    return list(merged.values()), compared


if __name__ == "__main__":
    out, compared = scan(sys.argv[1])
    print(json.dumps({"compared": dict(compared), "rows": len(out),
                      "by_class": dict(Counter(r["class"] for r in out)),
                      "keys": len({r["key"] for r in out})}))
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
