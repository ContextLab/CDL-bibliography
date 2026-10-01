"""Machinery fixes found by testing on real PRs #87 and #88 (2026-09-25).

verification/pr-check-2026-09-25/README.md lists the false rejections; the
rules are documented in verification/machinery-2026-09-25/README.md. Real PR
entries and their cached review rows are frozen in
tests/fixtures/machinery-2026-09-25-cases.json.gz (build_cases.py); MeyeEtal88 is
the frozen stage 1 case in tests/fixtures/apply-2026-09-25-cases.json.gz. Every
rule has negative controls.
"""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bibcheck"))
import auto_review  # noqa: E402
import catalogue_review  # noqa: E402
import correction_proposals as cp  # noqa: E402
import helpers  # noqa: E402
import verification as v  # noqa: E402

CASES = json.loads(gzip.open(ROOT / "tests/fixtures/machinery-2026-09-25-cases.json.gz").read())["cases"]
STAGE1 = json.loads(gzip.open(ROOT / "tests/fixtures/apply-2026-09-25-cases.json.gz").read())


def case(key):
    data = deepcopy(CASES[key])
    return data["entry"], data["previous"]


def edited(entry, **fields):
    entry = deepcopy(entry)
    for name, value in fields.items():
        if value is None:
            entry["fields"].pop(name, None)
        else:
            entry["fields"][name] = value
    return entry


def status(entry, previous):
    return auto_review.reassess(entry, previous)["status"]


def crossref(previous, doi):
    return next(c for c in previous["candidates"] if c.get("source") == "crossref"
                and c.get("doi", "").lower() == doi.lower())


# 1. Formatter ---------------------------------------------------------------

@pytest.mark.parametrize("pages,ok", [
    ("IMAG.a.136", True), ("1417--1427.e6", True), ("e1160--e1167", True), ("zpaf089", True),
    ("e.g.", False), ("IMAG.a.136--IMAG.a.140", False), ("136.a", False), ("a..1", False),
    ("1417--1427.e0", False), ("12--3", False),
])
def test_alphanumeric_article_numbers(pages, ok):
    assert helpers.valid_pages(pages)[0] is ok


def write_bib(path, raw):
    path.write_text(raw + "\n")
    return path


