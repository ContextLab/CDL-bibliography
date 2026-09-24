# Applied batches, 2026-09-23/24

Three user-approved batches from the
[resolution plan](../resolution-plan-2026-09-22/README.md), applied with
[`apply.py`](apply.py). Each batch was backed up first (a snapshot export and a
copy of `cdl.bib` under `.bibcheck/apply-2026-09-23/`). The edit batches were
staged first. The staging check asserted that only the batch's field changed,
that every cite key and the entry order were kept, and that
`helpers.check_bib` reported no errors. After that, the batch was applied and
verified with the production pipeline. For the edited keys that pipeline is:
`verify --recheck-cached`, then the `--auto-review` layers (auto-review,
full text, PMC metadata, publisher year, catalogue, preprint, arXiv), then
expanded discovery, the layers again, and a final recheck. A repeat run of the
whole pipeline had to make zero network requests and add zero review rows.
Accepted results outside the batch had to stay identical. The fresh-restore
check (`.bibcheck/validate-current-checkpoint.py`) also had to pass.

| Batch | Entries changed | Verified before / after (batch) | Network requests | Repeat | Library after | Commit |
|-|-|-|-|-|-|-|
| reassess001 | 0 (no BibTeX edit) | stale approvals 12 / 2 | 2 | 0 requests, 0 writes | 3,780 / 2,642 | d72d7c0 |
| droppub001 | 1,027 (`publisher` dropped) | 572 / 708 | 751 + 5 | 0 requests, 0 writes | 3,916 / 2,506 | daea76c |
| adddoi001 | 3,022 (`Doi` added) | 3,022 / 3,022 | 3,039 | 0 requests, 0 writes | 3,916 / 2,506 | 5754a71 |

Library counts are metadata_verified / needs_review, out of 6,422 entries.
The starting point was 3,669 / 2,753. Per-entry statuses are in
`*-results.json`. `*-first-run.json` holds the first run of each batch, before
the fixes described below.

## reassess001: resolver 28 and catalogue policy 7, no edits

- The production offline reassessment (`run_auto_review` with no client)
  verified **121** entries: 110 at article level and 11 catalogue books. These
  are exactly the keys that `measure.py` predicted offline: no key is missing
  and no key was added.
- **Stale approvals (12).** `verify --recheck-cached` and the auto-review
  layers ran on the 12 approvals listed by Phase 0.
  - Reopened (current rules reject them): DesbEtal04, Gold95, GreeStil95,
    HescEtal13b, JoEtal13, MoruMago49, SquiEtal04b, VaidEtal02, Vand00,
    YordKole98.
  - Still verified by the current pipeline: McAdMaun99 and PoldEtal99. Their
    DOI-linked PubMed records supply the missing initials (accepted source
    `europepmc`, 2 network requests).
- **Fix 1: recheck writes.** The first repeat added 2 review rows. The cause
  was that `verify --recheck-cached` appended a new row even when the
  reassessment reproduced the saved result. It now writes only when the result
  differs. Test: `test_recheck_that_reproduces_an_approval_writes_nothing`.
- **Fix 2: snapshot restore.** The fresh restore rejected 35 of the new
  approvals with "Machine approval is missing its source evidence". These were
  print-year (R1) approvals, whose Crossref candidate keeps the
  conflicting-dates finding by design. `import_snapshot` now accepts an
  approval when `valid_print_year_approval` holds. That function re-runs
  `print_year_route` on the cited fields saved in the candidate's evidence.
  Test: `test_print_year_approval_is_a_valid_snapshot_envelope`, with 7
  negative controls.

## droppub001: `publisher` dropped from every @article

- **Entries:** 1,027. This is the same key set as the Phase 0 `drop_publisher`
  list, and all fingerprints still matched when the list was regenerated.
  Before the batch, 572 of these entries were verified and 455 were held.
- **Result:** all 572 verified entries re-verified. **136** held entries became
  verified, which is exactly the Phase 0 prediction (the same 136 keys).
- **Fix 3: print year needs the PubMed lookup.** The first run verified 138
  entries. The two extra were Burw00 and Shim95.
  - They passed the print-year route before any DOI-linked PubMed lookup.
    Freshly re-verified entries skip PubMed when Crossref alone accepts them.
  - Phase 0 had found that PubMed contradicts Shim95.
  - `print_year_route` now also requires a `europepmc` attempt for the DOI,
    because an absent PubMed record counts as "no contradiction" only after
    someone has looked for it.
  - The batch pipeline now rechecks the saved approvals of the batch.
  - Result: 5 more requests. Burw00 and Shim95 are now needs_review.
  - Every other print-year approval in the library already had the lookup.
  - The benchmark stays at 60/60.
- **Evidence tables:** the source-notice table grew from 128 to 130 rows and
  the article-locator table from 293 to 304. Both keep newly found DOI-linked
  negative evidence.

## adddoi001: verified DOIs added

