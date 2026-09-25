"""Machinery fixes found by testing on real PRs #87 and #88 (2026-09-25).

verification/pr-check-2026-09-25/README.md lists the false rejections; the
rules are documented in verification/machinery-2026-09-25/README.md. Real PR
entries and their cached review rows are frozen in
verification/machinery-2026-09-25/cases.json.gz (build_cases.py); MeyeEtal88 is
the frozen stage 1 case in verification/apply-2026-09-25/cases.json.gz. Every
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

CASES = json.loads(gzip.open(ROOT / "verification/machinery-2026-09-25/cases.json.gz").read())["cases"]
STAGE1 = json.loads(gzip.open(ROOT / "verification/apply-2026-09-25/cases.json.gz").read())


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
    run = subprocess.run([sys.executable, "bibcheck.py", "verify", "--fname", str(good)], cwd=ROOT,
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


# 14. Crossref surname typo vs PubMed + library consensus ---------------------------

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


def meyer88():
    data = deepcopy(STAGE1["cases"]["MeyeEtal88"])
    return data["entry"], data["previous"]


def test_meyer88_crossref_typo_yields_to_pubmed_and_library_consensus(library):
    library(*KOUNIOS)
    entry, previous = meyer88()
    result = auto_review.reassess(entry, previous)
    assert result["status"] == "metadata_verified" and result["accepted_source"] == "europepmc"
    epmc = next(c for c in result["candidates"] if c["source"] == "europepmc")
    (resolved,) = epmc["resolved_findings"]
    assert resolved["rule"] == "registry-surname-typo" and resolved["registry_surname"] == "Kounois"
    assert resolved["library_consensus"] == sorted(KOUNIOS)
    assert v.result_advisories(entry["fields"], result) == ["missing DOI: 10.1037/0033-295x.95.2.183 (europepmc)"]


def test_meyer88_negative_controls(library):
    entry, previous = meyer88()
    library(extra=[("Other00", "A N Other")])  # no library consensus
    assert status(entry, previous) == "needs_review"
    library(*KOUNIOS, extra=[("Other00", "J Kounois")])  # the typo is used elsewhere
    assert status(entry, previous) == "needs_review"
    library(*KOUNIOS)
    for mutate in (
        lambda people: people[3].update(family="Konstantinou"),  # not a spelling slip
        lambda people: people[2].update(family="Osmun"),         # a second position differs
        lambda people: people[3].update(given="K"),              # another person
    ):
        changed = deepcopy(previous)
        for c in changed["candidates"]:
            if c["source"] == "crossref" and c["doi"] == "10.1037/0033-295x.95.2.183":
                mutate(c["record"]["author"])
        assert status(entry, changed) == "needs_review", mutate
    no_pubmed = deepcopy(previous)
    no_pubmed["candidates"] = [c for c in no_pubmed["candidates"] if c["source"] != "europepmc"]
    assert status(entry, no_pubmed) == "needs_review"


# 14. Stage 2B-i (2026-09-26): formatter key rule, publisher initials, route rechecks ---

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


@pytest.mark.parametrize("publisher", ["W.H. Freeman", "V. H. Winston", "D.C. Heath", "{W}. {H}. Freeman",
                                       "{D}. Appleton and Company", "Freeman"])
def test_publisher_dotted_initials_are_preserved(publisher):
    # Marr82 (LoC 3260955): the formatter used to rewrite "W.H. Freeman" as "W.h. Freeman".
    assert helpers.format_journal_name(publisher, key=helpers.publisher_key, dotted_initials=True) == publisher


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
    assert formatter_errors(tmp_path, raw % "W.H. Freeman") == {}
    assert formatter_errors(tmp_path, raw % "W.h. freeman") == {"Marr82": {"publisher": "W.h. Freeman"}}
    # Dotted initials are a publisher rule only: journal names are formatted as before.
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
    data = json.loads((ROOT / "verification/routes-2026-09-25/fixtures" / fixture).read_text())
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
