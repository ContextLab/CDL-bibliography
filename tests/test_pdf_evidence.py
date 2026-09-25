"""Tests for bibcheck/pdf_evidence.py.

Unit tests use short bibliographic lines copied verbatim from real PDFs in the
local paper library (no synthetic layouts, no mocks).  Integration tests run
the verifier on the real PDFs and the hard benchmark; they need the local
library and are skipped, with the reason stated, where it is not mounted.
"""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
sys.path.insert(0, str(ROOT / "verification" / "pdf-benchmark"))

import pdf_evidence as P  # noqa: E402

LIBRARY = Path(json.loads((ROOT / "verification" / "pdf-benchmark" / "cases.json").read_text())["library_default"])
CACHE = ROOT / ".bibcheck" / "pdf-benchmark" / "layout"
needs_library = pytest.mark.skipif(not LIBRARY.is_dir(), reason=f"local paper library not mounted at {LIBRARY}")


def values(text, journal_offset=None):
    return {(o["field"], o["value"]) for o in P.parse_citation_text(text, journal_offset)}


# ---------------------------------------------------------------- citation lines

@pytest.mark.parametrize("line, expected", [
    ("Neuropsychologia 38 (2000) 410±425", {("volume", "38"), ("year", "2000"), ("first", "410"), ("last", "425")}),
    ("2013, Vol. 142, No. 2, 412– 425", {("volume", "142"), ("number", "2"), ("first", "412"), ("last", "425"), ("year", "2013")}),
    ("7202 • The Journal of Neuroscience, May 23, 2012 • 32(21):7202–7207",
     {("volume", "32"), ("number", "21"), ("first", "7202"), ("last", "7207"), ("year", "2012")}),
    ("BRAIN 2017: 140; 1337–1350", {("year", "2017"), ("volume", "140"), ("first", "1337"), ("last", "1350")}),
    ("NATURE COMMUNICATIONS | (2018) 9:2715 | DOI: 10.1038/s41467-018-05121-8 | www.nature.com/naturecommunications 1",
     {("year", "2018"), ("volume", "9"), ("artno", "2715")}),
    ("Behavior Research Methods (2018) 50:2 597 –2 605", {("year", "2018"), ("volume", "50"), ("first", "2597"), ("last", "2605")}),
    ("Cognitive Brain Research 9 Ž 2000 . 299–312", {("volume", "9"), ("year", "2000"), ("first", "299"), ("last", "312")}),
    ("Volume 2, Number 2, 2012", {("volume", "2"), ("number", "2"), ("year", "2012")}),
    ("January 2012 | Volume 10 | Issue 1 | e1001251", {("volume", "10"), ("number", "1"), ("artno", "e1001251"), ("year", "2012")}),
])
def test_real_citation_lines(line, expected):
    assert expected <= values(line)


def test_page_number_before_volume_is_not_a_year():
    # Nature Neuroscience footer: 1664 is the page, not the year.
    got = values("1664 VOLUME 18 | NUMBER 11 | NOVEMBER 2015 NATURE NEUROSCIENCE")
    assert ("year", "1664") not in got and ("year", "2015") in got
    assert values("www.sciencemag.org SCIENCE VOL 342 1864") == {("volume", "342")}


def test_ocr_damaged_volume_is_not_truncated():
    # 'Vol. 1M' (OCR of 104) must not be read as volume 1.
    assert not any(f == "volume" for f, _ in values("1997. Vol. 1M. No. 2, 211-240 0033-295X/97/J3.00"))


def test_codes_dates_and_copyright_never_supply_values():
    sici = "doi:10.1002/(SICI)1097-0193(200006)10:2<74::AID-HBM30>3.0.CO;2-2"
    assert values(sici) == set()
    price = "Copyright © 2012 the authors 0270-6474/12/327202-06$15.00/0"
    assert values(price) == set()
    received = "Received September 8, 2016. Revised December 29, 2016. Accepted January 9, 2017."
    assert values(received) == set()
    assert values("© 2012 American Psychological Association") == set()


def test_psychonomic_year_is_not_a_volume():
    t = "Memory & Cognition 2009, 37 (4), 464-476"
    offset = P.journal_offset("Memory and Cognition", t, ())
    got = values(t, offset)
    assert ("volume", "37") in got and ("volume", "2009") not in got and ("volume", "009") not in got


# ---------------------------------------------------------------- journals