- **Eligibility.** The batch list was regenerated from the current results, not
  taken from the stale Phase 0 `add_doi` list. An entry was eligible when all
  of these held:
  - it is metadata_verified and has no DOI;
  - its accepted DOI has a Crossref record in the evidence;
  - that record's title is not a notice (erratum, correction, retraction and
    similar) and it has no `update-to` or `is-correction-of` link;
  - the record type fits the entry type (`journal-article` for @article);
  - no other DOI matches both title and byline, so it has no APA twin or rival.
- **Skipped (126 in total):**
  - 85 had a twin or rival;
  - 30 had no Crossref record of the accepted DOI;
  - 8 were posted content cited as @article;
  - 3 had a notice-like title.
- **Format.** Each DOI was written as a lowercase bare DOI (`Doi = {...}`),
  inserted at the field's alphabetical position, which is the house formatter's
  order. No added DOI duplicates the DOI of another entry.
- **Result.** All 3,022 entries re-verified on the added DOI, and for every one
  the accepted DOI equals the added DOI. Accepted sources: crossref 2,759,
  europepmc 241, pmc-jats 12, publisher-head 9, catalogue-imprint 1.
- **Fix 4: bookkeeping writes.** The first repeat added 2,723 rows with the
  same statuses. The rows only added `accepted_doi` and `auto_review`, which
  `verify_entry`'s own approvals omit. The pipeline now ends with a recheck. On
  the resumed run and its repeat, both cycles made 0 requests and 0 writes.

## Checks

- **Fresh restore.** After every batch it restored all 6,422 records exactly;
  a repeat import added 0 and SQLite `quick_check` returned ok. The staging
  expectation is now `.bibcheck/apply-2026-09-23/adddoi001-staged.bib`.
  `.bibcheck/` is git-ignored, so the validator change is local only.
- **Benchmark** (`verification/benchmark/run.py`, called through `run()` so
  that `results.json` is not rewritten): 60/60, with 0 false acceptances and
  0 missed matches, after every batch.
- **Full suite:**
  - after reassess001: 1,232 passed;
  - after droppub001: 1,255 passed;
  - after adddoi001: 1,254 passed and 1 failed. The failure is
    `tests/test_pdf_evidence.py::test_published_elsevier_article_passes_with_roles`.
    The test reads HoldEtal00 from the live `cdl.bib`, which now cites
    `10.1016/s0028-3932(99)00099-8`. The 2000 Neuropsychologia PDF does not
    print that DOI, so by design the PDF verifier marks it `absent` and
    abstains. The verifier's rule was not relaxed and the test was not edited;
    this is reported to the owner of the PDF verifier.

## Post-batch measurements (read-only)

[`measure_wrap.py`](measure_wrap.py) runs the Phase 0 and catalogue
measurement scripts unchanged. Their output goes to this folder instead of the
Phase 0 folders. Both scripts open the cache in `mode=ro` and make no network
requests.

Phase 0 ([measure-phase0/](measure-phase0/)), over 2,506 needs_review entries:

- **Verified with no edit:** 0. **Verified after the publisher drop:** 0.
- **Proposals:** 395. By class: S1-TWO-FIELDS-RISKY 80, S1-AUTHOR-NAMES 63,
  TWO-SOURCE 55, S1-PAGES-COMPLETE 47, S1-JOURNAL-HISTORY-OR-TYPO 33,
  S1-TITLE-CROSSREF-ONLY 31, S1-TWO-FIELDS 30, A1b 15, S1-COORDINATES 13,
  S1-TITLE-CORROBORATED 12, S1-AUTHOR-SURNAME 10, S1-JOURNAL-REPLACEMENT 6.
  The reopened stale approvals now appear here as ordinary proposals, except
  YordKole98, which is held.
- **Held:** 2,111.
- **Policy lists:** `drop_publisher` 0; `add_doi` 395 after correction; 126
  verified entries still lack a DOI (the skipped ones above).
- **Regressions among the 3,916 verified entries:** 0.

Catalogue ([measure-catalogue/](measure-catalogue/)):

- **Unresolved book-like entries:** 402, of which 110 have a cached LC search.
- **Outcomes:** 0 verified without an edit, 63 entries with proposals (88
  rows), 339 grouped.
- **Regression:** 46 of 46 verified entries holding LC candidates are kept
  identical.

## Reproduce

```
.venv/bin/python verification/apply-2026-09-23/apply.py {reassess001|droppub001|adddoi001} [--apply]
.venv/bin/python verification/apply-2026-09-23/measure_wrap.py phase0 --out verification/apply-2026-09-23/measure-phase0
.venv/bin/python verification/apply-2026-09-23/measure_wrap.py catalogue --out verification/apply-2026-09-23/measure-catalogue
.venv/bin/python .bibcheck/validate-current-checkpoint.py
```

A second `--apply` resumes from the saved backup (`.bibcheck/apply-2026-09-23/before-BATCH.*`).
