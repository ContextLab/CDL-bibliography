# Catalogue phase 0: widened LC record grammar (2026-09-22)

Scope: plan-books.md R2 (the 87 books whose LC record exists but was rejected)
plus the single-source correction rule from the resolution-plan revision.
Code only. No edits to `cdl.bib`, no writes to `.bibcheck/verification.sqlite3`,
no network requests, nothing committed.

Files changed: `bibcheck/catalogue_review.py`, `bibcheck/catalogue_discovery.py`,
`tests/test_catalogue_review.py`, `tests/test_catalogue_diacritics.py`,
`tests/test_catalogue_year_search.py`. `catalogue_imprint.py` and
`book_editions.json` are unchanged.

## How the widening is contained

- `CATALOGUE_POLICY` is now `"7"`. A normal `catalogue` run re-opens the
  unresolved books; the cached LC searches (retrieved 2026-09-15) are reused
  for 30 days by `fetch_search`.
- `parse_edition()` runs the policy-6 parser (`marc_book`, unchanged) first.
  The widened parser (`marc_book_widened`) runs only when policy 6 rejects a
  record, or when the policy-6 title ends in pre-ISBD `,`/`;` (such a title could
  never match). Every record policy 6 parsed is parsed identically, so the 35
  existing catalogue approvals rebuild byte-for-byte.
- Widened records carry `catalogue_grammar: "7"` and the LC `authority_headings`,
  so each approval shows which grammar produced it.

## Rules added

| Rule | What is accepted | What stays rejected |
|-|-|-|
| a. Dates | 008 type `s`, or `t` with copyright year = publication year; 260/264 `$c` of `Y`, `cY`, `[Y]`, `[cY]`, `©Y`, only when Y = 008 date1 | 008 `r`/`m`/others; `[1966?]`, `[1966-67]`, `1966, c1965`; bracket year ≠ 008 (BishEtal75) |
| b. RDA 264 | exactly one 264 with ind2=1; 264 _2/_3/_4 ignored | two 264_1; 264_0; 260 and 264_1 together |
| c. Two-publisher imprints | ordered (place, publisher) groups; a cited place must belong to the cited publisher's own group | a place of one publisher with the other publisher (Tulv83 OUP + Oxford) |
| d. Distributors | a `$b` group or inline `; distributed by …` clause is dropped | citing the distributor (Crow76 Halsted); a statement with only a distributor |
| e. No 245c | one 100 heading, no 700, no 245c: the heading is the byline | any 700; heading without given names |
| f. Printed names | 245c is the byline; each name pairs with its heading by surname (diacritics ignored only between the two LC fields) and compatible given names/initials in either direction; accents and full names kept verbatim | wrong initial, extra or missing initials against the printed form, `[et al.]`/`and others`, particles or brackets in unheaded names |
| g. Edited volumes | `edited by …` / `editors: …` / `…, editors` with 700 headings (no role or `ed.`/`editor`); an editor-only citation is compared on the full ordered editor list; 111 meeting and 710 sponsor headings allowed for edited volumes; `Contributors:` and foreword/introduction clauses allowed when their 700s have no author/editor role | editors cited as authors; reordered or partial editor lists; 710/711 with an author role; 700 with `$t` |
| Other | 710 with `$5 DLC` (LC copy note); 100/700 `$c` of `Sir`, `Dame` or a parenthesised qualifier; unheaded later co-authors in the simplest form (capitalised given names, one surname word) when the first author has a heading; 008 country codes for NJ, IL, CT, MD, PA, RI, FL, DC and England (`uk`, `england`) under the existing first-place rule | translation/revision clauses or 500 notes (`translat`, `reprint`, `revis`, `originally published`); 776/775/767/765/787/880 related-edition fields; 110 corporate main entry; microform (008/23) |
| Uniqueness | an unparsed record no longer blocks when it provably describes another edition: 008 date1 ≠ cited year (types s/r/t/e), a date range excluding it (m/i/k/q/c/d/u), or a different transcribed title | an unparsed record of the cited year and title still blocks (tested) |