def test_journal_names_are_bounded():
    line = "© 2018 Massachusetts Institute of Technology Journal of Cognitive Neuroscience 30:9, pp. 1345–1365"
    assert P.journal_in_text("Journal of Cognitive Neuroscience", line)[0] == "full"
    assert P.journal_in_text("Cognitive Neuroscience", line) is None
    assert P.journal_in_text("Cognition", "Cognition and Emotion 2010, 24 (3), 1-10") is None
    assert P.journal_in_text("Journal of Experimental Psychology",
                             "Journal of Experimental Psychology: General 2013, Vol. 142") is None
    assert P.journal_in_text("Science", "1464 17 JUNE 2016 • VOL 352 ISSUE 6292 sciencemag.org SCIENCE")[0] == "full"
    assert P.journal_in_text("Trends in Neurosciences", "Review Trends in Neurosciences Vol.33 No.3")[0] == "full"
    assert P.journal_in_text("Nature", "NATURE NEUROSCIENCE VOLUME 8 [ NUMBER 5 [ MAY 2005 679") is None


def test_letter_spaced_masthead_and_abbreviations():
    assert P.journal_in_text("Psychological Science", "PS YC HOLOGICA L SC IENCE")[0] == "full"
    hit = P.journal_in_text("Psychonomic Bulletin and Review", "Psychon Bull Rev (2014) 21:1174–1179",
                            ["Psychonomic Bulletin and Review", "Psychological Bulletin"])
    assert hit and hit[0] == "abbreviation"
    # A different journal whose name shares the prefix never matches the abbreviation.
    assert P.journal_in_text("Journal of Neurophysiology", "J. Neurosci., January 27, 2010 • 30(4):1250 –1257") is None
    acr = P.journal_in_text("Proceedings of the National Academy of Sciences, {USA}",
                            "PNAS | February 7, 2012 | vol. 109 | no. 6 | 1883–1888")
    assert acr and acr[0] == "acronym"


# ---------------------------------------------------------------- names

def test_entry_name_parsing():
    assert P.parse_bib_name("M K {van Vugt}") == (["m", "k"], ["van", "vugt"], None)
    assert P.parse_bib_name(r"M Barth\'{e}lemy") == (["m"], ["barthélemy"], None)
    assert P.parse_bib_name("Jean-Philippe Lachaux") == (["jean-philippe"], ["lachaux"], None)


def test_given_names_and_accents():
    assert P._given_token_ok("m", "Masa-aki") == "ok"
    assert P._given_token_ok("j-p", "Jean-Philippe") == "ok"
    assert P._given_token_ok("jean", "J.") == "initial_only"
    assert P._given_token_ok("m", "Robert") == "mismatch"
    # accents extracted as spacing marks are re-attached, never dropped
    assert "buzsáki" in {v.lower() for v in P.word_variants("Buzs´aki")}
    assert "buzsaki" not in {v.lower() for v in P.word_variants("Buzs´aki")}


def test_byline_groups_split_degrees_and_markers():
    tokens = [("name", "Nathan"), ("name", "E."), ("name", "Crone"), ("sep", ","), ("sep", "degree"), ("sep", ","),
              ("name", "Anna"), ("name", "Korzeniewska"), ("row_end", "")]
    assert P.name_groups(tokens, False) == [["Nathan", "E.", "Crone"], ["Anna", "Korzeniewska"]]
    authors = [P.parse_bib_name("N E Crone"), P.parse_bib_name("A Korzeniewska")]
    assert P.match_byline(authors, P.name_groups(tokens, False))[0] == "ok"
    # order, missing middle initial, and a dropped author are contradictions
    assert P.match_byline(authors[::-1], P.name_groups(tokens, False))[0] == "contradicted"
    assert P.match_byline([P.parse_bib_name("N Crone"), authors[1]], P.name_groups(tokens, False))[0] == "contradicted"
    assert P.match_byline(authors[:1], P.name_groups(tokens, False))[0] in {"contradicted", "absent"}


def test_pages_and_issue_normalisation():
    assert P.parse_entry_pages("410--425") == {"raw": "410-425", "first": "410", "last": "425"}
    assert P.normalize_issue("Suppl 1") == P.normalize_issue("Suppl. 1") == "suppl 1"
    assert P.normalize_issue("S1") == "suppl 1" and P.normalize_issue("1") == "1"


# ---------------------------------------------------------------- real PDFs

def _frozen(key):
    """Entry fields as frozen in the benchmark, so later cdl.bib edits (for example an
    added DOI) do not change what these tests check; live fields for keys not frozen."""
    cases = json.loads((ROOT / "verification/pdf-benchmark/cases.json").read_text())["cases"]
    for case in cases:
        if case["key"] == key and case.get("variant") == "control":
            return dict(case["fields"])
    from verification import load_entries
    return dict(load_entries(ROOT / "cdl.bib")[key]["fields"])


