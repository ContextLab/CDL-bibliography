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


# The bibliography as committed before wave 1 was applied (a9c7f16). The rows, reviews and
# decisions under test were made against it; reading HEAD instead would break these tests
# every time an approved batch is committed.
FROZEN_BIB = str(ROOT / "tests/fixtures/cdl-prewave1-2026-09-26.bib")
# verification/key-renames.json as committed in 3eb26c9 (2026-09-30): the log keeps growing
# (the KahaEtal08a/b swap and MurdVomS67 -> MurdvomS67 were added that day), so tests read
# this frozen copy, never the live file.
LOGGED_RENAMES = pc.renamed_away(ROOT / "tests/fixtures/key-renames-2026-09-30.json")


@pytest.fixture(scope="module")
def bib():
    return pc.load_bib(FROZEN_BIB)


def ctx_for(bib):
    return {"doi": pc.doi_record, "cities": pc.city_states(bib), "taken": set(), "reserved": dict(LOGGED_RENAMES),
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
    assert "surname_mismatch" in codes(rec)
    # the hold keeps the cited name: the respelled surname is not in the final entry
    assert rec["final_entry"]["author"] == "J R Manning and H Menjunatha and K Kording"
    assert "surname_mismatch" not in codes(check(bib, "DawKenj06"))  # PubMed + Crossref


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
    post, page, rules_only, merged = pc.run(WAVE, write=False, bib=FROZEN_BIB, renames=dict(LOGGED_RENAMES))
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
    post, page, rules_only, merged = pc.run(WAVE2, write=False, bib=FROZEN_BIB, renames=dict(LOGGED_RENAMES))
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
        post, page, rules_only, merged = offline_run(folder)
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
                    assert "surname_mismatch" in codes(rec), k
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


# User rule 2026-09-30 (verification/2026-09-29-user-review/CONFIRM.md, answer 5): "one
# source is sufficient; manual entry is the weakest part. notify user if mismatch is found
# and ask how they want to resolve it". A surname respelling is held for the user whatever
# the number of hosts, cdl.bib's other entries or the (agent) reviewer say; these tests
# used to assert that such evidence released it.

def test_single_source_surname_hold_keeps_cited_name(bib):
    rec = check3(bib, "FreeEtal03b")  # Crossref deposit typo 'Jorsten'; cited 'Jornten'
    assert "surname_mismatch" in codes(rec)
    names = pc.split_names(rec["final_entry"]["author"])
    assert names[2] == pc.split_names(bib["FreeEtal03b"]["author"])[2] and "Jorsten" not in rec["final_entry"]["author"]
    # the reviewer's corrected surname is an agent's value, not the user's: held too,
    # with both spellings named
    rec = check3(bib, "FreeEtal03b", review=True)
    assert pc.split_names(rec["final_entry"]["author"])[2] == "R Jornten"
    (f,) = [f for f in rec["flags"] if f["code"] == "surname_mismatch"]
    assert f["action"] == "held" and "'R Jornten'" in f["detail"] and "rnsten'" in f["detail"]
    # RuggEtal96: cited 'Patchin', Crossref only 'Patching'; the reviewer's confirmation
    # no longer releases it
    rec = check3(bib, "RuggEtal96", review=True)
    assert "Patching" not in rec["final_entry"]["author"] and "author" in rec["held"]
    assert any(f["code"] == "surname_mismatch" and f["action"] == "held" for f in rec["flags"])
    assert not any(f["code"] == "surname_mismatch" and f["action"] == "applied" for f in rec["flags"])
    rules_alone = check3(bib, "RuggEtal96")
    assert "author" in rules_alone["held"] and "Patching" not in rules_alone["final_entry"]["author"]
    # Brig12: the frozen bibliography cites 'F D Brigard' (surname Brigard); the researcher's
    # 'F {De Brigard}' (Crossref and PubMed) changes the surname. Two hosts used to release
    # it; now it is held for the user and the cited name is kept.
    rec = check3(bib, "Brig12")
    assert bib["Brig12"]["author"] == "F D Brigard"
    assert rec["final_entry"]["author"] == "F D Brigard" and "surname_mismatch" in codes(rec)
    assert "surname_corroborated" not in codes(rec)
    # negative control: the same particle braced without a change of letters is no mismatch
    rec = check3(dict(bib, Brig12=dict(bib["Brig12"], author="F De Brigard")), "Brig12")
    assert rec["final_entry"]["author"] == "F {De Brigard}" and "surname_mismatch" not in codes(rec)


@pytest.mark.parametrize("folder,findings", [(WAVE3, 8)])
def test_wave3_review_resolution(folder, findings):
    post, page, rules_only, merged = offline_run(folder)
    res = post["review_resolution"]
    # FreeEtal03b: the reviewer's surname 'J{\\"o}rnsten' for the cited 'Jornten' is a
    # surname mismatch the user decides (user rule 2026-09-30), so it stays unresolved.
    assert res["findings"] == findings and res["unresolved"] == ["FreeEtal03b"], res["unresolved"]
    assert not any(f["code"] == "initials_from_source" for r in merged.values() for f in r["flags"])


def test_surname_hold_keeps_the_whole_cited_name(bib):
    """AguiEtal96: cited 'M D Esposito', researcher 'M D'Esposito'. The hold keeps the
    cited name whole, so no initial is dropped ('M Esposito' was wrong). Neither the
    proposed DOI's Crossref record (a second host) nor cdl.bib's other entries writing
    'M D'Esposito' release it any more (user rule 2026-09-30)."""
    row = copy.deepcopy(ROWS2["AguiEtal96"])
    row["fields"] = {k: v for k, v in row["fields"].items() if k.lower() != "doi"}
    for rec in (check2(bib, "AguiEtal96", row), check2(bib, "AguiEtal96")):
        assert "surname_mismatch" in codes(rec) and "surname_corroborated" not in codes(rec)
        assert pc.split_names(rec["final_entry"]["author"])[-1] == "M D Esposito"
        (f,) = [f for f in rec["flags"] if f["code"] == "surname_mismatch"]
        assert "'M D Esposito'" in f["detail"] and "M D'Esposito" in f["detail"]
    # the DOI record is still named as a host that prints the new spelling
    assert "api.crossref.org" in f["detail"]


@pytest.mark.parametrize("wave,key", [("3", "BasaEtal92")])
def test_brace_or_spacing_fix_is_not_a_respelling(bib, wave, key):
    """{Schurman n} -> Sch{\\"u}rmann is a format fix of the same letters, not a surname
    respelling: applied, no hold."""
    rec = (check2 if wave == "2" else check3)(bib, key)
    assert "surname_mismatch" not in codes(rec)
    assert "author" not in rec["held"] and "author" in changed(rec)


def test_format_fix_applies_beside_a_held_respelling(bib):
    """KatzEtal89: the broken L{\\\\"u}ders is a format fix and is applied, but the same row
    respells the cited 'A K Kongy' as 'A K Kong' (PubMed and Europe PMC). That respelling
    used to be released by its two hosts; it is now held for the user (user rule
    2026-09-30) and the cited name is kept."""
    rec = check3(bib, "KatzEtal89")
    assert "author" in changed(rec)
    names = pc.split_names(rec["final_entry"]["author"])
    assert names[2] == "A K Kongy" and names[-1] == 'H L{\\"u}ders'
    (f,) = [f for f in rec["flags"] if f["code"] == "surname_mismatch"]
    assert f["action"] == "held" and "'A K Kong'" in f["detail"] and "www.ebi.ac.uk" in f["detail"]


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
    assert "surname_mismatch" not in codes(rec) and "author" not in rec["held"]
    # negative controls: a first-token 'Van' is a given name; a real respelling is held and
    # keeps the cited name in house form, never 'B A L D Leone'
    assert pc.normalise_names("Van Morrison")[0] == "V Morrison"
    row = copy.deepcopy(ROWS4["VogtEtal14"])
    row["fields"]["author"]["value"] = "D Vogt and A B Fox and B A L {Di Leoni}"
    rec = check4(bib, "VogtEtal14", row)
    assert "surname_mismatch" in codes(rec)
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


@pytest.mark.parametrize("key,name,cited", [("VanEEtal01", "J Dickson", "J Dickenson"),
                                           ("ToluEtal12", "J-P Changeux", "J P Cangeux")])
def test_doi_record_is_no_longer_a_second_surname_host(bib, key, name, cited):
    """VanEEtal01, ToluEtal12: the kept DOI's Crossref record used to be the second host
    that released the respelling. Under the user rule of 2026-09-30 it is held with and
    without the DOI, the cited name kept and both spellings named."""
    rec = check5(bib, key)
    assert cited in pc.split_names(rec["final_entry"]["author"]) and name not in pc.split_names(rec["final_entry"]["author"])
    (f,) = [f for f in rec["flags"] if f["code"] == "surname_mismatch"]
    assert f["action"] == "held" and repr(cited) in f["detail"] and repr(name) in f["detail"]
    row = copy.deepcopy(ROWS5[key])  # without the DOI record: held the same way
    row["fields"] = {k: v for k, v in row["fields"].items() if k.lower() != "doi"}
    current = dict(bib[key])
    current.pop("doi", None)
    rec = pc.check_entry(row, current, bib, ctx_for(bib), validation=VALIDATION5.get(key))
    assert "surname_mismatch" in codes(rec) and name not in pc.split_names(rec["final_entry"]["author"])


@pytest.mark.parametrize("key,name", [("KrauEtal13", "R J Robinson"), ("ChamEtal03", "A A Artigas"),
                                      ("WagnEtal01", "E J Paré-Blagoev")])
def test_format_damage_is_not_a_respelling(bib, key, name):
    """A mangled suffix ('{Robinson I I }'), a broken split ('{and Artigas}') and a
    restored accented letter ('Par-Blagoev') are not surname respellings."""
    row = copy.deepcopy(ROWS5[key])
    row["fields"] = {k: v for k, v in row["fields"].items() if k.lower() != "doi"}  # no registry host
    rec = check5(bib, key, row)
    assert name in pc.split_names(rec["final_entry"]["author"]) and "surname_mismatch" not in codes(rec)


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
    assert "surname_mismatch" not in codes(rec) and "author" not in rec["held"]
    assert pc.split_names(rec["final_entry"]["author"])[-1] == "J-A Meyer"
    assert pc.normalise_name("J.-A. Meyer")[0] == "J-A Meyer"
    assert pc.given_initials("Jean-{A}rcady") == "J-A"
    # negative controls: separate dotted initials stay separate; accent macros keep their letter
    assert pc.normalise_name("J. A. Meyer")[0] == "J A Meyer"
    assert pc.given_initials("{\\'E}mile") == "{\\'E}"


def test_cdl_bib_spelling_does_not_release_a_surname_mismatch(bib):
    """TulvThom73: cited 'D M Thompson', Crossref only 'Thomson'. cdl.bib writes the same
    person 'D M Thomson' (editor, Smit88); that used to release the respelling (Claude's
    cdl.bib rule). Now it is held with or without Smit88 (user rule 2026-09-30)."""
    no_smit = {k: v for k, v in bib.items() if k != "Smit88"}
    both = dict(bib, ZzzzTest73={"ENTRYTYPE": "article", "ID": "ZzzzTest73", "author": "D M Thompson",
                                 "title": "x", "year": "1973"})
    for library in (bib, no_smit, both):
        rec = check6(library, "TulvThom73", current=bib["TulvThom73"])
        assert "surname_mismatch" in codes(rec) and "surname_corroborated" not in codes(rec)
        assert rec["final_entry"]["author"] == "E Tulving and D M Thompson" and "author" in rec["held"]


@pytest.mark.parametrize("key,cited", [("Trop86", "Y Trop"), ("CrosEtal93", "B Crossen"), ("ParkEtal13", "J Gosh")])
def test_one_host_respellings_without_house_spelling_stay_held(bib, key, cited):
    """Trope, Crosson and Ghosh rest on one host (the researcher's only quotes come from the
    same Crossref record the post-check fetched, or PMLR alone) and cdl.bib has no other
    entry for these people: held, as for FreeEtal03b's Crossref typo 'Jorsten' and
    RuggEtal96's Crossref-only 'Patching'."""
    rec = check6(bib, key)
    assert "surname_mismatch" in codes(rec) and cited in pc.split_names(rec["final_entry"]["author"])


def test_surname_mismatch_names_both_spellings_and_hosts(bib):
    rec = check5(bib, "VanEEtal01")
    (f,) = [f for f in rec["flags"] if f["code"] == "surname_mismatch"]
    assert "'J Dickenson'" in f["detail"] and "'J Dickson'" in f["detail"]
    assert "api.crossref.org" in f["detail"] and "pubmed.ncbi.nlm.nih.gov" in f["detail"]
    assert "keep 'J Dickenson' or change to 'J Dickson'?" in f["detail"]


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
    post, page, rules_only, merged = offline_run(WAVE8)
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

def test_deposited_record_does_not_release_a_surname_mismatch(bib):
    """CaliVita05: Crossref and arXiv cs/0412098 both print Cilibrasi; ChanEtal20: DataCite
    and the Zenodo record print Geerligs. Author-deposited records used to release these
    respellings (wave-7 fix 10); under the user rule of 2026-09-30 they are held, with and
    without the arXiv id or Zenodo DOI, and the cited names are kept."""
    rec = checkw(bib, "7", "CaliVita05")
    assert rec["final_entry"]["author"] == "R L Calibrasi and P M B Vitanyi"
    assert rec["key_plan"]["new_key"] == "CaliVita07" and "surname_mismatch" in codes(rec)
    assert "surname_corroborated" not in codes(rec)
    rec = checkw(bib, "7", "ChanEtal20")
    assert "L Geerlings" in pc.split_names(rec["final_entry"]["author"]) and "author" in rec["held"]
    row = copy.deepcopy(ROWS7["CaliVita05"])
    row["notes"] = row["notes"].replace("(cs/0412098)", "")
    rec = checkw(bib, "7", "CaliVita05", row)
    assert "surname_mismatch" in codes(rec) and rec["key_plan"]["new_key"] == "CaliVita07"
    row = copy.deepcopy(ROWS7["ChanEtal20"])
    row["fields"].pop("doi")
    rec = checkw(bib, "7", "ChanEtal20", row)
    assert "surname_mismatch" in codes(rec) and "L Geerlings" in pc.split_names(rec["final_entry"]["author"])


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
    post, page, rules_only, merged = offline_run(WAVE7)
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
# The registry answers (doi.org handles/RA, Crossref, DataCite) the offline wave runs read,
# frozen on 2026-09-30 from the post-check cache (4540 responses). The runs used to read the
# git-ignored .bibcheck/research-postcheck/ itself, so their result depended on what the
# working tree had cached: in a clean clone a test passed in the suite (earlier tests had
# fetched the DOIs it needs) and failed on its own (WhitEtal96 -> WitmEtal96 needs
# 10.1006/ijhc.1996.0060).
WAVE_CACHE = ROOT / "tests/fixtures/postcheck-wave-cache-2026-09-30.jsonl.gz"
_WAVE_CACHE_DIR = None


def wave_cache_dir():
    """A temporary post-check cache holding exactly the frozen responses (created once)."""
    global _WAVE_CACHE_DIR
    if _WAVE_CACHE_DIR is None:
        import atexit
        import gzip
        import hashlib
        import shutil
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="postcheck-wave-cache-"))
        atexit.register(shutil.rmtree, d, True)
        with gzip.open(WAVE_CACHE, "rt") as f:
            for line in f:
                r = json.loads(line)
                (d / (hashlib.sha256(r["url"].encode()).hexdigest() + ".json")).write_text(json.dumps(r))
        (d / "validator").mkdir()
        _WAVE_CACHE_DIR = d
    return _WAVE_CACHE_DIR


