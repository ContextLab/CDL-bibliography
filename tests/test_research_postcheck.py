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


def test_hyphenated_initials_from_pubmed_forename(bib):
    rec = check(bib, "GoldEtal05")
    assert "J-P Michel" in changed(rec)["author"] and "initials_from_source" in codes(rec)


def test_all_initials_the_source_gives(bib):
    assert changed(check(bib, "Hawk99"))["author"] == "S W Hawking"


def test_initials_not_changed_when_sources_disagree_or_match(bib):
    rec = check(bib, "BlisColl93")  # PubMed 'T V', Crossref 'T. V. P.'; proposal keeps T V P
    assert "initials_from_source" not in codes(rec)
    assert rec["final_entry"]["author"] == "T V P Bliss and G L Collingridge"


def test_single_source_surname_change_is_flagged(bib):
    assert "surname_single_source" in codes(check(bib, "MannEtal23b"))
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
            "Frie06", "EchaEtal00", "LittEtal98", "IyyeEtal15", "ChenEtal22", "GoldEtal05",
            "KansEtal15"} <= caught
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


def test_initials_still_added_when_source_gives_them(bib):
    """Negative controls: the two wave-2 applications the reviewer confirmed, and a
    Crossref given name with a middle initial."""
    rec = check2(bib, "AllpEtal94")
    assert "S L Hsieh" in pc.split_names(rec["final_entry"]["author"])
    assert "initials_from_source" in codes(rec)
    assert "X-J Wang" in pc.split_names(check2(bib, "MillEtal03")["final_entry"]["author"])
    quote = '{"given":"John A.","family":"Smith","sequence":"first"}'
    assert pc.initials_from_evidence("J Smith", [quote])[0] == "J A Smith"
    assert pc.initials_from_evidence("J Smith and K Jones", ["John Andrew Smith, Kate Jones"])[0] == \
        "J A Smith and K Jones"


def test_uncertain_split_holds_initials():
    unsure = []
    assert pc.initials_from_evidence("D Bihan", ["Denis Le Bihan"], unsure)[0] == "D Bihan"
    assert unsure and "particle" in unsure[0]
    unsure = []
    quote = '{"given":"Mohsen Parto","family":"Dezfouli"}'  # source splits the surname
    assert pc.initials_from_evidence("M {Parto Dezfouli}", [quote], unsure)[0] == "M {Parto Dezfouli}"
    assert unsure and "splits the name differently" in unsure[0]
    # a braced surname is one unit and the source gives only 'Mohsen'
    assert pc.initials_from_evidence("M {Parto Dezfouli}", ["Mohsen Parto Dezfouli, Mohammad Reza Daliri"])[0] \
        == "M {Parto Dezfouli}"


def test_bibtex_author_list_is_structured_evidence():
    quote = "author = {Desmaison, Alban and Kopf, Andreas and Yang, Edward}"
    assert pc.evidence_given_names("K{\\\"o}pf", [quote]) == ["Andreas"]


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
