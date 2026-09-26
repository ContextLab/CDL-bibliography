"""Tests for verification/research-2026-09-25/postcheck.py.

Real wave-1 researcher rows, the committed cdl.bib, and live (disk-cached)
doi.org / Crossref responses; no mocks. Each rule has a positive case from the
independent wave-1 review and a negative control.
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WAVE = ROOT / "verification/research-2026-09-25/wave1"
spec = importlib.util.spec_from_file_location("postcheck", ROOT / "verification/research-2026-09-25/postcheck.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


def rows():
    out = {}
    for batch in sorted(WAVE.glob("batch-*.json")):
        for row in json.loads(batch.read_text()):
            out[row["key"]] = row
    return out


ROWS = rows()
REVIEW = {r["key"]: r for r in json.loads((WAVE / "review.json").read_text())}
VALIDATION = {e["key"]: e for e in json.loads((WAVE / "validation.json").read_text())["report"]}


@pytest.fixture(scope="module")
def bib():
    return pc.load_bib("HEAD")


def ctx_for(bib):
    return {"doi": pc.doi_record, "cities": pc.city_states(bib), "taken": set(), "reserved": pc.renamed_away(),
            "index": pc.work_index(bib)}


def check(bib, key, row=None, review=False):
    row = row or ROWS[key]
    return pc.check_entry(row, bib.get(key), bib, ctx_for(bib),
                          review=REVIEW.get(key) if review else None,
                          validation=VALIDATION.get(key))


def codes(rec):
    return {f["code"] for f in rec["flags"]}


def changed(rec):
    return {c["field"]: c["proposed"] for c in rec["changes"]}


# ---------------------------------------------------------------- DOIs

def test_taylor_francis_url_path_doi_is_unregistered():
    rec = pc.doi_record("10.4324/9780203837672-11")
    assert rec["registered"] is False


def test_registered_doi_has_crossref_title():
    rec = pc.doi_record("10.1038/361031a0")
    assert rec["registered"] is True and rec["ra"] == "Crossref"
    assert pc.titles_match(rec["title"], "A synaptic model of memory: long-term potentiation in the hippocampus")


def test_unregistered_doi_change_is_dropped(bib):
    for key in ("KleiEtal07b", "WardEtal09", "PetzHaub04", "Este91", "GoebLewa91"):
        rec = check(bib, key)
        assert "doi_unregistered" in codes(rec), key
        assert "doi" not in changed(rec), key


def test_registered_matching_doi_is_kept(bib):
    rec = check(bib, "BlisColl93")
    assert changed(rec)["doi"] == "10.1038/361031a0"
    assert not codes(rec) & {"doi_unregistered", "doi_title_mismatch", "doi_check_failed"}


def test_doi_of_another_work_is_dropped(bib):
    row = copy.deepcopy(ROWS["BlisColl93"])
    row["fields"]["doi"]["value"] = "10.1016/j.cub.2008.03.054"  # the Goense & Logothetis paper
    rec = check(bib, "BlisColl93", row)
    assert "doi_title_mismatch" in codes(rec)
    assert "doi" not in changed(rec)


def test_doi_record_pages_conflict_is_flagged(bib):
    rec = check(bib, "Jell02")  # PubMed 347-376 vs Crossref chapter 347-384
    assert any(f["code"] == "doi_record_conflict" and f["field"] == "pages" for f in rec["flags"])


# ---------------------------------------------------------------- keys

def test_rename_onto_existing_same_work_is_duplicate(bib):
    assert check(bib, "GoenEtal08")["key_plan"]["merge_into"] == "GoenLogo08"
    assert check(bib, "DawKenj06")["key_plan"]["merge_into"] == "DawDoya06"


def test_rename_onto_different_work_is_collision_with_suffix(bib):
    plan = check(bib, "Frie06")["key_plan"]
    assert plan["action"] == "collision" and "Frie08" in plan["existing"]
    assert plan["new_key"] == "Frie08b" and plan["also_rename"] == {"Frie08": "Frie08a"}


def test_author_change_renames_key(bib):
    plan = check(bib, "Nati24b")["key_plan"]
    assert plan["action"] == "rename" and plan["new_key"] == "Schn24"


def test_key_kept_when_metadata_still_fits(bib):
    for key in ("BlisColl93", "GoldEtal05", "ChenEtal22"):
        assert check(bib, key)["key_plan"]["action"] == "keep", key


# ---------------------------------------------------------------- patents

def test_patent_year_from_filing_or_priority_is_held(bib):
    for key, grant in (("LittEtal98", "2003"), ("EchaEtal00", "2004")):
        rec = check(bib, key)
        assert "patent_filing_year" in codes(rec), key
        assert "year" not in changed(rec)
        assert rec["suggestions"].get("year") == grant, key


def test_non_patent_has_no_patent_flags(bib):
    rec = check(bib, "BlisColl93")
    assert not {c for c in codes(rec) if c.startswith("patent")}


# ---------------------------------------------------------------- names

@pytest.mark.parametrize("given,expected", [
    ("H {Daum\\'{e} III}", "H {Daum\\'{e}}"),
    ("Engel, Jr., Jerome", "J Engel"),
    ("J {Engel Jr}", "J Engel"),
    ("Jean-Pierre Michel", "J-P Michel"),
    ("T. V. P. Bliss", "T V P Bliss"),
    ("de Marneffe, Marie-Catherine", "M-C {de Marneffe}"),
])
def test_house_name_form(given, expected):
    assert pc.normalise_names(given)[0] == expected


def test_house_names_unchanged_list():
    assert pc.normalise_names("{Food and Drug Administration}")[0] == "{Food and Drug Administration}"
    assert pc.split_names("A B Smith and {Food and Drug Administration}") == ["A B Smith", "{Food and Drug Administration}"]


def test_capitalised_source_names_are_not_initials(bib):
    rec = check(bib, "WardEtal09")  # T&F prints GEOFF WARD, LYDIA TAN, PARVEEN BHATARAH
    assert rec["final_entry"]["author"] == "G Ward and L Tan and P Bhatarah"


def test_formatter_never_lowercases_inner_capitals():
    assert pc.guarded("O'Reilly", "O'reilly") is None
    assert pc.guarded("Erlbaum", "Erlbaum") == "Erlbaum"


@pytest.mark.parametrize("name", ["{National Audubon Society}", "M {Van der Linden}", "J B M Goense",
                                  "S-{\\AA} Christianson", "N K Logothetis"])
def test_house_names_unchanged(name):
    assert pc.normalise_names(name)[0] == name


def test_suffix_stripped_from_wave_row(bib):
    assert changed(check(bib, "IyyeEtal15"))["author"] == "M Iyyer and V Manjunatha and J Boyd-Graber and H {Daum\\'{e}}"


def test_initials_come_from_the_researcher_or_reviewer_only(bib):
    """The post-check never adds or hyphenates initials from the sources (wave-3 review:
    5 of 6 applications wrong). GoldEtal05 and Hawk99 get the fuller forms only from
    the reviewer's values."""
    assert "J P Michel" in pc.split_names(check(bib, "GoldEtal05")["final_entry"]["author"])
    assert "J-P Michel" in pc.split_names(check(bib, "GoldEtal05", review=True)["final_entry"]["author"])
    assert "author" not in changed(check(bib, "Hawk99"))  # researcher confirmed 'S Hawking'
    rec = check(bib, "Hawk99", review=True)
    assert changed(rec)["author"] == "S W Hawking"
    assert {c["field"]: c["source"] for c in rec["changes"]}["author"] == "reviewer"