def offline_run(folder, **kw):
    """pc.run on a wave folder, offline, against the frozen bibliography, key renames and
    registry answers only; nothing it reads depends on the working tree or on other tests."""
    d = wave_cache_dir()
    V = pc.validator()
    saved = pc.CACHE, V.CACHE
    pc.CACHE, V.CACHE = d, d / "validator"
    try:
        return pc.run(folder, write=False, offline=True, bib=FROZEN_BIB, renames=dict(LOGGED_RENAMES), **kw)
    finally:
        pc.CACHE, V.CACHE = saved


def wave_run(n):
    if n not in _RUNS:
        _RUNS[n] = offline_run(ROOT / f"verification/research-2026-09-25/wave{n}")
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
    # the formatter never adds a country (user, 2026-09-26; e920c54): a quote that prints
    # 'Leipzig, Germany' leaves the researcher's 'Leipzig' as it is
    row["fields"]["address"]["evidence"][0]["quote"] = "Leipzig, Germany"
    assert checkw(bib, "8", "Ripl81", row=row)["final_entry"]["address"] == "Leipzig"


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


# ---------------------------------------------------------------- resolution decisions (2026-09-26)
# Real rows from verification/resolution-2026-09-26/batch-NN.json, frozen here (the batches
# are still being reconciled; a test must not break when a row is corrected there).

