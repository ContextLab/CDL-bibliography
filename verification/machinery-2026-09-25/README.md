# Machinery fixes from the PR #87/#88 test (2026-09-25)

[../pr-check-2026-09-25/README.md](../pr-check-2026-09-25/README.md) ran PRs #87 and #88
through the verifier and listed the entries it rejected although they were correct
("MACHINERY-WRONG"). This directory holds the code fixes for those false rejections, the
real cases the tests use, and an offline measurement of what the fixes change in cdl.bib.
The fixes change no BibTeX file and do not write to the cache. `RESOLVER_VERSION` is now 30.

Tests: `tests/test_machinery_2026_09_25.py`. They use real records: the PR entries and their
cached review rows, frozen in [`cases.json.gz`](cases.json.gz) by
[`build_cases.py`](build_cases.py) from the PR check's scratch cache (read-only), and the stage 1
MeyeEtal88 case. Every rule has negative controls.

## Rules

| # | Rule | Where | Real case | Negative controls |
|-|-|-|-|-|
| 1 | The formatter accepts a dotted alphanumeric article number (`IMAG.a.136`: starts with a letter, contains a digit, has no hyphen). `1417--1427.e6` was already accepted. | `helpers.valid_page` | KothEtal25 | `e.g.`, `136.a`, `IMAG.a.136--IMAG.a.140`, `1417--1427.e0` |
| 1 | `check_bib` raises "duplicate fields found" for a field given twice in one entry. bibtexparser used to keep one value without saying so. | `helpers.duplicate_fields` | the #88 merge shape (two `Doi` lines) | the entry itself |
| 1 | `bibcheck.py verify`, `magic` and `commit` print the exception and exit 1. They used to print "errors found" and exit 0 (bare `except`). A whole author name that cannot be parsed is now an error; a fragment of hyphenated initials (`X` of `J-X`) is not rearranged. | `bibcheck.py run_check`, `helpers.reformat_author` | KothEtal25 range error | a good entry exits 0 |
| 2 | A Crossref author `suffix` made up only of degrees or titles (`MD, FACP`, `Ph. D.`, `MS, MPH`, `BA`) is not part of the name. This applies to the source side only, in `author_evidence` and `compatible_authors`. | `verification.degree_suffix` | Schr03 verifies; FeliEtal98's authors now match | `Jr`, `III`, `MD, Jr`, `Smith`; surname or initial changes |
| 3 | A leading "The" is ignored when a cited journal is compared with the ISSN-bearing record of the cited DOI or search hit. `normalize_journal` itself is unchanged: it keeps "A Journal" and "The A Journal" apart for every other use (`tests/test_metadata_punctuation.py`). | `verification.registry_journal_match` | PigeEtal12 verifies | `Theoretical ...`, `(Paris)`, a record without ISSN, a different journal |
| 3 | An all-digit issue (or digit range) compares numerically (`09` = `9`). | `verification.normalize_issue` | PigeEtal12 | `9`/`19`, `S1`/`S01`, `Pt 2`/`2`, a wrong issue |
| 4 | A byline listed twice verbatim counts once. Only a repeated sequence of at least two names qualifies, and family, given, organization name and suffix must be identical. | `verification.collapse_repeated_byline` | a copy of LantEtal26's own first byline | LantEtal26's real record; a single repeated author (Gold87) |
| 6 | Journal history, pinned by ISSN: a citation of the historical title within its documented years and volumes matches the record's current title. | `verification.JOURNAL_HISTORY` | Chom56 (IRE, 1956, vol 2) verifies | year 1963, volume 9, another IRE title, another ISSN |
| 7 | Catalogue publisher same-firm: dotted acronyms are collapsed (`M.I.T. Press` = `MIT Press`). A catalogue record that matches exactly is never outvoted by a correction proposal from another record (`propose_corrections` reports `several-plausible-editions` or `cited-edition-matches`). | `catalogue_review.collapse_dotted_acronyms`, `propose_corrections` | Chom65 verifies; Feyn65 (MIT and BBC printings) proposes nothing | `N.I.T. Press`; `Harcourt, Brace ...`; another publisher |
| 8 | A series number printed after a book title (`Automata Studies. (AM-34)`) is ignored when it is the only difference. This covers the chapter's `booktitle` and a `@book` title. | `verification.book_title_forms` | Klee56 booktitle matches | `Automata Studies II` |
| 5 | A multi-volume packaging tail on a book title (`..., Two Volume Pack`) is ignored the same way. | `verification.book_title_forms` | Mann24 booktitle matches | `..., Volume 1` |
| 9 | A proceedings name from the source is compared without its four-digit year and without a final parenthetical acronym (house rule: booktitles omit the year). Ordinals and every other word are kept. | `verification.proceedings_name_forms` | BauEtal17 verifies | another conference; wrong year |
| 10 | The house edition form `3\textsuperscript{rd}` reads as `3rd` = `Third edition` = `3rd ed.` | `catalogue_review.normalized_edition` | Sips13 verifies | 2nd edition, `3\textsuperscript{st}`, a missing edition |
| 11 | Crossref `has-preprint` on the cited article already passes when the entry carries the article's own DOI and every other field matches (`explicit_final_article`, resolver 28). In the PR run it "blocked" only next to a real finding (ChenEtal21/SchwEtal22 pages lacked `.e5`/`.e4`). The fix is on the PubMed side: Europe PMC's `Preprint in` (source PPR) link is version provenance, not a correction, so the DOI-linked PubMed record is usable. Without the entry's DOI, `has-preprint` still holds the entry (documented rule, `test_final_article_requires_its_own_explicit_doi`). | `auto_review.blocking_pubmed_relationships` | ChenEtal21 with its source-backed `.e5` pages verifies | wrong pages, no DOI, `updated-by`, self-link, `is-preprint-of`, `Erratum in` |
| 13 | Missing-DOI advisory: a verified entry with no `doi` whose accepted record has one is reported as `missing DOI: <doi> (<source>)`. The advisory goes in `report_advisories` in `write_report` rows and is never a failure. | `verification.result_advisories` | MeyeEtal88, PigeEtal12 without its DOI | an entry with a DOI; a held entry |
| 14 | **Retired 2026-09-30** by the user's rule (a surname mismatch is the user's to resolve; see [apply-2026-09-30-surnames](../apply-2026-09-30-surnames/README.md)). Was: registry surname typo: the DOI-linked PubMed record may resolve Crossref's author finding when all of the following hold: (a) PubMed matches the citation on title, byline, year, journal, volume and pages, and Crossref matches on all but the byline; (b) the records share an ISSN; (c) exactly one surname differs, by at most two edits (both at least 4 letters), with agreeing given names; (d) library consensus: other cdl.bib entries use the cited spelling for that person and none uses Crossref's. The resolution records the rule, both spellings and the consensus keys. | `auto_review.registry_surname_typo` | MeyeEtal88 (Kounois/Kounios; AngeEtal07, JensEtal02, Koun93, Koun94, SmitKoun96) verifies | no consensus; the typo used elsewhere; a far-off surname; two positions differ; a different initial; no PubMed record |