Discovery: `search_query` falls back to the first editor when a book has no
author, and `run_catalogue_review` now includes editor-only books.

Tests: 204 pass in the five owned catalogue test files (152 at HEAD; 52 added).
The new tests in `test_catalogue_review.py` use real cached LC records, trimmed
to the relevant fields with record ids kept and every record of each search
kept, for 30 entries. Negative controls include et al. (RiekEtal97, ConwEtal07),
translations (Semo23, TalaTour88), a reissue (Munn50), another work (DudaEtal01),
an e-book with related editions (Wear16), a different edition (HawkBlak05), and
BishEtal75. LC holds no book-review records, so none appear.

Three existing tests encoded policy-6 limits that plan R2 asks to remove, and
were changed with added negatives:
- Fust05 (heading `Joaquin`, title page `Joaquín`) now verifies; `Joaquin M Fuster`,
  `Joaquím`, `J Fuster`, `M J Fuster` still fail. This is the plan's open
  diagnosis: the cause was the missing accent in the LC heading, not the second
  given name.
- Buzs06 (heading `Buzsáki, G.`, printed `György Buzsáki`) now has a matching
  byline and is blocked only by its address. Conflicting heading initial,
  misspelt heading surname and an editor role still reject.
- Luck05: the real broad search now verifies directly because the 2014 edition
  parses and fails on year, publisher and edition. The refinement tests use a
  derived broad response whose rival is an unparseable record re-dated 2005, so
  refinement is still exercised.

## Measured (offline, `measure.py`)

Baseline: 3,669 verified / 2,753 unresolved. Unresolved book-like entries: 413
(191 incollection, 158 book, 44 inbook, 10 techreport, 7 phdthesis, 2 manual,
1 mastersthesis). 121 have a cached LC search; all are books.

| Outcome | Entries |
|-|-|
| Verified with no edit | 11: Broa58, Fish25, Fish93, Fust05, GreeSwet66, Kaha12, Mall98, Mitc96, Paiv86, Rams07, Torg58 |
| Correction proposals (`proposals.json`, 88 field rows) | 63 |
| Remaining, grouped (`groups.json`) | 339 |

Regression: all 35 currently verified entries holding LC candidates re-assess to
the same accepted record, their stored approvals still pass
`valid_catalogue_approval`, and the accepted candidate is identical. No verified
entry from another source holds LC candidates.

### Proposal classes (one batch decision and one 10-entry spot check each)

A proposal is emitted only when one parsed LC record agrees on ordered surnames
and differs in at most two fields, never year and publisher together, no other
record of the search is equally close, no same-year record is unparsed, and
applying the change makes exactly that record match. After an edit the entry
re-verifies through the normal route; a changed title or first author changes
the LC query, so those need a fresh search.

| Class | Entries | Examples |
|-|-|-|
| P1 publisher: catalogue form of the same firm | 30 | Erlbaum → Lawrence Erlbaum Associates; Wiley → J. Wiley. Alternative decision: keep the cited short form and add a name-form rule in `catalogue_review.py` |
| P2 publisher: a different firm | 6 | Jens80 ERIC → Free Press; Marr82 Henry Holt → W.H. Freeman; MeltMart72 Halsted (distributor) → V. H. Winston |
| T title: complete from the catalogue | 12 | Fodo83 adds subtitle; Free00 brain → brains; Hebb49 adds "The" and subtitle |
| A1 byline from the title page | 8 | Carr93 J D → J B; Murd74 adds Jr.; Kohl40 Köhler; UndeShul60 Shultz → Schulz |
| A2 drop initials the title page does not print | 2 | Badd86, Badd90 A D → A (the LC heading has "Alan D.") |
| E edited volume: author → editor | 8 | HorcDhil04, MiyaShah99, SchaTulv94, TulvDona72 |
| D edition from the catalogue | 4 | RoseRosn91 2, Klin05 2, Howe97 4, Zar10 5 |
| L place: catalogue form | 8 | Tulv83 "New York, {NY}" → "New York"; TulvDona72 Oxford → New York |
| Y year of the only catalogue edition (same publisher) | 2 | Cowa97 1997 → 1995; Luca83 1983 → 1981 |