RESOLUTION = json.loads(r'''{
 "BairNoma78": {
  "key": "BairNoma78",
  "decision": "apply",
  "entrytype": "book",
  "set": {
   "title": {
    "value": "Fundamentals of scaling and psychophysics",
    "url": "http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=4&recordSchema=marcxml&query=dc.title%3D%22fundamentals%20of%20scaling%20and%20psychophysics%22",
    "quote": "<subfield code=\"a\">Fundamentals of scaling and psychophysics /</subfield>"
   },
   "address": {
    "value": "New York, {NY}",
    "url": "http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=4&recordSchema=marcxml&query=dc.title%3D%22fundamentals%20of%20scaling%20and%20psychophysics%22",
    "quote": "<subfield code=\"a\">New York :</subfield>"
   }
  },
  "withdraw": [
   "booktitle"
  ],
  "remove": [
   "chapter",
   "pages"
  ],
  "notes": "The authored book is confirmed (LoC 78006011, Wiley, New York, c1978). The cited chapter 'Multidimensional scaling' pp. 177-205 has no source: archive.org copy is lending-only, HathiTrust search-only returns no snippets, Scholar/Open Library/Crossref have no contents. Cited as the whole book with the unconfirmable chapter and pages removed.",
  "questions": [
   "When a chapter of an authored (single-work) book cannot be confirmed but the book is, should the entry cite the whole book (chapter and pages removed) or be dropped?"
  ],
  "_batch": "batch-23"
 },
 "Howa08": {
  "key": "Howa08",
  "decision": "apply",
  "new_key": "Howa09",
  "entrytype": "incollection",
  "set": {
   "title": {
    "value": "Memory: computational models",
    "url": "https://api.crossref.org/works/10.1016/b978-008045046-9.00754-3",
    "quote": "\"title\":[\"Memory: Computational Models\"]"
   },
   "year": {
    "value": "2009",
    "url": "https://api.crossref.org/works/10.1016/b978-008045046-9.00754-3",
    "quote": "\"published-print\":{\"date-parts\":[[2009]]}"
   }
  },
  "notes": "Crossref (pp. 771-777, 2009) and Howard's own publication list give the printed title 'Memory: Computational Models'; the cited 'Computational models of working memory' is a variant. Title set to the printed one (reviewer's correction), year 2009 (LoC c2009), key Howa09 (free in HEAD).",
  "questions": [],
  "_batch": "batch-20"
 },
 "GoldEtal08": {
  "key": "GoldEtal08",
  "decision": "apply",
  "new_key": "GoldEtal09",
  "entrytype": "incollection",
  "set": {
   "title": {
    "value": "Neural integrator models",
    "url": "https://api.crossref.org/works/10.1016/b978-008045046-9.01434-0",
    "quote": "\"title\":[\"Neural Integrator Models\"]"
   },
   "editor": {
    "value": "L R Squire",
    "url": "http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=8&recordSchema=marcxml&query=dc.title%3D%22encyclopedia%20of%20neuroscience%22%20and%20dc.creator%3D%22squire%22",
    "quote": "editor-in-chief, Larry R. Squire."
   }
  },
  "notes": "Crossref prints 'Neural Integrator Models', pp. 165-178, 2009 (the cited title was a draft). Editor: the printed work names only the editor-in-chief (LoC 2009923450 'editor-in-chief, Larry R. Squire.'); the other four cited names are unconfirmable and removed (same as Howa09). Key GoldEtal09 (free).",
  "questions": [],
  "_batch": "batch-20"
 },
 "Seac97": {
  "key": "Seac97",
  "decision": "drop",
  "drop_reason": "no evidence found after: Crossref bibliographic search, OpenAlex, Internet Archive (Computer Dealer News collection has no accessible 1997 issues), local PDF library; trade magazine indexed only in ProQuest/Gale",
  "notes": "No fetchable record of the article exists.",
  "_batch": "batch-04"
 },
 "DaPo67": {
  "key": "DaPo67",
  "decision": "keep",
  "notes": "Real Indiana University doctoral dissertation (F J DaPolito, 1966), not a conference abstract. The DAI citation as in HEAD (27, 2522-2523, 1967) is printed identically in two independent books' reference lists (Internet Archive full text: Foundations of Human Memory; Human Memory: a constructivist view: 'Proactive effects with independent retrieval of competing responses. Dissertation Abstracts International, 27, 2522-2523.'), search URL https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=100&user_query=DaPolito%20%22Proactive%20effects%22%202522 ; the DAI page itself is behind ProQuest/HathiTrust bot walls. Kept pending the DAI rule question.",
  "questions": [
   "Dissertation Abstracts International (DAI) entries: when the DAI volume/page cannot be reached (ProQuest/HathiTrust bot walls) but the dissertation itself is documented, should the entry (a) stay an @article in DAI when independent citing works agree on the DAI volume/pages, (b) be converted to @phdthesis (School, Year of the degree) from a catalogue/DataCite record of the thesis, or (c) be dropped?"
  ],
  "_batch": "batch-05"
 },
 "WhitEtal96": {
  "key": "WhitEtal96",
  "decision": "apply",
  "merge_into": "WitmEtal96",
  "set": {},
  "withdraw": [],
  "remove": [],
  "notes": "HEAD WitmEtal96 holds the same work (same DOI 10.1006/ijhc.1996.0060, Witmer, Bailey, Knerr, Parsons, IJHCS 45(4) 413-428, title as Crossref). WitmEtal96 is the keeper; WhitEtal96 (misspelled Whitmer) merges into it.",
  "questions": [],
  "_batch": "batch-06"
 },
 "KahaEtal08b": {
  "key": "KahaEtal08b",
  "decision": "drop",
  "merge_into": "KahaEtal08a",
  "set": {},
  "withdraw": [],
  "remove": [],
  "drop_reason": "duplicate of KahaEtal08a (user-approved merge); already deleted in HEAD (verification/key-deletions.json, keeper KahaEtal08a)",
  "notes": "The queued KahaEtal08b (chapter 'Associative processes in episodic memory') is the same chapter as KahaEtal08a and was removed in 282d321. CAUTION: the key KahaEtal08b in HEAD now names a different work (Kahana, Sederberg and Howard 2008, Psychological Review 115(4), renamed from KahaEtal08c per key-renames.json); do NOT delete it.",
  "questions": [],
  "_batch": "batch-19"
 }
}''')
NO_DELETIONS = {}  # a frozen, empty deletion ledger: the fixture bib predates every deletion


def checkr(bib, wave, key, res=None, row=None, current=None):
    """A real wave row through check_entry with its review, validation and a resolution row,
    then the key-level resolution step (as run() does in the final pass). current={} runs
    it on a bibliography without the key."""
    rows_, review_, validation_ = {"2": (ROWS2, REVIEW2, VALIDATION2), "3": (ROWS3, REVIEW3, VALIDATION3),
                                   "7": (ROWS7, REVIEW7, VALIDATION7), "8": (ROWS8, REVIEW8, VALIDATION8)}[wave]
    res = copy.deepcopy(RESOLUTION[key]) if res is None else res
    bib_ = bib if current is None else {k: v for k, v in bib.items() if k != key}
    rec = pc.check_entry(row or rows_[key], bib_.get(key), bib_, ctx_for(bib_), review=review_.get(key),
                         validation=validation_.get(key), resolution=res)
    pc.apply_resolutions({key: rec}, {key: res}, bib_, NO_DELETIONS, dict(LOGGED_RENAMES))
    return rec


def residue(rec):
    return rec["resolution"]["residue"]