The Chom56 history row is based on LC record 11278887 (LCCN sn79018898, ISSN 0096-1000,
checked 2026-09-25 through `lx2.loc.gov/sru/lcdb`): 245 "IRE transactions on information theory.";
362 "Vol. IT-1, no. 1 (Mar. 1955)-v. IT-8, no. 6 (Oct. 1962)."; 785 "IEEE transactions on
information theory 0018-9448". Crossref deposits the 1955–1962 issues under ISSN 0018-9448.

## Diagnosed, no rule added

- **LantEtal26.** The duplicated byline is not an exact repetition: the second copy has
  "Micheal-Christopher" and drops the consortium, so the rule does not apply. The year is
  online-first: published-online and issued are 2025-12-12, published-print is 2026-01-08.
  The documented print-year rule accepts a cited year only when both print and issued equal it.
  Accepting this record would need a new user decision on online-first records, so it stays needs_review.
- **Mann23.** Crossref's container title is "Intracranial EEG", without the subtitle "a guide
  for cognitive neuroscientists". No cached source states the subtitle. Accepting it would
  need the parent book's record (the Phase 3 "chapter two-layer rule"). The publisher
  ("Springer International Publishing") is also still a mismatch. Existing tests
  (`test_publisher_rule_does_not_change_titles_or_book_imprints`,
  `test_ieee_expansion_is_confined_to_article_publisher_comparison`) keep Crossref book
  imprints literal, so the same-firm rule was not extended to them. That would need a user decision.