def _verify(key, fields=None):
    fields = fields or _frozen(key)
    return P.verify_pdf_path(fields, LIBRARY / f"{key}.pdf", CACHE)


@needs_library
def test_layout_cache_is_content_addressed_and_outside_library(tmp_path):
    record = P.cached_layout(LIBRARY / "HoldEtal00.pdf", tmp_path)
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and files[0].name.startswith(record["pdf_sha256"])
    assert P.cached_layout(LIBRARY / "HoldEtal00.pdf", tmp_path) == record
    assert record["pages"][0]["lines"]


@needs_library
def test_published_elsevier_article_passes_with_roles():
    r = _verify("HoldEtal00")
    assert r["pass"], r["fields"]
    assert r["fields"]["title"]["region"] == "title_block"
    assert r["fields"]["author"]["region"] == "byline"
    assert r["fields"]["volume"]["region"] == "first_page_header"
    assert "410" in r["fields"]["pages"]["span"]


@needs_library
def test_off_by_one_and_decoy_pages_are_contradicted():
    fields = _frozen("HoldEtal00")
    for wrong in ("410--426", "410--424", "411--425"):
        r = _verify("HoldEtal00", dict(fields, pages=wrong))
        assert not r["pass"] and r["fields"]["pages"]["status"] == "contradicted"


@needs_library
def test_cover_page_is_never_the_identity_page():
    r = _verify("FawcTayl10")          # ResearchGate cover, article starts on PDF page 2
    assert r["pass"] and r["identity"]["page"] == 2


@needs_library
def test_preprint_and_manuscript_versions_never_pass():
    for key in ("GohEtal22", "CronEtal11", "SahaSmit14", "EzzyEtal17"):
        r = _verify(key)
        assert not r["pass"]
        assert r["version_flags"] or r["fields"]["pages"]["status"] != "supported"


@needs_library
def test_unprinted_issue_abstains():
    r = _verify("FostWils06")          # Nature prints no issue number
    assert not r["pass"] and r["fields"]["number"]["status"] == "absent"
    assert r["fields"]["pages"]["status"] == "supported"


@needs_library
def test_rotated_margin_stamp_is_not_a_new_article():
    r = _verify("KamiTong05")
    assert r["pass"], r["fields"]


@needs_library
def test_byline_continuing_past_unrecognised_affiliation_is_not_accepted():
    # RakiEtal98 cites 4 of 6 printed authors; the 5th and 6th sit below an affiliation
    # row with no affiliation keyword ("Hopital de la Salpetriere, INSERM U289").
    r = _verify("RakiEtal98")
    assert not r["pass"] and r["fields"]["author"]["status"] != "supported"


@needs_library
def test_title_missing_word_in_separate_block_is_not_supported():
    fields = _frozen("SwalEtal09")
    fields["title"] = "Event boundaries in perception affect memory encoding and"
    r = _verify("SwalEtal09", fields)
    assert r["fields"]["title"]["status"] != "supported"


@needs_library
def test_hyphenated_title_is_not_the_unhyphenated_print():
    # The citation as it stood on 2026-09-22 (since corrected to the printed form).
    cited = {"ENTRYTYPE": "article", "ID": "KahaJaco00", "author": "M J Kahana and J Jacobs",
             "journal": "Journal of Experimental Psychology: Learning, Memory, and Cognition",
             "pages": "1188--1197", "volume": "26", "year": "2000",
             "title": "Inter-response times in serial recall: effects of intraserial repetition"}
    r = _verify("KahaJaco00", cited)   # cites "Inter-response"; PDF prints "Interresponse"
    assert not r["pass"] and r["fields"]["title"]["status"] != "supported"


@needs_library
def test_hard_benchmark_has_zero_false_accepts():
    import run
    rows = run.run_benchmark(LIBRARY)
    tally, per = run.summarize(rows)
    assert tally.get("false_accept", 0) == 0
    assert tally.get("field_false_support", 0) == 0
    assert tally["true_reject"] == sum(r["expected"] == "reject" for r in rows)
    assert tally["true_accept"] >= 55
    for variant in ("volume_from_body_number", "first_page_is_next_page_footer", "last_page_plus_one",
                    "year_from_received_or_copyright_date", "missing_middle_initial", "extra_author_from_reference_list",
                    "journal_with_similar_name", "title_is_running_head", "wrong_version", "wrong_work", "abstain"):
        assert per[variant]["true_reject"] > 0 and per[variant]["false_accept"] == 0