def test_resolution_apply_set_withdraw_remove_entrytype(bib):
    """BairNoma78 (batch-23): the whole authored book. The set title and address are source
    'resolution' with their LoC quotes checked; the withdrawn booktitle is not added; chapter
    and pages are removed; entrytype book. Nothing is left for the user."""
    rec = checkr(bib, "8", "BairNoma78")
    fin = rec["final_entry"]
    assert fin["ENTRYTYPE"] == "book" and fin["title"] == "Fundamentals of scaling and psychophysics"
    assert fin["address"] == "New York, {NY}" and fin["publisher"] == "Wiley"
    assert "booktitle" not in fin and "chapter" not in fin and "pages" not in fin
    assert set(rec["removals"]) == {"chapter", "pages"}
    assert sources(rec) == {"ENTRYTYPE": "resolution", "title": "resolution", "address": "resolution"}
    assert all(q["ok"] for q in rec["resolution"]["quotes"].values())
    assert residue(rec) == [] and not pc.needs_user(rec)
    assert not any(f["action"] == "held" for f in rec["flags"])
    # negative control: without the resolution the no_source row changes nothing and needs the user
    plain = checkw(bib, "8", "BairNoma78", review=True)
    assert plain["final_entry"].get("ENTRYTYPE") == "inbook" and pc.needs_user(plain)


def test_resolution_values_override_research_and_confirm_key(bib):
    """Howa08 (batch-20): the resolution's printed title beats the cited chapter field the
    titled-chapter move would otherwise use; year 2009 from Crossref; new_key Howa09 is the
    post-check's own plan (confirmed); the researcher's other corrections stand."""
    rec = checkr(bib, "8", "Howa08")
    fin = rec["final_entry"]
    assert fin["title"] == "Memory: computational models" and fin["year"] == "2009"
    assert fin["ENTRYTYPE"] == "incollection" and fin["pages"] == "771--777"
    assert sources(rec)["title"] == "resolution" and sources(rec)["pages"] == "researcher"
    plan = rec["key_plan"]
    assert plan["action"] == "rename" and plan["new_key"] == "Howa09" and "confirmed" in plan["resolution"]
    assert residue(rec) == [] and not pc.needs_user(rec)


def test_resolution_values_get_house_form(bib):
    """Resolution values go through the house rules: an em dash in a title is a---b with no
    spaces; a name loses its suffix and full given names become initials (GoldEtal08's
    editor quote prints 'Larry R. Squire.')."""
    res = copy.deepcopy(RESOLUTION["Howa08"])
    res["set"]["title"]["value"] = "Memory — computational models"
    assert checkr(bib, "8", "Howa08", res=res)["final_entry"]["title"] == "Memory---computational models"
    res["set"]["title"]["value"] = "Memory --- computational models"
    assert checkr(bib, "8", "Howa08", res=res)["final_entry"]["title"] == "Memory---computational models"
    res = copy.deepcopy(RESOLUTION["GoldEtal08"])
    res["set"]["editor"]["value"] = "Larry R. Squire"
    rec = checkr(bib, "8", "GoldEtal08", res=res)
    assert rec["final_entry"]["editor"] == "L R Squire" and residue(rec) == []
    # a suffix the quote does not print: unverified, applied only because the notes say
    # the page was read in a browser, and then without the suffix
    res["set"]["editor"]["value"] = "Larry R. Squire Jr."
    res["notes"] += " Read in a browser."
    rec = checkr(bib, "8", "GoldEtal08", res=res)
    assert rec["final_entry"]["editor"] == "L R Squire"
    assert any(f["code"] == "resolution_quote_unverified" and f["action"] == "applied" for f in rec["flags"])


def test_resolution_drop_marks_the_entry_for_removal(bib):
    """Seac97 (batch-04): no evidence found; the entry is marked remove_entry with the
    drop reason, and nothing else changes."""
    rec = checkr(bib, "3", "Seac97")
    assert rec["remove_entry"].startswith("no evidence found after: Crossref bibliographic search")
    assert rec["changes"] == [] and rec["removals"] == {} and rec["key_plan"]["action"] == "keep"
    assert not pc.needs_user(rec)
    rows_, noop = pc.build_resolution_removals({"Seac97": RESOLUTION["Seac97"]}, bib, NO_DELETIONS,
                                               renames=dict(LOGGED_RENAMES))
    assert [r["key"] for r in rows_] == ["Seac97"] and noop == []


def test_resolution_drop_of_absent_or_deleted_key_is_a_noop(bib):
    """Negative controls: a drop of a key that is not in the bibliography removes nothing;
    KahaEtal08b (batch-19) is in key-deletions.json and its key now names another work
    (renamed from KahaEtal08c), so it is not removed again."""
    rec = checkr(bib, "3", "Seac97", current={})
    assert not rec.get("remove_entry") and "resolution_noop" in codes(rec) and not pc.needs_user(rec)
    rows_, noop = pc.build_resolution_removals({"Seac97": RESOLUTION["Seac97"]},
                                               {k: v for k, v in bib.items() if k != "Seac97"}, NO_DELETIONS,
                                               renames=dict(LOGGED_RENAMES))
    assert rows_ == [] and noop[0]["key"] == "Seac97"
    deleted = {"KahaEtal08b": {"key": "KahaEtal08b", "reason": "duplicate of KahaEtal08a (approved merge)"}}
    res = RESOLUTION["KahaEtal08b"]
    rec = pc.check_entry(ROWS8["KahaEtal08b"], bib.get("KahaEtal08b"), bib, ctx_for(bib),
                         validation=VALIDATION8.get("KahaEtal08b"), resolution=res)
    pc.apply_resolutions({"KahaEtal08b": rec}, {"KahaEtal08b": res}, bib, deleted, {"KahaEtal08c": "KahaEtal08b"})
    assert not rec.get("remove_entry") and rec["key_plan"]["action"] == "keep"
    assert "renamed from KahaEtal08c" in rec["resolution"]["noop"]
    rows_, noop = pc.build_resolution_removals({"KahaEtal08b": res}, bib, deleted, renames=dict(LOGGED_RENAMES))
    assert rows_ == [] and "another work" in noop[0]["why"]


def test_resolution_keep_changes_nothing(bib):
    """DaPo67 (batch-05): keep means the entry stays exactly as it is, holds are
    superseded and it does not need the user."""
    rec = checkr(bib, "3", "DaPo67")
    assert rec["changes"] == [] and rec["removals"] == {} and rec["final_entry"] == dict(bib["DaPo67"])
    assert rec["key_plan"]["action"] == "keep" and not pc.needs_user(rec)
    assert not any(f["action"] == "held" for f in rec["flags"])


def test_resolution_merge(bib):
    """WhitEtal96 (batch-06): merge into WitmEtal96 (the same work, same DOI). The row also
    respells the cited 'B G Whitmer' as Crossref's 'B G Witmer'; under the user rule of
    2026-09-30 that mismatch is the user's, so it is the one residue the merge leaves."""
    rec = checkr(bib, "3", "WhitEtal96")
    assert rec["key_plan"]["action"] == "duplicate" and rec["key_plan"]["merge_into"] == "WitmEtal96"
    assert residue(rec) == ["surname_mismatch on author is held and the resolution does not address it"]
    assert pc.needs_user(rec)
    # negative control: a merge target that is neither in the bibliography nor planned is residue
    res = dict(RESOLUTION["WhitEtal96"], merge_into="NoSuchKey99")
    rec = checkr(bib, "3", "WhitEtal96", res=res)
    assert any("NoSuchKey99" in r for r in residue(rec)) and pc.needs_user(rec)


def test_resolution_set_without_quote_is_refused(bib):
    """Negative control: a set value without a verbatim quote is refused, the field keeps
    the bibliography's value and the entry needs the user."""
    res = copy.deepcopy(RESOLUTION["BairNoma78"])
    del res["set"]["title"]["quote"]
    rec = checkr(bib, "8", "BairNoma78", res=res)
    assert rec["final_entry"]["title"] == bib["BairNoma78"]["title"]
    assert "resolution_set_refused" in codes(rec) and pc.needs_user(rec)
    assert any(r.startswith("title:") for r in residue(rec))