def test_source_backed_article_number_passes_the_formatter(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    entry, _ = case("KothEtal25")
    assert entry["fields"]["pages"] == "IMAG.a.136"
    errors, _ = helpers.check_bib(str(write_bib(tmp_path / "k.bib", entry["raw"])), verbose=False)
    assert errors == {}


def test_duplicate_fields_are_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    entry, _ = case("KothEtal25")
    # The #88 merge shape: one Doi inserted alphabetically, one appended at the end.
    assert entry["raw"].endswith("}}")
    raw = entry["raw"][:-1] + ",\n\tDoi = {10.1162/imag.a.136}}"
    assert helpers.duplicate_fields(raw) == {"KothEtal25": ["doi"]}
    with pytest.raises(Exception, match="duplicate fields found: KothEtal25: doi"):
        helpers.check_bib(str(write_bib(tmp_path / "d.bib", raw)), verbose=False)
    assert helpers.duplicate_fields(entry["raw"]) == {}  # negative control


def test_bibcheck_verify_surfaces_errors_and_exits_nonzero(tmp_path):
    entry, _ = case("KothEtal25")
    bad = write_bib(tmp_path / "bad.bib", entry["raw"].replace("IMAG.a.136", "IMAG.a.136--IMAG.a.1"))
    run = subprocess.run([sys.executable, "bibcheck.py", "verify", "--fname", str(bad)], cwd=ROOT,
                         capture_output=True, text=True)
    assert run.returncode == 1
    assert "page numbers are ambiguous or incorrect" in run.stderr and "KothEtal25" in run.stderr
    good = write_bib(tmp_path / "good.bib", entry["raw"])
    # Format only: the citation part of the gate is tested in section 16.
    run = subprocess.run([sys.executable, "bibcheck.py", "verify", "--fname", str(good), "--no-citations"], cwd=ROOT,
                         capture_output=True, text=True)
    assert run.returncode == 0 and "looks good!" in run.stdout


def test_unparseable_whole_name_is_an_error_but_initial_fragments_are_not():
    with pytest.raises(ValueError, match="cannot parse name"):
        helpers.reformat_author("Smith, Jones, Brown, Green")
    assert helpers.reformat_author("J-X Li") == "J-X Li"


# 2. Degree suffixes -----------------------------------------------------------

@pytest.mark.parametrize("value,degree", [
    ("MD, FACP", True), ("Ph. D.", True), ("PhD", True), ("MS, MPH", True), ("BA", True),
    ("MD PhD", True), ("Jr", False), ("III", False), ("MD, Jr", False), ("Smith", False), ("", False),
])
def test_degree_suffix_table(value, degree):
    assert v.degree_suffix(value) is degree


def test_schredl_degree_suffix_verifies():
    entry, previous = case("Schr03")
    assert crossref(previous, "10.1007/s00406-003-0438-1")["record"]["author"][0]["suffix"] == "Ph. D."
    result = auto_review.reassess(entry, previous)
    assert result["status"] == "metadata_verified"
    # Negative controls: a surname or given-name difference still blocks.
    assert status(edited(entry, author="M Schreddl"), previous) == "needs_review"
    assert status(edited(entry, author="J Schredl"), previous) == "needs_review"


def test_felitti_degrees_no_longer_block_but_the_truncated_title_does():
    entry, previous = case("FeliEtal98")
    record = crossref(previous, "10.1016/s0749-3797(98)00017-8")["record"]
    evidence, issues = v.compare_record(entry["fields"], record)
    assert evidence["author"]["match"] and issues == ["title: missing evidence or mismatch"]
    assert status(entry, previous) == "needs_review"
    # A non-degree suffix in the source is still a name part.
    other = deepcopy(record)
    other["author"][0]["suffix"] = "Esq Smith"
    assert not v.compare_record(entry["fields"], other)[0]["author"]["match"]


# 3. Leading "The" and numeric issues -----------------------------------------

def test_pigeon_leading_article_and_zero_padded_issue_verify():
    entry, previous = case("PigeEtal12")
    assert crossref(previous, "10.4088/jcp.11r07586")["record"]["issue"] == "09"
    assert status(entry, previous) == "metadata_verified"
    for change in ({"journal": "Journal of Clinical Psychology"}, {"number": "8"}, {"number": "90"},
                   {"volume": "74"}):
        assert status(edited(entry, **change), previous) == "needs_review", change


@pytest.mark.parametrize("cited,source,same", [
    ("Journal of Clinical Psychiatry", "The Journal of Clinical Psychiatry", True),
    ("The Journal of Clinical Psychiatry", "Journal of Clinical Psychiatry", True),
    ("Oretical Population Biology", "Theoretical Population Biology", False),
    ("Journal of Physiology (Paris)", "The Journal of Physiology", False),
])
def test_leading_article_only_against_an_issn_record(cited, source, same):
    record = {"container-title": [source], "ISSN": ["0160-6689"]}
    assert v.registry_journal_match(cited, record) is same
    assert not v.registry_journal_match(cited, {"container-title": [source]})  # no ISSN: no rule
    # normalize_journal itself keeps generic leading articles (tests/test_metadata_punctuation.py).
    assert v.normalize_journal("A Journal") != v.normalize_journal("The A Journal")


@pytest.mark.parametrize("a,b,same", [("09", "9", True), ("01--02", "1-2", True), ("9", "19", False),
                                      ("S1", "S01", False), ("Pt 2", "2", False)])
def test_issue_numbers_compare_numerically(a, b, same):
    assert (v.normalize_issue(a) == v.normalize_issue(b)) is same


# 4. Repeated byline; online-first year ----------------------------------------

def test_lanthier_duplicate_is_not_exact_and_the_year_is_online_first():
    entry, previous = case("LantEtal26")
    record = crossref(previous, "10.1093/sleepadvances/zpaf089")["record"]
    people, detail = v.collapse_repeated_byline(record["author"])
    assert detail is None and people == record["author"]  # 'Micheal-Christopher', no consortium
    # Genuinely online-first: issued/online 2025-12-12, print 2026-01-08.
    assert record["issued"]["date-parts"][0][0] == 2025 and record["published-print"]["date-parts"][0][0] == 2026
    assert not v.print_year_selects_cited(entry["fields"], record)
    assert status(entry, previous) == "needs_review"


def test_an_exact_repeated_byline_counts_once():
    # Derived from the real LantEtal26 record: its first (correct) 12-name byline
    # deposited twice verbatim, the shape this rule accepts.
    entry, previous = case("LantEtal26")
    record = deepcopy(crossref(previous, "10.1093/sleepadvances/zpaf089")["record"])
    first = [dict(p, affiliation=[]) for p in record["author"][:12]]
    record["author"] = record["author"][:12] + first
    evidence, _ = v.compare_record(entry["fields"], record)
    assert evidence["author"]["match"] and evidence["author"]["source_detail"] == v.REPEATED_BYLINE
    # Negative controls: one differing name, or a single repeated author (Gold87's
    # Halliburton record), is never collapsed.
    changed = deepcopy(record)
    changed["author"][-1]["given"] = "Rebecca"
    assert not v.compare_record(entry["fields"], changed)[0]["author"]["match"]
    single = [{"family": "Halliburton", "given": "W. D."}] * 2
    assert v.collapse_repeated_byline(single) == (single, None)


# 5/7. Publisher and container variants ----------------------------------------

def test_mann24_volume_pack_is_not_part_of_the_book_title():
    entry, previous = case("Mann24")
    record = crossref(previous, "10.1093/oxfordhb/9780190917982.013.38")["record"]
    evidence, issues = v.compare_record(entry["fields"], record)
    assert evidence["booktitle"]["match"]
    assert issues == ["editor: no deterministic verifier for this field"]  # no editor checker yet
    assert not v.compare_record(edited(entry, booktitle="The {Oxford} Handbook of Human Memory, Volume 1")["fields"],
                                record)[0]["booktitle"]["match"]


def test_mann23_is_diagnosed_not_ruled():
    # Crossref's container title lacks the subtitle, and a Crossref book/chapter
    # publisher is compared literally (tests/test_resolution_rules.py keeps book
    # imprints literal), so no registry rule is added; see the README.
    entry, previous = case("Mann23")
    record = crossref(previous, "10.1007/978-3-031-20910-9_48")["record"]
    evidence, issues = v.compare_record(entry["fields"], record)
    assert record["publisher"] == "Springer International Publishing"
    assert {"booktitle: missing evidence or mismatch", "publisher: missing evidence or mismatch"} <= set(issues)
    assert status(entry, previous) == "needs_review"


@pytest.mark.parametrize("cited,source,same", [
    ("{MIT} Press", "M.I.T. Press", True), ("{MIT} Press", "N.I.T. Press", False),
    ("Springer", "Springer International Publishing", True), ("Springer", "Springer-Verlag Berlin", True),
    ("Harcourt, Brace, and World", "Harcourt, Brace and Company", False),
])
def test_publisher_same_firm_with_dotted_acronyms(cited, source, same):
    assert catalogue_review.publisher_same_firm(cited, source) is same


def test_chomsky65_catalogue_mit_press_verifies():
    entry, previous = case("Chom65")
    assert status(entry, previous) == "metadata_verified"
    assert status(edited(entry, publisher="{Harvard} University Press"), previous) == "needs_review"
    assert status(edited(entry, year="1966"), previous) == "needs_review"


# 6. Historical journal names --------------------------------------------------

def test_chomsky56_ire_title_verifies_by_documented_history():
    entry, previous = case("Chom56")
    result = auto_review.reassess(entry, previous)
    assert result["status"] == "metadata_verified"
    chosen = crossref(result, "10.1109/tit.1956.1056813")
    assert chosen["evidence"]["journal"]["journal_history"]["issn"] == "0018-9448"
    for change in ({"year": "1963"}, {"volume": "9"}, {"journal": "{IRE} Transactions on Circuit Theory"}):
        assert status(edited(entry, **change), previous) == "needs_review", change
    other = deepcopy(previous)
    crossref(other, "10.1109/tit.1956.1056813")["record"]["ISSN"] = ["0096-1000"]
    assert status(entry, other) == "needs_review"  # the history row is ISSN-pinned
    assert v.normalize_journal("IRE Transactions on Information Theory") != \
        v.normalize_journal("IEEE Transactions on Information Theory")  # never an alias


# 8/9. Series numbers and proceedings names ------------------------------------

def test_kleene56_series_number_is_the_only_difference():
    entry, previous = case("Klee56")
    record = crossref(previous, "10.1515/9781400882618-002")["record"]
    evidence, issues = v.compare_record(entry["fields"], record)
    assert evidence["booktitle"]["match"]
    assert issues == ["address: no deterministic verifier for this field",
                      "editor: no deterministic verifier for this field"]
    assert not v.compare_record(edited(entry, booktitle="Automata Studies II")["fields"], record)[0]["booktitle"]["match"]


@pytest.mark.parametrize("source,house", [
    ("2017 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)",
     "IEEE Conference on Computer Vision and Pattern Recognition"),
    ("2005 IEEE Computer Society Conference on Computer Vision and Pattern Recognition (CVPR'05)",
     "IEEE Computer Society Conference on Computer Vision and Pattern Recognition"),
    ("Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th "
     "International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)",
     "Proceedings of the Conference on Empirical Methods in Natural Language Processing and the 9th "
     "International Joint Conference on Natural Language Processing"),
    ("Advances in Neural Information Processing Systems 30", "Advances in Neural Information Processing Systems 30"),
])
def test_proceedings_name_forms(source, house):
    assert v.proceedings_name_forms(source) == house


def test_bau17_proceedings_year_and_acronym_verify():
    entry, previous = case("BauEtal17")
    assert entry["fields"]["ENTRYTYPE"] == "inproceedings"
    assert status(entry, previous) == "metadata_verified"
    assert status(edited(entry, booktitle="{IEEE} International Conference on Computer Vision"), previous) == "needs_review"
    assert status(edited(entry, year="2016"), previous) == "needs_review"


def test_dalal05_still_differs_by_computer_society_and_missing_dates():
    entry, previous = case("DalaTrig05")
    record = crossref(previous, "10.1109/cvpr.2005.177")["record"]
    evidence, issues = v.compare_record(entry["fields"], record)
    assert not evidence["booktitle"]["match"] and v.YEAR_CONFLICT in issues
    assert status(entry, previous) == "needs_review"


# 10. Editions ----------------------------------------------------------------------

@pytest.mark.parametrize("a,b,same", [
    ("3\\textsuperscript{rd}", "Third edition", True), ("3\\textsuperscript{rd}", "3rd ed.", True),
    ("5\\textsuperscript{th}", "5th ed", True), ("3\\textsuperscript{rd}", "2nd ed", False),
    ("3\\textsuperscript{st}", "3rd ed.", False),
])
def test_house_edition_form(a, b, same):
    assert (catalogue_review.normalized_edition(a) == catalogue_review.normalized_edition(b)) is same


def test_sipser13_house_edition_verifies():
    entry, previous = case("Sips13")
    assert entry["fields"]["edition"] == "3\\textsuperscript{rd}"
    assert status(entry, previous) == "metadata_verified"
    assert status(edited(entry, edition="2\\textsuperscript{nd}"), previous) == "needs_review"
    assert status(edited(entry, edition=None), previous) == "needs_review"  # the record states an edition


# 11. Preprint relations ----------------------------------------------------------

def test_has_preprint_does_not_block_the_published_article():
    entry, previous = case("ChenEtal21")
    fixed = edited(entry, pages="4293--4304.e5")  # the source-backed entry fix
    record = crossref(previous, "10.1016/j.cub.2021.07.061")["record"]
    assert set(record["relation"]) == {"has-preprint"}
    assert status(fixed, previous) == "metadata_verified"
    # Without the entry's own DOI the documented final-article rule still holds
    # it (tests/test_resolution_rules.py::test_final_article_requires_its_own_explicit_doi).
    no_doi = edited(fixed, doi=None)
    assert v.compare_record(no_doi["fields"], record)[1] == [
        "Source has related versions/works; review publication identity"]
    # The PubMed record's "Preprint in" (PPR) link is not a correction.
    epmc = next(c for c in previous["candidates"] if c["source"] == "europepmc")
    assert not auto_review.blocking_pubmed_relationships(epmc["raw_record"])
    # Negative controls: wrong pages, a correction, a self-link and a non-version
    # relation still block.
    assert status(entry, previous) == "needs_review"
    for mutate in (lambda r: r.update({"updated-by": [{"DOI": "10.1016/j.cub.2021.99.999"}]}),
                   lambda r: r["relation"]["has-preprint"][0].update(id=r["DOI"]),
                   lambda r: r["relation"].update({"is-preprint-of": [{"id": "10.1/x", "id-type": "doi"}]})):
        changed = deepcopy(record)
        mutate(changed)
        assert v.compare_record(fixed["fields"], changed)[1], mutate
    comment = deepcopy(epmc["raw_record"])
    comment["commentCorrectionList"]["commentCorrection"].append(
        {"id": "PPR1", "source": "PPR", "type": "Erratum in"})
    assert auto_review.blocking_pubmed_relationships(comment)


def test_preprint_citation_of_a_published_record_is_not_accepted():
    entry, previous = case("SchwEtal22")
    record = crossref(previous, "10.1016/j.cub.2022.09.032")["record"]
    as_preprint = edited(entry, pages="4808--4816.e4", journal="{medRxiv}")
    assert "journal: missing evidence or mismatch" in v.compare_record(as_preprint["fields"], record)[1]


# 12. Route hooks -------------------------------------------------------------------

def test_registered_approval_validator_is_consulted_by_import_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "APPROVAL_VALIDATORS", [])
    entry, previous = case("Chom56")
    bib = write_bib(tmp_path / "c.bib", entry["raw"])
    loaded = v.load_entries(bib)["Chom56"]
    record = crossref(previous, "10.1109/tit.1956.1056813")["record"]

    def valid_demo_approval(result):
        # A route that re-derives its approval from the raw record it saved.
        saved = [c for c in result.get("candidates", []) if c.get("source") == "demo-route"]
        return (result.get("accepted_source") == "demo-route" and len(saved) == 1
                and v.compare_record(saved[0]["checked_fields"], saved[0]["raw_record"])[1] == [])

    approved = dict(v.outcome("metadata_verified", [], [{"source": "demo-route", "raw_record": record,
                                                        "checked_fields": loaded["fields"]}]),
                    accepted_source="demo-route", accepted_doi=record["DOI"])
    cache = v.Cache(tmp_path / "a.sqlite3")
    cache.put(bib, loaded, approved)
    snapshot = tmp_path / "s.jsonl.gz"
    v.export_snapshot(bib, cache, snapshot)
    with pytest.raises(ValueError, match="missing its source evidence"):
        v.import_snapshot(bib, v.Cache(tmp_path / "b.sqlite3"), snapshot)
    assert v.register_approval_validator(valid_demo_approval) is valid_demo_approval
    v.register_approval_validator(valid_demo_approval)
    assert v.APPROVAL_VALIDATORS == [valid_demo_approval]
    assert v.import_snapshot(bib, v.Cache(tmp_path / "c.sqlite3"), snapshot) == 1
    with pytest.raises(TypeError):
        v.register_approval_validator("not callable")