def test_initials_not_changed_when_sources_disagree_or_match(bib):
    rec = check(bib, "BlisColl93")  # PubMed 'T V', Crossref 'T. V. P.'; proposal keeps T V P
    assert "initials_from_source" not in codes(rec)
    assert rec["final_entry"]["author"] == "T V P Bliss and G L Collingridge"


def test_single_source_surname_change_is_flagged(bib):
    rec = check(bib, "MannEtal23b")
    assert "surname_single_source" in codes(rec)
    # the hold keeps the cited name: the respelled surname is not in the final entry
    assert rec["final_entry"]["author"] == "J R Manning and H Menjunatha and K Kording"
    assert "surname_single_source" not in codes(check(bib, "DawKenj06"))  # PubMed + Crossref


# ---------------------------------------------------------------- fields

@pytest.mark.parametrize("given,expected", [
    ("Seattle, United States", "Seattle, {WA}"),
    ("Hillsdale, N.J.", "Hillsdale, {NJ}"),
    ("Odessa, Fla.", "Odessa, {FL}"),
    ("Mahwah, NJ", "Mahwah, {NJ}"),
    ("San Antonio, Texas", "San Antonio, {TX}"),
    ("Berlin, Germany", "Berlin"),  # house address_key
])
def test_us_address(bib, given, expected):
    assert pc.normalise_address(given, pc.city_states(bib))[0] == expected


@pytest.mark.parametrize("value", ["Hove, {UK}", "Berlin", "New York, {NY}", "Heidelberg, Germany"])
def test_address_unchanged(bib, value):
    assert pc.normalise_address(value, pc.city_states(bib))[0] == value