def test_resolution_quote_that_fails_blocks_unless_browser_or_scan(bib):
    """A quote the validator does not find at its URL holds the value (residue); when the
    notes say the page was read in a browser or transcribed from a scan (user rule, round
    2), it is applied and flagged."""
    res = copy.deepcopy(RESOLUTION["BairNoma78"])
    res["set"]["title"]["quote"] = "Fundamentals of scaling and psychophysics, second edition"
    rec = checkr(bib, "8", "BairNoma78", res=res)
    assert rec["final_entry"]["title"] == bib["BairNoma78"]["title"] and pc.needs_user(rec)
    assert any(f["code"] == "resolution_quote_unverified" and f["action"] == "held" for f in rec["flags"])
    res["notes"] += " Title page transcribed from a scan (image-only)."
    rec = checkr(bib, "8", "BairNoma78", res=res)
    assert rec["final_entry"]["title"] == "Fundamentals of scaling and psychophysics" and not pc.needs_user(rec)
    assert any(f["code"] == "resolution_quote_unverified" and f["action"] == "applied" for f in rec["flags"])


def test_resolution_new_key_collisions(bib):
    """A new key held by a different work in the bibliography gets the next free suffix by
    the house rule (Howa04 -> Howa04a, new Howa04b) and is reported; a new key another
    entry already plans (Howa09, planned for Howa08) collides the same way."""
    res = dict(copy.deepcopy(RESOLUTION["Howa08"]), new_key="Howa04")
    rec = checkr(bib, "8", "Howa08", res=res)
    plan = rec["key_plan"]
    assert plan["action"] == "collision" and plan["new_key"] == "Howa04b"
    assert plan["also_rename"] == {"Howa04": "Howa04a"} and rec["resolution"]["key_collision"]["held_by"] == ["Howa04"]
    assert any("ID rule" in r for r in residue(rec))  # Howa04b does not fit the corrected year 2009
    howa = checkr(bib, "8", "Howa08")
    res = dict(copy.deepcopy(RESOLUTION["GoldEtal08"]), new_key="Howa09")
    gold = pc.check_entry(ROWS8["GoldEtal08"], bib["GoldEtal08"], bib, ctx_for(bib), review=REVIEW8.get("GoldEtal08"),
                          validation=VALIDATION8.get("GoldEtal08"), resolution=res)
    pc.apply_resolutions({"Howa08": howa, "GoldEtal08": gold}, {"GoldEtal08": res}, bib, NO_DELETIONS, {})
    assert howa["key_plan"]["new_key"] == "Howa09"
    assert gold["key_plan"]["action"] == "collision" and gold["key_plan"]["new_key"] == "Howa09b"
    # negative control: a free key is simply taken
    assert checkr(bib, "8", "GoldEtal08")["key_plan"]["new_key"] == "GoldEtal09"


def test_load_resolutions_refuses_unreadable_batches(tmp_path):
    """A half-written batch or a key decided two ways is an error, never 'no decision'."""
    (tmp_path / "batch-01.json").write_text(json.dumps([RESOLUTION["Seac97"], RESOLUTION["DaPo67"]]))
    got = pc.load_resolutions(tmp_path)
    assert set(got) == {"Seac97", "DaPo67"} and got["Seac97"]["_batch"] == "batch-01"
    assert pc.load_resolutions(tmp_path / "absent") == {}
    (tmp_path / "batch-02.json").write_text('[{"key": "Seac97", "decision": "keep"}')
    with pytest.raises(ValueError, match="not valid JSON"):
        pc.load_resolutions(tmp_path)
    (tmp_path / "batch-02.json").write_text(json.dumps([{"key": "Seac97", "decision": "keep"}]))
    with pytest.raises(ValueError, match="decided differently"):
        pc.load_resolutions(tmp_path)
    (tmp_path / "batch-02.json").write_text(json.dumps([{"key": "Seac97", "decision": "maybe"}]))
    with pytest.raises(ValueError, match="apply.drop.keep"):
        pc.load_resolutions(tmp_path)


def test_run_reads_resolutions_in_the_final_pass_only(tmp_path):
    """run() with a resolution directory: the final pass applies it (needs_user false, the
    drop in resolution_removals), the rules-alone pass never sees it; without one nothing
    changes (the default of run(); the CLI passes RESOLUTION_DIR when it exists)."""
    wave = tmp_path / "wave"
    wave.mkdir()
    (wave / "batch-001.json").write_text(json.dumps([ROWS3["Seac97"], ROWS3["DaPo67"], ROWS8["BairNoma78"]]))
    res_dir = tmp_path / "res"
    res_dir.mkdir()
    (res_dir / "batch-01.json").write_text(json.dumps([RESOLUTION[k] for k in ("Seac97", "DaPo67", "BairNoma78")]))
    post, page, rules_only, merged = pc.run(wave, bib=FROZEN_BIB, write=False, resolutions=res_dir,
                                            deleted=NO_DELETIONS, renames=dict(LOGGED_RENAMES))
    rows_ = {p["key"]: p for p in page}
    assert not any(r["needs_user"] for r in rows_.values())
    assert post["summary"]["resolution_removals"] == ["Seac97"] and rows_["Seac97"]["remove_entry"]
    assert post["summary"]["resolution_residue"] == {}
    assert rows_["BairNoma78"]["resolution"]["decision"] == "apply"
    assert not any(f["code"].startswith("resolution_") for r in rules_only.values() for f in r["flags"])
    post, page, rules_only, merged = pc.run(wave, bib=FROZEN_BIB, write=False, renames=dict(LOGGED_RENAMES))
    assert post["summary"]["resolutions"] == {} and any(p["needs_user"] for p in page)


# ---------------------------------------------------------------- resolutions on renamed keys

# Frozen rows of verification/key-renames.json (wave-1 apply, 2026-09-26, and the
# replace001 self-rename of SilvEtal19) and the batch-23 resolution of Frie08, written
# while its HEAD key was Frie08a.
FROZEN_RENAMES = {"Frie08": "Frie08a", "HerrEtal10": "HerrEtal10a", "Adey67a": "Adey67",
                  "KahaEtal08c": "KahaEtal08b", "JacoEtal05d": "JacoEtal05b", "SilvEtal19": "SilvEtal19"}
FROZEN_DELETIONS = {"KahaEtal08b": {"key": "KahaEtal08b", "reason": "duplicate of KahaEtal08a (approved merge)"},
                    "JacoEtal05b": {"key": "JacoEtal05b", "reason": "conference abstract (approved removal)"}}
FRIE08_RESOLUTION = json.loads(r'''{
 "key": "Frie08",
 "decision": "apply",
 "new_key": "Frie12",
 "set": {
  "year": {
   "value": "2012",
   "url": "http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=1&recordSchema=marcxml&query=bath.isbn=9780195374148",
   "quote": "c2012."
  },
  "pages": {
   "value": "514--536",
   "url": "https://academic.oup.com/edited-volume/34558/chapter-abstract/293244662",
   "quote": "Pages 514–536"
  }
 },
 "withdraw": [],
 "remove": [],
 "notes": "Publisher page (browser; citation_publication_date=2011/12/15, 'Pages 514–536') and Crossref published-print 2011-12-15 beat the LoC imprint c2012, so year 2011 (not the post-check's 2012) and key Frie11 (free in HEAD). Post-check DOI and journal removal stand. RECONCILED 2026-09-26: Print-year rule, consistent with BoydEtal15/Rugg95/MontEtal03 (batch 20): the printed book is 'Oxford : Oxford University Press, c2012.' (LoC 2010053196); Crossref/OUP 2011-12-15 is the Oxford Handbooks Online date. Key Frie12 (free). NOTE: this entry's HEAD key is now Frie08a (key-renames.json).",
 "questions": []
}''')


def renamed_bib(tmp_path, old, new):
    """The frozen bibliography with one entry renamed as the wave-1 apply renamed it."""
    text = Path(FROZEN_BIB).read_text()
    head = next(line for line in text.splitlines() if line.startswith("@") and line.endswith("{" + old + ","))
    path = tmp_path / "renamed.bib"
    path.write_text(text.replace(head, head[:-len(old) - 1] + new + ",", 1))
    return path