### Groups (339)

| Group | n | Suggested batch decision |
|-|-|-|
| chapter-no-registry-record | 128 | No decision yet: needs R3 (LC parent-volume search, network) plus a chapter layer |
| chapter-registry-reissue-or-serial | 42 | Keep rejected; serial volumes become booktitle/volume proposals |
| inbook-chapter-title-in-chapter-field | 35 | Apply the recorded inbook → incollection decision as a frozen batch |
| book-no-catalogue-or-registry-hit | 30 | R1 correction batch, then a fresh LC search |
| chapter-registry-name-variant | 21 | One inspected edition binding per volume |
| catalogue-other-editions-only | 14 | Keep as cited pending another source |
| report-or-manual | 12 | PEP route for 4; sign-off for the rest |
| catalogue-reissue-translation-or-microform | 9 | Approve as cited only with title-page evidence |
| catalogue-identity-disagrees | 8 | Per-entry human packet (likely citation defects) |
| catalogue-grammar-unsupported | 8 | One batch sign-off |
| thesis | 8 | Sign-off as cited |
| book-registry-reissue-only | 7 | Keep rejected; LC search or sign-off |
| catalogue-byline-et-al | 5 | Title-page evidence, else sign-off |
| chapter-registry-byline-or-pages-differ | 5 | Per-entry human packet |
| chapter-needs-editor-address-verifier | 4 | Needs the verification.py hooks below |
| catalogue-several-editions | 2 | User picks the edition (Feyn65, Spea27) |
| catalogue-transcription-typo | 1 | Approve as cited (Scha01: LC "Psycholoby Press") |

Non-catalogue groups use the plan's classes from
`verification/resolution-plan-2026-09-22/data/books-coarse.json`.

## Hooks requested in files this work does not own

Specified against the committed HEAD versions.

1. `verification.py compare_record`: fields `editor`, `address` and `chapter`
   always add "no deterministic verifier". Requested: an optional argument
   `extra_evidence={'editor': {...}, 'address': {...}, 'chapter': {...}}`; each
   item is `{'local', 'source', 'match', 'source_name'}` produced by a named
   verifier. The blocker is dropped only when `match` is true and `local` equals
   the cited field. Suppliers:
   - editor: `author_evidence(fields['editor'], parent_editors)` where the
     parents are a Crossref `edited-book` record reached by the chapter's ISBN
     with exactly one result, same title as `booktitle` and same year, or an LC
     parent-volume record (use `catalogue_review.parse_edition` +
     `compare_edition` with `title=booktitle`, which returns `evidence['editor']`);
   - address: the same edition's LC places (`compare_edition` evidence) or
     Crossref `publisher-location` on a record whose year and publisher also match;
   - chapter: a publisher chapter record stating the number, never a DOI suffix.
2. `verification.py compare_record` for `inbook`: when `chapter` is non-numeric,
   compare it with the record title and `title` with `container-title`, and
   expect type `book-chapter`. Not needed if the recorded inbook → incollection
   conversion is applied first.
3. `auto_review.py reassess`: `reassess_saved_catalogue` replaces the result
   whenever LC candidates exist, even when another source verified the entry.
   0 entries are affected today (measured). Requested guard: replace only when
   the previous status is not `metadata_verified` from another source, or when
   the catalogue result verifies.
4. Chapters, R3 volume layer: `catalogue_review.compare_edition(fields, record, xml)`
   is ready to compare a parent volume (pass `title=booktitle`, `editor`,
   `publisher`, `address`, `year`). The search step needs a `run_catalogue_review`
   variant for incollection entries that searches by booktitle and first editor
   (network); that runner can stay in `catalogue_review.py`.

## Reproduce

```
.venv/bin/python verification/catalogue-phase0-2026-09-22/measure.py
.venv/bin/python -m pytest -q tests/test_catalogue_review.py tests/test_catalogue_diacritics.py \
    tests/test_catalogue_discovery.py tests/test_catalogue_imprint.py tests/test_catalogue_year_search.py
```