def test_registered_saved_reassessor_runs_in_reassess(monkeypatch):
    monkeypatch.setattr(auto_review, "SAVED_REASSESSORS", [])
    entry, previous = case("Chom56")
    before = auto_review.reassess(entry, previous)

    def reassess_saved_demo(fields, previous):
        saved = [c for c in previous.get("candidates", []) if c.get("source") == "demo-route"]
        if not saved:
            return None
        return v.outcome("needs_review", ["demo route disagrees"], previous["candidates"])

    auto_review.register_saved_reassessor(reassess_saved_demo, review_key="demo_review")
    assert auto_review.reassess(entry, previous) == before  # nothing saved: unchanged
    routed = dict(previous, candidates=previous["candidates"] + [{"source": "demo-route"}],
                  demo_review={"policy": "1"})
    result = auto_review.reassess(entry, routed)
    assert result["issues"] == ["demo route disagrees"] and result["demo_review"] == {"policy": "1"}


# 13. Missing-DOI advisory ----------------------------------------------------------

def test_missing_doi_advisory():
    entry, previous = case("PigeEtal12")
    result = auto_review.reassess(entry, previous)
    assert v.result_advisories(entry["fields"], result) == []  # the entry has its DOI
    no_doi = edited(entry, doi=None)
    result = auto_review.reassess(no_doi, previous)
    assert result["status"] == "metadata_verified"
    assert v.result_advisories(no_doi["fields"], result) == [
        f"missing DOI: 10.4088/jcp.11r07586 ({result['accepted_source']})"]
    held = auto_review.reassess(edited(no_doi, volume="74"), previous)
    assert v.result_advisories(no_doi["fields"], held) == []