def test_resolution_follows_key_renames_to_the_current_key(tmp_path):
    """Frie08 (batch-23) was renamed Frie08a by the wave-1 apply (key-renames.json). The
    resolution applies to Frie08a: its set year and pages land, the key plan renames
    Frie08a -> Frie12, and the summary reports the redirect. Negative control: without the
    rename ledger the same decision is a no-op on an absent key, as before the fix."""
    bibpath = renamed_bib(tmp_path, "Frie08", "Frie08a")
    wave = tmp_path / "wave"
    wave.mkdir()
    (wave / "batch-001.json").write_text(json.dumps([ROWS8["Frie08"]]))
    res = {"Frie08": dict(FRIE08_RESOLUTION, _batch="batch-23")}
    post, page, rules_only, merged = pc.run(wave, bib=str(bibpath), write=False, resolutions=res,
                                            deleted=NO_DELETIONS, renames=FROZEN_RENAMES)
    s = post["summary"]
    assert s["resolution_redirects"] == {"Frie08": {"from": "Frie08", "to": "Frie08a", "chain": ["Frie08", "Frie08a"],
                                                    "decision": "apply"}}
    rec = merged["Frie08"]
    assert rec["key"] == "Frie08a" and "resolution_redirect" in codes(rec) and "not_in_bib" not in codes(rec)
    assert rec["final_entry"]["year"] == "2012" and rec["final_entry"]["pages"] == "514--536"
    plan = rec["key_plan"]
    assert plan["current_key"] == "Frie08a" and plan["action"] == "rename" and plan["new_key"] == "Frie12"
    assert s["renames"] == {"Frie08a": "Frie12"} and "Frie08" not in s["resolution_noops"]
    assert rec["resolution"]["residue"] == []
    # negative control: no rename ledger -> the key is absent and the decision is a no-op
    post, page, rules_only, merged = pc.run(wave, bib=str(bibpath), write=False, resolutions=res,
                                            deleted=NO_DELETIONS, renames={})
    assert post["summary"]["resolution_redirects"] == {} and "Frie08" in post["summary"]["resolution_noops"]
    assert merged["Frie08"]["key_plan"]["action"] == "keep" and "resolution_redirect" not in codes(merged["Frie08"])


def test_follow_renames_never_from_a_deleted_key(bib):
    """Redirects follow key-renames.json only from a key that is absent and not deleted:
    Adey67a -> Adey67 and HerrEtal10 -> HerrEtal10a are followed on a bibliography where
    they were renamed; a renamed work landing on a once-deleted key (JacoEtal05d ->
    JacoEtal05b) is followed; KahaEtal08b, deleted with its suffix reused, is never
    followed from, and its drop stays a no-op; SilvEtal19's self-rename is no cycle."""
    after = {("Adey67" if k == "Adey67a" else "HerrEtal10a" if k == "HerrEtal10" else
              "JacoEtal05b" if k == "JacoEtal05d" else k): v
             for k, v in bib.items() if k not in ("Adey67", "JacoEtal05b", "SilvEtal19")}
    assert pc.follow_renames("Adey67a", after, FROZEN_RENAMES, FROZEN_DELETIONS) == ("Adey67", ["Adey67a", "Adey67"])
    assert pc.follow_renames("HerrEtal10", after, FROZEN_RENAMES, FROZEN_DELETIONS)[0] == "HerrEtal10a"
    assert pc.follow_renames("JacoEtal05d", after, FROZEN_RENAMES, FROZEN_DELETIONS)[0] == "JacoEtal05b"
    assert pc.follow_renames("SilvEtal19", after, FROZEN_RENAMES, FROZEN_DELETIONS) == ("SilvEtal19", [])
    assert pc.follow_renames("Seac97", after, FROZEN_RENAMES, FROZEN_DELETIONS) == ("Seac97", [])
    # a key listed in key-deletions.json is never followed, even when a rename row names it
    assert pc.follow_renames("KahaEtal08b", {}, {"KahaEtal08b": "KahaEtal08a"}, FROZEN_DELETIONS) == ("KahaEtal08b", [])
    res = dict(RESOLUTION["KahaEtal08b"])
    no_kaha = {k: v for k, v in bib.items() if k != "KahaEtal08b"}
    rows_, noop = pc.build_resolution_removals({"KahaEtal08b": res}, no_kaha, FROZEN_DELETIONS,
                                               dict(FROZEN_RENAMES, KahaEtal08b="KahaEtal08a"))
    assert rows_ == [] and noop[0]["key"] == "KahaEtal08b"
    rec = pc.check_entry(ROWS8["KahaEtal08b"], None, no_kaha, ctx_for(no_kaha),
                         validation=VALIDATION8.get("KahaEtal08b"), resolution=res)
    pc.apply_resolutions({"KahaEtal08b": rec}, {"KahaEtal08b": res}, no_kaha, FROZEN_DELETIONS,
                         dict(FROZEN_RENAMES, KahaEtal08b="KahaEtal08a"))
    assert not rec.get("remove_entry") and "redirect" not in rec["resolution"]
    assert "resolution_redirect" not in codes(rec)
    # a drop of a renamed key removes the entry under its current key
    drop = dict(RESOLUTION["Seac97"], key="HerrEtal10")
    rows_, noop = pc.build_resolution_removals({"HerrEtal10": drop}, after, FROZEN_DELETIONS, FROZEN_RENAMES)
    assert [(r["key"], r["renamed_from"]) for r in rows_] == [("HerrEtal10a", "HerrEtal10 -> HerrEtal10a")]
    assert noop == []


# ---------------------------------------------------------------- resolution evidence rules (2026-09-26)
# Real rows from verification/resolution-2026-09-26/batch-NN.json after the evidence pass,
# frozen here: the user's rules for next-start end pages, several quotes, catalogue
# extents, roman page prefixes, and resolution values that a removal must not delete.