def test_address_rule_on_wave_row(bib):
    assert changed(check(bib, "ChenEtal22"))["address"] == "Seattle, {WA}"


def test_ordinals():
    assert pc.normalise_ordinals("Proceedings of the 53rd Annual Meeting")[0] == \
        "Proceedings of the 53\\textsuperscript{rd} Annual Meeting"
    assert pc.normalise_ordinals("22\\textsuperscript{th} meeting")[0] == "22\\textsuperscript{nd} meeting"
    assert pc.normalise_ordinals("11th and 112th")[0] == "11\\textsuperscript{th} and 112\\textsuperscript{th}"
    assert pc.normalise_ordinals("\\url{https://x.org/1st}")[0] == "\\url{https://x.org/1st}"
    assert pc.normalise_edition("Second")[0] == "2\\textsuperscript{nd}"
    assert pc.normalise_edition("2nd ed.")[0] == "2\\textsuperscript{nd}"
    assert pc.normalise_edition("Rev. and expanded")[0] == "Rev. and expanded"


def test_issue_ranges_and_pages():
    assert pc.normalise_number("3-4")[0] == "3--4"
    assert pc.normalise_number("5–6")[0] == "5--6"
    assert pc.normalise_number("6407")[0] == "6407"
    assert pc.normalise_pages("347-76")[0] == "347--376"
    assert pc.normalise_pages("31--39")[0] == "31--39"


def test_proceedings_booktitle_year():
    assert pc.normalise_booktitle("Proceedings of the 2022 Conference of the North {American} Chapter")[0] == \
        "Proceedings of the Conference of the North {American} Chapter"
    assert pc.normalise_booktitle("Advances in Neural Information Processing Systems 13 (2000)")[0] == \
        "Advances in Neural Information Processing Systems 13"
    assert pc.normalise_booktitle("Handbook of Data Visualization")[0] == "Handbook of Data Visualization"
    assert pc.normalise_booktitle("Memory in 2000: A Retrospective")[0] == "Memory in 2000: A Retrospective"


def test_book_has_no_pages(bib):
    row = copy.deepcopy(ROWS["HeatEtal93"])
    row["fields"]["pages"] = {"status": "confirmed", "value": "1--230", "evidence": []}
    rec = check(bib, "HeatEtal93", row)
    assert rec["final_entry"]["ENTRYTYPE"] == "book" and "pages" not in rec["final_entry"]


def test_titled_inbook_becomes_incollection(bib):
    rec = check(bib, "WardEtal09")
    ch = changed(rec)
    assert ch["ENTRYTYPE"] == "incollection"
    assert ch["title"].startswith("The roles of short-term and long-term verbal memory")
    assert ch["booktitle"].startswith("Interactions Between Short-Term")
    assert "chapter" in rec["removals"]


def test_inbook_with_booktitle_becomes_incollection(bib):
    assert changed(check(bib, "Este91"))["ENTRYTYPE"] == "incollection"
    assert "ENTRYTYPE" not in changed(check(bib, "BlisColl93"))


def test_invalid_entrytype_dropped(bib):
    rec = check(bib, "Mann06")
    assert "invalid_entrytype" in codes(rec) and "ENTRYTYPE" not in changed(rec)


# ---------------------------------------------------------------- empties, not_found, validator

def test_empty_values_never_applied(bib):
    rec = check(bib, "Chri92")
    assert any(f["code"] == "empty_value" and f["field"] == "author" for f in rec["flags"])
    assert rec["final_entry"].get("author") == bib["Chri92"].get("author")
    rec = check(bib, "Frie06")
    assert rec["final_entry"]["volume"] == "III"


def test_not_found_and_no_source_never_change_the_entry(bib):
    rec = check(bib, "BeckBurg01")
    assert "year" not in changed(rec) and "pages" not in changed(rec)
    assert {f["field"] for f in rec["flags"] if f["code"] == "field_not_found"} == {"year", "pages"}
    row = copy.deepcopy(ROWS["BeckBurg01"])
    row["fields"]["year"]["value"] = "2000"  # a not_found value that differs is only a suggestion
    rec = check(bib, "BeckBurg01", row)
    assert rec["final_entry"]["year"] == "2001" and rec["suggestions"]["year"] == "2000"
    assert check(bib, "GreeEtal13")["changes"] == []


def test_validator_failure_holds_field(bib):
    rec = check(bib, "Chri92")
    assert any(f["code"] == "quote_check_failed" and f["field"] == "title" for f in rec["flags"])