# 14. Crossref surname mismatch vs PubMed: named for the user ------------------------
#
# User rule 2026-09-30 (verification/2026-09-29-user-review/CONFIRM.md, answer 5): "one
# source is sufficient; manual entry is the weakest part. notify user if mismatch is found
# and ask how they want to resolve it". Until then (registry-surname-typo, 2026-09-25) a
# Crossref surname that PubMed and other cdl.bib entries contradicted was resolved in the
# citation's favour. Now the finding stays open and names both spellings and both records.

@pytest.fixture
def library(tmp_path, monkeypatch):
    def make(*keys, extra=()):
        rows = [(k, STAGE1["library_authors"][k]["author"]) for k in keys] + list(extra)
        path = tmp_path / f"library{len(list(tmp_path.iterdir()))}.bib"
        path.write_text("\n\n".join(f"@article{{{k},\n\tAuthor = {{{a}}},\n\tTitle = {{T}},\n\tYear = {{2000}}}}"
                                    for k, a in rows) + "\n")
        monkeypatch.setattr(cp, "LIBRARY_BIB", path)
        return path
    return make


KOUNIOS = ("AngeEtal07", "JensEtal02", "Koun93", "Koun94", "SmitKoun96")
MEYER_DOI = "10.1037/0033-295x.95.2.183"


def meyer88():
    data = deepcopy(STAGE1["cases"]["MeyeEtal88"])
    return data["entry"], data["previous"]


def mutate_crossref(previous, mutate):
    changed = deepcopy(previous)
    for c in changed["candidates"]:
        if c["source"] == "crossref" and c["doi"] == MEYER_DOI:
            mutate(c["record"]["author"])
    return changed


def test_meyer88_crossref_mismatch_is_named_for_the_user(library):
    for make in (lambda: library(*KOUNIOS), lambda: library(extra=[("Other00", "A N Other")])):
        make()  # other cdl.bib entries spelling "Kounios" no longer matter
        entry, previous = meyer88()
        result = auto_review.reassess(entry, previous)
        assert result["status"] == "needs_review" and not result.get("accepted_source")
        epmc = next(c for c in result["candidates"] if c["source"] == "europepmc")
        assert not any(r.get("rule") == "registry-surname-typo" for r in epmc["resolved_findings"])
        (issue,) = [i for i in epmc["issues"] if i.startswith("author: surname mismatch")]
        assert ("author 4 is 'Kounios' in the citation and PubMed 3375399 but 'Kounois' in Crossref "
                f"{MEYER_DOI}") in issue
        assert f"https://api.crossref.org/works/{MEYER_DOI}" in issue and "user rule 2026-09-30" in issue
        assert result["issues"][0] == issue  # the entry's own finding names both spellings


def test_meyer88_agreeing_single_source_is_accepted():
    # agree -> accepted on one source: with Crossref's byline corrected to the printed
    # "Kounios", Crossref alone verifies the entry (no PubMed record, no library).
    entry, previous = meyer88()
    fixed = mutate_crossref(previous, lambda people: people[3].update(family="Kounios"))
    fixed["candidates"] = [c for c in fixed["candidates"] if c["source"] != "europepmc"]
    result = auto_review.reassess(entry, fixed)
    assert result["status"] == "metadata_verified" and result["accepted_source"] == "crossref"
    assert not any("surname mismatch" in i for i in result.get("issues", []))


