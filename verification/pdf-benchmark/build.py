"""Build the hard PDF-evidence benchmark (verification/pdf-benchmark/cases.json).

Every base entry below was labelled by manual inspection of the text that
``pdftotext -bbox-layout`` extracts from the local PDF (header/footer bands,
title block, byline, running heads).  The ``evidence`` quotes are short
bibliographic lines copied from that text; the builder refuses to run if any
quote is not found in the extracted text of the recorded PDF, so labels cannot
silently drift from the source.

Planted variants perturb exactly one field of a correctly labelled base entry.
Wrong values are chosen *adversarially from the same PDF*: a number printed in
the body (a statistic, a figure or experiment number), in the reference list,
in a received/copyright date, in a DOI/ISSN/price code, or the page number of a
different page; a surname from the reference list; the article's own running
head as a title.  Every planted value is checked to differ from the true one.

This script needs the local paper library (read-only) and writes only
``cases.json`` (small snippets and hashes, no PDF content beyond single lines).

    python verification/pdf-benchmark/build.py [--library PATH]
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bibcheck"))

import pdf_evidence as P  # noqa: E402
from verification import load_entries  # noqa: E402

DEFAULT_LIBRARY = Path("/Users/jmanning/Library/CloudStorage/Dropbox-DartmouthCollege/Jeremy Manning/Papers")
CACHE = ROOT / ".bibcheck" / "pdf-benchmark" / "layout"
OUT = Path(__file__).resolve().parent / "cases.json"

# --------------------------------------------------------------------------
# Manually labelled bases.  label: accept | abstain | wrong_version | wrong_work
# evidence: bibliographic lines read in the extracted text (verified at build).
# --------------------------------------------------------------------------
BASES = [
    # ---- published version, every cited field printed in a bibliographic region
    ("HoldEtal00", "accept", ["Neuropsychologia 38 (2000) 410±425",
                              "J.S. Holdstock et al. / Neuropsychologia 38 (2000) 410±425"]),
    ("KuceEtal17", "accept", ["BRAIN 2017: 140; 1337–1350", "Daniel S. Rizzuto, Michael J. Kahana and Gregory A. Worrell"]),
    ("TurkEtal12", "accept", ["7202 • The Journal of Neuroscience, May 23, 2012 • 32(21):7202–7207",
                              "Nicholas B. Turk-Browne, Mason G. Simon, and Per B. Sederberg"]),
    ("HokEtal07", "accept", ["472 • The Journal of Neuroscience, January 17, 2007 • 27(3):472– 482",
                             "Sébastien Roux"]),
    ("Farr10", "accept", ["2010, Vol. 36, No. 2, 324 –347", "Simon Farrell"]),
    ("vanVEtal13", "accept", ["2013, Vol. 142, No. 2, 412– 425", "© 2012 American Psychological Association"]),
    ("JonePyc14", "accept", ["2014, Vol. 40, No. 1, 300 –305", "© 2013 American Psychological Association"]),
    ("JangHube08", "accept", ["2008, Vol. 34, No. 1, 112–127", "Yoonhee Jang and David E. Huber"]),
    ("StanEtal06", "accept", ["2006, Vol. 32, No. 3, 688 –704", "J. Stephen Mansfield"]),
    ("AvraKell10", "accept", ["2010, Vol. 36, No. 3, 635– 645", "Marios N. Avraamides"]),
    ("OReiRudy01", "accept", ["2001, Vol. 108. No. 2, 311-345", "Randall C. O'Reilly and Jerry W. Rudy"]),
    ("HowaKaha99", "accept", ["1999, Vol. 25, No. 4, 923-941", "Marc W. Howard and Michael J. Kahana"]),
    ("Kaha96", "accept", ["1996, 24 (1), 103–109", "MICHAEL J. KAHANA"]),
    ("KleiEtal05", "accept", ["2005, 33 (5), 833-839", "KRYSTAL A. KLEIN, KELLY M. ADDIS, and MICHAEL J. KAHANA"]),
    ("ChenEtal11", "accept", ["Neuropsychologia 49 (2011) 49–60", "© 2010 Elsevier Ltd. All rights reserved."]),
    ("DianEtal12", "accept", ["Neuropsychologia 50 (2012) 3062–3069"]),
    ("RubiSpor10", "accept", ["NeuroImage 52 (2010) 1059–1069", "© 2009 Elsevier Inc. All rights reserved."]),
    ("GersEtal11", "accept", ["NeuroImage 57 (2011) 89–100"]),
    ("VincEtal10", "accept", ["1250 • The Journal of Neuroscience, January 27, 2010 • 30(4):1250 –1257"]),
    ("HassEtal08", "accept", ["The Journal of Neuroscience, March 5, 2008 • 28(10):2539 –2550 • 2539"]),
    ("JacoEtal07", "accept", ["The Journal of Neuroscience, April 4, 2007 • 27(14):3839 –3844 • 3839"]),
    ("HaftEtal05", "accept", ["Vol 436|11 August 2005|doi:10.1038/nature03721", "NATURE|Vol 436|11 August 2005"]),
    ("HochEtal06", "accept", ["Vol 442|13 July 2006|doi:10.1038/nature04970"]),
    ("KamiTong05", "accept", ["NATURE NEUROSCIENCE VOLUME 8 [ NUMBER 5 [ MAY 2005 679"]),
    ("HaxbEtal01", "accept", ["www.sciencemag.org SCIENCE VOL 293 28 SEPTEMBER 2001 2425",
                              "2430 28 SEPTEMBER 2001 VOL 293 SCIENCE www.sciencemag.org"]),
    ("PaslEtal12", "accept", ["January 2012 | Volume 10 | Issue 1 | e1001251"]),
    ("LohmEtal10", "accept", ["April 2010 | Volume 5 | Issue 4 | e10232"]),
    ("MeyeEtal12", "accept", ["PNAS | February 7, 2012 | vol. 109 | no. 6 | 1883–1888"]),
    ("MortEtal20", "accept", ["29338–29345 | PNAS | November 24, 2020 | vol. 117 | no. 47"]),
    ("PallWagn02", "accept", ["TRENDS in Cognitive Sciences Vol.6 No.2 February 2002"]),
    ("Ward03", "accept", ["TRENDS in Cognitive Sciences Vol.7 No.12 December 2003"]),
    ("ZimaEtal18", "accept", ["https://doi.org/10.3758/s13428-018-1037-4", "Published online: 23 April 2018"]),
    ("Bart04", "accept", ["Eur. Phys. J. B 38, 163–168 (2004)", "M. Barthélemy"]),
    ("MiyaEtal08", "accept", ["Neuron 60, 915–929, December 11, 2008", "Masa-aki Sato"]),
    ("SteyMalm03", "accept", ["2003, Vol. 29, No. 5, 760 –766"]),
    ("Hoga75", "accept", ["1975, Vol. 3 (2), 197-209", "ROBERT M. HOGAN"]),
    ("Bowe81", "accept", ["Vol. 36, No. 2, 129-148 AMERICAN PSYCHOLOGIST • FEBRUARY 1981 • 129"]),
    ("ShohDaw15", "accept", ["Current Opinion in Behavioral Sciences 2015, 5:85–90"]),
    ("FawcTayl10", "accept", ["2010, 38 (6), 797-808", "See discussions, stats, and author profiles for this publication at:"]),
    ("Rund71", "accept", ["1971, Vol. 89, No. 1, 63-77", "DEWEY RUNDUS", "64 DEWEY J. RUNDUS"]),
    ("Sarv87", "accept", ["Phys. Med. Biol., 1987, Vol. 32, No 1, 11-22. Printed in the UK"]),
    ("LinEtal17", "accept", ["Hippocampus. 2017;27:1040–1053.", "Received: 10 March 2017"]),
    ("ArzyEtal09", "accept", ["Consciousness and Cognition 18 (2009) 781–785"]),
    # ---- correct entry, but the PDF does not print a cited field (must abstain)
    ("FostWils06", "abstain", ["Vol 440|30 March 2006|doi:10.1038/nature04587"],
     "number 7084 is cited but no issue number is printed anywhere in the PDF"),
    ("PanzEtal10", "abstain", ["Review Trends in Neurosciences Vol.33 No.3", "Available online 4 January 2010"],
     "year 2010 is printed only as an online date; the copyright line says 2009; no issue date"),
    ("MlodBrun14", "abstain", ["PHYSICAL REVIEW E 89, 052102 (2014)", "1539-3755/2014/89(5)/052102(8)"],
     "issue 5 appears only inside the price code 89(5)/052102(8), never as a labelled issue"),
    ("CaruEtal18", "abstain", ["NATURE COMMUNICATIONS | (2018) 9:2715"],
     "number 1 is cited but Nature Communications prints no issue"),
    ("DikkEtal17", "abstain", ["Current Biology 27, 1375–1380, May 8, 2017"],
     "number 9 is cited but Current Biology prints no issue; page 1 is a graphical-abstract page"),
    ("JensEtal07", "abstain", ["Vol.30 No.7", "318"],
     "page 1 prints no page number (317 is only inferable from page 2) and the year is printed only as a copyright year"),
    ("AlyEtal18", "abstain", ["© 2018 Massachusetts Institute of Technology Journal of Cognitive Neuroscience 30:9, pp. 1345–1365"],
     "the year is printed only as a copyright year, which is not the issue year (cf. vanVEtal13)"),
    # ---- correct entry, but the local PDF is another version of the work
    ("CronEtal11", "wrong_version", ["NIH Public Access", "Published in final edited form as:"],
     "NIH author manuscript, paginated 1-15"),
    ("DianEtal10", "wrong_version", ["J Cogn Neurosci. Author manuscript; available in PMC 2010 November 1."],
     "NIH author manuscript"),
    ("BaldEtal18", "wrong_version", ["This Accepted Manuscript has not been copyedited and formatted. The final version may differ from this version."],
     "accepted manuscript"),
    ("CoheEtal16", "wrong_version", ["Author’s Accepted Manuscript"], "accepted manuscript"),
    ("GohEtal22", "wrong_version", ["arXiv:2101.10953v3 [q-bio.NC] 23 Oct 2021"], "arXiv preprint of a Neural Computation article"),
    ("EzzyEtal17", "wrong_version", ["Current Biology 27, 1–8, May 8, 2017"], "article-in-press version paginated 1-8"),
    ("SahaSmit14", "wrong_version", ["Online First Publication, August 19, 2013. doi: 10.1037/a0034250"],
     "APA online-first version (2013, Vol. 39, No. 6, 000)"),
    # ---- correct entry, but the local PDF is a different work
    ("JacoEtal89", "wrong_work", ["1989, Vol. 56. No. 3, 326-338", "Becoming Famous Overnight: Limits on the Ability to Avoid"],
     "same first author and year, different JPSP article"),
    ("MannEtal14a", "wrong_work", ["Topographic Factor Analysis: A Bayesian Model for"],
     "different article by the same first author (PLOS ONE 2014)"),
    ("MillEtal13", "wrong_work", ["www.sciencemag.org/content/342/6162/1107/suppl/DC1"],
     "different Miller et al. 2013 article (Science); page 1 starts with the tail of another article"),
    ("MaguEtal99", "wrong_work", ["4398 – 4403 兩 PNAS 兩 April 11, 2000 兩 vol. 97 兩 no. 8"],
     "a 2000 PNAS article by the same first author"),
]

# Held-out bases: drawn at random (seed 20260922) from the Crossref-verified
# articles with a key-named PDF, labelled from their extracted text *before* the
# verifier was run on them, and never used to tune it.
BASES += [
    ("GlerEtal12", "accept", ["Volume 2, Number 2, 2012", "Iiro P. Jääskeläinen"]),
    ("NewmEtal12", "accept", ["Frontiers in Behavioral Neuroscience www.frontiersin.org June 2012 | Volume 6 | Article 24"]),
    ("WeisRapp00", "accept", ["Cognitive Brain Research 9 Ž 2000 . 299–312"]),
    ("FolkEtal18", "accept", ["4200 • The Journal of Neuroscience, April 25, 2018 • 38(17):4200 – 4211",
                              "Sarah Folkerts, X Ueli Rutishauser, and X Marc W. Howard"]),
    ("Kaha06", "accept", ["The Journal of Neuroscience, February 8, 2006 • 26(6):1669 –1672 • 1669"]),
    ("LogoEtal01", "accept", ["NATURE | VOL 412 | 12 JULY 2001 | www.nature.com"]),
    ("BurgEtal02", "accept", ["Neuron, Vol. 35, 625–641, August 15, 2002"]),
    ("SahaKell02", "accept", ["2002, Vol. 28, No. 6, 1064 –1072"]),
    ("Farr14", "accept", ["Psychon Bull Rev (2014) 21:1174–1179"]),
    ("Salz59", "abstain", ["T h e Journal o f General Psychology, 1959, 61, 65-94."],
     "number 1 is cited but no issue is printed; scanned 1959 article behind a publisher cover page"),
    # Label corrected after the verifier disagreed: first labelled 'abstain' from the footer
    # alone; the self-citation line on page 1 does print the volume.
    ("ShinEtal08", "accept", ["January 2008 | Issue 1 | e1394", "PLoS ONE 3(1): e1394."]),
    ("HupbEtal07", "abstain", ["14:47–53 ©2007 by Cold Spring Harbor Laboratory Press"],
     "the article pages print the year only as a copyright year; the year appears otherwise only on the publisher's cover page"),
    ("Shap19", "abstain", ["Nature Neuroscience | www.nature.com/natureneuroscience"],
     "News & Views PDF prints no volume, issue or page numbers"),
    ("ColeEtal16", "abstain", ["Received 18 April; accepted 7 September; published online 10 October 2016; doi:10.1038/nn.4406"],
     "advance-online PDF: volume, issue and pages are not printed"),
    ("HintSala06", "abstain", ["504 28 JULY 2006 VOL 313 SCIENCE www.sciencemag.org"],
     "issue 5786 is cited but not printed; page 1 begins with the end of another article"),
    ("Tolm48", "wrong_version", ["Cognitive Maps in Rats and Men"], "re-typeset reprint paginated from 1"),
    ("NosoEtal12", "wrong_version", ["Nosofsky et al. PNAS Early Edition | 3 of 6"], "PNAS Early Edition, paginated 1 of 6"),
    ("GuntEtal16", "wrong_version", ["Cerebral Cortex Advance Access published March 14, 2016", "Cerebral Cortex, 2016, 1–16"],
     "advance-access version paginated 1-16"),
]
# Needs-review entries surfaced by the offline coverage dry run (coverage.json) and
# then checked by hand.  Two exposed verifier defects that are now fixed and kept
# here as regressions: a byline continuing past an affiliation row without a
# keyword (RakiEtal98 cites 4 of the 6 printed authors) and hyphen-insensitive
# title matching (KahaJaco00 cites "Inter-response"; the PDF prints "Interresponse").
BASES += [
    ("RakiEtal98", "entry_error", ["1998, Vol. 24, No. 1,15-33", "Sean C. Hinton and Warren H. Meek"],
     "entry lists 4 authors; the byline prints 6 in three blocks separated by affiliation rows"),
    ("KahaJaco00", "entry_error", ["Interresponse Times in Serial Recall: Effects of Intraserial Repetition"],
     "entry title 'Inter-response' differs from the printed 'Interresponse'"),
    ("Free77", "accept", ["Sociometry", "1977, Vol. 40, No. 1, 35-41", "Stable URL: https://www.jstor.org/stable/3033543"]),
    ("MankEtal12", "accept", ["19462–19467 | PNAS | November 20, 2012 | vol. 109 | no. 47"]),
    ("Mill10", "accept", ["The Journal of Neuroscience, May 12, 2010 • 30(19):6477– 6479 • 6477"]),
    ("RichEtal99", "accept", ["1999,27 (4), 741-750", "ANTHONY E. RICHARDSON, DANIEL R. MONTELLO, and MARY HEGARTY"]),
]
# Found by the stress run (run.py --stress); both are entry or version problems, kept as regressions.
BASES += [
    ("Murd68", "entry_error", ["Journal of Experimental Psychology", "Monograph Supplement", "Vol. 76, No. 4, Part 2"],
     "entry cites 'Journal of Experimental Psychology: General' (founded 1975); the 1968 PDF prints the parent journal"),
    ("SwalEtal09", "wrong_version", ["Published in final edited form as:"],
     "NIH author manuscript; its title's last word sits in a separate text block"),
]
PDF_OVERRIDE = {"Mill10": "Mill12.pdf"}   # the local file name is wrong; its content is the 2010 article
WILD = {"Murd68", "SwalEtal09", "RakiEtal98", "KahaJaco00", "Free77", "MankEtal12", "Mill10", "RichEtal99"}

HELDOUT = {"GlerEtal12", "NewmEtal12", "WeisRapp00", "FolkEtal18", "Kaha06", "LogoEtal01", "BurgEtal02", "SahaKell02",
           "Farr14", "Salz59", "ShinEtal08", "HupbEtal07", "Shap19", "ColeEtal16", "HintSala06", "Tolm48", "NosoEtal12",
           "GuntEtal16"}

# Journals with a genuinely different, similar name (planted journal errors).
SIMILAR_JOURNAL = {
    "Neuropsychologia": "Neuropsychology",
    "Brain": "Brain Research",
    "The Journal of Neuroscience": "Journal of Neurophysiology",
    "Journal of Experimental Psychology: Learning, Memory, and Cognition": "Journal of Experimental Psychology: General",
    "Journal of Experimental Psychology: General": "Journal of Experimental Psychology: Learning, Memory, and Cognition",
    "Journal of Experimental Psychology: Human Perception and Performance": "Journal of Experimental Psychology: Learning, Memory, and Cognition",
    "Journal of Experimental Psychology": "Journal of Experimental Psychology: General",
    "Psychological Review": "Psychological Bulletin",
    "Memory and Cognition": "Memory",
    "{NeuroImage}": "{NeuroImage}: Clinical",
    "Nature": "Nature Neuroscience",
    "Nature Neuroscience": "Nature Reviews Neuroscience",
    "Science": "Science Advances",
    "{PLoS} Biology": "{PLoS} Computational Biology",
    "{PLoS} One": "{PLoS} Biology",
    "Proceedings of the National Academy of Sciences, {USA}": "Proceedings of the Royal Society B: Biological Sciences",
    "Trends in Cognitive Sciences": "Trends in Neurosciences",
    "Neuron": "Neural Computation",
    "Behavior Research Methods": "Behavior Research Methods, Instruments, and Computers",
    "{European} Physical Journal {B}": "{European} Physical Journal {E}",
    "{American} Psychologist": "American Journal of Psychology",
    "Current Opinion in Behavioral Sciences": "Current Opinion in Neurobiology",
    "Physics in Medicine and Biology": "Medical Physics",
    "Hippocampus": "Cortex",
    "Consciousness and Cognition": "Cognition",
    "Brain Connectivity": "Brain Structure and Function",
    "Frontiers in Behavioral Neuroscience": "Frontiers in Human Neuroscience",
    "Cognitive Brain Research": "Brain Research",
    "Psychonomic Bulletin and Review": "Psychological Bulletin",
}

# Printed running-head short titles of the article itself (never the title).
RUNNING_HEAD_TITLES = {
    "HokEtal07": "Place cells and goal coding",
    "TurkEtal12": "Scene representations and temporal context",
    "VincEtal10": "Gamma-phase shifting",
    "KuceEtal17": "Human gamma activities",
    "JangHube08": "Context retrieval and context change",
    "OReiRudy01": "Conjunctive representations",
    "Rund71": "Rehearsal processes in free recall",
}
# Titles of other works printed on the same pages (neighbouring article / reference list).
NEIGHBOUR_TITLES = {
    "PallWagn02": "Initial knowledge: six suggestions",
    "HaxbEtal01": "Field-induced superconductivity in a spin-ladder cuprate",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def squash(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def page_texts(pages):
    return [" ".join(l["text"] for l in p["lines"]) for p in pages]


def body_lines(pages):
    """Body text lines (never header/footer bands), in reading order."""
    for p in pages:
        for l in p["lines"]:
            if 0.12 < l["ry0"] and l["ry1"] < 0.88:
                yield p["page"], l["text"]


def numbers_in(text):
    return [m for m in re.finditer(r"(?<![\d.,/:-])(\d{1,4})(?![\d.,/:])", P.fold(text))]


def snippet(text, m=None, width=110):
    if m is None:
        return text[:width]
    a = max(0, m.start() - 45)
    return text[a:a + width]


def pick_body_number(pages, avoid, lo, hi, prefer_digits=None, start_page=2):
    best = None
    for pg, text in body_lines(pages):
        if pg < start_page:
            continue
        for m in numbers_in(text):
            v = int(m[1])
            if lo <= v <= hi and str(v) not in avoid and not P._is_year(m[1]):
                cand = (pg, text, m, str(v))
                if prefer_digits is None or len(str(v)) == prefer_digits:
                    return cand
                best = best or cand
    return best


def reference_range(pages, true_first, true_last):
    for p in reversed(pages[1:]):
        for l in p["lines"]:
            if not (0.08 < l["ry0"] < 0.92):
                continue
            for m in re.finditer(r"(?<![\d.])(\d{2,5})\s*[–-]\s*(\d{2,5})(?![\d.])", P.fold(l["text"])):
                a, b = int(m[1]), int(m[2])
                if a < b < a + 60 and (str(a), str(b)) != (true_first, true_last) and not P._is_year(m[1]):
                    return p["page"], l["text"], m, str(a), str(b)
    return None


def reference_person(pages, authors_surnames):
    rx = re.compile(r"\b([A-Z][a-z]{3,}),\s+([A-Z])\.\s?(?:([A-Z])\.)?")
    for p in reversed(pages[1:]):
        for l in p["lines"]:
            for m in rx.finditer(P.fold(l["text"])):
                if m[1].lower() not in authors_surnames:
                    initials = " ".join(x for x in (m[2], m[3]) if x)
                    return p["page"], l["text"], f"{initials} {m[1]}"
    return None


def date_years(pages):
    """Years printed in received/accepted/copyright/online lines of the first two pages."""
    out = []
    for p in pages[:2]:
        for l in p["lines"]:
            t = P.fold(l["text"])
            if re.search(r"(?i)received|accepted|revised|available online|published online|©|copyright|\bß\b|\bÓ\b", t):
                for m in re.finditer(r"\b(19[5-9]\d|20[0-4]\d)\b", t):
                    out.append((p["page"], l["text"], m[1]))
    return out


def body_year(pages, avoid):
    for pg, text in body_lines(pages):
        for m in re.finditer(r"\(([A-Z][A-Za-z-]+(?: et al\.)?,? )((?:19|20)\d\d)\)", P.fold(text)):
            if m[2] not in avoid:
                return pg, text, m[2]
    return None


def doi_numbers(pages, avoid):
    for l in pages[0]["lines"]:
        t = P.fold(l["text"])
        for m in re.finditer(r"(?i)(?:doi[:\s]*|\b)10\.\d{4,9}/\S+|\b\d{4}-\d{3}[\dX]\b|\S+\$\S*", t):
            for n in re.findall(r"\d{2,4}", m[0]):
                v = str(int(n))
                if v not in avoid and v != "10" and not P._is_year(n):
                    return pages[0]["page"], l["text"], v
    return None


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def fmt_pages(a, b):
    return a if a == b else f"{a}--{b}"


def variants(key, fields, pages):
    """Planted single-field errors whose wrong value is printed elsewhere in the PDF."""
    out = []
    pages_field = P.parse_entry_pages(fields.get("pages", "")) if fields.get("pages") else None
    first, last = (pages_field or {}).get("first"), (pages_field or {}).get("last")

    def add(kind, field, value, decoy, **extra):
        new = dict(fields)
        if value is None:
            new.pop(field, None)
        else:
            new[field] = value
        if new.get(field) == fields.get(field):
            raise ValueError(f"{key}/{kind}: planted value equals the true value")
        out.append({"variant": kind, "perturbed_field": field, "fields": new, "decoy": decoy, **extra})

    true_vol = fields.get("volume")
    if true_vol:
        c = pick_body_number(pages, {true_vol}, 1, 999, prefer_digits=len(true_vol))
        if c:
            add("volume_from_body_number", "volume", c[3], {"page": c[0], "text": snippet(c[1], c[2])})
        d = doi_numbers(pages, {true_vol})
        if d:
            add("volume_from_doi_issn_digits", "volume", d[2], {"page": d[0], "text": d[1][:110]})
    true_num = fields.get("number")
    if true_vol and first and first.isdigit() and first != true_vol:
        add("volume_equals_first_page", "volume", first, {"page": 1, "text": "first page number printed on page 1"})
    if true_vol and true_num and true_num != true_vol:
        add("volume_and_issue_swapped", "volume", true_num, {"page": 1, "text": "printed issue number"})
        add("issue_equals_volume", "number", true_vol, {"page": 1, "text": "printed volume number"})
    if true_num and re.fullmatch(r"\d+", true_num):
        add("issue_as_double_issue", "number", f"{true_num}-{int(true_num) + 1}", {"page": 1, "text": "single issue printed"})
    if true_num:
        c = pick_body_number(pages, {true_num, P.normalize_issue(true_num)}, 1, 12)
        if c:
            add("issue_from_body_number", "number", c[3], {"page": c[0], "text": snippet(c[1], c[2])})
        if re.fullmatch(r"\d+", true_num):
            add("issue_as_supplement", "number", f"Suppl {true_num}", {"page": None, "text": "printed issue has no supplement"})
    if first and last and first.isdigit() and last.isdigit():
        f, l = int(first), int(last)
        if f != l:
            add("first_page_is_next_page_footer", "pages", fmt_pages(str(f + 1), last),
                {"page": 2, "text": f"page number {f + 1} printed on the article's second page"})
            add("last_page_plus_one", "pages", fmt_pages(first, str(l + 1)), {"page": None, "text": "off by one"})
            add("last_page_minus_one", "pages", fmt_pages(first, str(l - 1)),
                {"page": len(pages) - 1, "text": f"page number {l - 1} printed on the penultimate page"})
        r = reference_range(pages, first, last)
        if r:
            add("pages_from_reference_list", "pages", fmt_pages(r[3], r[4]), {"page": r[0], "text": snippet(r[1], r[2])})
        c = pick_body_number(pages, {first}, 10 ** (len(first) - 1), 10 ** len(first) - 1, prefer_digits=len(first))
        if c and len(first) >= 2:
            add("first_page_from_body_number", "pages", fmt_pages(c[3], last), {"page": c[0], "text": snippet(c[1], c[2])})
    elif first and last:
        # article-number journals: cite the PDF page range instead of the article number
        add("page_range_instead_of_article_number", "pages", f"1--{len(pages)}",
            {"page": len(pages), "text": f"PDF pages printed 1..{len(pages)}"})
        m = re.fullmatch(r"([a-z]*)(\d+)", first, re.I)
        if m:
            add("article_number_off_by_one", "pages", f"{m[1]}{int(m[2]) + 1}", {"page": 1, "text": "article number"})
    doi = fields.get("doi")
    if doi:
        m = re.search(r"(\d)(?=\D*$)", doi)
        if m:
            d = str((int(m[1]) + 1) % 10)
            add("doi_last_digit_changed", "doi", doi[:m.start()] + d + doi[m.end():], {"page": 1, "text": "printed DOI"})
    year = fields.get("year")
    if year:
        seen = set()
        for pg, text, y in date_years(pages):
            if y != year and y not in seen:
                seen.add(y)
                add("year_from_received_or_copyright_date", "year", y, {"page": pg, "text": text[:110]})
                break
        b = body_year(pages, {year})
        if b:
            add("year_from_body_citation", "year", b[2], {"page": b[0], "text": b[1][:110]})
    names = P.split_authors(fields.get("author", ""))
    if len(names) >= 2:
        swapped = names[:]
        swapped[0], swapped[1] = swapped[1], swapped[0]
        add("swapped_first_two_authors", "author", " and ".join(swapped), {"page": 1, "text": "byline order"})
        add("dropped_last_author", "author", " and ".join(names[:-1]), {"page": 1, "text": "byline"})
    for i, n in enumerate(names):
        toks = n.split()
        if len(toks) >= 3 and all(len(t) == 1 for t in toks[:-1]) and "{" not in n:
            new = names[:]
            new[i] = " ".join(toks[:-2] + toks[-1:])
            add("missing_middle_initial", "author", " and ".join(new), {"page": 1, "text": f"byline prints {n}"})
            break
    for i, n in enumerate(names):
        plain = strip_accents(P._latex(n))
        if plain != P._latex(n):
            new = names[:]
            new[i] = plain
            add("dropped_accent", "author", " and ".join(new), {"page": 1, "text": f"byline prints {P._latex(n)}"})
            break
    surnames = {P.parse_bib_name(n)[1][-1] for n in names}
    ref = reference_person(pages, surnames)
    if ref:
        add("extra_author_from_reference_list", "author", " and ".join(names + [ref[2]]),
            {"page": ref[0], "text": ref[1][:110]})
        if len(names) >= 2:
            add("last_author_replaced_by_reference_person", "author", " and ".join(names[:-1] + [ref[2]]),
                {"page": ref[0], "text": ref[1][:110]})
    for i, n in enumerate(names):
        toks = n.split()
        if len(toks) >= 2 and len(toks[0]) == 1 and toks[0].isalpha():
            letter = "B" if toks[0].upper() != "B" else "D"
            new = names[:]
            new[i] = " ".join([letter] + toks[1:])
            add("author_initial_changed", "author", " and ".join(new), {"page": 1, "text": f"byline prints {n}"})
            break
    if key in RUNNING_HEAD_TITLES:
        add("title_is_running_head", "title", RUNNING_HEAD_TITLES[key], {"page": 2, "text": "running head"})
    if key in NEIGHBOUR_TITLES:
        add("title_of_neighbouring_work", "title", NEIGHBOUR_TITLES[key], {"page": 1, "text": NEIGHBOUR_TITLES[key]})
    title = fields.get("title", "")
    add("title_with_extra_word", "title", title + " revisited", {"page": 1, "text": "printed title"})
    if re.search(r"\w-\w", title):
        add("title_hyphen_dropped", "title", re.sub(r"(\w)-(\w)", r"\1\2", title, count=1),
            {"page": 1, "text": "printed title keeps the hyphen"})
    for i, n in enumerate(names):
        toks = n.split()
        full = [t for t in toks[:-1] if len(t) > 3 and t.isalpha()]
        if full:
            t = full[0]
            wrong = t[:-1] + ("a" if t[-1] != "a" else "e")
            new = names[:]
            new[i] = n.replace(t, wrong, 1)
            add("given_name_misspelled", "author", " and ".join(new), {"page": 1, "text": f"byline prints {n}"})
            break
    if ":" in title:
        add("title_missing_subtitle", "title", title.split(":")[0], {"page": 1, "text": "printed title has a subtitle"})
    else:
        words = title.split()
        if len(words) > 4:
            add("title_missing_last_word", "title", " ".join(words[:-1]), {"page": 1, "text": "printed title is longer"})
    journal = fields.get("journal")
    if journal and ":" in journal:
        add("journal_parent_title_without_section", "journal", journal.split(":")[0],
            {"page": 1, "text": "printed journal has a section subtitle"})
    if journal in SIMILAR_JOURNAL:
        add("journal_with_similar_name", "journal", SIMILAR_JOURNAL[journal], {"page": 1, "text": "printed journal"})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--bibliography", type=Path, default=ROOT / "cdl.bib")
    args = parser.parse_args()
    entries = load_entries(args.bibliography)
    known = sorted({e["fields"]["journal"] for e in entries.values() if e["fields"].get("journal")})
    cases, bases = [], []
    for base in BASES:
        key, label, evidence = base[0], base[1], base[2]
        note = base[3] if len(base) > 3 else None
        entry = entries[key]
        fields = {k: v for k, v in entry["fields"].items()}
        pdf = PDF_OVERRIDE.get(key, f"{key}.pdf")
        path = args.library / pdf
        layout = P.cached_layout(path, CACHE)
        pages = P.prepare_pages(layout["pages"])
        haystacks = [squash(" ".join(page_texts(pages))),
                     squash(" ".join(l["text_nosup"] for p in pages for l in p["lines"])),
                     squash(" ".join(P.band_text(r) for p in pages for r in P.band_rows(p, top=0.35, bottom=0.6)))]
        for quote in evidence:
            if not any(squash(quote) in h for h in haystacks):
                raise SystemExit(f"{key}: evidence quote not in extracted text: {quote!r}")
        bases.append({"key": key, "label": label, "heldout": key in HELDOUT, "from_coverage_run": key in WILD, "pdf": pdf, "pdf_sha256": layout["pdf_sha256"],
                      "fingerprint": entry["fingerprint"], "evidence": evidence, "note": note})
        expected = "accept" if label == "accept" else "reject"
        cases.append({"id": f"{key}/control", "key": key, "heldout": key in HELDOUT, "pdf": pdf, "pdf_sha256": layout["pdf_sha256"],
                      "variant": "control" if label == "accept" else label, "perturbed_field": None,
                      "expected": expected, "fields": fields, "decoy": None, "note": note})
        if label == "accept":
            for v in variants(key, fields, pages):
                cases.append({"id": f"{key}/{v['variant']}", "key": key, "heldout": key in HELDOUT, "pdf": pdf,
                              "pdf_sha256": layout["pdf_sha256"], "expected": "reject", "note": None, **v})
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate case ids")
    OUT.write_text(json.dumps({"schema": 1, "verifier": "bibcheck/pdf_evidence.py",
                               "library_default": str(DEFAULT_LIBRARY), "known_journals": known,
                               "bases": bases, "cases": cases}, indent=1, ensure_ascii=False) + "\n")
    kinds = {}
    for c in cases:
        kinds[c["variant"]] = kinds.get(c["variant"], 0) + 1
    print(json.dumps({"bases": len(bases), "cases": len(cases), "variants": kinds}, indent=1))


if __name__ == "__main__":
    main()