# ---------------------------------------------------------------- years, verdicts, style

def test_print_year_from_notes(bib):
    rec = check(bib, "KansEtal15")
    assert "print_year_conflict" in codes(rec) and rec["suggestions"]["year"] == "2017"
    assert "print_year_conflict" not in codes(check(bib, "BeckBurg01"))  # printed 2001 = year


def test_verdict_consistency(bib):
    assert "verdict_inconsistent" in codes(check(bib, "Este91"))  # 'verified' with a corrected DOI
    assert "verdict_understated" in codes(check(bib, "Wech45"))
    assert not codes(check(bib, "BlisColl93")) & {"verdict_inconsistent", "verdict_understated"}


def test_style_only_title_change_flagged(bib):
    assert "style_only_change" in codes(check(bib, "EngeFrie10"))
    assert "style_only_change" not in codes(check(bib, "HeatEtal93"))
    assert "style_only_change" not in codes(check(bib, "GallRoed02"))  # colon-case house fix, not spacing


# ---------------------------------------------------------------- reviewer merge

def test_reviewer_values_merge_with_provenance(bib):
    rec = check(bib, "EchaEtal00", review=True)
    by = {c["field"]: c for c in rec["changes"]}
    assert by["year"]["proposed"] == "2004" and by["year"]["source"] == "reviewer"
    assert rec["key_plan"]["new_key"] == "EchaEtal04"


def test_reviewer_null_withdraws_change(bib):
    rec = check(bib, "KleiEtal07b", review=True)
    assert "doi" not in changed(rec)
    assert changed(rec)["ENTRYTYPE"] == "incollection"


def test_reviewer_key_agreement(bib):
    plan = check(bib, "GoenEtal08", review=True)["key_plan"]
    assert plan["reviewer_key"]["key"] == "GoenLogo08" and plan["reviewer_agrees"] is True


# ---------------------------------------------------------------- whole wave

def test_wave1_run_measures_review(tmp_path):
    post, page, rules_only, merged = pc.run(WAVE, write=False)
    m = post["measurement"]
    assert m["findings"] == 29 and m["random_sample_findings"] == 10
    caught = {r["key"] for r in m["rows"] if r["caught"]}
    assert {"KleiEtal07b", "WardEtal09", "PetzHaub04", "GoebLewa91", "Este91", "GoenEtal08", "DawKenj06",
            "Frie06", "EchaEtal00", "LittEtal98", "IyyeEtal15", "ChenEtal22",
            "KansEtal15"} <= caught
    # GoldEtal05's J-P was caught by the source-initials rule, removed after the wave-3
    # review; the reviewer's value now supplies it (test_initials_come_from_...)
    assert "GoldEtal05" not in caught
    assert len(page) == 200
    for p in page:  # never an empty proposed value
        assert all(str(c["proposed"] or "").strip() for c in p["final_changes"]), p["key"]


# ---------------------------------------------------------------- wave-2 review regressions

WAVE2 = ROOT / "verification/research-2026-09-25/wave2"


def load_wave(folder):
    out = {}
    for batch in sorted(folder.glob("batch-*.json")):
        for row in json.loads(batch.read_text()):
            out[row["key"]] = row
    review = {r["key"]: r for r in json.loads((folder / "review.json").read_text())}
    validation = {e["key"]: e for e in json.loads((folder / "validation.json").read_text())["report"]}
    return out, review, validation


ROWS2, REVIEW2, VALIDATION2 = load_wave(WAVE2)


def check2(bib, key, row=None, review=False):
    row = row or ROWS2[key]
    return pc.check_entry(row, bib.get(key), bib, ctx_for(bib),
                          review=REVIEW2.get(key) if review else None,
                          validation=VALIDATION2.get(key))


@pytest.mark.parametrize("key,name", [
    ("DezfDali20", "M {Parto Dezfouli}"),
    ("DupoEtal00", "D {Le Bihan}"),
    ("SilbEtal03", "V {Di Lazzaro}"),
    ("HoltEtal12", "P {Riva Posse}"),
    ("TingEtal02", "M-L {Ting Lee}"),
    ("CassEtal02", "V {Di Lazzaro}"),
    ("CowaEtal04", "S {Della Sala}"),
    ("PaszEtal19", "A K{\\\"o}pf"),
])
def test_compound_surname_never_read_as_given_name(bib, key, name):
    """Wave-2 review: the first word of a compound surname (or the previous author in a
    comma-less byline) was added as an initial. Rules alone, no reviewer values."""
    rec = check2(bib, key)
    assert name in pc.split_names(rec["final_entry"]["author"]), rec["final_entry"]["author"]
    assert not any(f["code"] == "initials_from_source" and name.split()[-1] in f["detail"] for f in rec["flags"])