RESOLUTION_RULES = json.loads(r'''{
 "Gomu53": {
  "key": "Gomu53",
  "decision": "apply",
  "notes": "Work confirmed (Harvard/LoC LCCN 53011675: Gomulicki, Bronislaw R., 1953, series 'British journal of psychology. Monograph supplements ; 29'). Pages unconfirmed and conflicting: Harvard/LoC '94 p.' with 'Bibliography: pages [86]-91'; BJPS review 10.1093/bjps/vi.24.346 says 'pp. 85'. HEAD 1--91 left unchanged; no DOI exists. RECONCILED 2026-09-26: HEAD 1--91 is confirmed by no record; LoC catalogue extent '94 p.' gives 1--94, the same catalogue-extent form Gate17 (batch 02) uses for a numbered monograph issue.",
  "questions": [
   "For numbered monograph supplements catalogued as books (a whole issue by one author, e.g. BJP Monograph Supplements no. 29, '94 p.'), should pages be the catalogue extent (1--94), the text through the bibliography, or should the entry become @book with series/number and no pages?"
  ],
  "set": {
   "pages": {
    "value": "1--94",
    "url": "https://www.loc.gov/item/53011675/?fo=json",
    "quote": "94 p."
   }
  },
  "_batch": "batch-03"
 },
 "McCaEtal06": {
  "key": "McCaEtal06",
  "decision": "apply",
  "set": {
   "pages": {
    "value": "12--14",
    "url": "https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/download/1904/1802",
    "quote": "12 AI MAGAZINE",
    "extra_evidence": [
     {
      "url": "https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/download/1904/1802",
      "quote": "WINTER 2006 13"
     },
     {
      "url": "https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/download/1904/1802",
      "quote": "orderly thinking. 14 AI MAGAZINE"
     }
    ]
   },
   "doi": {
    "value": "10.1609/aimag.v27i4.1904",
    "url": "https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/view/1904",
    "quote": "citation_doi\" content=\"10.1609/aimag.v27i4.1904"
   }
  },
  "withdraw": [],
  "remove": [],
  "notes": "Publisher PDF (3 pages) prints page footers 12 ('12 AI MAGAZINE'), 'WINTER 2006 13' and 14; OJS meta tags wrongly give lastpage 12. DOI registered with Crossref (doiRA) and resolves to the AAAI OJS page, which prints it; the Crossref API returns 404 for the record. EVIDENCE 2026-09-26 (several-quotes rule): pages from the three PDF footers '12 AI MAGAZINE', 'WINTER 2006 13', '14 AI MAGAZINE'. DOI: doi.org resolves 10.1609/aimag.v27i4.1904 (HTTP 302 to the AAAI OJS article; handle API responseCode 1), so it is registered; only Crossref's REST API returns 404 for the record.",
  "questions": [],
  "_batch": "batch-14"
 },
 "VodrEtal16": {
  "key": "VodrEtal16",
  "decision": "apply",
  "new_key": "VodrEtal18",
  "entrytype": "article",
  "set": {
   "author": {
    "value": "K Vodrahalli and P-H Chen and Y Liang and C Baldassano and J Chen and E Yong and C Honey and U Hasson and P Ramadge and K A Norman and S Arora",
    "url": "https://api.crossref.org/works/10.1016/j.neuroimage.2017.06.042",
    "quote": "ations\"],\"prefix\":\"10.1016\",\"volume\":\"180\",\"author\":[{\"given\":\"Kiran\",\"family\":\"Vodrahalli\",\"sequence\":\"first\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Po-Hsuan\",\"family\":\"Chen\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Yingyu\",\"family\":\"Liang\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Christopher\",\"family\":\"Baldassano\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Janice\",\"family\":\"Chen\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Esther\",\"family\":\"Yong\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Christopher\",\"family\":\"Honey\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Uri\",\"family\":\"Hasson\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Peter\",\"family\":\"Ramadge\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Kenneth A.\",\"family\":\"Norman\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"role\":\"author\"}]},{\"given\":\"Sanjeev\",\"family\":\"Arora\",\"sequence\":\"additional\",\"affiliation\":[],\"role\":[{\"vocabulary\":\"crossref\",\"rol"
   },
   "title": {
    "value": "Mapping between {fMRI} responses to movies and their natural language annotations",
    "url": "https://api.crossref.org/works/10.1016/j.neuroimage.2017.06.042",
    "quote": "Mapping between fMRI responses to movies and their natural language annotations"
   },
   "journal": {
    "value": "{NeuroImage}",
    "url": "https://api.crossref.org/works/10.1016/j.neuroimage.2017.06.042",
    "quote": "\"container-title\":[\"NeuroImage\"]"
   },
   "volume": {
    "value": "180",
    "url": "https://api.crossref.org/works/10.1016/j.neuroimage.2017.06.042",
    "quote": "\"volume\":\"180\""
   },
   "pages": {
    "value": "223--231",
    "url": "https://api.crossref.org/works/10.1016/j.neuroimage.2017.06.042",
    "quote": "\"page\":\"223-231\""
   },
   "year": {
    "value": "2018",
    "url": "https://api.crossref.org/works/10.1016/j.neuroimage.2017.06.042",
    "quote": "\"published-print\":{\"date-parts\":[[2018,10]]}"
   },
   "doi": {
    "value": "10.1016/j.neuroimage.2017.06.042",
    "url": "https://api.crossref.org/works/10.1016/j.neuroimage.2017.06.042",
    "quote": "10.1016\\/j.neuroimage.2017.06.042"
   }
  },
  "withdraw": [],
  "remove": [],
  "notes": "Preprint published: NeuroImage 180:223-231 (print Oct 2018), same title and the same 11 authors as arXiv v3, whose comment reads 'in submission to NeuroImage'. Replaced by the published version per the preprint rule (supersedes the post-check's arXiv doi/volume/2017). VodrEtal18 free in HEAD; junk Pages URL replaced.",
  "questions": [],
  "_batch": "batch-17"
 },
 "Lovr80": {
  "key": "Lovr80",
  "decision": "apply",
  "set": {
   "author": {
    "value": "J H Lovrinic",
    "url": "https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=5&user_query=%22Chapter%203%22%20AND%20identifier%3Aaudiologyforphys0000unse",
    "quote": "Speech Audiometry Jean H. Lovrinic, Ph.D. 13"
   },
   "title": {
    "value": "Pure tone and speech audiometry",
    "url": "https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=5&user_query=%22Speech%20Audiometry%22%20AND%20identifier%3Aaudiologyforphys0000unse",
    "quote": "Pure Tone and {{{Speech Audiometry}}} Jean H. Lovrinic"
   },
   "pages": {
    "value": "13--32",
    "url": "https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=5&user_query=%22Chapter%203%22%20AND%20identifier%3Aaudiologyforphys0000unse",
    "quote": "Speech Audiometry Jean H. Lovrinic, Ph.D. 13",
    "next_start": {
     "url": "https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=5&user_query=%22Chapter%203%22%20AND%20identifier%3Aaudiologyforphys0000unse",
     "quote": "Diagnostic Audiometry Robert W. Keith, Ph.D. 33"
    }
   }
  },
  "notes": "Printed book (Internet Archive full text of Audiology for the Physician, Williams & Wilkins 1980): contents 'Chapter 2 Pure Tone and Speech Audiometry Jean H. Lovrinic, Ph.D. 13 / Chapter 3 Diagnostic Audiometry Robert W. Keith, Ph.D. 33', so pages 13--32 by the next-item rule (HEAD had 13--31). Editor R W Keith per post-check. EVIDENCE 2026-09-26 (next-start rule): pages quote the printed start page; next_start quotes the next item's printed start page (end = next start - 1, user rule round 2).",
  "_batch": "batch-18"
 },
 "KahaEtal08a": {
  "key": "KahaEtal08a",
  "decision": "apply",
  "set": {
   "pages": {
    "value": "467--490",
    "url": "https://memory.psych.upenn.edu/files/pubs/KahaEtal08.pdf",
    "quote": "490 Associative Retrieval Processes in Episodic Memory",
    "extra_evidence": [
     {
      "url": "https://memory.psych.upenn.edu/files/pubs/KahaEtal08.pdf",
      "quote": "Our power to remember this feature. 467 Author's personal copy"
     }
    ]
   }
  },
  "withdraw": [],
  "remove": [],
  "notes": "Printed record wins over Crossref '1-24': the authors' copy of the Elsevier chapter carries page folios 467 (first page) and '490 Associative Retrieval Processes in Episodic Memory' (last), and Crossref's preceding chapter (Raaijmakers) ends at 466. Keeps suffix 'a' because HEAD has another KahaEtal08 (KahaEtal08b, the Psychological Review reply renamed from KahaEtal08c). Apply the post-check (DOI, pages). EVIDENCE 2026-09-26 (several-quotes rule): pages evidence is several quotes from the same official record whose union prints every page number of the value.",
  "questions": [],
  "_batch": "batch-19"
 },
 "HallGree08": {
  "key": "HallGree08",
  "decision": "apply",
  "set": {
   "pages": {
    "value": "212--224",
    "url": "https://api.crossref.org/works/10.4135/9781412964012.n23",
    "quote": "\"page\":\"I-212-I-224\""
   },
   "booktitle": {
    "value": "21\\textsuperscript{st} Century Education: A Reference Handbook",
    "url": "https://api.crossref.org/works/10.4135/9781412964012.n23",
    "quote": "\"container-title\":[\"21st Century Education: A Reference Handbook\"]"
   },
   "volume": {
    "value": "1",
    "url": "https://api.crossref.org/works/10.4135/9781412964012.n23",
    "quote": "\"page\":\"I-212-I-224\""
   }
  },
  "withdraw": [],
  "remove": [],
  "notes": "Crossref pages I-212-I-224 (the I- prefix is the volume) give 212--224; booktitle title case checked and correct. Volume 1 is not added: no fetchable page prints it (SAGE Knowledge requires login; the LoC TOC does not split volumes), and HEAD has no volume. RECONCILED 2026-09-26: Volume 1 from the 'I-' page prefix, as the ICASSP volume-prefix default does for HuggEtal06/YingEtal93 (batch 26).",
  "questions": [],
  "_batch": "batch-23"
 }
}
''')


def rules_row(key, **change):
    return dict(copy.deepcopy(RESOLUTION_RULES[key]), **change)


def test_resolution_next_start_infers_the_end_page(bib):
    """Lovr80 (batch-18): the contents print the chapter's start (13) and the next chapter's
    start (33); no source prints 32. With next_start the end page is next start - 1 (user
    rule, round 2): applied, flagged resolution_inferred_value, nothing left for the user."""
    res = rules_row("Lovr80")
    assert res["set"]["pages"]["next_start"]["quote"].endswith("33")
    rec = checkr(bib, "8", "Lovr80", res=res)
    assert rec["final_entry"]["pages"] == "13--32" and sources(rec)["pages"] == "resolution"
    assert any(f["code"] == "resolution_inferred_value" and f["field"] == "pages" for f in rec["flags"])
    assert residue(rec) == [] and not pc.needs_user(rec)
    # negative controls: an end page that is not next start - 1; a start page the quote
    # does not print; next_start on a field other than pages; no next_start at all
    for value in ("13--31", "14--32"):
        bad = copy.deepcopy(res)
        bad["set"]["pages"]["value"] = value
        rec = checkr(bib, "8", "Lovr80", res=bad)
        assert sources(rec).get("pages") != "resolution" and pc.needs_user(rec)
        assert any(f["code"] == "resolution_quote_unverified" and f["action"] == "held" for f in rec["flags"])
        assert any(r.startswith("pages: quote unverified") for r in residue(rec))
    q = pc.resolution_quote("volume", dict(res["set"]["pages"], value="13"))
    assert q.get("refused") and not q["ok"]
    plain = copy.deepcopy(res)
    del plain["set"]["pages"]["next_start"]
    assert not pc.resolution_quote("pages", plain["set"]["pages"])["ok"]


