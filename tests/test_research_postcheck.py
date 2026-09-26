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
    # a surname the reviewer confirms is released, provenance reviewer (RuggEtal96:
    # cited 'Patchin', Crossref only 'Patching')
    rec = check3(bib, "RuggEtal96", review=True)
    assert "Patching" in rec["final_entry"]["author"]
    assert {c["field"]: c["source"] for c in rec["changes"]}["author"] == "reviewer"
    assert any(f["code"] == "surname_single_source" and f["action"] == "applied" for f in rec["flags"])
    rules_alone = check3(bib, "RuggEtal96")
    assert "author" in rules_alone["held"] and "Patching" not in rules_alone["final_entry"]["author"]
    # Brig12's cited 'F De Brigard' -> 'F {De Brigard}' is a particle brace fix (same
    # letters, wave-4 fix), applied by the rules alone without a hold
    rec = check3(bib, "Brig12")
    assert rec["final_entry"]["author"] == "F {De Brigard}" and "surname_single_source" not in codes(rec)


@pytest.mark.parametrize("folder,findings", [(WAVE3, 8)])
def test_wave3_review_resolution(folder, findings):
    post, page, rules_only, merged = pc.run(folder, write=False, offline=True)
    res = post["review_resolution"]
    assert res["findings"] == findings and res["unresolved"] == [], res["unresolved"]
    assert not any(f["code"] == "initials_from_source" for r in merged.values() for f in r["flags"])


def without_house_spelling(bib, name, key):
    """cdl.bib without the other entries that write `name` for the same person, so a
    test of another hold rule is not released by the wave-6 cdl.bib rule."""
    drop = set(pc.house_name_uses(bib, name, exclude_key=key))
    assert drop  # the corroborating entries exist in HEAD
    return {k: v for k, v in bib.items() if k not in drop}


def test_surname_hold_keeps_the_whole_cited_name(bib):
    """AguiEtal96: cited 'M D Esposito', researcher 'M D'Esposito' from PubMed alone. The
    hold keeps the cited name whole, so no initial is dropped ('M Esposito' was wrong).
    With the proposed DOI kept, its Crossref record is the second host (wave-5 fix) and
    the surname is applied; without the DOI the hold stands. (Wave-6 cdl.bib rule: cdl.bib
    writes 'M D'Esposito' in other entries, which alone releases the DOI-less hold, so the
    hold is tested on the bibliography without those entries.)"""
    row = copy.deepcopy(ROWS2["AguiEtal96"])
    row["fields"] = {k: v for k, v in row["fields"].items() if k.lower() != "doi"}
    rec = check2(bib, "AguiEtal96", row)
    assert any(f["code"] == "surname_corroborated" and "cdl.bib rule" in f["detail"] for f in rec["flags"])
    alone = without_house_spelling(bib, "M D'Esposito", "AguiEtal96")
    rec = pc.check_entry(row, bib["AguiEtal96"], alone, ctx_for(alone), validation=VALIDATION2.get("AguiEtal96"))
    assert "surname_single_source" in codes(rec)
    assert pc.split_names(rec["final_entry"]["author"])[-1] == "M D Esposito"
    rec = check2(bib, "AguiEtal96")
    assert "surname_single_source" not in codes(rec)
    assert pc.split_names(rec["final_entry"]["author"])[-1] == "M D'Esposito"


@pytest.mark.parametrize("wave,key", [("3", "BasaEtal92"), ("3", "KatzEtal89")])
def test_brace_or_spacing_fix_is_not_a_respelling(bib, wave, key):
    """{Schurman n} -> Sch{\\"u}rmann and a broken L{\\\\"u}ders are format fixes of the same
    letters, not surname respellings: applied, no hold."""
    rec = (check2 if wave == "2" else check3)(bib, key)
    assert "surname_single_source" not in codes(rec)
    assert "author" not in rec["held"] and "author" in changed(rec)


# ---------------------------------------------------------------- wave-4 review regressions

WAVE4 = ROOT / "verification/research-2026-09-25/wave4"
ROWS4, REVIEW4, VALIDATION4 = load_wave(WAVE4)


def check4(bib, key, row=None, review=False):
    row = row or ROWS4[key]
    return pc.check_entry(row, bib.get(key), bib, ctx_for(bib),
                          review=REVIEW4.get(key) if review else None, validation=VALIDATION4.get(key))


def test_particle_brace_fix_is_not_a_respelling(bib):
    """VogtEtal14: cited 'B A L Di Leone', researcher 'B A L {Di Leone}'. The normaliser
    made the unbraced particle an initial ('B A L D Leone') and the surname hold kept that."""
    assert pc.normalise_names("B A L Di Leone")[0] == "B A L {Di Leone}"
    assert pc.normalise_names("D Le Bihan")[0] == "D {Le Bihan}"
    rec = check4(bib, "VogtEtal14")
    assert rec["final_entry"]["author"] == "D Vogt and A B Fox and B A L {Di Leone}"
    assert "surname_single_source" not in codes(rec) and "author" not in rec["held"]
    # negative controls: a first-token 'Van' is a given name; a real respelling is held and
    # keeps the cited name in house form, never 'B A L D Leone'
    assert pc.normalise_names("Van Morrison")[0] == "V Morrison"
    row = copy.deepcopy(ROWS4["VogtEtal14"])
    row["fields"]["author"]["value"] = "D Vogt and A B Fox and B A L {Di Leoni}"
    rec = check4(bib, "VogtEtal14", row)
    assert "surname_single_source" in codes(rec)
    assert pc.split_names(rec["final_entry"]["author"])[-1] == "B A L {Di Leone}"


def test_researcher_remove_list_beats_journal_to_series(bib):
    """NeweRose81 (@article -> @incollection; the JMP article does not exist): the
    researcher removes journal, so it is never moved into series."""
    rec = check4(bib, "NeweRose81")
    assert "series" not in rec["final_entry"] and "journal" not in rec["final_entry"]
    assert "researcher" in rec["removals"]["journal"]
    row = copy.deepcopy(ROWS4["NeweRose81"])  # negative control: journal not in the remove list
    row["remove"] = [f for f in row["remove"] if f != "journal"]
    assert check4(bib, "NeweRose81", row)["final_entry"]["series"] == "Journal of Mathematical Psychology"


@pytest.mark.parametrize("key,doi", [
    ("Mitc09", "10.1177/0269881108091592"),    # 'Book Review: <title> Michael First, ... Price: 50'
    ("Waug63b", "10.1037/h0041501"),           # '2 methods' = 'Two methods'
    ("WehnSrin81", "10.1007/bf00605445"),      # 'genusCataglyphis' glued by the registry
])
def test_correct_dois_kept_by_title_check(bib, key, doi):
    rec = check4(bib, key)
    assert changed(rec).get("doi") == doi and "doi_title_mismatch" not in codes(rec)


def test_title_check_still_rejects_other_works():
    two = "Two methods for testing serial memorization"
    assert not pc.registry_title_matches("3 methods for testing serial memorization.", two)
    assert not pc.registry_title_matches("Book Review: A guide to the diagnosis of sleep disorders Michael First",
                                         "Clinical guide to the diagnosis and treatment of mental disorders")
    assert not pc.registry_title_matches("Book Review: Functional mapping of human sensorimotor cortex II",
                                         "Functional mapping of human sensorimotor cortex")
    assert not pc.registry_title_matches("Searching behaviour of desert bees, genusApis (Apidae)",
                                         "Searching behaviour of desert ants, genus \\textit{Cataglyphis} "
                                         "({Formicidae}, {Hymenoptera})")
    assert pc.fold("genus \\textit{Cataglyphis}") == "genus cataglyphis"