def test_researcher_initials_kept_without_reviewer_value(bib):
    """The rule that read initials from the sources is gone: AllpEtal94 and MillEtal03
    keep the researcher's initials (only format is normalised)."""
    assert not hasattr(pc, "initials_from_evidence")
    assert "S Hsieh" in pc.split_names(check2(bib, "AllpEtal94")["final_entry"]["author"])
    assert "X J Wang" in pc.split_names(check2(bib, "MillEtal03")["final_entry"]["author"])


NEURIPS_CONVERSIONS = ("BorzEtal23b", "ChanEtal09a", "ChenEtal24b", "ChenEtal24c", "GrifStey03", "KiroEtal15",
                       "KrizEtal12", "MairEtal09b", "MnihHint09", "PaszEtal19", "SanbGrif08", "ShihEtal23",
                       "SochEtal09")


@pytest.mark.parametrize("key", NEURIPS_CONVERSIONS + ("SchaTurk15", "Sina07", "MayeEtal92b", "AllpEtal94"))
def test_type_conversion_drops_journal(bib, key):
    rec = check2(bib, key, review=True)
    fin = rec["final_entry"]
    assert fin["ENTRYTYPE"] in ("inproceedings", "incollection") and fin.get("booktitle")
    assert "journal" not in fin and "journal" in rec["removals"]


def test_journal_as_series(bib):
    rec = check2(bib, "MayeEtal92b", review=True)
    assert rec["final_entry"]["series"] == "Advances in Psychology"
    row = copy.deepcopy(ROWS2["MayeEtal92b"])
    row["fields"].pop("series", None)  # no series proposed: the journal becomes the series
    fin = check2(bib, "MayeEtal92b", row)["final_entry"]
    assert fin.get("series") == bib["MayeEtal92b"]["journal"] and "journal" not in fin


def test_series_number_in_booktitle_drops_volume(bib):
    rec = check2(bib, "AllpEtal94", review=True)
    assert "volume" not in rec["final_entry"] and "volume" in rec["removals"]
    assert check2(bib, "KrizEtal12", review=True)["final_entry"]["volume"] == "25"  # NeurIPS volume kept


def test_article_keeps_journal(bib):
    for key in ("GoldEtal05", "DawKenj06"):
        fin = check(bib, key)["final_entry"]
        assert fin["ENTRYTYPE"] == "article" and fin["journal"], key


def test_lowercase_entrytype_is_the_type(bib):
    rec = check2(bib, "AllpEtal94")  # rules alone: researcher wrote 'entrytype'
    assert rec["final_entry"]["ENTRYTYPE"] == "incollection"
    assert "entrytype" not in rec["final_entry"]
    assert pc.field_name("EntryType") == "ENTRYTYPE" and pc.field_name("Journal") == "journal"


def test_duplicate_of_head_entry_without_doi(bib):
    """CronEtal98a gains a DOI; CronEtal98c (HEAD, no DOI) is the same Part II paper."""
    rec = check2(bib, "CronEtal98a")
    assert "duplicate" in codes(rec) and "CronEtal98c" in rec["key_plan"]["same_work_as"]
    plan = check2(bib, "CronEtal98c")["key_plan"]
    assert plan["action"] == "duplicate" and plan["merge_into"] == "CronEtal98a"
    assert "CronEtal98b" not in rec["key_plan"]["same_work_as"]  # Part I is a different work


def test_part_numbers_distinguish_works(bib):
    assert not pc.same_work(bib["CronEtal98b"], bib["CronEtal98a"])
    assert pc.same_work(bib["CronEtal98c"], bib["CronEtal98a"])


def test_duplicates_within_a_wave():
    base = {"ENTRYTYPE": "article", "author": "A Smith and B Jones", "year": "2001",
            "title": "A study of recall in rats"}
    recs = {k: {"final_entry": dict(base, **extra), "key_plan": {"action": "keep", "current_key": k}, "flags": []}
            for k, extra in (("SmitJone01", {"doi": "10.1/x"}), ("SmitJone01b", {"doi": "10.1/X"}),
                             ("SmitJone01c", {"title": "Another study entirely", "doi": "10.1/y"}))}
    pc.wave_duplicates(recs)
    assert recs["SmitJone01b"]["key_plan"]["merge_into"] == "SmitJone01"
    assert recs["SmitJone01"]["key_plan"]["action"] == "keep" and recs["SmitJone01"]["flags"]
    assert recs["SmitJone01c"]["key_plan"]["action"] == "keep" and not recs["SmitJone01c"]["flags"]