def test_resolution_value_from_several_quotes(bib):
    """KahaEtal08a (batch-19): the first and last folios (467, 490) sit about 150k
    characters apart in the authors' PDF; the union of two verified quotes covers
    467--490. Negative controls: the last-page quote alone does not; an extra quote that
    is not at its URL fails the whole value."""
    res = rules_row("KahaEtal08a")
    assert len(pc.evidence_items(res["set"]["pages"])) == 2
    rec = checkr(bib, "8", "KahaEtal08a", res=res)
    assert rec["final_entry"]["pages"] == "467--490" and residue(rec) == []
    assert rec["resolution"]["quotes"]["pages"]["ok"] and not rec["resolution"]["quotes"]["pages"].get("rule")
    one = copy.deepcopy(res)
    del one["set"]["pages"]["extra_evidence"]
    q = pc.resolution_quote("pages", one["set"]["pages"])
    assert not q["ok"] and "467" in q["why"]
    rec = checkr(bib, "8", "KahaEtal08a", res=one)
    assert pc.needs_user(rec) and any(r.startswith("pages: quote unverified") for r in residue(rec))
    wrong = copy.deepcopy(res)
    wrong["set"]["pages"]["extra_evidence"][0]["quote"] = "Our power to remember this feature. 466 Author's personal copy"
    q = pc.resolution_quote("pages", wrong["set"]["pages"])
    assert not q["ok"] and "quote not found" in q["why"]


def test_resolution_catalogue_extent_gives_monograph_pages(bib):
    """Gomu53 (batch-03): a numbered monograph supplement catalogued '94 p.' (LoC 53011675)
    is pages 1--94 (README default, as Gate17). Negative controls: a range not starting at
    1, and an N the extent does not print."""
    rec = checkr(bib, "2", "Gomu53", res=rules_row("Gomu53"))
    assert rec["final_entry"]["pages"] == "1--94" and residue(rec) == [] and not pc.needs_user(rec)
    assert any(f["code"] == "resolution_inferred_value" and "catalogue extent" in f["detail"] for f in rec["flags"])
    spec = RESOLUTION_RULES["Gomu53"]["set"]["pages"]
    for value in ("2--94", "1--91", "1--9"):
        assert not pc.resolution_quote("pages", dict(spec, value=value))["ok"], value


def test_resolution_volume_from_roman_page_prefix(bib):
    """HallGree08 (batch-23): SAGE prints pages 'I-212-I-224'; the 'I-' prefix is Volume 1
    (README default for ICASSP-style prefixes). The held quote_check_failed on volume is
    superseded. Negative controls: volume 2 from the same quote; a lower-case or unjoined
    numeral is no prefix."""
    rec = checkr(bib, "8", "HallGree08", res=rules_row("HallGree08"))
    assert rec["final_entry"]["volume"] == "1" and rec["final_entry"]["pages"] == "212--224"
    assert residue(rec) == [] and not pc.needs_user(rec)
    spec = RESOLUTION_RULES["HallGree08"]["set"]["volume"]
    assert not pc.resolution_quote("volume", dict(spec, value="2"))["ok"]
    V = pc.validator()
    assert pc.roman_page_prefix(V, "1", ['"page":"I-212-I-224"'])[0]
    assert not pc.roman_page_prefix(V, "1", ['"page":"i-212"'])[0]
    assert not pc.roman_page_prefix(V, "1", ["Part I 212"])[0]
    assert pc.roman_page_prefix(V, "2", ['"page":"II-5"'])[0]
    assert not pc.roman_page_prefix(V, "1", ['"page":"II-5"'])[0]


def test_resolution_set_survives_the_researchers_removal(bib):
    """VodrEtal16 (batch-17): HEAD's Pages holds a junk DOI URL, which the researcher asked to
    remove; the resolution sets the published pages 223--231. Resolution decisions are
    final: the removal never deletes the resolution's value. Negative control: without the
    resolution the researcher's removal still removes the junk value."""
    assert "pages" in ROWS7["VodrEtal16"].get("remove", [])
    rec = checkr(bib, "7", "VodrEtal16", res=rules_row("VodrEtal16"))
    assert rec["final_entry"]["pages"] == "223--231" and "pages" not in rec["removals"]
    assert not any("did not survive" in r for r in residue(rec))
    plain = checkw(bib, "7", "VodrEtal16")
    assert "pages" not in plain["final_entry"] and "pages" in plain["removals"]


def test_resolution_pages_from_pdf_footers_and_unregistered_doi(bib):
    """McCaEtal06 (batch-14): pages 12--14 from the three PDF footers (several quotes).
    Its DOI is registered at doi.org (only Crossref's REST API has no record), so it is not
    dropped: it stays held for the registry title. A resolution DOI that doi.org does not
    register (10.4324/9780203837672-11, a Taylor & Francis URL path) is dropped, with no
    residue for it (never cite an unregistered DOI)."""
    res = rules_row("McCaEtal06")
    rec = checkr(bib, "7", "McCaEtal06", res=res)
    assert rec["final_entry"]["pages"] == "12--14"
    assert not any(r.startswith("pages:") for r in residue(rec))
    assert rec["doi_status"]["registered"] is True
    assert any(r.startswith("doi:") for r in residue(rec)) and "resolution_doi_unregistered" not in codes(rec)
    bad = copy.deepcopy(res)
    bad["set"]["doi"] = {"value": "10.4324/9780203837672-11",
                         "url": "https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/view/1904",
                         "quote": "citation_doi\" content=\"10.1609/aimag.v27i4.1904"}
    bad["notes"] += " Read in a browser."
    rec = checkr(bib, "7", "McCaEtal06", res=bad)
    assert "resolution_doi_unregistered" in codes(rec)
    assert rec["final_entry"].get("doi") != "10.4324/9780203837672-11"
    assert not any(r.startswith("doi:") and "did not survive" in r for r in residue(rec))


def test_renamed_away_follows_the_log_in_order_through_a_key_swap(tmp_path, monkeypatch):
    """The 2026-09-30 swap (user, review page doc note-KahaEtal08b): the reply KahaEtal08b
    became KahaEtal08a and the chapter KahaEtal08a became KahaEtal08b, logged as three renames
    through a temporary key. Frozen rows: the wave-1 rename and the three swap rows."""
    log = [{"old_key": "KahaEtal08c", "new_key": "KahaEtal08b"},
           {"old_key": "KahaEtal08a", "new_key": "KahaEtal08-swap-2026-09-30"},
           {"old_key": "KahaEtal08b", "new_key": "KahaEtal08a"},
           {"old_key": "KahaEtal08-swap-2026-09-30", "new_key": "KahaEtal08b"},
           {"old_key": "HerrEtal10", "new_key": "HerrEtal10a"}]
    (tmp_path / "verification").mkdir()
    (tmp_path / "verification/key-renames.json").write_text(json.dumps(log))
    monkeypatch.setattr(pc, "ROOT", tmp_path)
    renames = pc.renamed_away()
    bib = {"KahaEtal08a": {}, "KahaEtal08b": {}, "HerrEtal10a": {}}
    # the reply, first keyed KahaEtal08c, is KahaEtal08a now (last-row-wins sent it to the chapter)
    assert pc.follow_renames("KahaEtal08c", bib, renames, {"KahaEtal08b"}) == \
        ("KahaEtal08a", ["KahaEtal08c", "KahaEtal08a"])
    assert renames["KahaEtal08a"] == "KahaEtal08b" and renames["KahaEtal08b"] == "KahaEtal08a"
    # keys still in the bibliography are never redirected; a deleted key is never followed
    assert pc.follow_renames("KahaEtal08a", bib, renames, {"KahaEtal08b"}) == ("KahaEtal08a", [])
    # negative control: an ordinary chain reads the same either way
    assert pc.follow_renames("HerrEtal10", bib, renames, set())[0] == "HerrEtal10a"