def test_meyer88_negative_controls(library):
    library(*KOUNIOS)
    entry, previous = meyer88()
    for mutate, named in (
        (lambda people: people[3].update(family="Konstantinou"), "'Konstantinou' in Crossref"),
        (lambda people: people[2].update(family="Osmun"), "author 3 is 'Osman'"),
        (lambda people: people[3].update(given="K"), "'Kounois' in Crossref"),
    ):
        result = auto_review.reassess(entry, mutate_crossref(previous, mutate))
        assert result["status"] == "needs_review", named
        assert any(named in i for i in result["issues"]), (named, result["issues"])
    # an order change is not a spelling: the generic finding stays, nothing is named ...
    def swap(people):
        people[3]["family"] = "Kounios"
        people[0], people[1] = people[1], people[0]
    result = auto_review.reassess(entry, mutate_crossref(previous, swap))
    assert result["status"] == "needs_review"
    assert not any("surname mismatch" in i for i in result["issues"])
    # ... but a respelling beside it is still named, and only its own position
    def swap_only(people):
        people[0], people[1] = people[1], people[0]
    result = auto_review.reassess(entry, mutate_crossref(previous, swap_only))
    (issue,) = [i for i in result["issues"] if "surname mismatch" in i]
    assert "author 4 is 'Kounios'" in issue and "author 1" not in issue and "author 2" not in issue
    no_pubmed = deepcopy(previous)
    no_pubmed["candidates"] = [c for c in no_pubmed["candidates"] if c["source"] != "europepmc"]
    assert status(entry, no_pubmed) == "needs_review"


# 14. Stage 2B-i (2026-09-25): formatter key rule, publisher initials, route rechecks ---

SCHACTER94 = """@book{%s,
	Address = {Cambridge, {MA}},
	%s = {D L Schacter and E Tulving},
	Publisher = {{MIT} Press},
	Title = {Memory systems 1994},
	Year = {1994}}"""


def formatter_errors(tmp_path, raw):
    return helpers.check_bib(str(write_bib(tmp_path / "f.bib", raw)), verbose=False)[0]


def test_edited_volume_key_uses_editor_surnames(tmp_path, monkeypatch):
    # SchaTulv94 is an edited volume (LoC 4889423): with the author moved to editor,
    # the ID rule used to demand the year-only key "94".
    monkeypatch.chdir(ROOT)
    assert formatter_errors(tmp_path, SCHACTER94 % ("SchaTulv94", "Editor")) == {}
    assert formatter_errors(tmp_path, SCHACTER94 % ("SchaTulv94", "Author")) == {}
    # Negative controls: a wrong key is still rejected, with the editor-based target.
    assert formatter_errors(tmp_path, SCHACTER94 % ("Scha94", "Editor")) == {"Scha94": {"ID": "SchaTulv94"}}
    assert formatter_errors(tmp_path, SCHACTER94 % ("94", "Editor")) == {"94": {"ID": "SchaTulv94"}}


def test_editor_keys_share_suffixes_and_authors_take_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    # MeltMart72 and TulvDona72 (both edited volumes, 1972) used to collide as "72a"/"72b".
    two = ("@book{MeltMart72,\n\tEditor = {A W Melton and E Martin},\n\tPublisher = {Winston},\n"
           "\tTitle = {Coding processes in human memory},\n\tYear = {1972}}\n\n"
           "@book{TulvDona72,\n\tAddress = {New York, {NY}},\n\tEditor = {E Tulving and W Donaldson},\n"
           "\tPublisher = {Academic Press},\n\tTitle = {Organization of memory},\n\tYear = {1972}}")
    assert formatter_errors(tmp_path, two) == {}
    # An entry with both an author and editors keys on the author (the chapter's byline).
    chapter = ("@incollection{Tulv72,\n\tAuthor = {E Tulving},\n\tBooktitle = {Organization of Memory},\n"
               "\tEditor = {E Tulving and W Donaldson},\n\tPages = {381--403},\n\tPublisher = {Academic Press},\n"
               "\tTitle = {Episodic and semantic memory},\n\tYear = {1972}}")
    assert formatter_errors(tmp_path, chapter) == {}
    assert formatter_errors(tmp_path, chapter.replace("{Tulv72,", "{TulvDona72,")) == {"TulvDona72": {"ID": "Tulv72"}}
    # Same editor-based base key twice: the suffix rule applies to editor keys too.
    twins = (SCHACTER94 % ("SchaTulv94a", "Editor") + "\n\n"
             + SCHACTER94.replace("Memory systems 1994", "Memory systems 1994, second printing") % ("SchaTulv94b", "Editor"))
    assert formatter_errors(tmp_path, twins) == {}
    assert formatter_errors(tmp_path, twins.replace("SchaTulv94b", "SchaTulv94")) != {}


@pytest.mark.parametrize("publisher,house", [
    ("W.H. Freeman", "W H Freeman"), ("V. H. Winston", "V H Winston"), ("D.C. Heath", "D C Heath"),
    ("{W}. {H}. Freeman", "W H Freeman"), ("{D}. Appleton and Company", "D Appleton and Company"),
    ("W H Freeman", "W H Freeman"), ("V H Winston", "V H Winston"), ("Alfred A Knopf", "Alfred A Knopf"),
    ("Freeman", "Freeman"),
])
def test_publisher_initials_use_the_house_form(publisher, house):
    # User decision 2026-09-25 07:37 EDT ("W.H. Freeman should be W H Freeman"), reversing stage 2B-i's
    # dotted-initials rule: publisher initials are undotted and space-separated, like author
    # initials. The formatter used to rewrite "W.H. Freeman" as "W.h. Freeman" (Marr82) and
    # to brace undotted initials ("{W} {H} Freeman").
    assert helpers.format_journal_name(publisher, key=helpers.publisher_key, dotted_initials=True) == house
    assert helpers.format_journal_name(house, key=helpers.publisher_key, dotted_initials=True) == house


@pytest.mark.parametrize("publisher,house", [
    ("w.h. freeman", "W.h. Freeman"), ("Henry holt and company", "Henry Holt and Company"),
    ("Lawrence Erlbaum Associates", "Erlbaum"), ("Wh. Freeman", "Wh. Freeman"),
])
def test_publisher_negative_controls_still_formatted(publisher, house):
    # Lowercase or non-initial tokens are formatted as before; aliases still apply.
    assert helpers.format_journal_name(publisher, key=helpers.publisher_key, dotted_initials=True) == house