def test_registry_title_with_footnote_matches(bib):
    rec = pc.doi_record("10.1016/s0006-3223(00)00917-3")
    assert rec["title"].startswith("Laboratory sleep correlates of nightmare complaint in PTSD inpatients11")
    r = check2(bib, "WoodEtal00b", review=True)
    assert changed(r)["doi"] == "10.1016/s0006-3223(00)00917-3" and "doi_title_mismatch" not in codes(r)
    assert pc.registry_title_matches("Memory for places in infancy*", "Memory for faces in infancy") is False
    assert pc.registry_title_matches("A theory of memory for faces*", "A theory of memory for faces")
    assert pc.registry_title_matches("Correspondence", "Correspondence regarding memory for faces") is False
    # strictness kept: another work's title, and a part number continuing the title
    assert not pc.registry_title_matches("Functional mapping of human sensorimotor cortex II",
                                         "Functional mapping of human sensorimotor cortex")


def test_boddetal97_generic_record_title_still_dropped(bib):
    rec = check(bib, "BoddEtal97")
    assert "doi_title_mismatch" in codes(rec) and "doi" not in changed(rec)


@pytest.mark.parametrize("key,expected", [
    ("CaoWors99", {"doi": "10.1214/aoap/1029962864"}),
    ("Schw78", {"volume": "6", "number": "2", "doi": "10.1214/aos/1176344136"}),
    ("Hint84", {"volume": "16"}),
])
def test_reviewer_confirmed_values_replace_blocked_holds(bib, key, expected):
    rec = check2(bib, key, review=True)
    by = {c["field"]: c for c in rec["changes"]}
    for field, value in expected.items():
        assert by[field]["proposed"] == value and by[field]["source"] == "reviewer", field
        assert field not in rec["held"]
    assert pc.fold(rec["final_entry"]["title"]) == pc.fold(REVIEW2[key]["suggested_value"].get(
        "title", rec["final_entry"]["title"]))


def test_reviewer_agreement_releases_fetch_blocked_hold(bib):
    """A field held only because the source could not be read, and the reviewer agrees
    with it (no suggested value): applied with provenance reviewer."""
    review = {"key": "CaoWors99", "agree": "yes", "field_verdicts": {"title": "agree (Crossref)"},
              "suggested_value": {}}
    rec = pc.check_entry(ROWS2["CaoWors99"], bib["CaoWors99"], bib, ctx_for(bib), review=review,
                         validation=VALIDATION2["CaoWors99"])
    assert changed(rec)["title"].startswith("The geometry of correlation fields with")
    assert {c["field"]: c["source"] for c in rec["changes"]}["title"] == "reviewer"
    # negative control: no reviewer confirmation keeps the hold
    rec = check2(bib, "CaoWors99")
    assert "title" in rec["held"] and "title" not in changed(rec)
    # a quote that fails on a page that WAS read (Hint84 volume) is not a fetch block
    assert not pc.fetch_blocked(VALIDATION2["Hint84"]["fields"]["volume"], VALIDATION2["Hint84"])
    assert pc.fetch_blocked(VALIDATION2["CaoWors99"]["fields"]["title"], VALIDATION2["CaoWors99"])


def test_wave2_review_resolution():
    post, page, rules_only, merged = pc.run(WAVE2, write=False)
    res = post["review_resolution"]
    fixed = {r["key"] for r in res["rows"] if r["resolved"]}
    assert {"DezfDali20", "DupoEtal00", "SilbEtal03", "PaszEtal19", "AllpEtal94", "CronEtal98a", "WoodEtal00b",
            "CaoWors99", "Schw78", "Hint84", "BorzEtal23b", "MayeEtal92b", "SchaTurk15"} <= fixed
    for p in page:
        assert all(str(c["proposed"] or "").strip() for c in p["final_changes"]), p["key"]


# ---------------------------------------------------------------- wave-3 review regressions

WAVE3 = ROOT / "verification/research-2026-09-25/wave3"
ROWS3, REVIEW3, VALIDATION3 = load_wave(WAVE3)


def check3(bib, key, row=None, review=False, current=None):
    row = row or ROWS3[key]
    return pc.check_entry(row, current if current is not None else bib.get(key), bib, ctx_for(bib),
                          review=REVIEW3.get(key) if review else None,
                          validation=VALIDATION3.get(key))


def researcher_value(row, field):
    return (pc.canonical_fields(row["fields"]).get(field) or {}).get("value")