- **Mann24, Klee56, Mann23.** `editor` (and Klee56's `address`) still have no deterministic
  verifier, so these @incollection entries stay needs_review even with a matching booktitle.
- **DalaTrig05.** After the year and acronym are removed, the source name keeps "Computer
  Society", which the citation lacks. The record also has no dates. This is a real
  difference, not machinery.
- **FeliEtal98.** The authors now match, but the title still differs: Crossref's title is
  truncated. The PubMed record (9635069) was not fetched in the PR run.

## Route hooks (for new source routes)

A new route module needs no edits to `verification.py` or `auto_review.py`:

- `verification.register_approval_validator(fn)`: `fn(result) -> bool` re-derives an
  approval from the evidence saved in the result (as `arxiv_review.valid_arxiv_approval`
  does). `import_snapshot` accepts a machine approval when a built-in check or any registered
  validator accepts it (`verification.route_approval_valid`). The module must be imported
  (and so registered) before a snapshot is imported. Otherwise its approvals are rejected
  with "Machine approval is missing its source evidence".
- `auto_review.register_saved_reassessor(fn, review_key=None)`: `fn(fields, previous) ->
  result | None` rebuilds the route's decision from its saved raw evidence, as
  `reassess_saved_arxiv` does, and returns None when nothing is saved. Registered routes run
  after the built-in ones. `previous[review_key]` is carried over.

## Offline measurement

[`measure.py`](measure.py) opens the main cache read-only (no writes, no network), re-runs
`reassess` on every current result, and writes [`newly-verifiable.json`](newly-verifiable.json).
That file holds the newly verifiable keys with the rules each depends on, any verified entry
that would be lost (none allowed), per-key errors, and the missing-DOI advisory counts.
Results are summarized below.

Result on 2026-09-25 (cdl.bib 4,034 metadata_verified / 2,388 needs_review):

- **18 needs_review entries verify with no BibTeX edit.** None of the currently verified
  entries is lost, and no entry raised an error. Attribution (the rule each depends on):
  - pubmed-preprint-link (5): JonaKord17, LeeEtal21, Mada21, NguyEtal22, WangEtal19. The PMC
    JATS route was blocked only by PubMed's "Preprint in" (PPR) link.
  - issue-numeric (5): BradLang00, GilmEtal79, HogeEtal99, NieuEtal01, SawrEtal96.
  - surname-typo (6): MeyeEtal88 (Kounois/Kounios), NoldEtal98 (Crossref "DʼEsposito"
    with a modifier apostrophe; 19 library entries), SchaEtal11, StJaEtal08, StJaEtal12 and
    StJaScha13 (Crossref "St. Jacques"; PubMed and library "St Jacques").
  - leading-the (1): DaviDavi12.
  - dotted-acronym + same-firm (1): Feyn65 (LoC "M.I.T. Press").
- **Missing-DOI advisories:** 228 currently verified entries have no `doi` although their
  accepted record carries one. 16 of the 18 newly verifiable entries would add to that count.
  Feyn65 has no DOI (catalogue), and StJaScha13 already cites its DOI.

The PR entries fixed here (Schr03, PigeEtal12, Chom56, Chom65, BauEtal17, Sips13, and
ChenEtal21/SchwEtal22 once their `.eN` pages are corrected) are not in cdl.bib yet. They are
covered by the tests on the frozen PR records.

Checks: full pytest suite 1,387 passed; `verification/benchmark/run.py` `run()` 60/60, with
0 false acceptances and 0 missed matches; `bibcheck.py verify` on cdl.bib prints "looks good!".