def test_marr82_publisher_passes_check_bib(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    raw = ("@book{Marr82,\n\tAuthor = {D Marr},\n\tPublisher = {%s},\n\tTitle = {Vision: a computational "
           "investigation into the human representation and processing of visual information},\n\tYear = {1982}}")
    assert formatter_errors(tmp_path, raw % "W H Freeman") == {}
    assert formatter_errors(tmp_path, raw % "W.H. Freeman") == {"Marr82": {"publisher": "W H Freeman"}}
    assert formatter_errors(tmp_path, raw % "W.h. freeman") == {"Marr82": {"publisher": "W.h. Freeman"}}
    # The initials rule is a publisher rule only: journal names are formatted as before.
    assert helpers.format_journal_name("W.H. Freeman", key=helpers.publisher_key) == "W.h. Freeman"


def route_bib(tmp_path, key, fields):
    body = ",\n".join(f"\t{name.capitalize()} = {{{value}}}" for name, value in sorted(fields.items())
                      if name not in {"ENTRYTYPE", "ID"})
    return write_bib(tmp_path / "r.bib", "@%s{%s,\n%s}" % (fields.get("ENTRYTYPE", "article"), key, body))


def recheck(tmp_path, key, fields, approval):
    bib = route_bib(tmp_path, key, fields)
    entry = v.load_entries(bib)[key]
    cache = v.Cache(tmp_path / "recheck.sqlite3")
    try:
        cache.put(str(bib), entry, approval)
        client = v.PoliteClient(cache, "jeremy.r.manning@dartmouth.edu")
        results = v.run_verification(str(bib), cache, client, str(tmp_path / "report.jsonl"),
                                     keys=[key], recheck_cached=True)
        rows = cache.db.execute("SELECT count(*) FROM reviews").fetchone()[0]
        return results[key], client.requests, rows
    finally:
        cache.close()


def route_case(module, fixture, key):
    import importlib
    data = json.loads((ROOT / "tests/fixtures/routes" / fixture).read_text())
    return importlib.import_module(module), deepcopy(data[key])


def test_recheck_cached_keeps_the_franliu18_osf_approval(tmp_path):
    # reassess002 attempt 2: verify --recheck-cached re-derived FranLiu18's osf-repository
    # approval from Crossref evidence only and reopened it on every run.
    o, c = route_case("osf_review", "osf_review.json", "FranLiu18")
    approval = o.assess_osf(c["fields"], c["raw"])
    assert approval["status"] == "metadata_verified" and approval["accepted_source"] == "osf-repository"
    entry = v.load_entries(route_bib(tmp_path, "FranLiu18", c["fields"]))["FranLiu18"]
    assert auto_review.reassess(entry, approval)["status"] == "needs_review"  # the recheck path alone reopens it
    result, requests, rows = recheck(tmp_path, "FranLiu18", c["fields"], approval)
    assert result["status"] == "metadata_verified" and result["accepted_source"] == "osf-repository"
    assert requests == 0 and rows == 1  # nothing written: a fixed point


def test_recheck_cached_still_reopens_an_invalid_route_approval(tmp_path):
    o, c = route_case("osf_review", "osf_review.json", "FranLiu18")
    approval = o.assess_osf(c["fields"], c["raw"])
    approval["candidates"][0]["checked_fields"]["year"] = "1999"  # tampered: the validator rejects it
    assert not v.route_approval_valid(approval)
    result, requests, rows = recheck(tmp_path, "FranLiu18", c["fields"], approval)
    assert result["status"] == "needs_review" and requests == 0 and rows == 2


def test_recheck_cached_keeps_arxiv_approvals(tmp_path):
    import arxiv_review as a
    c = deepcopy(json.loads((ROOT / "tests/fixtures/arxiv_preprints.json").read_text())["PianHill22"])
    approval = a.assess_arxiv(c["fields"], c["raw"])
    assert approval["status"] == "metadata_verified"
    result, requests, _ = recheck(tmp_path, "PianHill22", c["fields"], approval)
    assert result["status"] == "metadata_verified" and requests == 0


# 15. Stage 2B-ii (2026-09-25): ordinals, proceedings names, publisher initials ---------
# Real records frozen from verification/baseline.jsonl.gz (89c5b70) by
# verification/apply-2026-09-25d/build_cases.py.

CASES27 = json.loads(gzip.open(ROOT / "tests/fixtures/apply-2026-09-25d-cases.json.gz").read())["cases"]


def case27(key, **fields):
    data = deepcopy(CASES27[key])
    data["fields"].update(fields)
    return data


@pytest.mark.parametrize("value,text", [
    ("Proceedings of the 30\\textsuperscript{th} Annual Conference", "proceedings of the 30th annual conference"),
    ("2\\textsuperscript{nd}", "2nd"), ("The 21\\textsuperscript{st} century", "the 21st century"),
])
def test_normalized_reads_house_ordinals(value, text):
    assert v.normalized(value) == text


@pytest.mark.parametrize("value", ["x\\textsuperscript{2}", "\\textsuperscript{th}", "E = mc\\textsuperscript{2}"])
def test_other_superscripts_still_need_review(value):
    # Only a number followed by an ordinal suffix is read; any other superscript is markup.
    with pytest.raises(ValueError):
        v.normalized(value)


@pytest.mark.parametrize("a,b,same", [
    ("thirtieth annual conference", "30th annual conference", True),
    ("proceedings of the twenty-fourth annual", "proceedings of the 24th annual", True),
    ("twenty first annual", "21st annual", True),
    ("the third edition", "the 3rd edition", True),
    ("eleventh workshop", "11th workshop", True),
    ("thirtieth annual conference", "31st annual conference", False),
    ("thirty annual", "30th annual", False),
    ("the 3rd edition", "the 3th edition", False),
    ("first", "1th", False),
])
def test_ordinal_words_equal_numeric_ordinals(a, b, same):
    assert (v.ordinal_form(a) == v.ordinal_form(b)) is same


def test_house_ordinal_booktitle_still_matches_crossref():
    # NguyEtal18 is verified from Crossref with "16th"; the house form must still match.
    c = case27("NguyEtal18")
    evidence, _ = v.compare_record(c["fields"], c["record"])
    assert evidence["booktitle"]["match"]
    booktitle = c["fields"]["booktitle"].replace("16th", "16\\textsuperscript{th}")
    evidence, issues = v.compare_record(dict(c["fields"], booktitle=booktitle), c["record"])
    assert evidence["booktitle"]["match"] and not any(i.startswith("booktitle") for i in issues)
    # Negative control: a wrong ordinal does not match.
    evidence, _ = v.compare_record(dict(c["fields"], booktitle=booktitle.replace("16", "17")), c["record"])
    assert not evidence["booktitle"]["match"]


def test_numeric_house_ordinal_matches_a_word_ordinal_source():
    # AltmSchu02's Crossref chapter record names "the Twenty-Fourth Annual Conference".
    c = case27("AltmSchu02")
    assert "Twenty-Fourth" in c["record"]["container-title"][0]
    cited = "Proceedings of the 24\\textsuperscript{th} Annual Conference of the Cognitive Science Society"
    evidence, _ = v.compare_record(dict(c["fields"], booktitle=cited), c["record"])
    assert evidence["booktitle"]["match"]
    evidence, _ = v.compare_record(dict(c["fields"], booktitle=cited.replace("24", "25")), c["record"])
    assert not evidence["booktitle"]["match"]
    evidence, _ = v.compare_record(dict(c["fields"], booktitle=cited.replace("24\\textsuperscript{th} ", "")),
                                   c["record"])
    assert not evidence["booktitle"]["match"]


def test_proceedings_name_without_year_keeps_its_acronym():
    # CarvEtal22a (verified): the house form drops the year but the citation keeps "({comsnets})".
    c = case27("CarvEtal22a")
    assert v.compare_record(c["fields"], c["record"])[0]["booktitle"]["match"]
    house = "14\\textsuperscript{th} International Conference on Communication Systems \\& Networks ({comsnets})"
    evidence, issues = v.compare_record(dict(c["fields"], booktitle=house), c["record"])
    assert evidence["booktitle"]["match"] and not any(i.startswith("booktitle") for i in issues)
    # Without the acronym (year and acronym both dropped) still matches, as before.
    evidence, _ = v.compare_record(dict(c["fields"], booktitle=house.replace(" ({comsnets})", "")), c["record"])
    assert evidence["booktitle"]["match"]
    # Negative controls: another ordinal, another acronym, a year that is not the source's.
    for wrong in (house.replace("14", "15"), house.replace("comsnets", "infocom"),
                  "2021 " + house.replace("\\textsuperscript{th}", "th")):
        assert not v.compare_record(dict(c["fields"], booktitle=wrong), c["record"])[0]["booktitle"]["match"]


@pytest.mark.parametrize("key,house", [("Marr82", "W H Freeman"), ("MeltMart72", "V H Winston")])
def test_catalogue_publisher_initials_match_the_house_form(key, house):
    # LoC prints "W.H. Freeman" / "V. H. Winston"; the house form is undotted.
    c = case27(key)
    record = catalogue_review.parse_edition(c["raw_marcxml"])
    evidence, issues = catalogue_review.compare_edition(c["fields"], record, c["raw_marcxml"])
    assert evidence["publisher"]["match"] and not issues
    evidence, issues = catalogue_review.compare_edition(dict(c["fields"], publisher=house), record, c["raw_marcxml"])
    assert evidence["publisher"]["match"] and not issues
    assert "source_name_variant" not in evidence["publisher"]  # an exact match, not the same-firm fallback
    # Negative control: other initials are a different publisher.
    evidence, _ = catalogue_review.compare_edition(dict(c["fields"], publisher="J H Freeman" if key == "Marr82"
                                                        else "V J Winston"), record, c["raw_marcxml"])
    assert not evidence["publisher"]["match"]


@pytest.mark.parametrize("a,b,same", [
    ("W.H. Freeman", "W H Freeman", True), ("W. H. Freeman", "W H Freeman", True),
    ("{W}. {H}. Freeman", "W H Freeman", True), ("D. Appleton and Company", "D Appleton and Company", True),
    ("W.H. Freeman", "J H Freeman", False), ("W.H. Freeman", "WH Freeman", False),
])
def test_publisher_initials_compare_undotted(a, b, same):
    assert (v.publisher_initials(v.normalized(a)) == v.publisher_initials(v.normalized(b))) is same


# 16. verify/commit gate: format check + citation verification of changed entries ------
# User decisions 2026-09-25 07:42 and 07:44 EDT: `bibcheck.py verify` and `bibcheck.py commit` share one gate
# (bibcheck.py check_library). Real entry (cdl.bib Rame72, verified from Crossref
# 10.1016/S0146-664X(72)80017-0); the citation check makes real Crossref requests into a
# fresh cache in tmp_path. No mocks.

RAME72 = ("@article{Rame72,\n\tAuthor = {U Ramer},\n\tDoi = {10.1016/S0146-664X(72)80017-0},\n"
          "\tJournal = {Computer Graphics and Image Processing},\n\tNumber = {3},\n\tPages = {244--256},\n"
          "\tTitle = {An iterative procedure for the polygonal approximation of plane curves},\n"
          "\tVolume = {%s},\n\tYear = {1972}}")
ZOLL90 = ("@article{Zoll90,\n\tAuthor = {U Zoller},\n\tDoi = {10.1002/tea.3660271011},\n"
          "\tJournal = {Journal of Research in Science Teaching},\n\tNumber = {10},\n\tPages = {1053--1065},\n"
          "\tTitle = {Students' misunderstandings and misconceptions in college freshman chemistry (general and "
          "organic)},\n\tVolume = {27},\n\tYear = {1990}}")


def crossref_contact():
    """The contact the project's runs already send to Crossref (CROSSREF_MAILTO, else the
    mailto recorded in the main cache's Crossref responses); a real address is required."""
    import os
    import sqlite3
    if os.environ.get("CROSSREF_MAILTO"):
        return os.environ["CROSSREF_MAILTO"]
    missing = ("Set CROSSREF_MAILTO to a real contact address; these tests call the live Crossref API "
               "(in CI: the repository Actions variable CROSSREF_MAILTO)")
    cache = ROOT / ".bibcheck/verification.sqlite3"
    if not cache.is_file():
        pytest.fail(f"{missing}. No CROSSREF_MAILTO in the environment and no local cache at {cache}.")
    db = sqlite3.connect(f"file:{cache}?mode=ro", uri=True)
    try:
        row = db.execute("SELECT body FROM responses WHERE body LIKE '%api.crossref.org%mailto=%' LIMIT 1").fetchone()
    finally:
        db.close()
    if row is None:
        pytest.fail(f"{missing}. The local cache {cache} holds no Crossref request with a mailto.")
    from urllib.parse import parse_qs, urlparse
    return parse_qs(urlparse(json.loads(row[0])["url"]).query)["mailto"][0]


def gate(tmp_path, *args):
    env = dict(__import__("os").environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools",
               CROSSREF_MAILTO=crossref_contact())
    return subprocess.run([sys.executable, str(ROOT / "bibcheck.py"), *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=1800)


def gate_files(tmp_path, volume):
    base = write_bib(tmp_path / "base.bib", ZOLL90)
    new = write_bib(tmp_path / "new.bib", ZOLL90 + "\n\n" + RAME72 % volume)
    return base, new


def test_verify_passes_a_correct_changed_entry(tmp_path):
    base, new = gate_files(tmp_path, "1")
    run = gate(tmp_path, "verify", "--fname", str(new), "--reference", str(base),
               "--database", str(tmp_path / "db.sqlite3"))
    assert run.returncode == 0, run.stdout + run.stderr
    assert "citations: 1 of 1 new/edited entries verified" in run.stdout
    assert "library: 2 entries" in run.stdout  # Zoll90 is unchanged: reported, not checked
    assert "looks good!" in run.stdout


def test_verify_fails_a_wrong_changed_entry_and_shows_its_issue(tmp_path):
    base, new = gate_files(tmp_path, "2")  # Crossref: volume 1
    run = gate(tmp_path, "verify", "--fname", str(new), "--reference", str(base),
               "--database", str(tmp_path / "db.sqlite3"))
    assert run.returncode == 1, run.stdout + run.stderr
    assert "UNRESOLVED Rame72" in run.stdout and "volume" in run.stdout
    assert "review-packet" in run.stdout and "looks good!" not in run.stdout.replace("format: looks good!", "")


def test_verify_no_citations_is_offline_and_format_only(tmp_path):
    base, new = gate_files(tmp_path, "2")
    run = gate(tmp_path, "verify", "--fname", str(new), "--reference", str(base), "--no-citations",
               "--database", str(tmp_path / "db.sqlite3"))
    assert run.returncode == 0 and "citations:" not in run.stdout and "looks good!" in run.stdout
    assert not (tmp_path / "db.sqlite3").exists()
    bad = write_bib(tmp_path / "bad.bib", (RAME72 % "1").replace("244--256", "244--24"))
    run = gate(tmp_path, "verify", "--fname", str(bad), "--no-citations")
    assert run.returncode == 1 and "Rame72" in run.stderr


def test_commit_refuses_an_unresolved_entry_and_commits_only_the_bib(tmp_path):
    import os
    env = dict(os.environ, DEVELOPER_DIR="/Library/Developer/CommandLineTools")
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout

    git("init", "-q")
    base = write_bib(tmp_path / "base.bib", ZOLL90)
    bib = write_bib(repo / "cdl.bib", ZOLL90)
    (repo / "notes.txt").write_text("original\n")
    git("add", "cdl.bib", "notes.txt")
    git("commit", "-q", "-m", "base")
    (repo / "notes.txt").write_text("edited, must not be committed\n")
    db = str(tmp_path / "db.sqlite3")
    bib.write_text(ZOLL90 + "\n\n" + RAME72 % "2" + "\n")
    run = gate(tmp_path, "commit", "--fname", str(bib), "--reference", str(base), "--database", db)
    assert run.returncode == 1 and "UNRESOLVED Rame72" in run.stdout and "not committed" in run.stdout
    assert git("rev-list", "--count", "HEAD").strip() == "1"
    bib.write_text(ZOLL90 + "\n\n" + RAME72 % "1" + "\n")
    run = gate(tmp_path, "commit", "--fname", str(bib), "--reference", str(base), "--database", db)
    assert run.returncode == 0, run.stdout + run.stderr
    assert git("rev-list", "--count", "HEAD").strip() == "2"
    assert git("show", "--name-only", "--format=%s", "HEAD").split() [-1] == "cdl.bib"
    assert "Rame72" in git("log", "-1", "--format=%B")
    assert "notes.txt" in git("status", "--porcelain")  # the other edit stays uncommitted


def test_verify_all_checks_unchanged_entries_too(tmp_path):
    same = write_bib(tmp_path / "same.bib", RAME72 % "1")
    db = str(tmp_path / "db.sqlite3")
    run = gate(tmp_path, "verify", "--fname", str(same), "--reference", str(same), "--database", db)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "citations: 0 of 0 new/edited entries verified; network requests: 0" in run.stdout
    assert "library: 1 entries: pending=1" in run.stdout  # reported, not checked, not failing
    run = gate(tmp_path, "verify", "--fname", str(same), "--reference", str(same), "--all", "--database", db)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "citations: 1 of 1 entries verified" in run.stdout
    assert "library: 1 entries: metadata_verified=1" in run.stdout


# --- reformat_author keeps LaTeX-accented initials whole (ZhenEtal20, 2026-09-25) ---------
@pytest.mark.parametrize("cited, expected", [
    ("M {\\'A} Serrano", "M {\\'A} Serrano"),        # braced accent group, the ZhenEtal20 case
    ("M \\'A Serrano", "M \\'A Serrano"),            # unbraced accent macro
    ("M {\\'{A}} Serrano", "M {\\'{A}} Serrano"),    # doubly braced
    ("{\\'E} Durkheim", "{\\'E} Durkheim"),
    ("{\\v{S}} Novak", "{\\v{S}} Novak"),            # letter-named accent macro
    ("M{\\'A} Serrano", "M {\\'A} Serrano"),         # clumped initials still unclump by letter
    ("MA Serrano", "M A Serrano"),                   # negative control: plain clump unchanged
    ("É Durkheim", "É Durkheim"),
])
def test_reformat_author_keeps_latex_accented_initials(cited, expected):
    from helpers import reformat_author
    assert reformat_author(cited) == expected