@pytest.mark.parametrize("key,name", [
    ("BragEtal99", "J Engel"),       # PubMed 'Engel, J Jr' was read as 'J J Engel'
    ("MeckEtal99", "A Mecklinger"),  # PubMed-only 'A D' against the publisher's 'Axel'
    ("LachEtal00a", "E Rodriguez"),  # World Scientific all-caps 'EUGENIO'
    ("CarlEtal05", "G Carlsson"),    # 'GUNNAR'
])
def test_no_initials_added_from_sources(bib, key, name):
    rec = check3(bib, key)
    assert name in pc.split_names(rec["final_entry"]["author"]), rec["final_entry"]["author"]
    assert not codes(rec) & {"initials_from_source", "initials_uncertain"}


def test_author_changes_only_as_researcher_proposed(bib):
    """Every researcher author/editor that is applied ends as the researcher's value in
    house FORMAT: the same number of initials per name (rules alone, waves 1-3)."""
    for folder in (WAVE, WAVE2, WAVE3):
        post, page, rules_only, merged = pc.run(folder, write=False, offline=True)
        rows_, _, _ = load_wave(folder)
        for k, rec in rules_only.items():
            for field in pc.NAME_FIELDS:
                ch = {c["field"]: c for c in rec["changes"]}.get(field)
                if not ch or ch["source"] != "researcher":
                    continue
                raw = researcher_value(rows_[k], field)
                want, notes = pc.normalise_names(raw)
                want = want if notes else raw  # set only when the normaliser reports a change
                if field == "author" and "author" in rec["held"]:  # single-source surname kept as cited
                    assert "surname_single_source" in codes(rec), k
                    got_n, want_n = pc.split_names(ch["proposed"]), pc.split_names(want)
                    cited = {pc.normalise_name(n)[0] for n in pc.split_names(bib[k]["author"])}
                    assert len(got_n) == len(want_n), k
                    assert all(g == w or g in cited for g, w in zip(got_n, want_n)), (k, got_n)
                else:
                    assert ch["proposed"] == want, (folder.name, k, ch["proposed"], want)
                for n in pc.split_names(ch["proposed"]):
                    assert not any(len(t) == 1 and t.isalpha() for t in pc.split_top(pc.surname(n))), (k, n)


@pytest.mark.parametrize("given,expected", [
    ("Rodriguez, EUGENIO", "E Rodriguez"),
    ("EUGENIO RODRIGUEZ", "E Rodriguez"),
    ("JEAN-PHILIPPE LACHAUX", "J-P Lachaux"),
    ("{Le Van Quyen}, MICHEL", "M {Le Van Quyen}"),
    ("Engel, J Jr", "J Engel"),
    ("JP Smith", "J P Smith"),        # clumped initials stay initials
    ("M A A {van der Meer}", "M A A {van der Meer}"),
])
def test_capitalised_given_names_are_never_spelled_as_letters(given, expected):
    assert pc.normalise_names(given)[0] == expected


@pytest.mark.parametrize("key", ["DesaEtal12", "BoseEtal92"])
def test_journal_naming_the_booktitle_venue_is_dropped_not_series(bib, key):
    rec = check3(bib, key)
    fin = rec["final_entry"]
    assert "series" not in fin and "journal" not in fin and "journal" in rec["removals"]


def test_same_venue():
    assert pc.same_venue("Engineering in Medicine and Biology Society Annual International Conference of the {IEEE}",
                         "Annual International Conference of the {IEEE} Engineering in Medicine and Biology Society")
    assert pc.same_venue("Fifth Annual Workshop on Computational Learning Theory, {ACM}",
                         "Proceedings of the Fifth Annual Workshop on Computational Learning Theory")
    assert not pc.same_venue("Advances in Psychology", "The Nature and Origins of Mathematical Skills")
    assert not pc.same_venue("Lecture Notes in Computer Science", "Computer Vision -- {ECCV}")


ARTICLE_NUMBERS = ("Brig12", "JayaEtal23", "CookEtal16", "AfshEtal13", "NastEtal18")


@pytest.mark.parametrize("key", ARTICLE_NUMBERS)
def test_article_number_moved_to_pages_removes_number(bib, key):
    row = copy.deepcopy(ROWS3[key])
    row.pop("remove", None)  # the rule alone, without the researcher's remove list
    rec = check3(bib, key, row)
    fin = rec["final_entry"]
    assert fin["pages"] == bib[key]["number"] and "number" not in fin and "number" in rec["removals"]


