# Spot-check fixes to the correction proposals, 2026-09-24

The user's first spot-check verdicts are recorded in
[../resolution-plan-2026-09-22/README.md](../resolution-plan-2026-09-22/README.md#spot-check-findings-2026-09-24-first-9-verdicts).
This folder regenerates the Phase 0 proposals under the fixed rules. It covers the
post-batch library (3,916 verified / 2,506 needs_review) and compares the result with the
post-batch Phase 0 measurement in
[../apply-2026-09-23/measure-phase0/](../apply-2026-09-23/measure-phase0/).
`cdl.bib` and `.bibcheck/verification.sqlite3` were not modified.

## Rules changed

| Rule | Code |
|-|-|
| Author after-values use house form. Initials have no periods. Every initial the source gives is kept (`M E Smith`, `D C Young`, `N B Turk-Browne`), and hyphenated initials stay (`M-M`, `Y-C`). The citation's own surname text is kept when it differs from the source's only by case or braces (`{van Bruggen}`). Every name is round-tripped through the BibTeX name parser. The rule holds (does not propose) when the source gives an all-capital surname, a lower-case given-name token (a particle), a suffix inside the given names, or undotted capitals such as `JR`. This applies to every generator that writes `author`: S1, `field_proposal`, the combined generator, PubMed suffixes, PMC given names and publisher bylines. | `correction_proposals.house_given`, `house_byline`, `source_authors` |
| When an issue is written because a cited `volume(issue)` is split or `number` changes, a source must state it. The accepted sources are Crossref, the DOI-linked PubMed record, or a lookup: PubMed E-utilities (by DOI, then by ecitmatch), then the publisher. For Elsevier the publisher source is the article API (`prism:issueIdentifier`); for other publishers it is the landing page's `citation_issue`, used only when that page states the same DOI. If a lookup finds no statement, the issue is dropped. If no lookup was made, the entry is held (`issue-lookup-required`). If sources disagree, or the stated issue is not a plain number (`1-2`, `Supp`, `0 2`), the entry is held. An issue confirmed only by a lookup source the resolver cannot verify against is also held (`issue-confirmed-outside-resolver`). It is never dropped. | `correction_proposals.confirm_issue`, `publisher_corrections.issue_lookup` |
| When the corrected citation has no `number`, and Crossref or PubMed states one plain issue that the other does not contradict, the issue is added. The edited entry must still verify on the same DOI. This follows the SmitHalg89 verdict, "add number (1)". | `correction_proposals.complete_issue` |
| Every after-value must be stated by a source record for the proposal's DOI: Crossref, PubMed, PMC JATS, or a stored lookup. A deletion must not remove a value that a source states. Violations are withheld. Each proposal records `stated_by`, `field_sources` and `issue_evidence`. | `correction_proposals.after_value_statements` |
| LaTeX accent arguments (`\'{e}`) are no longer read as case-protecting braces. RacsEtal08 was being held on that false positive. | `correction_proposals._braced_words` |

## The five spot-check keys

| Key | Before | Now |
|-|-|-|
| AlyTurk16 | Mariam Aly and Nicholas B Turk-Browne | M Aly and N B Turk-Browne; pages e420--e429 (PubMed) |
| SmitHalg89 | Michael E Smith and Eric Halgren | M E Smith and E Halgren; number 1 added (Crossref) |
| Youn79 | David C Young | D C Young; number 6 added (Crossref) |
| Murd71 | volume 10, number 4 | unchanged: Crossref states issue 4 |
| Hint03 | volume 10, number 1 | unchanged: Crossref and PubMed state issue 1 |

**Needs the user's decision: Murd71 and Hint03.** The user found no issue number at the DOI
address. The sources do state one. Crossref gives issue 4 and issue 1; PubMed 12747488
gives issue 1. Springer's landing pages carry `citation_issue` 4 and 1 in their metadata.
These were fetched on 2026-09-24 and are stored in `cases.json.gz`. Springer's visible
"Cite this article" line leaves issue numbers out for every article, so the numbers are
not shown on the page. Under the recorded decision (a Crossref, PubMed or `citation_issue`
statement is enough), both keep their number. If the rule should instead be "the issue must
appear in the publisher's visible citation", that is a different decision. It would drop the
issue from every Springer/Psychonomic citation.

## Outcome (`measure.py`)

Over the 2,506 needs_review entries: **440 proposals** (395 before) and 2,066 held. Zero
regressions among the verified entries. `diff.json` lists every change per key.

| Class | Unchanged | Changed | New | Withdrawn |
|-|-|-|-|-|
| S1-AUTHOR-NAMES | 3 | 59 | 3 | 1 |
| S1-TWO-FIELDS-RISKY | 64 | 16 | 7 | 0 |
| TWO-SOURCE | 36 | 19 | 28 | 0 |
| S1-TITLE-CROSSREF-ONLY | 13 | 18 | 0 | 0 |
| S1-AUTHOR-SURNAME | 0 | 10 | 0 | 0 |
| S1-TWO-FIELDS | 20 | 10 | 0 | 0 |
| S1-JOURNAL-HISTORY-OR-TYPO | 26 | 7 | 0 | 0 |
| S1-TITLE-CORROBORATED | 9 | 3 | 0 | 0 |
| S1-JOURNAL-REPLACEMENT | 5 | 1 | 0 | 0 |
| S1-COORDINATES | 13 | 0 | 8 | 0 |
| S1-PAGES-COMPLETE | 47 | 0 | 0 | 0 |
| A1b-ARTICLE-NUMBER | 15 | 0 | 0 | 0 |

Classes are the pre-fix classes; `proposals.json` has the new classes. The 143 changed
proposals break down as follows:

- 105 changed the author value to house form.
- 94 gained an issue number that a source states. Some proposals changed in both ways.

The new proposals fall into three groups:

- 28 two-source author repairs. Crossref and PubMed now agree on the initials; the full
  names did not match PubMed's initials. Some of these reorder or add authors
  (GeviEtal99, Koun94, Lang01, WhitWang83), so each belongs in a spot-check.
- 13 proposals that drop a citation-only issue after a lookup (8 in S1-COORDINATES).
- A few author repairs, suffixes among them, that the old full-name values blocked.

WuEtal01 was withdrawn: its proposal carried Crossref's garbled "RMark", and it is now held.

**Issue lookups** (`lookups.json`): 15 DOIs.

| Result | DOIs |
|-|-|
| Confirmed | 0 |
| Dropped: no source states the issue | 14 |
| Held: PubMed issue "0 2" (EkstWatr14) | 1 |

For 13 of the 14 dropped DOIs, PubMed or the publisher returned the work with no issue. The
cited values included "October", "SUPPL.", "2000", "December 2016" and "3-17". CohnEtal96's
publisher page (jair.org) could not be fetched.

The measurement runs made 107 requests through `PoliteClient` (the lookup code changed twice
between runs), cached in `.bibcheck/fixes-2026-09-24.sqlite3`; exploratory checks made 26
more. A repeat run (`--offline`) makes 0.

**Audit of the pre-fix proposals** (`audit_baseline.py` → `baseline-audit.json`):

- 0 after-values that no source states. All 93 issue values were stated by Crossref or
  PubMed.
- 106 author values not in house form.

The "number" findings came from Springer's display, not from a value carried over from the
citation.

## Outside this folder's files

- `tests/test_pmc_corrections.py::test_missing_given_name_is_added_only_when_both_sources_supply_it`
  expects `Alice B Smith`; it now gets `A B Smith`.
- `tests/test_pubmed_suffixes.py::test_suffix_correction_can_use_suffix_present_in_both_sources`
  expects `Smith, Jr, Alice`; it now gets `Smith, Jr, A`.
- Both tests encode the full-name form that the user's decision replaced.
- Catalogue proposals (`bibcheck/catalogue_*.py`): vandGlas00's editor value "Wim J van der
  Linden and Cees A W Glas" is not in house form. The other catalogue bylines already use
  initials.

## Reproduce

```
.venv/bin/python verification/fixes-2026-09-24/measure.py [--workers 8] [--offline]
.venv/bin/python verification/fixes-2026-09-24/audit_baseline.py
.venv/bin/python verification/fixes-2026-09-24/build_cases.py   # test fixture cases.json.gz
```