def test_rate_limited_request_is_retried(tmp_path):
    """A real local HTTP server answers 429 (Retry-After: 0) twice, then 200: http_get
    retries and returns the 200. A server that always answers 429 gives 429 after the
    retries, which is never cached (CeraHend65 and HaymTulv89 were held on 429 only)."""
    import http.server
    import threading
    import uuid
    calls = {"n": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            calls["n"] += 1
            limited = "always" in self.path or calls["n"] <= 2
            self.send_response(429 if limited else 200)
            if limited:
                self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(b'{"limited": true}' if limited else b'{"ok": true}')

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    urls = [f"{base}/ok/{uuid.uuid4().hex}", f"{base}/always/{uuid.uuid4().hex}"]
    try:
        assert pc.http_get(urls[0]) == (200, '{"ok": true}') and calls["n"] == 3
        calls["n"] = 0
        status, _ = pc.http_get(urls[1], retries=2)
        assert status == 429 and calls["n"] == 3
        assert pc.http_get(urls[1], offline=True)[0] is None  # the 429 was not cached
    finally:
        server.shutdown()
        for u in urls:
            (pc.CACHE / (pc.hashlib.sha256(u.encode()).hexdigest() + ".json")).unlink(missing_ok=True)
    assert pc.retry_wait("7", 0) == 7 and pc.retry_wait(None, 2) == pc.BACKOFF * 4
    assert pc.retry_wait("100000", 0) == pc.MAX_WAIT


@pytest.mark.parametrize("key,doi", [("CeraHend65", "10.1037/h0022247"),
                                     ("HaymTulv89", "10.1037/0278-7393.15.5.941")])
def test_dois_held_only_by_rate_limit_now_checked(bib, key, doi):
    rec = check4(bib, key)
    assert changed(rec).get("doi") == doi and "doi_title_unavailable" not in codes(rec)


def test_run_together_surname_follows_house_form(bib):
    """MillEtal07d: the journal prints 'denNijs'; cdl.bib writes the same author M {den Nijs}."""
    rec = check4(bib, "MillEtal07d")
    assert "M {den Nijs}" in pc.split_names(rec["final_entry"]["author"])
    # negative controls: another initial, a spaced form, and a name cdl.bib has no spaced form for
    assert pc.house_surname("Q {denNijs}", bib)[0] == "Q {denNijs}"
    assert pc.house_surname("M {den Nijs}", bib)[0] == "M {den Nijs}"
    assert pc.house_surname("K J Miller", bib)[0] == "K J Miller"


def test_hyphenated_journal_keeps_its_suffix(bib):
    """LachEtal03: 'Journal of Physiology-Paris' is not 'Journal of Physiology'."""
    assert check4(bib, "LachEtal03")["final_entry"]["journal"] == "Journal of Physiology-Paris"
    assert pc.H.format_journal_name("Journal of Physiology") == "Journal of Physiology"


# ---------------------------------------------------------------- wave-5 review regressions

WAVE5 = ROOT / "verification/research-2026-09-25/wave5"
ROWS5, REVIEW5, VALIDATION5 = load_wave(WAVE5)


def check5(bib, key, row=None, review=False):
    row = row or ROWS5[key]
    return pc.check_entry(row, bib.get(key), bib, ctx_for(bib),
                          review=REVIEW5.get(key) if review else None, validation=VALIDATION5.get(key))


@pytest.mark.parametrize("key,doi", [
    ("Eich04", "10.1016/j.neuron.2004.08.028"),          # registry: 'Hippocampus'
    ("SaliThie00", "10.1016/s0896-6273(00)00004-0"),    # 'Gain Modulation'
    ("ShadMovs99", "10.1016/s0896-6273(00)80822-3"),    # 'Synchrony Unbound'
    ("WagnEtal01", "10.1016/s0896-6273(01)00359-2"),    # 'Recovering Meaning'
    ("Turi50", "10.1093/mind/lix.236.433"),             # 'I.—COMPUTING MACHINERY AND INTELLIGENCE'
    ("ChabEtal98", "10.1007/bfb0056189"),               # Crossref typo 'padiatric'
])
def test_wave5_correct_dois_kept(bib, key, doi):
    rec = check5(bib, key)
    assert changed(rec).get("doi") == doi and "doi_title_mismatch" not in codes(rec)


def test_precolon_title_needs_volume_or_page():
    entry = ["Hippocampus: cognitive processes and neural representations that underlie declarative memory"]
    rec = {"title": "Hippocampus", "volume": "44", "page": "109-120"}
    assert pc.doi_title_verdict(rec, entry, "44", "109--120")[0] == "match"
    assert pc.doi_title_verdict(dict(rec, volume="7", page="1-9"), entry, "44", "109--120")[0] == "short"
    assert pc.doi_title_verdict(rec, ["Hippocampus and memory"], "44", "109--120")[0] is None


def test_section_numeral_and_typo_tolerance_are_narrow():
    assert pc.registry_title_matches("I.—COMPUTING MACHINERY AND INTELLIGENCE", "Computing machinery and intelligence")
    assert not pc.registry_title_matches("I.—COMPUTING MACHINERY AND INTELLIGENCE", "Computing machinery and wisdom")
    assert pc.one_edit("padiatric", "pediatric") and not pc.one_edit("memory", "memoir")
    # two misspelled words are not one typo
    assert not pc.registry_title_matches("Three-dimensional reconstruction and surgical navigation in padiatric epilepsi",
                                         "Three-dimensional reconstruction and surgical navigation in pediatric epilepsy")


def test_part_number_guard_is_live(bib):
    """The bare titles_match alternative used to bypass the part-number rule. JacoEtal98
    ('Virtual Space {II}', Crossref 'Place Learning in Virtual Space') is kept only because
    the record's first page is the entry's; without that the DOI is held."""
    rec = check5(bib, "JacoEtal98")
    assert any(f["code"] == "doi_title_part_number" and f["action"] == "applied" for f in rec["flags"])
    entry = [bib["JacoEtal98"]["title"]]
    assert pc.doi_title_verdict({"title": "Place Learning in Virtual Space", "page": "1-20"},
                                entry, None, "288--308")[0] == "part_number"
    assert pc.doi_title_verdict({"title": "Functional mapping of human sensorimotor cortex II"},
                                ["Functional mapping of human sensorimotor cortex"])[0] == "part_number"


@pytest.mark.parametrize("key,name", [("VanEEtal01", "J Dickson"), ("ToluEtal12", "J-P Changeux")])
def test_doi_record_counts_as_second_surname_host(bib, key, name):
    rec = check5(bib, key)
    assert name in pc.split_names(rec["final_entry"]["author"]) and "surname_single_source" not in codes(rec)
    row = copy.deepcopy(ROWS5[key])  # negative control: without the DOI record, one host: held
    row["fields"] = {k: v for k, v in row["fields"].items() if k.lower() != "doi"}
    current = dict(bib[key])
    current.pop("doi", None)
    # (wave 6: cdl.bib's own spelling of these people, e.g. DehaChan06 'J-P Changeux', is a
    # witness of its own; the one-host hold is tested without those entries)
    alone = without_house_spelling(bib, name, key) if pc.house_name_uses(bib, name, key) else bib
    rec = pc.check_entry(row, current, alone, ctx_for(alone), validation=VALIDATION5.get(key))
    assert "surname_single_source" in codes(rec) and name not in pc.split_names(rec["final_entry"]["author"])


@pytest.mark.parametrize("key,name", [("KrauEtal13", "R J Robinson"), ("ChamEtal03", "A A Artigas"),
                                      ("WagnEtal01", "E J Paré-Blagoev")])
def test_format_damage_is_not_a_respelling(bib, key, name):
    """A mangled suffix ('{Robinson I I }'), a broken split ('{and Artigas}') and a
    restored accented letter ('Par-Blagoev') are not surname respellings."""
    row = copy.deepcopy(ROWS5[key])
    row["fields"] = {k: v for k, v in row["fields"].items() if k.lower() != "doi"}  # no registry host
    rec = check5(bib, key, row)
    assert name in pc.split_names(rec["final_entry"]["author"]) and "surname_single_source" not in codes(rec)


def test_format_damage_helpers():
    assert pc.surname_key("R J {Robinson I I }") == "robinson"
    assert pc.surname_key("A A {and Artigas}") == "artigas"
    assert pc.surname_without_accented("E J Par{\\'e}-Blagoev") == "par blagoev"
    assert pc.surname_without_accented("E J Pare-Blagoev") == "pare blagoev"  # a plain letter is a spelling
    assert pc.surname_key("R J Robertson") == "robertson"


# ---------------------------------------------------------------- wave-6 review regressions

WAVE6 = ROOT / "verification/research-2026-09-25/wave6"
ROWS6, REVIEW6, VALIDATION6 = load_wave(WAVE6)


def check6(bib, key, row=None, review=False, current=None):
    row = row or ROWS6[key]
    return pc.check_entry(row, current if current is not None else bib.get(key), bib, ctx_for(bib),
                          review=REVIEW6.get(key) if review else None, validation=VALIDATION6.get(key))


@pytest.mark.parametrize("key,doi", [
    ("Curr99", "10.1016/s0028-3932(98)00133-x"),   # Crossref 'intentionalretrieval', mojibake 'oldî\x97¿new'
    ("BousRosn70", "10.3758/bf03335608"),          # Crossref deposit typo 'Free vs unhibited recall'
    ("Mart65", "10.1037/h0022250"),                # the ENTRY's typo 'paried'; title left not_found
])
def test_near_title_with_agreeing_metadata_keeps_doi(bib, key, doi):
    """Wave-6 review: correct DOIs were dropped because one title is garbled or mistyped.
    Kept when the title is within two letters (spaces removed, vs = versus) and the
    record's first author, year, volume and first page all agree."""
    rec = check6(bib, key)
    assert changed(rec).get("doi") == doi and "doi_title_mismatch" not in codes(rec)
    assert any(f["code"] == "doi_title_near" and f["action"] == "applied" for f in rec["flags"])
    # negative control: the same record with one metadata field disagreeing is another work
    record = pc.doi_record(doi)
    entry = [bib[key]["title"]]
    year, pages = bib[key]["year"], bib[key]["pages"]
    author = pc.surname(pc.split_names(bib[key]["author"])[0])
    vol = record["volume"]
    assert pc.doi_title_verdict(record, entry, vol, pages, author, year)[0] == "near"
    assert pc.doi_title_verdict(record, entry, str(int(vol) + 1), pages, author, year)[0] is None
    assert pc.doi_title_verdict(record, entry, vol, "999--1000", author, year)[0] is None
    assert pc.doi_title_verdict(record, entry, vol, pages, "Smith", year)[0] is None
    assert pc.doi_title_verdict(record, entry, vol, pages, author, str(int(year) + 1))[0] is None


def test_near_title_still_rejects_other_works(bib):
    """Different wording, a part number, or a short title are never 'near', whatever the
    metadata say."""
    record = pc.doi_record("10.3758/bf03335608")  # 'Free vs unhibited recall', 20(2) 75-76, 1970
    args = ("20", "75--76", "Bousfield", "1970")
    assert pc.doi_title_verdict(record, ["Free versus cued recall"], *args)[0] is None
    assert pc.doi_title_verdict(record, ["Free versus uninhibited recall II"], *args)[0] is None
    assert not pc.near_title("Transfer and verbal paired associates II", "Transfer and verbal paired associates")
    assert not pc.near_title("Serial recall", "Serial recalls")  # under 20 letters
    assert pc.near_title("Free vs unhibited recall", "Free versus uninhibited recall")
    assert pc.osa_distance("paried", "paired") == 1 and pc.osa_distance("abc", "xyzabc") == 3
    # a real row whose record is another work: still dropped (BoddEtal97's 'Correspondence')
    rec = check(bib, "BoddEtal97")
    assert "doi_title_mismatch" in codes(rec) and "doi" not in changed(rec)


def test_hyphenated_dotted_initials(bib):
    """TrulEtal97: 'Jean-{A}rcady Meyer' became 'J-{ Meyer' (the brace read as an
    initial) and the surname hold fired on an unchanged surname."""
    rec = check6(bib, "TrulEtal97")
    assert "surname_single_source" not in codes(rec) and "author" not in rec["held"]
    assert pc.split_names(rec["final_entry"]["author"])[-1] == "J-A Meyer"
    assert pc.normalise_name("J.-A. Meyer")[0] == "J-A Meyer"
    assert pc.given_initials("Jean-{A}rcady") == "J-A"
    # negative controls: separate dotted initials stay separate; accent macros keep their letter
    assert pc.normalise_name("J. A. Meyer")[0] == "J A Meyer"
    assert pc.given_initials("{\\'E}mile") == "{\\'E}"


def test_cdl_bib_spelling_releases_surname_hold(bib):
    """TulvThom73: cited 'D M Thompson', Crossref only 'Thomson'. cdl.bib writes the same
    person 'D M Thomson' (editor, Smit88) and the cited spelling nowhere else: released
    by the cdl.bib rule and reported."""
    rec = check6(bib, "TulvThom73")
    assert rec["final_entry"]["author"] == "E Tulving and D M Thomson" and "author" not in rec["held"]
    assert any(f["code"] == "surname_corroborated" and "cdl.bib rule" in f["detail"] and "Smit88" in f["detail"]
               for f in rec["flags"])
    # negative control 1: without the corroborating entry the hold stands
    no_smit = {k: v for k, v in bib.items() if k != "Smit88"}
    rec = check6(no_smit, "TulvThom73", current=bib["TulvThom73"])
    assert "surname_single_source" in codes(rec) and "D M Thompson" in rec["final_entry"]["author"]
    # negative control 2: the cited spelling is also used for that person elsewhere: held
    both = dict(bib, ZzzzTest73={"ENTRYTYPE": "article", "ID": "ZzzzTest73", "author": "D M Thompson",
                                 "title": "x", "year": "1973"})
    rec = check6(both, "TulvThom73", current=bib["TulvThom73"])
    assert "surname_single_source" in codes(rec)


@pytest.mark.parametrize("key,cited", [("Trop86", "Y Trop"), ("CrosEtal93", "B Crossen"), ("ParkEtal13", "J Gosh")])
def test_one_host_respellings_without_house_spelling_stay_held(bib, key, cited):
    """Trope, Crosson and Ghosh rest on one host (the researcher's only quotes come from the
    same Crossref record the post-check fetched, or PMLR alone) and cdl.bib has no other
    entry for these people: held, as for FreeEtal03b's Crossref typo 'Jorsten' and
    RuggEtal96's Crossref-only 'Patching'."""
    rec = check6(bib, key)
    assert "surname_single_source" in codes(rec) and cited in pc.split_names(rec["final_entry"]["author"])


def test_doi_record_release_is_reported(bib):
    rec = check5(bib, "VanEEtal01")
    assert any(f["code"] == "surname_corroborated" and "DOI record rule" in f["detail"] for f in rec["flags"])


def test_january_cover_date_beats_crossref_print_year(bib):
    """WiggEtal99: PubMed DP '1999 Jan' (volume 37 issue 1), Crossref published-print
    1998-10. The cover year of a January issue stands; nothing is suggested."""
    rec = check6(bib, "WiggEtal99")
    assert "print_year_conflict" not in codes(rec) and "year" not in rec["suggestions"]
    assert any(f["code"] == "doi_record_conflict" and f["field"] == "year" for f in rec["flags"])
    # negative control: a March cover date is not explained by a late-printed January issue
    row = copy.deepcopy(ROWS6["WiggEtal99"])
    row["fields"]["year"]["evidence"][0]["quote"] = "DP  - 1999 Mar"
    rec = check6(bib, "WiggEtal99", row)
    assert "print_year_conflict" in codes(rec) and rec["suggestions"].get("year") == "1998"


def test_online_digitisation_year_in_notes_is_not_a_print_year(bib):
    """AdelEtal95: the notes say Karger's 2008 date is 'the online digitisation'; it is not
    a print date to suggest."""
    rec = check6(bib, "AdelEtal95")
    assert "print_year_conflict" not in codes(rec) and "year" not in rec["suggestions"]
    assert pc.print_years_in_notes("Crossref record lacks volume/print year (its 2008 date is the online "
                                   "digitisation)") == set()
    # negative controls: a print year next to an online year is still read
    assert pc.print_years_in_notes("Print issue 2012 (online 2011)") == {"2012"}
    row = copy.deepcopy(ROWS6["AdelEtal95"])
    row["notes"] = "The print issue is dated 2008."
    rec = check6(bib, "AdelEtal95", row)
    assert "print_year_conflict" in codes(rec) and rec["suggestions"].get("year") == "2008"


@pytest.mark.parametrize("key,journal", [("BousRosn70", "Psychonomic Science"), ("AlleGart68", "Psychonomic Science"),
                                         ("DanPoo06", "Physiological Reviews"), ("Jeff95", "Physiological Reviews")])
def test_journal_names_keep_their_identity(bib, key, journal):
    """Wave-6 review: the journal-key aliases 'psychonomic science' -> 'psychological
    science' and 'physiological reviews' -> 'physiological review' reverted the
    researchers' names (fixed in bibcheck/journal_key_overrides.json, 3eb4564)."""
    assert check6(bib, key)["final_entry"]["journal"] == journal
    # negative control: the other journal keeps its own name
    assert pc.H.format_journal_name("Psychological Science") == "Psychological Science"


# ---------------------------------------------------------------- wave-7/8/9 review regressions

WAVE7 = ROOT / "verification/research-2026-09-25/wave7"
WAVE8 = ROOT / "verification/research-2026-09-25/wave8"
WAVE9 = ROOT / "verification/research-2026-09-25/wave9"
ROWS7, REVIEW7, VALIDATION7 = load_wave(WAVE7)
ROWS8, REVIEW8, VALIDATION8 = load_wave(WAVE8)
ROWS9, REVIEW9, VALIDATION9 = load_wave(WAVE9)
WAVES789 = {"7": (ROWS7, REVIEW7, VALIDATION7), "8": (ROWS8, REVIEW8, VALIDATION8), "9": (ROWS9, REVIEW9, VALIDATION9)}


def checkw(bib, wave, key, row=None, review=False, current=None):
    rows_, review_, validation_ = WAVES789[wave]
    row = row or rows_[key]
    return pc.check_entry(row, current if current is not None else bib.get(key), bib, ctx_for(bib),
                          review=review_.get(key) if review else None, validation=validation_.get(key))


def sources(rec):
    return {c["field"]: c["source"] for c in rec["changes"]}


# --- wave 8, fix 1: the researcher's corrected chapter title wins over the cited chapter field

@pytest.mark.parametrize("key,title", [
    ("GoldEtal08", "Neural integrator models"),
    ("Howa08", "Memory: computational models"),
    ("BoraEtal05", "Oscillations in the basal ganglia: the good, the bad, and the unexpected"),
])
def test_researcher_corrected_chapter_title_wins(bib, key, title):
    """Wave-8 review: the @inbook -> @incollection move copied the CITED chapter field over
    the researcher's corrected title (GoldEtal08's draft 'Neural integrators: recurrent
    mechanisms and models'; BoraEtal05 lost the serial comma)."""
    rec = checkw(bib, "8", key)
    assert rec["final_entry"]["title"] == title and rec["final_entry"]["ENTRYTYPE"] == "incollection"
    assert "chapter" not in rec["final_entry"] and sources(rec)["title"] == "researcher"
    # negative control: without the researcher's title the cited chapter field is the title,
    # labelled as the post-check's move, not the researcher's value
    row = copy.deepcopy(ROWS8[key])
    row["fields"].pop("title")
    rec = checkw(bib, "8", key, row)
    assert pc.fold(rec["final_entry"]["title"]) == pc.fold(bib[key]["chapter"])
    assert sources(rec)["title"] == "postcheck"


# --- wave 8, fix 2: a chapter field holding the BOOK title; no_source rows never change

def test_no_source_and_ambiguous_rows_are_not_restructured(bib):
    """BairNoma78 (no_source) and Stey01 (ambiguous): the chapter field holds the book title;
    the move made the book the chapter. A no_source row now never changes; an ambiguous row's
    move is left for the user."""
    for wave, key in (("8", "BairNoma78"), ("8", "Stey01")):
        rec = checkw(bib, wave, key)
        assert rec["changes"] == [] and rec["removals"] == {}, key
        assert rec["final_entry"] == bib[key], key
        assert "chapter_move_held" in codes(rec)
    rec = checkw(bib, "8", "BairNoma78", review=True)  # the reviewer's own value is still applied
    assert sources(rec) == {"booktitle": "reviewer"} and rec["final_entry"]["title"] == "Multidimensional scaling"


def test_chapter_field_holding_the_book_title_becomes_booktitle(bib):
    """BairNoma78's researcher booktitle is the cited chapter field (the fields are swapped).
    On a verified row the chapter field becomes the booktitle and the title stays the
    chapter's, never the swap. Negative control: WardEtal09's chapter field is the chapter."""
    row = copy.deepcopy(ROWS8["BairNoma78"])
    row["verdict"] = "correction"
    rec = checkw(bib, "8", "BairNoma78", row)
    fin = rec["final_entry"]
    assert fin["title"] == "Multidimensional scaling" and fin["booktitle"] == "Fundamentals of Scaling and Psychophysics"
    assert fin["ENTRYTYPE"] == "incollection" and "chapter" not in fin and "booktitle" in rec["removals"]["chapter"]
    rec = check(bib, "WardEtal09")
    assert rec["final_entry"]["title"].startswith("The roles of short-term and long-term verbal memory")


# --- wave 8, fix 3: an ambiguous row's identity is one decision

def test_ambiguous_identity_changes_are_held_together(bib):
    """Ebbi85 (ambiguous) got the 1913 translation's title and DOI with the 1885 year. Now
    title and DOI are held together; with the review, the reviewer's year 1913 is held too."""
    rec = checkw(bib, "8", "Ebbi85")
    assert rec["changes"] == [] and {"title", "doi"} <= set(rec["held"])
    assert any(f["code"] == "ambiguous_identity_held" and f["action"] == "held" for f in rec["flags"])
    assert rec["suggestions"]["doi"] == "10.1037/10011-000"
    rec = checkw(bib, "8", "Ebbi85", review=True)
    assert {"title", "year"} <= set(rec["held"]) and rec["final_entry"]["year"] == "1885"
    assert "doi" not in changed(rec)  # the reviewer disagrees with the DOI: held by that rule
    assert rec["key_plan"]["action"] == "keep"
    # negative control: the same row as a correction applies title and DOI
    row = copy.deepcopy(ROWS8["Ebbi85"])
    row["verdict"] = "correction"
    ch = changed(checkw(bib, "8", "Ebbi85", row))
    assert ch.get("doi") == "10.1037/10011-000" and ch.get("title", "").startswith("Memory")


# --- wave 8, fix 4: duplicate resolution is deterministic and never circular

def test_duplicate_keeps_the_rule_conforming_key(bib):
    """Rugg00 and RuggAlla00 (same chapter; Rugg00 lacks K Allan) were each told to merge
    into the other. RuggAlla00 fits the ID rule for the corrected metadata and stays."""
    assert checkw(bib, "8", "RuggAlla00")["key_plan"]["action"] == "keep"
    assert checkw(bib, "8", "Rugg00")["key_plan"]["merge_into"] == "RuggAlla00"
    post, page, rules_only, merged = pc.run(WAVE8, write=False, offline=True)
    for recs in (rules_only, merged):
        dup = {k: r["key_plan"]["merge_into"] for k, r in recs.items() if r["key_plan"]["action"] == "duplicate"}
        assert dup.get("Rugg00") == "RuggAlla00" and "RuggAlla00" not in dup
        assert not any(dup.get(v) == k for k, v in dup.items())  # never A -> B and B -> A
    assert merged["RuggAlla00"]["key_plan"]["reviewer_agrees"] is True
    # negative control: with neither key fitting the rule the earlier key stays
    assert pc.keeper(["SmitJone01b", "SmitJone01"], "SmitJone01") == "SmitJone01"
    assert pc.keeper(["Rugg00", "RuggAlla00"], "RuggAlla00") == "RuggAlla00"
    assert pc.keeper(["Xa00", "Xb00"], None) == "Xa00"


def test_circular_merge_plans_are_broken():
    base = {"ENTRYTYPE": "incollection", "author": "M D Rugg and K Allan", "year": "2000",
            "title": "Event-related potential studies of memory"}
    recs = {"Rugg00": {"final_entry": dict(base), "flags": [],
                       "key_plan": {"current_key": "Rugg00", "action": "duplicate", "merge_into": "RuggAlla00"}},
            "RuggAlla00": {"final_entry": dict(base), "flags": [],
                           "key_plan": {"current_key": "RuggAlla00", "action": "duplicate", "merge_into": "Rugg00"}}}
    pc.break_merge_cycles(recs)
    assert recs["RuggAlla00"]["key_plan"]["action"] == "keep" and "merge_into" not in recs["RuggAlla00"]["key_plan"]
    assert recs["Rugg00"]["key_plan"]["merge_into"] == "RuggAlla00" and recs["RuggAlla00"]["flags"]


# --- wave 8, fix 5: rename only when a key-determining field changes

def test_off_rule_key_kept_without_key_field_change(bib):
    """ChatGPT -> Open23 was renamed only because the key never followed the rule."""
    rec = checkw(bib, "8", "ChatGPT", review=True)
    assert rec["key_plan"]["action"] == "keep" and "key_rename" not in codes(rec)
    assert rec["key_plan"]["reviewer_agrees"] is True
    # negative control: a corrected year (a key-determining field) renames it
    row = copy.deepcopy(ROWS8["ChatGPT"])
    row["fields"]["year"] = {"status": "corrected", "value": "2022", "evidence": [
        {"url": "http://web.archive.org/web/20230101000602/https://openai.com/blog/chatgpt/",
         "quote": "November 30, 2022"}]}
    rec = checkw(bib, "8", "ChatGPT", row)
    assert rec["key_plan"]["action"] == "rename" and rec["key_plan"]["new_key"] == "Open22"


# --- wave 8, fix 6: publisher and a held address are one decision

def test_publisher_with_held_address_is_one_decision(bib):
    """Herb34: the 1891 Langensalza publisher was applied next to the held 1834 address
    'Königsberg'. Rules alone: both are held, one flag; with the reviewer's address both apply.

    Since the user's country rule (2026-09-26) the real Herb34 address is no longer held:
    its quote check failed only on 'Germany', which no quote prints, so the address applies
    as 'Langensalza' and the publisher with it. The held-address case is kept below with a
    quote check that fails on the city itself."""
    rec = checkw(bib, "8", "Herb34")
    assert changed(rec)["address"] == "Langensalza" and "publisher" in changed(rec)
    assert "publisher_address_held" not in codes(rec) and "country_dropped" in codes(rec)
    validation = copy.deepcopy(VALIDATION8["Herb34"])
    validation["fields"]["address"]["value_missing_from_quotes"] = ["langensalza", "germany"]
    rec = pc.check_entry(ROWS8["Herb34"], bib["Herb34"], bib, ctx_for(bib), validation=validation)
    assert "publisher" not in changed(rec) and {"publisher", "address"} <= set(rec["held"])
    assert any(f["code"] == "publisher_address_held" and f["action"] == "held" for f in rec["flags"])
    rec = checkw(bib, "8", "Herb34", review=True)
    # the reviewer's 'Langensalza, Germany' loses the country no quote prints (user rule
    # 2026-09-26, cross-wave q-country: drop a country the source does not print)
    assert changed(rec)["address"] == "Langensalza" and "publisher" in changed(rec)
    assert "publisher_address_held" not in codes(rec)
    # negative controls: a rewording of the same publisher is not a different publisher
    assert not pc.different_publisher("Lawrence Erlbaum Associates", "Erlbaum")
    assert pc.different_publisher("Hermann Beyer \\& S{\\\"{o}}hne", "August Wilhelm Unzer")


# --- wave 8, fix 7: leading chapter number; the entry's own DOI

def test_leading_chapter_number_and_existing_doi(bib):
    """Sand80: Elsevier deposits '20 Stage Analysis of Reaction Processes'. Thor13 confirms
    its existing DOI: no 'DOI change dropped'."""
    rec = checkw(bib, "8", "Sand80")
    assert changed(rec).get("doi") == "10.1016/s0166-4115(08)61955-x" and "doi_title_mismatch" not in codes(rec)
    assert not pc.registry_title_matches("20 Stage Analysis of Reaction Processes", "Stage analysis of motor programs")
    assert not pc.registry_title_matches("3 Methods for testing serial memorization",
                                         "Two methods for testing serial memorization")
    rec = checkw(bib, "8", "Thor13")
    assert "doi_title_mismatch" not in codes(rec) and "doi" not in changed(rec) and rec["doi_status"] is None
    # negative control: the same DOI proposed for an entry without one is checked
    current = {k: v for k, v in bib["Thor13"].items() if k != "doi"}
    assert checkw(bib, "8", "Thor13", current=current)["doi_status"]["registered"] is True


# --- wave 7, fix 8: DOI titles with symbols, tags and generic column titles

@pytest.mark.parametrize("key,doi,code", [
    ("GusmEtal14", "10.2174/1874387001408010011", None),          # ®/™ vs \textregistered/\texttrademark
    ("HernEtal00", "10.1523/jneurosci.20-24-08987.2000", "doi_title_near"),  # D<sub>2</sub>Dopamine
    ("LismIdia95", "10.1126/science.7878473", None),              # '7 ± 2' vs '$7\pm2$'
    ("Rebe10", "10.1038/scientificamericanmind0510-70", "doi_generic_title"),  # 'Ask the Brains'
])
def test_wave7_correct_dois_kept(bib, key, doi, code):
    rec = checkw(bib, "7", key)
    assert changed(rec).get("doi") == doi and "doi_title_mismatch" not in codes(rec)
    if code:
        assert any(f["code"] == code and f["action"] == "applied" for f in rec["flags"])


def test_symbol_tag_and_generic_title_rules_are_narrow(bib):
    assert pc.fold("FitBit{\\textregistered} Ultra") == pc.fold("FitBit® Ultra") == "fitbit ultra"
    assert pc.fold("$7\\pm2$ memories") == pc.fold("7 ± 2 Memories") and pc.fold("$7\\pm2$") != pc.fold("72")
    assert pc.strip_tags("D<sub>2</sub>Dopamine") == "D 2 Dopamine"
    assert pc.fold("PLCβ1") == pc.fold("{PLC}$\\beta$1")
    rec = pc.doi_record("10.1038/scientificamericanmind0510-70")
    args = dict(volume="21", issue="2", pages="70", year="2010", journal="Scientific {American} Mind")
    assert pc.generic_item_agrees(rec, **args)
    for field, other in (("volume", "22"), ("issue", "3"), ("pages", "71"), ("year", "2011"), ("journal", "Nature")):
        assert not pc.generic_item_agrees(rec, **dict(args, **{field: other})), field
    rec = check(bib, "BoddEtal97")  # 'Correspondence', Crossref 1996 vs 1997: still another work
    assert "doi_title_mismatch" in codes(rec) and "doi" not in changed(rec)


# --- wave 7, fix 9: a contained type never loses its last venue

@pytest.mark.parametrize("key", ["GatyEtal16", "IsolEtal17", "LiEtal24a"])
def test_type_change_held_with_held_booktitle(bib, key):
    rec = checkw(bib, "7", key)
    fin = rec["final_entry"]
    assert fin["ENTRYTYPE"] == "article" and fin["journal"] == bib[key]["journal"] and not rec["removals"]
    assert any(f["code"] == "venue_held" and f["action"] == "held" for f in rec["flags"])
    # negative control: with the reviewer's booktitle the conversion goes through
    fin = checkw(bib, "7", key, review=True)["final_entry"]
    assert fin["ENTRYTYPE"] == "inproceedings" and fin["booktitle"] and "journal" not in fin


# --- wave 7, fix 10: author-deposited records are a second host

def test_deposited_record_releases_surname_hold(bib):
    """CaliVita05: Crossref and arXiv cs/0412098 both print Cilibrasi (key CiliVita07);
    ChanEtal20: DataCite and the Zenodo record print Geerligs."""
    rec = checkw(bib, "7", "CaliVita05")
    assert rec["final_entry"]["author"] == "R L Cilibrasi and P M B Vitanyi"
    assert rec["key_plan"]["new_key"] == "CiliVita07"
    assert any(f["code"] == "surname_corroborated" and "arXiv cs/0412098" in f["detail"] for f in rec["flags"])
    rec = checkw(bib, "7", "ChanEtal20")
    assert "L Geerligs" in pc.split_names(rec["final_entry"]["author"]) and "author" not in rec["held"]
    # negative controls: without the arXiv id, or without the Zenodo DOI, one host: held
    row = copy.deepcopy(ROWS7["CaliVita05"])
    row["notes"] = row["notes"].replace("(cs/0412098)", "")
    rec = checkw(bib, "7", "CaliVita05", row)
    assert "surname_single_source" in codes(rec) and rec["key_plan"]["new_key"] == "CaliVita07"
    row = copy.deepcopy(ROWS7["ChanEtal20"])
    row["fields"].pop("doi")
    rec = checkw(bib, "7", "ChanEtal20", row)
    assert "surname_single_source" in codes(rec) and "L Geerlings" in pc.split_names(rec["final_entry"]["author"])


# --- wave 7, fixes 11 and 12: another version named in the notes; junk Force field

@pytest.mark.parametrize("key", ["TsitEtal19", "LiEtal24b", "JainHuth18"])
def test_other_version_in_notes_needs_user(bib, key):
    rec = checkw(bib, "7", key)
    assert "other_version_named" in codes(rec)


def test_other_version_detection_is_conservative(bib):
    assert pc.other_version_named("No published version found in Crossref.") is None
    assert pc.other_version_named("Crossref has no is-preprint-of relation") is None
    assert pc.other_version_named("the 2025 re-depositions, not the published version; no DOI") is None
    assert pc.other_version_named("A bioRxiv preprint exists; the journal version is the one cited.") is None
    assert "other_version_named" not in codes(checkw(bib, "7", "XieEtal21"))
    post, page, rules_only, merged = pc.run(WAVE7, write=False, offline=True)
    needs = {p["key"]: p["needs_user"] for p in page}
    assert needs["TsitEtal19"] and needs["LiEtal24b"] and needs["JainHuth18"]


@pytest.mark.parametrize("wave,key", [("7", "AbdeEtal21"), ("7", "LiEtal24b"), ("7", "Amer23b"), ("8", "ChatGPT")])
def test_junk_force_field_removed(bib, wave, key):
    rec = checkw(bib, wave, key)
    assert bib[key].get("force") and "force" not in rec["final_entry"] and "force" in rec["removals"]


def test_no_force_removal_without_the_field(bib):
    rec = check(bib, "BlisColl93")
    assert "force" not in rec["removals"] and "force" not in bib["BlisColl93"]


# --- wave 9, fix 13: names left as the researcher wrote them

@pytest.mark.parametrize("key", ["CarvEtal22b", "TianEtal20b"])
def test_full_word_after_initials_never_becomes_an_initial(bib, key):
    """'A Quattrini Li' became 'A Q Li' (an added initial) under source 'researcher'."""
    rec = checkw(bib, "9", key)
    assert "A Quattrini Li" in pc.split_names(rec["final_entry"]["author"]) and "author" not in changed(rec)
    # a source that prints the compound as the family name braces it
    row = copy.deepcopy(ROWS9[key])
    row["fields"]["author"]["evidence"].append({"url": "https://example.org/x",
                                                "quote": '"given":"Alberto","family":"Quattrini Li"'})
    rec = checkw(bib, "9", key, row)
    assert "A {Quattrini Li}" in pc.split_names(rec["final_entry"]["author"])
    assert {c["field"]: c for c in rec["changes"]}["author"]["normalised_by"] == "postcheck"


def test_names_left_as_cited_are_not_rewritten(bib):
    """SingEtal24: the researcher left 'K Vasuden Alwala', 'K Hou U', 'V Satish Kumar' as cited."""
    rec = checkw(bib, "9", "SingEtal24")
    assert rec["final_entry"]["author"] == pc.canonical_fields(ROWS9["SingEtal24"]["fields"])["author"]["value"]
    # negative controls: full given names and a 'Family, Given' form are still abbreviated
    assert pc.normalise_name("John Paul Smith")[0] == "J P Smith"
    assert pc.normalise_name("Li, A Quattrini")[0] == "A Q Li"
    assert pc.normalise_name("A Quattrini Li")[0] == "A Quattrini Li"


# --- wave 9, fix 14: print-year false alarms

def test_print_year_false_alarms(bib):
    """ReccOKee89: 'pre-2000 SfN abstracts' is no print date. VaswEtal17 / LiuEtal18: the
    Curran reprint year of NeurIPS is not the paper's print year when the conference year
    is quoted."""
    rec = checkw(bib, "9", "ReccOKee89")
    assert "print_year_conflict" not in codes(rec) and "year" not in rec["suggestions"]
    assert pc.print_years_in_notes("pre-2000 SfN abstracts are only in print") == set()
    assert pc.print_years_in_notes("the volume was printed 2000") == {"2000"}  # negative control
    for key in ("VaswEtal17", "LiuEtal18"):
        rec = checkw(bib, "9", key)
        assert "print_year_conflict" not in codes(rec) and "year" not in rec["suggestions"], key
        assert "proceedings_print_year" in codes(rec)
    # negative control: without the quoted conference year the print year is still suggested
    row = copy.deepcopy(ROWS9["VaswEtal17"])
    row["fields"]["year"]["evidence"] = []
    rec = checkw(bib, "9", "VaswEtal17", row)
    assert "print_year_conflict" in codes(rec) and rec["suggestions"].get("year") == "2018"


# --- wave 9, fix 15: @conference without proceedings

def test_conference_without_proceedings_becomes_misc(bib):
    rec = checkw(bib, "9", "Laks01")
    assert rec["final_entry"]["ENTRYTYPE"] == "misc" and "conference_without_proceedings" in codes(rec)
    # negative control: a proceedings booktitle (NeurIPS) gives @inproceedings
    assert checkw(bib, "9", "VaswEtal17")["final_entry"]["ENTRYTYPE"] == "inproceedings"


def test_reviewer_remove_is_an_instruction_not_a_value(bib):
    """AbdeEtal21's reviewer suggested force = 'remove': the field goes, 'remove' is never a value."""
    rec = checkw(bib, "7", "AbdeEtal21", review=True)
    assert "force" not in rec["final_entry"] and all(c["proposed"] != "remove" for c in rec["changes"])
    assert pc.is_removal("remove") and pc.is_removal("(delete)") and not pc.is_removal("Removal of memories")


# ---------------------------------------------------------------- cross-wave user decisions (2026-09-26)

DECISIONS_DIR = ROOT / "verification/research-2026-09-25/crosswave/decisions"
RAW = {json.loads(p.read_text())["key"]: json.loads(p.read_text()) for p in DECISIONS_DIR.glob("*.json")}
APPLIED = pc.load_decisions()
ROWS1 = ROWS


def wave_rows(wave):
    return {"1": ROWS1, "2": ROWS2, "3": ROWS3, "7": ROWS7, "8": ROWS8, "9": ROWS9}[wave]


def checkd(bib, wave, key, row=None, review=True, current=None, decision=None):
    """A row of wave 1/2/3/7/8/9 through check_entry, with its review and validation."""
    rows_ = wave_rows(wave)
    review_, validation_ = {"1": (REVIEW, VALIDATION), "2": (REVIEW2, VALIDATION2), "3": (REVIEW3, VALIDATION3),
                            "7": (REVIEW7, VALIDATION7), "8": (REVIEW8, VALIDATION8), "9": (REVIEW9, VALIDATION9)}[wave]
    return pc.check_entry(row or rows_[key], current if current is not None else bib.get(key), bib, ctx_for(bib),
                          review=review_.get(key) if review else None, validation=validation_.get(key),
                          decision=decision)


_RUNS = {}


def wave_run(n):
    if n not in _RUNS:
        _RUNS[n] = pc.run(ROOT / f"verification/research-2026-09-25/wave{n}", write=False, offline=True)
    return _RUNS[n]


# --- rule 1: software / Zenodo releases cite the first version, its year, no version number

@pytest.mark.parametrize("given,expected", [
    ("{ContextLab}/efficient-learning-khan: {v1.0.0}", "{ContextLab}/efficient-learning-khan"),
    ("{ContextLab}/chatify: {v0.2.1}", "{ContextLab}/chatify"),
    ("ContextLab/chatify: v0.2.1 (August, 2023)", "ContextLab/chatify"),
    ("Brain Imaging Analysis Kit v0.2", "Brain Imaging Analysis Kit"),
    ("{naturalistic-data-analysis/naturalistic\\_data\\_analysis}: {Version 1.0}",
     "{naturalistic-data-analysis/naturalistic\\_data\\_analysis}"),
    ("{amueller/word\\_cloud}: {WordCloud} 1.5.0", "{amueller/word\\_cloud}: {WordCloud}"),
    ("{WordCloud} 1.5.0: a little word cloud generator in {Python}", "{WordCloud}: a little word cloud generator in {Python}"),
    # negative controls: not version numbers
    ("{Llama 3} model card", "{Llama 3} model card"),
    ("Llama 3", "Llama 3"),
    ("Frequency specific spatial interactions: {V1} alpha oscillations", "Frequency specific spatial interactions: {V1} alpha oscillations"),
    ("Data wrangler", "Data wrangler"),
    ("Brain imaging analysis kit", "Brain imaging analysis kit"),
])
def test_strip_version(given, expected):
    assert pc.strip_version(given) == expected


@pytest.mark.parametrize("doi,first,year", [
    ("10.5281/zenodo.8274025", "10.5281/zenodo.8152316", "2023"),   # chatify v0.2.1 -> v0.1.0
    ("10.5281/zenodo.1322068", "10.5281/zenodo.49907", "2016"),     # word_cloud 1.5.0 (2018) -> 1.2.1 (2016)
    ("10.5281/zenodo.3937848", "10.5281/zenodo.3937849", "2020"),   # a concept DOI -> its only version
    ("10.5281/zenodo.59780", "10.5281/zenodo.59780", "2016"),       # BrainIAK v0.2: already the first
])
def test_zenodo_first_version_live(doi, first, year):
    got = pc.zenodo_first_version(doi, pc.http_get)
    assert got.get("error") is None and got["doi"] == first and got["year"] == year
    assert pc.zenodo_first_version("10.1038/361031a0", pc.http_get).get("error")  # not a Zenodo DOI


def test_software_first_version_rows(bib):
    """CapoEtal17 (the cross-wave question): the v0.2 DOI is no longer held as a part-number
    mismatch, its year 2016 is the first version's, key CapoEtal16. MuelEtal18: the 1.5.0 DOI
    becomes the first version 1.2.1 (2016), key MuelEtal16, no version in the title, and
    the first version's different creator list is flagged, never applied."""
    rec = checkw(bib, "8", "CapoEtal17")
    assert changed(rec)["doi"] == "10.5281/zenodo.59780" and "doi_title_part_number" not in codes(rec)
    assert rec["final_entry"]["year"] == "2016" and rec["key_plan"]["new_key"] == "CapoEtal16"
    rec = checkw(bib, "7", "MuelEtal18")
    ch = changed(rec)
    assert ch["doi"] == "10.5281/zenodo.49907" and ch["year"] == "2016" and "1.5.0" not in ch["title"]
    assert rec["key_plan"]["new_key"] == "MuelEtal16" and "software_first_version_authors" in codes(rec)
    assert rec["final_entry"]["author"].startswith("A Mueller and J-C Fillion-Robin and R Boidol")  # not 1.2.1's list
    rec = checkd(bib, "1", "MannEtal23b")
    assert changed(rec)["doi"] == "10.5281/zenodo.8152316" and rec["final_entry"]["year"] == "2023"
    assert changed(rec)["title"] == "{ContextLab}/chatify"
    rec = check(bib, "FitzEtal25")
    assert changed(rec)["title"] == "{ContextLab}/efficient-learning-khan" and "doi" not in changed(rec)
    rec = checkw(bib, "7", "ChanEtal20")
    assert changed(rec)["doi"] == "10.5281/zenodo.3937849"


def test_software_rule_is_narrow(bib):
    """Negative controls: a manual or an article with 'version' in its title is not software
    (Stan13, Wils88), and a version field goes only from software."""
    assert "software_version_removed" not in codes(checkw(bib, "9", "Stan13"))
    assert "version 2" in checkd(bib, "2", "Wils88")["final_entry"]["title"]
    assert not pc.software_entry({"ENTRYTYPE": "manual", "title": "Stan, version 2.1"})
    assert pc.software_entry({"ENTRYTYPE": "misc", "howpublished": "\\url{https://github.com/x/y}"})
    row = copy.deepcopy(ROWS8["CapoEtal17"])
    rec = checkw(bib, "8", "CapoEtal17", row=row, current=dict(bib["CapoEtal17"], version="0.2"))
    assert "version" not in rec["final_entry"] and "version" in rec["removals"]
    assert not {"software_first_version", "software_version_removed"} & codes(check(bib, "BlisColl93"))


# --- rule 2: a country no quote prints is dropped from the address

def test_country_not_printed_is_dropped(bib):
    """Herb34 (reviewer 'Langensalza, Germany') and BuzsEtal94 ('Heidelberg, Germany', held
    only because the quotes do not print Germany: released without it)."""
    rec = checkw(bib, "8", "Herb34", review=True)
    assert changed(rec)["address"] == "Langensalza" and "country_dropped" in codes(rec)
    rec = checkw(bib, "8", "BuzsEtal94")
    assert rec["final_entry"]["address"] == "Heidelberg" and "address" not in rec["held"]
    assert "quote_check_failed" not in {f["code"] for f in rec["flags"] if f["field"] == "address"}


def test_country_printed_is_kept(bib):
    """Negative controls: the quote prints the country (Rayp68 'Horn, Austria' -> {AT};
    Addi02 'Bristol, UK'; Smit88 'Chichester [England]'); a US state is not a country."""
    assert check(bib, "Rayp68")["final_entry"]["address"] == "Horn, {AT}"
    assert checkw(bib, "7", "Addi02")["final_entry"]["address"] == "Bristol, {UK}"
    assert checkw(bib, "8", "Smit88")["final_entry"]["address"] == "Chichester, {UK}"
    assert pc.address_country("Bloomington, {IN}") is None and pc.address_country("New Orleans, {LA}") is None
    assert pc.address_country("Langensalza, Germany")[:2] == ("Langensalza", "Germany")
    assert pc.address_country("Germany")[:2] == ("", "Germany")


def test_country_only_address_is_left_out(bib):
    row = copy.deepcopy(ROWS8["Ripl81"])
    row["fields"]["address"] = {"status": "corrected", "value": "Germany",
                                "evidence": [{"url": "https://example.org", "quote": "Berlin"}]}
    rec = checkw(bib, "8", "Ripl81", row=row)
    assert "address" not in rec["final_entry"] and "country_dropped" in codes(rec)
    # the house address key adds a country ('Leipzig' -> 'Leipzig, Germany'): not when unprinted
    row["fields"]["address"] = {"status": "corrected", "value": "Leipzig",
                                "evidence": [{"url": "https://example.org", "quote": "Leipzig"}]}
    assert checkw(bib, "8", "Ripl81", row=row)["final_entry"]["address"] == "Leipzig"
    row["fields"]["address"]["evidence"][0]["quote"] = "Leipzig, Germany"
    assert checkw(bib, "8", "Ripl81", row=row)["final_entry"]["address"] == "Leipzig, Germany"


# --- rule 3: per-entry decisions (crosswave/applied-decisions.json), source 'user'

def test_applied_decisions_match_the_raw_answers():
    """Every raw answer on the cross-wave page is in applied-decisions.json as the user gave it."""
    for k, d in RAW.items():
        if k.startswith("a-"):
            e = APPLIED[d["entry"]]
            if d["verdict"] == "correct":
                assert e.get("remove_entry") == "conference abstract" and not e.get("not_abstract"), k
            else:
                assert d["verdict"] == "wrong" and e.get("not_abstract") and not e.get("remove_entry"), k
        elif k.startswith("dup-"):
            gone, keep = [x.strip() for x in d["entry"].split("\u2192")]
            assert APPLIED[gone]["merge_into"] == keep and gone in APPLIED[keep]["keeper_of"], k
    assert {k for k, e in APPLIED.items() if e.get("not_abstract")} == \
        {"BeckEtal09", "CronEtal94", "MannEtal97", "PailEtal00", "SpieEtal18", "TongEtal95"}
    assert APPLIED["Shim94"]["key"] == "Shim95b" and APPLIED["Shim95"]["key"] == "Shim95a"
    assert APPLIED["OGra11"]["key"] == "OGra08" and APPLIED["OGra11"]["set"]["year"]["value"] == "2008"
    assert APPLIED["KahaEtal08a"]["drop_suffix_if_only"] is True


def test_ebbinghaus_is_the_1885_original(bib):
    """Ebbi85: the user chose the 1885 German original; the 1913 translation's title, DOI
    and year are withdrawn, the original's title, publisher and place are source 'user'
    with quotes checked at archive.org; the verdict is resolved."""
    rec = checkd(bib, "8", "Ebbi85", decision=APPLIED["Ebbi85"])
    fin = rec["final_entry"]
    assert pc.fold(fin["title"]) == "uber das gedachtnis untersuchungen zur experimentellen psychologie" and fin["year"] == "1885" and "doi" not in fin and fin["address"] == "Leipzig"
    assert fin["publisher"] == "Duncker \\& Humblot"
    assert {c["field"]: c["source"] for c in rec["changes"]} == {"title": "user", "publisher": "user", "address": "user"}
    assert "user_evidence_unverified" not in codes(rec) and "needs_user" not in codes(rec)
    assert not any(f["action"] == "held" for f in rec["flags"])
    # negative control: without the decision the identity stays held for the user
    rec = checkd(bib, "8", "Ebbi85")
    assert "ambiguous_identity_held" in codes(rec) and "title" not in changed(rec)
    # a wrong quote would be reported
    bad = copy.deepcopy(APPLIED["Ebbi85"])
    bad["set"]["title"]["evidence"][0]["quote"] = "Memory: a contribution to experimental psychology"
    assert "user_evidence_unverified" in codes(checkd(bib, "8", "Ebbi85", decision=bad))


def test_key_decisions_on_the_wave_pages():
    """Shim94 -> Shim95b (wave 8) and Shim95 -> Shim95a (wave 2), OGra11 -> OGra08 (wave 9),
    BenaEtal04's booktitle; decisions never reach the rules-alone pass."""
    post, page, rules_only, merged = wave_run(8)
    assert merged["Shim94"]["key_plan"]["new_key"] == "Shim95b"
    ch = {c["field"]: c for c in merged["BenaEtal04"]["changes"]}
    assert ch["booktitle"]["proposed"] == "{Youmans} Neurological Surgery" and ch["booktitle"]["source"] == "user"
    assert "user_decision" not in {f["code"] for r in rules_only.values() for f in r["flags"]}
    post, page, rules_only, merged = wave_run(2)
    plan = merged["Shim95"]["key_plan"]
    assert plan["action"] == "rename" and plan["new_key"] == "Shim95a"
    assert rules_only["Shim95"]["key_plan"]["action"] == "keep"  # negative control
    post, page, rules_only, merged = wave_run(9)
    assert merged["OGra11"]["key_plan"]["new_key"] == "OGra08" and merged["OGra11"]["final_entry"]["year"] == "2008"
    assert {c["field"]: c["source"] for c in merged["OGra11"]["changes"]}["year"] == "user"


def test_approved_duplicates_agree_with_the_post_check_plans():
    """The 9 approved duplicates: the post-check's own plan already merges each into the
    keeper the user approved (no override needed)."""
    merges = {k: e["merge_into"] for k, e in APPLIED.items() if e.get("merge_into")}
    assert len(merges) == 9
    seen = 0
    for n in range(1, 10):
        post, page, rules_only, merged = wave_run(n)
        for k, into in merges.items():
            if k in merged:
                seen += 1
                assert rules_only[k]["key_plan"].get("merge_into") == into, k
                assert merged[k]["key_plan"]["merge_into"] == into and "the user's decision wins" not in \
                    " ".join(f["detail"] for f in merged[k]["flags"]), k
    assert seen == 9


def test_kahana_keeper_keeps_its_suffix_while_another_kahaetal08_exists(bib):
    """KahaEtal08b merges into KahaEtal08a; KahaEtal08c (a different 2008 paper) is in HEAD,
    so KahaEtal08a stays. Negative control: without KahaEtal08c it becomes KahaEtal08."""
    assert "KahaEtal08c" in bib
    post, page, rules_only, merged = wave_run(8)
    assert merged["KahaEtal08a"]["key_plan"]["action"] == "keep"
    assert merged["KahaEtal08a"]["key_plan"]["suffix_kept"] == ["KahaEtal08c"]
    assert merged["KahaEtal08b"]["key_plan"]["merge_into"] == "KahaEtal08a"
    recs = {"KahaEtal08a": copy.deepcopy(merged["KahaEtal08a"])}
    recs["KahaEtal08a"]["key_plan"] = {"current_key": "KahaEtal08a", "action": "keep"}
    pc.apply_entry_decisions(recs, APPLIED, {k: v for k, v in bib.items() if k != "KahaEtal08c"}, set())
    assert recs["KahaEtal08a"]["key_plan"]["new_key"] == "KahaEtal08"


def test_abstract_decisions_on_the_wave_pages():
    """The six real articles carry no removal; JohnRedi07b (wave 3) is marked for removal."""
    flagged = {}
    for n in range(1, 10):
        post, page, rules_only, merged = wave_run(n)
        for p in page:
            flagged[p["key"]] = p
    for k in ("BeckEtal09", "CronEtal94", "MannEtal97", "PailEtal00", "SpieEtal18", "TongEtal95"):
        assert not flagged[k]["remove_entry"] and any("not a conference abstract" in u for u in flagged[k]["user_decisions"]), k
    assert flagged["JohnRedi07b"]["remove_entry"] == "conference abstract"
    # the removal flag must not feed the cross-wave page's abstract finder (build_crosswave.py
    # ABSTRACT_RX) its own decision back as new evidence
    import re
    rx = re.compile(r"\b(?:conference|meeting|poster)(?: talk/| |-)abstract", re.I)
    for p in flagged.values():
        if p["remove_entry"]:
            assert not any(rx.search(u) for u in p["user_decisions"]), p["key"]
    assert sum(bool(p["remove_entry"]) for p in flagged.values()) == \
        sum(1 for k, e in APPLIED.items() if e.get("remove_entry") and k in flagged)


# --- rule 4: the removal list

def test_removals_file_is_the_approved_abstracts(bib):
    committed = json.loads((ROOT / "verification/research-2026-09-25/crosswave/removals.json").read_text())
    built = pc.build_removals(bib=bib)
    assert committed["entries"] == built and committed["count"] == len(built) == 45
    keys = {e["key"] for e in built}
    assert "JohnRedi07b" in keys and all(e["in_head_bib"] for e in built)
    assert not keys & {"BeckEtal09", "CronEtal94", "MannEtal97", "PailEtal00", "SpieEtal18", "TongEtal95"}
    assert keys == {k for k, e in APPLIED.items() if e.get("remove_entry")}