def test_number_kept_when_it_is_not_the_article_number(bib):
    row = copy.deepcopy(ROWS3["FoxGrei10"])  # Number 10, article number 19
    row.pop("remove", None)
    rec = check3(bib, "FoxGrei10", row)
    assert rec["final_entry"]["number"] == "10" and "number" not in rec["removals"]
    rec = check3(bib, "Bastvand05")  # issue 1, pages 61--77
    assert rec["final_entry"]["number"] == "1" and not rec["removals"]


def test_researcher_remove_list_is_honoured(bib):
    rec = check3(bib, "FoxGrei10")  # remove: ["number"]
    assert "number" not in rec["final_entry"] and "researcher" in rec["removals"]["number"]
    rec = check3(bib, "VidaEtal10")
    assert "number" not in rec["final_entry"] and "number" in rec["removals"]


def test_misc_drops_journal_and_url_volume(bib):
    row = copy.deepcopy(ROWS3["Hint12"])
    row.pop("remove", None)
    rec = check3(bib, "Hint12", row)
    fin = rec["final_entry"]
    assert fin["ENTRYTYPE"] == "misc" and "journal" not in fin and "volume" not in fin
    assert {"journal", "volume"} <= set(rec["removals"])
    current = dict(bib["Hint12"], volume="2")  # negative control: a plain volume stays
    rec = check3(bib, "Hint12", row, current=current)
    assert rec["final_entry"]["volume"] == "2" and "journal" not in rec["final_entry"]


def test_corroborated_print_year_beats_crossref_deposit(bib):
    rec = check3(bib, "Bastvand05")  # PubMed + Europe PMC print 2006; Crossref published-print 2005
    assert rec["final_entry"]["year"] == "2006"
    assert "year" not in rec["suggestions"]
    assert any(f["code"] == "doi_record_conflict" and f["field"] == "year" for f in rec["flags"])
    # negative control: one print-date source only -> Crossref's print year is still suggested
    row = copy.deepcopy(ROWS3["Bastvand05"])
    row["fields"]["year"]["evidence"] = row["fields"]["year"]["evidence"][:1]
    rec = check3(bib, "Bastvand05", row)
    assert rec["suggestions"].get("year") == "2005" and "print_year_conflict" in codes(rec)


def test_single_source_surname_hold_keeps_cited_name(bib):
    rec = check3(bib, "FreeEtal03b")  # Crossref deposit typo 'Jorsten'; cited 'Jornten'
    assert "surname_single_source" in codes(rec)
    names = pc.split_names(rec["final_entry"]["author"])
    assert names[2] == pc.split_names(bib["FreeEtal03b"]["author"])[2] and "Jorsten" not in rec["final_entry"]["author"]
    rec = check3(bib, "FreeEtal03b", review=True)  # the reviewer's corrected surname
    assert pc.split_names(rec["final_entry"]["author"])[2] == 'R J{\\"o}rnsten'
    # a surname the reviewer confirms (Crossref also gives it) is released, provenance reviewer
    rec = check3(bib, "Brig12", review=True)
    assert rec["final_entry"]["author"] == "F {De Brigard}"
    assert {c["field"]: c["source"] for c in rec["changes"]}["author"] == "reviewer"
    assert rec["final_entry"]["author"] != check3(bib, "Brig12")["final_entry"]["author"]


@pytest.mark.parametrize("folder,findings", [(WAVE3, 8)])
def test_wave3_review_resolution(folder, findings):
    post, page, rules_only, merged = pc.run(folder, write=False, offline=True)
    res = post["review_resolution"]
    assert res["findings"] == findings and res["unresolved"] == [], res["unresolved"]
    assert not any(f["code"] == "initials_from_source" for r in merged.values() for f in r["flags"])


def test_surname_hold_keeps_the_whole_cited_name(bib):
    """AguiEtal96: cited 'M D Esposito', researcher 'M D'Esposito' from PubMed alone. The
    hold keeps the cited name whole, so no initial is dropped ('M Esposito' was wrong)."""
    rec = check2(bib, "AguiEtal96")
    assert "surname_single_source" in codes(rec)
    assert pc.split_names(rec["final_entry"]["author"])[-1] == "M D Esposito"


@pytest.mark.parametrize("wave,key", [("3", "BasaEtal92"), ("3", "KatzEtal89")])
def test_brace_or_spacing_fix_is_not_a_respelling(bib, wave, key):
    """{Schurman n} -> Sch{\\"u}rmann and a broken L{\\\\"u}ders are format fixes of the same
    letters, not surname respellings: applied, no hold."""
    rec = (check2 if wave == "2" else check3)(bib, key)
    assert "surname_single_source" not in codes(rec)
    assert "author" not in rec["held"] and "author" in changed(rec)
